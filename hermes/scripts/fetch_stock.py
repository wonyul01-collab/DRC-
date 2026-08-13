#!/usr/bin/env python3
"""무료 스톡 영상 받아오기 — Pexels API.

AI 로 만들 필요가 없는 장면은 여기서 가져옵니다. 계단을 오르는 사람, 등산,
걷기, 앉았다 일어나기 같은 일상 동작은 스톡에 넘칩니다. **크레딧이 0 입니다.**

Higgsfield 크레딧은 스톡에 없는 것 — 몸 안을 보여주는 시뮬레이션 — 에만 쓰세요.
그러면 편당 클립 4개가 1~2개로 줄고, 남는 예산으로 편수를 늘릴 수 있습니다.

라이선스: Pexels 콘텐츠는 무료이며 상업적 이용이 가능하고 출처 표기 의무가
없습니다. 다만 받은 영상의 출처를 credits.json 에 남겨 두면 나중에 확인하기
편합니다. 사람을 알아볼 수 있는 영상을 상품 광고처럼 쓰는 것은 제한되므로,
지금처럼 정보성 콘텐츠에 배경으로 쓰는 용도로만 쓰세요.

API 키 발급 (무료, 1분): https://www.pexels.com/api/
  시간당 200회, 월 20,000회. 우리 용도로는 남습니다.

사용 예:
  python fetch_stock.py --setup                      # 키 파일 만들고 열기
  python fetch_stock.py search --query "climbing stairs"
  python fetch_stock.py get --query "climbing stairs" --out raw/stairs.mp4
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

API = "https://api.pexels.com/videos"
KEY_FILENAME = "pexels_api_key.txt"

# 세로 쇼츠용. 가로 영상을 크롭하면 인물이 잘리므로 세로를 우선합니다.
MIN_WIDTH = 720
MIN_HEIGHT = 1280


# --------------------------------------------------------------------------
# 키 관리 — analyze_reference.py 와 같은 방식
# --------------------------------------------------------------------------

def hermes_home() -> Path:
    env = os.environ.get("HERMES_HOME")
    if env:
        return Path(env).expanduser()
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "hermes"
    return Path.home() / ".hermes"


def key_file_candidates() -> list[Path]:
    here = Path(__file__).resolve().parent
    return [hermes_home() / "secrets" / KEY_FILENAME, here / KEY_FILENAME,
            Path.cwd() / KEY_FILENAME]


def read_key_file(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line and line.split("=", 1)[0].strip().upper().endswith("API_KEY"):
            line = line.split("=", 1)[1].strip()
        line = line.strip().strip('"').strip("'").strip()
        if line:
            return line
    return None


def load_api_key() -> str:
    env_key = os.environ.get("PEXELS_API_KEY", "").strip()
    if env_key:
        return env_key
    for path in key_file_candidates():
        key = read_key_file(path)
        if key:
            return key
    listed = "\n".join(f"      {p}" for p in key_file_candidates())
    sys.exit(
        "Pexels API 키를 찾지 못했습니다.\n\n"
        f"      python {Path(__file__).name} --setup\n\n"
        "  으로 키 파일을 만들고 붙여넣으세요.\n"
        "  발급: https://www.pexels.com/api/ (무료, 1분)\n\n"
        "  아래 위치 중 아무 곳에나 직접 만드셔도 됩니다:\n"
        f"{listed}"
    )


def cmd_setup() -> None:
    target = key_file_candidates()[0]
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and read_key_file(target):
        print(f"이미 키가 들어 있습니다: {target}")
        return
    if not target.exists():
        target.write_text(
            "# 이 줄 아래에 Pexels API 키를 붙여넣고 저장하세요.\n"
            "# 발급: https://www.pexels.com/api/  (무료, 1분)\n"
            "\n", encoding="utf-8")
        try:
            target.chmod(0o600)
        except OSError:
            pass
    print(f"키 파일을 만들었습니다:\n    {target}\n")
    try:
        if sys.platform == "win32":
            os.startfile(str(target))     # type: ignore[attr-defined]
        elif shutil.which("wslview"):
            subprocess.Popen(["wslview", str(target)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target)])
    except Exception:
        print("편집기를 자동으로 열지 못했습니다. 위 경로의 파일을 직접 여세요.")


# --------------------------------------------------------------------------
# 검색·다운로드
# --------------------------------------------------------------------------

def api_get(endpoint: str, params: dict, key: str) -> dict:
    url = f"{API}/{endpoint}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"Authorization": key})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        if exc.code == 401:
            sys.exit("Pexels API 키가 유효하지 않습니다. 키 파일을 확인하세요.")
        if exc.code == 429:
            sys.exit("Pexels 요청 한도를 넘었습니다 (시간당 200회). 잠시 뒤 다시 시도하세요.")
        sys.exit(f"API 오류 {exc.code}:\n{body[:500]}")
    except urllib.error.URLError as exc:
        sys.exit(f"네트워크 오류: {exc.reason}")


def best_file(video: dict) -> dict | None:
    """세로이고 해상도가 충분한 파일 중 가장 작은 것.

    무조건 큰 걸 받으면 용량만 커집니다. 최종 출력이 1080x1920 이므로
    그걸 넘는 해상도는 의미가 없습니다.
    """
    candidates = [
        f for f in video.get("video_files", [])
        if f.get("height", 0) >= MIN_HEIGHT and f.get("width", 0) >= MIN_WIDTH
        and f.get("height", 0) >= f.get("width", 0)          # 세로
    ]
    if not candidates:
        return None
    # 1080x1920 에 가장 가까우면서 그 이상인 것
    enough = [f for f in candidates if f["width"] >= 1080] or candidates
    return min(enough, key=lambda f: f["width"] * f["height"])


def search(query: str, key: str, limit: int, min_seconds: float) -> list[dict]:
    data = api_get("search", {
        "query": query,
        "orientation": "portrait",
        "per_page": min(max(limit * 3, 10), 80),
    }, key)

    results = []
    for v in data.get("videos", []):
        if v.get("duration", 0) < min_seconds:
            continue
        chosen = best_file(v)
        if not chosen:
            continue
        results.append({
            "id": v["id"],
            "duration": v.get("duration"),
            "width": chosen["width"],
            "height": chosen["height"],
            "download_url": chosen["link"],
            "page_url": v.get("url"),
            "photographer": v.get("user", {}).get("name"),
            "photographer_url": v.get("user", {}).get("url"),
        })
        if len(results) >= limit:
            break
    return results


def download(item: dict, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(item["download_url"], headers={"User-Agent": "hermes-shorts/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp, open(out_path, "wb") as fh:
        shutil.copyfileobj(resp, fh)

    # 출처 기록. 표기 의무는 없지만 나중에 어디서 왔는지 확인하려면 필요합니다.
    credits_path = out_path.parent / "credits.json"
    try:
        credits = json.loads(credits_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        credits = {}
    credits[out_path.name] = {
        "source": "Pexels",
        "license": "Pexels License (무료·상업적 이용 가능·출처 표기 불필요)",
        "id": item["id"],
        "page_url": item["page_url"],
        "photographer": item["photographer"],
    }
    credits_path.write_text(json.dumps(credits, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_search(args: argparse.Namespace) -> None:
    items = search(args.query, load_api_key(), args.limit, args.min_seconds)
    if not items:
        sys.exit(f"'{args.query}' 로 조건에 맞는 세로 영상을 찾지 못했습니다.\n"
                 "검색어를 영어로 바꾸거나 --min-seconds 를 줄여보세요.")
    print(json.dumps(items, ensure_ascii=False, indent=2))


def cmd_get(args: argparse.Namespace) -> None:
    key = load_api_key()
    items = search(args.query, key, max(args.pick, 1), args.min_seconds)
    if not items:
        sys.exit(f"'{args.query}' 로 조건에 맞는 세로 영상을 찾지 못했습니다.")
    if args.pick > len(items):
        sys.exit(f"{args.pick}번째 결과가 없습니다 (총 {len(items)}개).")
    item = items[args.pick - 1]
    out = Path(args.out).expanduser()
    download(item, out)
    print(json.dumps({
        "saved": str(out),
        "id": item["id"],
        "resolution": f"{item['width']}x{item['height']}",
        "duration": item["duration"],
        "page_url": item["page_url"],
        "credits": 0,
    }, ensure_ascii=False, indent=2))


def main() -> None:
    parser = argparse.ArgumentParser(description="Pexels 무료 스톡 영상 받아오기")
    parser.add_argument("--setup", action="store_true", help="API 키 파일을 만들고 연다")
    sub = parser.add_subparsers(dest="command")

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--query", required=True, help="검색어 (영어가 결과가 훨씬 많습니다)")
    common.add_argument("--min-seconds", type=float, default=5.0,
                        help="이보다 짧은 영상은 제외 (기본 5초)")

    s = sub.add_parser("search", parents=[common], help="후보 목록만 본다")
    s.add_argument("--limit", type=int, default=5)
    s.set_defaults(func=cmd_search)

    g = sub.add_parser("get", parents=[common], help="받아서 저장한다")
    g.add_argument("--out", required=True, help="저장할 경로")
    g.add_argument("--pick", type=int, default=1, help="검색 결과 중 몇 번째 (기본 1)")
    g.set_defaults(func=cmd_get)

    args = parser.parse_args()
    if args.setup:
        cmd_setup()
        return
    if not args.command:
        parser.error("search 또는 get 중 하나를 지정하세요 (또는 --setup)")
    args.func(args)


if __name__ == "__main__":
    main()
