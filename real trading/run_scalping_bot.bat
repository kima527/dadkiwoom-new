@echo off
title HFT Multi-Agent Scalping Bot
cd /d "%~dp0"
echo =======================================================
echo   HFT Multi-Agent Consensus Scalping Bot
echo   Strategy: Tick Acceleration + Theme Consensus
echo   WARNING: 1 share per trade (test mode)
echo =======================================================
echo.
echo [%date% %time%] Bot starting...
echo.
"C:\Users\zoela\AppData\Local\Programs\Python\Python312\python.exe" main_scalping.py
pause
