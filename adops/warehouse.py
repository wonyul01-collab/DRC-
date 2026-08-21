"""SQLite 기반 데이터 창고.

파일 하나(data/adops.db)로 끝나므로 백업이 쉽고, Hermes 컨테이너 안에서
별도 DB 서버 없이 돈다. 적재는 항상 멱등(idempotent)이다 — 같은 날짜의
같은 채널 데이터를 두 번 넣어도 중복되지 않고 덮어쓴다. 크론이 재시도돼도
숫자가 두 배가 되지 않게 하기 위한 것이다.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator, Sequence

from .schema import (CatalogRow, SalesRow, SearchTermRow, SkuMapRow,
                     SpendRow, to_dict)


DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "adops.db"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS spend (
    date TEXT NOT NULL,
    ad_channel TEXT NOT NULL,
    store_channel TEXT NOT NULL,
    campaign TEXT NOT NULL DEFAULT '',
    adgroup TEXT NOT NULL DEFAULT '',
    -- NULL 을 허용하면 안 된다. SQLite 는 PRIMARY KEY 안의 NULL 을 매번
    -- 서로 다른 값으로 취급해서 INSERT OR REPLACE 가 기존 행을 찾지 못하고,
    -- 키워드 개념이 없는 채널(메타·인스타·구글 일부·쿠팡 상품광고)의
    -- 광고비가 재적재할 때마다 중복 누적된다.
    keyword TEXT NOT NULL DEFAULT '',
    match_type TEXT NOT NULL DEFAULT '',
    impressions INTEGER NOT NULL DEFAULT 0,
    clicks INTEGER NOT NULL DEFAULT 0,
    cost REAL NOT NULL DEFAULT 0,
    conv_count REAL NOT NULL DEFAULT 0,
    conv_value REAL NOT NULL DEFAULT 0,
    -- 상품 단위로 집행되는 광고(쿠팡 상품광고, 구글 쇼핑)는 키워드가 아니라
    -- 상품이 행의 정체성이다. sku 가 키에 없으면 같은 캠페인의 여러 상품이
    -- 서로를 덮어써서 하나만 남는다.
    sku TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (date, ad_channel, campaign, adgroup, keyword, match_type, sku)
);
CREATE INDEX IF NOT EXISTS ix_spend_date ON spend(date);
CREATE INDEX IF NOT EXISTS ix_spend_kw ON spend(keyword);

CREATE TABLE IF NOT EXISTS sales (
    date TEXT NOT NULL,
    store_channel TEXT NOT NULL,
    sku TEXT NOT NULL DEFAULT '',
    product_name TEXT NOT NULL DEFAULT '',
    orders INTEGER NOT NULL DEFAULT 0,
    qty INTEGER NOT NULL DEFAULT 0,
    gross_sales REAL NOT NULL DEFAULT 0,
    discount REAL NOT NULL DEFAULT 0,
    net_sales REAL NOT NULL DEFAULT 0,
    cancels REAL NOT NULL DEFAULT 0,
    returns REAL NOT NULL DEFAULT 0,
    new_customer_orders INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (date, store_channel, sku)
);
CREATE INDEX IF NOT EXISTS ix_sales_date ON sales(date);

CREATE TABLE IF NOT EXISTS search_terms (
    date TEXT NOT NULL,
    ad_channel TEXT NOT NULL,
    campaign TEXT NOT NULL DEFAULT '',
    adgroup TEXT NOT NULL DEFAULT '',
    keyword TEXT NOT NULL DEFAULT '',
    search_term TEXT NOT NULL,
    impressions INTEGER NOT NULL DEFAULT 0,
    clicks INTEGER NOT NULL DEFAULT 0,
    cost REAL NOT NULL DEFAULT 0,
    conv_count REAL NOT NULL DEFAULT 0,
    conv_value REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (date, ad_channel, campaign, adgroup, keyword, search_term)
);
CREATE INDEX IF NOT EXISTS ix_st_date ON search_terms(date);

CREATE TABLE IF NOT EXISTS catalog (
    sku TEXT PRIMARY KEY,
    product_name TEXT NOT NULL DEFAULT '',
    price REAL NOT NULL DEFAULT 0,
    cogs REAL NOT NULL DEFAULT 0,
    category TEXT NOT NULL DEFAULT '',
    stock_qty INTEGER,
    active INTEGER NOT NULL DEFAULT 1
);

-- 채널별 상품코드 → 통합 SKU. 채널마다 코드 체계가 달라서, 이 표가 없으면
-- 한 채널에만 원가가 붙고 나머지는 전부 기본 마진율로 추정된다.
CREATE TABLE IF NOT EXISTS sku_map (
    channel TEXT NOT NULL DEFAULT '*',
    external_id TEXT NOT NULL,
    sku TEXT NOT NULL,
    note TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (channel, external_id)
);
CREATE INDEX IF NOT EXISTS ix_skumap_ext ON sku_map(external_id);

-- 적재 이력. '어제 데이터가 안 들어왔는데 리포트는 정상으로 보이는' 사고를
-- 막기 위해, 리포트는 매번 이 표를 확인해 결손을 먼저 경고한다.
CREATE TABLE IF NOT EXISTS ingest_log (
    ts TEXT NOT NULL,
    source TEXT NOT NULL,
    table_name TEXT NOT NULL,
    date_from TEXT,
    date_to TEXT,
    rows INTEGER NOT NULL DEFAULT 0,
    ok INTEGER NOT NULL DEFAULT 1,
    message TEXT NOT NULL DEFAULT ''
);
"""


