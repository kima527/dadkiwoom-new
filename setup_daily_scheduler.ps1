# Windows 작업 스케줄러 등록 스크립트: 매일 20:00 자동 실행
$TaskName = "Kiwoom_ScanTomorrowPicks"
$BatPath = "C:\Users\zoela\OneDrive\바탕 화면\PythonWorksplace\run_tomorrow_picks.bat"

Write-Host "=========================================================" -ForegroundColor Cyan
Write-Host " ⏰ 매일 20:00 [내일의 주도주 자동 스캐너] 작업 스케줄러 등록" -ForegroundColor Cyan
Write-Host "=========================================================" -ForegroundColor Cyan

# 기존 작업이 있으면 삭제
Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue

$Action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$BatPath`""
$Trigger = New-ScheduledTaskTrigger -Daily -At "20:00"
$Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

try {
    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -Description "키움증권 30분봉 W자/일봉 돌파 임박 주도주 매일 20시 자동 스캔" -Force
    Write-Host "✅ 작업 스케줄러 등록 완료!" -ForegroundColor Green
    Write-Host " - 작업 이름: $TaskName"
    Write-Host " - 실행 시각: 매일 20:00 (오후 8시)"
    Write-Host " - 실행 파일: $BatPath"
} catch {
    Write-Host "❌ 스케줄러 등록 실패: $_" -ForegroundColor Red
}
