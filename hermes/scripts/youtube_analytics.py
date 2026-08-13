#!/usr/bin/env python3
"""YouTube 성과 조회 CLI — Hermes 가 주간 리뷰 cron 에서 호출합니다.

youtube_upload.py 와 같은 토큰(YOUTUBE_TOKEN_STORE)을 씁니다.
따라서 먼저 `python youtube_upload.py auth` 를 한 번 실행해야 합니다.

사용 예:
  # 최근 28일 채널 요약
  python youtube_analytics.py channel --days 28

  # 최근 28일 영상별 성과 상위 20개
  python youtube_analytics.py videos --days 28 --limit 20

  # 트래픽 소스별
  python youtube_analytics.py traffic --days 28
"""

from __future__ import annotations

import argparse
import datetime as dt
import json

from googleapiclient.discovery import build

from youtube_upload import get_credentials

# 조회수/시청시간/구독자 증감/노출 대비 클릭률 — 다음 기획을 정하는 데 쓰는 최소 지표
CHANNEL_METRICS = (
    "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,"
    "subscribersGained,subscribersLost,likes,comments,shares"
)
VIDEO_METRICS = (
    "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,"
    "subscribersGained,likes,comments"
)


def analytics_client():
    return build("youtubeAnalytics", "v2", credentials=get_credentials(), cache_discovery=False)


def date_range(days: int) -> tuple[str, str]:
    # Analytics 데이터는 하루 이틀 지연되므로 어제까지를 끝으로 잡습니다.
    end = dt.date.today() - dt.timedelta(days=1)
    start = end - dt.timedelta(days=days - 1)
    return start.isoformat(), end.isoformat()


def as_records(response: dict) -> list[dict]:
    """Analytics 응답의 columnHeaders + rows 를 dict 리스트로 바꿉니다."""
    headers = [h["name"] for h in response.get("columnHeaders", [])]
    return [dict(zip(headers, row)) for row in response.get("rows", [])]


def run_query(**kwargs) -> list[dict]:
    return as_records(analytics_client().reports().query(ids="channel==MINE", **kwargs).execute())


def cmd_channel(args: argparse.Namespace) -> None:
    start, end = date_range(args.days)
    rows = run_query(startDate=start, endDate=end, metrics=CHANNEL_METRICS)
    print(json.dumps({"period": [start, end], "totals": rows[0] if rows else {}}, ensure_ascii=False, indent=2))


def cmd_videos(args: argparse.Namespace) -> None:
    start, end = date_range(args.days)
    rows = run_query(
        startDate=start,
        endDate=end,
        metrics=VIDEO_METRICS,
        dimensions="video",
        sort="-views",
        maxResults=args.limit,
    )
    print(json.dumps({"period": [start, end], "videos": rows}, ensure_ascii=False, indent=2))


def cmd_traffic(args: argparse.Namespace) -> None:
    start, end = date_range(args.days)
    rows = run_query(
        startDate=start,
        endDate=end,
        metrics="views,estimatedMinutesWatched",
        dimensions="insightTrafficSourceType",
        sort="-views",
    )
    print(json.dumps({"period": [start, end], "traffic": rows}, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="YouTube 성과 조회 CLI")
    # --days 를 서브커맨드 뒤에 써도 먹도록 공통 부모 파서로 붙입니다.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--days", type=int, default=28, help="조회 기간(일), 기본 28")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("channel", parents=[common], help="채널 전체 요약").set_defaults(func=cmd_channel)

    v = sub.add_parser("videos", parents=[common], help="영상별 성과")
    v.add_argument("--limit", type=int, default=20)
    v.set_defaults(func=cmd_videos)

    sub.add_parser("traffic", parents=[common], help="트래픽 소스별").set_defaults(func=cmd_traffic)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
