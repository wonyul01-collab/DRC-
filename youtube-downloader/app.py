"""
바로가기 진입점 겸 자가 수리 런처.

바탕화면 바로가기가 이 파일을 pythonw.exe 로 실행한다.
  ...\\.venv\\Scripts\\pythonw.exe "...\\영상다운로더\\app.py"

이 파일이 하는 일은 둘이다.

1. yt_dlp 를 import 하기 전에 최신인지 확인하고, 낡았으면 올린다.
   순서가 중요하다. 이미 import 된 모듈은 pip 로 올려도 안 바뀌기 때문에,
   반드시 import 전에 끝내야 새 버전이 실제로 쓰인다.
   403 의 1순위 원인이 낡은 yt-dlp 라서, 이 한 단계가 대부분을 해결한다.

2. 모든 예외를 붙잡아 창으로 띄운다.
   pythonw.exe 는 콘솔이 없다. 시작 단계에서 터지면 화면에 아무것도 안 뜨고
   조용히 죽는다. "눌렀는데 반응이 없다" 가 그 증상이다.
"""

from __future__ import annotations

import importlib.metadata
import json
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG = HERE / "오류기록.txt"
STATE = HERE / ".launcher_state.json"

sys.path.insert(0, str(HERE))

CHECK_INTERVAL = 6 * 3600  # 6시간에 한 번만 확인한다. 매번 하면 시작이 느려진다.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# --------------------------------------------------------------------------
# 버전 비교
# --------------------------------------------------------------------------

def _vtuple(v: str) -> tuple:
    """'2026.08.19' 와 '2026.8.19' 는 같은 버전이다. 숫자로 바꿔서 비교한다."""
    out = []
    for chunk in v.strip().split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        out.append(int(digits) if digits else 0)
    return tuple(out)


def _installed() -> str | None:
    """yt_dlp 를 import 하지 않고 설치된 버전만 읽는다."""
    try:
        return importlib.metadata.version("yt-dlp")
    except Exception:
        return None


