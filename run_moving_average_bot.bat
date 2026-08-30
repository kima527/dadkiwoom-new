@echo off
chcp 65001 >nul
echo ===================================================
echo   [실전 자동매매] 이평선 돌파 + 15분봉 추세 매매 봇
echo ===================================================
echo.
echo [매수] 일봉 20이평 돌파 & HH / 30분봉 260이평 돌파 & HH
echo [매도] 15분봉 5-40 이평 데드크로스 전량 청산
echo [방어] 코스피/코스닥 지수 급락 시 매수 자동 일시정지
echo.
python -X utf8 "MovingAveragelineTraid\execution\trading_bot.py"
pause
