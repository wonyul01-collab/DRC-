@echo off
chcp 65001 >nul
title yt-dlp Update
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo   [!] Not installed here yet.
    echo       Run the setup file first.
    echo.
    pause
    exit /b 1
)

echo.
echo   Updating yt-dlp to the latest build...
echo.
".venv\Scripts\python.exe" -m pip install --upgrade --pre yt-dlp --disable-pip-version-check
".venv\Scripts\python.exe" -m yt_dlp --rm-cache-dir >nul 2>&1
echo.
".venv\Scripts\python.exe" ytdl.py --check
echo.
pause
