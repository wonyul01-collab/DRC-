"""트렌드 분석 — 올해 발생분을 월 단위로.

일일 리포트에도 '올해 흐름'을 함께 실어야 오늘의 숫자가 좋은지 나쁜지
판단할 수 있다. 숫자 하나만 보면 사람은 항상 최근 며칠에 과민 반응한다.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any

from .config import Config
from .metrics import channel_margin_rates, safe_div


def ytd_range(day: str) -> tuple[str, str]:
    d = date.fromisoformat(day)
    return f"{d.year}-01-01", day


def monthly_overview(
    conn: sqlite3.Connection, cfg: Config, day: str
) -> list[dict[str, Any]]:
    """올해 1월 ~ 기준일까지 월별 매출/광고비/효율/수익성."""
    start, end = ytd_range(day)
    margins = channel_margin_rates(conn, cfg)

    spend: dict[str, dict[str, float]] = {}
    for r in conn.execute(
        "SELECT substr(date,1,7) ym, store_channel, SUM(cost) cost, "
        "SUM(clicks) clicks, SUM(conv_value) conv_value "
        "FROM spend WHERE date BETWEEN ? AND ? GROUP BY ym, store_channel",
        (start, end),
    ):
        node = spend.setdefault(r["ym"], {"cost": 0.0, "clicks": 0.0,
                                          "conv_value": 0.0, "_cm": 0.0})
        node["cost"] += float(r["cost"] or 0)
        node["clicks"] += float(r["clicks"] or 0)
        node["conv_value"] += float(r["conv_value"] or 0)

    sales: dict[str, dict[str, float]] = {}
    for r in conn.execute(
        "SELECT substr(date,1,7) ym, store_channel, SUM(orders) orders, "
        "SUM(net_sales) net_sales, SUM(cancels) cancels, SUM(returns) returns "
        "FROM sales WHERE date BETWEEN ? AND ? GROUP BY ym, store_channel",
        (start, end),
    ):
        ym = r["ym"]
        realized = (float(r["net_sales"] or 0) - float(r["cancels"] or 0)
                    - float(r["returns"] or 0))
        node = sales.setdefault(ym, {"orders": 0.0, "realized": 0.0, "cm": 0.0})
        node["orders"] += float(r["orders"] or 0)
        node["realized"] += realized
        ch = r["store_channel"]
        cmr = margins.get(ch, 0.45) - cfg.fee_rate(ch)
        node["cm"] += realized * cmr

    months = sorted(set(spend) | set(sales))
    out = []
    prev = None
    for ym in months:
        sp = spend.get(ym, {})
        sl = sales.get(ym, {})
        cost = sp.get("cost", 0.0)
        realized = sl.get("realized", 0.0)
        orders = sl.get("orders", 0.0)
        contribution = sl.get("cm", 0.0) - cost
        row = {
            "month": ym,
            "ad_cost": cost,
            "ad_conv_value": sp.get("conv_value", 0.0),
            "realized_sales": realized,
            "orders": int(orders),
            "aov": safe_div(realized, orders),
            "roas": safe_div(sp.get("conv_value", 0.0), cost),
            "ad_cost_ratio": safe_div(cost, realized),
            "contribution_profit": contribution,
            "contribution_margin_rate": safe_div(contribution, realized),
            "mom_sales": None,
            "mom_cost": None,
        }
        if prev:
            row["mom_sales"] = _pc(realized, prev["realized_sales"])
            row["mom_cost"] = _pc(cost, prev["ad_cost"])
        out.append(row)
        prev = row
    return out


def _pc(cur: float, prev: float) -> float | None:
    return (cur - prev) / abs(prev) if prev else None


def keyword_monthly_trend(
    conn: sqlite3.Connection, cfg: Config, day: str, top_n: int | None = None
) -> dict[str, Any]:
    """핵심 키워드별 월별 매출 추이.

    '핵심'은 올해 누적 전환매출 상위 키워드로 정의한다. 광고비 상위로 잡으면
    돈만 많이 쓴 키워드가 올라와서 추이의 의미가 흐려진다.
    """
    start, end = ytd_range(day)
    top_n = top_n or int(cfg.get("report.trend_top_keywords", 8))

    top = [
        (r["ad_channel"], r["keyword"])
        for r in conn.execute(
            "SELECT ad_channel, keyword, SUM(conv_value) v FROM spend "
            "WHERE date BETWEEN ? AND ? AND keyword IS NOT NULL AND keyword != '' "
            "GROUP BY ad_channel, keyword ORDER BY v DESC LIMIT ?",
            (start, end, top_n),
        )
    ]
    if not top:
        return {"months": [], "keywords": []}

    months = sorted({
        r["ym"] for r in conn.execute(
            "SELECT DISTINCT substr(date,1,7) ym FROM spend "
            "WHERE date BETWEEN ? AND ?", (start, end))
    })

    series = []
    for ch, kw in top:
        by_month = {
            r["ym"]: {
                "cost": float(r["cost"] or 0),
                "conv_value": float(r["v"] or 0),
                "conv_count": float(r["c"] or 0),
                "roas": safe_div(float(r["v"] or 0), float(r["cost"] or 0)),
            }
            for r in conn.execute(
                "SELECT substr(date,1,7) ym, SUM(cost) cost, "
                "SUM(conv_value) v, SUM(conv_count) c FROM spend "
                "WHERE date BETWEEN ? AND ? AND ad_channel = ? AND keyword = ? "
                "GROUP BY ym", (start, end, ch, kw))
        }
        values = [by_month.get(m, {}).get("conv_value", 0.0) for m in months]
        series.append({
            "ad_channel": ch,
            "keyword": kw,
            "by_month": {m: by_month.get(m, {"cost": 0.0, "conv_value": 0.0,
                                             "conv_count": 0.0, "roas": None})
                         for m in months},
            "sales_series": values,
            "direction": _direction(values),
            "ytd_conv_value": sum(values),
        })

    return {"months": months, "keywords": series}


def _direction(values: list[float]) -> str:
    """최근 3개월 기울기로 추세 판정. 표본이 적으면 판정하지 않는다."""
    pts = [v for v in values if v is not None]
    if len(pts) < 3:
        return "판정불가"
    recent, before = pts[-3:], pts[:-3]
    ra = sum(recent) / len(recent)
    ba = (sum(before) / len(before)) if before else ra
    if not ba:
        return "신규"
    change = (ra - ba) / ba
    if change > 0.15:
        return "상승"
    if change < -0.15:
        return "하락"
    return "보합"


def channel_mix_trend(
    conn: sqlite3.Connection, cfg: Config, day: str
) -> list[dict[str, Any]]:
    """월별 판매채널 매출 구성비 변화.

    특정 채널 의존도가 올라가는 중이면 그 자체가 리스크다.
    """
    start, end = ytd_range(day)
    data: dict[str, dict[str, float]] = {}
    for r in conn.execute(
        "SELECT substr(date,1,7) ym, store_channel ch, "
        "SUM(net_sales) - SUM(cancels) - SUM(returns) v "
        "FROM sales WHERE date BETWEEN ? AND ? GROUP BY ym, ch",
        (start, end),
    ):
        data.setdefault(r["ym"], {})[r["ch"]] = float(r["v"] or 0)

    out = []
    for ym in sorted(data):
        row = data[ym]
        total = sum(row.values())
        out.append({
            "month": ym,
            "total": total,
            "share": {ch: (v / total if total else None) for ch, v in row.items()},
            "amount": row,
        })
    return out
