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
from adops.schema import (CatalogRow, SalesRow, SearchTermRow,  # noqa: E402
                          SkuMapRow, SpendRow)


def make_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(wh.SCHEMA_SQL)
    # 조회 쿼리가 canon_sku() 를 쓰므로 등록해야 한다. 실제 connect() 와 동일.
    wh.register_sku_map(conn)
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


class TestSkuMapping(unittest.TestCase):
    """채널마다 상품코드 체계가 다르다. 매핑이 없으면 한 채널에만 원가가
    붙고 나머지는 전부 기본 마진율로 추정되어 수익성 판정이 어긋난다."""

    def _conn_with_map(self):
        conn = make_conn()
        # 같은 상품이 채널마다 다른 코드를 쓴다
        wh.upsert(conn, [
            SkuMapRow("smartstore", "1234567890", "SKU-1001"),
            SkuMapRow("coupang", "87654321", "SKU-1001"),
            SkuMapRow("*", "P-1001", "SKU-1001"),
        ])
        wh.register_sku_map(conn)
        # 원가율 40% → 매출총이익률 60% (기본값 45% 와 구분됨)
        wh.upsert(conn, [CatalogRow(sku="SKU-1001", price=10000, cogs=4000,
                                    stock_qty=0)])
        return conn

    def test_margin_resolves_across_channels(self):
        conn = self._conn_with_map()
        for ch, code in (("smartstore", "1234567890"),
                         ("coupang", "87654321"), ("own", "P-1001")):
            wh.upsert(conn, [SalesRow(date="2026-08-13", store_channel=ch,
                                      sku=code, orders=1, gross_sales=10000)])
        rates = metrics.channel_margin_rates(conn, cfg())
        for ch in ("smartstore", "coupang", "own"):
            self.assertAlmostEqual(rates[ch], 0.60, places=6,
                                   msg=f"{ch} 에 원가가 대조되지 않음")

    def test_unmapped_code_falls_back_to_default_margin(self):
        conn = self._conn_with_map()
        wh.upsert(conn, [SalesRow(date="2026-08-13", store_channel="coupang",
                                  sku="매핑없는코드", orders=1, gross_sales=10000)])
        self.assertAlmostEqual(
            metrics.channel_margin_rates(conn, cfg())["coupang"], 0.45, places=6)

    def test_dead_sku_detected_through_mapping(self):
        """품절 판정도 매핑을 거쳐야 한다. 쿠팡 광고는 쿠팡 코드로 들어온다."""
        conn = self._conn_with_map()
        wh.upsert(conn, [SpendRow(date="2026-08-13", ad_channel="coupang_ads",
                                  store_channel="coupang", campaign="c",
                                  sku="87654321", clicks=10, cost=10000)])
        out = opportunities.wasted_on_dead_skus(conn, cfg(), "2026-08-13")
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["reason"], "재고 0")

    def test_channel_specific_beats_wildcard(self):
        conn = make_conn()
        wh.upsert(conn, [SkuMapRow("*", "X1", "SKU-A"),
                         SkuMapRow("coupang", "X1", "SKU-B")])
        wh.register_sku_map(conn)
        q = "SELECT canon_sku(?,?) v"
        self.assertEqual(conn.execute(q, ("coupang", "X1")).fetchone()["v"], "SKU-B")
        self.assertEqual(conn.execute(q, ("own", "X1")).fetchone()["v"], "SKU-A")

    def test_sku_map_csv_profile_recognised(self):
        import tempfile
        from adops.adapters import csv_source
        d = Path(tempfile.mkdtemp())
        f = d / "매핑표.csv"
        f.write_text("채널,채널상품코드,통합SKU,비고\n"
                     "smartstore,1234567890,SKU-1001,콜라겐\n",
                     encoding="utf-8-sig")
        self.assertEqual(csv_source.classify(f)[0][0], "sku_map")


