---
name: yt-shorts-factory
description: 기획안을 받아 대본을 쓰고 Higgsfield MCP로 클립을 생성한 뒤 TTS 나레이션과 한글 자막을 합성해 YouTube에 비공개로 업로드한다. 유튜브 쇼츠를 실제로 제작·업로드해야 할 때 사용한다.
---

# 쇼츠 제작 파이프라인

기획안 하나 → 대본 → 클립 → 나레이션·자막 합성 → 비공개 업로드까지 끝낸다.
**공개(public)는 절대 자동으로 하지 않는다.** 사람이 검수한 뒤 직접 공개한다.

## 전제

- `~/.hermes/workspace/youtube/reference-style.yaml` 이 있어야 한다.
  없으면 `yt-style-extract` 를 먼저 돌리라고 안내하고 **중단한다.**
  스타일 없이 만들면 회차마다 다른 채널처럼 보인다.
- Higgsfield MCP 연결 필요. 툴이 안 보이면 `hermes mcp login higgsfield` 안내.
- Higgsfield 는 유료 크레딧을 쓴다. 생성 1회는 곧 돈이다. 실패를 줄이는 쪽으로 움직인다.

## 설정값 (skills.config.yt-shorts-factory)

| 키 | 의미 |
|---|---|
| `brief_path` | 채널 브리프 경로 |
| `style_path` | 레퍼런스 스타일 경로 |
| `output_dir` | 생성물 저장 위치 |
| `scripts_dir` | 파이썬 스크립트 위치 |
| `daily_video_cap` | 하루 최대 생성 편수 (폭주 루프 차단) |
| `max_clips_per_video` | 편당 최대 생성 클립 수 (**실질적인 비용 통제선**) |
| `min_credit_floor` | 잔량이 이 아래면 생성 중단 |
| `measured_credits_per_video` | 실측된 편당 크레딧. `null` 이면 아직 미측정 |
| `default_privacy` | 업로드 공개 범위 (기본 `private`) |

## 절차

### 1. 사전 점검 — 크레딧을 쓰기 전에 반드시

크레딧은 곧 돈이고, 한 번 쓰면 되돌릴 수 없다. 순서대로 확인한다.

1. **잔량 조회** — Higgsfield `balance` 툴을 호출한다.
   `min_credit_floor` 보다 적으면 **생성하지 말고 중단**하고 보고한다.
2. **오늘 편수** — `{output_dir}/log.jsonl` 에서 센다.
   `daily_video_cap` 에 도달했으면 중단하고 보고한다.
3. **예산 추정** — `measured_credits_per_video` 가 있으면
   `잔량 - 예상비용 < min_credit_floor` 인지 확인한다. 걸리면 중단한다.
4. 기획안의 `risk` 가 `none` 이 아니면 생성 전에 사용자에게 확인받는다.
5. `reference-style.yaml` 을 읽어 이번 회차가 지킬 규칙을 파악한다.

> **편수 상한은 비용 통제가 아니다.** 쇼츠 1편은 생성 1회가 아니라 컷 여러 개다.
> 20컷을 전부 새로 뽑으면 편당 300~900 크레딧이 나간다.
> 실제 방어선은 `max_clips_per_video` 다.

### 1-A. 첫 영상은 측정용이다

`measured_credits_per_video` 가 `null` 이면 아직 편당 비용을 모르는 상태다.
이때는 **본편을 만들지 말고 측정부터 한다.**

1. 클립 **3~4개짜리** 짧은 영상으로 만든다 (15초 내외).
2. 만들기 전후로 `balance` 를 호출해 차감량을 기록한다.
   `transactions` 로 항목별 단가도 확인한다.
3. 결과를 사용자에게 보고하고, `measured_credits_per_video` 와
   `max_clips_per_video` 를 실측에 맞춰 조정하자고 제안한다.
4. 그 전까지는 본편 제작을 시작하지 않는다.

추정으로 본편을 만들다가 크레딧이 중간에 떨어지면, 이미 쓴 크레딧은
못 돌려받고 영상은 미완성으로 남는다. 가장 비싼 실패다.

### 2. 대본 작성 — 스타일을 따른다

