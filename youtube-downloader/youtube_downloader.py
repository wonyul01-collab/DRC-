"""
영상 다운로더 — 화면.

customtkinter 가 있으면 그걸 쓰고, 없으면 기본 tkinter 로 돌아간다.
집 노트북에 뭐가 깔려 있든 프로그램은 떠야 한다.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ytdl_core as core
import ui_theme as T

try:
    import customtkinter as ctk
    HAVE_CTK = True
except Exception:
    HAVE_CTK = False


APP_TITLE = "영상 다운로더"
HERE = Path(__file__).resolve().parent
SETTINGS_PATH = Path.home() / ".youtube_downloader.json"

QUALITY_CHOICES = [
    ("최고 화질", "best"),
    ("1080p 이하", "1080"),
    ("720p 이하", "720"),
    ("음성만 (MP3)", "audio"),
]

COOKIE_CHOICES = [
    ("사용 안 함", ""),
    ("Firefox", "firefox"),
    ("Edge", "edge"),
    ("Chrome", "chrome"),
    ("Whale", "whale"),
    ("쿠키 파일 고르기", "__file__"),
]

PLACEHOLDER = "여기에 유튜브 주소를 붙여넣으세요.\n여러 개면 한 줄에 하나씩."


class App:
    def __init__(self, root):
        self.root = root
        self.msgq: queue.Queue = queue.Queue()
        self.worker: threading.Thread | None = None
        self.cancel_flag = threading.Event()
        self.settings = self._load_settings()
        self._placeholder_on = False

        root.title(APP_TITLE)
        root.geometry("860x800")
        root.minsize(760, 700)
        self._set_window_icon()

        self._build()
        self._pump()
        self.root.after(300, self._startup_check)

    # ---------------- 저장 ----------------

    def _load_settings(self) -> dict:
        import json
        try:
            return json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_settings(self):
        import json
        try:
            SETTINGS_PATH.write_text(json.dumps({
                "out_dir": self.out_dir.get(),
                "quality": self.quality,
                "cookie": self.cookie,
                "cookie_file": self.cookie_file,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _set_window_icon(self):
        ico = HERE / "assets" / "icon.ico"
        if not ico.is_file():
            ico = HERE / "icon.ico"
        try:
            if ico.is_file() and sys.platform == "win32":
                self.root.iconbitmap(str(ico))
        except Exception:
            pass

    # ---------------- 위젯 도우미 ----------------

    def _frame(self, parent, **kw):
        if HAVE_CTK:
            return ctk.CTkFrame(parent, fg_color=T.CARD, corner_radius=T.RADIUS,
                                border_width=1, border_color=T.CARD_EDGE, **kw)
        return tk.Frame(parent, bg=T.CARD[0], highlightbackground=T.CARD_EDGE[0],
                        highlightthickness=1)

    def _label(self, parent, text, *, size=13, bold=False, color=None, **kw):
        color = color or T.TEXT
        if HAVE_CTK:
            return ctk.CTkLabel(parent, text=text, text_color=color,
                                font=ctk.CTkFont(family=T.FONT_UI, size=size,
                                                 weight="bold" if bold else "normal"), **kw)
        return tk.Label(parent, text=text, bg=T.CARD[0], fg=color[0],
                        font=(T.FONT_UI, size, "bold" if bold else "normal"))

    # ---------------- 화면 ----------------

    def _build(self):
        if HAVE_CTK:
            self.root.configure(fg_color=T.BG)
        else:
            self.root.configure(bg=T.BG[0])

        outer = ctk.CTkFrame(self.root, fg_color="transparent") if HAVE_CTK \
            else tk.Frame(self.root, bg=T.BG[0])
        outer.pack(fill="both", expand=True, padx=T.PAD, pady=T.PAD)

        self._build_header(outer)
        self._build_input(outer)
        self._build_options(outer)
        self._build_action(outer)
        self._build_log(outer)

    def _build_header(self, parent):
        bar = ctk.CTkFrame(parent, fg_color="transparent") if HAVE_CTK \
            else tk.Frame(parent, bg=T.BG[0])
        bar.pack(fill="x", pady=(0, T.GAP))

        title = self._label(bar, APP_TITLE, size=22, bold=True)
        if not HAVE_CTK:
            title.configure(bg=T.BG[0])
        title.pack(side="left")

        sub = self._label(bar, "유튜브 주소를 넣으면 영상 파일로 저장합니다",
                          size=12, color=T.TEXT_SUB)
        if not HAVE_CTK:
            sub.configure(bg=T.BG[0])
        sub.pack(side="left", padx=(12, 0), pady=(8, 0))

        self.env_chip = self._label(bar, "", size=11, color=T.TEXT_SUB)
        if not HAVE_CTK:
            self.env_chip.configure(bg=T.BG[0])
        self.env_chip.pack(side="right", pady=(8, 0))

    def _build_input(self, parent):
        card = self._frame(parent)
        card.pack(fill="x", pady=(0, T.GAP))

        head = ctk.CTkFrame(card, fg_color="transparent") if HAVE_CTK \
            else tk.Frame(card, bg=T.CARD[0])
        head.pack(fill="x", padx=T.INNER, pady=(T.INNER, 6))
        self._label(head, "영상 주소", size=13, bold=True).pack(side="left")

        if HAVE_CTK:
            ctk.CTkButton(head, text="붙여넣기", width=78, height=28,
                          corner_radius=8, fg_color="transparent",
                          text_color=T.ACCENT, hover_color=T.BG,
                          border_width=1, border_color=T.CARD_EDGE,
                          font=ctk.CTkFont(family=T.FONT_UI, size=12),
                          command=self._paste).pack(side="right")
            ctk.CTkButton(head, text="지우기", width=64, height=28,
                          corner_radius=8, fg_color="transparent",
                          text_color=T.TEXT_SUB, hover_color=T.BG,
                          border_width=1, border_color=T.CARD_EDGE,
                          font=ctk.CTkFont(family=T.FONT_UI, size=12),
                          command=self._clear).pack(side="right", padx=6)
            self.urls = ctk.CTkTextbox(
                card, height=110, corner_radius=8, border_width=1,
                border_color=T.CARD_EDGE, fg_color=T.BG,
                font=ctk.CTkFont(family=T.FONT_MONO, size=12),
            )
        else:
            tk.Button(head, text="붙여넣기", command=self._paste).pack(side="right")
            tk.Button(head, text="지우기", command=self._clear).pack(side="right", padx=6)
            self.urls = tk.Text(card, height=6, font=(T.FONT_MONO, 10))

        self.urls.pack(fill="x", padx=T.INNER, pady=(0, T.INNER))
        self._show_placeholder()
        self.urls.bind("<FocusIn>", self._clear_placeholder)
        self.urls.bind("<FocusOut>", self._maybe_placeholder)

    def _build_options(self, parent):
        card = self._frame(parent)
        card.pack(fill="x", pady=(0, T.GAP))

        # 저장 폴더
        r1 = ctk.CTkFrame(card, fg_color="transparent") if HAVE_CTK \
            else tk.Frame(card, bg=T.CARD[0])
        r1.pack(fill="x", padx=T.INNER, pady=(T.INNER, 8))
        self._label(r1, "저장 폴더", size=12, bold=True, width=70, anchor="w").pack(side="left")

        default_dir = self.settings.get("out_dir") or str(Path.home() / "Downloads" / "영상다운로드")
        self.out_dir = tk.StringVar(value=default_dir)

        if HAVE_CTK:
            ctk.CTkEntry(r1, textvariable=self.out_dir, height=32, corner_radius=8,
                         border_color=T.CARD_EDGE, fg_color=T.BG,
                         font=ctk.CTkFont(family=T.FONT_UI, size=12)
                         ).pack(side="left", fill="x", expand=True, padx=(8, 8))
            for txt, cmd in (("찾아보기", self._browse), ("열기", self._open_folder)):
                ctk.CTkButton(r1, text=txt, width=72, height=32, corner_radius=8,
                              fg_color="transparent", text_color=T.TEXT,
                              hover_color=T.BG, border_width=1, border_color=T.CARD_EDGE,
                              font=ctk.CTkFont(family=T.FONT_UI, size=12),
                              command=cmd).pack(side="left", padx=(0, 6))
        else:
            tk.Entry(r1, textvariable=self.out_dir).pack(side="left", fill="x", expand=True, padx=8)
            tk.Button(r1, text="찾아보기", command=self._browse).pack(side="left")
            tk.Button(r1, text="열기", command=self._open_folder).pack(side="left", padx=6)

        # 화질 / 쿠키
        r2 = ctk.CTkFrame(card, fg_color="transparent") if HAVE_CTK \
            else tk.Frame(card, bg=T.CARD[0])
        r2.pack(fill="x", padx=T.INNER, pady=(0, T.INNER))

        self.quality = self.settings.get("quality", "best")
        self.cookie = self.settings.get("cookie", "")
        self.cookie_file = self.settings.get("cookie_file", "")

        self._label(r2, "화질", size=12, bold=True, width=70, anchor="w").pack(side="left")
        qlabels = [lbl for lbl, _ in QUALITY_CHOICES]
        qcur = next((l for l, v in QUALITY_CHOICES if v == self.quality), qlabels[0])
        if HAVE_CTK:
            self.qmenu = ctk.CTkOptionMenu(
                r2, values=qlabels, width=150, height=32, corner_radius=8,
                fg_color=T.BG, button_color=T.CARD_EDGE, button_hover_color=T.ACCENT,
                text_color=T.TEXT, font=ctk.CTkFont(family=T.FONT_UI, size=12),
                command=self._on_quality)
            self.qmenu.set(qcur)
            self.qmenu.pack(side="left", padx=(8, 24))
        else:
            self.qmenu = tk.StringVar(value=qcur)
            tk.OptionMenu(r2, self.qmenu, *qlabels,
                          command=self._on_quality).pack(side="left", padx=8)

        self._label(r2, "브라우저 쿠키", size=12, bold=True, anchor="w").pack(side="left")
        clabels = [lbl for lbl, _ in COOKIE_CHOICES]
        ccur = next((l for l, v in COOKIE_CHOICES if v == self.cookie), clabels[0])
        if HAVE_CTK:
            self.cmenu = ctk.CTkOptionMenu(
                r2, values=clabels, width=160, height=32, corner_radius=8,
                fg_color=T.BG, button_color=T.CARD_EDGE, button_hover_color=T.ACCENT,
                text_color=T.TEXT, font=ctk.CTkFont(family=T.FONT_UI, size=12),
                command=self._on_cookie)
            self.cmenu.set(ccur)
            self.cmenu.pack(side="left", padx=8)
        else:
            self.cmenu = tk.StringVar(value=ccur)
            tk.OptionMenu(r2, self.cmenu, *clabels,
                          command=self._on_cookie).pack(side="left", padx=8)

    def _build_action(self, parent):
        bar = ctk.CTkFrame(parent, fg_color="transparent") if HAVE_CTK \
            else tk.Frame(parent, bg=T.BG[0])
        bar.pack(fill="x", pady=(0, T.GAP))

        if HAVE_CTK:
            self.btn_go = ctk.CTkButton(
                bar, text="다운로드 시작", width=190, height=46, corner_radius=10,
                fg_color=T.ACCENT, hover_color=T.ACCENT_HOVER, text_color="#FFFFFF",
                font=ctk.CTkFont(family=T.FONT_UI, size=15, weight="bold"),
                command=self._start)
            self.btn_go.pack(side="left")
            self.btn_cancel = ctk.CTkButton(
                bar, text="취소", width=88, height=46, corner_radius=10,
                fg_color="transparent", text_color=T.TEXT_SUB, hover_color=T.CARD,
                border_width=1, border_color=T.CARD_EDGE,
                font=ctk.CTkFont(family=T.FONT_UI, size=13),
                state="disabled", command=self._cancel)
            self.btn_cancel.pack(side="left", padx=8)

            self.btn_fix = ctk.CTkButton(
                bar, text="자동 고치기", width=110, height=46, corner_radius=10,
                fg_color="transparent", text_color=T.TEXT, hover_color=T.CARD,
                border_width=1, border_color=T.CARD_EDGE,
                font=ctk.CTkFont(family=T.FONT_UI, size=13), command=self._repair)
            self.btn_fix.pack(side="right")
            ctk.CTkButton(bar, text="문제 진단", width=100, height=46, corner_radius=10,
                          fg_color="transparent", text_color=T.TEXT_SUB, hover_color=T.CARD,
                          border_width=1, border_color=T.CARD_EDGE,
                          font=ctk.CTkFont(family=T.FONT_UI, size=13),
                          command=self._diagnose).pack(side="right", padx=8)
        else:
            self.btn_go = tk.Button(bar, text="다운로드 시작", command=self._start)
            self.btn_go.pack(side="left")
            self.btn_cancel = tk.Button(bar, text="취소", state="disabled", command=self._cancel)
            self.btn_cancel.pack(side="left", padx=8)
            self.btn_fix = tk.Button(bar, text="자동 고치기", command=self._repair)
            self.btn_fix.pack(side="right")
            tk.Button(bar, text="문제 진단", command=self._diagnose).pack(side="right", padx=8)

        # 진행 표시
        prog = ctk.CTkFrame(parent, fg_color="transparent") if HAVE_CTK \
            else tk.Frame(parent, bg=T.BG[0])
        prog.pack(fill="x", pady=(0, T.GAP))

        if HAVE_CTK:
            self.progress = ctk.CTkProgressBar(prog, height=6, corner_radius=0,
                                               progress_color=T.ACCENT, fg_color=T.CARD_EDGE)
            self.progress.set(0)
            self.progress.pack(fill="x")
            self.status_lbl = ctk.CTkLabel(
                prog, text="대기 중", text_color=T.TEXT_SUB, anchor="w",
                font=ctk.CTkFont(family=T.FONT_UI, size=12))
            self.status_lbl.pack(fill="x", pady=(6, 0))
        else:
            from tkinter import ttk
            self.progress = ttk.Progressbar(prog, maximum=1.0)
            self.progress.pack(fill="x")
            self.status_var = tk.StringVar(value="대기 중")
            self.status_lbl = tk.Label(prog, textvariable=self.status_var,
                                       bg=T.BG[0], fg=T.TEXT_SUB[0], anchor="w")
            self.status_lbl.pack(fill="x")

    def _build_log(self, parent):
        card = self._frame(parent)
        card.pack(fill="both", expand=True)

        self._label(card, "진행 기록", size=13, bold=True).pack(
            anchor="w", padx=T.INNER, pady=(T.INNER, 6))

        wrap = tk.Frame(card, bg=T.LOG_BG, highlightthickness=0, bd=0)
        wrap.pack(fill="both", expand=True, padx=T.INNER, pady=(0, T.INNER))

        self.log = tk.Text(wrap, bg=T.LOG_BG, fg=T.LOG_FG, insertbackground=T.LOG_FG,
                           font=(T.FONT_MONO, 10), wrap="word", relief="flat",
                           borderwidth=0, highlightthickness=0,
                           padx=12, pady=10, height=12)
        if HAVE_CTK:
            sb = ctk.CTkScrollbar(wrap, command=self.log.yview, width=14,
                                  fg_color=T.LOG_BG, button_color="#3F3F46",
                                  button_hover_color="#52525B", corner_radius=7)
        else:
            sb = tk.Scrollbar(wrap, command=self.log.yview, width=12,
                              bg=T.LOG_BG, troughcolor=T.LOG_BG, borderwidth=0,
                              highlightthickness=0, activebackground="#3F3F46")
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y", padx=(0, 2), pady=2)
        self.log.pack(side="left", fill="both", expand=True)

        for tag, color in T.LOG_COLORS.items():
            self.log.tag_configure(tag, foreground=color)
        self.log.tag_configure("head", font=(T.FONT_MONO, 10, "bold"))
        self.log.configure(state="disabled")

    # ---------------- 안내문구 ----------------

    def _show_placeholder(self):
        self.urls.delete("1.0", "end")
        self.urls.insert("1.0", PLACEHOLDER)
        self._placeholder_on = True
        try:
            self.urls.configure(text_color=T.TEXT_SUB if HAVE_CTK else T.TEXT_SUB[0])
        except Exception:
            pass

    def _clear_placeholder(self, _=None):
        if self._placeholder_on:
            self.urls.delete("1.0", "end")
            self._placeholder_on = False
            try:
                self.urls.configure(text_color=T.TEXT if HAVE_CTK else T.TEXT[0])
            except Exception:
                pass

    def _maybe_placeholder(self, _=None):
        if not self.urls.get("1.0", "end").strip():
            self._show_placeholder()

    def _read_urls(self) -> list[str]:
        if self._placeholder_on:
            return []
        raw = self.urls.get("1.0", "end").strip()
        return [u.strip() for u in raw.splitlines() if u.strip()]

    # ---------------- 로그 / 펌프 ----------------

    def _w(self, text: str, tag: str = ""):
        self.msgq.put(("log", text, tag))

    def _set_status(self, text: str):
        if HAVE_CTK:
            self.status_lbl.configure(text=text)
        else:
            self.status_var.set(text)

    def _set_progress(self, frac: float):
        if HAVE_CTK:
            self.progress.set(max(0.0, min(1.0, frac)))
        else:
            self.progress["value"] = max(0.0, min(1.0, frac))

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
                    self._set_status(rest[0])
                elif kind == "progress":
                    self._set_progress(rest[0])
                elif kind == "chip":
                    self.env_chip.configure(text=rest[0])
                elif kind == "done":
                    self._on_finish()
                elif kind == "restart":
                    self._do_restart()
                    return
                elif kind == "repair_failed":
                    self.btn_fix.configure(state="normal")
                    self.btn_go.configure(state="normal")
                    self._set_status("고치기 실패 — 인터넷 연결을 확인하세요")
                elif kind == "offer_repair":
                    self._set_status("전부 403 으로 막혔습니다")
                    if messagebox.askyesno(
                        APP_TITLE,
                        "모든 방법이 403 으로 막혔습니다.\n\n"
                        "yt-dlp 가 낡은 것이 가장 흔한 원인입니다.\n"
                        "지금 자동으로 고칠까요?\n\n"
                        "(최신화 → 캐시 정리 → 다시 시작)",
                    ):
                        self._repair()
        except queue.Empty:
            pass
        self.root.after(80, self._pump)

    # ---------------- 동작 ----------------

    def _paste(self):
        try:
            self._clear_placeholder()
            self.urls.insert("end", self.root.clipboard_get().strip() + "\n")
        except Exception:
            pass

    def _clear(self):
        self.urls.delete("1.0", "end")
        self._placeholder_on = False
        self._show_placeholder()

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

    def _on_quality(self, label):
        self.quality = next((v for l, v in QUALITY_CHOICES if l == label), "best")

    def _on_cookie(self, label):
        value = next((v for l, v in COOKIE_CHOICES if l == label), "")
        if value == "__file__":
            path = filedialog.askopenfilename(
                title="cookies.txt 고르기",
                filetypes=[("쿠키 파일", "*.txt"), ("모든 파일", "*.*")])
            if path:
                self.cookie_file = path
                self.cookie = "__file__"
                self._w(f"쿠키 파일: {path}", "dim")
            else:
                self.cookie = ""
                if HAVE_CTK:
                    self.cmenu.set(COOKIE_CHOICES[0][0])
        else:
            self.cookie = value
            self.cookie_file = ""
            if value == "chrome":
                self._w("Chrome 은 127 버전부터 쿠키 추출이 막혀 있습니다. "
                        "안 되면 Firefox 나 쿠키 파일을 쓰세요.", "warn")

    def _startup_check(self):
        self._w(f"{APP_TITLE}  준비됨", "head")
        threading.Thread(target=self._env_scan, args=(False,), daemon=True).start()

    def _diagnose(self):
        self._w("")
        self._w("── 문제 진단 ─────────────────────────", "info")
        threading.Thread(target=self._env_scan, args=(True,), daemon=True).start()

    def _env_scan(self, verbose: bool):
        env = core.check_environment(check_updates=True)
        chip = f"yt-dlp {env.ytdlp_version or '없음'}"
        if env.ytdlp_outdated:
            chip += "  (업데이트 있음)"
        self.msgq.put(("chip", chip))

        if env.ytdlp_version:
            if env.ytdlp_outdated:
                self._w(f"  yt-dlp {env.ytdlp_version} → 최신 {env.ytdlp_latest} 있음", "bad")
            else:
                self._w(f"  yt-dlp {env.ytdlp_version} (최신)", "ok")
        self._w(f"  ffmpeg {'있음' if env.ffmpeg else '없음'}", "ok" if env.ffmpeg else "warn")
        self._w(f"  JS 런타임 {env.js_runtime or '없음'}", "ok" if env.js_runtime else "warn")

        for p in env.problems:
            self._w(f"  ! {p}", "bad")
        if verbose:
            for n in env.notes:
                self._w(f"  · {n}", "warn")
            self._w("  403 이 나도 android_vr / ios 로 자동 우회합니다.", "dim")
            self._w("──────────────────────────────────────", "info")

    def _start(self):
        if self.worker and self.worker.is_alive():
            return
        urls = self._read_urls()
        if not urls:
            messagebox.showwarning(APP_TITLE, "영상 주소를 넣어 주세요.")
            return
        out_dir = self.out_dir.get().strip()
        if not out_dir:
            messagebox.showwarning(APP_TITLE, "저장 폴더를 정해 주세요.")
            return
        os.makedirs(out_dir, exist_ok=True)

        self._save_settings()
        self.cancel_flag.clear()
        self.btn_go.configure(state="disabled")
        self.btn_cancel.configure(state="normal")
        self._set_progress(0)

        self.worker = threading.Thread(target=self._run, args=(urls, out_dir), daemon=True)
        self.worker.start()

    def _cancel(self):
        self.cancel_flag.set()
        self.msgq.put(("status", "취소 중..."))
        self._w("  취소 요청됨 — 현재 파일을 마치고 멈춥니다.", "warn")

    def _run(self, urls: list[str], out_dir: str):
        cookies = core.cookie_options(
            self.cookie if self.cookie != "__file__" else None,
            self.cookie_file or None)

        self._w("")
        self._w(f"── 총 {len(urls)}개 · {out_dir}", "info")

        ok = fail = blocked = 0
        preferred: core.Strategy | None = None

        for i, url in enumerate(urls, 1):
            if self.cancel_flag.is_set():
                break
            self.msgq.put(("status", f"({i}/{len(urls)}) 준비 중..."))
            self.msgq.put(("progress", (i - 1) / len(urls)))
            self._w(f"▶ ({i}/{len(urls)}) {url}", "info")

            def hook(d, _i=i):
                if d.get("status") != "downloading":
                    return
                total = d.get("total_bytes") or d.get("total_bytes_estimate")
                if not total:
                    return
                frac = d.get("downloaded_bytes", 0) / total
                self.msgq.put(("progress", ((_i - 1) + frac) / len(urls)))
                spd = d.get("speed") or 0
                txt = f"({_i}/{len(urls)}) {frac*100:5.1f}%"
                if spd:
                    txt += f"   {spd/1024/1024:.1f} MB/s"
                self.msgq.put(("status", txt))

            res = core.download_one(
                url, out_dir, quality=self.quality, cookies=cookies,
                log=lambda m: self._w(m, "warn"), progress_hook=hook,
                should_cancel=self.cancel_flag.is_set, preferred=preferred)

            if res.ok:
                ok += 1
                preferred = next((s for s in core.STRATEGIES if s.name == res.strategy), None)
                name = res.title or Path(res.filepath or url).name
                tail = "" if res.strategy == "기본" else f"   [{res.strategy} 로 우회]"
                self._w(f"    ✓ {name}{tail}", "ok")
            else:
                fail += 1
                if res.error and "403" in res.error:
                    blocked += 1
                self._w(f"    ✗ {res.error}", "bad")

        self.msgq.put(("progress", 1.0))
        self._w(f"── 완료: 성공 {ok} / 실패 {fail}", "ok" if fail == 0 else "warn")
        self.msgq.put(("status", f"끝났습니다 — 성공 {ok}개, 실패 {fail}개"))
        self.msgq.put(("done",))

        if ok == 0 and blocked > 0 and not self.cancel_flag.is_set():
            self.msgq.put(("offer_repair",))

    def _on_finish(self):
        self.btn_go.configure(state="normal")
        self.btn_cancel.configure(state="disabled")

    # ---------------- 자동 고치기 ----------------

    def _repair(self):
        if self.worker and self.worker.is_alive():
            messagebox.showinfo(APP_TITLE, "다운로드가 끝난 뒤에 눌러 주세요.")
            return
        if not messagebox.askyesno(
            APP_TITLE,
            "yt-dlp 를 최신으로 올리고 캐시를 비웁니다.\n"
            "끝나면 프로그램이 저절로 다시 시작됩니다.\n\n"
            "1분 정도 걸립니다. 계속할까요?",
        ):
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
        self._w(f"  ✓ yt-dlp {before} → {after}" if before != after
                else f"  · yt-dlp {after} (이미 최신)", "ok" if before != after else "dim")
        core.clear_cache()
        self._w("  ✓ 서명 캐시를 비웠습니다", "ok")
        self._w("  다시 시작합니다...", "info")
        self.msgq.put(("restart",))

    def _do_restart(self):
        self._save_settings()
        try:
            import json, time
            (HERE / ".launcher_state.json").write_text(
                json.dumps({"last_check": time.time()}), encoding="utf-8")
        except Exception:
            pass
        try:
            self.root.destroy()
        except Exception:
            pass
        os.execv(sys.executable, [sys.executable] + sys.argv)


def main():
    if HAVE_CTK:
        ctk.set_appearance_mode("system")
        root = ctk.CTk()
    else:
        root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
