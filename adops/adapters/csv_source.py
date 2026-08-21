"""CSV/엑셀 내보내기 어댑터.

각 채널 관리자에서 받은 리포트 파일을 data/raw/<프로파일>/ 에 넣어두면
자동으로 인식해 적재한다. API 키가 없어도 오늘 당장 돌릴 수 있는 경로다.

채널마다 컬럼명이 다르고, 같은 채널도 시기에 따라 바뀐다. 그래서 컬럼은
'별칭 목록'으로 매칭한다 — 하나라도 맞으면 잡힌다. 매칭에 실패한 필수
컬럼은 조용히 0으로 두지 않고 명시적으로 경고를 남긴다.
"""

from __future__ import annotations

import csv
import io
import json
import re
from pathlib import Path
from typing import Any, Iterable

from ..schema import (CatalogRow, ProductRow, SalesRow, SearchTermRow,
                      SkuMapRow, SpendRow)
from .base import FetchResult, Source, integer, num


RAW_ROOT = Path(__file__).resolve().parent.parent.parent / "data" / "raw"


# --- 내장 매핑 프로파일 -----------------------------------------------------
# columns 의 값은 '허용하는 컬럼명 별칭'. 실제 파일 헤더와 공백/대소문자를
# 무시하고 비교한다. 채널이 컬럼명을 바꾸면 여기에 별칭만 추가하면 된다.

