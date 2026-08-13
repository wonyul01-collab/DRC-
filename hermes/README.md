# Hermes × Higgsfield 유튜브 파이프라인

Hermes Agent가 **소재 리서치 → 대본 → 영상 생성 → 유튜브 업로드 → 성과 분석**을
스스로 돌게 만드는 설정 모음입니다. 영상 생성은 Higgsfield MCP,
업로드·분석은 YouTube 공식 API를 씁니다.

## 왜 이 구조인가

Higgsfield MCP는 Claude에 붙여도 되지만, 그건 **대화창을 열어야만 돌아갑니다.**
Hermes는 상주하면서 cron으로 혼자 돌고, 결과를 텔레그램 같은 곳으로 보내주고,
반복 작업을 스킬로 굳혀 둘 수 있습니다. "매일 알아서 돌리기"가 목적이라면 Hermes 쪽이 맞습니다.

## 구조

```
hermes/
├── install.sh                    # 스킬·스크립트를 ~/.hermes 에 배치
├── config.snippet.yaml           # ~/.hermes/config.yaml 에 병합할 블록
├── .env.example                  # ~/.hermes/.env 템플릿 (비밀값)
├── skills/
│   ├── yt-trend-research/        # 수요 조사 → 기획안
│   ├── yt-shorts-factory/        # 기획안 → 대본 → 영상 → 비공개 업로드
│   └── yt-growth-review/         # 성과 분석 → 다음 주 방향
├── scripts/
│   ├── youtube_upload.py         # 업로드 (AI 콘텐츠 공시 포함)
│   └── youtube_analytics.py      # 성과 조회
├── content/
│   └── channel-brief.example.yaml  # 채널 정의 — 가장 중요한 파일
└── cron/
    └── jobs.md                   # 예약 작업 등록 명령
```

## 사전 준비

| 항목 | 필요한 것 | 비용 |
|---|---|---|
| Hermes Agent | 설치 완료 (`~/.hermes` 존재) | 무료 (오픈소스) |
| LLM | Anthropic / OpenRouter / Gemini 중 하나 | 사용량 과금 |
| Higgsfield | **유료 구독 필수** (MCP는 구독자만) | 월 $15~ (크레딧제) |
| Google Cloud | YouTube Data API v3 사용 설정 + 데스크톱 OAuth 클라이언트 | 무료 (할당량 있음) |
| YouTube 채널 | 업로드할 채널 | 무료 |

> Higgsfield 크레딧은 이월되지 않고, 영상 1편 생성마다 차감됩니다.
> 그래서 이 설정에는 `daily_video_cap` 하드 캡과 순차 생성 강제가 들어 있습니다.

## 설치

```bash
git clone <이 저장소> && cd DRC-
bash hermes/install.sh
```

스크립트는 `~/.hermes/config.yaml` 을 **건드리지 않습니다.** 기존 설정을 깨뜨리지 않으려고
병합은 사람이 직접 합니다. 나머지 5단계는 install.sh 가 끝나면서 화면에 다시 안내합니다.

1. **config 병합** — `config.snippet.yaml` 의 `mcp_servers` / `skills.config` / `cron` 블록을
   `~/.hermes/config.yaml` 의 같은 최상위 키에 합칩니다.
2. **Higgsfield 연결**
   ```bash
   hermes mcp login higgsfield   # 브라우저 OAuth. API 키 없음.
   hermes tools                  # 툴이 실제로 등록됐는지 확인
   ```
   `tools.include` 는 `generate_*` 등 글롭으로 걸어뒀습니다. 실제 툴 이름이 다르면
   `hermes mcp configure higgsfield` 로 확인 후 조정하세요.
3. **YouTube 연결** — Google Cloud Console에서 YouTube Data API v3를 켜고
   "데스크톱 앱" OAuth 클라이언트 JSON을 받아 `~/.hermes/secrets/youtube_client_secret.json` 로 둔 뒤:
   ```bash
   python ~/.hermes/workspace/youtube/scripts/youtube_upload.py auth
   ```
4. **채널 브리프 작성** — `~/.hermes/workspace/youtube/channel-brief.yaml`.
   **여기가 비면 나머지가 다 무의미합니다.** 니치·타깃·파는 것을 구체적으로 적으세요.
5. **예약 작업 등록** — `cron/jobs.md` 참고. 리서치 잡 하나부터 시작하세요.

## 첫 실행

자동화를 켜기 전에 손으로 한 바퀴 돌려보세요.

```
hermes
> /yt-trend-research 이번 주 쇼츠 기획안 3개 만들어줘
> /yt-shorts-factory 방금 나온 기획안 중 1번으로 영상 만들어서 비공개 업로드해줘
```

기획안 품질이 쓸 만하고 영상이 원하는 톤으로 나오면, 그때 cron을 켭니다.

## 수익화에 대한 현실 점검

읽고 시작하시는 게 좋습니다. 여기서 대부분이 갈립니다.

**AI로 만들었다는 이유로 수익화가 막히지는 않습니다.** 2025년 7월 정책 개편 이후
YouTube가 걸러내는 건 "AI 사용"이 아니라 **반복·양산되는 비진정성 콘텐츠(inauthentic content)** 입니다.
기획 의도와 사람의 개입이 있고 시청자에게 새로운 가치를 주면, 100% AI 제작물도 수익화됩니다.
반대로 프롬프트만 갈아끼워 하루 20편씩 찍어내는 채널은 수익화에서 제외됩니다.

이 설정이 그에 맞춰 강제하는 것:

- 하루 생성 편수 하드 캡 (`daily_video_cap`, 기본 3)
- 업로드는 **항상 비공개**. 공개는 사람이 스튜디오에서 직접
- 기획안마다 수요 근거 URL 요구 — 추측 소재 방지
- 템플릿 복제 금지를 스킬에 명시
- AI 생성 사실적 영상은 `status.containsSyntheticMedia` 로 공시 (`--synthetic`)

**돈은 광고보다 상품에서 먼저 납니다.** 광고 수익(YPP)은 구독자·시청시간 요건을 채워야 시작되지만,
상품·리드마그넷은 첫날부터 팔 수 있습니다. 그래서 브리프에 `products` 와 `funnel` 을 필수로 뒀고,
주간 리뷰가 매번 퍼널 새는 곳을 짚습니다. 조회수만 나오고 상품과 무관한 영상은 이 파이프라인에서 버립니다.

## 안전장치 요약

| 위험 | 장치 |
|---|---|
| 크레딧 폭주 | `daily_video_cap`, 순차 생성, 2회 실패 시 중단 |
| 이상한 영상 자동 공개 | 업로드 기본 `private`, 검수 체크리스트 |
| 정책 위반 | 양산 금지 명시, AI 공시, 실존 인물 재현 금지 |
| 비밀값 유출 | 키는 `.env` 와 `~/.hermes/secrets`(700), config.yaml 에 넣지 않음 |

## 출처

- [Hermes Agent — MCP 설정 문서](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/mcp.md)
- [Hermes Agent — 전체 설정 문서](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/configuration.md)
- [Higgsfield MCP](https://higgsfield.ai/mcp) — 엔드포인트 `https://mcp.higgsfield.ai/mcp`, OAuth
- [YouTube Data API — videos.insert](https://developers.google.com/youtube/v3/docs/videos/insert)
- [YouTube Data API 개정 이력 — containsSyntheticMedia](https://developers.google.com/youtube/v3/revision_history)
- [유튜브 AI 수익화 정책 정리 (한국어)](https://www.openads.co.kr/content/contentDetail?contsId=17728)