class TestClassify(unittest.TestCase):
    """폴더가 아홉 개라 손으로 넣다 보면 틀린다. 잘못 넣으면 그 채널만
    빠진 리포트가 조용히 나가므로, 헤더로 판별해준다."""

    def setUp(self):
        import tempfile
        from adops.adapters import csv_source
        self.cs = csv_source
        self.tmp = Path(tempfile.mkdtemp())

    def _write(self, name, header, row):
        p = self.tmp / name
        p.write_text(",".join(header) + "\n" + ",".join(row) + "\n",
                     encoding="utf-8-sig")
        return p

    def test_naver_keyword_report(self):
        p = self._write("아무이름.csv",
                        ["날짜", "캠페인", "광고그룹", "키워드", "노출수",
                         "클릭수", "광고비", "전환수", "전환매출액"],
                        ["2026-08-13", "c", "g", "콜라겐", "100", "5", "5000", "1", "30000"])
        self.assertEqual(self.cs.classify(p)[0][0], "naver_sa")

    def test_search_term_report_not_confused_with_keyword_report(self):
        """검색어 보고서는 키워드 보고서와 컬럼이 거의 겹친다."""
        p = self._write("보고서.csv",
                        ["날짜", "캠페인", "광고그룹", "키워드", "검색어",
                         "노출수", "클릭수", "광고비", "전환수", "전환매출액"],
                        ["2026-08-13", "c", "g", "콜라겐", "콜라겐 추천",
                         "100", "5", "5000", "0", "0"])
        self.assertEqual(self.cs.classify(p)[0][0], "naver_search_terms")

    def test_catalog(self):
        p = self._write("상품표.csv",
                        ["sku", "상품명", "판매가", "원가", "카테고리", "재고", "판매상태"],
                        ["A1", "콜라겐", "39000", "16000", "건기식", "10", "판매중"])
        self.assertEqual(self.cs.classify(p)[0][0], "catalog")

    def test_unknown_header_returns_no_confident_match(self):
        p = self._write("이상한파일.csv", ["가", "나", "다"], ["1", "2", "3"])
        cands = self.cs.classify(p)
        self.assertTrue(not cands or cands[0][1] < 0.4)


