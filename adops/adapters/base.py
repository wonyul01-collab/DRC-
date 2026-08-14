"""어댑터 공통 규약.

모든 채널 어댑터는 Source 를 구현한다. 분석 계층은 어댑터가 CSV를 읽는지
API를 때리는지 알지 못하며, 알 필요도 없다. 그래서 나중에 채널이 추가되거나
CSV → API 로 갈아타도 분석 코드는 한 줄도 바뀌지 않는다.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass
from typing import Sequence


@dataclass(slots=True)
class FetchResult:
    """어댑터 1회 실행 결과."""

    rows: Sequence
    table: str                  # spend / sales / search_terms / catalog
    source: str                 # 로그에 남길 식별자
    ok: bool = True
    message: str = ""


class Source(abc.ABC):
    """채널 데이터 원천."""

    #: 설정/CLI 에서 이 어댑터를 지정할 때 쓰는 이름
    name: str = "base"

    def __init__(self, settings: dict | None = None) -> None:
        self.settings = settings or {}

    @abc.abstractmethod
    def fetch(self, date_from: str, date_to: str) -> list[FetchResult]:
        """[date_from, date_to] 구간 데이터를 정규화 레코드로 반환.

        구현체는 부분 실패를 예외로 던지지 말고 ok=False 인 FetchResult 로
        돌려준다. 한 채널이 죽어도 나머지 채널 리포트는 나가야 하기 때문이다.
        """

    def available(self) -> tuple[bool, str]:
        """실행 가능 여부와 사유. 크론이 돌기 전에 미리 점검하는 용도."""
        return True, ""


class NotConfigured(RuntimeError):
    """자격증명 미설정. 호출자가 잡아서 건너뛰도록 한다."""


def num(value, default: float = 0.0) -> float:
    """'1,234원', '12.5%', '', None 을 모두 안전하게 float 로."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s or s in {"-", "--"}:
        return default
    s = s.replace(",", "").replace("원", "").replace("%", "").replace("₩", "")
    try:
        return float(s)
    except ValueError:
        return default


def integer(value, default: int = 0) -> int:
    return int(round(num(value, default)))
