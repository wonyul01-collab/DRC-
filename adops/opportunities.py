"""매출 반등 레버 — 낭비 제거 너머의 분석.

낭비 키워드를 다 끄면 비용은 줄지만 매출도 같이 준다. 가라앉은 매출을
끌어올리려면 '어디에 더 쓸 것인가'와 '왜 떨어졌는가'가 필요하다.
이 모듈은 그 판단 근거를 계산으로 만든다.

여기 있는 항목은 모두 보유 데이터만으로 계산 가능한 것들이다.
추정이나 감이 들어가는 항목은 넣지 않았다.
"""

from __future__ import annotations

import sqlite3
from typing import Any

from .config import Config
from .metrics import channel_margin_rates, safe_div, shift


# --- 1. 품절/판매중지 상품에 광고비 지출 -----------------------------------

def wasted_on_dead_skus(
    conn: sqlite3.Connection, cfg: Config, end: str, lookback: int = 14
) -> list[dict]:
    """재고 0 또는 판매중지 SKU에 계속 나가는 광고비.

    가장 즉각적인 절감 항목. 조치에 협의가 필요 없고 매출 손실이 0이다.
    """
    start = shift(end, -(lookback - 1))
    rows = conn.execute(
        "SELECT s.ad_channel, s.campaign, s.sku, c.product_name, "
        "c.stock_qty, c.active, SUM(s.cost) cost, SUM(s.clicks) clicks, "
        "SUM(s.conv_count) conv "
        "FROM spend s JOIN catalog c ON c.sku = s.sku "
        "WHERE s.date BETWEEN ? AND ? AND (c.active = 0 OR c.stock_qty = 0) "
        "GROUP BY s.ad_channel, s.campaign, s.sku HAVING SUM(s.cost) > 0 "
        "ORDER BY cost DESC",
        (start, end),
    )
    out = []
    for r in rows:
        cost = float(r["cost"] or 0)
        reason = "판매중지" if not r["active"] else "재고 0"
        out.append({
            "ad_channel": r["ad_channel"],
            "campaign": r["campaign"],
            "sku": r["sku"],
            "product_name": r["product_name"],
            "reason": reason,
            "cost": cost,
            "clicks": int(r["clicks"] or 0),
            "monthly_saving": cost / lookback * 30,
            "action": f"{reason} 상품 광고 즉시 중단 (매출 손실 없음)",
        })
    return out


# --- 2. 예산 재배분 시뮬레이션 ---------------------------------------------

def budget_reallocation(
    conn: sqlite3.Connection, cfg: Config, end: str, lookback: int = 30
) -> dict[str, Any]:
    """손익분기 ROAS 대비 여유도를 기준으로 예산 이동안 산출.

    로직: 손익분기 미달 채널의 초과 지출분을 회수해서, 손익분기를 크게
    상회하는 채널로 옮긴다. 이동 후 기대 매출은 '이동 대상 채널의 현재
    한계 ROAS'로 계산하되, 증액 시 효율 체감을 반영해 70%만 인정한다.
    체감을 무시하면 시뮬레이션이 항상 장밋빛으로 나온다.
    """
    start = shift(end, -(lookback - 1))
    margins = channel_margin_rates(conn, cfg)
    decay = 0.7

    rows = list(conn.execute(
        "SELECT ad_channel, store_channel, SUM(cost) cost, "
        "SUM(conv_value) conv_value, SUM(conv_count) conv_count "
        "FROM spend WHERE date BETWEEN ? AND ? "
        "GROUP BY ad_channel, store_channel HAVING SUM(cost) > 0",
        (start, end),
    ))

    donors, receivers = [], []
    for r in rows:
        cost = float(r["cost"] or 0)
        value = float(r["conv_value"] or 0)
        store = r["store_channel"]
        bep = cfg.bep_roas(store, margins.get(store))
        roas = safe_div(value, cost)
        if not bep or roas is None:
            continue
        item = {
            "ad_channel": r["ad_channel"], "store_channel": store,
            "cost": cost, "conv_value": value, "roas": roas, "bep_roas": bep,
            "headroom": roas / bep,
        }
        if roas < bep:
            # 손익분기까지만 남기고 초과분 회수
            item["releasable"] = max(cost - (value / bep), 0.0)
            donors.append(item)
        elif roas >= bep * 1.2:
            receivers.append(item)

    donors.sort(key=lambda x: -x["releasable"])
    receivers.sort(key=lambda x: -x["headroom"])

    pool = sum(d["releasable"] for d in donors)
    moves, remaining = [], pool
    # 여유도 비중대로 배분
    total_headroom = sum(r["headroom"] for r in receivers) or 1.0
    for rc in receivers:
        if remaining <= 0:
            break
        alloc = min(pool * (rc["headroom"] / total_headroom), remaining)
        # 한 채널에 현재 예산의 50% 넘게 한 번에 증액하지 않는다.
        alloc = min(alloc, rc["cost"] * 0.5)
        if alloc < 10000:
            continue
        expected = alloc * rc["roas"] * decay
        moves.append({
            "to_ad_channel": rc["ad_channel"],
            "to_store_channel": rc["store_channel"],
            "amount": alloc,
            "current_roas": rc["roas"],
            "bep_roas": rc["bep_roas"],
            "expected_added_sales": expected,
            "assumption": f"증액 시 효율 체감 {int((1-decay)*100)}% 반영",
        })
        remaining -= alloc

    return {
        "window": {"start": start, "end": end, "days": lookback},
        "release_from": [{
            "ad_channel": d["ad_channel"], "store_channel": d["store_channel"],
            "current_cost": d["cost"], "roas": d["roas"], "bep_roas": d["bep_roas"],
            "releasable": d["releasable"],
        } for d in donors if d["releasable"] > 0],
        "move_to": moves,
        "total_releasable": pool,
        "unallocated": max(remaining, 0.0),
        "expected_added_sales": sum(m["expected_added_sales"] for m in moves),
    }


