"""
유튜브 다운로드 엔진.

HTTP 403 Forbidden 을 자동으로 우회하는 것이 이 파일의 존재 이유다.

403 이 나는 이유는 대부분 셋 중 하나다.
  1. yt-dlp 가 낡음        -> 서명(signature) 계산이 틀려서 스트림 URL 이 거부된다
  2. JS 런타임이 없음      -> YouTube 챌린지를 못 풀어서 스트림 URL 이 거부된다
  3. PO 토큰/쿠키가 없음   -> 봇으로 판정돼서 스트림 URL 이 거부된다

2번과 3번은 클라이언트를 바꾸면 통째로 피해갈 수 있다.
android_vr / ios / visionos 는 JS 플레이어도 쿠키도 요구하지 않기 때문이다.
그래서 화질이 가장 좋은 기본 클라이언트부터 시도하고, 403 이 나면
요구조건이 적은 클라이언트로 한 단계씩 내려간다.
"""

from __future__ import annotations

import json
import os
import shutil
import urllib.request
from dataclasses import dataclass, field
from typing import Callable, Iterable

try:
    import yt_dlp
    from yt_dlp.utils import DownloadError
except ImportError:  # pragma: no cover - 실행 스크립트가 먼저 설치한다
    yt_dlp = None
    DownloadError = Exception


class _QuietLogger:
    """
    yt-dlp 는 quiet=True 여도 오류를 stderr 로 직접 뱉는다.
    폴백 도중의 실패는 정상 동작이므로 사용자에게 보일 필요가 없다.
    여기서 전부 삼키고, 최종 메시지는 _friendly() 가 만든 것만 쓴다.
    """

    def __init__(self):
        self.lines: list[str] = []

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        pass

    def error(self, msg):
        self.lines.append(str(msg))


# --------------------------------------------------------------------------
# 폴백 전략
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Strategy:
    name: str
    clients: tuple[str, ...] = ()
    use_cookies: bool = True
    note: str = ""

    def extractor_args(self) -> dict:
        if not self.clients:
            return {}
        return {"youtube": {"player_client": list(self.clients)}}


# 위에서부터 순서대로 시도한다. 위쪽일수록 화질이 좋고, 아래쪽일수록 잘 뚫린다.
STRATEGIES: tuple[Strategy, ...] = (
    Strategy("기본", (), True, "yt-dlp 가 알아서 고름 - 화질 최상"),
    Strategy("tv", ("tv",), True, "TV 클라이언트 - 화질 좋음"),
    Strategy("android_vr", ("android_vr",), False, "JS·쿠키 불필요 - 403 우회용"),
    Strategy("ios", ("ios",), False, "JS·쿠키 불필요 - 403 우회용"),
    Strategy("visionos", ("visionos",), False, "JS·쿠키 불필요 - 최후 수단"),
    Strategy("web_safari", ("web_safari",), True, "쿠키가 있을 때 유효"),
)


def _is_403(err: BaseException) -> bool:
    text = str(err).lower()
    return "403" in text or "forbidden" in text


def _is_retryable(err: BaseException) -> bool:
    """클라이언트를 바꿔서 다시 해볼 가치가 있는 오류인가."""
    text = str(err).lower()
    if _is_403(err):
        return True
    for phrase in (
        "unable to download video data",
        "requested format is not available",
        "sign in to confirm",
        "this content isn",
        "failed to extract",
        "player response",
        "nsig",
        "unable to extract",
    ):
        if phrase in text:
            return True
    return False


def _is_fatal(err: BaseException) -> bool:
    """클라이언트를 바꿔도 소용없는 오류인가."""
    text = str(err).lower()
    for phrase in (
        "private video",
        "video unavailable",
        "removed by the uploader",
        "account associated with this video has been terminated",
        "is not available in your country",
        "members-only",
        "this live event will begin",
    ):
        if phrase in text:
            return True
    return False


# --------------------------------------------------------------------------
# 환경 점검
# --------------------------------------------------------------------------

JS_RUNTIMES = ("deno", "node", "bun", "qjs")


