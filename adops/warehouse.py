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

from .schema import CatalogRow, SalesRow, SearchTermRow, SpendRow, to_dict


DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "adops.db"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS spend (
    date TEXT NOT NULL,
    ad_channel TEXT NOT NULL,
    store_channel TEXT NOT NULL,
    campaign TEXT NOT NULL DEFAULT '',
    adgroup TEXT NOT NULL DEFAULT '',
    keyword TEXT,
    match_type TEXT NOT NULL DEFAULT '',
    impressions INTEGER NOT NULL DEFAULT 0,
    clicks INTEGER NOT NULL DEFAULT 0,
    cost REAL NOT NULL DEFAULT 0,
    conv_count REAL NOT NULL DEFAULT 0,
    conv_value REAL NOT NULL DEFAULT 0,
    sku TEXT,
    PRIMARY KEY (date, ad_channel, campaign, adgroup, keyword, match_type)
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


@contextmanager
def connect(db_path: str | Path | None = None) -> Iterator[sqlite3.Connection]:
    path = Path(db_path or DEFAULT_DB)
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA_SQL)
        yield conn
        conn.commit()
    finally:
        conn.close()


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
}

_TABLE_OF = {
    SpendRow: "spend",
    SalesRow: "sales",
    SearchTermRow: "search_terms",
    CatalogRow: "catalog",
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
