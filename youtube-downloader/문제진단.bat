@echo off
chcp 65001 >nul
title 문제 진단
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo   [!] 먼저 실행.bat 을 한 번 실행하세요.
    pause
    exit /b 1
)

echo.
set /p URL="진단할 영상 주소 (그냥 Enter 치면 환경만 점검): "
echo.

if "%URL%"=="" (
    ".venv\Scripts\python.exe" ytdl.py --check
) else (
    ".venv\Scripts\python.exe" ytdl.py --check "%URL%"
)
echo.
pause
