@echo off
chcp 65001 > nul
title Samsung Dedicated Auto Trading Bot
cd /d "%~dp0"
echo =======================================================
echo Samsung Bot Started.
echo Strategy: 120-tick SMA 40/60 Scalping (Multi-trade)
echo =======================================================
"C:\Users\zoela\AppData\Local\Programs\Python\Python312\python.exe" samsung_bot.py
pause