PROFILES: dict[str, dict[str, Any]] = {
    "naver_sa": {
        "table": "spend",
        "constants": {"ad_channel": "naver_sa", "store_channel": "smartstore"},
        "columns": {
            "date": ["날짜", "일자", "date"],
            "campaign": ["캠페인", "캠페인명", "campaign"],
            "adgroup": ["광고그룹", "광고그룹명", "adgroup"],
            "keyword": ["키워드", "검색키워드", "keyword"],
            "impressions": ["노출수", "노출", "impressions"],
            "clicks": ["클릭수", "클릭", "clicks"],
            "cost": ["광고비", "총비용", "비용", "cost"],
            "conv_count": ["전환수", "직접전환수", "conversions"],
            "conv_value": ["전환매출액", "직접전환매출액", "전환매출", "conv_value"],
        },
    },
    "naver_search_terms": {
        "table": "search_terms",
        "constants": {"ad_channel": "naver_sa"},
        "columns": {
            "date": ["날짜", "일자", "date"],
            "campaign": ["캠페인", "캠페인명"],
            "adgroup": ["광고그룹", "광고그룹명"],
            "keyword": ["키워드", "등록키워드"],
            "search_term": ["검색어", "사용자검색어", "search term", "search_term"],
            "impressions": ["노출수", "노출"],
            "clicks": ["클릭수", "클릭"],
            "cost": ["광고비", "총비용", "비용"],
            "conv_count": ["전환수", "직접전환수"],
            "conv_value": ["전환매출액", "직접전환매출액"],
        },
    },
    "coupang_ads": {
        "table": "spend",
        "constants": {"ad_channel": "coupang_ads", "store_channel": "coupang"},
        "columns": {
            "date": ["날짜", "일자", "date"],
            "campaign": ["캠페인명", "캠페인", "campaign"],
            "adgroup": ["광고그룹", "광고그룹명"],
            "keyword": ["키워드", "검색어", "keyword"],
            "sku": ["상품ID", "옵션ID", "product id", "sku"],
            "impressions": ["노출수", "노출", "impressions"],
            "clicks": ["클릭수", "클릭", "clicks"],
            "cost": ["광고비", "집행광고비", "비용", "spend"],
            "conv_count": ["전환판매수량", "주문수", "판매수", "orders"],
            "conv_value": ["전환매출", "총전환매출", "광고전환매출", "sales"],
        },
    },
    "meta_ads": {
        "table": "spend",
        "constants": {"ad_channel": "meta"},
        "columns": {
            "date": ["일", "날짜", "date", "day", "reporting starts"],
            "campaign": ["캠페인 이름", "캠페인명", "campaign name"],
            "adgroup": ["광고 세트 이름", "광고세트", "ad set name"],
            "impressions": ["노출", "노출수", "impressions"],
            "clicks": ["링크 클릭", "클릭", "clicks", "link clicks"],
            "cost": ["지출 금액", "지출금액", "비용", "amount spent"],
            "conv_count": ["구매", "구매수", "purchases", "결제"],
            "conv_value": ["구매 전환값", "구매전환값", "purchase conversion value"],
            # 지면 구분. instagram 이면 ad_channel 을 instagram 으로 승격시킨다.
            "_platform": ["플랫폼", "게재 위치", "publisher platform", "platform"],
            "_store": ["판매채널", "store channel"],
        },
    },
    "google_ads": {
        "table": "spend",
        "constants": {"ad_channel": "google"},
        "columns": {
            "date": ["일", "날짜", "date", "day"],
            "campaign": ["캠페인", "캠페인명", "campaign"],
            "adgroup": ["광고그룹", "ad group"],
            "keyword": ["키워드", "검색어", "keyword", "search keyword"],
            "match_type": ["일치검색유형", "매치타입", "match type"],
            "impressions": ["노출수", "노출", "impr.", "impressions"],
            "clicks": ["클릭수", "클릭", "clicks"],
            "cost": ["비용", "광고비", "cost"],
            "conv_count": ["전환수", "conversions"],
            "conv_value": ["전환가치", "전환값", "conv. value", "conversion value"],
            "_store": ["판매채널", "store channel"],
        },
    },
    "sales_smartstore": {
        "table": "sales",
        "constants": {"store_channel": "smartstore"},
        "columns": {
            "date": ["결제일", "주문일", "날짜", "일자", "date"],
            "sku": ["상품번호", "옵션코드", "sku"],
            "product_name": ["상품명", "product name"],
            "orders": ["주문건수", "주문수", "orders"],
            "qty": ["수량", "판매수량", "qty"],
            "gross_sales": ["상품금액", "총주문금액", "결제금액", "gross"],
            "discount": ["할인액", "할인금액", "discount"],
            "cancels": ["취소금액", "취소액", "cancels"],
            "returns": ["반품금액", "반품액", "returns"],
        },
    },
    "sales_coupang": {
        "table": "sales",
        "constants": {"store_channel": "coupang"},
        "columns": {
            "date": ["주문일", "결제일", "날짜", "date"],
            "sku": ["옵션ID", "노출상품ID", "sku"],
            "product_name": ["상품명", "등록상품명"],
            "orders": ["주문건수", "주문수"],
            "qty": ["수량", "판매수량"],
            "gross_sales": ["판매금액", "결제금액", "총판매금액"],
            "discount": ["할인액", "할인금액"],
            "cancels": ["취소금액"],
            "returns": ["반품금액"],
        },
    },
    "sales_own": {
        "table": "sales",
        "constants": {"store_channel": "own"},
        "columns": {
            "date": ["결제일", "주문일", "날짜", "date"],
            "sku": ["상품코드", "sku"],
            "product_name": ["상품명"],
            "orders": ["주문건수", "주문수"],
            "qty": ["수량"],
            "gross_sales": ["결제금액", "총결제금액"],
            "discount": ["할인액", "할인금액"],
            "cancels": ["취소금액"],
            "returns": ["반품금액"],
            "new_customer_orders": ["신규주문수", "신규고객주문", "new orders"],
        },
    },
    "products_smartstore": {
        "table": "products",
        "constants": {"channel": "smartstore"},
        "columns": {
            "code": ["상품번호", "옵션ID", "노출상품ID", "상품코드", "옵션코드",
                     "판매자상품코드", "product id", "code", "sku"],
            "name": ["상품명", "등록상품명", "노출상품명", "product name", "name"],
            "price": ["판매가", "정상가", "할인가", "가격", "price"],
        },
    },
    "products_coupang": {
        "table": "products",
        "constants": {"channel": "coupang"},
        "columns": {
            "code": ["상품번호", "옵션ID", "노출상품ID", "상품코드", "옵션코드",
                     "판매자상품코드", "product id", "code", "sku"],
            "name": ["상품명", "등록상품명", "노출상품명", "product name", "name"],
            "price": ["판매가", "정상가", "할인가", "가격", "price"],
        },
    },
    "products_own": {
        "table": "products",
        "constants": {"channel": "own"},
        "columns": {
            "code": ["상품번호", "옵션ID", "노출상품ID", "상품코드", "옵션코드",
                     "판매자상품코드", "product id", "code", "sku"],
            "name": ["상품명", "등록상품명", "노출상품명", "product name", "name"],
            "price": ["판매가", "정상가", "할인가", "가격", "price"],
        },
    },
    "sku_map": {
        "table": "sku_map",
        "constants": {},
        "columns": {
            "channel": ["채널", "판매채널", "channel"],
            "external_id": ["채널상품코드", "상품코드", "상품번호", "옵션ID",
                            "외부코드", "external id", "external_id"],
            "sku": ["통합SKU", "통합sku", "sku", "대표코드"],
            "note": ["비고", "메모", "note"],
        },
    },
    "catalog": {
        "table": "catalog",
        "constants": {},
        "columns": {
            "sku": ["sku", "상품코드", "상품번호", "옵션ID"],
            "product_name": ["상품명", "product name"],
            "price": ["판매가", "정상가", "price"],
            "cogs": ["원가", "매입가", "cogs"],
            "category": ["카테고리", "category"],
            "stock_qty": ["재고", "재고수량", "stock"],
            "active": ["판매상태", "활성", "active"],
        },
    },
}


