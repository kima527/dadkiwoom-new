import os
import sys
import argparse
from yt_dlp import YoutubeDL

# Ensure UTF-8 output for Windows console
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

def download_animal_videos(keywords, max_results=2, download_dir=r"D:\download\animal"):
    """
    지정된 동물 키워드로 유튜브 영상을 검색하여 고화질(MP4)로 자동 다운로드합니다.
    """
    if not os.path.exists(download_dir):
        os.makedirs(download_dir, exist_ok=True)
        print(f"📁 기본 다운로드 폴더 생성: {download_dir}", flush=True)

    ffmpeg_bin = r"C:\Users\zoela\AppData\Local\Programs\Python\Python312\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"
    if not os.path.exists(ffmpeg_bin):
        ffmpeg_bin = "ffmpeg"

    for keyword in keywords:
        print(f"\n🔍 '{keyword}' 관련 영상 검색 및 다운로드 시작 (상위 {max_results}개)...", flush=True)
        
        # 동물/키워드별 하위 폴더 생성
        sub_dir = os.path.join(download_dir, keyword)
        os.makedirs(sub_dir, exist_ok=True)

        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best[ext=mp4]/best',
            'outtmpl': os.path.join(sub_dir, '%(title)s.%(ext)s'),
            'noplaylist': True,
            'ignoreerrors': True,
            'ffmpeg_location': ffmpeg_bin,
            'merge_output_format': 'mp4',
            'windowsfilenames': True,
        }

        search_query = f"ytsearch{max_results}:{keyword}"

        try:
            with YoutubeDL(ydl_opts) as ydl:
                ydl.download([search_query])
            print(f"✅ '{keyword}' 영상 {max_results}개 수집 완료!", flush=True)
        except Exception as e:
            print(f"❌ '{keyword}' 수집 중 오류 발생: {e}", flush=True)

    print(f"\n🎉 모든 키워드 영상 다운로드 작업이 완료되었습니다! (저장 위치: {download_dir})", flush=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="YouTube Animal Video Search & Batch Downloader")
    parser.add_argument("--dir", type=str, default=r"D:\download\animal", help="Download directory")
    parser.add_argument("--max", type=int, default=2, help="Max results per keyword")
    args = parser.parse_args()

    # 손녀분이 좋아할 만한 귀여운 동물 키워드 리스트
    target_animals = ["아기 판다 귀여운 영상", "수달 물장구", "아기 코끼리 재롱"]
    
    download_animal_videos(keywords=target_animals, max_results=args.max, download_dir=args.dir)