def _latest(timeout: float = 6.0) -> str | None:
    try:
        req = urllib.request.Request(
            "https://pypi.org/pypi/yt-dlp/json",
            headers={"User-Agent": "youtube-downloader/2.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)["info"]["version"]
    except Exception:
        return None


def _state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(d: dict) -> None:
    try:
        STATE.write_text(json.dumps(d), encoding="utf-8")
    except Exception:
        pass


# --------------------------------------------------------------------------
# 알림창 (콘솔이 없으므로)
# --------------------------------------------------------------------------

def _report(title: str, body: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        with LOG.open("a", encoding="utf-8") as f:
            f.write(f"\n{'='*60}\n{stamp}  {title}\n{'='*60}\n{body}\n")
    except Exception:
        pass

    try:
        import tkinter as tk
        from tkinter import scrolledtext

        root = tk.Tk()
        root.title("영상 다운로더 - 실행 실패")
        root.geometry("760x460")
        tk.Label(root, text=title, font=("맑은 고딕", 11, "bold"), fg="#c00",
                 anchor="w", justify="left", wraplength=720).pack(fill="x", padx=14, pady=(14, 6))
        box = scrolledtext.ScrolledText(root, font=("Consolas", 9), wrap="word")
        box.pack(fill="both", expand=True, padx=14, pady=6)
        box.insert("1.0", body)
        box.configure(state="disabled")
        tk.Label(root, text=f"이 내용은 {LOG.name} 에도 저장됐습니다.",
                 fg="#666", anchor="w").pack(fill="x", padx=14, pady=(0, 4))
        tk.Button(root, text="닫기", command=root.destroy, width=14).pack(pady=(0, 14))
        root.mainloop()
    except Exception:
        pass


class _Splash:
    """업데이트 중에 아무것도 안 뜨면 멈춘 줄 안다. 작은 창을 띄운다."""

    def __init__(self, text: str):
        self.root = None
        try:
            import tkinter as tk
            self.root = tk.Tk()
            self.root.title("영상 다운로더")
            self.root.geometry("420x120")
            self.root.resizable(False, False)
            tk.Label(self.root, text=text, font=("맑은 고딕", 10),
                     wraplength=380, justify="center").pack(expand=True, padx=16, pady=(18, 6))
            from tkinter import ttk
            bar = ttk.Progressbar(self.root, mode="indeterminate")
            bar.pack(fill="x", padx=20, pady=(0, 18))
            bar.start(12)
            self.root.update()
        except Exception:
            self.root = None

    def pump(self):
        if self.root is not None:
            try:
                self.root.update()
            except Exception:
                pass

    def close(self):
        if self.root is not None:
            try:
                self.root.destroy()
            except Exception:
                pass
            self.root = None


# --------------------------------------------------------------------------
# 사전 점검
# --------------------------------------------------------------------------

def preflight() -> None:
    """yt_dlp import 전에 최신화한다. 실패해도 진행한다 (인터넷이 없을 수도 있다)."""
    installed = _installed()
    if installed is None:
        _install_fresh()
        return

    st = _state()
    if time.time() - st.get("last_check", 0) < CHECK_INTERVAL:
        return

    latest = _latest()
    st["last_check"] = time.time()
    _save_state(st)

    if not latest or _vtuple(installed) >= _vtuple(latest):
        return

    splash = _Splash(
        f"yt-dlp 를 최신으로 올리는 중입니다.\n{installed}  →  {latest}\n\n"
        "유튜브가 다운로드를 막는 걸 푸는 과정입니다.\n잠시만 기다려 주세요."
    )
    done = {}

    def work():
        try:
            done["proc"] = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", "--pre",
                 "yt-dlp", "--disable-pip-version-check", "--quiet"],
                capture_output=True, text=True, timeout=300, creationflags=NO_WINDOW,
            )
        except Exception as e:
            done["err"] = e

    t = threading.Thread(target=work, daemon=True)
    t.start()
    while t.is_alive():
        splash.pump()
        time.sleep(0.05)
    splash.close()


def _install_fresh() -> None:
    """yt-dlp 가 아예 없을 때."""
    splash = _Splash("yt-dlp 를 설치하는 중입니다.\n처음 한 번만 걸립니다.")
    done = {}

    def work():
        try:
            done["proc"] = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", "--pre",
                 "yt-dlp", "--disable-pip-version-check", "--quiet"],
                capture_output=True, text=True, timeout=300, creationflags=NO_WINDOW,
            )
        except Exception as e:
            done["err"] = e

    t = threading.Thread(target=work, daemon=True)
    t.start()
    while t.is_alive():
        splash.pump()
        time.sleep(0.05)
    splash.close()

    if _installed() is None:
        _report(
            "yt-dlp 를 설치하지 못했습니다.",
            "인터넷 연결을 확인한 뒤 다시 실행해 보세요.\n\n"
            "계속 안 되면 이 폴더에서 명령 프롬프트를 열고 아래를 실행하세요.\n\n"
            "    .venv\\Scripts\\python.exe -m pip install --upgrade --pre yt-dlp\n",
        )
        sys.exit(1)


# --------------------------------------------------------------------------

def main() -> int:
    try:
        preflight()
    except Exception:
        pass  # 사전 점검 실패로 프로그램이 안 뜨면 안 된다

    try:
        import youtube_downloader
    except Exception:
        _report(
            "프로그램 파일을 불러오지 못했습니다.",
            "youtube_downloader.py 와 ytdl_core.py 가 app.py 와 같은 폴더에 있어야 합니다.\n"
            f"현재 폴더: {HERE}\n\n"
            + "\n".join(f"  {f.name}" for f in sorted(HERE.glob("*.py")))
            + "\n\n" + traceback.format_exc(),
        )
        return 1

    try:
        youtube_downloader.main()
    except Exception:
        _report("실행 중 오류가 났습니다.", traceback.format_exc())
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