def _canon(s: str) -> str:
    return re.sub(r"[\s_\-().]", "", str(s or "")).lower()


def _resolve_columns(header: list[str], spec: dict[str, list[str]]) -> dict[str, str]:
    """논리 필드명 → 실제 헤더명 매핑."""
    canon_header = {_canon(h): h for h in header}
    out: dict[str, str] = {}
    for field, aliases in spec.items():
        for alias in aliases:
            hit = canon_header.get(_canon(alias))
            if hit is not None:
                out[field] = hit
                break
    return out


def _read_rows(path: Path) -> tuple[list[str], list[dict]]:
    """CSV/TSV 를 읽는다. BOM·인코딩·구분자를 자동 판별."""
    data = path.read_bytes()
    text = None
    for enc in ("utf-8-sig", "cp949", "euc-kr", "utf-8"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = data.decode("utf-8", errors="replace")

    sample = text[:4096]
    delim = "\t" if sample.count("\t") > sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(text), delimiter=delim)
    rows = [r for r in reader]
    return list(reader.fieldnames or []), rows


_DATE_RE = re.compile(r"(\d{4})[-./]?(\d{2})[-./]?(\d{2})")


def _parse_date(value: str) -> str | None:
    m = _DATE_RE.search(str(value or ""))
    if not m:
        return None
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"


