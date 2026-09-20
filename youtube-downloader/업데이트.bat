@echo off
chcp 65001 >nul
title yt-dlp 업데이트
cd /d "%~dp0"

echo.
echo   yt-dlp 를 최신 나이틀리로 올립니다.
echo   403 오류는 대부분 이것으로 해결됩니다.
echo   ----------------------------------------
echo.

if not exist ".venv\Scripts\python.exe" (
    echo   [!] 먼저 실행.bat 을 한 번 실행하세요.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m pip install --upgrade --pre yt-dlp
echo.

echo   캐시를 비웁니다...
".venv\Scripts\python.exe" -m yt_dlp --rm-cache-dir
echo.

echo   현재 상태:
".venv\Scripts\python.exe" ytdl.py --check
echo.
pause
