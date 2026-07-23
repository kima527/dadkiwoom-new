@echo off
chcp 65001
echo =========================================================
echo       [종가 스캔] 내일의 주도주 자동 추출 시스템
echo =========================================================
echo 거래대금 상위 200종목 중 "최근 20일 내 20%% 이상 급등" 이력이 있는
echo 1조원 미만의 중소형주만 엄선하여 관심종목으로 저장합니다.
echo.

cd /d "C:\Users\zoela\OneDrive\바탕 화면\MovingAveragelineTraid"
call "C:\Users\zoela\OneDrive\바탕 화면\PythonWorksplace\.venv\Scripts\activate.bat"

python extract_tomorrow_picks.py

echo.
echo 스캔이 완료되었습니다! 
echo 이제 내일 아침 run_watchlist_bot.bat을 실행하시면 됩니다.
pause
