#!/usr/bin/env bash
# 사용: bash rend.sh <real|illus> <작업폴더(index.html·dur.js·a/narration.wav 위치)> <출력.mp4>
set -euo pipefail
MODE=$1; WORK=$2; OUTMP4=$3
export NODE_PATH=$(npm root -g)
rm -rf "$WORK/fr_$MODE"; mkdir -p "$WORK/fr_$MODE"
node "$(dirname "$0")/cap.js" "$MODE" all "$WORK/fr_$MODE" "$WORK/index.html"
ffmpeg -nostdin -y -loglevel error -framerate 30 -i "$WORK/fr_$MODE/%05d.jpg" -i "$WORK/a/narration.wav" \
  -c:v libx264 -preset medium -crf 21 -pix_fmt yuv420p -c:a aac -b:a 192k -shortest -movflags +faststart "$OUTMP4"
ffprobe -v error -show_entries format=duration,size -of default=nw=1 "$OUTMP4"
