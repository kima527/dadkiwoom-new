import os
import sys
import imageio_ffmpeg
import yt_dlp

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

DOWNLOAD_DIR = r"D:\download"
os.makedirs(DOWNLOAD_DIR, exist_ok=True)
ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
ffmpeg_dir = os.path.dirname(ffmpeg_exe)

print("==================================================================")
print(f" 🎬 [BTS 유튜브 공식 안무 영상 다운로드 시작]")
print(f" 📂 저장 위치: {DOWNLOAD_DIR}")
print(f" ⚙️ FFmpeg 위치: {ffmpeg_exe}")
print("==================================================================")

ydl_opts = {
    'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best',
    'outtmpl': os.path.join(DOWNLOAD_DIR, '%(title)s.%(ext)s'),
    'merge_output_format': 'mp4',
    'ffmpeg_location': ffmpeg_dir,
    'quiet': False,
    'no_warnings': True,
    'ignoreerrors': True,
}

# 1. First priority: Dynamite Dance Practice
dynamite_url = "https://www.youtube.com/watch?v=CN4fffh7gmk"
print(f"\n[1/2] 🌟 1순위 핵심 영상 다운로드: BTS 'Dynamite' Dance Practice")
try:
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([dynamite_url])
    print("-> 'Dynamite' 다운로드 완료!")
except Exception as e:
    print(f"-> 오류 발생: {e}")

# 2. BTS Practice Choreography Playlist
playlist_url = "https://www.youtube.com/playlist?list=PLno1mwvwwOD1BW1PJoIVcnmyT79RQXeXz"
print(f"\n[2/2] 📋 BTS 안무 플레이리스트 전체 다운로드 진행...")
try:
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([playlist_url])
    print("-> 플레이리스트 다운로드 완료!")
except Exception as e:
    print(f"-> 플레이리스트 오류: {e}")

print("\n==================================================================")
print(f" 🎉 다운로드 완료! [{DOWNLOAD_DIR}] 폴더 파일 목록:")
if os.path.exists(DOWNLOAD_DIR):
    for f in os.listdir(DOWNLOAD_DIR):
        full_p = os.path.join(DOWNLOAD_DIR, f)
        if os.path.isfile(full_p):
            sz_mb = os.path.getsize(full_p) / (1024 * 1024)
            print(f"  - {f} ({sz_mb:.2f} MB)")
print("==================================================================")

