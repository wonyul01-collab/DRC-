#!/usr/bin/env bash
# 사용: TYPECAST_API_KEY=... bash tts.sh lines.txt 출력폴더
# lines.txt 한 줄 = 한 장면. 결과: n1.wav.. narration.wav, dur.js(장면 길이)
set -euo pipefail
LINES=$1; OUT=$2; mkdir -p "$OUT"
: "${TYPECAST_API_KEY:?TYPECAST_API_KEY 환경변수가 필요합니다}"
VOICE=${VOICE:-tc_69f2e455ea79fd197aa0476f}   # 서현
N=$(grep -c . "$LINES")
for i in $(seq 1 "$N"); do
  line=$(sed -n "${i}p" "$LINES")
  body=$(python3 -c 'import json,sys;print(json.dumps({"voice_id":sys.argv[1],"text":sys.argv[2],"model":"ssfm-v30","language":"kor","prompt":{"emotion_preset":"normal"},"output":{"audio_format":"wav"}},ensure_ascii=False))' "$VOICE" "$line")
  code=$(curl -s -o "$OUT/raw$i.wav" -w "%{http_code}" -X POST https://api.typecast.ai/v1/text-to-speech \
    -H "X-API-KEY: $TYPECAST_API_KEY" -H "Content-Type: application/json" -d "$body" </dev/null)
  [ "$code" = 200 ] || { echo "n$i 실패 HTTP $code: $(head -c 200 "$OUT/raw$i.wav")"; exit 1; }
  # -nostdin 필수: 빠지면 ffmpeg 가 다음 줄을 읽어가 요청이 깨진다
  ffmpeg -nostdin -y -loglevel error -i "$OUT/raw$i.wav" -ar 24000 -ac 2 "$OUT/n$i.wav"
  echo "n$i $(soxi -D "$OUT/n$i.wav")s"
done
sox -n -r 24000 -c 2 "$OUT/lead.wav" trim 0 0.4
sox -n -r 24000 -c 2 "$OUT/gap.wav" trim 0 0.6
sox -n -r 24000 -c 2 "$OUT/tail.wav" trim 0 2.4
parts=("$OUT/lead.wav"); for i in $(seq 1 "$N"); do parts+=("$OUT/n$i.wav"); [ "$i" -lt "$N" ] && parts+=("$OUT/gap.wav"); done; parts+=("$OUT/tail.wav")
sox "${parts[@]}" "$OUT/narration.wav"
echo "window.DUR=[$(for i in $(seq 1 "$N"); do soxi -D "$OUT/n$i.wav"; done | paste -sd,)];" > "$OUT/dur.js"
echo "총 길이 $(soxi -D "$OUT/narration.wav")s"
