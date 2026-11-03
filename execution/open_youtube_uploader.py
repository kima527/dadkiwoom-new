import os
import sys
import json
import subprocess
import webbrowser

# Ensure UTF-8 output
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

def launch_upload_helper():
    video_path = r"D:\DailyQuant\PreMarket_Urgent_Shorts.mp4"
    if not os.path.exists(video_path):
        video_path = r"D:\DailyQuant\Daily_Quant_Shorts_Sample.mp4"

    title = "개장 10분 전! 08:50 프리마켓 SK하이닉스 수급 폭발 & 시초가 갭 속보 #Shorts"
    tags = "#Shorts #주식 #국내증시 #프리마켓 #시초가 #SK하이닉스"

    # Copy title to Windows clipboard
    copy_text = f"{title}\n\n{tags}"
    try:
        cmd = f'Set-Clipboard -Value "{copy_text}"'
        subprocess.run(["powershell", "-Command", cmd], check=True)
        print("📋 [클립보드 복사 완료] 유튜브 제목과 태그가 복사되었습니다! (Ctrl + V로 바로 붙여넣기 가능)")
    except Exception as e:
        print(f"클립보드 복사 예외: {e}")

    # 1. Open Explorer and highlight the video file
    try:
        subprocess.Popen(f'explorer /select,"{video_path}"')
        print(f"📁 [폴더 열림] 영상 파일 선택 완료: {video_path}")
    except Exception as e:
        print(f"탐색기 실행 예외: {e}")

    # 2. Open YouTube Studio Upload in default browser
    studio_url = "https://studio.youtube.com/"
    try:
        webbrowser.open(studio_url)
        print("🌐 [크롬 브라우저 열림] 유튜브 스튜디오가 열렸습니다.")
        print("👉 브라우저에 열린 유튜브 스튜디오 화면으로 탐색기의 영상 파일을 마우스로 '끌어다 놓기(Drag & Drop)'만 하세요!")
    except Exception as e:
        print(f"브라우저 실행 예외: {e}")

if __name__ == "__main__":
    launch_upload_helper()

