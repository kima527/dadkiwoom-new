import os
import sys
import argparse
from yt_dlp import YoutubeDL

def download_playlist(playlist_url: str, save_path: str = r"D:\download"):
    """
    Downloads all videos from a YouTube playlist or video URL in maximum MP4 quality.
    """
    if not os.path.exists(save_path):
        os.makedirs(save_path, exist_ok=True)
        print(f"[안내] '{save_path}' 폴더를 생성했습니다.", flush=True)

    ffmpeg_bin = r"C:\Users\zoela\AppData\Local\Programs\Python\Python312\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"
    if not os.path.exists(ffmpeg_bin):
        ffmpeg_bin = "ffmpeg"

    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best',
        'outtmpl': os.path.join(save_path, '%(title)s.%(ext)s'),
        'ignoreerrors': True,
        'playlist_items': '1-',
        'ffmpeg_location': ffmpeg_bin,
        'merge_output_format': 'mp4',
    }

    print(f"[시작] 유튜브 영상/재생목록 다운로드를 시작합니다 (저장경로: {save_path})...\n", flush=True)
    with YoutubeDL(ydl_opts) as ydl:
        ydl.download([playlist_url])
    print("\n[완료] 다운로드 프로세스가 성공적으로 완료되었습니다.", flush=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="YouTube Playlist & Video Batch Downloader")
    parser.add_argument("--url", type=str, default="https://www.youtube.com/playlist?list=PLhbeLti9jwYSZyHHkQlYMLARRj5lVmOVL", help="YouTube playlist or video URL")
    parser.add_argument("--output-dir", type=str, default=r"D:\download", help="Directory where files will be saved")
    args = parser.parse_args()

    download_playlist(args.url, args.output_dir)
