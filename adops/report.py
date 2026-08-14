"""HTML 리포트 렌더링.

메일 클라이언트(특히 네이버 메일)는 <style> 블록과 외부 CSS를 자주 잘라낸다.
그래서 모든 스타일은 인라인이고, 레이아웃은 table 기반이다. 폰트는 시스템
폰트만 쓴다. 예쁘게 만드는 것보다 '어느 메일 앱에서 열어도 깨지지 않는 것'이
우선이다.
"""

from __future__ import annotations

import html
from typing import Any


# 색: 의미가 있는 곳에만 쓴다. 좋음/나쁨/주의 3단계.
OK = "#0f7b4f"
BAD = "#b3261e"
WARN = "#8a6100"
MUTED = "#5f6368"
LINE = "#e3e5e8"
HEAD_BG = "#f5f6f7"

TD = f"padding:8px 10px;border-bottom:1px solid {LINE};font-size:13px;"
TH = (f"padding:8px 10px;border-bottom:2px solid #d0d3d7;font-size:12px;"
      f"text-align:left;color:{MUTED};font-weight:600;background:{HEAD_BG};")


def esc(s: Any) -> str:
    return html.escape(str(s if s is not None else ""))


def won(v: float | None, digits: int = 0) -> str:
    if v is None:
        return "—"
    return f"{v:,.{digits}f}원"


def pct(v: float | None, digits: int = 1) -> str:
    if v is None:
        return "—"
    return f"{v * 100:,.{digits}f}%"


def signed_pct(v: float | None) -> str:
    if v is None:
        return "—"
    arrow = "▲" if v > 0 else ("▼" if v < 0 else "―")
    return f"{arrow} {abs(v) * 100:,.1f}%"


def delta_html(v: float | None, good_when_up: bool = True) -> str:
    if v is None:
        return f'<span style="color:{MUTED}">—</span>'
    good = (v > 0) if good_when_up else (v < 0)
    color = OK if good else (BAD if abs(v) > 0.0001 else MUTED)
    return f'<span style="color:{color};font-weight:600">{signed_pct(v)}</span>'


def _bar(value: float, maximum: float, width: int = 90) -> str:
    """이미지 없이 막대 그리기. 메일에서 이미지가 차단돼도 보인다."""
    if not maximum:
        return ""
    w = max(int(width * (value / maximum)), 1) if value > 0 else 0
    return (f'<span style="display:inline-block;height:9px;width:{w}px;'
            f'background:#4a6fa5;border-radius:2px;vertical-align:middle"></span>')


def _section(title: str, body: str, note: str = "") -> str:
    note_html = (f'<div style="font-size:12px;color:{MUTED};margin:0 0 10px">'
                 f'{esc(note)}</div>') if note else ""
    return (
        f'<tr><td style="padding:22px 0 0">'
        f'<div style="font-size:15px;font-weight:700;color:#1a1c1e;'
        f'border-left:3px solid #4a6fa5;padding-left:9px;margin-bottom:8px">'
        f'{esc(title)}</div>{note_html}{body}</td></tr>'
    )


