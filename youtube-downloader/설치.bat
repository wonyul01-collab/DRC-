@echo off
chcp 65001 >nul
title 영상 다운로더 v2 설치
setlocal

set "TARGET=%USERPROFILE%\영상다운로더"
set "SRC=%~dp0"

echo.
echo   영상 다운로더 v2 설치
echo   ========================================
echo.
echo   기존 폴더에 덮어씁니다. 바탕화면 바로가기는 그대로 씁니다.
echo.
echo     설치 위치 : %TARGET%
echo.

if not exist "%TARGET%" (
    echo   [!] 폴더가 없습니다: %TARGET%
    echo       기존 프로그램 폴더 경로가 다르면 이 파일을 열어 TARGET 을 고치세요.
    echo.
    pause
    exit /b 1
)

set /p GO="계속할까요? (Y/N): "
if /i not "%GO%"=="Y" (
    echo   취소했습니다.
    pause
    exit /b 0
)
echo.

rem --- 기존 app.py 백업 ---
if exist "%TARGET%\app.py" (
    copy /y "%TARGET%\app.py" "%TARGET%\app.py.v1백업" >nul
    echo   기존 app.py 를 app.py.v1백업 으로 저장했습니다.
)

rem --- v2 파일 복사 ---
copy /y "%SRC%app.py"                "%TARGET%\" >nul
copy /y "%SRC%youtube_downloader.py" "%TARGET%\" >nul
copy /y "%SRC%ytdl_core.py"          "%TARGET%\" >nul
copy /y "%SRC%ytdl.py"               "%TARGET%\" >nul
copy /y "%SRC%업데이트.bat"          "%TARGET%\" >nul
copy /y "%SRC%문제진단.bat"          "%TARGET%\" >nul
copy /y "%SRC%README.md"             "%TARGET%\" >nul
echo   프로그램 파일을 복사했습니다.
echo.

rem --- 기존 venv 에 yt-dlp 최신화 ---
if exist "%TARGET%\.venv\Scripts\python.exe" (
    echo   yt-dlp 를 최신으로 올립니다. 잠시 걸립니다...
    "%TARGET%\.venv\Scripts\python.exe" -m pip install --upgrade --pre yt-dlp --quiet
    "%TARGET%\.venv\Scripts\python.exe" -m yt_dlp --rm-cache-dir >nul 2>&1
    echo   완료.
    echo.
    echo   현재 상태:
    "%TARGET%\.venv\Scripts\python.exe" "%TARGET%\ytdl.py" --check
) else (
    echo   [!] 기존 가상환경(.venv)이 없습니다. 새로 만듭니다...
    python -m venv "%TARGET%\.venv"
    "%TARGET%\.venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
    "%TARGET%\.venv\Scripts\python.exe" -m pip install --upgrade --pre yt-dlp --quiet
    echo   완료.
)

echo.
echo   ========================================
echo   설치 끝. 바탕화면 바로가기를 그대로 누르면 v2 가 뜹니다.
echo   ========================================
echo.
pause
