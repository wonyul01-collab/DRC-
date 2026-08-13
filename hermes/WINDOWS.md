# Windows 설치 가이드

Windows에서 Hermes를 돌리는 방법은 두 가지고, **설치 방법이 서로 다릅니다.**
먼저 어느 쪽인지 확인하세요.

## 0. 내 Hermes는 어디에 깔렸나

**폴더 존재 여부로 판단하지 마세요.** `analyze_reference.py --setup` 이
`%LOCALAPPDATA%\hermes\secrets\` 를 만들기 때문에, Hermes 가 없어도 그 경로는
생길 수 있습니다. 실행 파일로 판단해야 합니다.

Windows 터미널(PowerShell)에서:

```powershell
# 설치 여부와 위치를 한 번에
hermes --version
Get-Command hermes | Select-Object -ExpandProperty Source
```

| `Get-Command` 결과 | 갈 길 |
|---|---|
| `...\AppData\Local\hermes\hermes-agent\venv\Scripts\hermes.exe` | **네이티브 Windows** → 경로 B |
| WSL 안에서만 `hermes --version` 이 응답 | **WSL2** → 경로 A |
| 양쪽 다 응답 | 실제로 쓰실 쪽을 고르세요 |
| `명령을 찾을 수 없습니다` | 아직 미설치 |

WSL2 쪽도 따로 확인하려면:

```powershell
wsl bash -lc "hermes --version"
```

> **왜 WSL2를 권하는가**: 이 파이프라인은 ffmpeg·edge-tts·bash에 기대고 있고,
> Hermes 자체도 리눅스 경로가 더 검증돼 있습니다. 네이티브 Windows도 되게
> 만들어 뒀지만(`install.ps1`), 문제가 생기면 WSL2 쪽이 고치기 쉽습니다.

---

## 경로 A — WSL2 (권장)

WSL2 안의 Ubuntu 터미널에서 진행합니다. `wsl` 을 치면 들어갑니다.

### A-1. 준비물 설치

```bash
sudo apt update
sudo apt install -y ffmpeg fonts-noto-cjk python3-pip
fc-cache -f
```

폰트 확인 — **`Noto Sans CJK KR`** 이 나와야 합니다:

```bash
fc-list :lang=ko family | tr ',' '\n' | sort -u
```

### A-2. 파이프라인 설치

```bash
cd /mnt/c/Users/<사용자명>/여기에-클론한-폴더    # 또는 WSL 홈에 클론
bash hermes/install.sh
```

> `bad interpreter: /bin/bash^M` 오류가 나면 Windows에서 클론하며 줄바꿈이
> CRLF로 바뀐 경우입니다. 저장소에 `.gitattributes` 를 넣어 뒀으니
> 다시 클론하거나 `sed -i 's/\r$//' hermes/install.sh` 로 고치면 됩니다.

### A-3. 자막 폰트 설정

기본값은 **Pretendard** 입니다. 없으면 [배포 페이지](https://github.com/orioncactus/pretendard/releases)
에서 받아 설치하시면 Windows·WSL 양쪽에서 다 잡힙니다.

설치된 이름을 먼저 확인하세요:

```bash
fc-list :lang=ko family | tr ',' '\n' | sort -u
```

그 목록에 있는 이름을 `~/.hermes/workspace/youtube/reference-style.yaml` 에 넣습니다:

```yaml
subtitle:
  font_family: "Pretendard"           # 권장
```

Windows의 맑은 고딕을 그대로 쓰고 싶으면 (WSL에서 접근 가능합니다):

```yaml
subtitle:
  font_family: "Malgun Gothic"
  font_file: "/mnt/c/Windows/Fonts/malgun.ttf"
```

> **`Noto Sans CJK KR` 은 피하세요.** 배포판에 따라 `Black / Bold / Light / Medium / Regular`
> 만 등록되고 **굵기 없는 순수 패밀리명이 없는** 경우가 있습니다. 그러면 libass 가
> 매칭에 실패하는데, **에러를 내지 않고 조용히 기본 폰트로 떨어집니다.**
> 영상을 눈으로 볼 때까지 모릅니다.

`compose_short.py` 가 실행 전에 폰트 존재를 확인해 경고를 띄웁니다.
경고가 뜨면 반드시 고치고 진행하세요.

### A-4. 브라우저 인증 (WSL2의 유일한 함정)

WSL2에는 브라우저가 없어서 OAuth 창이 자동으로 안 열릴 수 있습니다. 둘 중 하나:

**방법 1 — 자동으로 열리게 만들기** (한 번만 하면 됨)

```bash
sudo apt install -y wslu
```

**방법 2 — URL 직접 복사**

터미널에 뜨는 `https://...` 주소를 복사해서 Windows 브라우저 주소창에 붙여넣습니다.
인증 후 `localhost:포트` 로 돌아오는 것은 WSL2가 자동 전달하므로 그대로 완료됩니다.

