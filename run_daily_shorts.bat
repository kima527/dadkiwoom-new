@echo off
chcp 65001 >nul
title [모닝 퀀트] 유튜브 쇼츠 자동 제작 및 배포

echo ======================================================================
echo   [모닝 퀀트] 유튜브 쇼츠 및 인스타 릴스 원클릭 자동 제작기
echo ======================================================================
echo.
echo [1] 미국/국내 증시 데이터 및 핵심 뉴스 크롤링
echo [2] 바이럴 훅 커버페이지(1080x1920) 생성
echo [3] 고대비 다크모드 차트 및 지표 인포그래픽 렌더링
echo [4] AI 신경망 내레이션 음성 합성 (49초 쇼츠 최적화)
echo [5] FFmpeg 60FPS 모션 안정화 및 비디오 합성
echo [6] 유튜브 쇼츠 및 인스타그램 릴스 자동 배포
echo.
echo ======================================================================
echo   제작을 시작합니다. 잠시만 기다려 주세요...
echo ======================================================================
echo.

cd /d "%~dp0."
if not exist "execution\build_daily_shorts.py" (
    cd /d "C:\Users\zoela\OneDrive\바탕 화면\PythonWorksplace"
)

if exist ".venv\Scripts\python.exe" (
    ".venv\Scripts\python.exe" "execution\build_daily_shorts.py" --upload
) else (
    "C:\Users\zoela\OneDrive\바탕 화면\PythonWorksplace\.venv\Scripts\python.exe" "C:\Users\zoela\OneDrive\바탕 화면\PythonWorksplace\execution\build_daily_shorts.py" --upload
)

echo.
echo ======================================================================
echo   제작이 완료되었습니다! D:\DailyQuant 폴더에서 영상을 확인하세요.
echo ======================================================================
echo.
pause