class TestMarginSource(unittest.TestCase):
    """doctor 가 알려주는 손익분기 ROAS 와 리포트가 판정에 쓰는 값이
    달라서는 안 된다. 어긋나면 맞는 값을 틀렸다고 보고 엉뚱한 곳을 고친다."""

    def test_catalog_cogs_overrides_default_margin(self):
        conn = make_conn()
        # 원가율 40% → 매출총이익률 60% (기본값 45% 와 다르게)
        wh.upsert(conn, [CatalogRow(sku="A", price=10000, cogs=4000)])
        wh.upsert(conn, [SalesRow(date="2026-08-13", store_channel="smartstore",
                                  sku="A", orders=1, gross_sales=10000)])
        rates = metrics.channel_margin_rates(conn, cfg())
        self.assertAlmostEqual(rates["smartstore"], 0.60, places=6)
        self.assertNotAlmostEqual(rates["smartstore"], 0.45, places=2)

    def test_missing_cogs_falls_back_to_default(self):
        conn = make_conn()
        wh.upsert(conn, [SalesRow(date="2026-08-13", store_channel="coupang",
                                  sku="ZZ", orders=1, gross_sales=10000)])
        rates = metrics.channel_margin_rates(conn, cfg())
        self.assertAlmostEqual(rates["coupang"], 0.45, places=6)

    def test_bep_follows_actual_margin(self):
        conn = make_conn()
        wh.upsert(conn, [CatalogRow(sku="A", price=10000, cogs=4000)])
        wh.upsert(conn, [SalesRow(date="2026-08-13", store_channel="smartstore",
                                  sku="A", orders=1, gross_sales=10000)])
        c = cfg()
        gm = metrics.channel_margin_rates(conn, c)["smartstore"]
        # 공헌이익률 = 0.60 - 0.0585 = 0.5415 → BEP = 1/0.5415
        self.assertAlmostEqual(c.bep_roas("smartstore", gm), 1 / 0.5415, places=6)


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

    def test_null_keyword_is_also_idempotent(self):
        """메타·인스타·구글 일부·쿠팡 상품광고는 키워드가 없다.

        SQLite 는 PRIMARY KEY 안의 NULL 을 매번 서로 다른 값으로 취급하므로,
        NULL 을 그대로 두면 INSERT OR REPLACE 가 기존 행을 찾지 못해 재적재
        때마다 광고비가 누적된다. 스킬이 매일 최근 3일을 다시 넣기 때문에
        이 채널들의 ROAS 와 공헌이익이 날마다 잘못 하락하게 된다.
        """
        conn = make_conn()
        row = SpendRow(date="2026-08-13", ad_channel="meta",
                       store_channel="own", campaign="c",
                       keyword=None, clicks=10, cost=1000)
        for _ in range(5):
            wh.upsert(conn, [row])
        r = conn.execute("SELECT COUNT(*) n, SUM(cost) s FROM spend").fetchone()
        self.assertEqual(r["n"], 1)
        self.assertEqual(r["s"], 1000)

    def test_same_campaign_different_skus_kept_apart(self):
        """상품광고는 상품이 행의 정체성이다. sku 가 키에 없으면 같은
        캠페인의 여러 상품이 서로를 덮어써서 하나만 남는다."""
        conn = make_conn()
        wh.upsert(conn, [
            SpendRow(date="2026-08-13", ad_channel="coupang_ads",
                     store_channel="coupang", campaign="c", sku=sku, cost=1000)
            for sku in ("A", "B", "C")
        ])
        r = conn.execute("SELECT COUNT(*) n, SUM(cost) s FROM spend").fetchone()
        self.assertEqual((r["n"], r["s"]), (3, 3000))

    def test_null_keyword_stored_as_empty_string(self):
        """키워드 분석 쿼리가 `!= ''` 로 거르므로 빈 문자열이어야 한다."""
        conn = make_conn()
        wh.upsert(conn, [SpendRow(date="2026-08-13", ad_channel="meta",
                                  store_channel="own", campaign="c",
                                  keyword=None, cost=1000)])
        self.assertEqual(
            conn.execute("SELECT keyword FROM spend").fetchone()["keyword"], "")

    def test_migration_dedupes_legacy_rows(self):
        """예전 스키마로 이미 중복이 쌓인 DB 도 복구되어야 한다."""
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        # 예전 스키마 재현 (keyword NULL 허용)
        conn.executescript("""
            CREATE TABLE spend (
                date TEXT NOT NULL, ad_channel TEXT NOT NULL,
                store_channel TEXT NOT NULL, campaign TEXT NOT NULL DEFAULT '',
                adgroup TEXT NOT NULL DEFAULT '', keyword TEXT,
                match_type TEXT NOT NULL DEFAULT '',
                impressions INTEGER NOT NULL DEFAULT 0,
                clicks INTEGER NOT NULL DEFAULT 0, cost REAL NOT NULL DEFAULT 0,
                conv_count REAL NOT NULL DEFAULT 0,
                conv_value REAL NOT NULL DEFAULT 0, sku TEXT,
                PRIMARY KEY (date, ad_channel, campaign, adgroup, keyword, match_type)
            );""")
        for _ in range(4):
            conn.execute(
                "INSERT INTO spend (date,ad_channel,store_channel,campaign,"
                "keyword,cost) VALUES ('2026-08-13','meta','own','c',NULL,1000)")
        self.assertEqual(
            conn.execute("SELECT SUM(cost) s FROM spend").fetchone()["s"], 4000)

        removed = wh.migrate(conn)
        self.assertEqual(removed, 3)
        r = conn.execute("SELECT COUNT(*) n, SUM(cost) s FROM spend").fetchone()
        self.assertEqual((r["n"], r["s"]), (1, 1000))

        # 마이그레이션 후에도 멱등해야 한다
        wh.upsert(conn, [SpendRow(date="2026-08-13", ad_channel="meta",
                                  store_channel="own", campaign="c",
                                  keyword=None, cost=1000)])
        self.assertEqual(
            conn.execute("SELECT COUNT(*) n FROM spend").fetchone()["n"], 1)


