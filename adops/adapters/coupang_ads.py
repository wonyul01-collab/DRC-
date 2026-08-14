"""쿠팡 광고 어댑터.

쿠팡 오픈API는 HMAC-SHA256 기반 CEA 서명을 쓴다. 서명 생성은 아래 구현이
정확하지만, 광고 리포트 엔드포인트는 판매자 계약 유형(로켓그로스/마켓플레이스)과
광고 상품에 따라 경로와 응답 스키마가 달라진다.

그래서 최초 1회는 실제 계정 응답을 확인하고 _parse 를 맞춰야 한다.
검증 전에는 CSV 어댑터(쿠팡 광고 관리자 → 보고서 다운로드)를 권장한다.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

from ..schema import SpendRow
from .base import FetchResult, Source, integer, num


BASE_URL = "https://api-gateway.coupang.com"


def cea_signature(method: str, path: str, query: str,
                  access_key: str, secret_key: str) -> tuple[str, str]:
    """쿠팡 CEA 서명 생성. 반환: (Authorization 헤더값, timestamp)"""
    ts = time.strftime("%y%m%dT%H%M%SZ", time.gmtime())
    message = f"{ts}{method}{path}{query}"
    signature = hmac.new(
        secret_key.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    auth = (f"CEA algorithm=HmacSHA256, access-key={access_key}, "
            f"signed-date={ts}, signature={signature}")
    return auth, ts


class CoupangAdsSource(Source):
    name = "coupang_ads"

    def __init__(self, settings: dict | None = None) -> None:
        super().__init__(settings)
        self.access_key = self.settings.get("access_key") or os.environ.get("COUPANG_ACCESS_KEY", "")
        self.secret_key = self.settings.get("secret_key") or os.environ.get("COUPANG_SECRET_KEY", "")
        self.vendor_id = self.settings.get("vendor_id") or os.environ.get("COUPANG_VENDOR_ID", "")

    def available(self) -> tuple[bool, str]:
        if not (self.access_key and self.secret_key and self.vendor_id):
            return False, ("자격증명 미설정 "
                           "(COUPANG_ACCESS_KEY / COUPANG_SECRET_KEY / COUPANG_VENDOR_ID)")
        return True, ""

    def fetch(self, date_from: str, date_to: str) -> list[FetchResult]:
        ok, why = self.available()
        if not ok:
            return [FetchResult([], "spend", self.name, ok=False, message=why)]

        path = f"/v2/providers/openapi/apis/api/v1/vendors/{self.vendor_id}/reports/ads"
        query = urllib.parse.urlencode({
            "startDate": date_from.replace("-", ""),
            "endDate": date_to.replace("-", ""),
        })
        auth, _ = cea_signature("GET", path, query,
                                self.access_key, self.secret_key)
        req = urllib.request.Request(
            f"{BASE_URL}{path}?{query}",
            headers={"Authorization": auth, "Content-Type": "application/json"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(req, timeout=90) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:300]
            return [FetchResult([], "spend", self.name, ok=False,
                                message=f"HTTP {exc.code}: {body}")]
        except Exception as exc:                            # noqa: BLE001
            return [FetchResult([], "spend", self.name, ok=False, message=str(exc))]

        rows = self._parse(payload, date_from)
        note = ("" if rows else
                "응답을 파싱하지 못했습니다. 실제 스키마에 맞춰 _parse 를 "
                "조정하세요 (docs/DATA_SOURCES.md 참고).")
        return [FetchResult(rows, "spend", self.name, ok=bool(rows), message=note)]

    def _parse(self, payload, default_date: str) -> list[SpendRow]:
        items = payload.get("data", payload) if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            return []
        out: list[SpendRow] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            try:
                raw_date = str(it.get("date") or it.get("reportDate") or default_date)
                d = (f"{raw_date[:4]}-{raw_date[4:6]}-{raw_date[6:8]}"
                     if len(raw_date) == 8 and raw_date.isdigit() else raw_date[:10])
                out.append(SpendRow(
                    date=d,
                    ad_channel="coupang_ads",
                    store_channel="coupang",
                    campaign=str(it.get("campaignName") or it.get("campaignId") or ""),
                    adgroup=str(it.get("adGroupName") or ""),
                    keyword=(str(it.get("keyword") or "") or None),
                    sku=(str(it.get("productId") or it.get("vendorItemId") or "") or None),
                    impressions=integer(it.get("impressions")),
                    clicks=integer(it.get("clicks")),
                    cost=num(it.get("adcost") or it.get("spend")),
                    conv_count=num(it.get("orders") or it.get("conversions")),
                    conv_value=num(it.get("sales") or it.get("convValue")),
                ))
            except (ValueError, TypeError):
                continue
        return out