# --- 3. 매출 증감 요인분해 --------------------------------------------------

def sales_bridge(
    conn: sqlite3.Connection, cfg: Config, end: str, span: int = 30
) -> list[dict]:
    """매출 변동을 트래픽 × 전환율 × 객단가로 분해.

    '매출이 20% 빠졌다'로는 아무것도 못 한다. 트래픽이 빠진 건지,
    전환이 안 되는 건지, 객단가가 내려간 건지에 따라 처방이 완전히 다르다.
    - 트래픽 하락 → 노출/입찰/신규 키워드
    - 전환율 하락 → 상세페이지/가격경쟁력/리뷰
    - 객단가 하락 → 할인 과다/구성 변경
    """
    cur_s, cur_e = shift(end, -(span - 1)), end
    pre_s, pre_e = shift(end, -(span * 2 - 1)), shift(end, -span)

    def snap(s: str, e: str) -> dict[str, dict[str, float]]:
        clicks: dict[str, float] = {}
        for r in conn.execute(
            "SELECT store_channel ch, SUM(clicks) c FROM spend "
            "WHERE date BETWEEN ? AND ? GROUP BY ch", (s, e)):
            clicks[r["ch"]] = float(r["c"] or 0)
        out: dict[str, dict[str, float]] = {}
        for r in conn.execute(
            "SELECT store_channel ch, SUM(orders) o, "
            "SUM(net_sales)-SUM(cancels)-SUM(returns) v FROM sales "
            "WHERE date BETWEEN ? AND ? GROUP BY ch", (s, e)):
            ch = r["ch"]
            orders = float(r["o"] or 0)
            rev = float(r["v"] or 0)
            tr = clicks.get(ch, 0.0)
            out[ch] = {
                "traffic": tr,
                "cvr": (orders / tr) if tr else 0.0,
                "aov": (rev / orders) if orders else 0.0,
                "revenue": rev,
                "orders": orders,
            }
        return out

    cur, pre = snap(cur_s, cur_e), snap(pre_s, pre_e)
    results = []
    for ch in sorted(set(cur) | set(pre)):
        c = cur.get(ch, {"traffic": 0, "cvr": 0, "aov": 0, "revenue": 0})
        p = pre.get(ch, {"traffic": 0, "cvr": 0, "aov": 0, "revenue": 0})
        if not p["revenue"] and not c["revenue"]:
            continue
        # 순차 분해: 트래픽 → 전환율 → 객단가 순으로 하나씩 교체
        base = p["traffic"] * p["cvr"] * p["aov"]
        after_t = c["traffic"] * p["cvr"] * p["aov"]
        after_c = c["traffic"] * c["cvr"] * p["aov"]
        after_a = c["traffic"] * c["cvr"] * c["aov"]

        effects = {
            "traffic": after_t - base,
            "cvr": after_c - after_t,
            "aov": after_a - after_c,
        }
        driver = max(effects, key=lambda k: abs(effects[k]))
        label = {"traffic": "트래픽", "cvr": "전환율", "aov": "객단가"}[driver]
        prescription = {
            "traffic": "노출 확보 문제 — 입찰가/예산/신규 키워드 확대 검토",
            "cvr": "구매 전환 문제 — 상세페이지·가격경쟁력·리뷰 점검",
            "aov": "객단가 문제 — 할인율 과다 또는 저가 구성 편중 점검",
        }[driver]

        results.append({
            "store_channel": ch,
            "current": {"start": cur_s, "end": cur_e, **c},
            "previous": {"start": pre_s, "end": pre_e, **p},
            "revenue_change": c["revenue"] - p["revenue"],
            "revenue_change_pct": ((c["revenue"] - p["revenue"]) / p["revenue"]
                                   if p["revenue"] else None),
            "effects": effects,
            "primary_driver": label,
            "prescription": prescription,
        })
    return results


