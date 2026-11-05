$WorkDir = (Get-Item -LiteralPath $PSScriptRoot).FullName
$PythonExe = Join-Path $WorkDir ".venv\Scripts\python.exe"

# 1. 07:00 모닝 퀀트 데일리 시황 쇼츠
Unregister-ScheduledTask -TaskName "DailyQuant_Morning_0700" -Confirm:$false -ErrorAction SilentlyContinue
$Action1 = New-ScheduledTaskAction -Execute $PythonExe -Argument "execution\build_daily_shorts.py --upload --privacy public" -WorkingDirectory $WorkDir
$Trigger1 = New-ScheduledTaskTrigger -Daily -At "07:00"
$Settings1 = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Minutes 25)
Register-ScheduledTask -TaskName "DailyQuant_Morning_0700" -Action $Action1 -Trigger $Trigger1 -Settings $Settings1 -Force

# 2. 08:50 프리마켓 & 시초가 갭 긴급 숏츠
Unregister-ScheduledTask -TaskName "DailyQuant_PreMarket_0850" -Confirm:$false -ErrorAction SilentlyContinue
$Action2 = New-ScheduledTaskAction -Execute $PythonExe -Argument "execution\build_premarket_shorts.py --upload --privacy public" -WorkingDirectory $WorkDir
$Trigger2 = New-ScheduledTaskTrigger -Daily -At "08:50"
$Settings2 = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
Register-ScheduledTask -TaskName "DailyQuant_PreMarket_0850" -Action $Action2 -Trigger $Trigger2 -Settings $Settings2 -Force

# 3. 08:55 AI 500만원 실시간 가상 매매 상주 데몬 (09:05 눌림목 매수 ➔ 🎯 매도 체결 즉시 유튜브 쇼츠 실시간 자동 업로드)
Unregister-ScheduledTask -TaskName "DailyQuant_Challenge5M_Realtime" -Confirm:$false -ErrorAction SilentlyContinue
$Action3 = New-ScheduledTaskAction -Execute $PythonExe -Argument "execution\realtime_challenge_daemon.py --upload --privacy public" -WorkingDirectory $WorkDir
$Trigger3 = New-ScheduledTaskTrigger -Daily -At "08:55"
$Settings3 = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Hours 7)
Register-ScheduledTask -TaskName "DailyQuant_Challenge5M_Realtime" -Action $Action3 -Trigger $Trigger3 -Settings $Settings3 -Force

# 4. 17:30 AI 500M 챌린지 당일 체결타점 정밀 분석 Full HD 롱폼 영상 (퇴근길 피크타임)
Unregister-ScheduledTask -TaskName "DailyQuant_Challenge5M_1730" -Confirm:$false -ErrorAction SilentlyContinue
$Action4 = New-ScheduledTaskAction -Execute $PythonExe -Argument "execution\build_virtual_challenge_longform.py" -WorkingDirectory $WorkDir
$Trigger4 = New-ScheduledTaskTrigger -Daily -At "17:30"
$Settings4 = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Minutes 30)
Register-ScheduledTask -TaskName "DailyQuant_Challenge5M_1730" -Action $Action4 -Trigger $Trigger4 -Settings $Settings4 -Force

Write-Host "==========================================================================" -ForegroundColor Cyan
Write-Host "🎉 [데일리 퀀트] 4대 무인 자동 스케줄러 등록 완료" -ForegroundColor Green
Write-Host "==========================================================================" -ForegroundColor Cyan
Get-ScheduledTask -TaskName "DailyQuant*" | Format-Table TaskName, State, @{Name="NextRunTime";Expression={($_ | Get-ScheduledTaskInfo).NextRunTime}}, @{Name="WakeToRun";Expression={$_.Settings.WakeToRun}} -AutoSize
