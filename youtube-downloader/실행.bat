@echo off
chcp 65001 >nul
title 영상 다운로더
cd /d "%~dp0"

echo.
echo   영상 다운로더 v2.0
echo   ----------------------------------------
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo   [!] 파이썬이 설치돼 있지 않습니다.
    echo.
    echo       아래 명령으로 설치한 뒤 다시 실행하세요:
    echo         winget install Python.Python.3.12
    echo.
    pause
    exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
    echo   처음 실행이라 준비를 좀 하겠습니다. 1~2분 걸립니다.
    echo.
    python -m venv .venv
    if errorlevel 1 (
        echo   [!] 가상환경을 만들지 못했습니다.
        pause
        exit /b 1
    )
    ".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
    echo   yt-dlp 설치 중...
    ".venv\Scripts\python.exe" -m pip install --upgrade --pre yt-dlp --quiet
    echo   준비 끝.
    echo.
)

".venv\Scripts\python.exe" youtube_downloader.py
if errorlevel 1 (
    echo.
    echo   [!] 오류가 났습니다. 위 메시지를 확인하세요.
    pause
)