def classify(path: Path) -> list[tuple[str, float, list[str]]]:
    """CSV 헤더를 보고 어느 프로파일 폴더에 속하는지 추정한다.

    폴더가 아홉 개라 사람이 매번 판단하기 번거롭고, 잘못 넣으면 그 채널만
    조용히 빠진 리포트가 나간다. 헤더의 컬럼 별칭이 몇 개나 맞는지로
    점수를 매겨 후보를 순서대로 돌려준다.

    반환: [(프로파일명, 일치율, 인식된 필드 목록), ...] 점수 내림차순
    """
    try:
        header, rows = _read_rows(path)
    except Exception:                                       # noqa: BLE001
        return []
    if not header:
        return []

    scored: list[tuple[str, float, list[str]]] = []
    for name, spec in PROFILES.items():
        colmap = _resolve_columns(header, spec["columns"])
        # 설명용 밑줄 필드(_platform 등)는 판별에 쓰지 않는다.
        hit = [f for f in colmap if not f.startswith("_")]
        want = [f for f in spec["columns"] if not f.startswith("_")]
        if not want:
            continue
        ratio = len(hit) / len(want)
        # 표를 구분하는 결정적 컬럼. 이게 없으면 후보에서 뺀다.
        required = {"spend": "cost", "sales": "gross_sales",
                    "search_terms": "search_term", "catalog": "sku",
                    "sku_map": "external_id", "products": "code"}[spec["table"]]
        if required not in colmap:
            continue
        # 검색어 보고서는 광고 보고서와 컬럼이 거의 겹친다. search_term 유무로 가른다.
        if spec["table"] == "spend" and "search_term" in _resolve_columns(
                header, {"search_term": PROFILES["naver_search_terms"]
                         ["columns"]["search_term"]}):
            ratio *= 0.5
        scored.append((name, ratio, sorted(hit)))

    scored.sort(key=lambda x: -x[1])
    return scored


