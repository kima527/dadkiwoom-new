@echo off
chcp 65001 >nul
echo ===================================================
echo   [장전 테마 브리핑] 오늘의 주도 테마 및 대장주 발굴
echo ===================================================
echo.
echo [1] 상위 핫 테마 및 거래대금 1위 대장주 자동 색출
echo [2] 실시간 뉴스 모멘텀 AI 및 금융 NLP 채점
echo [3] 치명적 악재(CB/횡령/유증) 종목 원천 차단
echo [4] 봇 감시 워치리스트(watchlist.json) 가중치 자동 동기화
echo.
python -X utf8 "MovingAveragelineTraid\execution\premarket_scanner.py"
echo.
pause
