@echo off
title 주도주 종가매매 봇 (Theme EOD Bot)
echo ========================================================
echo        [AI 주도주 종가매매 봇 실행 중]
echo.
echo - 오후 2시 45분: 대장주 스캔 및 종가매수 대기
echo - 익일 오전 9시 5분: 목표가/손절가 달성 시 청산
echo ========================================================
echo.

cd /d "%~dp0"
python theme_eod_bot.py

pause
