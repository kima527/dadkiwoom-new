@echo off
chcp 65001 >nul
echo ===================================================
echo   관심종목 기반 1분봉 자동매매 봇 (Watchlist Bot)
echo ===================================================
echo.
echo [안내] MovingAveragelineTraid\watchlist.json 파일을 기반으로 매매를 시작합니다.
echo [안내] 시작 전 추세 판단 에이전트가 일봉 추세를 사전 학습합니다.
echo.
python "MovingAveragelineTraid\execution\trading_bot.py"
pause
