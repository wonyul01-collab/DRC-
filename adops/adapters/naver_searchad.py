"""네이버 검색광고 API 어댑터.

인증 방식(HMAC 서명)은 구현되어 있다. 다만 리포트 조회는 네이버가
'대용량 보고서(StatReport)를 비동기로 생성 → 다운로드 URL 수신 → TSV 다운로드'
방식이라 계정 권한과 보고서 유형에 따라 응답 형태가 달라진다.

따라서 최초 1회는 반드시 실제 계정으로 응답을 확인한 뒤 _parse_* 를
조정해야 한다. 검증 전에는 CSV 어댑터를 쓰는 편이 안전하다.
자격증명이 없으면 조용히 건너뛴다.
"""

from __future__ import annotations

import base64
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


BASE_URL = "https://api.searchad.naver.com"


class NaverSearchAdSource(Source):
    name = "naver_sa"

    def __init__(self, settings: dict | None = None) -> None:
        super().__init__(settings)
        self.api_key = self.settings.get("api_key") or os.environ.get("NAVER_AD_API_KEY", "")
        self.secret = self.settings.get("secret_key") or os.environ.get("NAVER_AD_SECRET_KEY", "")
        self.customer_id = str(
            self.settings.get("customer_id") or os.environ.get("NAVER_AD_CUSTOMER_ID", "")
        )
        self.store_channel = self.settings.get("store_channel", "smartstore")

    def available(self) -> tuple[bool, str]:
        if not (self.api_key and self.secret and self.customer_id):
            return False, ("자격증명 미설정 "
                           "(NAVER_AD_API_KEY / NAVER_AD_SECRET_KEY / NAVER_AD_CUSTOMER_ID)")
        return True, ""

    # -- 인증 -------------------------------------------------------------

    def _headers(self, method: str, path: str) -> dict[str, str]:
        ts = str(int(time.time() * 1000))
        message = f"{ts}.{method}.{path}"
        sig = base64.b64encode(
            hmac.new(self.secret.encode("utf-8"),
                     message.encode("utf-8"),
                     hashlib.sha256).digest()
        ).decode("utf-8")
        return {
            "Content-Type": "application/json; charset=UTF-8",
            "X-Timestamp": ts,
            "X-API-KEY": self.api_key,
            "X-Customer": self.customer_id,
            "X-Signature": sig,
        }

    def _get(self, path: str, params: dict | None = None) -> object:
        qs = f"?{urllib.parse.urlencode(params)}" if params else ""
        req = urllib.request.Request(
            f"{BASE_URL}{path}{qs}",
            headers=self._headers("GET", path),  # 서명 대상은 쿼리 제외 경로
            method="GET",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # -- 수집 -------------------------------------------------------------

    def fetch(self, date_from: str, date_to: str) -> list[FetchResult]:
        ok, why = self.available()
        if not ok:
            return [FetchResult([], "spend", self.name, ok=False, message=why)]

        try:
            # StatReports 는 일자별 보고서를 비동기 생성한다.
            # 응답 스키마는 계정/보고서 유형에 따라 달라지므로 방어적으로 다룬다.
            raw = self._get("/stats", {
                "ids": self.settings.get("campaign_ids", ""),
                "fields": json.dumps(
                    ["impCnt", "clkCnt", "salesAmt", "ccnt", "convAmt"]),
                "timeRange": json.dumps({"since": date_from, "until": date_to}),
                "datePreset": "",
                "breakdown": "keyword",
            })
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:300]
            return [FetchResult([], "spend", self.name, ok=False,
                                message=f"HTTP {exc.code}: {body}")]
        except Exception as exc:                            # noqa: BLE001
            return [FetchResult([], "spend", self.name, ok=False, message=str(exc))]

        rows = self._parse_stats(raw, date_from)
        note = ("" if rows else
                "응답을 파싱하지 못했습니다. 실제 응답 스키마에 맞춰 "
                "_parse_stats 를 조정하세요 (docs/DATA_SOURCES.md 참고).")
        return [FetchResult(rows, "spend", self.name, ok=bool(rows), message=note)]

    def _parse_stats(self, raw, default_date: str) -> list[SpendRow]:
        """네이버 통계 응답 → SpendRow.

        응답이 {"data": [...]} 인 경우와 배열인 경우를 모두 받는다.
        """
        items = raw.get("data", raw) if isinstance(raw, dict) else raw
        if not isinstance(items, list):
            return []

        out: list[SpendRow] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            try:
                out.append(SpendRow(
                    date=str(it.get("dateStart") or it.get("statDt") or default_date)[:10],
                    ad_channel="naver_sa",
                    store_channel=self.store_channel,
                    campaign=str(it.get("campaignName") or it.get("nccCampaignId") or ""),
                    adgroup=str(it.get("adgroupName") or it.get("nccAdgroupId") or ""),
                    keyword=(str(it.get("keyword") or it.get("nccKeywordId") or "") or None),
                    impressions=integer(it.get("impCnt")),
                    clicks=integer(it.get("clkCnt")),
                    cost=num(it.get("salesAmt")),        # 네이버는 salesAmt 가 '광고비'
                    conv_count=num(it.get("ccnt")),
                    conv_value=num(it.get("convAmt")),
                ))
            except (ValueError, TypeError):
                continue
        return out
