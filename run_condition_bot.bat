@echo off
chcp 65001 >nul
echo ===================================================
echo   실시간 조건검색 스캘핑 봇 (Condition Bot)
echo ===================================================
echo.
echo [안내] 키움증권 조건검색식에서 포착되는 종목을 실시간 스캘핑합니다.
echo [안내] 종목 포착 시 백그라운드에서 추세를 즉각 분석하여 방어합니다.
echo.
python "real trading\main_condition_scalper.py"
pause
