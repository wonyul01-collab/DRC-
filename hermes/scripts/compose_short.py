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
    {"clip": "out/video/raw/01.mp4", "narration": "읽을 문장", "subtitle": "띄울 자막"},
    {"clip": "out/video/raw/02.mp4", "narration": "다음 문장"}
  ]
}
  - subtitle 을 생략하면 narration 을 그대로 자막으로 씁니다.
  - voice.provider 가 none 이면 각 shot 에 "duration"(초)이 있어야 합니다.
  - narration 이 빈 문자열이면 그 shot 은 무음으로 처리하고 duration 을 씁니다.
"""

from __future__ import annotations

import argparse
import json
import os
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


def installed_font_families() -> list[str] | None:
    """설치된 폰트 패밀리 목록. 확인할 방법이 없으면 None."""
    if shutil.which("fc-list"):
        out = subprocess.run(["fc-list", ":lang=ko", "family"],
                             capture_output=True, text=True)
        if out.returncode == 0:
            families: set[str] = set()
            for line in out.stdout.splitlines():
                families.update(part.strip() for part in line.split(","))
            return sorted(f for f in families if f)
    if sys.platform == "win32":
        # 네이티브 Windows: 폰트 폴더의 파일명으로 대략 확인한다.
        fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
        if fonts.is_dir():
            return sorted({p.stem for p in fonts.glob("*.tt[fc]")})
    return None


def warn_if_font_missing(font_family: str) -> None:
    """폰트명이 틀리면 ffmpeg가 조용히 기본 폰트로 떨어진다. 미리 잡는다."""
    families = installed_font_families()
    if families is None or not font_family:
        return
    lowered = [f.lower() for f in families]
    target = font_family.lower()
    if any(target == f or target in f for f in lowered):
        return
    hint = ", ".join(f for f in families if any(
        k in f.lower() for k in ("noto", "malgun", "pretendard", "nanum", "gothic")
    )) or ", ".join(families[:10])
    print(
        f"경고: 폰트 '{font_family}' 를 찾지 못했습니다. 자막이 기본 폰트로 나오거나 깨집니다.\n"
        f"       스타일 파일의 subtitle.font_family 를 아래 중 하나로 바꾸세요:\n"
        f"       {hint}",
        file=sys.stderr,
    )


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


def build_ass(cues: list[tuple[float, float, str]], sub_cfg: dict) -> str:
    font_name = sub_cfg.get("font_family", "Noto Sans KR")
    if sub_cfg.get("font_file"):
        # fontsdir 로 폰트를 넘길 때도 FontName 은 파일의 실제 패밀리명이어야 합니다.
        font_name = sub_cfg.get("font_family") or Path(sub_cfg["font_file"]).stem

    style = ",".join([
        "Default",
        font_name,
        str(sub_cfg.get("font_size", 72)),
        sub_cfg.get("primary_color", "&H00FFFFFF"),
        "&H000000FF",                                   # SecondaryColour (미사용)
        sub_cfg.get("outline_color", "&H00000000"),
        "&H00000000",                                   # BackColour
        "-1" if sub_cfg.get("bold", True) else "0",
        "0", "0", "0",                                  # Italic, Underline, StrikeOut
        "100", "100", "0", "0",                         # Scale/Spacing/Angle
        "1",                                            # BorderStyle: outline+shadow
        str(sub_cfg.get("outline_width", 4)),
        str(sub_cfg.get("shadow", 0)),
        str(sub_cfg.get("alignment", 2)),
        "80", "80",                                     # MarginL, MarginR
        str(sub_cfg.get("margin_vertical", 320)),
        "1",                                            # Encoding
    ])

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
        f"Style: {style}",
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for start, end, text in cues:
        safe = text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", "\\N")
        lines.append(f"Dialogue: 0,{ass_time(start)},{ass_time(end)},Default,,0,0,0,,{safe}")
    return "\n".join(lines) + "\n"


def escape_for_filter(path: Path) -> str:
    """ffmpeg 필터 인자에 경로를 넣을 때 필요한 이스케이프."""
    return str(path).replace("\\", "\\\\").replace(":", r"\:").replace("'", r"\'")


# --------------------------------------------------------------------------
# 빌드
# --------------------------------------------------------------------------

def cmd_check(_args: argparse.Namespace) -> None:
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
    silent = voice_cfg.get("provider", "edge") == "none"

    seg_videos: list[Path] = []
    seg_audios: list[Path] = []
    cues: list[tuple[float, float, str]] = []
    timeline = 0.0

    for idx, shot in enumerate(shots):
        clip = Path(shot["clip"])
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

        # 2) 영상 세그먼트 — 세로로 채우고 길이를 맞춘다 (짧으면 루프)
        seg_v = work / f"v{idx:03d}.mp4"
        run([
            "ffmpeg", "-y", "-loglevel", "error",
            "-stream_loop", "-1", "-i", str(clip),
            "-t", f"{duration:.3f}",
            "-an",
            "-vf", f"scale={W}:{H}:force_original_aspect_ratio=increase,"
                   f"crop={W}:{H},setsar=1,fps={fps}",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "20",
            "-pix_fmt", "yuv420p",
            str(seg_v),
        ])
        seg_videos.append(seg_v)

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
        if pieces:
            total_chars = sum(len(p) for p in pieces)
            lead = float(sub_cfg.get("lead_seconds", 0.0))
            cursor = timeline + lead
            for piece in pieces:
                span = duration * (len(piece) / total_chars)
                cues.append((cursor, cursor + span, piece))
                cursor += span

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
    concat(seg_audios, merged_a, ["-c", "copy"])

    # 6) 자막 굽고 오디오 붙이기
    ass_path = work / "subs.ass"
    ass_path.write_text(build_ass(cues, sub_cfg), encoding="utf-8")

    sub_filter = f"ass='{escape_for_filter(ass_path)}'"
    if sub_cfg.get("font_file"):
        fonts_dir = Path(sub_cfg["font_file"]).expanduser().parent
        sub_filter += f":fontsdir='{escape_for_filter(fonts_dir)}'"

    run([
        "ffmpeg", "-y", "-loglevel", "error",
        "-i", str(merged_v), "-i", str(merged_a),
        "-vf", sub_filter,
        "-map", "0:v:0", "-map", "1:a:0",
        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest", "-movflags", "+faststart",
        str(out_path),
    ])

    result = {
        "output": str(out_path),
        "duration_seconds": round(timeline, 2),
        "shots": len(shots),
        "subtitle_cues": len(cues),
        "narration": "none" if silent else voice_cfg.get("name", ""),
    }
    if timeline > 60:
        result["warning"] = "60초를 넘습니다. 쇼츠로 안 잡힐 수 있습니다."
    print(json.dumps(result, ensure_ascii=False, indent=2))

    if not args.keep_work:
        shutil.rmtree(work, ignore_errors=True)
    else:
        print(f"작업 폴더 유지: {work}", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="쇼츠 합성 (클립 + TTS + 자막)")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("check", help="ffmpeg/edge-tts 설치 확인").set_defaults(func=cmd_check)

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