def migrate(conn: sqlite3.Connection) -> int:
    """예전 스키마(keyword NULL 허용)로 만들어진 DB를 고친다.

    NULL 키워드 행이 재적재 때마다 중복 누적되어 있으므로, 스키마를 바꾸는
    것만으로는 부족하고 이미 쌓인 중복도 걷어내야 한다. 같은 키의 행이
    여러 개면 가장 나중에 적재된 것(rowid 최대)을 남긴다. 채널이 수치를
    정정해 다시 보낸 경우 최신값이 맞기 때문이다.

    제거한 중복 행 수를 반환한다.
    """
    # sqlite3.Row 에는 .get() 이 없으므로 평범한 dict 로 옮긴다.
    notnull = {c["name"]: bool(c["notnull"])
               for c in conn.execute("PRAGMA table_info(spend)")}
    if not notnull:
        return 0
    # 두 가지를 함께 고친다.
    #  - keyword 가 NULL 을 허용하면 재적재 시 중복이 쌓인다.
    #  - sku 가 키에 없으면 같은 캠페인의 여러 상품이 서로를 덮어쓴다.
    if notnull.get("keyword") and notnull.get("sku"):
        return 0                      # 이미 새 스키마

    before = conn.execute("SELECT COUNT(*) n FROM spend").fetchone()["n"]
    conn.executescript("""
        CREATE TABLE spend_migrated (
            date TEXT NOT NULL, ad_channel TEXT NOT NULL,
            store_channel TEXT NOT NULL, campaign TEXT NOT NULL DEFAULT '',
            adgroup TEXT NOT NULL DEFAULT '', keyword TEXT NOT NULL DEFAULT '',
            match_type TEXT NOT NULL DEFAULT '',
            impressions INTEGER NOT NULL DEFAULT 0,
            clicks INTEGER NOT NULL DEFAULT 0, cost REAL NOT NULL DEFAULT 0,
            conv_count REAL NOT NULL DEFAULT 0, conv_value REAL NOT NULL DEFAULT 0,
            sku TEXT NOT NULL DEFAULT '',
            PRIMARY KEY (date, ad_channel, campaign, adgroup, keyword, match_type, sku)
        );
        INSERT INTO spend_migrated
        SELECT date, ad_channel, store_channel, campaign, adgroup,
               COALESCE(keyword, ''), match_type, impressions, clicks, cost,
               conv_count, conv_value, COALESCE(sku, '')
          FROM spend
         WHERE rowid IN (
               SELECT MAX(rowid) FROM spend
                GROUP BY date, ad_channel, campaign, adgroup,
                         COALESCE(keyword, ''), match_type, COALESCE(sku, ''));
        DROP TABLE spend;
        ALTER TABLE spend_migrated RENAME TO spend;
        CREATE INDEX IF NOT EXISTS ix_spend_date ON spend(date);
        CREATE INDEX IF NOT EXISTS ix_spend_kw ON spend(keyword);
    """)
    after = conn.execute("SELECT COUNT(*) n FROM spend").fetchone()["n"]
    return before - after


