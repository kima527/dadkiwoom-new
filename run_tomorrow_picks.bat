@echo off
chcp 65001 >nul
echo =========================================================
echo       [종가 스캔] 내일의 주도주 / 돌파 임박 종목 자동 추출
echo =========================================================
echo  - 30분봉 260이평 W자 반등 종목
echo  - 일봉 20이평선 상향 돌파 임박 종목
echo  - 30분봉 3일선-5일선 골든크로스 수렴 종목
echo  - 가중 5-20 고가선(HH) 돌파 사정권 종목
echo =========================================================
echo.

cd /d "C:\Users\zoela\OneDrive\바탕 화면\PythonWorksplace"
python -X utf8 "MovingAveragelineTraid\execution\scan_tomorrow_picks.py"

echo.
echo [알림] 스캔이 완료되었습니다!
echo 내일 아침 09:00에 run_moving_average_bot.bat을 실행하면 이 종목들이 최우선 매수 감시됩니다.
echo.
timeout /t 10