---

## 경로 B — 네이티브 Windows

PowerShell에서:

```powershell
# ffmpeg (없으면)
winget install --id Gyan.FFmpeg
# 설치 후 새 터미널을 열어야 PATH가 잡힙니다

# 파이프라인 설치
powershell -ExecutionPolicy Bypass -File hermes\install.ps1
```

자막 폰트는 **Pretendard** 를 권장합니다
([설치](https://github.com/orioncactus/pretendard/releases)). 설치가 번거로우면
Windows 기본 맑은 고딕도 됩니다:

```yaml
subtitle:
  font_family: "Pretendard"      # 또는 "Malgun Gothic"
```

> `install.ps1` 은 이 개발 환경에 PowerShell이 없어 **실행 검증을 못 했습니다.**
> 문제가 생기면 알려주세요. 하는 일은 폴더 만들고 파일 복사하는 것뿐이라
> 아래 수동 명령으로 대체할 수도 있습니다.

<details>
<summary>수동 설치 (install.ps1 대신)</summary>

```powershell
$H = "$env:LOCALAPPDATA\hermes"
$W = "$H\workspace\youtube"

New-Item -ItemType Directory -Force -Path "$H\skills","$W\scripts","$H\secrets" | Out-Null
'plans','scripts','video','video\raw','desc','reviews' | ForEach-Object {
    New-Item -ItemType Directory -Force -Path "$W\out\$_" | Out-Null
}

Copy-Item hermes\skills\* "$H\skills\" -Recurse -Force
Copy-Item hermes\scripts\*.py "$W\scripts\" -Force
Copy-Item hermes\scripts\requirements.txt "$W\scripts\" -Force
Copy-Item hermes\content\channel-brief.example.yaml "$W\channel-brief.yaml"
Copy-Item hermes\content\styles\jinjja-jamkkanman.yaml "$W\reference-style.yaml"

python -m pip install -r "$W\scripts\requirements.txt"
```

</details>

---

## 공통 — 두 경로 모두 해야 할 것

### 1. config.yaml 병합

`hermes/config.snippet.yaml` 의 `mcp_servers` / `skills.config` / `cron` 블록을
Hermes의 `config.yaml` 같은 최상위 키에 **합칩니다.** 파일 전체를 덮어쓰지 마세요.

| 경로 | config.yaml 위치 |
|---|---|
| WSL2 | `~/.hermes/config.yaml` (윈도우 탐색기에서 `\\wsl$\Ubuntu\home\<사용자>\.hermes`) |
| 네이티브 | `%LOCALAPPDATA%\hermes\config.yaml` |

### 2. Higgsfield 연결

구독은 이미 되어 있으니 인증만 하면 됩니다. 구글 로그인 창이 뜹니다.

```bash
hermes mcp login higgsfield
```

브라우저에 구글 로그인 창이 뜹니다. 끝나면 터미널에
`✓ Authenticated — N tool(s) available` 이 찍힙니다. **그게 확인입니다.**
숫자가 나오면 구독도 살아 있다는 뜻입니다.

### ⚠ 주의: 확인용으로 쓰면 안 되는 명령

| 명령 | 실제 동작 |
|---|---|
| `hermes tools` | 조회가 아니라 **대화형 툴셋 선택 UI** |
| `hermes mcp configure <name>` | **대화형 툴 선택 체크리스트** |
| `hermes mcp` (인자 없이) | **대화형 카탈로그 피커** |

이름만 보면 조회 명령 같지만 전부 사람이 방향키로 고르는 화면입니다.
공식 문서에도 `hermes tools — Configure enabled tools` 로 적혀 있습니다.

**에이전트·스크립트·백그라운드처럼 stdin 이 없는 곳에서 실행하면 위험합니다.**
메뉴가 무한 재출력되다가 선택 결과가 `config.yaml` 에 써지고,
`platform_toolsets.cli` 같은 값이 통째로 덮어써집니다. 그러면 화이트리스트
게이팅에 걸려 방금 붙인 MCP 툴이 오히려 전부 차단됩니다.

**툴 이름을 알고 싶으면 Hermes 대화창에서 에이전트에게 물어보세요:**

```
지금 쓸 수 있는 higgsfield 툴 이름을 전부 나열해줘
```

에이전트는 자기 툴 목록을 이미 갖고 있어서 바로 답합니다.
설정 파일을 건드리지 않는 유일하게 안전한 확인 방법입니다.

> 사고가 났다면 `config.yaml.bak-*` 백업이 같은 폴더에 있습니다.
> `platform_toolsets.cli` 를 원래 값(보통 `['hermes-cli']`)으로 되돌리면 복구됩니다.

### `-t` 플래그도 조심하세요 (미확인 가설)

`hermes -t hermes-cli,mcp-higgsfield -z "..."` 처럼 툴셋을 명시한 직후
`platform_toolsets.cli` 가 개별 툴셋 목록으로 펼쳐지고 MCP 툴이
`TOOL_UNAVAILABLE` 로 사라지는 현상을 겪었습니다. **인과는 확인되지 않았지만
시간 순서가 겹칩니다.**

MCP 서버 툴은 런타임에 `mcp-<이름>` 으로 등록되는 것이라 `-t` 의 툴셋 목록에
넣을 대상이 아닐 수 있습니다. 넣으면 오히려 화이트리스트로 작동해 차단될
여지가 있습니다.

**MCP 툴을 쓸 때는 `-t` 를 붙이지 마세요.** 그냥 `hermes -z "..."` 로
호출하면 등록된 MCP 툴이 그대로 보입니다. 실제로 세션 초반 `-t` 없이 호출한
`balance` 는 성공했습니다.

### 3. YouTube 인증 (업로드용)

Google Cloud Console → **YouTube Data API v3 사용 설정** →
사용자 인증 정보 → **데스크톱 앱** OAuth 클라이언트 생성 → JSON 다운로드

| 경로 | 저장 위치 |
|---|---|
| WSL2 | `~/.hermes/secrets/youtube_client_secret.json` |
| 네이티브 | `%LOCALAPPDATA%\hermes\secrets\youtube_client_secret.json` |

```bash
python <스크립트경로>/youtube_upload.py auth
```

### 4. 벤치마크 채널 분석용 API 키 (읽기 전용)

위 OAuth와 **별개**입니다. 같은 프로젝트에서 사용자 인증 정보 → **API 키** →
API 제한사항에서 `YouTube Data API v3` 하나만 선택.

**키는 파일에 한 번만 넣어두면 됩니다.** 명령창에 매번 입력할 필요 없습니다.

```powershell
python analyze_reference.py --setup
```

메모장이 열립니다. 키를 붙여넣고 저장하면 끝입니다. 이후로는 그냥 실행하면 됩니다:

```powershell
python analyze_reference.py --handle "@진짜잠깐만" --calibrate
```

키 파일 위치:

| 경로 | 위치 |
|---|---|
| 네이티브 Windows | `%LOCALAPPDATA%\hermes\secrets\youtube_api_key.txt` |
| WSL2 | `~/.hermes/secrets/youtube_api_key.txt` |

메모장이 남기는 BOM·따옴표·`YOUTUBE_API_KEY=` 접두사는 스크립트가 알아서 걷어냅니다.
`#` 으로 시작하는 줄은 주석으로 무시합니다.

> 이 파일은 `.gitignore` 에 걸려 있어 저장소에 올라가지 않습니다.
> 환경변수 `YOUTUBE_API_KEY` 를 쓰면 파일보다 우선합니다.

### 5. 점검

**`--style` 을 꼭 붙이세요.** 없으면 폰트를 검사하지 않습니다.

```bash
python <스크립트경로>/compose_short.py check --style <reference-style.yaml 경로>
```

`ffmpeg` / `ffprobe` / `edge-tts` / `폰트` 네 줄이 모두 OK 면 준비 끝입니다.
하나라도 실패하면 종료 코드가 1 이라 스크립트로도 판단할 수 있습니다.

폰트 검사는 Windows 에서 **레지스트리의 패밀리명**을 읽습니다.
파일명이 아니라 실제 패밀리명이라 `malgun.ttf` → `Malgun Gothic` 으로 잡히고,
사용자 폴더(`%LOCALAPPDATA%\Microsoft\Windows\Fonts`)에 설치한 폰트와
`.otf` 폰트도 인식합니다. Pretendard 는 OTF 로 배포되고 보통 사용자 폴더에
설치되므로 이 둘이 다 필요합니다.

---

## Windows에서 자주 걸리는 것

| 증상 | 원인 | 해결 |
|---|---|---|
| `bad interpreter: /bin/bash^M` | CRLF 줄바꿈 | `sed -i 's/\r$//' 파일명` |
| 자막이 네모(□)로 나옴 | 한글 폰트 없음 | `sudo apt install fonts-noto-cjk` |
| 자막이 밋밋한 기본 폰트 | `font_family` 이름 불일치 | `compose_short.py` 경고 메시지가 알려주는 이름으로 교체 |
| `ffmpeg: command not found` | PATH 미반영 | 새 터미널을 열 것 |
| OAuth 창이 안 뜸 (WSL2) | 브라우저 없음 | `sudo apt install wslu` 또는 URL 수동 복사 |
| `hermes` 명령을 못 찾음 | 셸 재시작 필요 | 터미널을 새로 열거나 `source ~/.bashrc` |
