$MorningTask = "DailyQuant_Morning_0700"
$MorningBat = "C:\Users\zoela\OneDrive\바탕 화면\PythonWorksplace\run_daily_shorts.bat"

$PreMarketTask = "DailyQuant_PreMarket_0850"
$PreMarketBat = "C:\Users\zoela\OneDrive\바탕 화면\PythonWorksplace\run_premarket_shorts.bat"

Unregister-ScheduledTask -TaskName $MorningTask -Confirm:$false -ErrorAction SilentlyContinue
$Action1 = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$MorningBat`""
$Trigger1 = New-ScheduledTaskTrigger -Daily -At "07:00"
$Settings1 = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 25)
Register-ScheduledTask -TaskName $MorningTask -Action $Action1 -Trigger $Trigger1 -Settings $Settings1 -Force

Unregister-ScheduledTask -TaskName $PreMarketTask -Confirm:$false -ErrorAction SilentlyContinue
$Action2 = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$PreMarketBat`""
$Trigger2 = New-ScheduledTaskTrigger -Daily -At "08:50"
$Settings2 = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
Register-ScheduledTask -TaskName $PreMarketTask -Action $Action2 -Trigger $Trigger2 -Settings $Settings2 -Force

Get-ScheduledTask -TaskName "DailyQuant*" | Select-Object TaskName, State
