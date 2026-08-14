"""샘플 데이터 생성기.

실제 채널 데이터를 붙이기 전에 파이프라인 전체가 도는지 확인하는 용도.
의도적으로 '문제가 있는' 데이터를 섞어 넣는다 — 전환 0인 고비용 키워드,
품절 상품 광고, 손익분기 미달 채널, 하락 추세 키워드 등. 그래야 진단
로직이 실제로 잡아내는지 확인할 수 있다.

    python3 tools/make_sample_data.py
    python3 -m adops ingest --from 2026-01-01 --to 2026-08-13
"""

from __future__ import annotations

import csv
import math
import random
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"

random.seed(20260814)

END = date(2026, 8, 13)
START = date(2026, 1, 1)

SKUS = [
    # sku, 상품명, 판매가, 원가, 재고, 판매중
    ("SKU-1001", "프리미엄 콜라겐 30포", 39000, 16000, 240, True),
    ("SKU-1002", "저분자 피쉬콜라겐 60포", 59000, 26000, 120, True),
    ("SKU-1003", "비타민D 3000IU", 19000, 6800, 500, True),
    ("SKU-1004", "루테인 지아잔틴", 29000, 12500, 0, True),      # 품절
    ("SKU-1005", "프로바이오틱스 100억", 34000, 15000, 310, True),
    ("SKU-1006", "밀크씨슬 간건강", 24000, 11000, 90, False),    # 판매중지
    ("SKU-1007", "오메가3 알티지", 32000, 14200, 180, True),
    ("SKU-1008", "마그네슘 400", 17000, 7100, 420, True),
]

KEYWORDS = [
    # 키워드, 기본CPC, 전환율, 소속몰, 추세(월 배수)
    ("콜라겐", 980, 0.021, "smartstore", 1.00),
    ("저분자콜라겐", 1250, 0.028, "smartstore", 1.06),
    ("피쉬콜라겐", 1420, 0.024, "smartstore", 0.93),   # 하락
    ("비타민d", 640, 0.031, "smartstore", 1.02),
    ("루테인", 1180, 0.019, "smartstore", 0.88),
    ("유산균", 1520, 0.026, "smartstore", 1.11),
    ("콜라겐추천", 2100, 0.0, "smartstore", 1.00),      # 전환 0 — 낭비
    ("콜라겐효능", 1750, 0.0, "smartstore", 1.00),      # 전환 0 — 낭비
    ("영양제", 2450, 0.004, "smartstore", 1.00),        # 고CPC 저전환
    ("우리브랜드", 420, 0.085, "smartstore", 1.00),     # 브랜드 잠식 대상
    ("오메가3", 1130, 0.023, "coupang", 1.04),
    ("마그네슘", 870, 0.027, "coupang", 1.01),
    ("밀크씨슬", 960, 0.018, "coupang", 0.90),
]

SEARCH_TERMS = [
    ("콜라겐", "콜라겐 부작용", 0.0),
    ("콜라겐", "콜라겐 언제 먹나요", 0.0),
    ("콜라겐", "콜라겐 무료 샘플", 0.0),
    ("유산균", "유산균 가격비교", 0.0),
    ("영양제", "영양제 추천 디시", 0.0),
    ("저분자콜라겐", "저분자 콜라겐 펩타이드 분말", 0.035),  # 승격 후보
    ("비타민d", "비타민d 임산부", 0.029),                    # 승격 후보
]


def daterange():
    d = START
    while d <= END:
        yield d
        d += timedelta(days=1)


def seasonal(d: date) -> float:
    """주말 하락 + 완만한 연간 하락(매출이 가라앉은 상황 재현)."""
    weekday = 0.82 if d.weekday() >= 5 else 1.0
    month_decay = 1.0 - (d.month - 1) * 0.028
    noise = random.uniform(0.86, 1.14)
    return weekday * month_decay * noise


