@echo off
chcp 65001 >nul
title [모닝 퀀트] 롱폼 1편 자동 제작기 - 골든크로스 10년 팩트체크

echo ======================================================================
echo   [모닝 퀀트] 16:9 롱폼 1편 원클릭 전자동 제작 엔진 가동
echo   주제: 골든크로스 10년간 믿고 샀더니 계좌가 반토막 난 이유
echo ======================================================================
echo.
echo [1] 코스피 200 10개년(2014~2024) 전수조사 백테스트 연산
echo [2] 16:9 고반응 썸네일(커버페이지) 렌더링
echo [3] 7개 챕터 16:9 와이드스크린 슬라이드 렌더링
echo [4] AI 신경망 전문 퀀트 내레이션 음성 합성 (5분 풀버전)
echo [5] FFmpeg 1080p 30FPS 비디오 합성 및 썸네일 아트워크 내장
echo.
echo ======================================================================
echo   제작을 시작합니다. 잠시만 기다려 주세요...
echo ======================================================================
echo.

cd /d "%~dp0."
if not exist "execution\build_longform_ep1.py" (
    cd /d "C:\Users\zoela\OneDrive\바탕 화면\PythonWorksplace"
)

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "execution\build_longform_ep1.py"
) else (
    "C:\Users\zoela\OneDrive\바탕 화면\PythonWorksplace\.venv\Scripts\python.exe" "C:\Users\zoela\OneDrive\바탕 화면\PythonWorksplace\execution\build_longform_ep1.py"
)

echo.
echo ======================================================================
echo   제작이 완료되었습니다! D:\DailyQuant 폴더에서 영상을 확인하세요.
echo ======================================================================
echo.
pause
