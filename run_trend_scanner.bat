@echo off
chcp 65001 >nul
echo ===================================================
echo   전종목 추세 스캐너 (Trend Scanner)
echo ===================================================
echo.
echo [안내] 당일 거래대금 상위 200개 종목을 스캔하여 추세가 살아있는 종목을 찾습니다.
echo [안내] ETF/ETN 등은 자동으로 제외됩니다.
echo.
python "real trading\do_pre_learn_script.py"
pause
