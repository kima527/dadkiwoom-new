@echo off
chcp 65001 > nul
title AI Auto Trading System (Picker + Bot)
cd /d "%~dp0"
echo =======================================================
echo 1. Running Daily Stock Picker...
echo =======================================================
"C:\Users\zoela\AppData\Local\Programs\Python\Python312\python.exe" daily_picker.py

echo =======================================================
echo 2. Starting Basket Trading Bot...
echo =======================================================
"C:\Users\zoela\AppData\Local\Programs\Python\Python312\python.exe" multi_bot.py

pause