def _vtuple(v: str) -> tuple:
    """
    '2026.08.19' 와 '2026.8.19' 는 같은 버전이다.
    문자열로 비교하면 매번 '낡았다' 고 잘못 알리므로 숫자로 바꿔서 비교한다.
    나이틀리는 '2026.08.19.232045' 처럼 뒤가 더 붙는다.
    """
    parts = []
    for chunk in v.strip().split("."):
        digits = "".join(c for c in chunk if c.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


@dataclass
class Environment:
    ytdlp_version: str | None = None
    ytdlp_latest: str | None = None
    ffmpeg: str | None = None
    js_runtime: str | None = None
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ytdlp_outdated(self) -> bool:
        if not self.ytdlp_version or not self.ytdlp_latest:
            return False
        return _vtuple(self.ytdlp_version) < _vtuple(self.ytdlp_latest)


def _pypi_latest(timeout: float = 6.0) -> str | None:
    try:
        req = urllib.request.Request(
            "https://pypi.org/pypi/yt-dlp/json",
            headers={"User-Agent": "youtube-downloader/2.0"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.load(resp)["info"]["version"]
    except Exception:
        return None


def check_environment(check_updates: bool = True) -> Environment:
    env = Environment()

    if yt_dlp is None:
        env.problems.append("yt-dlp 가 설치돼 있지 않습니다. 실행.bat 으로 실행하세요.")
    else:
        env.ytdlp_version = yt_dlp.version.__version__
        if check_updates:
            env.ytdlp_latest = _pypi_latest()
            if env.ytdlp_outdated:
                env.problems.append(
                    f"yt-dlp 가 낡았습니다 (설치 {env.ytdlp_version} / 최신 {env.ytdlp_latest}). "
                    "이게 403 의 1순위 원인입니다 - 업데이트.bat 을 실행하세요."
                )

    env.ffmpeg = shutil.which("ffmpeg")
    if not env.ffmpeg:
        env.notes.append(
            "ffmpeg 가 없습니다. 고화질 영상과 음성을 합치지 못해 화질이 떨어집니다. "
            "(winget install Gyan.FFmpeg)"
        )

    for rt in JS_RUNTIMES:
        if shutil.which(rt):
            env.js_runtime = rt
            break
    if not env.js_runtime:
        env.notes.append(
            "JS 런타임이 없습니다. 일부 고화질 포맷이 막힐 수 있습니다. "
            "(winget install DenoLand.Deno) - 없어도 자동 우회는 동작합니다."
        )

    return env


# --------------------------------------------------------------------------
# 쿠키
# --------------------------------------------------------------------------

def cookie_options(source: str | None, cookie_file: str | None) -> dict:
    """
    source: None | 'chrome' | 'edge' | 'firefox' | 'whale' | 'brave'
    cookie_file: cookies.txt 경로

    쿠키 파일이 있으면 그쪽을 우선한다. Chrome 127+ 는 App-Bound Encryption
    때문에 브라우저에서 직접 뽑는 게 막혀 있어서, 파일 쪽이 훨씬 확실하다.
    """
    if cookie_file and os.path.isfile(cookie_file):
        return {"cookiefile": cookie_file}
    if source:
        return {"cookiesfrombrowser": (source,)}
    return {}


# --------------------------------------------------------------------------
# 다운로드
# --------------------------------------------------------------------------

QUALITY_FORMATS = {
    "best": "bestvideo*+bestaudio/best",
    "1080": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
    "720": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
    "audio": "bestaudio/best",
}


def build_opts(
    out_dir: str,
    quality: str = "best",
    cookies: dict | None = None,
    strategy: Strategy | None = None,
    progress_hook: Callable | None = None,
    logger=None,
) -> dict:
    opts: dict = {
        "outtmpl": os.path.join(out_dir, "%(title)s [%(id)s].%(ext)s"),
        "format": QUALITY_FORMATS.get(quality, QUALITY_FORMATS["best"]),
        "noplaylist": True,
        "retries": 10,
        "fragment_retries": 10,
        "extractor_retries": 3,
        "continuedl": True,
        "ignoreerrors": False,
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "consoletitle": False,
    }

    if quality == "audio":
        opts["postprocessors"] = [
            {"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "192"}
        ]
    else:
        opts["merge_output_format"] = "mp4"

    if strategy is not None:
        ea = strategy.extractor_args()
        if ea:
            opts["extractor_args"] = ea
        if cookies and strategy.use_cookies:
            opts.update(cookies)
    elif cookies:
        opts.update(cookies)

    if progress_hook:
        opts["progress_hooks"] = [progress_hook]
    opts["logger"] = logger if logger is not None else _QuietLogger()

    return opts


@dataclass
class Result:
    url: str
    ok: bool
    strategy: str = ""
    filepath: str | None = None
    title: str | None = None
    error: str | None = None


def download_one(
    url: str,
    out_dir: str,
    quality: str = "best",
    cookies: dict | None = None,
    strategies: Iterable[Strategy] = STRATEGIES,
    log: Callable[[str], None] = print,
    progress_hook: Callable | None = None,
    should_cancel: Callable[[], bool] = lambda: False,
    preferred: Strategy | None = None,
) -> Result:
    """
    403 이 나면 클라이언트를 바꿔가며 자동 재시도한다.
    성공한 전략을 Result.strategy 로 돌려주므로, 다음 URL 부터는
    그 전략을 먼저 쓰면 빠르다.
    """
    if yt_dlp is None:
        return Result(url, False, error="yt-dlp 가 설치돼 있지 않습니다.")

    order = list(strategies)
    if preferred is not None and preferred in order:
        order.remove(preferred)
        order.insert(0, preferred)

    last_error: str | None = None
    cache_cleared = False

    for idx, strat in enumerate(order, 1):
        if should_cancel():
            return Result(url, False, error="사용자가 취소했습니다.")

        if idx > 1:
            log(f"    ↻ 재시도: {strat.name}  ({strat.note})")

        opts = build_opts(out_dir, quality, cookies, strat, progress_hook)

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
                if info is None:
                    raise DownloadError("정보를 가져오지 못했습니다.")
                path = None
                try:
                    path = ydl.prepare_filename(info)
                except Exception:
                    pass
                return Result(
                    url, True,
                    strategy=strat.name,
                    filepath=path,
                    title=info.get("title"),
                )

        except DownloadError as e:
            last_error = str(e)

            if _is_fatal(e):
                log(f"    ✗ {_friendly(last_error)}")
                return Result(url, False, strategy=strat.name, error=_friendly(last_error))

            if _is_403(e) and not cache_cleared:
                # 낡은 서명 캐시가 원인일 수 있다. 한 번만 비운다.
                try:
                    yt_dlp.YoutubeDL({"quiet": True}).cache.remove()
                    log("    ↻ 서명 캐시를 비웠습니다")
                    cache_cleared = True
                except Exception:
                    cache_cleared = True

            if not _is_retryable(e):
                log(f"    ✗ {_friendly(last_error)}")
                return Result(url, False, strategy=strat.name, error=_friendly(last_error))

        except Exception as e:  # 예상 못 한 오류도 다음 전략으로 넘어간다
            last_error = str(e)

    return Result(url, False, error=_friendly(last_error or "알 수 없는 오류"))


def _friendly(msg: str) -> str:
    """yt-dlp 원문 오류를 사람이 읽을 수 있게 바꾼다."""
    m = msg.replace("ERROR: ", "").strip()
    low = m.lower()

    if "403" in low or "forbidden" in low:
        return (
            "모든 방법으로 시도했지만 YouTube 가 계속 거부했습니다 (403). "
            "업데이트.bat 을 실행해 yt-dlp 를 최신으로 올린 뒤 다시 해보세요."
        )
    if "private video" in low:
        return "비공개 영상입니다."
    if "video unavailable" in low:
        return "삭제됐거나 볼 수 없는 영상입니다."
    if "members-only" in low:
        return "멤버십 전용 영상입니다. 쿠키를 설정해야 받을 수 있습니다."
    if "sign in to confirm" in low and "age" in low:
        return "연령 제한 영상입니다. 쿠키를 설정해야 받을 수 있습니다."
    if "sign in to confirm" in low:
        return "봇 확인에 걸렸습니다. 쿠키를 설정하면 풀립니다."
    if "not available in your country" in low:
        return "지역 제한 영상입니다."
    if "unable to extract" in low or "player response" in low:
        return "영상 정보를 읽지 못했습니다. yt-dlp 업데이트가 필요합니다 (업데이트.bat)."
    if "ffmpeg" in low:
        return "ffmpeg 가 필요합니다. winget install Gyan.FFmpeg 로 설치하세요."
    if "no space left" in low:
        return "저장 공간이 부족합니다."

    return m.split("\n")[0][:300]
