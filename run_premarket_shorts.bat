@echo off
chcp 65001 >nul
title [08:50 장전 긴급 숏츠] 넥스트레이드 프리마켓 & 시초가 갭 자동 제작 및 배포

echo ======================================================================
echo   🚨 [08:50 긴급 숏츠] 넥스트레이드 프리마켓 & 시초가 갭 숏츠 파이프라인
echo ======================================================================
echo.
echo [1] 키움 REST API 실시간 NXT 프리마켓 & 시초가 갭 수급 수집
echo [2] 1440x2560 QHD 다크모드 긴급 인포그래픽 렌더링
echo [3] 45초 카운트다운 고긴장 스토리텔링 & Edge-TTS 음성 합성
echo [4] FFmpeg 60FPS QHD 고화질 쇼츠 영상 렌더링
echo [5] 스마트폰 텔레그램 즉시 발송
echo [6] 유튜브 쇼츠 100%% 무인 자동 업로드
echo.
echo ======================================================================
echo   제작 및 업로드를 시작합니다. 잠시만 기다려 주세요...
echo ======================================================================
echo.

cd /d "%~dp0."
if not exist "execution\build_premarket_shorts.py" (
    cd /d "C:\Users\zoela\OneDrive\바탕 화면\PythonWorksplace"
)

".venv\Scripts\python.exe" "execution\build_premarket_shorts.py" --upload --privacy public

echo.
echo ======================================================================
echo   제작 및 유튜브 자동 업로드가 완료되었습니다!
echo   D:\DailyQuant\PreMarket_Urgent_Shorts.mp4
echo ======================================================================
echo.
pause
