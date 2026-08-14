"""핵심 계산 로직 검증.

의존성 없이 돌아야 하므로 unittest 를 쓴다.

    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import sqlite3
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from adops import analyze, keywords, metrics, opportunities, report, trends  # noqa: E402
from adops import warehouse as wh                                            # noqa: E402
from adops.config import Config, DEFAULTS                                    # noqa: E402
from adops.schema import CatalogRow, SalesRow, SearchTermRow, SpendRow       # noqa: E402


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(wh.SCHEMA_SQL)
    return conn


def cfg() -> Config:
    return Config(dict(DEFAULTS))


class TestBreakevenRoas(unittest.TestCase):
    """손익분기 ROAS는 리포트 전체 판정의 기준선이라 가장 중요하다."""

    def test_formula(self):
        c = cfg()
        # 마진 45%, 수수료 5.85% → 공헌이익률 39.15% → BEP 2.554배
        self.assertAlmostEqual(c.bep_roas("smartstore", 0.45), 1 / 0.3915, places=6)

    def test_channel_fee_changes_breakeven(self):
        c = cfg()
        # 수수료가 높은 쿠팡이 손익분기가 더 높아야 한다
        self.assertGreater(c.bep_roas("coupang", 0.45), c.bep_roas("smartstore", 0.45))

    def test_margin_below_fee_returns_none(self):
        """마진이 수수료보다 낮으면 어떤 ROAS로도 흑자가 안 된다."""
        c = cfg()
        self.assertIsNone(c.bep_roas("coupang", 0.05))


class TestContributionProfit(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        wh.upsert(self.conn, [CatalogRow(sku="A", price=10000, cogs=5000)])
        wh.upsert(self.conn, [SalesRow(
            date="2026-08-13", store_channel="smartstore", sku="A",
            orders=10, qty=10, gross_sales=100000, discount=0)])
        wh.upsert(self.conn, [SpendRow(
            date="2026-08-13", ad_channel="naver_sa", store_channel="smartstore",
            campaign="c", keyword="k", clicks=100, cost=20000,
            conv_count=10, conv_value=100000)])

    def test_contribution(self):
        res = metrics.channel_results(self.conn, cfg(), "2026-08-13", "2026-08-13")
        ss = next(r for r in res if r.store_channel == "smartstore")
        # 마진 50%, 수수료 5.85% → 공헌이익률 44.15%
        # 100,000 × 0.4415 − 20,000 = 24,150
        self.assertAlmostEqual(ss.contribution_profit, 24150, places=2)

    def test_realized_sales_excludes_cancels(self):
        wh.upsert(self.conn, [SalesRow(
            date="2026-08-13", store_channel="coupang", sku="A", orders=5,
            gross_sales=50000, cancels=10000, returns=5000)])
        s = metrics.fetch_sales(self.conn, "2026-08-13", "2026-08-13")
        self.assertEqual(s["coupang"]["realized_sales"], 35000)


class TestWasteRules(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        wh.upsert(self.conn, [CatalogRow(sku="A", price=10000, cogs=5000)])
        rows = []
        for i in range(30):
            d = f"2026-07-{i+1:02d}" if i < 31 else "2026-07-31"
            # 전환 0인 고비용 키워드
            rows.append(SpendRow(date=d, ad_channel="naver_sa",
                                 store_channel="smartstore", campaign="c",
                                 keyword="낭비키워드", clicks=30, cost=30000,
                                 conv_count=0, conv_value=0))
            # 표본 미달 키워드 (판정 제외 대상)
            rows.append(SpendRow(date=d, ad_channel="naver_sa",
                                 store_channel="smartstore", campaign="c",
                                 keyword="소량키워드", clicks=0, cost=100,
                                 conv_count=0, conv_value=0))
        wh.upsert(self.conn, rows)

    def test_zero_conversion_detected(self):
        out = keywords.diagnose(self.conn, cfg(), "2026-07-31")
        kws = {f["keyword"]: f for f in out["findings"]}
        self.assertIn("낭비키워드", kws)
        self.assertEqual(kws["낭비키워드"]["rule"], "zero_conversion_spend")
        self.assertEqual(kws["낭비키워드"]["severity"], "critical")

    def test_low_sample_keyword_not_judged(self):
        """표본 부족 키워드를 끄면 멀쩡한 키워드를 계속 죽이게 된다."""
        out = keywords.diagnose(self.conn, cfg(), "2026-07-31")
        self.assertNotIn("소량키워드", {f["keyword"] for f in out["findings"]})

    def test_monthly_saving_is_30day_normalized(self):
        out = keywords.diagnose(self.conn, cfg(), "2026-07-31")
        f = next(x for x in out["findings"] if x["keyword"] == "낭비키워드")
        # 30일간 30일치 지출 → 월 절감 = 총지출과 동일
        self.assertAlmostEqual(f["monthly_saving"], f["cost"], delta=1.0)


class TestNegativeAndPromotion(unittest.TestCase):
    def setUp(self):
        self.conn = make_conn()
        rows = []
        for i in range(1, 29):
            d = f"2026-07-{i:02d}"
            rows.append(SearchTermRow(
                date=d, ad_channel="naver_sa", campaign="c", keyword="콜라겐",
                search_term="콜라겐 부작용", clicks=5, cost=5000,
                conv_count=0, conv_value=0))
            rows.append(SearchTermRow(
                date=d, ad_channel="naver_sa", campaign="c", keyword="콜라겐",
                search_term="저분자 콜라겐 분말", clicks=5, cost=4000,
                conv_count=1, conv_value=40000))
        wh.upsert(self.conn, rows)

    def test_negative_candidate(self):
        out = keywords.diagnose(self.conn, cfg(), "2026-07-31")
        terms = {n["search_term"] for n in out["negative_keyword_candidates"]}
        self.assertIn("콜라겐 부작용", terms)

    def test_promotion_candidate(self):
        """전환되는 미등록 검색어는 승격 후보로 잡혀야 한다."""
        out = keywords.diagnose(self.conn, cfg(), "2026-07-31")
        terms = {p["search_term"] for p in out["promotion_candidates"]}
        self.assertIn("저분자 콜라겐 분말", terms)


class TestDeadSkuSpend(unittest.TestCase):
    def test_out_of_stock_and_inactive(self):
        conn = make_conn()
        wh.upsert(conn, [
            CatalogRow(sku="OOS", product_name="품절상품", price=10000,
                       cogs=5000, stock_qty=0),
            CatalogRow(sku="OFF", product_name="중지상품", price=10000,
                       cogs=5000, stock_qty=50, active=False),
            CatalogRow(sku="OK", product_name="정상상품", price=10000,
                       cogs=5000, stock_qty=50),
        ])
        wh.upsert(conn, [
            SpendRow(date="2026-08-13", ad_channel="coupang_ads",
                     store_channel="coupang", campaign="c", sku=sku,
                     clicks=10, cost=10000)
            for sku in ("OOS", "OFF", "OK")
        ])
        out = opportunities.wasted_on_dead_skus(conn, cfg(), "2026-08-13")
        self.assertEqual({d["sku"] for d in out}, {"OOS", "OFF"})


class TestSalesBridge(unittest.TestCase):
    def test_traffic_drop_identified(self):
        """트래픽만 반토막 나면 주원인이 '트래픽'으로 나와야 한다."""
        conn = make_conn()
        rows_spend, rows_sales = [], []
        for i in range(60):
            d = metrics.shift("2026-08-13", -i)
            recent = i < 30
            clicks = 50 if recent else 100
            orders = 5 if recent else 10           # 전환율 동일
            rows_spend.append(SpendRow(
                date=d, ad_channel="naver_sa", store_channel="smartstore",
                campaign="c", keyword="k", clicks=clicks, cost=clicks * 100))
            rows_sales.append(SalesRow(
                date=d, store_channel="smartstore", sku="A", orders=orders,
                gross_sales=orders * 10000))
        wh.upsert(conn, rows_spend)
        wh.upsert(conn, rows_sales)

        out = opportunities.sales_bridge(conn, cfg(), "2026-08-13")
        ss = next(b for b in out if b["store_channel"] == "smartstore")
        self.assertEqual(ss["primary_driver"], "트래픽")
        self.assertLess(ss["revenue_change"], 0)


class TestDataGaps(unittest.TestCase):
    def test_missing_days_reported(self):
        conn = make_conn()
        # 7일 중 3일만 적재
        for d in ("2026-08-13", "2026-08-12", "2026-08-11"):
            wh.upsert(conn, [SpendRow(
                date=d, ad_channel="naver_sa", store_channel="smartstore",
                campaign="c", keyword="k", clicks=10, cost=1000)])
        gaps = metrics.data_gaps(conn, "2026-08-13")
        self.assertTrue(any("naver_sa" in g for g in gaps))


class TestIdempotentIngest(unittest.TestCase):
    def test_double_insert_does_not_double_count(self):
        """크론 재시도로 숫자가 두 배가 되면 리포트를 신뢰할 수 없다."""
        conn = make_conn()
        row = SpendRow(date="2026-08-13", ad_channel="naver_sa",
                       store_channel="smartstore", campaign="c",
                       keyword="k", clicks=10, cost=1000)
        wh.upsert(conn, [row])
        wh.upsert(conn, [row])
        total = conn.execute("SELECT SUM(cost) s FROM spend").fetchone()["s"]
        self.assertEqual(total, 1000)


class TestEndToEnd(unittest.TestCase):
    """팩 생성 → HTML 렌더까지 예외 없이 통과하는지."""

    def test_full_pack_and_render(self):
        conn = make_conn()
        wh.upsert(conn, [CatalogRow(sku="A", price=10000, cogs=5000, stock_qty=10)])
        rows_s, rows_v = [], []
        for i in range(40):
            d = metrics.shift("2026-08-13", -i)
            rows_s.append(SpendRow(
                date=d, ad_channel="naver_sa", store_channel="smartstore",
                campaign="c", keyword="k", clicks=50, cost=50000,
                conv_count=5, conv_value=200000))
            rows_v.append(SalesRow(
                date=d, store_channel="smartstore", sku="A", orders=5,
                gross_sales=200000))
        wh.upsert(conn, rows_s)
        wh.upsert(conn, rows_v)

        pack = analyze.build(conn, cfg(), "2026-08-13", mode="daily")
        self.assertEqual(pack["mode"], "daily")
        self.assertIn("action_queue", pack)

        html = report.render(pack)
        self.assertIn("<!doctype html>", html)
        # 계산 실패가 문자열로 새어 나오면 안 된다
        self.assertNotIn("None원", html)
        self.assertNotIn("nan", html)

    def test_monthly_targets_previous_month(self):
        conn = make_conn()
        wh.upsert(conn, [SalesRow(date="2026-07-15", store_channel="own",
                                  sku="A", orders=1, gross_sales=10000)])
        pack = analyze.build(conn, cfg(), "2026-08-01", mode="monthly")
        self.assertEqual(pack["monthly_close"]["period"]["start"], "2026-07-01")
        self.assertEqual(pack["monthly_close"]["period"]["end"], "2026-07-31")


if __name__ == "__main__":
    unittest.main()
