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
mkdir -p "$WORKSPACE/out"/{plans,scripts,video,desc,reviews}
mkdir -p "$HERMES_HOME/secrets"
chmod 700 "$HERMES_HOME/secrets"

if [ ! -f "$WORKSPACE/channel-brief.yaml" ]; then
  cp "$SRC/content/channel-brief.example.yaml" "$WORKSPACE/channel-brief.yaml"
  echo "    채널 브리프 템플릿 생성: $WORKSPACE/channel-brief.yaml"
else
  echo "    채널 브리프 이미 있음, 건드리지 않음"
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

cat <<EOF

설치 완료. 남은 일은 사람이 해야 합니다:

  1. $HERMES_HOME/config.yaml 에 hermes/config.snippet.yaml 내용을 병합
     (mcp_servers / skills.config / cron 블록. 파일 전체를 덮어쓰지 마세요.)

  2. Higgsfield 인증
       hermes mcp login higgsfield
       hermes tools            # 툴이 등록됐는지 확인

  3. YouTube 인증
       # Google Cloud Console에서 데스크톱 앱 OAuth 클라이언트 JSON을 받아
       # $HERMES_HOME/secrets/youtube_client_secret.json 로 저장한 뒤:
       python $WORKSPACE/scripts/youtube_upload.py auth

  4. 채널 브리프 작성 (가장 중요)
       \$EDITOR $WORKSPACE/channel-brief.yaml

  5. 예약 작업 등록: hermes/cron/jobs.md 참고
EOF
