# 설치 및 운영 설정

Hermes Agent 컨테이너 안에서 돌리는 것을 기준으로 한다.
컨테이너의 영속 볼륨은 `/opt/data` 이므로, 재시작해도 남아야 하는 것은
전부 그 아래에 둔다.

---

## 1. 저장소 배치

```bash
cd /opt/data
git clone <이 저장소 URL> adops-repo
cd adops-repo
python3 -m adops doctor     # 의존성 없이 바로 돌아야 정상
```

`adops`는 표준 라이브러리만 쓰므로 `pip install`이 필요 없다.
(구글 광고 API를 쓸 때만 `pip install google-ads`가 추가로 필요하다.)

환경변수로 위치를 고정해 둔다:

```bash
hermes config set ADOPS_HOME /opt/data/adops-repo
```

---

## 2. 설정 파일

```bash
cp config/config.example.yaml config/config.yaml
```

**가장 먼저 맞춰야 할 두 가지.** 이게 틀리면 리포트의 모든 판정이 무의미하다.

| 항목 | 어디서 확인 | 왜 중요한가 |
|---|---|---|
| `channel_fees` | 각 채널 **정산서**의 실효 수수료율 | 손익분기 ROAS의 분모 |
| `catalog` CSV의 원가 | 매입 단가 | 공헌이익 계산의 전부 |

카탈로그에 원가가 없으면 `default_gross_margin_rate`로 추정하는데,
이건 어디까지나 임시방편이다. `doctor`가 원가 미등록 SKU 수를 경고한다.

설정 후 확인:

```bash
python3 -m adops doctor
```

`손익분기 ROAS`가 상식적인 값(보통 200~350%)으로 나오는지 본다.
`계산불가(마진<수수료)`가 뜨면 수수료율이나 마진율 입력이 잘못된 것이다.

---

## 3. 데이터 연결

### 방법 A — CSV (권장, 오늘 바로 가능)

각 채널 관리자에서 리포트를 받아 아래 폴더에 넣는다. 파일명은 자유이고,
같은 폴더에 여러 파일이 있어도 전부 읽는다.

```
data/raw/
├── naver_sa/              네이버 검색광고 → 키워드별 성과 보고서
├── naver_search_terms/    네이버 검색광고 → 검색어 보고서
├── coupang_ads/           쿠팡 광고 → 보고서 다운로드
├── meta_ads/              메타 광고관리자 → 내보내기 (지면별 분류 포함)
├── google_ads/            구글 광고 → 키워드 보고서
├── sales_smartstore/      스마트스토어 → 정산/매출 내역
├── sales_coupang/         쿠팡 윙 → 판매 내역
├── sales_own/             자사몰 → 주문 내역
└── catalog/               SKU 마스터 (원가 포함) — 직접 작성
```

컬럼명은 자동 인식된다(한글/영문, 공백·괄호 무시). 인식 실패 시
어떤 컬럼을 못 찾았는지 경고가 뜨므로, `adops/adapters/csv_source.py`의
`PROFILES`에 별칭만 추가하면 된다.

**검색어 보고서를 빼먹지 마라.** 제외키워드 후보와 승격 후보는 전적으로
이 데이터에서만 나온다. 실무 절감 효과가 가장 큰 항목이다.

### 방법 B — API

`config.yaml`의 `sources`에서 해당 채널을 `enabled: true`로 바꾸고
자격증명을 환경변수로 넣는다. 자세한 내용은 [DATA_SOURCES.md](DATA_SOURCES.md).

> API 어댑터 중 **네이버·쿠팡은 최초 1회 실제 응답 확인이 필요하다.**
> 인증(서명)은 구현되어 있으나 리포트 응답 스키마가 계정 유형에 따라
> 달라서, 검증 전에는 CSV를 쓰는 편이 안전하다. 메타·구글은 응답 형식이
> 안정적이라 그대로 쓸 수 있다.

---

## 4. 스킬 설치

```bash
mkdir -p ~/.hermes/skills/ecommerce
cp -r skills/ad-daily-report   ~/.hermes/skills/ecommerce/
cp -r skills/ad-monthly-close  ~/.hermes/skills/ecommerce/
```

채팅창에서 재스캔:

```
/reload-skills
/skills
```

목록에 두 스킬이 보이면 `/ad-daily-report` 로 수동 실행할 수 있다.

---

## 5. 메일 발송 설정

Hermes에 이메일 채널이 내장되어 있어 별도 SMTP 코드가 필요 없다.

```bash
hermes config set EMAIL_ADDRESS       발신계정@gmail.com
hermes config set EMAIL_PASSWORD      <Gmail 앱 비밀번호>
hermes config set EMAIL_SMTP_HOST     smtp.gmail.com
hermes config set EMAIL_IMAP_HOST     imap.gmail.com
hermes config set EMAIL_HOME_ADDRESS  drc2104@naver.com
```

- **앱 비밀번호**를 써야 한다. 구글 계정 비밀번호로는 SMTP 인증이 안 된다.
  구글 계정 → 보안 → 2단계 인증 활성화 → 앱 비밀번호 생성.
- `EMAIL_HOME_ADDRESS`가 **크론 작업의 기본 발송 대상**이다.
- 수신자를 늘리려면 쉼표로 구분한다.

설정 후 게이트웨이 재시작(웹 UI의 `Restart Gateway`), 그다음 확인:

```
/platforms
```

---

## 6. 크론 등록

채팅창에서 등록한다. 시각은 컨테이너 로컬 시간 기준이므로, KST가 아니면
먼저 `date`로 확인하고 보정한다.

```
/cron add "0 8 * * *" "어제자 광고 효율 분석을 수행하고 리포트를 메일로 발송해줘" --skill ad-daily-report
/cron add "0 9 1 * *" "전월 마감 상세 분석을 수행하고 리포트를 메일로 발송해줘" --skill ad-monthly-close
```

확인 및 시험 실행:

```
/cron list
/cron run <job_id>
```

**반드시 `/cron run`으로 한 번 수동 실행해서 메일이 실제로 도착하는지
확인하라.** 크론은 조용히 실패하는 것이 가장 흔한 사고 유형이다.

---

## 7. 운영 점검

주기적으로 확인할 것:

```bash
python3 -m adops doctor          # 데이터 결손·원가 누락
```

```
/cron list                       # 작업이 살아 있는지
/logs                            # 게이트웨이 로그
```

리포트 최상단에 **데이터 결손 경고**가 떴다면 그날 수치는 과소계상된
것이다. 해당 채널의 CSV 업로드나 API 자격증명 만료를 확인한다.

메타 액세스 토큰은 **장기 토큰(long-lived)**이어야 한다. 단기 토큰은
며칠 만에 만료되어 크론이 조용히 실패한다.
