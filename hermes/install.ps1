# Hermes 유튜브 파이프라인 설치 — 네이티브 Windows 용
#
#   powershell -ExecutionPolicy Bypass -File hermes\install.ps1
#
# WSL2 에 Hermes 를 설치하셨다면 이 파일이 아니라 install.sh 를 쓰세요.
#   wsl bash hermes/install.sh
#
# config.yaml 은 자동으로 건드리지 않습니다. 기존 설정을 깨뜨릴 수 있어서
# 병합은 사람이 직접 합니다. 이 스크립트는 스킬·스크립트·작업폴더만 배치합니다.

$ErrorActionPreference = 'Stop'
$OutputEncoding = [System.Text.Encoding]::UTF8

$HermesHome = if ($env:HERMES_HOME) { $env:HERMES_HOME } else { Join-Path $env:LOCALAPPDATA 'hermes' }
$Workspace  = Join-Path $HermesHome 'workspace\youtube'
$Src        = $PSScriptRoot

if (-not (Test-Path $HermesHome)) {
    Write-Error @"
$HermesHome 가 없습니다. 네이티브 Windows 에 Hermes 가 설치되어 있는지 확인하세요.

WSL2 에 설치하셨다면 이 스크립트가 아니라 아래를 실행하세요:
    wsl bash hermes/install.sh

설치 위치를 직접 지정하려면:
    `$env:HERMES_HOME = 'C:\path\to\.hermes'; .\hermes\install.ps1
"@
}

Write-Host "==> 스킬 설치: $HermesHome\skills\"
$SkillsDir = Join-Path $HermesHome 'skills'
New-Item -ItemType Directory -Force -Path $SkillsDir | Out-Null
Get-ChildItem -Path (Join-Path $Src 'skills') -Directory | ForEach-Object {
    $target = Join-Path $SkillsDir $_.Name
    if (Test-Path $target) {
        $backup = "$target.bak"
        if (Test-Path $backup) { Remove-Item $backup -Recurse -Force }
        Move-Item $target $backup
        Write-Host "    이미 있음, 덮어씀: $($_.Name) (기존은 $($_.Name).bak 로 백업)"
    }
    Copy-Item $_.FullName $target -Recurse
    Write-Host "    설치됨: $($_.Name)"
}

Write-Host "==> 스크립트 설치: $Workspace\scripts\"
$ScriptsDir = Join-Path $Workspace 'scripts'
New-Item -ItemType Directory -Force -Path $ScriptsDir | Out-Null
Copy-Item (Join-Path $Src 'scripts\*.py') $ScriptsDir -Force
Copy-Item (Join-Path $Src 'scripts\requirements.txt') $ScriptsDir -Force

Write-Host "==> 작업 폴더 생성"
'plans','scripts','video','video\raw','desc','reviews' | ForEach-Object {
    New-Item -ItemType Directory -Force -Path (Join-Path $Workspace "out\$_") | Out-Null
}
New-Item -ItemType Directory -Force -Path (Join-Path $HermesHome 'secrets') | Out-Null

# 채널 브리프. $env:BRIEF 로 준비된 초안을 고를 수 있습니다.
#   $env:BRIEF = 'health-simulation'
$Brief = Join-Path $Workspace 'channel-brief.yaml'
if (-not (Test-Path $Brief)) {
    $BriefSrc = if ($env:BRIEF) { Join-Path $Src "content\briefs\$($env:BRIEF).yaml" } else { $null }
    if ($BriefSrc -and (Test-Path $BriefSrc)) {
        Copy-Item $BriefSrc $Brief
        Write-Host "    브리프 적용: $($env:BRIEF) -> $Brief"
    } else {
        Copy-Item (Join-Path $Src 'content\channel-brief.example.yaml') $Brief
        Write-Host "    빈 템플릿 생성: $Brief"
    }
} else {
    Write-Host "    이미 있음, 건드리지 않음: channel-brief.yaml"
}

# 벤치마크 스타일. $env:STYLE 로 다른 채널 스타일을 고를 수 있습니다.
$StyleName = if ($env:STYLE) { $env:STYLE } else { 'jinjja-jamkkanman' }
$StyleDest = Join-Path $Workspace 'reference-style.yaml'
if (-not (Test-Path $StyleDest)) {
    $StyleSrc = Join-Path $Src "content\styles\$StyleName.yaml"
    if (Test-Path $StyleSrc) {
        Copy-Item $StyleSrc $StyleDest
        Write-Host "    스타일 적용: $StyleName -> $StyleDest"
    } else {
        Copy-Item (Join-Path $Src 'content\reference-style.example.yaml') $StyleDest
        Write-Host "    빈 템플릿 생성 ($StyleName 없음): $StyleDest"
    }
} else {
    Write-Host "    이미 있음, 건드리지 않음: reference-style.yaml"
}

Write-Host "==> Python 의존성 설치"
$reqs = Join-Path $ScriptsDir 'requirements.txt'
try {
    python -m pip install -r $reqs
} catch {
    Write-Warning "자동 설치 실패. 직접 실행하세요: python -m pip install -r `"$reqs`""
}

Write-Host "==> 영상 합성 도구 확인"
if (Get-Command ffmpeg -ErrorAction SilentlyContinue) {
    Write-Host "    ffmpeg OK"
} else {
    Write-Warning "ffmpeg 가 없습니다. 자막·나레이션 합성이 안 됩니다."
    Write-Host   "      설치: winget install --id Gyan.FFmpeg" -ForegroundColor Yellow
    Write-Host   "      설치 후 새 터미널을 열어야 PATH 가 잡힙니다." -ForegroundColor Yellow
}

# 폰트는 compose_short.py 가 레지스트리까지 읽어 정확히 판정합니다.
# 여기서는 스타일 파일 기준으로 그 검사를 그대로 한 번 돌립니다.
$fontCheck = & python (Join-Path $ScriptsDir 'compose_short.py') check --style $StyleDest 2>&1
$fontLine = $fontCheck | Where-Object { $_ -match '^폰트' }
if ($fontLine) { Write-Host "    $fontLine" }
if ($fontCheck -match "찾지 못했습니다") {
    Write-Warning "자막 폰트가 없습니다. 아래 중 하나로 해결하세요."
    Write-Host "      1) Pretendard 설치: https://github.com/orioncactus/pretendard/releases" -ForegroundColor Yellow
    Write-Host "      2) $StyleDest 의 subtitle.font_family 를 'Malgun Gothic' 으로 변경" -ForegroundColor Yellow
}

@"

설치 완료. 남은 일은 사람이 해야 합니다:

  1. $HermesHome\config.yaml 에 hermes\config.snippet.yaml 내용을 병합
     (mcp_servers / skills.config / cron 블록. 파일 전체를 덮어쓰지 마세요.)

  2. Higgsfield 인증 (구글 로그인 창이 브라우저에 뜹니다)
       hermes mcp login higgsfield
       # "Authenticated - N tool(s) available" 이 뜨면 성공입니다.
       # 주의: hermes tools / hermes mcp configure 는 조회가 아니라 대화형
       #       선택 UI 입니다. 확인 목적으로 실행하면 config.yaml 이 덮어써집니다.

  3. YouTube 인증
       # 데스크톱 앱 OAuth JSON 을 $HermesHome\secrets\youtube_client_secret.json 로 저장 후:
       python $ScriptsDir\youtube_upload.py auth

  4. 채널 브리프 작성
       notepad $Brief

  5. 합성 도구 점검
       python $ScriptsDir\compose_short.py check --style $StyleDest

  6. 예약 작업 등록: hermes\cron\jobs.md 참고
"@ | Write-Host
