@echo off
chcp 65001 >nul
echo ===================================================
echo   이평선 + 돌파매매 봇 (MovingAverage + Breakout Bot)
echo ===================================================
echo.
echo [안내] 실시간 조건검색에서 포착된 종목만을 대상으로 합니다.
echo [안내] 초기 5분봉 고점 돌파 및 3-10 골든크로스 로직이 적용됩니다.
echo.
python "MovingAveragelineTraid\execution\trading_bot.py"
pause
