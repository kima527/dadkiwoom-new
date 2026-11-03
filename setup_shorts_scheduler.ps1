$WorkDir = (Get-Item -LiteralPath $PSScriptRoot).FullName
$PythonExe = Join-Path $WorkDir ".venv\Scripts\python.exe"

Unregister-ScheduledTask -TaskName "DailyQuant_Morning_0700" -Confirm:$false -ErrorAction SilentlyContinue
$Action1 = New-ScheduledTaskAction -Execute $PythonExe -Argument "execution\build_daily_shorts.py --upload --privacy public" -WorkingDirectory $WorkDir
$Trigger1 = New-ScheduledTaskTrigger -Daily -At "07:00"
$Settings1 = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 25)
Register-ScheduledTask -TaskName "DailyQuant_Morning_0700" -Action $Action1 -Trigger $Trigger1 -Settings $Settings1 -Force

Unregister-ScheduledTask -TaskName "DailyQuant_PreMarket_0850" -Confirm:$false -ErrorAction SilentlyContinue
$Action2 = New-ScheduledTaskAction -Execute $PythonExe -Argument "execution\build_premarket_shorts.py --upload --privacy public" -WorkingDirectory $WorkDir
$Trigger2 = New-ScheduledTaskTrigger -Daily -At "08:50"
$Settings2 = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
Register-ScheduledTask -TaskName "DailyQuant_PreMarket_0850" -Action $Action2 -Trigger $Trigger2 -Settings $Settings2 -Force

Get-ScheduledTask -TaskName "DailyQuant*" | Select-Object TaskName, State
