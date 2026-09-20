"""
화면 디자인 값 모음.

색과 여백을 여기 한 곳에 모아 둔다. 화면 코드에 색을 직접 박아 넣으면
나중에 손볼 때 빠뜨리는 곳이 생긴다.

customtkinter 는 (밝은색, 어두운색) 짝으로 받는다. 시스템 설정을 따라간다.
"""

# 강조색 — 아이콘과 같은 계열로 맞춘다
ACCENT       = ("#F43F5E", "#F43F5E")
ACCENT_HOVER = ("#E11D48", "#E11D48")

# 바탕
BG        = ("#F7F7F9", "#1A1A1E")
CARD      = ("#FFFFFF", "#242429")
CARD_EDGE = ("#E8E8ED", "#323238")

# 글자
TEXT     = ("#18181B", "#F4F4F5")
TEXT_SUB = ("#71717A", "#A1A1AA")

# 상태
OK    = ("#059669", "#34D399")
WARN  = ("#D97706", "#FBBF24")
ERROR = ("#DC2626", "#F87171")

# 기록창 (항상 어두운 바탕 — 터미널처럼 보이는 편이 읽기 좋다)
LOG_BG = "#16161A"
LOG_FG = "#D4D4D8"
LOG_COLORS = {
    "ok":   "#34D399",
    "bad":  "#F87171",
    "warn": "#FBBF24",
    "info": "#818CF8",
    "dim":  "#71717A",
    "head": "#F43F5E",
}

# 여백
PAD   = 20      # 바깥 여백
GAP   = 14      # 카드 사이
INNER = 16      # 카드 안쪽

RADIUS = 12

# 글꼴 — 윈도우에 기본으로 있는 것만 쓴다
FONT_UI   = "맑은 고딕"
FONT_MONO = "Consolas"
