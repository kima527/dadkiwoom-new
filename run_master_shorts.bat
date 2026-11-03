@echo off
chcp 65001 >nul
title [통합 관리] 유튜브 쇼츠 퀀트 자동화 시스템

:MENU
cls
echo ======================================================================
echo   🎬 [통합 관리] 유튜브 쇼츠 자동 제작 & 업로드 마스터 시스템
echo ======================================================================
echo.
echo   [현재 윈도우 작업 스케줄러 등록 상태: 자동 가동 중]
echo    - 1차 모닝 퀀트 쇼츠    : 매일 아침 07:00 자동 제작 및 유튜브 업로드
echo    - 2차 프리마켓 긴급 쇼츠 : 매일 아침 08:50 자동 제작 및 유튜브 업로드
echo.
echo ======================================================================
echo   [수동 즉시 실행 메뉴]
echo ======================================================================
echo   [1] 07:00 모닝 퀀트 쇼츠 지금 즉시 제작 및 유튜브 업로드
echo   [2] 08:50 프리마켓 긴급 쇼츠 지금 즉시 제작 및 유튜브 업로드
echo   [3] 두 영상 연속으로 모두 즉시 제작 및 업로드
echo   [4] 윈도우 스케줄러 등록 상태 확인
echo   [5] 종료
echo ======================================================================
set /p choice="실행할 번호를 입력하세요 (1-5): "

if "%choice%"=="1" goto MORNING
if "%choice%"=="2" goto PREMARKET
if "%choice%"=="3" goto ALL
if "%choice%"=="4" goto STATUS
if "%choice%"=="5" goto EXIT
goto MENU

:MORNING
cls
echo 🚀 07:00 모닝 퀀트 쇼츠 제작 및 업로드를 시작합니다...
cd /d "C:\Users\zoela\OneDrive\바탕 화면\PythonWorksplace"
call run_daily_shorts.bat
pause
goto MENU

:PREMARKET
cls
echo 🚨 08:50 프리마켓 긴급 쇼츠 제작 및 업로드를 시작합니다...
cd /d "C:\Users\zoela\OneDrive\바탕 화면\PythonWorksplace"
call run_premarket_shorts.bat
pause
goto MENU

:ALL
cls
echo 🎬 두 영상 연속 자동 제작 및 업로드를 시작합니다...
cd /d "C:\Users\zoela\OneDrive\바탕 화면\PythonWorksplace"
echo.
echo [단계 1] 07:00 모닝 퀀트 쇼츠 가동...
call run_daily_shorts.bat
echo.
echo [단계 2] 08:50 프리마켓 긴급 쇼츠 가동...
call run_premarket_shorts.bat
echo.
echo ✅ 두 영상 모두 성공적으로 완료되었습니다!
pause
goto MENU

:STATUS
cls
echo ⏰ 윈도우 작업 스케줄러 등록 현황:
powershell -Command "Get-ScheduledTask -TaskName 'DailyQuant*' | Select-Object TaskName, State"
pause
goto MENU

:EXIT
exit
