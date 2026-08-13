# Hermes 예약 작업 등록

아래 명령을 터미널에서 한 번씩 실행하면 등록됩니다.
Hermes 대화창 안에서는 `hermes` 를 떼고 `/cron add ...` 형태로 쓰면 됩니다.

`--deliver` 는 결과를 받을 곳입니다. Telegram 을 안 쓰면 `local` 로 바꾸세요
(결과가 `~/.hermes/cron/output/` 에 파일로 쌓입니다).

## 처음엔 이것 하나만 등록하세요

자동 생성부터 켜지 마세요. 채널 방향이 잡히기 전에 크레딧만 태웁니다.
먼저 리서치 잡만 돌려보고, 나온 기획안 품질이 쓸 만해지면 제작 잡을 켭니다.

```bash
# 매주 월요일 오전 9시 — 이번 주 기획안 5개
hermes cron create "0 9 * * 1" \
  "채널 브리프를 읽고 이번 주에 만들 쇼츠 기획안 5개를 만들어라. 각 기획안에 수요 근거 URL을 붙여라." \
  --name "yt-weekly-plans" \
  --skill yt-trend-research \
  --deliver telegram
```

## 방향이 잡힌 뒤 추가

```bash
# 평일 오전 10시 — 기획안 1개를 실제 영상으로 제작 후 비공개 업로드
# 하루 1편. daily_video_cap 이 추가 안전장치로 걸려 있습니다.
hermes cron create "0 10 * * 1-5" \
  "오늘자 기획안 중 아직 제작하지 않은 것 1개를 골라 쇼츠를 제작하고 비공개로 업로드하라. 완료 후 studio_url 을 보고하라." \
  --name "yt-daily-produce" \
  --skill yt-shorts-factory \
  --deliver telegram

# 매주 월요일 오전 8시 — 지난주 성과 리뷰 (기획 잡보다 먼저 돌려야 결과가 반영됩니다)
hermes cron create "0 8 * * 1" \
  "지난 28일 유튜브 성과를 분석하고, 다음 주에 바꿀 것 한 가지를 정해서 보고하라." \
  --name "yt-weekly-review" \
  --skill yt-growth-review \
  --deliver telegram
```

## 관리 명령

```bash
hermes cron list                    # 등록된 잡 확인
hermes cron run yt-weekly-plans     # 스케줄 기다리지 않고 지금 한 번 실행 (테스트용)
hermes cron pause yt-daily-produce  # 잠깐 멈춤 — 크레딧 아낄 때
hermes cron resume yt-daily-produce
hermes cron edit yt-daily-produce
hermes cron remove yt-daily-produce
```

## cron 을 켜기 전 체크리스트

무인 실행이라 사람이 못 막습니다. 아래를 먼저 확인하세요.

- [ ] **Higgsfield 결제 계열 툴이 차단돼 있는가** — `mcp_servers.higgsfield.tools.include` 가
      생성·조회 계열로만 좁혀져 있어야 합니다. `confirm_billing_purchase` 같은 툴이
      열린 채로 cron 을 돌리면 크레딧이 떨어졌을 때 자동으로 결제할 수 있습니다.
- [ ] **크레딧 잔량을 확인했는가** — 잔량에 맞춰 `daily_video_cap` 을 정하세요.
      무료 체험이면 하루 3편으로 며칠 만에 소진됩니다.
- [ ] **수동으로 한 바퀴 돌려봤는가** — `hermes cron run <이름>` 으로 1회 테스트.
- [ ] **업로드가 private 로 끝나는가** — 검수 없이 공개되면 되돌리기 어렵습니다.

## 주의

- 예약 작업은 **매번 새 세션**에서 돕니다. 이전 대화 맥락이 없으므로, 프롬프트에 필요한 정보가
  다 들어있거나 스킬·브리프 파일에서 읽을 수 있어야 합니다.
- 제작 잡을 켜기 전에 반드시 `hermes cron run yt-daily-produce` 로 **수동 1회 테스트**를 하세요.
  Higgsfield 크레딧이 걸린 작업입니다.
- 업로드는 항상 비공개로 끝납니다. 공개는 사람이 스튜디오에서 직접 합니다.
