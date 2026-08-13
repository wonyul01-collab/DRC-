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
import statistics
import sys
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime

API = "https://www.googleapis.com/youtube/v3"

# 제목에서 후킹 유형을 추정하는 규칙. 분석 노트의 4분류를 그대로 쓴다.
HOOK_PATTERNS = [
    # 순서가 중요합니다. 위에서부터 먼저 걸리는 규칙이 이깁니다.
    ("라이벌대결형", r"\bvs\b|대결|누가\s*더|누가\s*이|이길까|승부|맞붙|붙으면"),
    ("기발한가설형", r"만약|했더니|가능할까|[가-힣]까\?|실험|도전|해봤|달면|넣으면|쏘면"),
    ("Pain-Point형", r"방법|꿀팁|해결|사기템|이것만|알면|하는\s*법|없애는|펴는"),
    ("충격선언형", r"충격|경악|실화|근황|저지르|수준|실태|폭로|난리|짓"),
]


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
    parser.add_argument("--handle", required=True, help='채널 핸들 (예: "@진짜잠깐만")')
    parser.add_argument("--max", type=int, default=200, help="분석할 최대 영상 수 (기본 200)")
    parser.add_argument("--out", help="전체 결과를 저장할 JSON 경로")
    parser.add_argument("--calibrate", action="store_true",
                        help="reference-style.yaml 에 넣을 값 제안까지 출력")
    args = parser.parse_args()

    key = os.environ.get("YOUTUBE_API_KEY")
    if not key:
        sys.exit("YOUTUBE_API_KEY 환경변수가 없습니다.\n"
                 '  export YOUTUBE_API_KEY="AIza..."\n'
                 "발급: Google Cloud Console → 사용자 인증 정보 → API 키")

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