# --- 4. SKU 집중도 / 광고 사각지대 ------------------------------------------

def sku_focus(
    conn: sqlite3.Connection, cfg: Config, end: str, lookback: int = 30
) -> dict[str, Any]:
    """매출 상위 SKU 중 광고가 안 붙은 것 = 가장 확실한 증액 후보.

    이미 스스로 팔리는 상품은 광고 반응도 좋다. 반대로 매출 하위인데
    광고비만 먹는 SKU는 정리 대상이다.
    """
    start = shift(end, -(lookback - 1))
    sales = {
        r["sku"]: {
            "sku": r["sku"], "product_name": r["name"],
            "revenue": float(r["v"] or 0), "qty": int(r["q"] or 0),
        }
        for r in conn.execute(
            "SELECT sku, MAX(product_name) name, "
            "SUM(net_sales)-SUM(cancels)-SUM(returns) v, SUM(qty) q "
            "FROM sales WHERE date BETWEEN ? AND ? AND sku != '' "
            "GROUP BY sku", (start, end))
    }
    ad = {
        r["sku"]: float(r["c"] or 0)
        for r in conn.execute(
            "SELECT sku, SUM(cost) c FROM spend WHERE date BETWEEN ? AND ? "
            "AND sku IS NOT NULL AND sku != '' GROUP BY sku", (start, end))
    }
    if not sales:
        return {"unadvertised_winners": [], "overspent_losers": [],
                "concentration": None}

    ranked = sorted(sales.values(), key=lambda x: -x["revenue"])
    total = sum(s["revenue"] for s in ranked) or 1.0

    # 상위 20% SKU가 매출의 몇 %를 차지하는가
    cut = max(int(len(ranked) * 0.2), 1)
    concentration = sum(s["revenue"] for s in ranked[:cut]) / total

    winners = [{
        **s, "ad_cost": ad.get(s["sku"], 0.0),
        "revenue_share": s["revenue"] / total,
        "action": "광고 미집행 상위 매출 상품 — 소액 테스트 예산부터 배정",
    } for s in ranked[:cut] if ad.get(s["sku"], 0.0) <= 0 and s["revenue"] > 0]

    losers = []
    for sku, cost in sorted(ad.items(), key=lambda kv: -kv[1]):
        rev = sales.get(sku, {}).get("revenue", 0.0)
        if cost > 0 and rev < cost:
            losers.append({
                "sku": sku,
                "product_name": sales.get(sku, {}).get("product_name", ""),
                "ad_cost": cost, "revenue": rev,
                "action": "광고비가 해당 SKU 매출을 초과 — 집행 중단 검토",
            })

    return {
        "window": {"start": start, "end": end},
        "concentration_top20pct": concentration,
        "unadvertised_winners": winners[:10],
        "overspent_losers": losers[:10],
    }


# --- 5. 신규/재구매 구조 (자사몰) -------------------------------------------

