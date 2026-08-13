#!/usr/bin/env bash
# Hermes 유튜브 파이프라인 설치 스크립트
#
#   bash hermes/install.sh
#
# config.yaml 은 자동으로 건드리지 않습니다. 기존 설정을 깨뜨릴 수 있어서
# 병합은 사람이 직접 합니다. 이 스크립트는 스킬·스크립트·작업폴더만 배치합니다.

set -euo pipefail

HERMES_HOME="${HERMES_HOME:-$HOME/.hermes}"
WORKSPACE="$HERMES_HOME/workspace/youtube"
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ ! -d "$HERMES_HOME" ]; then
  echo "오류: $HERMES_HOME 가 없습니다. Hermes 가 설치되어 있는지 확인하세요." >&2
  echo "설치: curl -fsSL https://raw.githubusercontent.com/NousResearch/hermes-agent/main/scripts/install.sh | bash" >&2
  exit 1
fi

echo "==> 스킬 설치: $HERMES_HOME/skills/"
mkdir -p "$HERMES_HOME/skills"
for skill in "$SRC"/skills/*/; do
  name="$(basename "$skill")"
  target="$HERMES_HOME/skills/$name"
  if [ -e "$target" ]; then
    echo "    이미 있음, 덮어씀: $name (기존 파일은 $name.bak 로 백업)"
    mv "$target" "$target.bak"
  fi
  cp -r "$skill" "$target"
  echo "    설치됨: $name"
done

echo "==> 스크립트 설치: $WORKSPACE/scripts/"
mkdir -p "$WORKSPACE/scripts"
cp "$SRC"/scripts/*.py "$SRC"/scripts/requirements.txt "$WORKSPACE/scripts/"

echo "==> 작업 폴더 생성"
mkdir -p "$WORKSPACE/out"/{plans,scripts,video/raw,desc,reviews}
mkdir -p "$HERMES_HOME/secrets"
chmod 700 "$HERMES_HOME/secrets"

# 채널 브리프. BRIEF 환경변수로 준비된 초안을 고를 수 있습니다.
#   BRIEF=health-simulation bash install.sh
# 지정 안 하면 빈 템플릿이 깔립니다.
if [ ! -f "$WORKSPACE/channel-brief.yaml" ]; then
  if [ -n "${BRIEF:-}" ] && [ -f "$SRC/content/briefs/$BRIEF.yaml" ]; then
    cp "$SRC/content/briefs/$BRIEF.yaml" "$WORKSPACE/channel-brief.yaml"
    echo "    브리프 적용: $BRIEF → $WORKSPACE/channel-brief.yaml"
  else
    cp "$SRC/content/channel-brief.example.yaml" "$WORKSPACE/channel-brief.yaml"
    echo "    빈 템플릿 생성: $WORKSPACE/channel-brief.yaml"
  fi
else
  echo "    이미 있음, 건드리지 않음: channel-brief.yaml"
fi

# 벤치마크 스타일. STYLE 환경변수로 다른 채널 스타일을 고를 수 있습니다.
#   STYLE=other-channel bash install.sh
STYLE="${STYLE:-jinjja-jamkkanman}"
if [ ! -f "$WORKSPACE/reference-style.yaml" ]; then
  if [ -f "$SRC/content/styles/$STYLE.yaml" ]; then
    cp "$SRC/content/styles/$STYLE.yaml" "$WORKSPACE/reference-style.yaml"
    echo "    스타일 적용: $STYLE → $WORKSPACE/reference-style.yaml"
  else
    cp "$SRC/content/reference-style.example.yaml" "$WORKSPACE/reference-style.yaml"
    echo "    빈 템플릿 생성 ($STYLE 없음): $WORKSPACE/reference-style.yaml"
  fi
else
  echo "    이미 있음, 건드리지 않음: reference-style.yaml"
fi

echo "==> Python 의존성 설치"
# 실패해도 설치를 중단하지 않습니다. 아래 안내는 여전히 유효하고,
# 파이썬 환경은 사용자마다 달라서 수동 설치가 필요할 수 있습니다.
install_deps() {
  if command -v uv >/dev/null 2>&1; then
    uv pip install --system -r "$WORKSPACE/scripts/requirements.txt" 2>/dev/null && return 0
  fi
  pip install -r "$WORKSPACE/scripts/requirements.txt"
}
if ! install_deps; then
  echo "    경고: 자동 설치 실패. 직접 실행하세요:" >&2
  echo "      pip install -r $WORKSPACE/scripts/requirements.txt" >&2
fi

echo "==> 영상 합성 도구 확인"
if command -v ffmpeg >/dev/null 2>&1; then
  echo "    ffmpeg OK"
else
  echo "    경고: ffmpeg 가 없습니다. 자막·나레이션 합성이 안 됩니다." >&2
  echo "      Ubuntu/WSL: sudo apt install ffmpeg" >&2
  echo "      macOS:      brew install ffmpeg" >&2
fi
if fc-list :lang=ko 2>/dev/null | grep -qi -e "noto sans" -e pretendard -e nanum; then
  echo "    한글 폰트 OK"
else
  echo "    경고: 자막용 한글 폰트가 안 보입니다. 자막이 네모로 깨질 수 있습니다." >&2
  echo "      Ubuntu/WSL: sudo apt install fonts-noto-cjk" >&2
  echo "      설치 후 확인: fc-list :lang=ko family | sort -u" >&2
fi

cat <<EOF

설치 완료. 남은 일은 사람이 해야 합니다:

  1. $HERMES_HOME/config.yaml 에 hermes/config.snippet.yaml 내용을 병합
     (mcp_servers / skills.config / cron 블록. 파일 전체를 덮어쓰지 마세요.)

  2. Higgsfield 인증
       hermes mcp login higgsfield
       # "Authenticated - N tool(s) available" 이 뜨면 성공입니다.
       # ⚠ hermes tools / hermes mcp configure 로 확인하려 하지 마세요.
       #   조회 명령이 아니라 대화형 선택 UI 라서 config.yaml 이 덮어써집니다.

  3. YouTube 인증
       # Google Cloud Console에서 데스크톱 앱 OAuth 클라이언트 JSON을 받아
       # $HERMES_HOME/secrets/youtube_client_secret.json 로 저장한 뒤:
       python $WORKSPACE/scripts/youtube_upload.py auth

  4. 채널 브리프 작성
       \$EDITOR $WORKSPACE/channel-brief.yaml

  5. 벤치마크 채널 문법 심기 (가장 중요)
       hermes
       > /yt-style-extract <분석 노트가 있는 경로> 를 읽고 스타일 파일을 채워줘

  6. 합성 도구 점검
       python $WORKSPACE/scripts/compose_short.py check \\
         --style $WORKSPACE/reference-style.yaml

  7. 예약 작업 등록: hermes/cron/jobs.md 참고
EOF
