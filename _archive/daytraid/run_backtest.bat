@echo off
title Daytraid Backtesting Simulator
cd /d "%~dp0"
echo =======================================================
echo 키움증권 36개 종목 과거 데이터 기반 백테스트를 시작합니다.
echo 일봉 K/L선 돌파 + 15분봉 데드크로스 로직 시뮬레이션
echo =======================================================
"C:\Users\zoela\AppData\Local\Programs\Python\Python313-32\python.exe" backtest.py
pause
