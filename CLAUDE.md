# 이 저장소에서 일할 때의 규칙

## 응답 규칙 — 반드시 지킬 것

**사용자가 열어야 할 위치는 항상 클릭 가능한 링크로 준다.**

사용자는 컴퓨터에 익숙하지 않다. "hPanel → VPS → 관리 → 도커 매니저 →
프로젝트" 같은 경로 설명만 주면 찾아가지 못하거나 엉뚱한 화면에 도달한다.
실제로 그 때문에 잘못된 인스턴스에서 작업하거나, 만료된 주소를 다시 열다가
시간을 크게 잃은 적이 여러 번 있다.

- 웹 페이지 → 마크다운 링크로 건다. 경로 설명은 링크를 연 **다음**에
  화면 어디를 봐야 하는지 알려주는 용도로만 쓴다.
- 저장소 파일 → GitHub 링크로 건다.
- PC 안의 파일·폴더 → 링크를 걸 수 없으므로 **복사해서 탐색기 주소창에
  붙여넣을 수 있는 전체 경로**를 코드블록으로 준다.
- 서버 안의 파일 → 경로만으로는 열 수 없으므로 **내용을 보는 명령**을
  함께 준다. 경로만 적어두면 사용자가 열 방법이 없다.

## 자주 여는 곳

| 대상 | 링크 |
|---|---|
| VPS 도커 매니저 (컨테이너 · nexos 크레딧 · 터미널) | https://hpanel.hostinger.com/vps/1902827/docker-manager?state=deployed |
| VPS 목록 | https://hpanel.hostinger.com/vps |
| Hermes 웹 UI (VPS, 운영용) | https://hermes-agent-5odr.srv1902827.hstgr.cloud/chat |
| 이 저장소 | https://github.com/wonyul01-collab/DRC- |
| 서식 — 상품 원가표 | https://github.com/wonyul01-collab/DRC-/blob/main/templates/catalog.csv |
| 서식 — 채널 상품코드 매핑 | https://github.com/wonyul01-collab/DRC-/blob/main/templates/sku_map.csv |
| 준비 안내 | https://github.com/wonyul01-collab/DRC-/blob/main/templates/README.md |
| 설치·운영 문서 | https://github.com/wonyul01-collab/DRC-/blob/main/docs/SETUP.md |
| 구글 앱 비밀번호 발급 | https://myaccount.google.com/apppasswords |

## 명령을 줄 때

- **한 줄로 준다.** 여러 줄을 붙여넣으면 채팅창이 줄바꿈을 전송으로 처리해
  첫 줄만 실행된다.
- **조용히 성공하는 명령에는 확인 명령을 같이 붙인다.** `sed`, `cp`, `mv`
  같은 명령은 성공하면 아무것도 출력하지 않아서, 사용자는 안 된 줄 안다.
- **비밀번호·API 키가 화면에 찍히는 명령은 주지 않는다.** 길이만 확인하는
  형태로 준다. 실제로 앱 비밀번호가 두 번 화면에 노출된 적이 있다.
- **어느 화면에 입력하는지 명시한다.** 셸 명령(`hermes`, `python3`)과
  채팅 슬래시 명령(`/config`, `/model`)은 입력하는 곳이 다르다.

## 이 환경의 구조

| | 위치 | 용도 |
|---|---|---|
| Hermes (VPS) | 호스팅어 컨테이너 `hermes-agent-5odr` | **운영** — 크론·자동 리포트 |
| Hermes (사무실 PC) | 로컬 설치 | 수동 작업 |
| Hermes (개인 PC) | 로컬 설치 | 수동 작업 |
| adops 파이프라인 | `/opt/data/adops-repo` (VPS) | 숫자 계산·리포트·발송 |

- 데이터 루트는 `/opt/data` (영속 볼륨). 스킬은 `/opt/data/skills/`.
- 컨테이너는 **UTC** 로 돈다. 크론은 KST−9시간으로 환산한다.
- **크론은 VPS 한 곳에만 건다.** 여러 곳에 걸면 메일이 중복 발송된다.
- LLM 크레딧(nexos.ai)과 웹 스크래핑 크레딧(Oxylabs)은 **별개 잔액**이며
  서로 대체되지 않는다.

## 설계상 지켜야 할 경계

**숫자는 `adops` 가 계산하고, 해석과 개선방안만 LLM 이 쓴다.**
광고비·ROAS·손익분기·공헌이익을 모델에게 계산시키면 매일 조금씩 틀린
리포트가 나간다. 스킬은 `analyze --brief` 가 만든 요약본만 읽는다.

크레딧이 떨어져도 숫자 리포트는 나가야 한다. `python3 -m adops daily` 는
모델을 전혀 호출하지 않는 경로다.