def write_csv(path: Path, header: list[str], rows: list[list]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        w.writerows(rows)
    print(f"  {path.relative_to(ROOT)}  ({len(rows):,}행)")


def main() -> None:
    print("샘플 데이터 생성 중…")

    # --- 네이버 검색광고 ---------------------------------------------------
    naver, coupang_ad, terms = [], [], []
    for d in daterange():
        f = seasonal(d)
        for kw, cpc, cvr, store, trend in KEYWORDS:
            drift = trend ** (d.month - 1)
            clicks = max(int(random.gauss(46, 15) * f * drift), 0)
            if not clicks:
                continue
            cost = round(clicks * cpc * random.uniform(0.9, 1.1))
            conv = sum(1 for _ in range(clicks) if random.random() < cvr)
            value = conv * random.randint(28000, 52000)
            impr = int(clicks / random.uniform(0.018, 0.045))
            row = [d.isoformat(), f"{store}_캠페인", f"{kw}_그룹", kw,
                   impr, clicks, cost, conv, value]
            (naver if store == "smartstore" else coupang_ad).append(row)

        for kw, term, cvr in SEARCH_TERMS:
            clicks = max(int(random.gauss(9, 4) * f), 0)
            if not clicks:
                continue
            cost = round(clicks * random.uniform(900, 2300))
            conv = sum(1 for _ in range(clicks) if random.random() < cvr)
            terms.append([d.isoformat(), "smartstore_캠페인", f"{kw}_그룹",
                          kw, term, int(clicks / 0.03), clicks, cost,
                          conv, conv * random.randint(30000, 48000)])

    write_csv(RAW / "naver_sa" / "keyword_report.csv",
              ["날짜", "캠페인", "광고그룹", "키워드", "노출수", "클릭수",
               "광고비", "전환수", "전환매출액"], naver)
    write_csv(RAW / "naver_search_terms" / "search_terms.csv",
              ["날짜", "캠페인", "광고그룹", "키워드", "검색어", "노출수",
               "클릭수", "광고비", "전환수", "전환매출액"], terms)

    # --- 쿠팡 광고 (품절/중지 상품 광고 포함) --------------------------------
    cp = []
    for row in coupang_ad:
        cp.append(row[:4] + ["SKU-1007"] + row[4:])
    for d in daterange():
        for sku in ("SKU-1004", "SKU-1006"):     # 품절·판매중지인데 광고 집행
            clicks = max(int(random.gauss(14, 6)), 0)
            if not clicks:
                continue
            cp.append([d.isoformat(), "coupang_캠페인", "상품광고", "",
                       sku, int(clicks / 0.03), clicks,
                       round(clicks * random.uniform(800, 1400)), 0, 0])
    write_csv(RAW / "coupang_ads" / "ads_report.csv",
              ["날짜", "캠페인명", "광고그룹", "키워드", "상품ID", "노출수",
               "클릭수", "광고비", "전환판매수량", "전환매출"], cp)

    # --- 메타 / 인스타 -----------------------------------------------------
    meta = []
    for d in daterange():
        f = seasonal(d)
        for platform in ("facebook", "instagram"):
            spend = round(random.gauss(180000, 45000) * f)
            if spend <= 0:
                continue
            clicks = max(int(spend / random.uniform(700, 1500)), 1)
            purchases = sum(1 for _ in range(clicks)
                            if random.random() < (0.012 if platform == "facebook" else 0.019))
            meta.append([d.isoformat(), f"{platform}_전환캠페인", "리타겟팅_세트",
                         platform, "own", int(clicks / 0.011), clicks, spend,
                         purchases, purchases * random.randint(31000, 56000)])
    write_csv(RAW / "meta_ads" / "insights.csv",
              ["일", "캠페인 이름", "광고 세트 이름", "플랫폼", "판매채널",
               "노출", "링크 클릭", "지출 금액", "구매", "구매 전환값"], meta)

    # --- 구글 ---------------------------------------------------------------
    google = []
    for d in daterange():
        f = seasonal(d)
        for kw in ("건강기능식품", "콜라겐 브랜드", "영양제 쇼핑"):
            clicks = max(int(random.gauss(22, 9) * f), 0)
            if not clicks:
                continue
            cost = round(clicks * random.uniform(600, 1900))
            conv = sum(1 for _ in range(clicks) if random.random() < 0.016)
            google.append([d.isoformat(), "google_검색", "일반_그룹", kw,
                           "구문검색", int(clicks / 0.04), clicks, cost,
                           conv, conv * random.randint(29000, 51000), "own"])
    write_csv(RAW / "google_ads" / "keywords.csv",
              ["일", "캠페인", "광고그룹", "키워드", "일치검색유형", "노출수",
               "클릭수", "비용", "전환수", "전환가치", "판매채널"], google)

    # --- 매출 ---------------------------------------------------------------
    for store, folder, share in (("smartstore", "sales_smartstore", 0.46),
                                 ("coupang", "sales_coupang", 0.34),
                                 ("own", "sales_own", 0.20)):
        rows = []
        for d in daterange():
            f = seasonal(d)
            for sku, name, price, cogs, stock, active in SKUS:
                if not active or stock == 0:
                    continue
                qty = max(int(random.gauss(11, 5) * f * share * 2.4), 0)
                if not qty:
                    continue
                gross = qty * price
                disc = round(gross * random.uniform(0.04, 0.16))
                cancels = round(gross * random.uniform(0, 0.03))
                returns = round(gross * random.uniform(0, 0.025))
                row = [d.isoformat(), sku, name, qty, qty, gross, disc,
                       cancels, returns]
                if store == "own":
                    row.append(int(qty * random.uniform(0.45, 0.7)))
                rows.append(row)
        header = ["결제일", "상품코드" if store == "own" else
                  ("상품번호" if store == "smartstore" else "옵션ID"),
                  "상품명", "주문건수", "수량",
                  "결제금액" if store != "smartstore" else "상품금액",
                  "할인액", "취소금액", "반품금액"]
        if store == "own":
            header.append("신규주문수")
        write_csv(RAW / folder / f"{store}_sales.csv", header, rows)

    # --- 카탈로그 -----------------------------------------------------------
    write_csv(RAW / "catalog" / "catalog.csv",
              ["sku", "상품명", "판매가", "원가", "카테고리", "재고", "판매상태"],
              [[s, n, p, c, "건강기능식품", st, "판매중" if a else "판매중지"]
               for s, n, p, c, st, a in SKUS])

    print("\n완료. 다음 명령으로 적재하세요:")
    print(f"  python3 -m adops ingest --from {START} --to {END}")


if __name__ == "__main__":
    main()
