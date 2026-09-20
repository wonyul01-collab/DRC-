"""
앱 아이콘 생성기.

설계 기준
  - 작업표시줄에서는 16픽셀까지 줄어든다. 그 크기에서 '다운로드' 로 읽혀야 한다.
    그래서 요소는 셋뿐이다. 둥근 사각 바탕, 아래 화살표, 받침선.
    글자와 가는 선은 넣지 않는다. 16픽셀에서 뭉개진다.
  - 재생 삼각형을 같이 넣어 봤지만 16픽셀에서 화살표와 엉겨 못 알아본다.
    '영상' 느낌은 도형 대신 따뜻한 색(레드→오렌지)으로 낸다.
  - 모든 모서리의 둥글기를 맞춘다. 화살표 머리만 뾰족하면 투박해 보인다.

4배로 그린 뒤 줄여 가장자리를 매끄럽게 만든다.
"""

import math
from PIL import Image, ImageDraw

S = 1024            # 최종 크기
SS = 4              # 슈퍼샘플링 배율
W = S * SS

TOP = (244, 63, 94)     # 레드
BOT = (249, 115, 22)    # 오렌지
WHITE = (255, 255, 255, 255)
ICO_SIZES = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]


def _gradient(size: int, top, bot) -> Image.Image:
    col = Image.new("RGB", (1, size))
    for y in range(size):
        t = y / max(size - 1, 1)
        col.putpixel((0, y), tuple(round(a + (b - a) * t) for a, b in zip(top, bot)))
    return col.resize((size, size), Image.BICUBIC)


def _plate() -> Image.Image:
    img = _gradient(W, TOP, BOT).convert("RGBA")
    mask = Image.new("L", (W, W), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, W - 1, W - 1], int(W * 0.225), fill=255)
    img.putalpha(mask)
    return img


def _rounded_triangle(d: ImageDraw.ImageDraw, pts, r: int, fill) -> None:
    """무게중심 쪽으로 줄인 삼각형을 채우고 둥근 이음선으로 두른다.

    꼭짓점에 원을 얹는 방식은 뾰족한 끝에서 원이 삐져나와 혹처럼 보인다.
    """
    cx = sum(p[0] for p in pts) / 3.0
    cy = sum(p[1] for p in pts) / 3.0

    dmin = float("inf")
    for i in range(3):
        x1, y1 = pts[i]
        x2, y2 = pts[(i + 1) % 3]
        length = math.hypot(x2 - x1, y2 - y1)
        dist = abs((x2 - x1) * (y1 - cy) - (x1 - cx) * (y2 - y1)) / max(length, 1e-6)
        dmin = min(dmin, dist)

    f = max(0.0, 1.0 - r / max(dmin, 1e-6))
    inner = [(cx + (x - cx) * f, cy + (y - cy) * f) for x, y in pts]
    d.polygon(inner, fill=fill)
    d.line(inner + [inner[0]], fill=fill, width=int(2 * r), joint="curve")


def build() -> Image.Image:
    img = _plate()
    d = ImageDraw.Draw(img)
    cx = W // 2

    stem_w = int(W * 0.125)
    d.rounded_rectangle(
        [cx - stem_w // 2, int(W * 0.23), cx + stem_w // 2, int(W * 0.53)],
        radius=stem_w // 2, fill=WHITE,
    )

    head_w = int(W * 0.345)
    _rounded_triangle(
        d,
        [(cx - head_w // 2, int(W * 0.48)), (cx + head_w // 2, int(W * 0.48)), (cx, int(W * 0.70))],
        int(W * 0.028), WHITE,
    )

    bar_w, bar_h = int(W * 0.44), int(W * 0.082)
    d.rounded_rectangle(
        [cx - bar_w // 2, int(W * 0.76), cx + bar_w // 2, int(W * 0.76) + bar_h],
        radius=bar_h // 2, fill=WHITE,
    )

    return img.resize((S, S), Image.LANCZOS)


if __name__ == "__main__":
    icon = build()
    icon.save("icon.png")
    icon.save("icon.ico", sizes=ICO_SIZES)
    print(f"icon.png ({S}x{S}) / icon.ico ({len(ICO_SIZES)}개 크기) 생성")