class TestCommentaryGate(unittest.TestCase):
    """코멘터리가 빠진 채 리포트가 조용히 만들어지면 안 된다.

    에이전트의 쓰기 권한이 막혀 파일이 생성되지 않았는데도 리포트는
    정상 생성되어, 해석 없는 리포트가 그대로 발송된 사고가 있었다.
    """

    def setUp(self):
        import tempfile
        from adops import cli
        self.cli = cli
        self.tmp = tempfile.mkdtemp()
        conn = make_conn()
        wh.upsert(conn, [SpendRow(
            date="2026-08-13", ad_channel="naver_sa", store_channel="smartstore",
            campaign="c", keyword="k", clicks=10, cost=10000,
            conv_count=1, conv_value=40000)])
        wh.upsert(conn, [SalesRow(date="2026-08-13", store_channel="smartstore",
                                  sku="A", orders=1, gross_sales=40000)])
        self.db = str(Path(self.tmp) / "t.db")
        with wh.connect(self.db) as c2:
            wh.upsert(c2, [SpendRow(
                date="2026-08-13", ad_channel="naver_sa",
                store_channel="smartstore", campaign="c", keyword="k",
                clicks=10, cost=10000, conv_count=1, conv_value=40000)])
            wh.upsert(c2, [SalesRow(date="2026-08-13",
                                    store_channel="smartstore", sku="A",
                                    orders=1, gross_sales=40000)])

    def _run(self, extra):
        return self.cli.main(["--db", self.db, "report", "--date", "2026-08-13",
                              "--out", self.tmp] + extra)

    def test_missing_commentary_file_fails(self):
        rc = self._run(["--commentary", str(Path(self.tmp) / "nope.html")])
        self.assertEqual(rc, 2)

    def test_empty_commentary_file_fails(self):
        p = Path(self.tmp) / "empty.html"
        p.write_text("   \n", encoding="utf-8")
        rc = self._run(["--commentary", str(p)])
        self.assertEqual(rc, 2)

    def test_present_commentary_is_embedded(self):
        p = Path(self.tmp) / "c.html"
        p.write_text("<div>해석 본문</div>", encoding="utf-8")
        rc = self._run(["--commentary", str(p)])
        self.assertEqual(rc, 0)
        html = (Path(self.tmp) / "report-daily-2026-08-13.html").read_text(
            encoding="utf-8")
        self.assertIn("해석 본문", html)

    def test_no_commentary_flag_is_allowed(self):
        """--commentary 를 아예 안 주면 숫자만 있는 리포트도 정상이다."""
        self.assertEqual(self._run([]), 0)


class TestBrief(unittest.TestCase):
    """요약본은 토큰 비용을 좌우한다. 전체 팩은 7만자가 넘어서, 매일
    통째로 모델에 넣으면 그만큼 매일 청구된다."""

    def setUp(self):
        conn = make_conn()
        wh.upsert(conn, [CatalogRow(sku="A", price=10000, cogs=5000, stock_qty=10)])
        rows_s, rows_v = [], []
        for i in range(40):
            d = metrics.shift("2026-08-13", -i)
            rows_s.append(SpendRow(
                date=d, ad_channel="naver_sa", store_channel="smartstore",
                campaign="c", keyword="k", clicks=50, cost=50000,
                conv_count=5, conv_value=200000))
            rows_v.append(SalesRow(date=d, store_channel="smartstore", sku="A",
                                   orders=5, gross_sales=200000))
        wh.upsert(conn, rows_s)
        wh.upsert(conn, rows_v)
        self.pack = analyze.build(conn, cfg(), "2026-08-13", mode="daily")

    def test_brief_is_much_smaller(self):
        import json
        full = len(json.dumps(self.pack, ensure_ascii=False))
        small = len(json.dumps(analyze.brief(self.pack), ensure_ascii=False))
        self.assertLess(small, full * 0.35,
                        f"요약본이 충분히 줄지 않음: {small} vs {full}")

    def test_brief_keeps_decision_inputs(self):
        """줄이더라도 판단 근거는 남아야 한다."""
        b = analyze.brief(self.pack)
        for key in ("데이터결손", "오늘", "판매채널", "조치대기열",
                    "매출요인분해", "월별추이"):
            self.assertIn(key, b)

    def test_brief_numbers_match_pack(self):
        """요약본에서 재계산하지 않는다. 원본과 값이 달라지면 안 된다."""
        b = analyze.brief(self.pack)
        self.assertEqual(b["오늘"]["실매출"],
                         round(self.pack["today"]["totals"]["realized_sales"]))
        self.assertEqual(b["조치대기열_전체건수"], len(self.pack["action_queue"]))

    def test_monthly_brief_includes_close(self):
        conn = make_conn()
        wh.upsert(conn, [SalesRow(date="2026-07-15", store_channel="own",
                                  sku="A", orders=1, gross_sales=10000)])
        pack = analyze.build(conn, cfg(), "2026-08-01", mode="monthly")
        b = analyze.brief(pack)
        self.assertIn("월마감", b)
        self.assertEqual(b["월마감"]["기간"], "2026년 07월")


