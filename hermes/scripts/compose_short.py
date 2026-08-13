#!/usr/bin/env python3
"""쇼츠 합성 — 생성된 클립 + TTS 나레이션 + 한글 자막을 하나의 세로 영상으로 만든다.

Higgsfield는 클립을 만들어 주지만, 한글 자막과 한국어 나레이션은 못 넣습니다.
그 마지막 한 뼘을 여기서 ffmpeg로 처리합니다.

사용 예:
  # 의존성 확인
  python compose_short.py check

  # 합성
  python compose_short.py build \
      --shotlist out/plans/2026-08-13-01.shotlist.json \
      --style ~/.hermes/workspace/youtube/reference-style.yaml \
      --out out/video/2026-08-13-01.mp4

shotlist.json 형식:
{
  "id": "2026-08-13-01",
  "shots": [
    {"clip": "out/video/raw/01.mp4", "narration": "읽을 문장", "subtitle": "띄울 자막",
     "note": "체중 70kg 기준"},
    {"clip": "out/video/raw/02.mp4", "narration": "다음 문장"}
  ]
}
  - subtitle 을 생략하면 narration 을 그대로 자막으로 씁니다.
  - note 는 보조 자막입니다. 출처·기준값·다음 편 예고처럼 본문을 방해하지 않고
    작게 깔아야 하는 것에 씁니다. 쪼개지 않고 그 shot 전체에 한 줄로 표시됩니다.
    크기·색·위치는 스타일 파일의 subtitle.secondary 에서 조정합니다.
  - shotlist 최상위에 "audio": "narration.mp3" 를 두면 그 파일 하나를 전체에
    깔고 각 shot 은 duration 으로 나뉩니다. 타입캐스트 같은 유료 TTS 에서
    한 번에 내보낸 나레이션을 쓸 때 편합니다. 이때는 모든 shot 에 duration 이
    있어야 합니다.
  - clip 에 "@black" 을 쓰면 검은 화면을 스크립트가 직접 만듭니다. 생성 크레딧이
    들지 않습니다. 절단마공 엔딩의 블랙아웃에 씁니다. "@color:0x101820" 도 됩니다.
  - voice.provider 가 none 이면 각 shot 에 "duration"(초)이 있어야 합니다.
  - narration 이 빈 문자열이면 그 shot 은 무음으로 처리하고 duration 을 씁니다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

W, H = 1080, 1920
# 나레이션 사이에 넣는 최소 숨. 0이면 말이 붙어서 답답해집니다.
SHOT_PADDING = 0.12


# --------------------------------------------------------------------------
# 유틸
# --------------------------------------------------------------------------

def run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.exit(f"명령 실패: {' '.join(cmd[:4])} ...\n{proc.stderr[-2000:]}")


def probe_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    if out.returncode != 0 or not out.stdout.strip():
        sys.exit(f"길이를 읽을 수 없습니다: {path}")
    return float(out.stdout.strip())


def load_style(path: Path) -> dict:
    if not path.is_file():
        sys.exit(f"스타일 파일이 없습니다: {path}\n"
                 "content/reference-style.example.yaml 를 복사해서 채우세요.")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _windows_font_families() -> list[str]:
    """Windows 에 설치된 폰트의 '패밀리명'을 모은다.

    파일명(stem)은 패밀리명이 아니다 — malgun.ttf 의 패밀리는 "Malgun Gothic" 이다.
    그래서 레지스트리를 1순위로 읽고, 파일 스캔은 보조로만 쓴다.
    사용자 폴더 설치 폰트(관리자 권한 없이 설치한 것)는 HKCU 와
    %LOCALAPPDATA%\\Microsoft\\Windows\\Fonts 에 들어간다. 둘 다 봐야 한다.
    """
    names: set[str] = set()

    try:
        import winreg  # Windows 전용 표준 라이브러리

        subkey = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Fonts"
        for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
            try:
                with winreg.OpenKey(root, subkey) as key:
                    for i in range(winreg.QueryInfoKey(key)[1]):
                        value_name = winreg.EnumValue(key, i)[0]
                        # "Pretendard Regular (OpenType)" -> "Pretendard Regular"
                        cleaned = re.sub(r"\s*\([^)]*\)\s*$", "", value_name).strip()
                        # "Malgun Gothic & Malgun Gothic Semilight" -> 각각 등록
                        for part in cleaned.split("&"):
                            part = part.strip()
                            if part:
                                names.add(part)
            except OSError:
                continue
    except ImportError:
        pass

    # 보조: 폰트 폴더 파일명. 레지스트리에 없는 것을 놓치지 않기 위해서다.
    # .otf 를 반드시 포함한다 — Pretendard 가 OTF 로 배포된다.
    font_dirs = [Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"]
    local = os.environ.get("LOCALAPPDATA")
    if local:
        font_dirs.append(Path(local) / "Microsoft" / "Windows" / "Fonts")
    for directory in font_dirs:
        if not directory.is_dir():
            continue
        for pattern in ("*.ttf", "*.ttc", "*.otf", "*.TTF", "*.OTF"):
            for path in directory.glob(pattern):
                names.add(path.stem)

    return sorted(names)


def installed_font_families() -> list[str] | None:
    """설치된 폰트 패밀리 목록. 확인할 방법이 없으면 None."""
    if shutil.which("fc-list"):
        out = subprocess.run(["fc-list", ":lang=ko", "family"],
                             capture_output=True, text=True)
        if out.returncode == 0:
            families: set[str] = set()
            for line in out.stdout.splitlines():
                families.update(part.strip() for part in line.split(","))
            if families:
                return sorted(f for f in families if f)
    if sys.platform == "win32":
        found = _windows_font_families()
        return found or None
    return None


def font_is_installed(font_family: str) -> tuple[bool | None, list[str]]:
    """(설치 여부, 후보 목록). 확인할 방법이 없으면 여부가 None."""
    families = installed_font_families()
    if families is None or not font_family:
        return None, families or []
    target = font_family.lower()
    ok = any(target == f.lower() or target in f.lower() for f in families)
    return ok, families


def warn_if_font_missing(font_family: str) -> bool:
    """폰트명이 틀리면 ffmpeg가 조용히 기본 폰트로 떨어진다. 미리 잡는다."""
    ok, families = font_is_installed(font_family)
    if ok is not False:
        return True
    hint = ", ".join(f for f in families if any(
        k in f.lower() for k in ("noto", "malgun", "pretendard", "nanum", "gothic", "gulim", "batang")
    )) or ", ".join(families[:10])
    print(
        f"경고: 폰트 '{font_family}' 를 찾지 못했습니다. 자막이 기본 폰트로 나오거나 깨집니다.\n"
        f"       스타일 파일의 subtitle.font_family 를 아래 중 하나로 바꾸세요:\n"
        f"       {hint}\n"
        f"       (또는 subtitle.font_file 에 폰트 파일 절대경로를 지정하면 이 검사를 건너뜁니다)",
        file=sys.stderr,
    )
    return False


# --------------------------------------------------------------------------
# TTS
# --------------------------------------------------------------------------

def synth_edge(text: str, voice_cfg: dict, out_path: Path) -> None:
    import asyncio

    import edge_tts

    async def go() -> None:
        comm = edge_tts.Communicate(
            text,
            voice_cfg.get("name", "ko-KR-InJoonNeural"),
            rate=voice_cfg.get("rate", "+0%"),
            pitch=voice_cfg.get("pitch", "+0Hz"),
            volume=voice_cfg.get("volume", "+0%"),
        )
        await comm.save(str(out_path))

    asyncio.run(go())


def synth_narration(text: str, voice_cfg: dict, out_path: Path) -> None:
    provider = voice_cfg.get("provider", "edge")
    if provider == "edge":
        synth_edge(text, voice_cfg, out_path)
    elif provider == "elevenlabs":
        sys.exit("ElevenLabs 연동은 아직 없습니다. voice.provider 를 edge 로 두거나 "
                 "shotlist 에 audio 경로를 직접 지정하세요.")
    else:
        sys.exit(f"알 수 없는 voice.provider: {provider}")


# --------------------------------------------------------------------------
# 자막 (ASS)
# --------------------------------------------------------------------------

def ass_time(seconds: float) -> str:
    seconds = max(0.0, seconds)
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def chunk_text(text: str, max_chars: int) -> list[str]:
    """자막을 max_chars 이하 덩어리로 쪼갠다. 단어 경계를 지킨다."""
    text = text.strip()
    if not text:
        return []
    if max_chars <= 0 or len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if len(candidate) <= max_chars:
            current = candidate
            continue
        if current:
            chunks.append(current)
        # 한 단어가 통째로 길면 강제로 자른다
        while len(word) > max_chars:
            chunks.append(word[:max_chars])
            word = word[max_chars:]
        current = word
    if current:
        chunks.append(current)
    return chunks


def _style_line(name: str, font_name: str, cfg: dict, defaults: dict) -> str:
    def get(key: str):
        return cfg.get(key, defaults[key])

    return ",".join([
        name,
        font_name,
        str(get("font_size")),
        get("primary_color"),
        "&H000000FF",                                   # SecondaryColour (미사용)
        get("outline_color"),
        "&H00000000",                                   # BackColour
        "-1" if get("bold") else "0",
        "0", "0", "0",                                  # Italic, Underline, StrikeOut
        "100", "100", "0", "0",                         # Scale/Spacing/Angle
        "1",                                            # BorderStyle: outline+shadow
        str(get("outline_width")),
        str(get("shadow")),
        str(get("alignment")),
        "80", "80",                                     # MarginL, MarginR
        str(get("margin_vertical")),
        "1",                                            # Encoding
    ])


# 본 자막. 세로 1920 기준 margin_vertical 700 이면 화면 아래에서 약 36%,
# 즉 하단 1/3~2/5 지점입니다. 쇼츠 UI 를 확실히 피하고 시선이 머무는 자리입니다.
PRIMARY_DEFAULTS = {
    "font_size": 96,
    "primary_color": "&H00FFFFFF",
    "outline_color": "&H00000000",
    "outline_width": 6,
    "shadow": 0,
    "bold": True,
    "alignment": 2,
    "margin_vertical": 700,
}

# 보조 자막(출처·기준값·다음 편 예고). 본 자막보다 작지만
# "읽히지 않을 만큼" 작으면 넣는 의미가 없습니다. 55~75세 시청자 기준입니다.
SECONDARY_DEFAULTS = {
    "font_size": 52,
    "primary_color": "&H00D2D2D2",   # 살짝 어두운 흰색 — 본문과 위계만 만든다
    "outline_color": "&H00000000",
    "outline_width": 4,
    "shadow": 0,
    "bold": False,
    "alignment": 2,
    "margin_vertical": 560,          # 본 자막(700) 바로 아래
}

# 강조색 기본값. ASS 는 &HBBGGRR 순서라 RGB 와 순서가 반대입니다.
DEFAULT_HIGHLIGHT_COLOR = "&H0000D7FF"   # 주황빛 노랑 (RGB FFD700)


def apply_highlight(escaped: str, words: list[str], color: str) -> str:
    """이미 이스케이프된 자막에서 지정한 단어만 색을 바꾼다.

    ASS 인라인 태그를 넣는 것이라 반드시 이스케이프 뒤에 호출해야 한다.
    \\r 은 스타일 기본색으로 되돌린다.
    """
    for word in words:
        word = (word or "").strip()
        if word and word in escaped:
            escaped = escaped.replace(word, f"{{\\c{color}}}{word}{{\\r}}")
    return escaped


def build_ass(cues: list[tuple[float, float, str, str, list[str]]], sub_cfg: dict) -> str:
    """cues 는 (시작, 끝, 텍스트, 스타일명, 강조단어들)."""
    font_name = sub_cfg.get("font_family", "Pretendard")
    if sub_cfg.get("font_file"):
        # fontsdir 로 폰트를 넘길 때도 FontName 은 파일의 실제 패밀리명이어야 합니다.
        font_name = sub_cfg.get("font_family") or Path(sub_cfg["font_file"]).stem

    secondary_cfg = sub_cfg.get("secondary") or {}
    # 보조 자막도 같은 폰트를 쓰되, 따로 지정하면 그쪽을 따릅니다.
    note_font = secondary_cfg.get("font_family", font_name)

    lines = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {W}",
        f"PlayResY: {H}",
        "WrapStyle: 0",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: {_style_line('Default', font_name, sub_cfg, PRIMARY_DEFAULTS)}",
        f"Style: {_style_line('Note', note_font, secondary_cfg, SECONDARY_DEFAULTS)}",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    highlight_color = sub_cfg.get("highlight_color", DEFAULT_HIGHLIGHT_COLOR)
    for start, end, text, style_name, highlights in cues:
        safe = text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")
        if highlights:
            safe = apply_highlight(safe, highlights, highlight_color)
        lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},{style_name},,0,0,0,,{safe}")
    return "\n".join(lines) + "\n"


def escape_for_filter(path: Path) -> str:
    """ffmpeg 필터 인자에 경로를 넣을 때 필요한 이스케이프."""
    return str(path).replace("\\", "\\\\").replace(":", r"\:").replace("'", r"\'")


# --------------------------------------------------------------------------
# 빌드
# --------------------------------------------------------------------------

def make_filler(spec: str, work: Path, idx: int, fps: int) -> Path:
    """생성 클립이 아닌 단색 화면을 만든다. 크레딧이 들지 않는다.

    spec:
      "@black"            검은 화면 (절단마공 엔딩의 블랙아웃)
      "@color:0x101820"   지정한 색 화면
    """
    if spec == "@black":
        color = "black"
    elif spec.startswith("@color:"):
        color = spec.split(":", 1)[1].strip() or "black"
    else:
        sys.exit(f"알 수 없는 클립 지정자: {spec}\n"
                 '쓸 수 있는 값: "@black", "@color:0xRRGGBB"')

    out = work / f"filler{idx:03d}.mp4"
    run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "lavfi", "-t", "2",
        "-i", f"color=c={color}:s={W}x{H}:r={fps}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "24",
        "-pix_fmt", "yuv420p",
        str(out),
    ])
    return out


def cmd_check(args: argparse.Namespace) -> None:
    ok = True
    for tool in ("ffmpeg", "ffprobe"):
        path = shutil.which(tool)
        print(f"{tool:8} {'OK  ' + path if path else '없음 — 설치하세요'}")
        ok = ok and bool(path)
    try:
        import edge_tts  # noqa: F401
        print("edge-tts OK")
    except ImportError:
        print("edge-tts 없음 — pip install edge-tts (voice.provider=edge 를 쓸 때만 필요)")
        ok = False

    # 폰트는 스타일 파일을 알아야 검사할 수 있다. --style 을 주면 실제로 검사한다.
    if args.style:
        style = load_style(Path(args.style).expanduser())
        sub_cfg = style.get("subtitle") or {}
        if sub_cfg.get("font_file"):
            font_path = Path(sub_cfg["font_file"]).expanduser()
            exists = font_path.is_file()
            print(f"폰트     {'OK  ' + str(font_path) if exists else '파일 없음 — ' + str(font_path)}")
            ok = ok and exists
        else:
            family = sub_cfg.get("font_family", "")
            found, families = font_is_installed(family)
            if found is None:
                print(f"폰트     확인 불가 (설치 목록을 읽을 수 없음) — 설정값: {family or '없음'}")
            elif found:
                print(f"폰트     OK  {family}")
            else:
                print(f"폰트     없음 — '{family}'")
                warn_if_font_missing(family)
                ok = False
    else:
        print("폰트     건너뜀 — 검사하려면 --style <reference-style.yaml> 을 주세요")

    sys.exit(0 if ok else 1)


def cmd_build(args: argparse.Namespace) -> None:
    style = load_style(Path(args.style).expanduser())
    sub_cfg = style.get("subtitle") or {}
    voice_cfg = style.get("voice") or {}
    visual_cfg = style.get("visual") or {}
    fps = int(visual_cfg.get("fps", 30))

    if not sub_cfg.get("font_file"):
        warn_if_font_missing(sub_cfg.get("font_family", ""))

    shotlist = json.loads(Path(args.shotlist).expanduser().read_text(encoding="utf-8"))
    shots = shotlist.get("shots") or []
    if not shots:
        sys.exit("shotlist 에 shots 가 없습니다.")

    base = Path(args.shotlist).expanduser().parent
    out_path = Path(args.out).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    work = Path(tempfile.mkdtemp(prefix="short-"))

    # 전체 나레이션 파일 하나를 통째로 까는 방식.
    # 타입캐스트 같은 유료 TTS 에서 문장별로 11개를 따로 받는 것은 번거롭습니다.
    # 한 번에 내보낸 mp3 를 shotlist 최상위 "audio" 에 지정하면
    # 각 shot 은 duration 으로 나뉘고 나레이션은 그 위에 이어서 흐릅니다.
    whole_audio: Path | None = None
    if shotlist.get("audio"):
        whole_audio = Path(shotlist["audio"])
        if not whole_audio.is_absolute():
            whole_audio = base / whole_audio
        if not whole_audio.is_file():
            sys.exit(f"나레이션 파일이 없습니다: {whole_audio}")
        missing = [i for i, s in enumerate(shots) if "duration" not in s]
        if missing:
            sys.exit("전체 나레이션(audio)을 쓸 때는 모든 shot 에 duration 이 필요합니다.\n"
                     f"빠진 shot: {missing}\n"
                     "나레이션을 들으면서 각 문장이 끝나는 시각으로 duration 을 정하세요.")

    silent = whole_audio is not None or voice_cfg.get("provider", "edge") == "none"

    seg_videos: list[Path] = []
    seg_audios: list[Path] = []
    cues: list[tuple[float, float, str, str, list[str]]] = []
    fit_log: list[dict] = []
    timeline = 0.0

    for idx, shot in enumerate(shots):
        # "@black" 은 생성 클립이 아니라 스크립트가 만드는 검은 화면입니다.
        # 절단마공 엔딩의 블랙아웃에 씁니다. Higgsfield 크레딧이 들지 않습니다.
        raw_clip = str(shot["clip"])
        if raw_clip.startswith("@"):
            clip = make_filler(raw_clip, work, idx, fps)
        else:
            clip = Path(raw_clip)
            if not clip.is_absolute():
                clip = base / clip
            if not clip.is_file():
                sys.exit(f"클립이 없습니다: {clip}")

        narration = (shot.get("narration") or "").strip()
        audio_path: Path | None = None

        # 1) 이 shot 의 길이를 정한다
        if shot.get("audio"):
            audio_path = Path(shot["audio"])
            if not audio_path.is_absolute():
                audio_path = base / audio_path
            duration = probe_duration(audio_path) + SHOT_PADDING
        elif narration and not silent:
            audio_path = work / f"a{idx:03d}.mp3"
            synth_narration(narration, voice_cfg, audio_path)
            duration = probe_duration(audio_path) + SHOT_PADDING
        else:
            if "duration" not in shot:
                sys.exit(f"shot {idx}: 나레이션이 없으면 duration(초)이 필요합니다.")
            duration = float(shot["duration"])

        # 2) 영상 세그먼트 — 세로로 채우고 길이를 맞춘다.
        #    생성 클립(보통 5초 안팎)이 shot 보다 짧을 때 그냥 루프시키면
        #    이어지는 지점에서 화면이 튄다. 조금 모자란 정도면 재생을 늦춰서
        #    이어붙이는 쪽이 훨씬 자연스럽다. 많이 모자라면 그때 루프한다.
        clip_len = probe_duration(clip)
        stretch = duration / clip_len if clip_len > 0 else 1.0
        max_stretch = float(visual_cfg.get("max_slowdown", 2.0))

        common_vf = (f"scale={W}:{H}:force_original_aspect_ratio=increase,"
                     f"crop={W}:{H},setsar=1,fps={fps}")
        seg_v = work / f"v{idx:03d}.mp4"

        if 1.0 < stretch <= max_stretch:
            # setpts 로 늘린다. 오디오는 별도 트랙이라 영향이 없다.
            cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", str(clip),
                   "-vf", f"setpts=PTS*{stretch:.6f},{common_vf}"]
            fitted = "slowed"
        else:
            cmd = ["ffmpeg", "-y", "-loglevel", "error",
                   "-stream_loop", "-1", "-i", str(clip), "-vf", common_vf]
            fitted = "looped" if stretch > 1.0 else "trimmed"

        run([*cmd, "-t", f"{duration:.3f}", "-an",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
             "-pix_fmt", "yuv420p", str(seg_v)])
        seg_videos.append(seg_v)

        if fitted == "looped":
            print(f"경고: shot {idx} — 클립 {clip_len:.1f}초를 {duration:.1f}초로 채우려고 "
                  f"루프했습니다({stretch:.1f}배). 이어지는 지점에서 화면이 튑니다.\n"
                  f"      대본을 나눠 shot 을 짧게 하거나 클립을 더 길게 생성하세요.",
                  file=sys.stderr)

        fit_log.append({"shot": idx, "clip_seconds": round(clip_len, 2),
                        "shot_seconds": round(duration, 2), "fit": fitted})

        # 3) 오디오 세그먼트 — 없으면 무음으로 채워서 길이를 맞춘다
        seg_a = work / f"s{idx:03d}.m4a"
        if audio_path:
            run([
                "ffmpeg", "-y", "-loglevel", "error",
                "-i", str(audio_path),
                "-f", "lavfi", "-t", f"{duration:.3f}", "-i", "anullsrc=r=44100:cl=stereo",
                "-filter_complex", "[0:a]aresample=44100[a0];[a0][1:a]amix=inputs=2:duration=longest[out]",
                "-map", "[out]", "-t", f"{duration:.3f}",
                "-c:a", "aac", "-b:a", "128k",
                str(seg_a),
            ])
        else:
            run([
                "ffmpeg", "-y", "-loglevel", "error",
                "-f", "lavfi", "-t", f"{duration:.3f}", "-i", "anullsrc=r=44100:cl=stereo",
                "-c:a", "aac", "-b:a", "128k",
                str(seg_a),
            ])
        seg_audios.append(seg_a)

        # 4) 자막 큐 — shot 길이를 덩어리 길이 비율로 나눈다
        text = shot.get("subtitle", narration)
        pieces = chunk_text(text, int(sub_cfg.get("max_chars_per_cue", 18)))
        # shot 의 highlight 에 적힌 단어는 강조색으로 나옵니다.
        highlights = shot.get("highlight") or []
        if isinstance(highlights, str):
            highlights = [highlights]

        if pieces:
            total_chars = sum(len(p) for p in pieces)
            lead = float(sub_cfg.get("lead_seconds", 0.0))
            cursor = timeline + lead
            for piece in pieces:
                span = duration * (len(piece) / total_chars)
                cues.append((cursor, cursor + span, piece, "Default", highlights))
                cursor += span

        # 4-A) 보조 자막 — 출처, 기준값, 다음 편 예고 같은 것.
        #      쪼개지 않고 shot 전체에 한 줄로 깔린다. 본 자막보다 작고 아래에 있다.
        note = (shot.get("note") or "").strip()
        if note:
            cues.append((timeline, timeline + duration, note, "Note", []))

        timeline += duration

    # 5) 이어붙이기
    def concat(files: list[Path], out: Path, codec: list[str]) -> None:
        listing = work / f"{out.stem}.txt"
        listing.write_text("".join(f"file '{f}'\n" for f in files), encoding="utf-8")
        run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0",
             "-i", str(listing), *codec, str(out)])

    merged_v = work / "video.mp4"
    merged_a = work / "audio.m4a"
    concat(seg_videos, merged_v, ["-c", "copy"])

    if whole_audio:
        # 전체 나레이션을 영상 길이에 맞춰 자르거나 무음으로 채웁니다.
        run(["ffmpeg", "-y", "-loglevel", "error",
             "-i", str(whole_audio),
             "-f", "lavfi", "-t", f"{timeline:.3f}", "-i", "anullsrc=r=44100:cl=stereo",
             "-filter_complex",
             "[0:a]aresample=44100[a0];[a0][1:a]amix=inputs=2:duration=longest[out]",
             "-map", "[out]", "-t", f"{timeline:.3f}",
             "-c:a", "aac", "-b:a", "128k", str(merged_a)])
        narration_len = probe_duration(whole_audio)
        if abs(narration_len - timeline) > 1.5:
            print(f"경고: 나레이션 {narration_len:.1f}초 vs 영상 {timeline:.1f}초 — "
                  f"{abs(narration_len - timeline):.1f}초 차이가 납니다.\n"
                  f"      shot 의 duration 합을 나레이션 길이에 맞추세요.",
                  file=sys.stderr)
    else:
        concat(seg_audios, merged_a, ["-c", "copy"])

    # 6) 자막 굽고 오디오 붙이기
    ass_path = work / "subs.ass"
    ass_path.write_text(build_ass(cues, sub_cfg), encoding="utf-8")

    sub_filter = f"ass='{escape_for_filter(ass_path)}'"
    if sub_cfg.get("font_file"):
        fonts_dir = Path(sub_cfg["font_file"]).expanduser().parent
        sub_filter += f":fontsdir='{escape_for_filter(fonts_dir)}'"

    # 전체 배속. 자막을 구운 뒤에 걸어야 자막까지 같이 빨라집니다.
    # 오디오는 atempo 로 맞춰서 목소리 높이가 변하지 않게 합니다.
    speed = float(visual_cfg.get("playback_speed", 1.0))
    if speed <= 0:
        sys.exit("visual.playback_speed 는 0보다 커야 합니다.")
    vf = sub_filter
    af = None
    if abs(speed - 1.0) > 1e-6:
        vf = f"{sub_filter},setpts=PTS/{speed:.6f}"
        af = f"atempo={speed:.6f}"     # atempo 는 0.5~2.0 범위에서 유효
        if not 0.5 <= speed <= 2.0:
            sys.exit(f"visual.playback_speed 는 0.5~2.0 사이여야 합니다 (지금 {speed}).")

    cmd = ["ffmpeg", "-y", "-loglevel", "error",
           "-i", str(merged_v), "-i", str(merged_a),
           "-vf", vf]
    if af:
        cmd += ["-af", af]
    cmd += ["-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-shortest", "-movflags", "+faststart",
            str(out_path)]
    run(cmd)

    result = {
        "output": str(out_path),
        "duration_seconds": round(timeline, 2),
        "shots": len(shots),
        "subtitle_cues": sum(1 for c in cues if c[3] == "Default"),
        "note_cues": sum(1 for c in cues if c[3] == "Note"),
        "clip_fit": fit_log,
        "playback_speed": speed,
        "final_seconds": round(timeline / speed, 2),
        "narration": "none" if silent else voice_cfg.get("name", ""),
    }
    if timeline / speed > 60:
        result["warning"] = "60초를 넘습니다. 쇼츠로 안 잡힐 수 있습니다."
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if not args.keep_work:
        shutil.rmtree(work, ignore_errors=True)
    else:
        print(f"작업 폴더 유지: {work}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="쇼츠 합성 (클립 + TTS + 자막)")
    sub = parser.add_subparsers(dest="command", required=True)

    c = sub.add_parser("check", help="ffmpeg / edge-tts / 폰트 설치 확인")
    c.add_argument("--style", help="reference-style.yaml 경로 (주면 폰트까지 검사)")
    c.set_defaults(func=cmd_check)

    b = sub.add_parser("build", help="합성 실행")
    b.add_argument("--shotlist", required=True, help="shotlist JSON 경로")
    b.add_argument("--style", required=True, help="reference-style.yaml 경로")
    b.add_argument("--out", required=True, help="출력 mp4 경로")
    b.add_argument("--keep-work", action="store_true", help="중간 파일 남기기 (디버깅용)")
    b.set_defaults(func=cmd_build)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