기획안의 `beats` 를 실제 낭독 대본으로 옮기되, **스타일 파일의 공식을 적용한다.**

- 첫 문장은 `hooking.types` 중 하나의 `pattern` 을 써서 만든다.
  단, 패턴은 *틀* 이다. 예시 문장을 그대로 쓰지 않는다.
- 총 길이는 `structure.total_seconds` 범위 안. 한국어 낭독은 초당 4~5음절로 계산한다.
- 컷 수는 `structure.cut_rhythm.avg_shot_seconds` 로 나눠서 정한다.
  (예: 25초 영상, 평균 컷 1.5초 → 약 16컷. 너무 많으면 컷당 2~3초로 묶는다.)
- 마지막은 `structure.ending.signature` 와 `cta` 를 따른다.
- `{output_dir}/scripts/{id}.md` 에 저장한다.

### 3. shotlist 만들기

대본을 컷 단위로 쪼개 `{output_dir}/plans/{id}.shotlist.json` 을 만든다.

```json
{
  "id": "2026-08-13-01",
  "shots": [
    {
      "clip": "../video/raw/2026-08-13-01/01.mp4",
      "narration": "이 컷에서 읽을 문장",
      "subtitle": "화면에 띄울 자막 (생략하면 narration 사용)",
      "note": "체중 70kg 기준",
      "visual_prompt": "Higgsfield 에 넣을 장면 묘사"
    }
  ]
}
```

- `subtitle` — 본 자막. `max_chars_per_cue` 단위로 잘려 순차 표시된다.
- `note` — **보조 자막.** 본 자막보다 작고 회색으로 아래에 깔리며, 쪼개지 않고
  그 shot 내내 한 줄로 표시된다. 크기·색·위치는 `subtitle.secondary` 에서 조정한다.
  아래 세 가지에 쓴다. 정직함을 화면에서 지키는 수단이다.
  - **기준값** — "체중 70kg 기준" 처럼 숫자를 해석하는 데 필요한 전제
  - **출처·한계** — "계측 인공관절 5명 측정값" 처럼 표본의 한계
  - **다음 편 예고** — 마지막 shot 에 걸어 구독 동기를 만든다
- `visual_prompt` — 합성 스크립트가 쓰지 않는다. 클립 생성 단계에서 쓰는 메모다.
- `clip` 에 **`"@black"`** 을 쓰면 스크립트가 검은 화면을 직접 만든다.
  **Higgsfield 크레딧이 들지 않는다.** 절단마공 엔딩의 블랙아웃은 항상 이걸 쓴다.
  단색이 필요하면 `"@color:0x101820"` 형식도 된다.
  생성 클립을 무음 처리해도 화면은 계속 나오므로, 블랙아웃은 반드시 이 방식이어야 한다.

### 4. 클립 생성 (Higgsfield MCP)

- 먼저 사용 가능한 툴과 모델을 확인한다. 툴 이름을 추측해서 호출하지 않는다.
- 종횡비는 `visual.aspect_ratio` (기본 **9:16**).
- 프롬프트에 `visual.mood`, `visual.camera`, `visual.subject_type` 을 반영한다.
  기획안의 `visual_direction` 을 구체적 장면 묘사로 풀어 쓴다.
- **블랙아웃·단색 화면은 생성하지 않는다.** shotlist 에서 `"@black"` 을 쓴다.
  크레딧 0 이다. 이런 걸 Higgsfield 로 만드는 것은 돈을 버리는 일이다.
- **생성할 클립 수가 `max_clips_per_video` 를 넘지 않게 한다.**
  컷이 20개여도 클립은 8개면 된다. 같은 클립을 여러 shot 이 나눠 쓰고,
  자막·나레이션이 바뀌면 시청자에게는 다른 컷으로 읽힌다.
  이게 편당 비용을 절반 이하로 줄이는 가장 확실한 방법이다.
