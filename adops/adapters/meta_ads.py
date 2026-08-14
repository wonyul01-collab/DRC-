"""메타(페이스북/인스타그램) 광고 어댑터.

Graph API insights 엔드포인트를 쓴다. publisher_platform 으로 분해해서
페이스북 지면과 인스타그램 지면을 별도 광고채널로 적재한다 — 두 지면의
CPC/전환율 차이가 커서 합산하면 판단이 흐려진다.

액세스 토큰은 장기 토큰(long-lived)이어야 한다. 단기 토큰은 며칠 만에
만료돼서 크론이 조용히 실패한다.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

from ..schema import SpendRow
from .base import FetchResult, Source, integer, num


API_VERSION = "v21.0"
BASE_URL = f"https://graph.facebook.com/{API_VERSION}"


class MetaAdsSource(Source):
    name = "meta"

    def __init__(self, settings: dict | None = None) -> None:
        super().__init__(settings)
        self.token = self.settings.get("access_token") or os.environ.get("META_ACCESS_TOKEN", "")
        act = str(self.settings.get("ad_account_id") or os.environ.get("META_AD_ACCOUNT_ID", ""))
        self.account_id = act if act.startswith("act_") else (f"act_{act}" if act else "")
        self.store_channel = self.settings.get("store_channel", "own")

    def available(self) -> tuple[bool, str]:
        if not (self.token and self.account_id):
            return False, "자격증명 미설정 (META_ACCESS_TOKEN / META_AD_ACCOUNT_ID)"
        return True, ""

    def fetch(self, date_from: str, date_to: str) -> list[FetchResult]:
        ok, why = self.available()
        if not ok:
            return [FetchResult([], "spend", self.name, ok=False, message=why)]

        params = {
            "access_token": self.token,
            "level": "adset",
            "time_increment": 1,                       # 일자별로 쪼개서 수령
            "breakdowns": "publisher_platform",
            "time_range": json.dumps({"since": date_from, "until": date_to}),
            "fields": ",".join([
                "date_start", "campaign_name", "adset_name",
                "impressions", "clicks", "spend", "actions", "action_values",
            ]),
            "limit": 500,
        }
        url = f"{BASE_URL}/{self.account_id}/insights?{urllib.parse.urlencode(params)}"

        rows: list[SpendRow] = []
        try:
            while url:
                with urllib.request.urlopen(url, timeout=90) as resp:
                    payload = json.loads(resp.read().decode("utf-8"))
                rows.extend(self._parse(payload.get("data", [])))
                url = (payload.get("paging") or {}).get("next")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")[:300]
            return [FetchResult([], "spend", self.name, ok=False,
                                message=f"HTTP {exc.code}: {body}")]
        except Exception as exc:                            # noqa: BLE001
            return [FetchResult([], "spend", self.name, ok=False, message=str(exc))]

        return [FetchResult(rows, "spend", self.name, ok=True)]

    def _parse(self, items: list) -> list[SpendRow]:
        out: list[SpendRow] = []
        for it in items:
            platform = str(it.get("publisher_platform") or "").lower()
            channel = "instagram" if "instagram" in platform else "meta"
            out.append(SpendRow(
                date=str(it.get("date_start", ""))[:10],
                ad_channel=channel,
                store_channel=self.store_channel,
                campaign=str(it.get("campaign_name") or ""),
                adgroup=str(it.get("adset_name") or ""),
                keyword=None,                    # 메타에는 키워드 개념이 없다
                impressions=integer(it.get("impressions")),
                clicks=integer(it.get("clicks")),
                cost=num(it.get("spend")),
                conv_count=_action(it.get("actions"), "purchase"),
                conv_value=_action(it.get("action_values"), "purchase"),
            ))
        return out


def _action(actions, wanted: str) -> float:
    """actions/action_values 배열에서 구매 액션만 뽑는다.

    action_type 은 'purchase', 'omni_purchase',
    'offsite_conversion.fb_pixel_purchase' 등 여러 형태로 온다.
    """
    if not isinstance(actions, list):
        return 0.0
    total = 0.0
    for a in actions:
        if not isinstance(a, dict):
            continue
        at = str(a.get("action_type", ""))
        if at == wanted or at.endswith(f"_{wanted}") or at.endswith(f".fb_pixel_{wanted}"):
            total += num(a.get("value"))
            break            # 중복 집계 방지: 가장 먼저 맞는 것 하나만
    return total
