@echo off
title Daytraid Auto Trading Bot (15분봉 눌림목 전략)
cd /d "%~dp0"
echo =======================================================
echo 키움증권 실시간 자동매매 봇을 시작합니다.
echo 전략: 15분봉 SMA3/40 + K선 -3%% 눌림목 매수
echo =======================================================
"C:\Users\zoela\AppData\Local\Programs\Python\Python313-32\python.exe" main.py
pause
