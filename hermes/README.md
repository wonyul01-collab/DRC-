# Hermes × Higgsfield 유튜브 쇼츠 파이프라인

Hermes Agent가 **벤치마크 채널 문법 학습 → 소재 리서치 → 대본 → 클립 생성 → 나레이션·자막 합성
→ 유튜브 업로드 → 성과 분석**을 돌게 만드는 설정 모음입니다.

## 왜 이 구조인가

Higgsfield MCP는 Claude에 붙여도 되지만, 그건 **대화창을 열어야만 돌아갑니다.**
Hermes는 상주하면서 cron으로 혼자 돌고, 결과를 텔레그램으로 보내주고,
반복 작업을 스킬로 굳혀 둘 수 있습니다. "매일 알아서 돌리기"가 목적이면 Hermes 쪽이 맞습니다.

그리고 **Higgsfield만으로는 한국어 쇼츠가 완성되지 않습니다.** 클립은 만들어 주지만
한글 자막은 깨지고 한국어 나레이션은 제어가 안 됩니다. 그래서 마지막 조립을
`compose_short.py` 가 ffmpeg로 처리합니다.

```
Higgsfield MCP  →  무음 클립 (9:16)
edge-tts        →  한국어 나레이션
ffmpeg          →  세로 크롭 + 자막 번인 + 오디오 합성 + 컷 연결
YouTube API     →  비공개 업로드
```

## 구조

```
hermes/
├── install.sh                      # 스킬·스크립트를 ~/.hermes 에 배치
├── config.snippet.yaml             # ~/.hermes/config.yaml 에 병합할 블록
├── .env.example                    # ~/.hermes/.env 템플릿 (비밀값)
├── skills/
│   ├── yt-style-extract/           # 분석 노트 → reference-style.yaml
│   ├── yt-trend-research/          # 수요 조사 → 기획안
│   ├── yt-shorts-factory/          # 기획안 → 대본 → 클립 → 합성 → 비공개 업로드
│   └── yt-growth-review/           # 성과 분석 → 다음 주 방향
├── scripts/
│   ├── compose_short.py            # TTS + 한글 자막 + 컷 합성  ★핵심
│   ├── analyze_reference.py        # 벤치마크 채널 실측 (YouTube API)
│   ├── youtube_upload.py           # 업로드 (AI 콘텐츠 공시 포함)
│   └── youtube_analytics.py        # 성과 조회
├── content/
│   ├── channel-brief.example.yaml  # 내 채널 정의
│   ├── reference-style.example.yaml # 벤치마크 문법 빈 템플릿
│   └── styles/
│       └── jinjja-jamkkanman.yaml  # "진짜 잠깐만" 분석 결과  ★핵심
└── cron/jobs.md                    # 예약 작업 등록 명령
```

핵심 파일은 두 개입니다. `reference-style.yaml` 이 **어떻게 만들지**를 정하고,
`channel-brief.yaml` 이 **무엇을 만들지**를 정합니다.

## 단계 (brief 의 `stage`)

| stage | 목표 | 채워야 할 것 |
|---|---|---|
| `practice` | 벤치마크 채널처럼 만들어 보기 | channel, audience, benchmark, format |
| `growth` | 구독자·시청시간 확보 | 위 + cadence 준수 |
| `monetize` | 상품 판매 / 광고 수익 | 위 + products, funnel |

지금은 `practice` 로 두고 시작하면 됩니다. `products` 가 비어 있어도 파이프라인은 돕니다.

## 사전 준비

| 항목 | 필요한 것 | 비용 |
|---|---|---|
| Hermes Agent | 설치 완료 (`~/.hermes` 존재) | 무료 |
| LLM | Anthropic / OpenRouter / Gemini 중 하나 | 사용량 과금 |
| Higgsfield | **유료 구독 필수** (MCP는 구독자만) | 월 $15~ (크레딧제) |
| YouTube API 키 | 벤치마크 채널 실측 (읽기 전용, OAuth와 별개) | 무료 |
| ffmpeg | 자막·오디오 합성 | 무료 |
| 한글 폰트 | 자막 렌더링 (Noto Sans KR 등) | 무료 |
| edge-tts | 한국어 나레이션 | 무료 |
| Google Cloud | YouTube Data API v3 + 데스크톱 OAuth 클라이언트 | 무료 |

