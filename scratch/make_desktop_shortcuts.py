import os
import subprocess

desktop = os.path.normpath(os.path.expanduser('~/OneDrive/바탕 화면'))
workspace = os.path.abspath('.')

# VBScript to create shortcuts reliably with UTF-16 encoding
vbs_content = f'''
Set oWS = WScript.CreateObject("WScript.Shell")

' 1. 원클릭 제작 바로가기
sLink1 = "{desktop}\\모닝 퀀트 쇼츠 자동 제작.lnk"
Set oLink1 = oWS.CreateShortcut(sLink1)
oLink1.TargetPath = "{workspace}\\run_daily_shorts.bat"
oLink1.WorkingDirectory = "{workspace}"
oLink1.IconLocation = "shell32.dll,220"
oLink1.Description = "모닝 퀀트 유튜브 쇼츠 원클릭 자동 제작 및 배포"
oLink1.Save

' 2. D 드라이브 영상 보관함 폴더 바로가기
sLink2 = "{desktop}\\모닝 퀀트 영상 보관함 (D_DailyQuant).lnk"
Set oLink2 = oWS.CreateShortcut(sLink2)
oLink2.TargetPath = "D:\\DailyQuant"
oLink2.IconLocation = "shell32.dll,4"
oLink2.Description = "D:\\DailyQuant 완성 영상 및 썸네일 보관함 폴더"
oLink2.Save

' 3. 오늘 쇼츠 영상 바로보기 바로가기
sLink3 = "{desktop}\\오늘의 모닝 퀀트 쇼츠 바로보기.lnk"
Set oLink3 = oWS.CreateShortcut(sLink3)
oLink3.TargetPath = "D:\\DailyQuant\\Daily_Quant_Shorts_Sample.mp4"
oLink3.IconLocation = "shell32.dll,116"
oLink3.Description = "오늘 제작된 최신 모닝 퀀트 쇼츠 영상 재생"
oLink3.Save
'''

os.makedirs('.tmp', exist_ok=True)
vbs_path = os.path.join(workspace, '.tmp', 'create_shortcuts.vbs')
with open(vbs_path, 'w', encoding='utf-16') as f:
    f.write(vbs_content)

res = subprocess.run(['cscript.exe', '//Nologo', vbs_path], capture_output=True, text=True)
print('VBS Script Returncode:', res.returncode)
if res.returncode == 0:
    print('✅ 바탕화면 바로가기 아이콘 생성 성공!')
    for item in os.listdir(desktop):
        if '모닝 퀀트' in item or '쇼츠' in item:
            print(f'  - [바로가기] {item}')
else:
    print('❌ VBS 에러:', res.stderr)

