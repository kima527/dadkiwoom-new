@echo off
chcp 65001 > nul
set PYTHONIOENCODING=utf-8
title AI 500만원 주식 굴리기 챌린지 쇼츠 자동 제작 및 업로드

echo ======================================================================
echo 🤖 [AI 500만원 주식 굴리기 챌린지] 무인 자동 제작 및 유튜브 업로드 시작
echo ======================================================================
echo.

cd /d "%~dp0"
call .venv\Scripts\activate.bat

python execution\build_virtual_challenge_shorts.py --upload --privacy public

if errorlevel 1 (
    echo.
    echo ❌ [오류 발생] 쇼츠 제작 또는 업로드 도중 문제가 발생했습니다.
    pause
    exit /b 1
)

echo.
echo ======================================================================
echo 🎉 [성공] AI 500만원 챌린지 쇼츠 제작 및 유튜브 업로드가 완료되었습니다!
echo ======================================================================
timeout /t 5
