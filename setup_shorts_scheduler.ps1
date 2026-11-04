$WorkDir = (Get-Item -LiteralPath $PSScriptRoot).FullName
$PythonExe = Join-Path $WorkDir ".venv\Scripts\python.exe"

# 1. 07:00 모닝 퀀트 데일리 쇼츠
Unregister-ScheduledTask -TaskName "DailyQuant_Morning_0700" -Confirm:$false -ErrorAction SilentlyContinue
$Action1 = New-ScheduledTaskAction -Execute $PythonExe -Argument "execution\build_daily_shorts.py --upload --privacy public" -WorkingDirectory $WorkDir
$Trigger1 = New-ScheduledTaskTrigger -Daily -At "07:00"
$Settings1 = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Minutes 25)
Register-ScheduledTask -TaskName "DailyQuant_Morning_0700" -Action $Action1 -Trigger $Trigger1 -Settings $Settings1 -Force

# 2. 08:50 프리마켓 긴급 숏츠
Unregister-ScheduledTask -TaskName "DailyQuant_PreMarket_0850" -Confirm:$false -ErrorAction SilentlyContinue
$Action2 = New-ScheduledTaskAction -Execute $PythonExe -Argument "execution\build_premarket_shorts.py --upload --privacy public" -WorkingDirectory $WorkDir
$Trigger2 = New-ScheduledTaskTrigger -Daily -At "08:50"
$Settings2 = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
Register-ScheduledTask -TaskName "DailyQuant_PreMarket_0850" -Action $Action2 -Trigger $Trigger2 -Settings $Settings2 -Force

# 3. 17:30 AI 500만원 주식 굴리기 챌린지 쇼츠 (퇴근길 피크타임 무인 자동 업로드)
Unregister-ScheduledTask -TaskName "DailyQuant_Challenge5M_1730" -Confirm:$false -ErrorAction SilentlyContinue
$Action3 = New-ScheduledTaskAction -Execute $PythonExe -Argument "execution\build_virtual_challenge_shorts.py --upload --privacy public" -WorkingDirectory $WorkDir
$Trigger3 = New-ScheduledTaskTrigger -Daily -At "17:30"
$Settings3 = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -WakeToRun -ExecutionTimeLimit (New-TimeSpan -Minutes 20)
Register-ScheduledTask -TaskName "DailyQuant_Challenge5M_1730" -Action $Action3 -Trigger $Trigger3 -Settings $Settings3 -Force

Get-ScheduledTask -TaskName "DailyQuant*" | Format-Table TaskName, State, @{Name="NextRunTime";Expression={($_ | Get-ScheduledTaskInfo).NextRunTime}}, @{Name="WakeToRun";Expression={$_.Settings.WakeToRun}} -AutoSize
