"""설정 로더.

config.yaml 을 우선 읽고, PyYAML 이 없는 환경(예: 슬림 컨테이너)에서는
같은 이름의 config.json 으로 자동 폴백한다. 의존성 때문에 크론이
죽는 상황을 만들지 않기 위한 장치다.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict


DEFAULTS: Dict[str, Any] = {
    # 판매채널별 수수료율(플랫폼 수수료 + 결제수수료 합산, 소수)
    "channel_fees": {
        "smartstore": 0.0585,
        "coupang": 0.108,
        "own": 0.033,
    },
    # 원가를 모르는 SKU에 적용할 기본 매출총이익률.
    # 실제 원가가 catalog 에 있으면 그쪽이 항상 우선한다.
    "default_gross_margin_rate": 0.45,

    # 낭비 키워드 판정 임계값
    "waste_rules": {
        "lookback_days": 30,
        "min_clicks": 20,          # 이보다 적으면 표본 부족 → 판정 보류
        "min_cost": 30000,         # 이보다 적게 쓴 키워드는 노이즈 → 제외
        "high_cpc_multiple": 1.8,  # 채널 중앙 CPC 대비 배수
        "low_cvr_ratio": 0.5,      # 채널 중앙 CVR 대비 비율
    },

    # 리포트 표시 옵션
    "report": {
        "top_keywords": 15,
        "trend_top_keywords": 8,
        "currency": "KRW",
        "timezone": "Asia/Seoul",
    },

    # 브랜드 키워드(자연검색 상위 노출 중이라 광고 잠식 의심 대상)
    "brand_keywords": [],

    # 월 목표 (월마감 분석에서 달성률 계산에 사용)
    "targets": {},

    # 경쟁사 (월마감 상세분석 대상)
    "competitors": [],
}


@dataclass(slots=True)
class Config:
    raw: Dict[str, Any] = field(default_factory=dict)
    path: Path | None = None

    def get(self, dotted: str, default: Any = None) -> Any:
        """'waste_rules.min_cost' 같은 점 표기로 조회."""
        node: Any = self.raw
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    # --- 자주 쓰는 파생값 -------------------------------------------------

    def fee_rate(self, store_channel: str) -> float:
        return float(self.get(f"channel_fees.{store_channel}", 0.0))

    def contribution_margin_rate(
        self, store_channel: str, gross_margin_rate: float | None = None
    ) -> float:
        """공헌이익률 = 매출총이익률 - 채널수수료율.

        광고비를 태우기 전에 1원의 매출이 남기는 비율. 손익분기 ROAS의 분모.
        """
        gm = (
            gross_margin_rate
            if gross_margin_rate is not None
            else float(self.get("default_gross_margin_rate", 0.45))
        )
        return gm - self.fee_rate(store_channel)

    def bep_roas(
        self, store_channel: str, gross_margin_rate: float | None = None
    ) -> float | None:
        """손익분기 ROAS.

        공헌이익 = 매출*공헌이익률 - 광고비 = 0  →  매출/광고비 = 1/공헌이익률

        이 값보다 낮은 ROAS는 팔수록 손해다. '목표 ROAS 300%' 같은
        관행적 숫자 대신 이 계산값을 기준선으로 쓴다.
        """
        cmr = self.contribution_margin_rate(store_channel, gross_margin_rate)
        if cmr <= 0:
            return None  # 수수료가 마진을 넘어섬 = 광고 이전에 상품 구조 문제
        return 1.0 / cmr


def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load(path: str | os.PathLike | None = None) -> Config:
    """설정 로드. 파일이 없으면 기본값만으로 동작한다."""
    candidates = []
    if path:
        candidates.append(Path(path))
    else:
        env = os.environ.get("ADOPS_CONFIG")
        if env:
            candidates.append(Path(env))
        root = Path(__file__).resolve().parent.parent
        candidates += [
            root / "config" / "config.yaml",
            root / "config" / "config.json",
        ]

    for cand in candidates:
        if not cand.exists():
            continue
        text = cand.read_text(encoding="utf-8")
        if cand.suffix in (".yaml", ".yml"):
            try:
                import yaml  # type: ignore
            except ImportError:
                # YAML 파서가 없으면 같은 이름의 json 을 찾아본다.
                alt = cand.with_suffix(".json")
                if alt.exists():
                    return Config(_deep_merge(DEFAULTS, json.loads(
                        alt.read_text(encoding="utf-8"))), alt)
                raise RuntimeError(
                    f"{cand} 를 읽으려면 PyYAML 이 필요합니다. "
                    f"'pip install pyyaml' 하거나 {alt.name} 로 변환하세요."
                )
            data = yaml.safe_load(text) or {}
        else:
            data = json.loads(text)
        return Config(_deep_merge(DEFAULTS, data), cand)

    return Config(dict(DEFAULTS), None)