> Higgsfield 크레딧은 이월되지 않고 영상 1편마다 차감됩니다.
> 그래서 `daily_video_cap` 하드 캡과 순차 생성 강제가 들어 있습니다.

## 설치

```bash
bash hermes/install.sh
```

`~/.hermes/config.yaml` 은 **자동으로 안 건드립니다.** 기존 설정을 깨뜨리지 않으려고
병합은 사람이 합니다. 나머지 단계는 install.sh 가 끝나면서 화면에 다시 안내합니다.

1. **config 병합** — `config.snippet.yaml` 의 `mcp_servers` / `skills.config` / `cron` 을
   `~/.hermes/config.yaml` 의 같은 최상위 키에 합칩니다.
2. **Higgsfield 연결** — `hermes mcp login higgsfield` → `hermes tools` 로 확인
3. **YouTube 연결** — 데스크톱 OAuth JSON을 `~/.hermes/secrets/youtube_client_secret.json` 에 두고
   `python ~/.hermes/workspace/youtube/scripts/youtube_upload.py auth`
4. **채널 브리프 작성** — `~/.hermes/workspace/youtube/channel-brief.yaml`
5. **벤치마크 문법 심기** — 분석 노트를 주고 `/yt-style-extract` 실행
6. **합성 도구 점검** — `python .../compose_short.py check`

## 첫 실행

자동화를 켜기 전에 손으로 한 바퀴 돌려보세요.

```
hermes
> /yt-style-extract ~/obsidian/shorts-vault 를 읽고 스타일 파일을 채워줘
> /yt-trend-research 이번 주 쇼츠 기획안 3개 만들어줘
> /yt-shorts-factory 1번 기획안으로 영상 만들어서 비공개 업로드해줘
```

## 합성 스크립트 단독 사용

Hermes 없이도 됩니다. shotlist JSON 하나면 영상이 나옵니다.

```bash
python compose_short.py build \
  --shotlist out/plans/2026-08-13-01.shotlist.json \
  --style ~/.hermes/workspace/youtube/reference-style.yaml \
  --out out/video/2026-08-13-01.mp4
```

`voice.provider: none` 으로 두고 각 shot 에 `duration` 을 적으면 나레이션 없이
자막만 넣은 영상도 만들 수 있습니다.

## 벤치마킹의 선

성공한 채널의 **문법**을 배우는 것과 **콘텐츠**를 복제하는 것은 다릅니다.
이 파이프라인은 전자만 합니다.

| 가져오는 것 | 가져오지 않는 것 |
|---|---|
| 후킹 문장의 *틀* | 후킹 문장 자체 |
| 컷 리듬, 자막 스타일, 목소리 톤 | 원본 클립, 로고, 시그니처 사운드 |
| 구조 (몇 초에 무엇) | 대본, 소재 |

저작권 문제이기도 하고, YouTube가 **재사용·양산 콘텐츠**를 수익화에서 제외하기 때문입니다.
2025년 7월 정책 개편 이후 걸러지는 건 "AI 사용"이 아니라 **비진정성 콘텐츠**입니다.
기획 의도와 사람의 개입이 있으면 100% AI 제작물도 수익화됩니다.

## 안전장치

| 위험 | 장치 |
|---|---|
| 크레딧 폭주 | `daily_video_cap`, 순차 생성, 2회 실패 시 중단 |
| 이상한 영상 자동 공개 | 업로드 기본 `private`, 7항목 검수 체크리스트 |
| 정책 위반 | 양산·복제 금지 명시, AI 공시(`--synthetic`), 실존 인물 재현 금지 |
| 자막 깨짐 | install 시 한글 폰트 검사, `compose_short.py check` |
| 비밀값 유출 | 키는 `.env` 와 `~/.hermes/secrets`(700), config.yaml 에 넣지 않음 |

## 출처

- [Hermes Agent — MCP 설정](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/features/mcp.md) · [전체 설정](https://github.com/NousResearch/hermes-agent/blob/main/website/docs/user-guide/configuration.md)
- [Higgsfield MCP](https://higgsfield.ai/mcp) — `https://mcp.higgsfield.ai/mcp`, OAuth
- [YouTube Data API — videos.insert](https://developers.google.com/youtube/v3/docs/videos/insert) · [containsSyntheticMedia](https://developers.google.com/youtube/v3/revision_history)
- [유튜브 AI 수익화 정책 정리](https://www.openads.co.kr/content/contentDetail?contsId=17728)
