"""채널별 상품 목록을 상품명으로 대조해 통합 SKU 매핑을 만든다.

채널마다 상품코드 체계가 달라 매핑표가 필요한데, 상품이 수백 개면 사람이
일일이 짝지을 수 없다. 상품명은 대체로 비슷하므로 그것으로 후보를 찾는다.

다만 이름이 비슷하다고 무조건 묶으면 안 된다. '콜라겐 30포'와 '콜라겐
60포'는 이름이 90% 넘게 같지만 **다른 상품**이고, 잘못 묶으면 원가가
통째로 틀어져 수익성 판정이 어긋난다. 그래서 수량·용량 토큰이 다르면
아무리 이름이 닮아도 짝짓지 않는다.

확신이 낮은 짝은 자동 확정하지 않고 사람이 볼 목록으로 넘긴다.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Iterable


# 상품명에 흔히 붙는 판촉 문구. 상품을 구분하는 정보가 아니라 잡음이다.
NOISE = [
    "무료배송", "당일발송", "당일출고", "오늘출발", "정품", "본사직영",
    "공식", "인증", "국내산", "특가", "할인", "이벤트", "사은품", "증정",
    "선물포장", "최저가", "베스트", "신상", "리뉴얼", "묶음", "단독",
    "빠른배송", "로켓배송", "무료", "행사", "기획전", "추천",
]
NOISE_RE = re.compile("|".join(map(re.escape, NOISE)))

# 수량·용량. 이게 다르면 다른 상품이다.
QTY_RE = re.compile(
    r"(\d+(?:\.\d+)?)\s*(포|정|캡슐|캡술|ml|mL|ML|g|kg|G|KG|개|매|팩|박스|세트|병|스틱|일분|개월)"
)


def normalize(name: str) -> str:
    """비교용 이름. 괄호·판촉문구·기호를 걷어낸다."""
    s = str(name or "")
    s = re.sub(r"\[[^\]]*\]", " ", s)      # [대괄호]
    s = re.sub(r"\([^)]*\)", " ", s)       # (괄호)
    s = NOISE_RE.sub(" ", s)
    s = re.sub(r"[^0-9A-Za-z가-힣]+", "", s)
    return s.lower()


def qty_signature(name: str) -> frozenset:
    """수량·용량 토큰 집합. '30포' 와 '60포' 를 가르는 기준."""
    out = set()
    for num, unit in QTY_RE.findall(str(name or "")):
        n = float(num)
        # 30 과 30.0 을 같게, 단위는 대소문자 통일
        out.add((n, unit.lower().replace("캡술", "캡슐")))
    return frozenset(out)


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


@dataclass(slots=True)
class Item:
    channel: str
    code: str
    name: str
    price: float = 0.0

    @property
    def norm(self) -> str:
        return normalize(self.name)

    @property
    def qty(self) -> frozenset:
        return qty_signature(self.name)


@dataclass(slots=True)
class Pair:
    left: Item
    right: Item
    score: float
    reason: str

    @property
    def confident(self) -> bool:
        return self.score >= 0.85


def collect_items(conn: sqlite3.Connection) -> list[Item]:
    """상품 목록 표와 매출 데이터에서 (채널, 코드, 이름, 가격)을 모은다.

    별도로 올린 상품 목록이 있으면 그쪽을 쓰고, 없으면 매출 데이터에 남은
    상품명으로도 대조할 수 있다. 매출이 없는 신상품은 상품 목록에만 있다.
    """
    seen: dict[tuple[str, str], Item] = {}

    try:
        rows = conn.execute(
            "SELECT channel, code, name, price FROM products WHERE code != ''")
    except sqlite3.OperationalError:
        rows = []
    for r in rows:
        key = (r["channel"], str(r["code"]))
        seen[key] = Item(r["channel"], str(r["code"]), r["name"] or "",
                         float(r["price"] or 0))

    for r in conn.execute(
        "SELECT store_channel ch, sku, MAX(product_name) nm, "
        "       CASE WHEN SUM(qty) > 0 THEN SUM(net_sales)/SUM(qty) ELSE 0 END px "
        "FROM sales WHERE sku != '' GROUP BY 1,2"
    ):
        key = (r["ch"], str(r["sku"]))
        if key in seen and seen[key].name:
            continue
        if not (r["nm"] or "").strip():
            continue
        seen[key] = Item(r["ch"], str(r["sku"]), r["nm"], float(r["px"] or 0))

    return list(seen.values())


def score_pair(a: Item, b: Item, price_tolerance: float = 0.25) -> tuple[float, str]:
    """두 상품이 같은 것일 가능성과 그 근거."""
    if a.channel == b.channel:
        return 0.0, "같은 채널"

    # 수량·용량이 다르면 다른 상품이다. 이름이 아무리 닮아도 짝짓지 않는다.
    if a.qty and b.qty and a.qty != b.qty:
        return 0.0, f"수량 불일치 {sorted(a.qty)} vs {sorted(b.qty)}"

    base = similarity(a.norm, b.norm)
    reason = f"이름 유사도 {base*100:.0f}%"

    if a.qty and b.qty and a.qty == b.qty:
        base = min(base + 0.05, 1.0)
        reason += ", 수량 일치"

    # 가격이 크게 다르면 다른 상품일 가능성이 높다. 채널마다 가격이 조금씩
    # 다른 것은 정상이므로 관대하게 본다.
    if a.price > 0 and b.price > 0:
        gap = abs(a.price - b.price) / max(a.price, b.price)
        if gap <= price_tolerance:
            base = min(base + 0.05, 1.0)
            reason += f", 가격 근접({gap*100:.0f}% 차)"
        elif gap > 0.5:
            base *= 0.7
            reason += f", 가격 차 큼({gap*100:.0f}%)"

    return base, reason


def build_groups(
    items: Iterable[Item], *, threshold: float = 0.72
) -> tuple[list[list[Item]], list[Pair]]:
    """상품을 채널 교차로 묶는다.

    반환: (확정 그룹 목록, 검토가 필요한 짝 목록)
    """
    items = [i for i in items if i.norm]
    pairs: list[Pair] = []
    for i, a in enumerate(items):
        for b in items[i + 1:]:
            sc, why = score_pair(a, b)
            if sc >= threshold:
                pairs.append(Pair(a, b, sc, why))

    pairs.sort(key=lambda p: -p.score)

    # 확신 있는 짝만으로 유니온-파인드. 애매한 짝으로 묶으면 서로 다른
    # 상품이 한 덩어리로 번지므로 확정 짝만 병합에 쓴다.
    parent: dict[tuple[str, str], tuple[str, str]] = {}

    def find(k):
        parent.setdefault(k, k)
        while parent[k] != k:
            parent[k] = parent[parent[k]]
            k = parent[k]
        return k

    def union(x, y):
        rx, ry = find(x), find(y)
        if rx != ry:
            parent[rx] = ry

    key = lambda it: (it.channel, it.code)          # noqa: E731
    for it in items:
        find(key(it))
    for p in pairs:
        if p.confident:
            union(key(p.left), key(p.right))

    groups: dict[tuple, list[Item]] = {}
    for it in items:
        groups.setdefault(find(key(it)), []).append(it)

    review = [p for p in pairs if not p.confident]
    return list(groups.values()), review


def assign_sku(
    group: list[Item],
    catalog: dict[str, Item],
    counter: list[int],
    *,
    threshold: float = 0.72,
) -> tuple[str, str]:
    """그룹의 통합 SKU 를 정한다.

    이미 카탈로그에 있는 상품이면 그 SKU 를 재사용해야 한다. 새 번호를
    붙이면 이미 입력해 둔 원가가 연결되지 않고 버려진다.

    1) 그룹의 코드가 카탈로그 SKU 와 그대로 일치하면 그것
    2) 아니면 카탈로그 상품명과 대조해 가장 닮은 것 (수량 일치 필수)
    3) 그래도 없으면 새 번호

    반환: (SKU, 근거)
    """
    for it in group:
        if it.code in catalog:
            return it.code, "카탈로그 코드 일치"

    best, best_score = None, 0.0
    for sku, cat in catalog.items():
        for it in group:
            # 수량이 다르면 다른 상품이다. 이름이 닮아도 붙이지 않는다.
            if it.qty and cat.qty and it.qty != cat.qty:
                continue
            sc = similarity(it.norm, cat.norm)
            if sc > best_score:
                best, best_score = sku, sc
    if best and best_score >= threshold:
        return best, f"카탈로그 상품명 유사 {best_score*100:.0f}%"

    counter[0] += 1
    return f"SKU-{counter[0]:04d}", "신규 부여"
