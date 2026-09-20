"""
명령줄 다운로더 겸 진단 도구.

  python ytdl.py "https://youtu.be/..."        받기
  python ytdl.py --check                       환경 점검만
  python ytdl.py --check "https://youtu.be/.." 어느 클라이언트가 뚫리는지 확인
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ytdl_core as core


def cmd_check(urls: list[str], cookies: dict) -> int:
    env = core.check_environment(check_updates=True)

    print("── 환경 ──────────────────────────────")
    print(f"  yt-dlp       {env.ytdlp_version or '없음'}"
          + (f"   (최신 {env.ytdlp_latest})" if env.ytdlp_outdated else "   (최신)"))
    print(f"  ffmpeg       {env.ffmpeg or '없음'}")
    print(f"  JS 런타임    {env.js_runtime or '없음'}")
    print()

    for p in env.problems:
        print(f"  ⚠  {p}")
    for n in env.notes:
        print(f"  ·  {n}")
    if env.problems or env.notes:
        print()

    if not urls:
        return 0

    import yt_dlp
    for url in urls:
        print(f"── {url}")
        for strat in core.STRATEGIES:
            opts = core.build_opts(".", "best", cookies, strat)
            opts.update({"skip_download": True, "quiet": True, "no_warnings": True})
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                n = len(info.get("formats") or [])
                print(f"  ✓ {strat.name:14} 포맷 {n}개   {info.get('title','')[:40]}")
            except Exception as e:
                print(f"  ✗ {strat.name:14} {core._friendly(str(e))[:70]}")
        print()
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="유튜브 다운로더 (403 자동 우회)")
    ap.add_argument("urls", nargs="*", help="영상 주소")
    ap.add_argument("-o", "--out", default=str(Path.home() / "Downloads" / "영상다운로드"))
    ap.add_argument("-q", "--quality", default="best",
                    choices=list(core.QUALITY_FORMATS.keys()))
    ap.add_argument("--cookies-from", metavar="BROWSER",
                    help="firefox / edge / chrome / whale")
    ap.add_argument("--cookies", metavar="FILE", help="cookies.txt 경로")
    ap.add_argument("--check", action="store_true", help="환경 점검 / 클라이언트별 확인")
    args = ap.parse_args()

    cookies = core.cookie_options(args.cookies_from, args.cookies)

    if args.check:
        return cmd_check(args.urls, cookies)

    if not args.urls:
        ap.print_help()
        return 1

    os.makedirs(args.out, exist_ok=True)
    print(f"저장 위치: {args.out}\n")

    ok = fail = 0
    preferred = None
    for i, url in enumerate(args.urls, 1):
        print(f"▶ ({i}/{len(args.urls)}) {url}")
        res = core.download_one(
            url, args.out, args.quality, cookies,
            log=lambda m: print(m), preferred=preferred,
        )
        if res.ok:
            ok += 1
            preferred = next((s for s in core.STRATEGIES if s.name == res.strategy), None)
            tail = "" if res.strategy == "기본" else f"   [{res.strategy} 로 우회]"
            print(f"    ✓ {res.title}{tail}")
        else:
            fail += 1
            print(f"    ✗ {res.error}")

    print(f"\n완료: 성공 {ok} / 실패 {fail}")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
