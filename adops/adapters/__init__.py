"""어댑터 레지스트리.

설정의 sources 항목을 보고 어댑터 인스턴스를 만든다. 설정이 없으면
CSV 어댑터만 켠다 — 자격증명이 하나도 없는 상태에서도 파이프라인이
끝까지 돌아야 하기 때문이다.
"""

from __future__ import annotations

from typing import Sequence

from ..config import Config
from .base import Source
from .csv_source import CsvSource


def _registry() -> dict[str, type[Source]]:
    # API 어댑터는 임포트 시점에 SDK를 요구하지 않도록 지연 임포트한다.
    from .coupang_ads import CoupangAdsSource
    from .google_ads import GoogleAdsSource
    from .meta_ads import MetaAdsSource
    from .naver_searchad import NaverSearchAdSource

    return {
        CsvSource.name: CsvSource,
        NaverSearchAdSource.name: NaverSearchAdSource,
        CoupangAdsSource.name: CoupangAdsSource,
        MetaAdsSource.name: MetaAdsSource,
        GoogleAdsSource.name: GoogleAdsSource,
    }


def build_sources(cfg: Config, only: str | None = None) -> list[Source]:
    reg = _registry()
    configured = cfg.get("sources") or {"csv": {"enabled": True}}

    sources: list[Source] = []
    for name, settings in configured.items():
        if not isinstance(settings, dict) or not settings.get("enabled", True):
            continue
        if only and name != only:
            continue
        cls = reg.get(name)
        if cls is None:
            continue
        sources.append(cls(settings))

    if not sources and not only:
        sources.append(CsvSource({}))
    return sources


__all__ = ["Source", "CsvSource", "build_sources"]