def customer_mix(
    conn: sqlite3.Connection, cfg: Config, end: str, lookback: int = 30
) -> dict[str, Any] | None:
    """자사몰 신규 주문 비중과 신규고객 획득비용(CAC).

    광고비는 대부분 신규 획득에 쓰이는데, 성과는 전체 매출로 평가한다.
    그러면 재구매가 만든 매출까지 광고 공으로 잡혀 ROAS가 부풀려진다.
    """
    start = shift(end, -(lookback - 1))
    row = conn.execute(
        "SELECT SUM(orders) o, SUM(new_customer_orders) n, "
        "SUM(net_sales)-SUM(cancels)-SUM(returns) v FROM sales "
        "WHERE date BETWEEN ? AND ? AND store_channel = 'own'",
        (start, end),
    ).fetchone()
    if not row or not row["o"]:
        return None
    orders = float(row["o"] or 0)
    new = float(row["n"] or 0)
    if new <= 0:
        return None

    cost = float(conn.execute(
        "SELECT SUM(cost) c FROM spend WHERE date BETWEEN ? AND ? "
        "AND store_channel = 'own'", (start, end)).fetchone()["c"] or 0)

    rev = float(row["v"] or 0)
    aov = rev / orders if orders else 0
    margins = channel_margin_rates(conn, cfg)
    cmr = margins.get("own", 0.45) - cfg.fee_rate("own")

    return {
        "window": {"start": start, "end": end},
        "orders": int(orders),
        "new_customer_orders": int(new),
        "new_ratio": new / orders,
        "repeat_ratio": 1 - (new / orders),
        "ad_cost": cost,
        "cac": cost / new,
        "aov": aov,
        "first_order_contribution": aov * cmr,
        "payback_orders": (cost / new) / (aov * cmr) if aov * cmr else None,
        "note": ("첫 주문 공헌이익으로 CAC를 회수하는 데 필요한 주문 수. "
                 "1을 넘으면 재구매 없이는 신규 획득이 적자."),
    }


# --- 6. 요일 효율 -----------------------------------------------------------

def weekday_efficiency(
    conn: sqlite3.Connection, cfg: Config, end: str, lookback: int = 56
) -> list[dict]:
    """요일별 광고 효율. 요일 입찰 조정(dayparting)의 근거."""
    start = shift(end, -(lookback - 1))
    names = ["월", "화", "수", "목", "금", "토", "일"]
    buckets: dict[int, dict[str, float]] = {
        i: {"cost": 0.0, "conv_value": 0.0, "clicks": 0.0, "days": 0}
        for i in range(7)
    }
    from datetime import date as _date
    seen: dict[int, set] = {i: set() for i in range(7)}

    for r in conn.execute(
        "SELECT date, SUM(cost) c, SUM(conv_value) v, SUM(clicks) k "
        "FROM spend WHERE date BETWEEN ? AND ? GROUP BY date", (start, end)):
        wd = _date.fromisoformat(r["date"]).weekday()
        buckets[wd]["cost"] += float(r["c"] or 0)
        buckets[wd]["conv_value"] += float(r["v"] or 0)
        buckets[wd]["clicks"] += float(r["k"] or 0)
        seen[wd].add(r["date"])

    out = []
    for i in range(7):
        b = buckets[i]
        n = len(seen[i]) or 1
        out.append({
            "weekday": names[i],
            "avg_cost": b["cost"] / n,
            "avg_conv_value": b["conv_value"] / n,
            "roas": safe_div(b["conv_value"], b["cost"]),
            "samples": len(seen[i]),
        })
    roas_vals = [o["roas"] for o in out if o["roas"]]
    if roas_vals:
        avg = sum(roas_vals) / len(roas_vals)
        for o in out:
            o["vs_avg"] = (o["roas"] / avg) if o["roas"] else None
    return out


def collect(conn: sqlite3.Connection, cfg: Config, end: str) -> dict[str, Any]:
    """반등 레버 전체 수집."""
    return {
        "dead_sku_spend": wasted_on_dead_skus(conn, cfg, end),
        "budget_reallocation": budget_reallocation(conn, cfg, end),
        "sales_bridge": sales_bridge(conn, cfg, end),
        "sku_focus": sku_focus(conn, cfg, end),
        "customer_mix": customer_mix(conn, cfg, end),
        "weekday_efficiency": weekday_efficiency(conn, cfg, end),
    }
