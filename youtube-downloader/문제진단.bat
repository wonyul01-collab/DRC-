@echo off
chcp 65001 >nul
title Diagnose
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
set /p URL="Video URL (press Enter to check environment only): "
echo.
if "%URL%"=="" (
    ".venv\Scripts\python.exe" ytdl.py --check
) else (
    ".venv\Scripts\python.exe" ytdl.py --check "%URL%"
)
echo.
pause
