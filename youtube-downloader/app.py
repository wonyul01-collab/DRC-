"""
기존 바로가기용 진입점.

바탕화면 바로가기가 이 파일을 pythonw.exe 로 실행한다.
  C:\\Users\\USER\\영상다운로더\\.venv\\Scripts\\pythonw.exe "C:\\Users\\USER\\영상다운로더\\app.py"

pythonw.exe 는 콘솔이 없다. 그래서 import 단계에서 터지면 화면에 아무것도
안 뜨고 조용히 죽는다. v1 을 쓸 때 "눌렀는데 아무 반응이 없다" 가 이것이다.
여기서 모든 예외를 붙잡아 창으로 띄우고 파일로도 남긴다.
"""

from __future__ import annotations

import importlib.util
import sys
import traceback
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG = HERE / "오류기록.txt"

sys.path.insert(0, str(HERE))


def _report(title: str, body: str) -> None:
    """콘솔이 없으므로 창으로 알린다. 창도 못 띄우면 파일만 남긴다."""
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

        tk.Label(
            root, text=title, font=("맑은 고딕", 11, "bold"),
            fg="#c00", anchor="w", justify="left", wraplength=720,
        ).pack(fill="x", padx=14, pady=(14, 6))

        box = scrolledtext.ScrolledText(root, font=("Consolas", 9), wrap="word")
        box.pack(fill="both", expand=True, padx=14, pady=6)
        box.insert("1.0", body)
        box.configure(state="disabled")

        tk.Label(
            root, text=f"이 내용은 {LOG.name} 에도 저장됐습니다.",
            fg="#666", anchor="w",
        ).pack(fill="x", padx=14, pady=(0, 4))
        tk.Button(root, text="닫기", command=root.destroy, width=14).pack(pady=(0, 14))

        root.mainloop()
    except Exception:
        pass


def main() -> int:
    # yt-dlp 가 없으면 무엇을 해야 하는지 콕 집어 알려준다
    if importlib.util.find_spec("yt_dlp") is None:
        _report(
            "yt-dlp 가 설치돼 있지 않습니다.",
            "이 폴더에서 명령 프롬프트를 열고 아래를 실행하세요.\n\n"
            "    .venv\\Scripts\\python.exe -m pip install --upgrade --pre yt-dlp\n\n"
            "또는 업데이트.bat 을 더블클릭하세요.",
        )
        return 1

    try:
        import youtube_downloader
    except Exception:
        _report(
            "프로그램 파일을 불러오지 못했습니다.",
            "youtube_downloader.py 와 ytdl_core.py 가 app.py 와 같은 폴더에 있어야 합니다.\n"
            f"현재 폴더: {HERE}\n\n"
            + "\n".join(f"  {f.name}" for f in sorted(HERE.glob('*.py')))
            + "\n\n"
            + traceback.format_exc(),
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
