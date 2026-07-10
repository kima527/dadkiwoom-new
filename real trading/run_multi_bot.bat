@echo off
chcp 65001 > nul
title Morning-Exclusive Auto Trading Bot
cd /d "%~dp0"
echo =======================================================
echo Morning-Exclusive AI Bot Started.
echo Strategy: AI 5m 단타 (MACD+BB+RSI) + Time Stop (11:30)
echo =======================================================
"C:\Users\zoela\AppData\Local\Programs\Python\Python312\python.exe" multi_bot.py
pause
