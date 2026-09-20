@echo off
chcp 65001 >nul
title Video Downloader Setup
cd /d "%~dp0"

set "PY="
where py >nul 2>&1 && set "PY=py"
if not defined PY where python >nul 2>&1 && set "PY=python"

if not defined PY (
    echo.
    echo   [!] Python is not installed.
    echo.
    echo   Copy the line below, paste it here, and press Enter:
    echo.
    echo       winget install Python.Python.3.12
    echo.
    echo   After it finishes, close this window and
    echo   double-click this file again.
    echo.
    pause
    exit /b 1
)

%PY% install.py
