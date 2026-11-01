@echo off
chcp 65001 >nul
echo ========================================================
echo   🛡️ [모의 안전 모드(DRY-RUN)] 60분봉 집중 매매 봇
echo   (실시간 시세/신호 감시는 정상 작동하며, 실제 주문만 차단됩니다)
echo ========================================================
echo.
python -X utf8 "execution\trading_bot_holdings_only.py" --dry-run
pause

