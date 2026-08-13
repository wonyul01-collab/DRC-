#!/usr/bin/env python3
"""YouTube 업로드 CLI — Hermes 에이전트가 shell 툴로 호출하는 용도.

기본값은 항상 비공개(private) 업로드입니다. 사람이 검수한 뒤
`--privacy public` 또는 예약공개로 바꿔서 다시 올리거나 스튜디오에서 공개하세요.

사용 예:
  # 최초 1회 브라우저 인증
  python youtube_upload.py auth

  # 업로드
  python youtube_upload.py upload \
      --file out/2026-08-13-shorts.mp4 \
      --title "3분 만에 끝내는 엑셀 단축키 5개" \
      --description-file out/2026-08-13-shorts.txt \
      --tags 엑셀,단축키,직장인 \
      --synthetic \
      --privacy private

  # 썸네일 (채널 인증 필요)
  python youtube_upload.py thumbnail --video-id XXXX --file out/thumb.jpg
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

# 업로드와 성과 조회가 토큰 하나를 공유하도록 스코프를 한 곳에 모아둡니다.
# 여기를 바꾸면 기존 토큰은 무효가 되므로 `auth` 를 다시 실행해야 합니다.
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/yt-analytics.readonly",
]

# 업로드 도중 끊겼을 때 재시도해도 되는 HTTP 상태
RETRIABLE_STATUS = {500, 502, 503, 504}
MAX_RETRIES = 8


def _path_from_env(var: str, default: str) -> Path:
    return Path(os.environ.get(var, default)).expanduser()


def _client_secrets() -> Path:
    p = _path_from_env("YOUTUBE_CLIENT_SECRETS", "~/.hermes/secrets/youtube_client_secret.json")
    if not p.is_file():
        sys.exit(
            f"client_secret 파일이 없습니다: {p}\n"
            "Google Cloud Console → API 및 서비스 → 사용자 인증 정보에서 "
            "'데스크톱 앱' OAuth 클라이언트를 만들어 JSON을 내려받고, "
            "YOUTUBE_CLIENT_SECRETS 환경변수에 경로를 지정하세요."
        )
    return p


def _token_store() -> Path:
    return _path_from_env("YOUTUBE_TOKEN_STORE", "~/.hermes/secrets/youtube_token.json")


def get_credentials(interactive: bool = False) -> Credentials:
    """저장된 토큰을 쓰고, 없거나 만료됐으면 갱신/재인증한다."""
    store = _token_store()
    creds: Credentials | None = None

    if store.is_file():
        creds = Credentials.from_authorized_user_file(str(store), SCOPES)

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
    else:
        if not interactive:
            sys.exit(
                "유효한 YouTube 인증 토큰이 없습니다. "
                "먼저 `python youtube_upload.py auth` 를 한 번 실행하세요."
            )
        flow = InstalledAppFlow.from_client_secrets_file(str(_client_secrets()), SCOPES)
        # 헤드리스 서버에서도 되도록 브라우저를 자동으로 열지 않고 URL만 출력한다.
        creds = flow.run_local_server(port=0, open_browser=False)

    store.parent.mkdir(parents=True, exist_ok=True)
    store.write_text(creds.to_json())
    store.chmod(0o600)
    return creds


def youtube_client(interactive: bool = False):
    return build("youtube", "v3", credentials=get_credentials(interactive), cache_discovery=False)


def cmd_auth(_args: argparse.Namespace) -> None:
    get_credentials(interactive=True)
    print(f"인증 완료. 토큰 저장 위치: {_token_store()}")


def cmd_upload(args: argparse.Namespace) -> None:
    video = Path(args.file).expanduser()
    if not video.is_file():
        sys.exit(f"영상 파일이 없습니다: {video}")

    description = args.description or ""
    if args.description_file:
        description = Path(args.description_file).expanduser().read_text(encoding="utf-8")

    if len(args.title) > 100:
        sys.exit(f"제목이 100자를 넘습니다 ({len(args.title)}자). YouTube 제한입니다.")
    if len(description) > 5000:
        sys.exit(f"설명이 5000자를 넘습니다 ({len(description)}자). YouTube 제한입니다.")

    tags = [t.strip() for t in (args.tags or "").split(",") if t.strip()]

    status: dict[str, object] = {
        "privacyStatus": args.privacy,
        "selfDeclaredMadeForKids": args.made_for_kids,
    }
    if args.publish_at:
        # 예약 공개는 privacyStatus 가 private 여야 동작합니다.
        status["privacyStatus"] = "private"
        status["publishAt"] = args.publish_at
    if args.synthetic:
        # AI로 생성/변형한 사실적 콘텐츠는 공시 의무가 있습니다.
        status["containsSyntheticMedia"] = True

    body = {
        "snippet": {
            "title": args.title,
            "description": description,
            "tags": tags,
            "categoryId": args.category_id,
            "defaultLanguage": args.language,
            "defaultAudioLanguage": args.language,
        },
        "status": status,
    }

    yt = youtube_client()
    media = MediaFileUpload(str(video), chunksize=-1, resumable=True)
    request = yt.videos().insert(part="snippet,status", body=body, media_body=media)

    response = None
    attempt = 0
    while response is None:
        try:
            _, response = request.next_chunk()
        except HttpError as exc:
            if exc.resp.status in RETRIABLE_STATUS and attempt < MAX_RETRIES:
                attempt += 1
                sleep_for = 2**attempt
                print(f"일시 오류 {exc.resp.status}, {sleep_for}초 후 재시도 ({attempt}/{MAX_RETRIES})", file=sys.stderr)
                time.sleep(sleep_for)
                continue
            raise

    video_id = response["id"]
    result = {
        "video_id": video_id,
        "url": f"https://youtu.be/{video_id}",
        "studio_url": f"https://studio.youtube.com/video/{video_id}/edit",
        "privacy": response.get("status", {}).get("privacyStatus"),
        "publish_at": response.get("status", {}).get("publishAt"),
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_thumbnail(args: argparse.Namespace) -> None:
    thumb = Path(args.file).expanduser()
    if not thumb.is_file():
        sys.exit(f"썸네일 파일이 없습니다: {thumb}")
    yt = youtube_client()
    yt.thumbnails().set(videoId=args.video_id, media_body=MediaFileUpload(str(thumb))).execute()
    print(json.dumps({"video_id": args.video_id, "thumbnail": "set"}, ensure_ascii=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="YouTube 업로드 CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("auth", help="브라우저 OAuth 인증 (최초 1회)").set_defaults(func=cmd_auth)

    up = sub.add_parser("upload", help="영상 업로드")
    up.add_argument("--file", required=True, help="업로드할 영상 파일")
    up.add_argument("--title", required=True, help="제목 (최대 100자)")
    up.add_argument("--description", help="설명 문자열")
    up.add_argument("--description-file", help="설명을 담은 텍스트 파일 (--description 보다 우선)")
    up.add_argument("--tags", help="쉼표로 구분한 태그")
    up.add_argument("--category-id", default="22", help="YouTube 카테고리 ID (기본 22=People & Blogs)")
    up.add_argument("--language", default="ko", help="기본 언어 코드")
    up.add_argument(
        "--privacy",
        default="private",
        choices=["private", "unlisted", "public"],
        help="공개 범위 (기본 private — 사람이 검수한 뒤 공개하세요)",
    )
    up.add_argument("--publish-at", help="예약 공개 시각 (RFC3339, 예: 2026-08-15T09:00:00Z)")
    up.add_argument("--made-for-kids", action="store_true", help="아동용 콘텐츠로 신고")
    up.add_argument(
        "--synthetic",
        action="store_true",
        help="AI 생성/변형된 사실적 콘텐츠임을 공시 (status.containsSyntheticMedia)",
    )
    up.set_defaults(func=cmd_upload)

    th = sub.add_parser("thumbnail", help="썸네일 설정 (채널 인증 필요)")
    th.add_argument("--video-id", required=True)
    th.add_argument("--file", required=True)
    th.set_defaults(func=cmd_thumbnail)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
