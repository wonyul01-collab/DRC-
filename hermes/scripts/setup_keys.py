#!/usr/bin/env python3
"""API 키를 한 파일에 모아 관리한다.

키마다 파일을 따로 만들면 번거롭습니다. 이 스크립트가 파일 하나를 만들고
편집기로 열어주면, 거기에 필요한 키를 전부 붙여넣고 저장하면 끝입니다.

  python setup_keys.py

만들어지는 파일:
  Windows : %LOCALAPPDATA%\\hermes\\secrets\\api_keys.txt
  그 외    : ~/.hermes/secrets/api_keys.txt

이 파일은 .gitignore 에 걸려 있어 저장소에 올라가지 않습니다.
환경변수(YOUTUBE_API_KEY 등)를 쓰면 파일보다 우선합니다.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

SHARED_FILENAME = "api_keys.txt"

KEYS = [
    ("YOUTUBE_API_KEY",
     "유튜브 채널 분석 (analyze_reference.py). 읽기 전용.",
     "Google Cloud Console → 사용자 인증 정보 → API 키 → YouTube Data API v3 만 선택"),
    ("PEXELS_API_KEY",
     "무료 스톡 영상 (fetch_stock.py). 크레딧 0.",
     "https://www.pexels.com/api/  (무료, 1분)"),
    ("TYPECAST_API_KEY",
     "한국어 나레이션 (compose_short.py, voice.provider=typecast).",
     "https://typecast.ai  API 콘솔에서 발급"),
]

TEMPLATE_HEADER = """\
# API 키 모음 — 등호 뒤에 키를 붙여넣고 저장하세요.
#
#   - '#' 으로 시작하는 줄은 무시됩니다.
#   - 따옴표는 붙이지 않아도 됩니다.
#   - 안 쓰는 키는 비워두면 됩니다.
#   - 이 파일은 저장소에 올라가지 않습니다 (.gitignore).
#
"""


def hermes_home() -> Path:
    env = os.environ.get("HERMES_HOME")
    if env:
        return Path(env).expanduser()
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "hermes"
    return Path.home() / ".hermes"


def shared_key_file() -> Path:
    return hermes_home() / "secrets" / SHARED_FILENAME


def parse_shared(path: Path) -> dict[str, str]:
    """api_keys.txt 를 읽어 {키이름: 값}. 메모장이 남기는 BOM·따옴표를 걷어낸다."""
    try:
        text = path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError):
        return {}
    found: dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        value = value.strip().strip('"').strip("'").strip()
        if value:
            found[name.strip().upper()] = value
    return found


def build_template(existing: dict[str, str]) -> str:
    out = [TEMPLATE_HEADER]
    for name, what, where in KEYS:
        out.append(f"# {what}")
        out.append(f"#   발급: {where}")
        out.append(f"{name}={existing.get(name, '')}")
        out.append("")
    return "\n".join(out)


def main() -> None:
    target = shared_key_file()
    target.parent.mkdir(parents=True, exist_ok=True)

    # 기존에 개별 파일로 넣어둔 키가 있으면 끌어와서 옮겨 담는다.
    existing = parse_shared(target) if target.exists() else {}
    legacy = {
        "YOUTUBE_API_KEY": target.parent / "youtube_api_key.txt",
        "PEXELS_API_KEY": target.parent / "pexels_api_key.txt",
        "TYPECAST_API_KEY": target.parent / "typecast_api_key.txt",
    }
    for name, path in legacy.items():
        if existing.get(name) or not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8-sig").splitlines():
            line = raw.strip()
            if line and not line.startswith("#"):
                if "=" in line and line.split("=", 1)[0].strip().upper().endswith("API_KEY"):
                    line = line.split("=", 1)[1]
                value = line.strip().strip('"').strip("'").strip()
                if value:
                    existing[name] = value
                    print(f"기존 파일에서 옮겨 담음: {name}  ({path.name})")
                break

    target.write_text(build_template(existing), encoding="utf-8")
    try:
        target.chmod(0o600)
    except OSError:
        pass

    print(f"\n키 파일: {target}\n")
    for name, what, _ in KEYS:
        state = "입력됨" if existing.get(name) else "비어 있음"
        print(f"  {name:<20} {state:<8} {what}")
    print("\n열리는 메모장에 키를 붙여넣고 저장하세요. 안 쓰는 것은 비워두면 됩니다.")

    try:
        if sys.platform == "win32":
            os.startfile(str(target))     # type: ignore[attr-defined]
        elif shutil.which("wslview"):
            subprocess.Popen(["wslview", str(target)])
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(target)])
        else:
            print("\n편집기를 자동으로 열지 못했습니다. 위 경로의 파일을 직접 여세요.")
    except Exception:
        print("\n편집기를 자동으로 열지 못했습니다. 위 경로의 파일을 직접 여세요.")


if __name__ == "__main__":
    main()
