@echo off
chcp 65001 >nul
cd /d "%~dp0"
set TARGET_DIR=E:\HolyGrail_Bot

echo ===============================================================================
echo   🚀 [E:/ 드라이브 자동 패키징] 유튜브 파일 제외 · 순수 성배 로직 가상매매 감시팩 추출
echo   대상 경로: %TARGET_DIR%
echo ===============================================================================
echo.

if not exist "E:\" (
    echo ❌ [오류] 현재 E:\ 드라이브가 연결되어 있지 않습니다. USB/외장하드(E:)를 연결한 후 다시 실행해 주세요.
    pause
    exit /b 1
)

mkdir "%TARGET_DIR%" 2>nul
mkdir "%TARGET_DIR%\execution" 2>nul
mkdir "%TARGET_DIR%\MovingAveragelineTraid\execution" 2>nul
mkdir "%TARGET_DIR%\real trading" 2>nul

echo [1/4] 노트북 전용 가상매매 감시 실행 파일 복사 중...
copy /Y "holdings_bot_laptop_dryrun.bat" "%TARGET_DIR%\" >nul
copy /Y "install_laptop_packages.bat" "%TARGET_DIR%\" >nul

echo [2/4] 성배 로직 핵심 엔진(execution) 7개 파일만 선별 복사 중 (유튜브 관련 파일 100%% 제외)...
copy /Y "execution\trading_bot_holdings_only.py" "%TARGET_DIR%\execution\" >nul
copy /Y "execution\strategy.py" "%TARGET_DIR%\execution\" >nul
copy /Y "execution\indicators.py" "%TARGET_DIR%\execution\" >nul
copy /Y "execution\watchlist_scanner.py" "%TARGET_DIR%\execution\" >nul
copy /Y "execution\config.py" "%TARGET_DIR%\execution\" >nul
if exist "execution\holy_grail_watchlist.json" copy /Y "execution\holy_grail_watchlist.json" "%TARGET_DIR%\execution\" >nul
if exist "execution\generate_sample_data.py" copy /Y "execution\generate_sample_data.py" "%TARGET_DIR%\execution\" >nul

echo [3/4] 키움 실전 차트/선물지수 수신 어댑터 복사 중...
copy /Y "MovingAveragelineTraid\execution\real_api_adapter.py" "%TARGET_DIR%\MovingAveragelineTraid\execution\" >nul

echo [4/4] 키움 REST API 필수 모듈(config.py, kiwoom_client.py, .env) 선별 복사 중...
copy /Y "real trading\config.py" "%TARGET_DIR%\real trading\" >nul
copy /Y "real trading\kiwoom_client.py" "%TARGET_DIR%\real trading\" >nul
copy /Y "real trading\.env" "%TARGET_DIR%\real trading\" >nul
if exist "real trading\target_pick.csv" copy /Y "real trading\target_pick.csv" "%TARGET_DIR%\real trading\" >nul

echo.
echo ===============================================================================
echo ✅ [추출 완료!] %TARGET_DIR% 폴더에 순수 성배 로직 가상매매 감시팩이 생성되었습니다!
echo    - 유튜브 관련 파일은 단 1개도 포함되지 않았습니다.
echo    - 노트북으로 옮기신 후:
echo      1) 최초 1회: install_laptop_packages.bat 더블클릭
echo      2) 평상시:   holdings_bot_laptop_dryrun.bat 더블클릭 (실제 주문 0%% 가상매매 감시)
echo ===============================================================================
pause
