"""정규화 스키마.

각 채널의 리포트는 형식이 제각각이므로, 어댑터가 모두 아래 4개의
표준 레코드로 변환한 뒤에야 창고(warehouse)에 적재된다.
분석 로직은 원본 채널 형식을 절대 알지 못한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Optional


# --- 채널 식별자 -----------------------------------------------------------

# 판매(매출이 찍히는) 채널
STORE_CHANNELS = ("smartstore", "coupang", "own")

# 광고(비용이 찍히는) 채널
AD_CHANNELS = ("naver_sa", "coupang_ads", "meta", "instagram", "google")

# 인스타 광고는 Meta 광고 관리자에서 집행되지만, 지면별 효율이 크게 다르므로
# publisher_platform 기준으로 분리해 적재한다. (meta = 페이스북 지면)


def _norm_date(value) -> str:
    """date/datetime/str 무엇이 오든 'YYYY-MM-DD' 문자열로 통일."""
    if isinstance(value, str):
        return value[:10]
    if isinstance(value, date):
        return value.isoformat()
    raise TypeError(f"지원하지 않는 날짜 타입: {type(value)!r}")


@dataclass(slots=True)
class SpendRow:
    """광고 집행 실적. 키워드 단위가 없는 채널(메타/인스타)은 keyword=None."""

    date: str
    ad_channel: str
    store_channel: str          # 이 광고가 어느 판매채널로 트래픽을 보내는지
    campaign: str
    adgroup: str = ""
    keyword: Optional[str] = None
    match_type: str = ""        # exact / phrase / broad
    impressions: int = 0
    clicks: int = 0
    cost: float = 0.0           # 광고비 (VAT 제외, 원)
    conv_count: float = 0.0     # 전환수 (채널 리포트 기준)
    conv_value: float = 0.0     # 전환매출 (채널 리포트 기준, 원)
    sku: Optional[str] = None

    def __post_init__(self) -> None:
        self.date = _norm_date(self.date)
        if self.ad_channel not in AD_CHANNELS:
            raise ValueError(f"알 수 없는 광고채널: {self.ad_channel}")
        if self.store_channel not in STORE_CHANNELS:
            raise ValueError(f"알 수 없는 판매채널: {self.store_channel}")


@dataclass(slots=True)
class SalesRow:
    """판매채널 실매출. 광고 리포트의 conv_value와는 별개로 관리한다.

    채널 리포트의 전환매출은 어트리뷰션 창(click-through window) 때문에
    항상 부풀려진다. 수익성 판단은 반드시 이 실매출을 기준으로 한다.
    """

    date: str
    store_channel: str
    sku: str = ""
    product_name: str = ""
    orders: int = 0
    qty: int = 0
    gross_sales: float = 0.0    # 할인 전
    discount: float = 0.0
    net_sales: float = 0.0      # 할인 후, 취소/반품 차감 전
    cancels: float = 0.0
    returns: float = 0.0
    new_customer_orders: int = 0   # 자사몰만 채워짐. 비면 None 취급.

    def __post_init__(self) -> None:
        self.date = _norm_date(self.date)
        if self.store_channel not in STORE_CHANNELS:
            raise ValueError(f"알 수 없는 판매채널: {self.store_channel}")
        if not self.net_sales and self.gross_sales:
            self.net_sales = self.gross_sales - self.discount

    @property
    def realized_sales(self) -> float:
        """취소·반품까지 차감한 확정 매출."""
        return self.net_sales - self.cancels - self.returns


@dataclass(slots=True)
class SearchTermRow:
    """검색어 리포트. 부정키워드(제외키워드) 후보 도출의 유일한 근거."""

    date: str
    ad_channel: str
    campaign: str
    keyword: str                # 매칭된 등록 키워드
    search_term: str            # 실제 검색된 질의어
    adgroup: str = ""
    impressions: int = 0
    clicks: int = 0
    cost: float = 0.0
    conv_count: float = 0.0
    conv_value: float = 0.0

    def __post_init__(self) -> None:
        self.date = _norm_date(self.date)


@dataclass(slots=True)
class CatalogRow:
    """SKU 마스터. 원가가 없으면 수익성 분석 전체가 불가능하므로 필수."""

    sku: str
    product_name: str = ""
    price: float = 0.0
    cogs: float = 0.0           # 매입원가
    category: str = ""
    stock_qty: Optional[int] = None
    active: bool = True

    @property
    def gross_margin_rate(self) -> Optional[float]:
        if not self.price:
            return None
        return (self.price - self.cogs) / self.price


ROW_TYPES = {
    "spend": SpendRow,
    "sales": SalesRow,
    "search_terms": SearchTermRow,
    "catalog": CatalogRow,
}


def to_dict(row) -> dict:
    return asdict(row)
