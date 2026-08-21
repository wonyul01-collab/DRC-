"""성과·수익성 지표 계산.

중요한 원칙 두 가지:

1) 매출은 두 종류를 끝까지 분리한다.
   - conv_value : 광고 채널이 자기 어트리뷰션 창으로 잡은 '광고 전환매출'
   - realized   : 판매채널 정산 기준 '실매출'
   채널 리포트를 다 더하면 실매출보다 항상 크다(중복 귀속). 이 둘을 섞으면
   ROAS가 부풀고, 그 숫자로 예산을 늘리면 손실이 커진다. 리포트에는 둘 다
   싣고 괴리율을 명시한다.

2) 광고 성패는 ROAS 절대값이 아니라 '손익분기 ROAS 대비'로 판정한다.
   마진 구조가 다른 상품/채널에 동일한 목표 ROAS를 적용하는 것이
   현장에서 가장 흔한 오판이다.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from typing import Any, Iterable

from .config import Config


def _d(s: str) -> date:
    return date.fromisoformat(s)


def daterange_days(start: str, end: str) -> int:
    return (_d(end) - _d(start)).days + 1


def shift(day: str, days: int) -> str:
    return (_d(day) + timedelta(days=days)).isoformat()


def safe_div(a: float, b: float) -> float | None:
    return (a / b) if b else None


def pct_change(cur: float | None, prev: float | None) -> float | None:
    if cur is None or prev in (None, 0):
        return None
    return (cur - prev) / abs(prev)


# --- 집계 결과 컨테이너 -----------------------------------------------------


@dataclass(slots=True)
class Perf:
    """광고 성과 한 덩어리(채널/키워드/전체 무엇이든)."""

    label: str = ""
    impressions: int = 0
    clicks: int = 0
    cost: float = 0.0
    conv_count: float = 0.0
    conv_value: float = 0.0

    def add(self, row) -> None:
        self.impressions += int(row["impressions"] or 0)
        self.clicks += int(row["clicks"] or 0)
        self.cost += float(row["cost"] or 0)
        self.conv_count += float(row["conv_count"] or 0)
        self.conv_value += float(row["conv_value"] or 0)

    @property
    def ctr(self): return safe_div(self.clicks, self.impressions)
    @property
    def cpc(self): return safe_div(self.cost, self.clicks)
    @property
    def cvr(self): return safe_div(self.conv_count, self.clicks)
    @property
    def cpa(self): return safe_div(self.cost, self.conv_count)
    @property
    def roas(self): return safe_div(self.conv_value, self.cost)
    @property
    def acos(self): return safe_div(self.cost, self.conv_value)

    def as_dict(self) -> dict:
        d = asdict(self)
        d.update(ctr=self.ctr, cpc=self.cpc, cvr=self.cvr,
                 cpa=self.cpa, roas=self.roas, acos=self.acos)
        return d


def fetch_spend(
    conn: sqlite3.Connection, start: str, end: str, *, group_by: Iterable[str]
) -> dict[tuple, Perf]:
    cols = list(group_by)
    sel = ", ".join(cols)
    sql = (
        f"SELECT {sel}, SUM(impressions) impressions, SUM(clicks) clicks, "
        f"SUM(cost) cost, SUM(conv_count) conv_count, SUM(conv_value) conv_value "
        f"FROM spend WHERE date BETWEEN ? AND ? GROUP BY {sel}"
    )
    out: dict[tuple, Perf] = {}
    for row in conn.execute(sql, (start, end)):
        key = tuple(row[c] for c in cols)
        p = Perf(label=" / ".join(str(k) for k in key if k is not None))
        p.add(row)
        out[key] = p
    return out


def fetch_sales(
    conn: sqlite3.Connection, start: str, end: str, *, by_channel: bool = True
) -> dict[str, dict[str, float]]:
    grp = "store_channel" if by_channel else "'ALL'"
    sql = (
        f"SELECT {grp} AS ch, SUM(orders) orders, SUM(qty) qty, "
        f"SUM(gross_sales) gross_sales, SUM(discount) discount, "
        f"SUM(net_sales) net_sales, SUM(cancels) cancels, SUM(returns) returns, "
        f"SUM(new_customer_orders) new_orders "
        f"FROM sales WHERE date BETWEEN ? AND ? GROUP BY {grp}"
    )
    out: dict[str, dict[str, float]] = {}
    for row in conn.execute(sql, (start, end)):
        realized = (row["net_sales"] or 0) - (row["cancels"] or 0) - (row["returns"] or 0)
        out[row["ch"]] = {
            "orders": int(row["orders"] or 0),
            "qty": int(row["qty"] or 0),
            "gross_sales": float(row["gross_sales"] or 0),
            "discount": float(row["discount"] or 0),
            "net_sales": float(row["net_sales"] or 0),
            "cancels": float(row["cancels"] or 0),
            "returns": float(row["returns"] or 0),
            "realized_sales": realized,
            "new_customer_orders": int(row["new_orders"] or 0),
            "aov": safe_div(realized, int(row["orders"] or 0)) or 0.0,
        }
    return out


def channel_margin_rates(conn: sqlite3.Connection, cfg: Config) -> dict[str, float]:
    """판매채널별 실효 매출총이익률.

    카탈로그에 원가가 있는 SKU는 실제 판매 구성비로 가중평균하고,
    원가가 없으면 설정의 기본 마진율로 메운다.

    채널마다 상품코드 체계가 달라서 sku_map 을 거쳐 통합 SKU 로 바꾼 뒤
    카탈로그와 대조한다. 매핑이 없으면 원본 코드를 그대로 쓴다.
    """
    default_gm = float(cfg.get("default_gross_margin_rate", 0.45))
    sql = (
        "SELECT s.store_channel ch, SUM(s.net_sales) rev, "
        "SUM(CASE WHEN c.price > 0 THEN s.net_sales * (c.price - c.cogs)/c.price "
        "         ELSE s.net_sales * ? END) profit "
        "FROM sales s LEFT JOIN catalog c "
        "  ON c.sku = canon_sku(s.store_channel, s.sku) "
        "GROUP BY s.store_channel"
    )
    out: dict[str, float] = {}
    for row in conn.execute(sql, (default_gm,)):
        rev = float(row["rev"] or 0)
        out[row["ch"]] = (float(row["profit"] or 0) / rev) if rev else default_gm
    for ch in ("smartstore", "coupang", "own"):
        out.setdefault(ch, default_gm)
    return out


@dataclass(slots=True)
class ChannelResult:
    store_channel: str
    ad: Perf
    sales: dict[str, float]
    gross_margin_rate: float
    fee_rate: float
    bep_roas: float | None
    contribution_profit: float
    contribution_margin_rate: float
    ad_cost_ratio: float | None          # 광고비 / 실매출
    attribution_gap: float | None        # (광고전환매출 - 실매출) / 실매출

    def as_dict(self) -> dict:
        return {
            "store_channel": self.store_channel,
            "ad": self.ad.as_dict(),
            "sales": self.sales,
            "gross_margin_rate": self.gross_margin_rate,
            "fee_rate": self.fee_rate,
            "bep_roas": self.bep_roas,
            "contribution_profit": self.contribution_profit,
            "contribution_margin_rate": self.contribution_margin_rate,
            "ad_cost_ratio": self.ad_cost_ratio,
            "attribution_gap": self.attribution_gap,
            "verdict": self.verdict(),
        }

    def verdict(self) -> str:
        """이 채널이 지금 돈을 벌고 있는지 한 단어로."""
        if self.ad.cost == 0:
            return "광고미집행"
        if self.bep_roas is None:
            return "마진구조점검"
        if self.ad.roas is None:
            return "전환없음"
        if self.ad.roas >= self.bep_roas * 1.3:
            return "증액검토"
        if self.ad.roas >= self.bep_roas:
            return "유지"
        if self.ad.roas >= self.bep_roas * 0.7:
            return "개선필요"
        return "즉시축소"


def channel_results(
    conn: sqlite3.Connection, cfg: Config, start: str, end: str
) -> list[ChannelResult]:
    """판매채널 단위 손익 통합."""
    spend = fetch_spend(conn, start, end, group_by=["store_channel"])
    sales = fetch_sales(conn, start, end)
    margins = channel_margin_rates(conn, cfg)

    channels = sorted(set(list(sales.keys()) + [k[0] for k in spend]))
    results: list[ChannelResult] = []
    for ch in channels:
        ad = spend.get((ch,), Perf(label=ch))
        sl = sales.get(ch, {"realized_sales": 0.0, "orders": 0, "aov": 0.0})
        gm = margins.get(ch, float(cfg.get("default_gross_margin_rate", 0.45)))
        fee = cfg.fee_rate(ch)
        cmr = gm - fee
        realized = sl.get("realized_sales", 0.0)
        # 공헌이익 = 실매출 × (마진율 - 수수료율) - 광고비
        contribution = realized * cmr - ad.cost
        results.append(ChannelResult(
            store_channel=ch,
            ad=ad,
            sales=sl,
            gross_margin_rate=gm,
            fee_rate=fee,
            bep_roas=cfg.bep_roas(ch, gm),
            contribution_profit=contribution,
            contribution_margin_rate=safe_div(contribution, realized) or 0.0,
            ad_cost_ratio=safe_div(ad.cost, realized),
            attribution_gap=pct_change(ad.conv_value, realized),
        ))
    return results


def ad_channel_breakdown(
    conn: sqlite3.Connection, cfg: Config, start: str, end: str
) -> list[dict]:
    """광고채널(네이버/쿠팡/메타/인스타/구글) 단위 성과."""
    margins = channel_margin_rates(conn, cfg)
    grouped = fetch_spend(conn, start, end, group_by=["ad_channel", "store_channel"])

    merged: dict[str, dict[str, Any]] = {}
    for (ad_ch, store_ch), perf in grouped.items():
        node = merged.setdefault(ad_ch, {
            "ad_channel": ad_ch, "perf": Perf(label=ad_ch),
            "_bep_num": 0.0, "_bep_den": 0.0, "stores": {},
        })
        node["perf"].impressions += perf.impressions
        node["perf"].clicks += perf.clicks
        node["perf"].cost += perf.cost
        node["perf"].conv_count += perf.conv_count
        node["perf"].conv_value += perf.conv_value
        node["stores"][store_ch] = perf.as_dict()
        # 광고채널이 여러 몰로 트래픽을 보내면 손익분기 ROAS도 비용가중 평균
        bep = cfg.bep_roas(store_ch, margins.get(store_ch))
        if bep:
            node["_bep_num"] += bep * perf.cost
            node["_bep_den"] += perf.cost

    out = []
    for ad_ch, node in merged.items():
        perf: Perf = node["perf"]
        bep = safe_div(node["_bep_num"], node["_bep_den"])
        d = perf.as_dict()
        d.update({
            "ad_channel": ad_ch,
            "bep_roas": bep,
            "roas_vs_bep": (safe_div(perf.roas, bep) if perf.roas and bep else None),
            "stores": node["stores"],
        })
        out.append(d)
    out.sort(key=lambda x: x["cost"], reverse=True)
    return out


def period_comparison(
    conn: sqlite3.Connection, cfg: Config, day: str
) -> dict[str, Any]:
    """당일 vs 전일 / 전주 동요일 / 최근 7일 평균.

    전주 동요일 비교를 넣는 이유: 커머스 매출은 요일 효과가 커서
    전일 대비만 보면 월요일마다 '급락' 경보가 뜬다.
    """
    def snap(s: str, e: str) -> dict:
        spend = fetch_spend(conn, s, e, group_by=["store_channel"])
        total = Perf(label="ALL")
        for p in spend.values():
            total.impressions += p.impressions
            total.clicks += p.clicks
            total.cost += p.cost
            total.conv_count += p.conv_count
            total.conv_value += p.conv_value
        sales = fetch_sales(conn, s, e, by_channel=False).get("ALL", {})
        days = daterange_days(s, e)
        return {
            "start": s, "end": e, "days": days,
            "cost": total.cost / days,
            "realized_sales": sales.get("realized_sales", 0.0) / days,
            "orders": sales.get("orders", 0) / days,
            "roas": total.roas,
        }

    today = snap(day, day)
    prev_day = snap(shift(day, -1), shift(day, -1))
    last_week = snap(shift(day, -7), shift(day, -7))
    trailing7 = snap(shift(day, -7), shift(day, -1))

    def delta(base: dict) -> dict:
        return {
            k: pct_change(today[k], base[k])
            for k in ("cost", "realized_sales", "orders", "roas")
        }

    return {
        "today": today,
        "vs_prev_day": {"base": prev_day, "delta": delta(prev_day)},
        "vs_last_week_same_dow": {"base": last_week, "delta": delta(last_week)},
        "vs_trailing_7d_avg": {"base": trailing7, "delta": delta(trailing7)},
    }


def data_gaps(conn: sqlite3.Connection, day: str, lookback: int = 7) -> list[str]:
    """최근 N일 중 채널별 데이터 결손 목록.

    결손을 숨기면 '광고비 0원 = 효율 무한대' 같은 엉터리 결론이 나온다.
    리포트 최상단에 경고로 올린다.
    """
    days = [shift(day, -i) for i in range(lookback)]
    problems: list[str] = []

    have_spend: dict[str, set[str]] = {}
    for row in conn.execute(
        "SELECT DISTINCT ad_channel, date FROM spend WHERE date BETWEEN ? AND ?",
        (days[-1], day),
    ):
        have_spend.setdefault(row["ad_channel"], set()).add(row["date"])

    for ch, dates in sorted(have_spend.items()):
        missing = sorted(set(days) - dates)
        if missing:
            problems.append(f"광고 {ch}: {len(missing)}일 결손 ({', '.join(missing[:3])}…)")

    have_sales: dict[str, set[str]] = {}
    for row in conn.execute(
        "SELECT DISTINCT store_channel, date FROM sales WHERE date BETWEEN ? AND ?",
        (days[-1], day),
    ):
        have_sales.setdefault(row["store_channel"], set()).add(row["date"])

    for ch in ("smartstore", "coupang", "own"):
        missing = sorted(set(days) - have_sales.get(ch, set()))
        if len(missing) == lookback:
            problems.append(f"매출 {ch}: 최근 {lookback}일 데이터 전무")
        elif missing:
            problems.append(f"매출 {ch}: {len(missing)}일 결손 ({', '.join(missing[:3])}…)")

    return problems
