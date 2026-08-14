"""구글 광고 어댑터.

구글은 REST 직접 호출도 가능하지만 OAuth 토큰 갱신·developer token·
로그인 고객 ID 처리가 까다로워, 공식 SDK(google-ads)를 쓰는 편이
유지보수 비용이 훨씬 낮다. SDK가 없으면 건너뛴다.

    pip install google-ads

GAQL 쿼리는 키워드 단위 실적을 가져온다. 쇼핑/PMax 캠페인은 키워드가
없으므로 별도 쿼리가 필요하다 — 필요해지면 _QUERY_PRODUCT 를 추가하라.
"""

from __future__ import annotations

import os

from ..schema import SpendRow
from .base import FetchResult, Source


_QUERY_KEYWORD = """
SELECT
  segments.date,
  campaign.name,
  ad_group.name,
  ad_group_criterion.keyword.text,
  ad_group_criterion.keyword.match_type,
  metrics.impressions,
  metrics.clicks,
  metrics.cost_micros,
  metrics.conversions,
  metrics.conversions_value
FROM keyword_view
WHERE segments.date BETWEEN '{since}' AND '{until}'
  AND metrics.impressions > 0
"""


class GoogleAdsSource(Source):
    name = "google"

    def __init__(self, settings: dict | None = None) -> None:
        super().__init__(settings)
        self.customer_id = str(
            self.settings.get("customer_id") or os.environ.get("GOOGLE_ADS_CUSTOMER_ID", "")
        ).replace("-", "")
        self.store_channel = self.settings.get("store_channel", "own")

    def available(self) -> tuple[bool, str]:
        if not self.customer_id:
            return False, "자격증명 미설정 (GOOGLE_ADS_CUSTOMER_ID)"
        try:
            import google.ads.googleads.client  # noqa: F401
        except ImportError:
            return False, "google-ads SDK 미설치 (pip install google-ads)"
        return True, ""

    def fetch(self, date_from: str, date_to: str) -> list[FetchResult]:
        ok, why = self.available()
        if not ok:
            return [FetchResult([], "spend", self.name, ok=False, message=why)]

        try:
            from google.ads.googleads.client import GoogleAdsClient

            # google-ads.yaml 또는 GOOGLE_ADS_* 환경변수에서 자격증명을 읽는다.
            client = GoogleAdsClient.load_from_env()
            service = client.get_service("GoogleAdsService")
            query = _QUERY_KEYWORD.format(since=date_from, until=date_to)

            rows: list[SpendRow] = []
            for batch in service.search_stream(
                customer_id=self.customer_id, query=query
            ):
                for r in batch.results:
                    kw = r.ad_group_criterion.keyword
                    rows.append(SpendRow(
                        date=r.segments.date,
                        ad_channel="google",
                        store_channel=self.store_channel,
                        campaign=r.campaign.name,
                        adgroup=r.ad_group.name,
                        keyword=kw.text or None,
                        match_type=str(kw.match_type.name).lower() if kw.match_type else "",
                        impressions=int(r.metrics.impressions),
                        clicks=int(r.metrics.clicks),
                        # 구글은 비용을 마이크로 단위로 준다
                        cost=r.metrics.cost_micros / 1_000_000,
                        conv_count=float(r.metrics.conversions),
                        conv_value=float(r.metrics.conversions_value),
                    ))
        except Exception as exc:                            # noqa: BLE001
            return [FetchResult([], "spend", self.name, ok=False, message=str(exc))]

        return [FetchResult(rows, "spend", self.name, ok=True)]
