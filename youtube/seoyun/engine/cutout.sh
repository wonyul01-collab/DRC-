#!/usr/bin/env bash
# 공식몰 흰 배경 제품 사진 → 투명 컷아웃. 사용: bash cutout.sh 입력.png 출력.png [자를폭]
# 자를폭: 오른쪽 배지(어워드 등)를 잘라낼 때 사용 (예: 780)
set -euo pipefail
IN=$1; OUT=$2; W=${3:-}
read -r w h < <(identify -format "%w %h" "$IN")
[ -n "$W" ] && { convert "$IN" -crop "${W}x${h}+0+0" +repage /tmp/_c.png; IN=/tmp/_c.png; w=$W; }
convert "$IN" -alpha set -fuzz 2% -fill none \
  -floodfill +0+0 white -floodfill +$((w-1))+0 white -floodfill +0+$((h-1)) white -floodfill +$((w-1))+$((h-1)) white \
  -trim +repage "$OUT"
