"""분석 팩 생성.

모든 계산을 끝낸 뒤 하나의 JSON 으로 묶는다. Hermes 스킬은 이 JSON만
읽고 해석·개선안을 쓴다. LLM이 원본 표를 훑으며 암산하는 일이 없도록
하기 위한 경계선이다.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from . import keywords as kw
from . import metrics as mx
from . import opportunities as opp
from . import trends as tr
from .config import Config


PACK_VERSION = "1.0"


def build(
    conn: sqlite3.Connection, cfg: Config, day: str, *, mode: str = "daily"
) -> dict[str, Any]:
    """mode: daily | monthly"""
    gaps = mx.data_gaps(conn, day)

    pack: dict[str, Any] = {
        "pack_version": PACK_VERSION,
        "mode": mode,
        "as_of": day,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "data_quality": {
            "gaps": gaps,
            "trustworthy": not gaps,
            "note": ("결손이 있으면 해당 채널 수치는 과소계상된다. "
                     "리포트 해석 시 반드시 감안할 것."),
        },
        "config_snapshot": {
            "channel_fees": cfg.get("channel_fees"),
            "default_gross_margin_rate": cfg.get("default_gross_margin_rate"),
            "waste_rules": cfg.get("waste_rules"),
        },
    }

    # --- 일일 성과 -------------------------------------------------------
    channels = mx.channel_results(conn, cfg, day, day)
    pack["today"] = {
        "date": day,
        "by_store_channel": [c.as_dict() for c in channels],
        "by_ad_channel": mx.ad_channel_breakdown(conn, cfg, day, day),
        "totals": _totals(channels),
    }
    pack["comparison"] = mx.period_comparison(conn, cfg, day)

    # --- 최근 30일 (판단의 기준 구간) --------------------------------------
    m30_start = mx.shift(day, -29)
    m30 = mx.channel_results(conn, cfg, m30_start, day)
    pack["last_30d"] = {
        "start": m30_start, "end": day,
        "by_store_channel": [c.as_dict() for c in m30],
        "by_ad_channel": mx.ad_channel_breakdown(conn, cfg, m30_start, day),
        "totals": _totals(m30),
    }

    # --- 키워드 진단 -----------------------------------------------------
    pack["keyword_diagnosis"] = kw.diagnose(conn, cfg, day)

    # --- 트렌드 (올해) ---------------------------------------------------
    pack["trends"] = {
        "monthly": tr.monthly_overview(conn, cfg, day),
        "keyword_monthly": tr.keyword_monthly_trend(conn, cfg, day),
        "channel_mix": tr.channel_mix_trend(conn, cfg, day),
    }

    # --- 반등 레버 -------------------------------------------------------
    pack["opportunities"] = opp.collect(conn, cfg, day)

    # --- 우선순위 액션 ---------------------------------------------------
    pack["action_queue"] = _action_queue(pack)

    if mode == "monthly":
        pack["monthly_close"] = _monthly_close(conn, cfg, day)

    return pack


def _totals(channels: list[mx.ChannelResult]) -> dict[str, Any]:
    cost = sum(c.ad.cost for c in channels)
    conv_value = sum(c.ad.conv_value for c in channels)
    realized = sum(c.sales.get("realized_sales", 0.0) for c in channels)
    contribution = sum(c.contribution_profit for c in channels)
    orders = sum(int(c.sales.get("orders", 0)) for c in channels)
    return {
        "ad_cost": cost,
        "ad_conv_value": conv_value,
        "realized_sales": realized,
        "orders": orders,
        "aov": mx.safe_div(realized, orders),
        "blended_roas": mx.safe_div(conv_value, cost),
        "true_roas": mx.safe_div(realized, cost),
        "ad_cost_ratio": mx.safe_div(cost, realized),
        "contribution_profit": contribution,
        "contribution_margin_rate": mx.safe_div(contribution, realized),
        "attribution_gap": mx.pct_change(conv_value, realized),
    }


def _action_queue(pack: dict) -> list[dict]:
    """모든 발견을 '금액 임팩트' 기준 단일 대기열로 병합.

    리포트가 길어지면 아무도 안 읽는다. 오늘 무엇부터 손댈지는 이 목록
    상위 5개면 충분하도록 만든다.
    """
    items: list[dict] = []

    for f in pack["keyword_diagnosis"]["findings"][:30]:
        items.append({
            "type": "키워드",
            "severity": f["severity"],
            "title": f"[{f['ad_channel']}] {f['keyword']}",
            "impact_krw": f["monthly_saving"],
            "impact_kind": "월 절감",
            "evidence": f["evidence"],
            "action": f["action"],
        })

    for n in pack["keyword_diagnosis"]["negative_keyword_candidates"][:15]:
        items.append({
            "type": "제외키워드",
            "severity": "high",
            "title": f"[{n['ad_channel']}] 검색어 '{n['search_term']}'",
            "impact_krw": n["monthly_saving"],
            "impact_kind": "월 절감",
            "evidence": f"클릭 {n['clicks']:,}회 / {n['cost']:,.0f}원 지출, 전환 0",
            "action": n["action"],
        })

    for d in pack["opportunities"]["dead_sku_spend"][:10]:
        items.append({
            "type": "품절/중지 상품",
            "severity": "critical",
            "title": f"[{d['ad_channel']}] {d['product_name'] or d['sku']}",
            "impact_krw": d["monthly_saving"],
            "impact_kind": "월 절감",
            "evidence": f"{d['reason']} 상태로 {d['cost']:,.0f}원 지출",
            "action": d["action"],
        })

    for p in pack["keyword_diagnosis"]["promotion_candidates"][:10]:
        items.append({
            "type": "키워드 승격",
            "severity": "medium",
            "title": f"[{p['ad_channel']}] 검색어 '{p['search_term']}'",
            "impact_krw": p["monthly_value"],
            "impact_kind": "월 매출 기여",
            "evidence": (f"전환 {p['conv_count']:.0f}건 / 매출 "
                         f"{p['conv_value']:,.0f}원, ROAS "
                         f"{(p['roas'] or 0)*100:,.0f}%"),
            "action": p["action"],
        })

    for w in pack["opportunities"]["sku_focus"].get("unadvertised_winners", [])[:5]:
        items.append({
            "type": "광고 사각지대",
            "severity": "medium",
            "title": w["product_name"] or w["sku"],
            "impact_krw": w["revenue"] * 0.15,   # 보수적으로 15% 증분 가정
            "impact_kind": "월 매출 기회(추정)",
            "evidence": (f"최근 30일 매출 {w['revenue']:,.0f}원"
                         f"(전체의 {w['revenue_share']*100:.1f}%)인데 광고비 0원"),
            "action": w["action"],
        })

    realloc = pack["opportunities"]["budget_reallocation"]
    if realloc["expected_added_sales"] > 0:
        items.append({
            "type": "예산 재배분",
            "severity": "high",
            "title": f"손익분기 미달 채널 → 초과 채널로 {realloc['total_releasable']:,.0f}원 이동",
            "impact_krw": realloc["expected_added_sales"],
            "impact_kind": "월 매출 증가(추정)",
            "evidence": (f"회수 가능 {realloc['total_releasable']:,.0f}원, "
                         f"이동 대상 {len(realloc['move_to'])}개 채널"),
            "action": "예산 이동 실행 후 2주간 일별 모니터링",
        })

    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    items.sort(key=lambda x: (order.get(x["severity"], 9), -x["impact_krw"]))
    return items


def _monthly_close(conn: sqlite3.Connection, cfg: Config, day: str) -> dict:
    """월마감 — 기준일이 속한 달의 '직전 달' 전체를 결산한다.

    매월 1일에 돌리면 전월이 대상이 된다.
    """
    d = date.fromisoformat(day)
    last_day_prev = d.replace(day=1) - timedelta(days=1)
    first_day_prev = last_day_prev.replace(day=1)
    start, end = first_day_prev.isoformat(), last_day_prev.isoformat()

    # 전년 동월
    try:
        yoy_start = first_day_prev.replace(year=first_day_prev.year - 1)
        yoy_end = last_day_prev.replace(year=last_day_prev.year - 1)
        yoy = _totals(mx.channel_results(conn, cfg, yoy_start.isoformat(),
                                         yoy_end.isoformat()))
    except ValueError:
        yoy = None

    # 전월(=대상월의 직전월)
    prev_end = first_day_prev - timedelta(days=1)
    prev_start = prev_end.replace(day=1)

    cur = mx.channel_results(conn, cfg, start, end)
    totals = _totals(cur)
    prev_totals = _totals(mx.channel_results(conn, cfg, prev_start.isoformat(),
                                             prev_end.isoformat()))

    target = (cfg.get("targets", {}) or {}).get(first_day_prev.strftime("%Y-%m"))

    return {
        "period": {"start": start, "end": end,
                   "label": first_day_prev.strftime("%Y년 %m월")},
        "totals": totals,
        "by_store_channel": [c.as_dict() for c in cur],
        "by_ad_channel": mx.ad_channel_breakdown(conn, cfg, start, end),
        "vs_prev_month": {
            "period": {"start": prev_start.isoformat(), "end": prev_end.isoformat()},
            "totals": prev_totals,
            "delta": {
                k: mx.pct_change(totals.get(k), prev_totals.get(k))
                for k in ("realized_sales", "ad_cost", "contribution_profit", "orders")
            },
        },
        "vs_same_month_last_year": yoy and {
            "totals": yoy,
            "delta": {
                k: mx.pct_change(totals.get(k), yoy.get(k))
                for k in ("realized_sales", "ad_cost", "contribution_profit", "orders")
            },
        },
        "target": target,
        "target_achievement": (
            mx.safe_div(totals["realized_sales"], target.get("sales"))
            if isinstance(target, dict) and target.get("sales") else None
        ),
        "sales_bridge": opp.sales_bridge(conn, cfg, end, span=30),
        "competitors_to_research": cfg.get("competitors", []),
    }


def brief(pack: dict) -> dict:
    """코멘터리 작성에 필요한 것만 추린 요약본.

    전체 팩은 7만자에 달한다. 이걸 매일 모델 컨텍스트에 통째로 밀어 넣으면
    토큰 비용이 그대로 청구되는데, 해석을 쓰는 데 필요한 것은 그중 일부다.
    월별 추이의 원본 수치나 30일 채널별 원시 집계는 사람이 리포트 표에서
    보면 되는 것이지 모델이 읽을 필요가 없다.

    숫자는 전부 원본 팩에서 그대로 가져온다. 여기서 재계산하지 않는다.
    """
    t = pack["today"]["totals"]
    m30 = pack["last_30d"]["totals"]
    kd = pack["keyword_diagnosis"]
    opp = pack["opportunities"]
    dow = pack["comparison"]["vs_last_week_same_dow"]["delta"]

    def kw(f):
        return {
            "채널": f["ad_channel"], "키워드": f["keyword"],
            "등급": f["severity"], "광고비": round(f["cost"]),
            "ROAS": round(f["roas"], 3) if f["roas"] else 0,
            "손익분기": round(f["bep_roas"], 2) if f["bep_roas"] else None,
            "근거": f["evidence"], "조치": f["action"],
            "월절감": round(f["monthly_saving"]),
        }

    out = {
        "기준일": pack["as_of"],
        "모드": pack["mode"],
        "데이터결손": pack["data_quality"]["gaps"],

        "오늘": {k: round(v) if isinstance(v, (int, float)) and v else v
                 for k, v in {
                     "실매출": t["realized_sales"], "광고비": t["ad_cost"],
                     "주문수": t["orders"], "객단가": t["aov"],
                     "공헌이익": t["contribution_profit"],
                     "광고비비중": round(t["ad_cost_ratio"], 4) if t["ad_cost_ratio"] else None,
                 }.items()},
        "전주동요일대비": {k: (round(v, 3) if v is not None else None)
                          for k, v in dow.items()},

        "최근30일": {
            "실매출": round(m30["realized_sales"]),
            "광고비": round(m30["ad_cost"]),
            "공헌이익": round(m30["contribution_profit"]),
            "어트리뷰션괴리": (round(m30["attribution_gap"], 3)
                              if m30["attribution_gap"] is not None else None),
        },

        "판매채널": [{
            "채널": c["store_channel"],
            "실매출": round(c["sales"].get("realized_sales", 0)),
            "광고비": round(c["ad"]["cost"]),
            "ROAS": round(c["ad"]["roas"], 2) if c["ad"]["roas"] else None,
            "손익분기ROAS": round(c["bep_roas"], 2) if c["bep_roas"] else None,
            "공헌이익": round(c["contribution_profit"]),
            "판정": c["verdict"],
        } for c in pack["today"]["by_store_channel"]],

        "광고채널_30일": [{
            "채널": a["ad_channel"], "광고비": round(a["cost"]),
            "ROAS": round(a["roas"], 2) if a["roas"] else None,
            "손익분기대비": round(a["roas_vs_bep"], 2) if a.get("roas_vs_bep") else None,
        } for a in pack["last_30d"]["by_ad_channel"][:6]],

        "조치대기열": [{
            "구분": a["type"], "등급": a["severity"], "대상": a["title"],
            "임팩트": round(a["impact_krw"]), "종류": a["impact_kind"],
            "근거": a["evidence"], "조치": a["action"],
        } for a in pack["action_queue"][:7]],
        "조치대기열_전체건수": len(pack["action_queue"]),
        "월절감_합계": round(kd["total_monthly_saving"]),

        "낭비키워드": [kw(f) for f in kd["findings"][:5]],
        "제외키워드후보": [{
            "채널": n["ad_channel"], "검색어": n["search_term"],
            "지출": round(n["cost"]), "월절감": round(n["monthly_saving"]),
        } for n in kd["negative_keyword_candidates"][:5]],
        "승격후보": [{
            "채널": p["ad_channel"], "검색어": p["search_term"],
            "전환": p["conv_count"],
            "ROAS": round(p["roas"], 2) if p["roas"] else None,
            "월기여": round(p["monthly_value"]),
        } for p in kd["promotion_candidates"][:5]],

        "매출요인분해": [{
            "채널": b["store_channel"],
            "매출증감률": round(b["revenue_change_pct"], 3) if b["revenue_change_pct"] is not None else None,
            "주원인": b["primary_driver"], "처방": b["prescription"],
        } for b in opp["sales_bridge"]],

        "예산재배분": {
            "회수가능": round(opp["budget_reallocation"]["total_releasable"]),
            "기대추가매출": round(opp["budget_reallocation"]["expected_added_sales"]),
            "이동처수": len(opp["budget_reallocation"]["move_to"]),
        },
        "품절광고": {
            "건수": len(opp["dead_sku_spend"]),
            "월절감": round(sum(d["monthly_saving"] for d in opp["dead_sku_spend"])),
        },

        # 월별 원본 수치는 리포트 표에 이미 있다. 모델에는 추세만 준다.
        "월별추이": [{
            "월": m["month"], "실매출": round(m["realized_sales"]),
            "광고비": round(m["ad_cost"]),
            "전월비": round(m["mom_sales"], 3) if m["mom_sales"] is not None else None,
        } for m in pack["trends"]["monthly"]],
        "핵심키워드추세": [{
            "키워드": k["keyword"], "채널": k["ad_channel"],
            "추세": k["direction"], "올해매출": round(k["ytd_conv_value"]),
        } for k in pack["trends"]["keyword_monthly"]["keywords"]],
    }

    cm = opp.get("customer_mix")
    if cm:
        out["자사몰신규구조"] = {
            "신규비중": round(cm["new_ratio"], 3),
            "CAC": round(cm["cac"]),
            "CAC회수주문수": round(cm["payback_orders"], 2) if cm.get("payback_orders") else None,
        }

    if pack.get("monthly_close"):
        mc = pack["monthly_close"]
        out["월마감"] = {
            "기간": mc["period"]["label"],
            "실적": {k: round(v) for k, v in mc["totals"].items()
                     if isinstance(v, (int, float))},
            "전월비": {k: (round(v, 3) if v is not None else None)
                       for k, v in mc["vs_prev_month"]["delta"].items()},
            "전년동월비": ({k: (round(v, 3) if v is not None else None)
                            for k, v in mc["vs_same_month_last_year"]["delta"].items()}
                           if mc.get("vs_same_month_last_year") else None),
            "목표달성률": (round(mc["target_achievement"], 3)
                          if mc.get("target_achievement") else None),
            "경쟁사": mc["competitors_to_research"],
        }
    return out


def write(pack: dict, out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"pack-{pack['mode']}-{pack['as_of']}.json"
    path.write_text(
        json.dumps(pack, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )
    return path


def write_brief(pack: dict, out_dir: str | Path) -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"brief-{pack['mode']}-{pack['as_of']}.json"
    path.write_text(
        json.dumps(brief(pack), ensure_ascii=False, indent=1, default=str),
        encoding="utf-8",
    )
    return path