class CsvSource(Source):
    """data/raw/<profile>/*.csv 를 읽어 정규화 레코드로 변환."""

    name = "csv"

    def __init__(self, settings: dict | None = None) -> None:
        super().__init__(settings)
        self.root = Path(self.settings.get("root") or RAW_ROOT)
        # 사용자 정의 매핑으로 내장 프로파일을 덮어쓸 수 있다.
        self.profiles = dict(PROFILES)
        override = self.settings.get("profiles_file")
        if override and Path(override).exists():
            extra = json.loads(Path(override).read_text(encoding="utf-8"))
            for key, spec in extra.items():
                merged = dict(self.profiles.get(key, {}))
                merged.update(spec)
                self.profiles[key] = merged

    def available(self) -> tuple[bool, str]:
        if not self.root.exists():
            return False, f"원본 폴더 없음: {self.root}"
        return True, ""

    def fetch(self, date_from: str, date_to: str) -> list[FetchResult]:
        results: list[FetchResult] = []
        if not self.root.exists():
            return [FetchResult([], "spend", "csv", ok=False,
                                message=f"원본 폴더 없음: {self.root}")]

        for profile_name, spec in self.profiles.items():
            folder = self.root / profile_name
            if not folder.exists():
                continue
            files = sorted(
                p for p in folder.iterdir()
                if p.suffix.lower() in (".csv", ".tsv", ".txt")
            )
            if not files:
                continue
            results.extend(
                self._load_profile(profile_name, spec, files, date_from, date_to)
            )
        return results

    # -- 내부 -------------------------------------------------------------

    def _load_profile(
        self,
        profile_name: str,
        spec: dict,
        files: list[Path],
        date_from: str,
        date_to: str,
    ) -> list[FetchResult]:
        table = spec["table"]
        consts = spec.get("constants", {})
        rows: list[Any] = []
        warnings: list[str] = []

        for path in files:
            header, raw_rows = _read_rows(path)
            if not raw_rows:
                continue
            colmap = _resolve_columns(header, spec["columns"])

            required = {"spend": ["cost"], "sales": ["gross_sales"],
                        "search_terms": ["search_term"], "catalog": ["sku"],
                        "sku_map": ["external_id", "sku"],
                        "products": ["code", "name"]}[table]
            missing = [c for c in required if c not in colmap]
            if missing:
                warnings.append(
                    f"{path.name}: 필수 컬럼 미인식 {missing} "
                    f"(헤더: {header[:8]}…) — 이 파일은 건너뜁니다"
                )
                continue

            for raw in raw_rows:
                built = self._build_row(
                    table, raw, colmap, consts, date_from, date_to
                )
                if built is not None:
                    rows.append(built)

        return [FetchResult(
            rows=rows,
            table=table,
            source=f"csv:{profile_name}",
            ok=not warnings or bool(rows),
            message=" / ".join(warnings),
        )]

    def _build_row(
        self,
        table: str,
        raw: dict,
        colmap: dict[str, str],
        consts: dict,
        date_from: str,
        date_to: str,
    ):
        def val(field, default=""):
            col = colmap.get(field)
            return raw.get(col, default) if col else default

        if table != "catalog":
            d = _parse_date(val("date"))
            if not d or not (date_from <= d <= date_to):
                return None

        if table == "spend":
            ad_channel = consts.get("ad_channel", "")
            # 메타 리포트에서 인스타그램 지면을 별도 채널로 분리
            platform = _canon(val("_platform"))
            if ad_channel == "meta" and "instagram" in platform:
                ad_channel = "instagram"
            store = _canon(val("_store")) or consts.get("store_channel", "")
            if store not in ("smartstore", "coupang", "own"):
                # 메타/구글은 어느 몰로 보내는지 파일에 없으면 자사몰로 본다.
                store = consts.get("store_channel", "own")
            kw = str(val("keyword") or "").strip() or None
            return SpendRow(
                date=d,
                ad_channel=ad_channel,
                store_channel=store,
                campaign=str(val("campaign") or "").strip(),
                adgroup=str(val("adgroup") or "").strip(),
                keyword=kw,
                match_type=str(val("match_type") or "").strip(),
                impressions=integer(val("impressions")),
                clicks=integer(val("clicks")),
                cost=num(val("cost")),
                conv_count=num(val("conv_count")),
                conv_value=num(val("conv_value")),
                sku=str(val("sku") or "").strip() or None,
            )

        if table == "sales":
            return SalesRow(
                date=d,
                store_channel=consts["store_channel"],
                sku=str(val("sku") or "").strip(),
                product_name=str(val("product_name") or "").strip(),
                orders=integer(val("orders")),
                qty=integer(val("qty")),
                gross_sales=num(val("gross_sales")),
                discount=num(val("discount")),
                cancels=num(val("cancels")),
                returns=num(val("returns")),
                new_customer_orders=integer(val("new_customer_orders")),
            )

        if table == "search_terms":
            term = str(val("search_term") or "").strip()
            if not term:
                return None
            return SearchTermRow(
                date=d,
                ad_channel=consts.get("ad_channel", ""),
                campaign=str(val("campaign") or "").strip(),
                adgroup=str(val("adgroup") or "").strip(),
                keyword=str(val("keyword") or "").strip(),
                search_term=term,
                impressions=integer(val("impressions")),
                clicks=integer(val("clicks")),
                cost=num(val("cost")),
                conv_count=num(val("conv_count")),
                conv_value=num(val("conv_value")),
            )

        if table == "products":
            code = str(val("code") or "").strip()
            if not code:
                return None
            return ProductRow(
                channel=consts["channel"], code=code,
                name=str(val("name") or "").strip(), price=num(val("price")),
            )

        if table == "sku_map":
            ext = str(val("external_id") or "").strip()
            sku = str(val("sku") or "").strip()
            if not ext or not sku:
                return None
            return SkuMapRow(
                channel=str(val("channel") or "*").strip() or "*",
                external_id=ext, sku=sku,
                note=str(val("note") or "").strip(),
            )

        if table == "catalog":
            sku = str(val("sku") or "").strip()
            if not sku:
                return None
            active_raw = _canon(val("active", "1"))
            active = active_raw not in ("0", "false", "n", "no", "판매중지",
                                        "품절", "중지", "비활성")
            stock_col = colmap.get("stock_qty")
            return CatalogRow(
                sku=sku,
                product_name=str(val("product_name") or "").strip(),
                price=num(val("price")),
                cogs=num(val("cogs")),
                category=str(val("category") or "").strip(),
                stock_qty=integer(val("stock_qty")) if stock_col else None,
                active=active,
            )

        return None