- **한 컷씩 순차 생성.** 병렬로 돌리지 않는다 (크레딧·레이트리밋).
- **클립에 글자를 넣으려 하지 않는다.** 한글은 깨진다. 자막은 6단계에서 넣는다.
- 나레이션도 Higgsfield에 시키지 않는다. 한국어 TTS는 6단계에서 처리한다.
- 생성 실패 시 같은 프롬프트로 무한 재시도하지 않는다. 2회 실패하면 멈추고 보고한다.
- 채널 캐릭터가 정해져 있으면 캐릭터 일관성 기능(Soul 등)을 쓴다.
- 결과를 `{output_dir}/video/raw/{id}/NN.mp4` 로 내려받는다.

> 컷 수가 많고 크레딧이 부담되면, 클립 하나를 여러 shot 이 나눠 쓰게 해도 된다.
> `compose_short.py` 는 같은 클립을 여러 shot 에서 참조해도 정상 동작한다.

### 5. 합성 — 나레이션 + 자막

```bash
python {scripts_dir}/compose_short.py build \
  --shotlist "{output_dir}/plans/{id}.shotlist.json" \
  --style "{style_path}" \
  --out "{output_dir}/video/{id}.mp4"
```

- 스크립트가 TTS 생성 → 컷 길이 계산 → 세로 크롭 → 자막 번인 → 오디오 합성을 한 번에 한다.
- 출력 JSON 의 `duration_seconds` 를 확인한다. 60초를 넘으면 경고가 뜬다. 대본을 줄인다.
- 처음 실행이라면 먼저 `python {scripts_dir}/compose_short.py check --style {style_path}` 로
  ffmpeg·edge-tts·한글 폰트를 확인한다. `--style` 을 빼면 폰트 검사가 생략된다.

### 6. 사람 검수 게이트

업로드 전에 아래를 스스로 점검하고, 하나라도 걸리면 업로드하지 말고 보고한다.

- [ ] 자막이 화면 밖으로 나가거나 쇼츠 UI에 가리지 않는가
- [ ] 자막에 오탈자가 없는가
- [ ] 나레이션과 자막이 어긋나지 않는가
- [ ] 실존 인물처럼 보이는 얼굴이 사실과 다른 말을 하고 있지 않은가
- [ ] 사실 주장(수치·인용)에 근거가 있는가
- [ ] 참고 채널의 대본·클립·로고를 그대로 쓴 곳이 없는가

### 7. 업로드

```bash
python {scripts_dir}/youtube_upload.py upload \
  --file "{output_dir}/video/{id}.mp4" \
  --title "기획안의 title" \
  --description-file "{output_dir}/desc/{id}.txt" \
  --tags "태그1,태그2,태그3" \
  --privacy private \
  --synthetic
```

- `--synthetic` 은 **AI로 만든 사실적 영상이면 반드시 붙인다.** YouTube 합성 콘텐츠 공시 항목이다.
  애니메이션·명백한 비현실 연출만 있으면 빼도 된다.
- 설명문은 `{output_dir}/desc/{id}.txt` 에 먼저 쓴다. 훅 요약 + 해시태그.
- 끝나면 반환된 `studio_url` 을 사용자에게 전달한다. 사람이 거기서 확인하고 공개한다.

### 8. 기록

`{output_dir}/log.jsonl` 에 한 줄 추가한다.

```json
{"date":"2026-08-13","plan_id":"...","video_id":"...","shots":12,"clips_generated":8,
 "credits_before":1800,"credits_after":1640,"credits_used":160,
 "duration":27.4,"hook_type":"충격선언","status":"uploaded_private"}
```

- `hook_type` 을 남겨야 주간 리뷰에서 "어떤 후킹이 먹혔는가"를 판정할 수 있다.
- `credits_used` 를 남겨야 편당 비용이 실측으로 쌓인다. 이 값이 몇 편 모이면
  `measured_credits_per_video` 를 평균으로 갱신하자고 제안한다.

## 하지 말 것

- 공개 상태로 자동 업로드하지 않는다.
- `daily_video_cap` 을 넘겨 생성하지 않는다.
- 참고 채널의 대본 문장을 그대로 쓰지 않는다. 공식만 쓴다.
  YouTube는 재사용·양산 콘텐츠를 수익화 대상에서 제외한다.
- 하나의 대본을 단어만 바꿔 여러 편으로 복제하지 않는다.
- 실존 인물의 얼굴·목소리를 동의 없이 재현하지 않는다.
