$desktop = [Environment]::GetFolderPath('Desktop')
$wsh = New-Object -ComObject WScript.Shell
$workspace = "C:\Users\zoela\OneDrive\바탕 화면\PythonWorksplace"

# 1. 원클릭 자동 제작 바로가기
$sc1 = $wsh.CreateShortcut("$desktop\모닝 퀀트 쇼츠 자동 제작.lnk")
$sc1.TargetPath = "$workspace\run_daily_shorts.bat"
$sc1.WorkingDirectory = $workspace
$sc1.IconLocation = "shell32.dll,220" # camera / video recorder icon
$sc1.Description = "모닝 퀀트 유튜브 쇼츠 원클릭 자동 제작 및 배포"
$sc1.Save()

# 2. D 드라이브 영상 보관함 폴더 바로가기
$sc2 = $wsh.CreateShortcut("$desktop\모닝 퀀트 영상 보관함 (D드라이브).lnk")
$sc2.TargetPath = "D:\DailyQuant"
$sc2.IconLocation = "shell32.dll,4" # folder icon
$sc2.Description = "D:\DailyQuant 완성 영상 및 썸네일 보관함 폴더"
$sc2.Save()

# 3. 최신 쇼츠 영상 바로보기 바로가기
$sc3 = $wsh.CreateShortcut("$desktop\오늘의 모닝 퀀트 쇼츠 바로보기.lnk")
$sc3.TargetPath = "D:\DailyQuant\Daily_Quant_Shorts_Sample.mp4"
$sc3.IconLocation = "shell32.dll,116" # video player icon
$sc3.Description = "오늘 제작된 최신 모닝 퀀트 쇼츠 영상 재생"
$sc3.Save()

Write-Host "✅ 바탕화면 바로가기 생성 완료:"
Get-ChildItem -Path $desktop -Filter "*모닝 퀀트*" | Select-Object Name, LastWriteTime

