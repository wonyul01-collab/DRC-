"""
영상 다운로더 v2.0 - 403 자동 우회판

실행: 실행.bat 을 더블클릭
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ytdl_core as core


APP_TITLE = "영상 다운로더 v2.0"
SETTINGS_PATH = Path.home() / ".youtube_downloader.json"

QUALITY_CHOICES = [
    ("최고 화질 (권장)", "best"),
    ("1080p 이하", "1080"),
    ("720p 이하", "720"),
    ("음성만 (MP3)", "audio"),
]

COOKIE_CHOICES = [
    ("사용 안 함 (권장)", ""),
    ("Firefox", "firefox"),
    ("Edge", "edge"),
    ("Chrome", "chrome"),
    ("Whale", "whale"),
    ("쿠키 파일 직접 지정", "__file__"),
]

# 색
BG = "#1e1e1e"
FG = "#d4d4d4"
OK = "#4ec9b0"
BAD = "#f48771"
WARN = "#dcdcaa"
INFO = "#569cd6"
DIM = "#808080"


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(APP_TITLE)
        root.geometry("780x720")
        root.minsize(680, 600)

        self.msgq: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.cancel_flag = threading.Event()
        self.settings = self._load_settings()

        self._build_ui()
        self._pump()
        self.root.after(200, self._startup_check)

    # ---------------- 설정 저장/복원 ----------------

    def _load_settings(self) -> dict:
        import json
        try:
            return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_settings(self):
        import json
        data = {
            "out_dir": self.out_dir.get(),
            "quality": self.quality.get(),
            "cookie": self.cookie.get(),
            "cookie_file": self.cookie_file,
        }
        try:
            SETTINGS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    # ---------------- UI ----------------

    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        # --- 주소 입력 ---
        f1 = ttk.LabelFrame(self.root, text="영상 주소 (여러 개는 한 줄에 하나씩)")
        f1.pack(fill="x", **pad)

        self.urls = tk.Text(f1, height=6, wrap="none", font=("Consolas", 10))
        self.urls.pack(fill="x", padx=8, pady=(8, 4))

        b1 = ttk.Frame(f1)
        b1.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(b1, text="붙여넣기", command=self._paste, width=12).pack(side="left")
        ttk.Button(b1, text="지우기", command=lambda: self.urls.delete("1.0", "end"), width=12).pack(side="left", padx=6)

        # --- 설정 ---
        f2 = ttk.LabelFrame(self.root, text="설정")
        f2.pack(fill="x", **pad)

        r1 = ttk.Frame(f2)
        r1.pack(fill="x", padx=8, pady=6)
        ttk.Label(r1, text="저장 폴더", width=10).pack(side="left")
        default_dir = self.settings.get("out_dir") or str(Path.home() / "Downloads" / "영상다운로드")
        self.out_dir = tk.StringVar(value=default_dir)
        ttk.Entry(r1, textvariable=self.out_dir).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(r1, text="찾아보기", command=self._browse, width=10).pack(side="left")
        ttk.Button(r1, text="폴더 열기", command=self._open_folder, width=10).pack(side="left", padx=(6, 0))

        r2 = ttk.Frame(f2)
        r2.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Label(r2, text="화질", width=10).pack(side="left")
        self.quality = tk.StringVar(value=self.settings.get("quality", "best"))
        qbox = ttk.Combobox(r2, state="readonly", width=20,
                            values=[label for label, _ in QUALITY_CHOICES])
        qbox.pack(side="left", padx=6)
        self._qbox = qbox
        qbox.current(self._index_of(QUALITY_CHOICES, self.quality.get()))
        qbox.bind("<<ComboboxSelected>>",
                  lambda e: self.quality.set(QUALITY_CHOICES[qbox.current()][1]))

        ttk.Label(r2, text="브라우저 쿠키").pack(side="left", padx=(16, 0))
        self.cookie = tk.StringVar(value=self.settings.get("cookie", ""))
        self.cookie_file = self.settings.get("cookie_file", "")
        cbox = ttk.Combobox(r2, state="readonly", width=20,
                            values=[label for label, _ in COOKIE_CHOICES])
        cbox.pack(side="left", padx=6)
        self._cbox = cbox
        cbox.current(self._index_of(COOKIE_CHOICES, self.cookie.get()))
        cbox.bind("<<ComboboxSelected>>", self._on_cookie_change)

        # --- 실행 버튼 ---
        f3 = ttk.Frame(self.root)
        f3.pack(fill="x", **pad)
        self.btn_go = ttk.Button(f3, text="⬇  다운로드 시작", command=self._start, width=24)
        self.btn_go.pack(side="left")
        self.btn_cancel = ttk.Button(f3, text="취소", command=self._cancel, width=12, state="disabled")
        self.btn_cancel.pack(side="left", padx=8)
        ttk.Button(f3, text="문제 진단", command=self._diagnose, width=12).pack(side="right")
        self.btn_fix = ttk.Button(f3, text="🔧 자동 고치기", command=self._repair, width=16)
        self.btn_fix.pack(side="right", padx=6)

        # --- 진행 ---
        self.progress = ttk.Progressbar(self.root, mode="determinate")
        self.progress.pack(fill="x", padx=10)
        self.status = tk.StringVar(value="대기 중")
        ttk.Label(self.root, textvariable=self.status).pack(anchor="w", padx=12, pady=(4, 0))

        # --- 로그 ---
        f4 = ttk.LabelFrame(self.root, text="진행 기록")
        f4.pack(fill="both", expand=True, **pad)
        self.log = tk.Text(f4, bg=BG, fg=FG, insertbackground=FG,
                           font=("Consolas", 9), wrap="word", height=14)
        sb = ttk.Scrollbar(f4, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True, padx=(8, 0), pady=8)

        for tag, color in (("ok", OK), ("bad", BAD), ("warn", WARN),
                           ("info", INFO), ("dim", DIM)):
            self.log.tag_configure(tag, foreground=color)
        self.log.configure(state="disabled")

    @staticmethod
    def _index_of(choices, value) -> int:
        for i, (_, v) in enumerate(choices):
            if v == value:
                return i
        return 0

    # ---------------- 로그 ----------------

    def _w(self, text: str, tag: str = ""):
        self.msgq.put(("log", text, tag))

    def _pump(self):
        try:
            while True:
                kind, *rest = self.msgq.get_nowait()
                if kind == "log":
                    text, tag = rest
                    self.log.configure(state="normal")
                    self.log.insert("end", text + "\n", tag or ())
                    self.log.see("end")
                    self.log.configure(state="disabled")
                elif kind == "status":
                    self.status.set(rest[0])
                elif kind == "progress":
                    self.progress["value"] = rest[0]
                elif kind == "done":
                    self._on_finish()
                elif kind == "restart":
                    self._do_restart()
                    return
                elif kind == "repair_failed":
                    self.btn_fix.configure(state="normal")
                    self.btn_go.configure(state="normal")
                    self.status.set("고치기 실패 - 인터넷 연결을 확인하세요")
                elif kind == "offer_repair":
                    self.status.set("전부 403 으로 막혔습니다")
                    if messagebox.askyesno(
                        APP_TITLE,
                        "모든 방법이 403 으로 막혔습니다.\n\n"
                        "yt-dlp 가 낡은 것이 가장 흔한 원인입니다.\n"
                        "지금 자동으로 고칠까요?\n\n"
                        "(yt-dlp 최신화 → 캐시 정리 → 재시작)",
                    ):
                        self._repair(auto=True)
        except queue.Empty:
            pass
        self.root.after(80, self._pump)

    # ---------------- 동작 ----------------

    def _paste(self):
        try:
            self.urls.insert("end", self.root.clipboard_get().strip() + "\n")
        except Exception:
            pass

    def _browse(self):
        d = filedialog.askdirectory(initialdir=self.out_dir.get() or str(Path.home()))
        if d:
            self.out_dir.set(d)

    def _open_folder(self):
        d = self.out_dir.get()
        os.makedirs(d, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(d)
        elif sys.platform == "darwin":
            subprocess.run(["open", d])
        else:
            subprocess.run(["xdg-open", d])

    def _on_cookie_change(self, _event=None):
        label, value = COOKIE_CHOICES[self._cbox.current()]
        if value == "__file__":
            path = filedialog.askopenfilename(
                title="cookies.txt 선택",
                filetypes=[("쿠키 파일", "*.txt"), ("모든 파일", "*.*")],
            )
            if path:
                self.cookie_file = path
                self.cookie.set("__file__")
                self._w(f"쿠키 파일: {path}", "dim")
            else:
                self._cbox.current(0)
                self.cookie.set("")
        else:
            self.cookie.set(value)
            self.cookie_file = ""
            if value == "chrome":
                self._w(
                    "주의: Chrome 127+ 는 App-Bound Encryption 때문에 쿠키 추출이 막혀 있습니다. "
                    "실패하면 Firefox 나 쿠키 파일을 쓰세요.", "warn")

    def _startup_check(self):
        self._w(APP_TITLE, "ok")
        threading.Thread(target=self._env_scan, args=(False,), daemon=True).start()

    def _diagnose(self):
        self._w("")
        self._w("── 문제 진단 ─────────────────────────", "info")
        threading.Thread(target=self._env_scan, args=(True,), daemon=True).start()

    def _env_scan(self, verbose: bool):
        env = core.check_environment(check_updates=True)

        if env.ytdlp_version:
            if env.ytdlp_outdated:
                self._w(f"yt-dlp {env.ytdlp_version}  →  최신 {env.ytdlp_latest} 있음", "bad")
            else:
                self._w(f"yt-dlp {env.ytdlp_version} (최신)", "ok")
        self._w(f"ffmpeg {'있음' if env.ffmpeg else '없음'}", "ok" if env.ffmpeg else "warn")
        self._w(f"JS 런타임 {env.js_runtime or '없음'}",
                "ok" if env.js_runtime else "warn")

        for p in env.problems:
            self._w(f"⚠ {p}", "bad")
        if verbose:
            for n in env.notes:
                self._w(f"· {n}", "warn")
            self._w("403 이 나도 android_vr / ios 클라이언트로 자동 우회합니다.", "dim")
            self._w("──────────────────────────────────────", "info")

    def _repair(self, auto: bool = False):
        """yt-dlp 를 올리고 캐시를 비운 뒤 프로그램을 다시 시작한다.

        재시작이 필요한 이유: 이미 import 된 yt_dlp 모듈은 pip 로 올려도
        현재 프로세스에서는 예전 코드가 그대로 돌기 때문이다.
        """
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(APP_TITLE, "다운로드가 끝난 뒤에 눌러 주세요.")
            return

        msg = ("yt-dlp 를 최신으로 올리고 캐시를 비웁니다.\n"
               "끝나면 프로그램이 자동으로 다시 시작됩니다.\n\n"
               "1분 정도 걸립니다. 계속할까요?")
        if not messagebox.askyesno(APP_TITLE, msg):
            return

        self.btn_fix.configure(state="disabled")
        self.btn_go.configure(state="disabled")
        self.msgq.put(("status", "고치는 중..."))
        threading.Thread(target=self._repair_work, daemon=True).start()

    def _repair_work(self):
        self._w("")
        self._w("── 자동 고치기 ───────────────────────", "info")

        before = core.installed_version()
        ok, msg = core.upgrade_ytdlp(log=lambda m: self._w("  " + m, "dim"))
        if not ok:
            self._w(f"  ✗ {msg}", "bad")
            self.msgq.put(("repair_failed",))
            return

        after = core.installed_version()
        if before != after:
            self._w(f"  ✓ yt-dlp {before} → {after}", "ok")
        else:
            self._w(f"  · yt-dlp {after} (이미 최신)", "dim")

        core.clear_cache()
        self._w("  ✓ 서명 캐시를 비웠습니다", "ok")
        self._w("  프로그램을 다시 시작합니다...", "info")
        self.msgq.put(("restart",))

    def _do_restart(self):
        self._save_settings()
        try:
            # launcher 가 6시간 캐시를 쓰므로, 방금 올린 걸 다시 확인하지 않게 한다
            state = Path(__file__).resolve().parent / ".launcher_state.json"
            import json, time as _t
            state.write_text(json.dumps({"last_check": _t.time()}), encoding="utf-8")
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass
        os.execv(sys.executable, [sys.executable] + sys.argv)

    def _start(self):
        if self.worker and self.worker.is_alive():
            return

        raw = self.urls.get("1.0", "end").strip()
        urls = [u.strip() for u in raw.splitlines() if u.strip()]
        if not urls:
            messagebox.showwarning(APP_TITLE, "영상 주소를 입력하세요.")
            return

        out_dir = self.out_dir.get().strip()
        if not out_dir:
            messagebox.showwarning(APP_TITLE, "저장 폴더를 지정하세요.")
            return
        os.makedirs(out_dir, exist_ok=True)

        self._save_settings()
        self.cancel_flag.clear()
        self.btn_go.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        self.progress["value"] = 0

        self.worker = threading.Thread(target=self._run, args=(urls, out_dir), daemon=True)
        self.worker.start()

    def _cancel(self):
        self.cancel_flag.set()
        self.msgq.put(("status", "취소 중..."))
        self._w("취소 요청됨 - 현재 파일을 마치고 멈춥니다.", "warn")

    def _run(self, urls: list[str], out_dir: str):
        cookies = core.cookie_options(
            self.cookie.get() if self.cookie.get() != "__file__" else None,
            self.cookie_file or None,
        )

        self._w("")
        self._w(f"── 총 {len(urls)}개 · {out_dir}", "info")

        ok = fail = 0
        blocked = 0          # 403 으로 막힌 건수
        preferred: core.Strategy | None = None

        for i, url in enumerate(urls, 1):
            if self.cancel_flag.is_set():
                break

            self.msgq.put(("status", f"({i}/{len(urls)}) 다운로드 중..."))
            self.msgq.put(("progress", (i - 1) / len(urls) * 100))
            self._w(f"▶ ({i}/{len(urls)}) {url}", "info")

            def hook(d):
                if d.get("status") == "downloading":
                    total = d.get("total_bytes") or d.get("total_bytes_estimate")
                    got = d.get("downloaded_bytes", 0)
                    if total:
                        frac = got / total
                        overall = ((i - 1) + frac) / len(urls) * 100
                        self.msgq.put(("progress", overall))
                        pct = frac * 100
                        spd = d.get("speed") or 0
                        self.msgq.put((
                            "status",
                            f"({i}/{len(urls)}) {pct:5.1f}%  {spd/1024/1024:.1f} MB/s"
                            if spd else f"({i}/{len(urls)}) {pct:5.1f}%",
                        ))

            res = core.download_one(
                url, out_dir,
                quality=self.quality.get(),
                cookies=cookies,
                log=lambda m: self._w(m, "warn"),
                progress_hook=hook,
                should_cancel=self.cancel_flag.is_set,
                preferred=preferred,
            )

            if res.ok:
                ok += 1
                preferred = next((s for s in core.STRATEGIES if s.name == res.strategy), None)
                name = res.title or Path(res.filepath or url).name
                suffix = "" if res.strategy == "기본" else f"   [{res.strategy} 로 우회]"
                self._w(f"    ✓ {name}{suffix}", "ok")
            else:
                fail += 1
                if res.error and "403" in res.error:
                    blocked += 1
                self._w(f"    ✗ {res.error}", "bad")

        self.msgq.put(("progress", 100))
        self._w(f"── 완료: 성공 {ok} / 실패 {fail}", "ok" if fail == 0 else "warn")
        self.msgq.put(("status", f"끝났습니다 — 성공 {ok}개, 실패 {fail}개"))
        self.msgq.put(("done",))

        # 전부 403 으로 막혔으면 물어보지 말고 고치기를 제안한다
        if ok == 0 and blocked > 0 and not self.cancel_flag.is_set():
            self.msgq.put(("offer_repair",))

    def _on_finish(self):
        self.btn_go.configure(state="normal")
        self.btn_cancel.configure(state="disabled")


def main():
    root = tk.Tk()
    try:
        ttk.Style().theme_use("vista" if sys.platform == "win32" else "clam")
    except Exception:
        pass
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
