$WshShell = New-Object -ComObject WScript.Shell
$DesktopPath = [Environment]::GetFolderPath("Desktop")
$ShortcutPath = [System.IO.Path]::Combine($DesktopPath, "HFT Scalping Bot.lnk")

$BatPath = Join-Path $PSScriptRoot "run_scalping_bot.bat"

$Shortcut = $WshShell.CreateShortcut($ShortcutPath)
$Shortcut.TargetPath = $BatPath
$Shortcut.WorkingDirectory = $PSScriptRoot
$Shortcut.IconLocation = "shell32.dll,172"
$Shortcut.Description = "HFT Multi-Agent Consensus Scalping Bot"
$Shortcut.Save()

Write-Host "Desktop shortcut created at: $ShortcutPath"
