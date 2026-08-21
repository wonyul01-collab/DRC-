#!/usr/bin/env bash
#
# Hermes 컨테이너에 adops 를 설치·갱신한다.
#
# 여러 단계를 손으로 하다 보면 한 단계를 빠뜨리기 쉽고, 빠뜨린 단계는
# 대개 크론이 돌 때가 되어서야 드러난다. 전부 한 번에 묶고 멱등하게 만든다.
# 몇 번을 실행해도 결과가 같다.
#
#   bash tools/setup_hermes.sh
#
set -uo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HOME_DIR="${HERMES_HOME:-/opt/data}"
SKILLS_DIR="$HOME_DIR/skills"
FAIL=0

say()  { printf '\n\033[1m%s\033[0m\n' "$*"; }
ok()   { printf '  [OK] %s\n' "$*"; }
warn() { printf '  [!!] %s\n' "$*"; }
bad()  { printf '  [XX] %s\n' "$*"; FAIL=1; }

say "1. 환경 확인"
printf '  저장소      : %s\n' "$REPO"
printf '  HERMES_HOME : %s\n' "$HOME_DIR"
[ -d "$HOME_DIR" ] && ok "데이터 디렉토리 존재" || bad "데이터 디렉토리 없음: $HOME_DIR"

# 스킬을 영속 볼륨에 두지 않으면 컨테이너 재시작 시 사라지고,
# 크론이 '스킬 없음' 으로 조용히 실패한다. 가장 늦게 발견되는 고장이다.
if command -v findmnt >/dev/null 2>&1; then
    if findmnt -no TARGET "$HOME_DIR" >/dev/null 2>&1; then
        ok "$HOME_DIR 는 별도 마운트 (재시작 후 유지됨)"
    else
        warn "$HOME_DIR 가 별도 마운트가 아님 — 재시작 시 사라질 수 있음"
    fi
fi

say "2. 저장소 갱신"
cd "$REPO" || exit 1

# 컨테이너 안에서는 저장소 소유 uid 가 실행 사용자와 달라 git 이 안전장치로
# 거부하는 일이 잦다. 그러면 git pull 이 멈추고, 옛 코드로 돌면서 "없는
# 명령" 오류가 뒤따라 원인이 엉뚱한 곳으로 보인다.
if ! git status >/dev/null 2>&1; then
    git config --global --add safe.directory "$REPO" 2>/dev/null
    if git status >/dev/null 2>&1; then
        ok "safe.directory 등록 (소유권 경고 해소)"
    else
        bad "git 저장소를 읽을 수 없음: $REPO"
    fi
fi
BRANCH="$(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
printf '  현재 브랜치 : %s\n' "$BRANCH"
if git pull --ff-only 2>&1 | sed 's/^/  /'; then
    ok "갱신 완료"
else
    warn "갱신 실패 (오프라인이거나 로컬 변경 있음) — 기존 코드로 진행"
fi

say "3. 설정 파일"
# PyYAML 이 없는 환경에서도 돌아야 하므로 JSON 을 기본으로 둔다.
if [ -f config/config.json ] || [ -f config/config.yaml ]; then
    ok "설정 파일 있음"
else
    cp config/config.example.json config/config.json
    ok "config/config.json 생성 (예시값)"
    warn "채널 수수료율이 예시값입니다. 실제 정산서 기준으로 반드시 교체하세요."
fi

say "4. 스킬 설치"
mkdir -p "$SKILLS_DIR"
for s in ad-daily-report ad-monthly-close; do
    if [ -d "skills/$s" ]; then
        rm -rf "${SKILLS_DIR:?}/$s"
        cp -r "skills/$s" "$SKILLS_DIR/"
        ok "$s → $SKILLS_DIR/$s"
    else
        bad "skills/$s 없음 (브랜치가 맞는지 확인)"
    fi
done

say "5. 동작 점검"
if python3 -m adops doctor 2>&1 | sed 's/^/  /'; then
    ok "doctor 정상"
else
    bad "doctor 실패"
fi

say "6. 메일 설정 확인"
ENVF="$HOME_DIR/.env"
if [ -f "$ENVF" ]; then
    # 값은 절대 출력하지 않는다. 길이만 본다.
    for k in EMAIL_ADDRESS EMAIL_PASSWORD EMAIL_SMTP_HOST EMAIL_HOME_ADDRESS; do
        L="$(awk -F= -v K="^$k=" '$0 ~ K {print length($2); exit}' "$ENVF")"
        if [ -n "$L" ] && [ "$L" -gt 0 ]; then
            ok "$k 설정됨 (길이 $L)"
            # 구글 앱 비밀번호를 공백째 넣으면 셸이 잘라 4자만 저장된다.
            if [ "$k" = "EMAIL_PASSWORD" ] && [ "$L" -lt 8 ]; then
                bad "  → 너무 짧습니다. 공백에서 잘렸을 가능성 (앱 비밀번호는 16자)"
            fi
        else
            warn "$k 미설정"
        fi
    done
else
    warn "$ENVF 없음 — 메일 설정 전"
fi

say "결과"
if [ "$FAIL" -eq 0 ]; then
    cat <<'NEXT'
  설치 완료.

  다음 순서로 진행하세요.
    1) 채팅창에서  /reload-skills
    2) 채팅창에서  /skills          (ad-daily-report 가 보이는지)
    3) 채팅창에서  /ad-daily-report (시험 실행)

  크론 등록 전 확인 (컨테이너는 UTC 로 돕니다):
    매일 08:00 KST  →  "0 23 * * *"
    매월 1일 09:00 KST →  "0 0 1 * *"
NEXT
else
    printf '  실패한 항목이 있습니다. 위 [XX] 표시를 확인하세요.\n'
fi
exit "$FAIL"
