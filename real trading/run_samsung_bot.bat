@echo off
chcp 65001 > nul
title Samsung Dedicated Auto Trading Bot
cd /d "%~dp0"
echo =======================================================
echo Samsung Bot Started.
echo Strategy: BB5 Lower touch + RSI 70 crossup
echo =======================================================
"C:\Users\zoela\AppData\Local\Programs\Python\Python312\python.exe" samsung_bot.py
pause