@contextmanager
def connect(db_path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    path = Path(db_path or DEFAULT_DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA_SQL)
        register_sku_map(conn)
        removed = migrate(conn)
        if removed:
            import sys
            print(f"[migrate] 중복 광고비 행 {removed:,}개 제거 "
                  f"(키워드 없는 채널의 재적재 중복)", file=sys.stderr)
        yield conn
        conn.commit()
    finally:
        conn.close()


def register_sku_map(conn: sqlite3.Connection) -> int:
    """canon_sku(채널, 원본코드) SQL 함수를 등록한다.

    적재 시점이 아니라 조회 시점에 해석한다. 나중에 매핑을 추가하면
    과거 데이터에도 즉시 적용되고, 원본 코드는 그대로 보존된다.
    다시 내려받아 재적재할 필요가 없다.

    등록된 매핑 수를 반환한다.
    """
    mapping: dict[tuple[str, str], str] = {}
    try:
        rows = conn.execute("SELECT channel, external_id, sku FROM sku_map")
    except sqlite3.OperationalError:
        rows = []
    for r in rows:
        mapping[(r["channel"], r["external_id"])] = r["sku"]

    def canon(channel, raw):
        if not raw:
            return ""
        raw = str(raw).strip()
        # 채널 지정 매핑이 우선, 없으면 전채널(*) 매핑, 그것도 없으면 원본 그대로.
        return (mapping.get((str(channel or ""), raw))
                or mapping.get(("*", raw))
                or raw)

    conn.create_function("canon_sku", 2, canon)
    return len(mapping)


_UPSERT = {
    "spend": (
        "INSERT OR REPLACE INTO spend (date,ad_channel,store_channel,campaign,"
        "adgroup,keyword,match_type,impressions,clicks,cost,conv_count,"
        "conv_value,sku) VALUES (:date,:ad_channel,:store_channel,:campaign,"
        ":adgroup,:keyword,:match_type,:impressions,:clicks,:cost,:conv_count,"
        ":conv_value,:sku)"
    ),
    "sales": (
        "INSERT OR REPLACE INTO sales (date,store_channel,sku,product_name,"
        "orders,qty,gross_sales,discount,net_sales,cancels,returns,"
        "new_customer_orders) VALUES (:date,:store_channel,:sku,:product_name,"
        ":orders,:qty,:gross_sales,:discount,:net_sales,:cancels,:returns,"
        ":new_customer_orders)"
    ),
    "search_terms": (
        "INSERT OR REPLACE INTO search_terms (date,ad_channel,campaign,adgroup,"
        "keyword,search_term,impressions,clicks,cost,conv_count,conv_value) "
        "VALUES (:date,:ad_channel,:campaign,:adgroup,:keyword,:search_term,"
        ":impressions,:clicks,:cost,:conv_count,:conv_value)"
    ),
    "catalog": (
        "INSERT OR REPLACE INTO catalog (sku,product_name,price,cogs,category,"
        "stock_qty,active) VALUES (:sku,:product_name,:price,:cogs,:category,"
        ":stock_qty,:active)"
    ),
    "sku_map": (
        "INSERT OR REPLACE INTO sku_map (channel,external_id,sku,note) "
        "VALUES (:channel,:external_id,:sku,:note)"
    ),
}

_TABLE_OF = {
    SpendRow: "spend",
    SalesRow: "sales",
    SearchTermRow: "search_terms",
    CatalogRow: "catalog",
    SkuMapRow: "sku_map",
}


def upsert(conn: sqlite3.Connection, rows: Sequence) -> int:
    """레코드 타입을 보고 알아서 해당 표에 멱등 적재."""
    if not rows:
        return 0
    table = _TABLE_OF[type(rows[0])]
    payload = []
    for r in rows:
        d = to_dict(r)
        if table == "catalog":
            d["active"] = 1 if d.get("active", True) else 0
        elif table == "spend":
            # PRIMARY KEY 안의 NULL 은 매번 다른 값으로 취급되어 멱등성이
            # 깨진다. 어댑터가 무엇을 주든 여기서 빈 문자열로 통일한다.
            if d.get("keyword") is None:
                d["keyword"] = ""
            if d.get("sku") is None:
                d["sku"] = ""
        payload.append(d)
    conn.executemany(_UPSERT[table], payload)
    return len(payload)


def log_ingest(
    conn: sqlite3.Connection,
    *,
    ts: str,
    source: str,
    table_name: str,
    date_from: str | None,
    date_to: str | None,
    rows: int,
    ok: bool = True,
    message: str = "",
) -> None:
    conn.execute(
        "INSERT INTO ingest_log (ts,source,table_name,date_from,date_to,rows,"
        "ok,message) VALUES (?,?,?,?,?,?,?,?)",
        (ts, source, table_name, date_from, date_to, rows, 1 if ok else 0, message),
    )


def query(conn: sqlite3.Connection, sql: str, params: Iterable = ()) -> list[sqlite3.Row]:
    return list(conn.execute(sql, tuple(params)))


def covered_dates(conn: sqlite3.Connection, table: str, channel_col: str) -> dict[str, set[str]]:
    """채널별로 데이터가 존재하는 날짜 집합. 결손 탐지에 쓴다."""
    out: dict[str, set[str]] = {}
    for row in conn.execute(f"SELECT DISTINCT {channel_col} AS ch, date FROM {table}"):
        out.setdefault(row["ch"], set()).add(row["date"])
    return out
