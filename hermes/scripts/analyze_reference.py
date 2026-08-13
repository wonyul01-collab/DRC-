#!/usr/bin/env python3
"""벤치마크 채널 실측 분석 — reference-style.yaml 의 추정값을 실제 숫자로 바꾼다.

YouTube Data API v3 만 씁니다. 웹 스크래핑이 아니라서 차단 없이 동작하고,
읽기 전용 API 키만 있으면 됩니다 (업로드용 OAuth 와 별개).

API 키 발급 (2분, 무료):
  Google Cloud Console → API 및 서비스 → 사용자 인증 정보
  → 사용자 인증 정보 만들기 → API 키
  → YouTube Data API v3 가 사용 설정되어 있어야 합니다.
  할당량은 하루 10,000 유닛이고 이 스크립트는 한 번에 20 유닛도 안 씁니다.

사용 예:
  export YOUTUBE_API_KEY="AIza..."
  python analyze_reference.py --handle "@진짜잠깐만" --max 200
  python analyze_reference.py --handle "@진짜잠깐만" --out ref-data.json --calibrate
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime
from pathlib import Path

API = "https://www.googleapis.com/youtube/v3"

# API 키를 찾는 순서. 위에서부터 먼저 발견되는 것을 씁니다.
#   1) --key-file 로 직접 지정한 파일
#   2) YOUTUBE_API_KEY 환경변수
#   3) 아래 후보 경로들 (메모장으로 만들어 두면 됩니다)
KEY_FILENAME = "youtube_api_key.txt"

# 제목에서 후킹 유형을 추정하는 규칙. 분석 노트의 4분류를 그대로 쓴다.
HOOK_PATTERNS = [
    # 순서가 중요합니다. 위에서부터 먼저 걸리는 규칙이 이깁니다.
    ("라이벌대결형", r"\bvs\b|대결|누가\s*더|누가\s*이|이길까|승부|맞붙|붙으면"),
    ("기발한가설형", r"만약|했더니|가능할까|[가-힣]까\?|실험|도전|해봤|달면|넣으면|쏘면"),
    ("Pain-Point형", r"방법|꿀팁|해결|사기템|이것만|알면|하는\s*법|없애는|펴는"),
    ("충격선언형", r"충격|경악|실화|근황|저지르|수준|실태|폭로|난리|짓"),
]


def hermes_home() -> Path:
    """Hermes 설치 위치. 네이티브 Windows 와 그 외를 모두 본다."""
    env = os.environ.get("HERMES_HOME")
    if env:
        return Path(env).expanduser()
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "hermes"
    return Path.home() / ".hermes"


def key_file_candidates() -> list[Path]:
    """키 파일을 찾아볼 위치들. 첫 번째가 권장 위치."""
    here = Path(__file__).resolve().parent
    return [
        hermes_home() / "secrets" / KEY_FILENAME,
        here / KEY_FILENAME,
        Path.cwd() / KEY_FILENAME,
    ]


def read_key_file(path: Path) -> str | None:
    """키 파일에서 값을 뽑는다. 메모장이 남기는 BOM·따옴표·주석을 걷어낸다."""
    try:
        # utf-8-sig: 메모장이 UTF-8로 저장하면 앞에 BOM이 붙는데 그걸 제거한다.
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # YOUTUBE_API_KEY=AIza... 형식도 받아준다
        if "=" in line and line.split("=", 1)[0].strip().upper().endswith("API_KEY"):
            line = line.split("=", 1)[1].strip()
        line = line.strip().strip('"').strip("'").strip()
        if line:
            return line
    return None


def load_api_key(explicit_file: str | None) -> str:
    if explicit_file:
        path = Path(explicit_file).expanduser()
        key = read_key_file(path)
        if not key:
            sys.exit(f"키 파일에서 값을 읽지 못했습니다: {path}")
        return key

    env_key = os.environ.get("YOUTUBE_API_KEY", "").strip()
    if env_key:
        return env_key

    for path in key_file_candidates():
        key = read_key_file(path)
        if key:
            print(f"키 파일 사용: {path}", file=sys.stderr)
            return key

    listed = "\n".join(f"      {p}" for p in key_file_candidates())
    sys.exit(
        "API 키를 찾지 못했습니다.\n\n"
        "  가장 쉬운 방법 — 키 파일을 만드세요:\n"
        f"      python {Path(__file__).name} --setup\n\n"
        "  그러면 메모장이 열립니다. 키를 붙여넣고 저장하면 끝입니다.\n\n"
        "  아래 위치 중 아무 곳에나 직접 만드셔도 됩니다:\n"
        f"{listed}\n\n"
        "  또는 환경변수로:\n"
        '      PowerShell:  $env:YOUTUBE_API_KEY = "AIza..."\n'
        '      WSL/Linux :  export YOUTUBE_API_KEY="AIza..."'
    )


def cmd_setup() -> None:
    """키 파일을 만들고 편집기로 열어준다."""
    target = key_file_candidates()[0]
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists() and read_key_file(target):
        print(f"이미 키가 들어 있습니다: {target}")
        print("바꾸시려면 그 파일을 직접 여세요.")
        return

    if not target.exists():
        target.write_text(
            "# 이 줄 아래에 YouTube Data API 키를 붙여넣고 저장하세요.\n"
            "# '#' 으로 시작하는 줄은 무시됩니다. 따옴표는 붙이지 않아도 됩니다.\n"
            "\n",
            encoding="utf-8",
        )
        try:
            target.chmod(0o600)          # 소유자만 읽기 (Windows 에서는 무시됨)
        except OSError:
            pass

    print(f"키 파일을 만들었습니다:\n    {target}\n")
    print("여기에 키를 붙여넣고 저장한 뒤, 분석을 다시 실행하세요.")

    opened = False
    try:
        if sys.platform == "win32":
            os.startfile(str(target))    # type: ignore[attr-defined]
            opened = True
        elif shutil.which("wslview"):    # WSL2 에서 Windows 기본 앱으로 열기
            subprocess.Popen(["wslview", str(target)])
            opened = True
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target)])
            opened = True
    except Exception:
        opened = False

    if not opened:
        print("\n편집기를 자동으로 열지 못했습니다. 위 경로의 파일을 직접 여세요.")


def api_get(endpoint: str, params: dict, key: str) -> dict:
    params = {**params, "key": key}
    url = f"{API}/{endpoint}?{urllib.parse.urlencode(params)}"
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        sys.exit(f"API 오류 {exc.code} ({endpoint}):\n{body[:800]}")
    except urllib.error.URLError as exc:
        sys.exit(f"네트워크 오류 ({endpoint}): {exc.reason}")


def parse_duration(iso: str) -> int:
    """PT1M23S → 83 (초)."""
    m = re.fullmatch(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso or "")
    if not m:
        return 0
    h, mi, s = (int(g) if g else 0 for g in m.groups())
    return h * 3600 + mi * 60 + s


def resolve_channel(handle: str, key: str) -> dict:
    handle = urllib.parse.unquote(handle)
    if not handle.startswith("@"):
        handle = "@" + handle
    data = api_get("channels", {
        "part": "snippet,statistics,contentDetails",
        "forHandle": handle,
    }, key)
    items = data.get("items") or []
    if not items:
        sys.exit(f"채널을 찾을 수 없습니다: {handle}\n"
                 "핸들이 정확한지 확인하세요 (유튜브 채널 주소의 @ 뒤 부분).")
    return items[0]


def fetch_video_ids(uploads_playlist: str, key: str, limit: int) -> list[str]:
    ids: list[str] = []
    token = None
    while len(ids) < limit:
        params = {"part": "contentDetails", "playlistId": uploads_playlist,
                  "maxResults": 50}
        if token:
            params["pageToken"] = token
        data = api_get("playlistItems", params, key)
        for item in data.get("items", []):
            vid = item.get("contentDetails", {}).get("videoId")
            if vid:
                ids.append(vid)
        token = data.get("nextPageToken")
        if not token:
            break
    return ids[:limit]


def fetch_videos(ids: list[str], key: str) -> list[dict]:
    out: list[dict] = []
    for i in range(0, len(ids), 50):
        data = api_get("videos", {
            "part": "snippet,contentDetails,statistics",
            "id": ",".join(ids[i:i + 50]),
        }, key)
        for v in data.get("items", []):
            stats = v.get("statistics", {})
            snip = v.get("snippet", {})
            out.append({
                "id": v["id"],
                "title": snip.get("title", ""),
                "description": snip.get("description", ""),
                "tags": snip.get("tags", []),
                "published_at": snip.get("publishedAt", ""),
                "duration_seconds": parse_duration(v.get("contentDetails", {}).get("duration", "")),
                "views": int(stats.get("viewCount", 0)),
                "likes": int(stats.get("likeCount", 0)),
                "comments": int(stats.get("commentCount", 0)),
            })
    return out


def classify_hook(title: str) -> str:
    for name, pattern in HOOK_PATTERNS:
        if re.search(pattern, title, re.IGNORECASE):
            return name
    return "미분류"


def summarize(channel: dict, videos: list[dict]) -> dict:
    shorts = [v for v in videos if v["duration_seconds"] <= 60]
    longs = [v for v in videos if v["duration_seconds"] > 60]
    pool = shorts or videos

    durations = sorted(v["duration_seconds"] for v in pool)
    views = sorted(v["views"] for v in pool)
    title_lens = [len(v["title"]) for v in pool]

    def pct(data: list[int], p: float) -> float:
        if not data:
            return 0.0
        idx = min(len(data) - 1, int(len(data) * p))
        return float(data[idx])

    hooks = Counter(classify_hook(v["title"]) for v in pool)

    # 업로드 주기
    dates = sorted(v["published_at"][:10] for v in pool if v["published_at"])
    cadence = None
    if len(dates) >= 2:
        d0 = datetime.fromisoformat(dates[0])
        d1 = datetime.fromisoformat(dates[-1])
        days = max(1, (d1 - d0).days)
        cadence = round(len(dates) / days * 7, 1)

    tag_counts = Counter(t for v in pool for t in v["tags"]).most_common(15)
    top = sorted(pool, key=lambda v: v["views"], reverse=True)[:10]

    return {
        "channel": {
            "title": channel["snippet"]["title"],
            "handle": channel["snippet"].get("customUrl", ""),
            "subscribers": int(channel["statistics"].get("subscriberCount", 0)),
            "total_videos": int(channel["statistics"].get("videoCount", 0)),
            "total_views": int(channel["statistics"].get("viewCount", 0)),
            "description": channel["snippet"].get("description", "")[:500],
        },
        "sample": {
            "analyzed": len(videos),
            "shorts": len(shorts),
            "long_form": len(longs),
        },
        "duration_seconds": {
            "min": durations[0] if durations else 0,
            "p25": pct(durations, 0.25),
            "median": statistics.median(durations) if durations else 0,
            "p75": pct(durations, 0.75),
            "max": durations[-1] if durations else 0,
        },
        "views": {
            "median": statistics.median(views) if views else 0,
            "p90": pct(views, 0.90),
            "max": views[-1] if views else 0,
        },
        "title_length": {
            "median": statistics.median(title_lens) if title_lens else 0,
            "max": max(title_lens) if title_lens else 0,
        },
        "hook_types": hooks.most_common(),
        "uploads_per_week": cadence,
        "top_tags": tag_counts,
        "top_videos": [
            {"title": v["title"], "views": v["views"],
             "duration_seconds": v["duration_seconds"], "hook": classify_hook(v["title"]),
             "url": f"https://youtu.be/{v['id']}"}
            for v in top
        ],
    }


def calibration_hints(summary: dict) -> list[str]:
    """reference-style.yaml 에 그대로 넣을 수 있는 값 제안."""
    d = summary["duration_seconds"]
    hooks = summary["hook_types"]
    hints = [
        f"structure.total_seconds: [{int(d['p25'])}, {int(d['p75'])}]"
        f"   # 중앙값 {int(d['median'])}초, 전체 {int(d['min'])}~{int(d['max'])}초",
        f"hooking.opening_caption.max_chars: {int(summary['title_length']['median'])}"
        f"   # 제목 길이 중앙값 기준. 자막은 보통 제목보다 짧게 간다",
    ]
    if hooks:
        top_hook, count = hooks[0]
        total = sum(c for _, c in hooks)
        hints.append(
            f"hooking.types 우선순위: {top_hook} (표본의 {count}/{total})"
            f"   # frequency 를 이 비율에 맞춰 high/medium/low 로 조정"
        )
    if summary["uploads_per_week"]:
        hints.append(f"cadence.videos_per_week: {summary['uploads_per_week']}   # 벤치마크 채널 실측")
    unclassified = dict(hooks).get("미분류", 0)
    if unclassified and hooks:
        share = unclassified / sum(c for _, c in hooks)
        if share > 0.35:
            hints.append(
                f"⚠ 제목의 {share:.0%} 가 미분류입니다. HOOK_PATTERNS 규칙이 이 채널과 안 맞거나, "
                "노트의 4분류 외에 다른 유형이 있습니다. top_videos 제목을 직접 읽어보세요."
            )
    return hints


def main() -> None:
    parser = argparse.ArgumentParser(description="벤치마크 채널 실측 분석")
    parser.add_argument("--setup", action="store_true",
                        help="API 키를 넣을 파일을 만들고 편집기로 연다 (처음 한 번만)")
    parser.add_argument("--handle", help='채널 핸들 (예: "@진짜잠깐만")')
    parser.add_argument("--max", type=int, default=200, help="분석할 최대 영상 수 (기본 200)")
    parser.add_argument("--out", help="전체 결과를 저장할 JSON 경로")
    parser.add_argument("--key-file", help="API 키가 든 파일 경로 (직접 지정할 때만)")
    parser.add_argument("--calibrate", action="store_true",
                        help="reference-style.yaml 에 넣을 값 제안까지 출력")
    args = parser.parse_args()

    if args.setup:
        cmd_setup()
        return
    if not args.handle:
        parser.error('--handle 이 필요합니다. 예: --handle "@진짜잠깐만"')

    key = load_api_key(args.key_file)

    channel = resolve_channel(args.handle, key)
    uploads = channel["contentDetails"]["relatedPlaylists"]["uploads"]
    ids = fetch_video_ids(uploads, key, args.max)
    if not ids:
        sys.exit("영상을 가져오지 못했습니다. 채널이 비공개이거나 업로드가 없습니다.")
    videos = fetch_videos(ids, key)
    summary = summarize(channel, videos)

    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.calibrate:
        print("\n=== reference-style.yaml 보정 제안 ===", file=sys.stderr)
        for hint in calibration_hints(summary):
            print(f"  {hint}", file=sys.stderr)

    if args.out:
        payload = {"summary": summary, "videos": videos}
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        print(f"\n전체 데이터 저장: {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
