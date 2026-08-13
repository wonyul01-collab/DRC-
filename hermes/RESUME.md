# 다시 시작하기

터미널을 닫았거나 며칠 뒤에 이어서 작업할 때 보는 문서입니다.

## 먼저 — 끄기 전에 확인할 것

터미널을 닫으면 **그 안에서 돌던 프로세스가 죽습니다.** 영상 생성 중이라면
크레딧은 이미 나간 뒤이므로 손해입니다.

끄기 전에:

1. 생성이 돌고 있지 않은지 확인 (화면에 `1 shell still running` 같은 표시가 없어야 함)
2. 돌고 있다면 **job/generation ID 를 기록**하고 끄기.
   생성물은 서버에 남으므로 나중에 `show_generation_by_ids` 로 회수할 수 있습니다
3. 만든 파일은 디스크에 남으니 걱정하지 않아도 됩니다

## 무엇이 남고 무엇이 사라지나

| 남는 것 | 위치 |
|---|---|
| 설정·스킬·워크스페이스 | `%LOCALAPPDATA%\hermes\` |
| 인증 정보 (Higgsfield 토큰, API 키, YouTube OAuth) | `%LOCALAPPDATA%\hermes\secrets\` |
| 기획안·대본·영상 | `%LOCALAPPDATA%\hermes\workspace\youtube\out\` |
| 코드·설정 원본 | 저장소 `C:\Users\User\DRC-` + GitHub |
| 채널 | YouTube (`@몸의속사정`) |
| 작업 기록 | 옵시디언 `클로드 작업\Hermes 유튜브 쇼츠 파이프라인\` |

| 사라지는 것 |
|---|
| 터미널 세션의 대화 맥락 (아래 방법으로 되살릴 수 있음) |
| 실행 중이던 백그라운드 프로세스 |

**인증은 다시 안 해도 됩니다.** Higgsfield 토큰과 YouTube OAuth 는 파일로
저장돼 있어서 재로그인이 필요 없습니다.

## 재개 방법

### 1. 터미널을 열고 저장소로 이동

```powershell
cd C:\Users\User\DRC-
git pull
```

### 2. 이전 대화를 이어서

```powershell
claude --continue          # 가장 최근 세션 이어서
claude --resume            # 목록에서 골라서
```

맥락이 그대로 살아납니다. 대부분 이걸로 충분합니다.

### 3. 새로 시작해야 한다면 — 아래 한 줄을 붙여넣으세요

세션이 너무 오래됐거나 새 창에서 시작할 때, 이 한 줄이면 에이전트가 상황을
파악합니다. **줄바꿈 없이 통째로** 복사하십시오.

```
유튜브 쇼츠 파이프라인 작업을 이어서 한다. 저장소는 C:\Users\User\DRC- 이고 브랜치는 claude/hermes-youtube-monetization-7i8fg5 다. 먼저 git pull 하고 hermes/RESUME.md 와 hermes/README.md 를 읽어라. Hermes 는 %LOCALAPPDATA%\hermes 에 네이티브 설치돼 있고 워크스페이스는 그 아래 workspace\youtube 다. 채널은 @몸의속사정 (UCquJ4vugjON-2t5Clp569fQ) 이고 운영 대상이다. 금지사항: hermes tools 와 hermes mcp configure 는 대화형 피커라 config 를 덮어쓰니 절대 실행하지 마라. search.list 는 1회 100유닛이라 쓰지 마라. API 키를 명령줄에 넣지 마라 — %LOCALAPPDATA%\hermes\secrets\youtube_api_key.txt 에 있다. 업로드는 항상 private 이고 공개는 사람이 한다. 현재 상태를 파악해서 보고하고 다음 할 일을 물어라.
```

## 재개 후 상태 점검

```powershell
# 합성 도구
python "$env:LOCALAPPDATA\hermes\workspace\youtube\scripts\compose_short.py" check --style "$env:LOCALAPPDATA\hermes\workspace\youtube\reference-style.yaml"

# 지금까지 만든 것
dir "$env:LOCALAPPDATA\hermes\workspace\youtube\out\video"
type "$env:LOCALAPPDATA\hermes\workspace\youtube\out\log.jsonl"
```

크레딧 잔량은 Hermes 대화창에서 `balance` 를 물어보면 됩니다.
편당 실제 소모는 `transactions` 로 봅니다.

## 자주 하게 될 일

| 하고 싶은 것 | 명령 |
|---|---|
| 이번 주 기획안 뽑기 | `/yt-trend-research 이번 주 기획안 3개 만들어줘` |
| 영상 한 편 만들기 | `/yt-shorts-factory 1번 기획안으로 만들어줘` |
| 성과 보기 | `/yt-growth-review` |
| 벤치마크 다시 재기 | `python analyze_reference.py --handle "@진짜잠깐만" --calibrate` |

## 잊기 쉬운 것들

- **크레딧은 매달 초기화되고 이월되지 않습니다.** 월말에 남으면 버려집니다
- **YouTube OAuth 동의 화면이 `테스트` 상태면 토큰이 7일마다 만료됩니다.**
  `프로덕션으로 푸시` 해두지 않으면 자동화가 매주 죽습니다
- 업로드는 항상 `private` 로 끝납니다. **공개는 스튜디오에서 사람이 합니다**
- 워크스페이스와 저장소를 따로 고치지 마십시오. 저장소를 고치고 복사하는 방향
  한쪽으로만 가야 어긋나지 않습니다
