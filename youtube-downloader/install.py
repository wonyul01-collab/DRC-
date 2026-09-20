"""
영상 다운로더 설치 프로그램.

배치 파일로 하지 않는 이유: 한글 경로 + 따옴표 + PowerShell 을 배치에서 섞으면
인코딩 때문에 깨지기 쉽고, 깨져도 원인을 알기 어렵다. 파이썬은 경로를
문자열로 다루고 subprocess 에 리스트로 넘기므로 따옴표 문제가 아예 없다.

기존 폴더가 있든 없든 같은 동작을 한다.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
TARGET = Path.home() / "영상다운로더"
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
IS_WIN = os.name == "nt"

COPY_FILES = [
    "app.py",
    "youtube_downloader.py",
    "ytdl_core.py",
    "ytdl.py",
    "README.md",
]


def say(msg: str = "") -> None:
    print(msg, flush=True)


def step(n: int, total: int, msg: str) -> None:
    say(f"  [{n}/{total}] {msg}")


def venv_python(target: Path) -> Path:
    if IS_WIN:
        return target / ".venv" / "Scripts" / "python.exe"
    return target / ".venv" / "bin" / "python"


def venv_pythonw(target: Path) -> Path:
    if IS_WIN:
        return target / ".venv" / "Scripts" / "pythonw.exe"
    return venv_python(target)


def run(cmd: list, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(
        [str(c) for c in cmd],
        capture_output=True, text=True, timeout=timeout,
        creationflags=NO_WINDOW if IS_WIN else 0,
    )


# --------------------------------------------------------------------------

def prepare_folder(target: Path) -> None:
    if target.exists():
        old = target / "app.py"
        if old.is_file():
            backup = target / "app.py.예전버전백업"
            shutil.copy2(old, backup)
            say(f"        기존 프로그램을 백업했습니다: {backup.name}")
        else:
            say("        기존 폴더를 사용합니다.")
    else:
        target.mkdir(parents=True, exist_ok=True)
        say("        새 폴더를 만들었습니다.")


def copy_files(target: Path) -> int:
    n = 0
    for name in COPY_FILES:
        src = HERE / name
        if src.is_file():
            shutil.copy2(src, target / name)
            n += 1
    # 보조 배치 파일은 있으면 같이 옮긴다
    for name in ("업데이트.bat", "문제진단.bat"):
        src = HERE / name
        if src.is_file():
            shutil.copy2(src, target / name)
    return n


def make_venv(target: Path) -> bool:
    py = venv_python(target)
    if py.is_file():
        say("        기존 실행 환경을 사용합니다.")
        return True
    say("        실행 환경을 만드는 중입니다...")
    proc = run([sys.executable, "-m", "venv", str(target / ".venv")])
    if proc.returncode != 0 or not py.is_file():
        say("")
        say("  [!] 실행 환경을 만들지 못했습니다.")
        say((proc.stderr or proc.stdout or "").strip()[:500])
        return False
    return True


def install_ytdlp(target: Path) -> bool:
    py = venv_python(target)
    run([py, "-m", "pip", "install", "--upgrade", "pip",
         "--quiet", "--disable-pip-version-check"], timeout=300)
    say("        yt-dlp 를 받는 중입니다. 조금 기다려 주세요...")
    proc = run([py, "-m", "pip", "install", "--upgrade", "--pre", "yt-dlp",
                "--quiet", "--disable-pip-version-check"])
    if proc.returncode != 0:
        say("")
        say("  [!] yt-dlp 를 받지 못했습니다. 인터넷 연결을 확인하세요.")
        say((proc.stderr or proc.stdout or "").strip()[:500])
        return False
    run([py, "-m", "yt_dlp", "--rm-cache-dir"], timeout=120)
    return True


def make_shortcut(target: Path) -> Path | None:
    """바탕화면 바로가기. 실패해도 설치는 성공으로 친다."""
    if not IS_WIN:
        return None

    desktop = Path.home() / "Desktop"
    if not desktop.is_dir():
        onedrive = Path.home() / "OneDrive" / "Desktop"   # OneDrive 동기화 환경
        if onedrive.is_dir():
            desktop = onedrive
        else:
            return None

    lnk = desktop / "영상 다운로더.lnk"
    exe = venv_pythonw(target)
    arg = target / "app.py"

    # 경로를 환경변수로 넘긴다. 명령줄 따옴표 escape 를 아예 피하기 위해서다.
    env = dict(os.environ, SC_LNK=str(lnk), SC_EXE=str(exe),
               SC_ARG=str(arg), SC_DIR=str(target))
    ps = (
        "$q=[char]34;"
        "$w=New-Object -ComObject WScript.Shell;"
        "$s=$w.CreateShortcut($env:SC_LNK);"
        "$s.TargetPath=$env:SC_EXE;"
        "$s.Arguments=$q+$env:SC_ARG+$q;"
        "$s.WorkingDirectory=$env:SC_DIR;"
        "$s.Description='Video Downloader';"
        "$s.Save()"
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
            capture_output=True, text=True, timeout=120, env=env,
            creationflags=NO_WINDOW,
        )
    except Exception:
        return None

    return lnk if lnk.is_file() else None


def verify(target: Path) -> bool:
    py = venv_python(target)
    proc = run([py, str(target / "ytdl.py"), "--check"], timeout=120)
    say(proc.stdout.rstrip() or "(점검 결과를 읽지 못했습니다)")
    if proc.returncode != 0 and proc.stderr:
        say(proc.stderr.strip()[:400])
    return proc.returncode == 0


# --------------------------------------------------------------------------

def main() -> int:
    total = 5
    say()
    say("  ============================================")
    say("     영상 다운로더 설치")
    say("  ============================================")
    say()
    say("  설치할 위치:")
    say(f"    {TARGET}")
    say()

    try:
        input("  계속하려면 엔터를 누르세요 (그만두려면 창을 닫으세요) ")
    except (EOFError, KeyboardInterrupt):
        return 1
    say()

    step(1, total, "폴더 준비 중...")
    prepare_folder(TARGET)

    step(2, total, "프로그램 파일 복사 중...")
    n = copy_files(TARGET)
    if n < len(COPY_FILES):
        say(f"  [!] 파일이 부족합니다 ({n}/{len(COPY_FILES)}).")
        say(f"      이 폴더에 프로그램 파일이 다 있어야 합니다: {HERE}")
        return 1
    say("        완료.")

    step(3, total, "실행 환경 준비 중... (처음이면 1~2분 걸립니다)")
    if not make_venv(TARGET):
        return 1

    step(4, total, "yt-dlp 설치 중...")
    if not install_ytdlp(TARGET):
        return 1
    say("        완료.")

    step(5, total, "바탕화면 바로가기 만드는 중...")
    lnk = make_shortcut(TARGET)
    say(f"        만들었습니다: {lnk}" if lnk
        else "        바로가기는 못 만들었습니다 (프로그램은 정상입니다).")

    say()
    say("  ============================================")
    say("     설치가 끝났습니다")
    say("  ============================================")
    say()
    verify(TARGET)
    say()
    say("  ── 쓰는 방법 ──────────────────────────────")
    if lnk:
        say("  바탕화면의 [영상 다운로더] 아이콘을 더블클릭하세요.")
    else:
        say("  아래 파일을 더블클릭하세요:")
        say(f"    {TARGET / 'app.py'}")
    say()
    say("  ── 프로그램 위치 ──────────────────────────")
    say(f"    {TARGET}")
    say()
    say("  ── 잘 안 될 때 ────────────────────────────")
    say(f"    {TARGET / '문제진단.bat'}  를 더블클릭하세요.")
    say("  ============================================")
    say()

    if IS_WIN:
        try:
            ans = input("  지금 바로 실행해 볼까요? (Y/N): ").strip().lower()
            if ans == "y":
                subprocess.Popen([str(venv_pythonw(TARGET)), str(TARGET / "app.py")],
                                 cwd=str(TARGET))
        except (EOFError, KeyboardInterrupt):
            pass
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except Exception:
        import traceback
        say()
        say("  [!] 설치 중 오류가 났습니다:")
        say(traceback.format_exc())
        code = 1
    if IS_WIN:
        try:
            input("\n  이 창을 닫으려면 엔터를 누르세요 ")
        except Exception:
            pass
    sys.exit(code)