class TestDailyFlags(unittest.TestCase):
    """크론 줄에 적어둔 옵션이 실제로 인식되어야 한다. 문서와 코드가
    어긋나면 매일 아침 조용히 실패한다."""

    def _parse(self, argv):
        from adops import cli
        return cli.build_parser().parse_args(argv)

    def test_mail_is_default(self):
        self.assertTrue(self._parse(["daily"]).mail)

    def test_explicit_mail_flag_accepted(self):
        self.assertTrue(self._parse(["daily", "--mail"]).mail)

    def test_no_mail_disables(self):
        self.assertFalse(self._parse(["daily", "--no-mail"]).mail)


class TestMailer(unittest.TestCase):
    """LLM 없이도 리포트가 나가야 한다. 크레딧 소진으로 에이전트가 통째로
    멈춘 적이 있고, 그때 크론이 걸려 있었다면 아침에 메일이 그냥 오지 않고
    원인조차 드러나지 않았을 것이다."""

    def setUp(self):
        import tempfile
        from adops import mailer
        self.mailer = mailer
        self.tmp = Path(tempfile.mkdtemp())
        self.html = self.tmp / "r.html"
        self.html.write_text("<b>리포트</b>", encoding="utf-8")

    def _env(self, **over):
        vals = {
            "EMAIL_ADDRESS": "a@gmail.com",
            "EMAIL_PASSWORD": "abcdefghijklmnop",
            "EMAIL_SMTP_HOST": "smtp.gmail.com",
            "EMAIL_HOME_ADDRESS": "x@naver.com",
        }
        vals.update(over)
        p = self.tmp / f"env{len(list(self.tmp.iterdir()))}"
        p.write_text("\n".join(f"{k}={v}" for k, v in vals.items() if v is not None),
                     encoding="utf-8")
        return p

    def test_dry_run_resolves_recipients(self):
        r = self.mailer.send_report(self.html, "제목", env_path=self._env(),
                                    dry_run=True)
        self.assertEqual(r, ["x@naver.com"])

    def test_multiple_recipients(self):
        env = self._env(EMAIL_HOME_ADDRESS="a@b.com, c@d.com")
        r = self.mailer.send_report(self.html, "제목", env_path=env, dry_run=True)
        self.assertEqual(r, ["a@b.com", "c@d.com"])

    def test_truncated_app_password_rejected(self):
        """구글 앱 비밀번호를 공백째 넣으면 셸이 잘라 4자만 남는다.
        조용히 인증 실패하는 것보다 여기서 막는 편이 낫다."""
        env = self._env(EMAIL_PASSWORD="abcd")
        with self.assertRaises(self.mailer.MailNotConfigured) as ctx:
            self.mailer.send_report(self.html, "제목", env_path=env, dry_run=True)
        self.assertIn("4자", str(ctx.exception))

    def test_missing_credentials_rejected(self):
        env = self._env(EMAIL_PASSWORD=None)
        with self.assertRaises(self.mailer.MailNotConfigured):
            self.mailer.send_report(self.html, "제목", env_path=env, dry_run=True)

    def test_no_recipient_rejected(self):
        env = self._env(EMAIL_HOME_ADDRESS="")
        with self.assertRaises(self.mailer.MailNotConfigured):
            self.mailer.send_report(self.html, "제목", env_path=env, dry_run=True)

    def test_subject_carries_key_figures(self):
        pack = {"mode": "daily", "as_of": "2026-08-13",
                "today": {"totals": {"realized_sales": 3786501,
                                     "contribution_profit": 585191}},
                "data_quality": {"gaps": []}}
        s = self.mailer.subject_for(pack)
        self.assertIn("2026-08-13", s)
        self.assertIn("3,786,501", s)

    def test_subject_flags_data_gaps(self):
        pack = {"mode": "daily", "as_of": "2026-08-13",
                "today": {"totals": {}},
                "data_quality": {"gaps": ["광고 naver_sa: 2일 결손"]}}
        self.assertIn("결손", self.mailer.subject_for(pack))


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