def _table(headers: list[str], rows: list[list[str]], aligns: list[str] | None = None) -> str:
    if not rows:
        return f'<div style="font-size:13px;color:{MUTED}">해당 없음</div>'
    aligns = aligns or ["left"] * len(headers)
    head = "".join(
        f'<th style="{TH}text-align:{a}">{esc(h)}</th>'
        for h, a in zip(headers, aligns)
    )
    body = ""
    for r in rows:
        cells = "".join(
            f'<td style="{TD}text-align:{a}">{c}</td>'
            for c, a in zip(r, aligns)
        )
        body += f"<tr>{cells}</tr>"
    return (f'<table role="presentation" cellpadding="0" cellspacing="0" '
            f'style="width:100%;border-collapse:collapse;margin-bottom:4px">'
            f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>")


VERDICT_STYLE = {
    "증액검토": OK, "유지": MUTED, "개선필요": WARN,
    "즉시축소": BAD, "전환없음": BAD, "광고미집행": MUTED,
    "마진구조점검": BAD,
}


def _chip(text: str) -> str:
    color = VERDICT_STYLE.get(text, MUTED)
    return (f'<span style="display:inline-block;padding:2px 7px;border-radius:9px;'
            f'font-size:11px;font-weight:600;color:#fff;background:{color}">'
            f'{esc(text)}</span>')


SEV_LABEL = {"critical": ("긴급", BAD), "high": ("높음", "#c9600a"),
             "medium": ("보통", WARN), "low": ("낮음", MUTED)}


def render(pack: dict) -> str:
    mode = pack["mode"]
    day = pack["as_of"]
    t = pack["today"]["totals"]
    parts: list[str] = []

    # --- 데이터 품질 경고 (있으면 최상단) ----------------------------------
    gaps = pack["data_quality"]["gaps"]
    if gaps:
        items = "".join(f"<li>{esc(g)}</li>" for g in gaps)
        parts.append(
            f'<tr><td style="padding:12px 14px;background:#fdf3f2;'
            f'border:1px solid #f3c9c5;border-radius:6px;margin-bottom:8px">'
            f'<div style="font-weight:700;color:{BAD};font-size:13px;'
            f'margin-bottom:4px">데이터 결손 경고 — 아래 수치는 과소계상되었습니다</div>'
            f'<ul style="margin:4px 0 0 16px;padding:0;font-size:12px;'
            f'color:#5c2b27">{items}</ul></td></tr>'
        )

    # --- 요약 카드 -------------------------------------------------------
    cmp_dow = pack["comparison"]["vs_last_week_same_dow"]["delta"]
    kpis = [
        ("실매출", won(t["realized_sales"]), delta_html(cmp_dow.get("realized_sales"))),
        ("광고비", won(t["ad_cost"]), delta_html(cmp_dow.get("cost"), good_when_up=False)),
        ("광고비 비중", pct(t["ad_cost_ratio"]), ""),
        ("공헌이익", won(t["contribution_profit"]),
         f'<span style="color:{OK if t["contribution_profit"] > 0 else BAD}">'
         f'{pct(t["contribution_margin_rate"])}</span>'),
    ]
    cards = "".join(
        f'<td style="padding:11px 12px;border:1px solid {LINE};border-radius:6px;'
        f'width:25%;vertical-align:top">'
        f'<div style="font-size:11px;color:{MUTED};margin-bottom:3px">{esc(k)}</div>'
        f'<div style="font-size:17px;font-weight:700;color:#1a1c1e">{v}</div>'
        f'<div style="font-size:11px;margin-top:2px">{d}</div></td>'
        f'<td style="width:6px"></td>'
        for k, v, d in kpis
    )
    parts.append(
        f'<tr><td style="padding-top:6px">'
        f'<table role="presentation" cellpadding="0" cellspacing="0" '
        f'style="width:100%;border-collapse:separate"><tr>{cards}</tr></table>'
        f'<div style="font-size:11px;color:{MUTED};margin-top:6px">'
        f'증감은 전주 동요일 대비 (요일 효과 제거)</div></td></tr>'
    )

    # --- 오늘 할 일 ------------------------------------------------------
    queue = pack["action_queue"][:6]
    if queue:
        rows = []
        for i, a in enumerate(queue, 1):
            label, color = SEV_LABEL.get(a["severity"], ("―", MUTED))
            rows.append([
                f'<b>{i}</b>',
                f'<span style="color:{color};font-weight:700;font-size:11px">{label}</span>',
                f'<div style="font-weight:600">{esc(a["title"])}</div>'
                f'<div style="font-size:11px;color:{MUTED};margin-top:2px">'
                f'{esc(a["evidence"])}</div>',
                f'<b>{won(a["impact_krw"])}</b><br>'
                f'<span style="font-size:11px;color:{MUTED}">{esc(a["impact_kind"])}</span>',
                f'<span style="font-size:12px">{esc(a["action"])}</span>',
            ])
        total_save = sum(
            a["impact_krw"] for a in pack["action_queue"]
            if a["impact_kind"] == "월 절감"
        )
        parts.append(_section(
            "오늘 조치할 것",
            _table(["#", "등급", "대상", "임팩트", "권고 조치"], rows,
                   ["center", "center", "left", "right", "left"])
            + f'<div style="margin-top:8px;padding:9px 11px;background:#f2f7f4;'
              f'border-radius:5px;font-size:13px">'
              f'전체 대기열 {len(pack["action_queue"])}건 조치 시 '
              f'<b style="color:{OK}">월 {won(total_save)}</b> 절감 가능</div>',
            "임팩트 금액이 큰 순서. 상위 5건만 처리해도 대부분의 효과가 나온다.",
        ))

    # --- 판매채널별 손익 -------------------------------------------------
    rows = []
    for c in pack["today"]["by_store_channel"]:
        ad, s = c["ad"], c["sales"]
        rows.append([
            esc(_CH_KR.get(c["store_channel"], c["store_channel"])),
            won(s.get("realized_sales")),
            won(ad["cost"]),
            pct(ad["roas"]) if ad["roas"] else "—",
            pct(c["bep_roas"]) if c["bep_roas"] else "—",
            f'<span style="color:{OK if c["contribution_profit"] > 0 else BAD};'
            f'font-weight:600">{won(c["contribution_profit"])}</span>',
            _chip(c["verdict"]),
        ])
    parts.append(_section(
        "판매채널별 손익",
        _table(["채널", "실매출", "광고비", "ROAS", "손익분기 ROAS", "공헌이익", "판정"],
               rows, ["left", "right", "right", "right", "right", "right", "center"]),
        "손익분기 ROAS = 1 ÷ (매출총이익률 − 채널수수료율). 이보다 낮으면 팔수록 손해다.",
    ))

    # --- 광고채널별 성과 -------------------------------------------------
    ad_rows = []
    max_cost = max([a["cost"] for a in pack["last_30d"]["by_ad_channel"]] or [1])
    for a in pack["last_30d"]["by_ad_channel"]:
        ratio = a.get("roas_vs_bep")
        color = OK if (ratio or 0) >= 1 else BAD
        ad_rows.append([
            esc(_AD_KR.get(a["ad_channel"], a["ad_channel"])),
            f'{_bar(a["cost"], max_cost)} {won(a["cost"])}',
            won(a["conv_value"]),
            pct(a["roas"]) if a["roas"] else "—",
            (f'<span style="color:{color};font-weight:600">{ratio:.2f}배</span>'
             if ratio else "—"),
            f'{a["clicks"]:,}',
            won(a["cpc"]) if a["cpc"] else "—",
            pct(a["cvr"], 2) if a["cvr"] else "—",
        ])
    parts.append(_section(
        "광고채널별 성과 (최근 30일)",
        _table(["광고채널", "광고비", "전환매출", "ROAS", "손익분기 대비",
                "클릭", "CPC", "전환율"], ad_rows,
               ["left", "left", "right", "right", "right", "right", "right", "right"]),
        "손익분기 대비 1.00배 미만 = 적자 구간.",
    ))

    # --- 낭비 키워드 -----------------------------------------------------
    kd = pack["keyword_diagnosis"]
    kw_rows = []
    for f in kd["findings"][:12]:
        label, color = SEV_LABEL.get(f["severity"], ("―", MUTED))
        kw_rows.append([
            f'<span style="color:{color};font-weight:700;font-size:11px">{label}</span>',
            esc(_AD_KR.get(f["ad_channel"], f["ad_channel"])),
            f'<b>{esc(f["keyword"])}</b>',
            won(f["cost"]),
            pct(f["roas"]) if f["roas"] else "0%",
            f'<span style="font-size:12px">{esc(f["evidence"])}</span>',
            f'<b style="color:{OK}">{won(f["monthly_saving"])}</b>',
        ])
    parts.append(_section(
        f'불필요 광고비 키워드 (최근 {kd["window"]["days"]}일)',
        _table(["등급", "채널", "키워드", "광고비", "ROAS", "근거", "월 절감"],
               kw_rows,
               ["center", "left", "left", "right", "right", "left", "right"]),
        f'클릭 {kd["thresholds"]["min_clicks"]}회 미만·광고비 '
        f'{kd["thresholds"]["min_cost"]:,.0f}원 미만은 표본 부족으로 판정 제외.',
    ))

    # --- 제외키워드 후보 -------------------------------------------------
    neg = kd["negative_keyword_candidates"][:10]
    if neg:
        parts.append(_section(
            "제외키워드 등록 후보",
            _table(["채널", "검색어", "매칭 키워드", "클릭", "지출", "월 절감"],
                   [[esc(_AD_KR.get(n["ad_channel"], n["ad_channel"])),
                     f'<b>{esc(n["search_term"])}</b>',
                     esc(n["matched_keyword"]), f'{n["clicks"]:,}',
                     won(n["cost"]),
                     f'<b style="color:{OK}">{won(n["monthly_saving"])}</b>']
                    for n in neg],
                   ["left", "left", "left", "right", "right", "right"]),
            "전환 0인 실제 검색어. 개별 키워드를 끄는 것보다 절감 효과가 크다.",
        ))

    # --- 승격 후보 -------------------------------------------------------
    promo = kd["promotion_candidates"][:8]
    if promo:
        parts.append(_section(
            "키워드 승격 후보 (매출 기회)",
            _table(["채널", "검색어", "전환", "전환매출", "ROAS", "월 기여"],
                   [[esc(_AD_KR.get(p["ad_channel"], p["ad_channel"])),
                     f'<b>{esc(p["search_term"])}</b>',
                     f'{p["conv_count"]:.0f}건', won(p["conv_value"]),
                     pct(p["roas"]) if p["roas"] else "—",
                     f'<b style="color:{OK}">{won(p["monthly_value"])}</b>']
                    for p in promo],
                   ["left", "left", "right", "right", "right", "right"]),
            "광범위 매칭에 묻혀 있는 고효율 검색어. 개별 등록 시 입찰 최적화가 가능해진다.",
        ))

    # --- 월별 트렌드 -----------------------------------------------------
    monthly = pack["trends"]["monthly"]
    if monthly:
        mx_sales = max([m["realized_sales"] for m in monthly] or [1])
        parts.append(_section(
            f'{day[:4]}년 월별 추이',
            _table(["월", "실매출", "", "전월비", "광고비", "광고비중",
                    "ROAS", "공헌이익"],
                   [[esc(m["month"]), won(m["realized_sales"]),
                     _bar(m["realized_sales"], mx_sales, 70),
                     delta_html(m["mom_sales"]), won(m["ad_cost"]),
                     pct(m["ad_cost_ratio"]), pct(m["roas"]) if m["roas"] else "—",
                     f'<span style="color:{OK if m["contribution_profit"] > 0 else BAD}">'
                     f'{won(m["contribution_profit"])}</span>']
                    for m in monthly],
                   ["left", "right", "left", "right", "right", "right", "right", "right"]),
        ))

    # --- 핵심 키워드 월별 매출 추이 ---------------------------------------
    kt = pack["trends"]["keyword_monthly"]
    if kt["keywords"]:
        months = kt["months"]
        headers = ["키워드", "채널"] + [m[5:] + "월" for m in months] + ["추세"]
        rows = []
        for k in kt["keywords"]:
            cells = [f'<b>{esc(k["keyword"])}</b>',
                     esc(_AD_KR.get(k["ad_channel"], k["ad_channel"]))]
            for m in months:
                v = k["by_month"][m]["conv_value"]
                cells.append(f'{v/10000:,.0f}' if v else "—")
            d = k["direction"]
            color = {"상승": OK, "하락": BAD, "보합": MUTED}.get(d, MUTED)
            cells.append(f'<span style="color:{color};font-weight:600">{esc(d)}</span>')
            rows.append(cells)
        parts.append(_section(
            "핵심 키워드 월별 매출 추이",
            _table(headers, rows,
                   ["left", "left"] + ["right"] * len(months) + ["center"]),
            "단위: 만원 (전환매출 기준). 추세는 최근 3개월 대비 이전 구간.",
        ))

    # --- 반등 레버 -------------------------------------------------------
    parts.append(_render_opportunities(pack))

    # --- 월마감 ----------------------------------------------------------
    if mode == "monthly" and pack.get("monthly_close"):
        parts.append(_render_monthly(pack["monthly_close"]))

    # --- LLM 코멘터리 자리 ------------------------------------------------
    if pack.get("commentary"):
        parts.append(_section("분석 코멘트 및 개선방안", pack["commentary"]))

    title = ("월마감 상세 분석" if mode == "monthly" else "일일 광고효율 리포트")
    subtitle = (pack.get("monthly_close", {}).get("period", {}).get("label", "")
                if mode == "monthly" else f"{day} 기준")

    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#eef0f2;">
<table role="presentation" cellpadding="0" cellspacing="0" style="width:100%;background:#eef0f2">
<tr><td align="center" style="padding:18px 10px">
<table role="presentation" cellpadding="0" cellspacing="0" style="max-width:860px;width:100%;background:#ffffff;border-radius:8px;padding:22px 24px;font-family:-apple-system,BlinkMacSystemFont,'Malgun Gothic','Apple SD Gothic Neo',sans-serif;color:#1a1c1e">
<tr><td style="border-bottom:2px solid #1a1c1e;padding-bottom:9px">
<div style="font-size:19px;font-weight:800">{esc(title)}</div>
<div style="font-size:12px;color:{MUTED};margin-top:3px">{esc(subtitle)} · 생성 {esc(pack["generated_at"][:16])}</div>
</td></tr>
{''.join(parts)}
<tr><td style="padding-top:22px;border-top:1px solid {LINE};font-size:11px;color:{MUTED}">
모든 금액은 VAT 제외. 실매출은 취소·반품 차감 후 확정 기준.<br>
숫자는 adops 파이프라인이 계산했고, 해석과 개선방안만 Hermes가 작성했습니다.
</td></tr>
</table></td></tr></table></body></html>"""


_CH_KR = {"smartstore": "스마트스토어", "coupang": "쿠팡", "own": "자사몰"}
_AD_KR = {"naver_sa": "네이버 검색광고", "coupang_ads": "쿠팡 광고",
          "meta": "메타(페이스북)", "instagram": "인스타그램", "google": "구글"}


def _render_opportunities(pack: dict) -> str:
    o = pack["opportunities"]
    blocks: list[str] = []

    dead = o["dead_sku_spend"][:6]
    if dead:
        blocks.append(
            "<div style='font-size:13px;font-weight:700;margin:10px 0 5px'>"
            "품절·판매중지 상품 광고비 (즉시 중단 대상)</div>"
            + _table(["채널", "상품", "사유", "지출", "월 절감"],
                     [[esc(_AD_KR.get(d["ad_channel"], d["ad_channel"])),
                       esc(d["product_name"] or d["sku"]), esc(d["reason"]),
                       won(d["cost"]),
                       f'<b style="color:{OK}">{won(d["monthly_saving"])}</b>']
                      for d in dead],
                     ["left", "left", "center", "right", "right"]))

    br = o["sales_bridge"]
    if br:
        blocks.append(
            "<div style='font-size:13px;font-weight:700;margin:14px 0 5px'>"
            "매출 증감 요인분해 (최근 30일 vs 직전 30일)</div>"
            + _table(["채널", "매출 변동", "트래픽 효과", "전환율 효과",
                      "객단가 효과", "주원인", "처방"],
                     [[esc(_CH_KR.get(b["store_channel"], b["store_channel"])),
                       delta_html(b["revenue_change_pct"]),
                       won(b["effects"]["traffic"]), won(b["effects"]["cvr"]),
                       won(b["effects"]["aov"]),
                       f'<b>{esc(b["primary_driver"])}</b>',
                       f'<span style="font-size:12px">{esc(b["prescription"])}</span>']
                      for b in br],
                     ["left", "right", "right", "right", "right", "center", "left"]))

    ra = o["budget_reallocation"]
    if ra["move_to"]:
        blocks.append(
            "<div style='font-size:13px;font-weight:700;margin:14px 0 5px'>"
            "예산 재배분 제안</div>"
            + _table(["이동처", "금액", "현재 ROAS", "손익분기", "기대 추가매출"],
                     [[esc(_AD_KR.get(m["to_ad_channel"], m["to_ad_channel"]))
                       + f' → {esc(_CH_KR.get(m["to_store_channel"], m["to_store_channel"]))}',
                       won(m["amount"]), pct(m["current_roas"]),
                       pct(m["bep_roas"]),
                       f'<b style="color:{OK}">{won(m["expected_added_sales"])}</b>']
                      for m in ra["move_to"]],
                     ["left", "right", "right", "right", "right"])
            + f'<div style="font-size:11px;color:{MUTED};margin-top:5px">'
              f'손익분기 미달 채널에서 {won(ra["total_releasable"])} 회수 가정. '
              f'증액 시 효율 체감 30% 반영한 보수적 추정.</div>')

    sf = o["sku_focus"]
    if sf.get("unadvertised_winners"):
        blocks.append(
            "<div style='font-size:13px;font-weight:700;margin:14px 0 5px'>"
            "광고 사각지대 — 잘 팔리는데 광고가 없는 상품</div>"
            + _table(["상품", "30일 매출", "매출 비중", "광고비"],
                     [[esc(w["product_name"] or w["sku"]), won(w["revenue"]),
                       pct(w["revenue_share"]), won(w["ad_cost"])]
                      for w in sf["unadvertised_winners"][:6]],
                     ["left", "right", "right", "right"]))

    cm = o.get("customer_mix")
    if cm:
        payback = cm.get("payback_orders")
        color = BAD if (payback or 0) > 1 else OK
        blocks.append(
            "<div style='font-size:13px;font-weight:700;margin:14px 0 5px'>"
            "자사몰 신규고객 획득 구조</div>"
            + _table(["신규 주문비중", "재구매 비중", "CAC", "객단가",
                      "첫주문 공헌이익", "CAC 회수 주문수"],
                     [[pct(cm["new_ratio"]), pct(cm["repeat_ratio"]),
                       won(cm["cac"]), won(cm["aov"]),
                       won(cm["first_order_contribution"]),
                       f'<b style="color:{color}">'
                       f'{payback:.2f}건</b>' if payback else "—"]],
                     ["right"] * 6)
            + f'<div style="font-size:11px;color:{MUTED};margin-top:5px">'
              f'{esc(cm["note"])}</div>')

    wd = o["weekday_efficiency"]
    if any(w.get("roas") for w in wd):
        blocks.append(
            "<div style='font-size:13px;font-weight:700;margin:14px 0 5px'>"
            "요일별 효율 (입찰 조정 근거)</div>"
            + _table(["요일"] + [w["weekday"] for w in wd],
                     [["ROAS"] + [pct(w["roas"]) if w["roas"] else "—" for w in wd],
                      ["평균 대비"] + [
                          (f'<span style="color:{OK if w["vs_avg"] >= 1 else BAD}">'
                           f'{w["vs_avg"]:.2f}배</span>') if w.get("vs_avg") else "—"
                          for w in wd]],
                     ["left"] + ["right"] * len(wd)))

    return _section("매출 반등 레버", "".join(blocks) or "해당 없음",
                    "낭비 제거만으로는 매출이 줄어든다. 어디에 더 쓸지가 함께 있어야 한다.")


def _render_monthly(mc: dict) -> str:
    t = mc["totals"]
    prev = mc["vs_prev_month"]["delta"]
    yoy = (mc.get("vs_same_month_last_year") or {}).get("delta", {})
    rows = [
        ["실매출", won(t["realized_sales"]), delta_html(prev.get("realized_sales")),
         delta_html(yoy.get("realized_sales"))],
        ["광고비", won(t["ad_cost"]), delta_html(prev.get("ad_cost"), False),
         delta_html(yoy.get("ad_cost"), False)],
        ["주문수", f'{t["orders"]:,}건', delta_html(prev.get("orders")),
         delta_html(yoy.get("orders"))],
        ["객단가", won(t["aov"]), "—", "—"],
        ["공헌이익", won(t["contribution_profit"]),
         delta_html(prev.get("contribution_profit")),
         delta_html(yoy.get("contribution_profit"))],
        ["광고비 비중", pct(t["ad_cost_ratio"]), "—", "—"],
    ]
    body = _table(["항목", mc["period"]["label"], "전월비", "전년동월비"], rows,
                  ["left", "right", "right", "right"])
    if mc.get("target_achievement"):
        body += (f'<div style="margin-top:8px;padding:9px 11px;background:{HEAD_BG};'
                 f'border-radius:5px;font-size:13px">목표 대비 달성률 '
                 f'<b>{pct(mc["target_achievement"])}</b></div>')
    return _section(f'{mc["period"]["label"]} 마감', body)
