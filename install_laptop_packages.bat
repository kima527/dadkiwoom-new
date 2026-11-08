@echo off
chcp 65001 >nul
echo ===============================================================================
echo   📦 [노트북 최초 1회] 성배 로직 가상매매 감시용 필수 파이썬 패키지 설치
echo ===============================================================================
python -m pip install --upgrade pip
pip install pandas numpy requests httpx python-dotenv kiwoom-rest-api
echo.
echo ✅ 설치가 완료되었습니다! 이제 holdings_bot_laptop_dryrun.bat 을 실행하세요.
pause
