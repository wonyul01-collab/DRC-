"""키워드 진단 — '매출과 무관하게 돈만 쓰는 키워드' 도출.

각 규칙은 (판정, 근거 숫자, 권고 조치, 월 절감 추정액)을 함께 낸다.
'ROAS가 낮습니다' 같은 말은 아무도 행동하게 만들지 못한다. 리포트에는
"이 키워드를 끄면 월 32만원이 남는다"까지 나와야 한다.

표본이 부족한 키워드는 판정하지 않는다(min_clicks/min_cost). 클릭 3회에
전환 0이라고 끄면, 실제로는 멀쩡한 키워드를 계속 죽이게 된다.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass, asdict
from statistics import median
from typing import Any

from .config import Config
from .metrics import safe_div, shift


SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


@dataclass(slots=True)
class Finding:
    rule: str
    severity: str
    ad_channel: str
    keyword: str
    campaign: str
    cost: float
    clicks: int
    conv_count: float
    conv_value: float
    roas: float | None
    bep_roas: float | None
    evidence: str
    action: str
    monthly_saving: float       # 조치 시 월 절감(또는 회수) 추정액

    def as_dict(self) -> dict:
        return asdict(self)


def _monthly(amount: float, days: int) -> float:
    return amount / days * 30.0 if days else 0.0


def diagnose(
    conn: sqlite3.Connection, cfg: Config, end_day: str
) -> dict[str, Any]:
    """낭비 키워드 종합 진단."""
    rules = cfg.get("waste_rules", {})
    lookback = int(rules.get("lookback_days", 30))
    min_clicks = int(rules.get("min_clicks", 20))
    min_cost = float(rules.get("min_cost", 30000))
    cpc_mult = float(rules.get("high_cpc_multiple", 1.8))
    cvr_ratio = float(rules.get("low_cvr_ratio", 0.5))

    start = shift(end_day, -(lookback - 1))
    from .metrics import channel_margin_rates
    margins = channel_margin_rates(conn, cfg)

    rows = list(conn.execute(
        "SELECT ad_channel, store_channel, campaign, adgroup, keyword, "
        "SUM(impressions) impressions, SUM(clicks) clicks, SUM(cost) cost, "
        "SUM(conv_count) conv_count, SUM(conv_value) conv_value "
        "FROM spend WHERE date BETWEEN ? AND ? AND keyword IS NOT NULL "
        "AND keyword != '' GROUP BY ad_channel, campaign, adgroup, keyword",
        (start, end_day),
    ))

    # 채널별 중앙값 — '비싸다/전환 안 된다'의 기준선을 절대값이 아니라
    # 같은 채널 내 상대값으로 잡는다. 채널 간 CPC 수준이 원래 다르기 때문.
    by_channel: dict[str, list] = {}
    for r in rows:
        by_channel.setdefault(r["ad_channel"], []).append(r)

    baselines: dict[str, dict[str, float]] = {}
    for ch, items in by_channel.items():
        cpcs = [c for c in (safe_div(i["cost"], i["clicks"]) for i in items) if c]
        cvrs = [c for c in (safe_div(i["conv_count"], i["clicks"]) for i in items) if c]
        baselines[ch] = {
            "median_cpc": median(cpcs) if cpcs else 0.0,
            "median_cvr": median(cvrs) if cvrs else 0.0,
        }

    findings: list[Finding] = []
    brand_kws = {k.strip().lower() for k in cfg.get("brand_keywords", []) or []}

    for r in rows:
        cost = float(r["cost"] or 0)
        clicks = int(r["clicks"] or 0)
        conv = float(r["conv_count"] or 0)
        value = float(r["conv_value"] or 0)
        kw = r["keyword"]
        ch = r["ad_channel"]
        store = r["store_channel"]
        roas = safe_div(value, cost)
        bep = cfg.bep_roas(store, margins.get(store))
        base = baselines.get(ch, {})

        # 표본 부족 — 판정 보류
        if cost < min_cost and clicks < min_clicks:
            continue

        common = dict(
            ad_channel=ch, keyword=kw, campaign=r["campaign"] or "",
            cost=cost, clicks=clicks, conv_count=conv, conv_value=value,
            roas=roas, bep_roas=bep,
        )

        # 1) 전환 0 지출 — 가장 명확한 낭비
        if conv == 0 and clicks >= min_clicks and cost >= min_cost:
            findings.append(Finding(
                rule="zero_conversion_spend",
                severity="critical",
                evidence=(f"{lookback}일간 클릭 {clicks:,}회 / 광고비 "
                          f"{cost:,.0f}원 지출, 전환 0건"),
                action="키워드 OFF 또는 입찰가 최저 하한까지 인하 후 2주 재관찰",
                monthly_saving=_monthly(cost, lookback),
                **common,
            ))
            continue

        # 2) 손익분기 미달 — 팔수록 손해
        if bep and roas is not None and roas < bep and cost >= min_cost:
            # 손익분기까지 끌어올리는 데 필요한 비용 절감분
            breakeven_cost = value / bep if bep else 0.0
            excess = max(cost - breakeven_cost, 0.0)
            sev = "critical" if roas < bep * 0.5 else "high"
            findings.append(Finding(
                rule="below_breakeven_roas",
                severity=sev,
                evidence=(f"ROAS {roas*100:,.0f}% < 손익분기 {bep*100:,.0f}% "
                          f"(광고비 {cost:,.0f}원 / 전환매출 {value:,.0f}원)"),
                action=(f"입찰가 {(1-breakeven_cost/cost)*100:,.0f}% 인하 또는 "
                        f"랜딩·상세페이지 전환율 개선. 2주 내 미개선 시 중단"),
                monthly_saving=_monthly(excess, lookback),
                **common,
            ))
            continue

        # 3) 고CPC·저전환 — 아직 손해는 아니지만 구조적으로 위험
        mcpc, mcvr = base.get("median_cpc", 0), base.get("median_cvr", 0)
        cpc = safe_div(cost, clicks) or 0
        cvr = safe_div(conv, clicks) or 0
        if mcpc and mcvr and cpc > mcpc * cpc_mult and cvr < mcvr * cvr_ratio:
            target_cost = cost * (mcpc * cpc_mult) / cpc if cpc else cost
            findings.append(Finding(
                rule="high_cpc_low_cvr",
                severity="medium",
                evidence=(f"CPC {cpc:,.0f}원(채널 중앙 {mcpc:,.0f}원의 "
                          f"{cpc/mcpc:.1f}배) / CVR {cvr*100:.2f}%"
                          f"(중앙 {mcvr*100:.2f}%)"),
                action="입찰가 단계적 인하 + 소재/썸네일 교체 A/B 테스트",
                monthly_saving=_monthly(max(cost - target_cost, 0), lookback),
                **common,
            ))
            continue

        # 4) 브랜드 키워드 잠식 — 자연검색으로 이미 잡을 트래픽에 지출
        if kw and kw.strip().lower() in brand_kws and cost >= min_cost:
            findings.append(Finding(
                rule="brand_cannibalization",
                severity="medium",
                evidence=(f"브랜드 키워드에 {lookback}일간 {cost:,.0f}원 지출. "
                          f"자연검색 상위 노출 시 상당 부분이 잠식성 지출"),
                action=("2주간 예산 50% 감액 후 실매출 변화 측정. "
                        "매출 유지되면 완전 중단"),
                monthly_saving=_monthly(cost * 0.5, lookback),
                **common,
            ))

    findings.sort(key=lambda f: (SEVERITY_ORDER[f.severity], -f.monthly_saving))

    return {
        "window": {"start": start, "end": end_day, "days": lookback},
        "thresholds": {"min_clicks": min_clicks, "min_cost": min_cost},
        "findings": [f.as_dict() for f in findings],
        "total_monthly_saving": sum(f.monthly_saving for f in findings),
        "negative_keyword_candidates": negative_keywords(
            conn, cfg, start, end_day, min_cost=min_cost
        ),
        "promotion_candidates": promotion_candidates(conn, cfg, start, end_day),
    }


def negative_keywords(
    conn: sqlite3.Connection, cfg: Config, start: str, end: str,
    *, min_cost: float,
) -> list[dict]:
    """검색어 리포트에서 제외키워드 후보 도출.

    등록 키워드가 아니라 '실제 검색된 질의어' 기준이다. 여기서 나오는
    무관 검색어를 제외키워드로 등록하는 것이, 개별 키워드를 끄는 것보다
    보통 절감 효과가 크다.
    """
    rows = conn.execute(
        "SELECT ad_channel, campaign, keyword, search_term, "
        "SUM(clicks) clicks, SUM(cost) cost, SUM(conv_count) conv_count, "
        "SUM(conv_value) conv_value "
        "FROM search_terms WHERE date BETWEEN ? AND ? "
        "GROUP BY ad_channel, campaign, keyword, search_term "
        "HAVING SUM(conv_count) = 0 AND SUM(cost) >= ? "
        "ORDER BY SUM(cost) DESC LIMIT 40",
        (start, end, min_cost * 0.3),
    )
    days = max((_days_between(start, end)), 1)
    return [{
        "ad_channel": r["ad_channel"],
        "campaign": r["campaign"],
        "matched_keyword": r["keyword"],
        "search_term": r["search_term"],
        "clicks": int(r["clicks"] or 0),
        "cost": float(r["cost"] or 0),
        "monthly_saving": _monthly(float(r["cost"] or 0), days),
        "action": "제외키워드(부정키워드) 등록",
    } for r in rows]


def promotion_candidates(
    conn: sqlite3.Connection, cfg: Config, start: str, end: str
) -> list[dict]:
    """반대 방향 — 성과 좋은데 등록 안 된 검색어를 키워드로 승격.

    낭비 제거만 하면 매출은 줄어든다. 매출을 끌어올리려면 이쪽이 필요하다.
    """
    registered = {
        (r["ad_channel"], (r["keyword"] or "").strip().lower())
        for r in conn.execute(
            "SELECT DISTINCT ad_channel, keyword FROM spend "
            "WHERE keyword IS NOT NULL AND keyword != ''"
        )
    }
    out = []
    days = max(_days_between(start, end), 1)
    for r in conn.execute(
        "SELECT ad_channel, campaign, search_term, SUM(clicks) clicks, "
        "SUM(cost) cost, SUM(conv_count) conv_count, SUM(conv_value) conv_value "
        "FROM search_terms WHERE date BETWEEN ? AND ? "
        "GROUP BY ad_channel, campaign, search_term "
        "HAVING SUM(conv_count) >= 2 ORDER BY SUM(conv_value) DESC LIMIT 60",
        (start, end),
    ):
        term = (r["search_term"] or "").strip()
        if (r["ad_channel"], term.lower()) in registered:
            continue
        cost = float(r["cost"] or 0)
        value = float(r["conv_value"] or 0)
        roas = safe_div(value, cost)
        out.append({
            "ad_channel": r["ad_channel"],
            "campaign": r["campaign"],
            "search_term": term,
            "clicks": int(r["clicks"] or 0),
            "cost": cost,
            "conv_count": float(r["conv_count"] or 0),
            "conv_value": value,
            "roas": roas,
            "monthly_value": _monthly(value, days),
            "action": "개별 키워드로 등록 후 전용 입찰가 설정(현재 광범위 매칭에 묻혀 있음)",
        })
    out.sort(key=lambda x: x["monthly_value"], reverse=True)
    return out[:15]


def _days_between(start: str, end: str) -> int:
    from datetime import date
    return (date.fromisoformat(end) - date.fromisoformat(start)).days + 1
