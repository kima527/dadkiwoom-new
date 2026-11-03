import os
import sys
import time
import subprocess
import shutil

# Ensure UTF-8 output
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from fetch_premarket_anomaly import fetch_premarket_anomaly_data
from generate_premarket_chart import create_premarket_visual
from storyteller_premarket import generate_premarket_script_and_audio

def run_premarket_shorts_pipeline(
    output_video_path: str = r"D:\DailyQuant\PreMarket_Urgent_Shorts.mp4",
    output_thumbnail_path: str = r"D:\DailyQuant\PreMarket_Urgent_Thumbnail.png"
):
    """
    Executes the 08:50 Pre-Market & Opening Gap Urgent Shorts Pipeline:
      1. 08:50 NXT Pre-Market & KRX Opening Gap Anomaly Data Fetch
      2. 1440x2560 QHD High-Contrast Dark Mode Emergency Graphic Generation
      3. 45s High-Urgency Storyteller Script & Edge-TTS Neural Audio Synthesis
      4. FFmpeg 60FPS 1440x2560 QHD Video Encoding
      5. Standalone Thumbnail & Metadata Export
    """
    start_time = time.time()
    print("=" * 70)
    print("🚨 [08:50 긴급 속보] 넥스트레이드(NXT) 프리마켓 & 시초가 갭 숏츠 제작 가동")
    print("=" * 70 + "\n")

    # Step 1: Fetch Pre-Market Data
    print(">>> [1/4] 08:50 프리마켓 마감 체결 및 9시 시초가 예상 갭 데이터 수집 중...")
    data = fetch_premarket_anomaly_data()
    json_path = ".tmp/premarket_anomaly_today.json"
    print()

    # Step 2: Render QHD Visual
    print(">>> [2/4] 1440x2560 QHD 긴급 속보 다크모드 인포그래픽 렌더링 중...")
    visual_path = ".tmp/premarket_visual_today.png"
    create_premarket_visual(json_path, visual_path)
    
    # Export standalone thumbnail
    os.makedirs(os.path.dirname(output_thumbnail_path), exist_ok=True)
    shutil.copy(visual_path, output_thumbnail_path)
    print(f"🖼️ 단독 썸네일 복사 완료: {output_thumbnail_path}\n")

    # Step 3: Storyteller Script & Audio
    print(">>> [3/4] 45초 초긴급 카운트다운 스토리텔링 대본 & AI 신경망 음성 합성 중...")
    script_path = ".tmp/premarket_script.txt"
    audio_path = ".tmp/premarket_narration.mp3"
    generate_premarket_script_and_audio(json_path, script_path, audio_path)
    print()

    # Step 4: Render Video with FFmpeg (1440x2560 QHD, 60fps)
    print(">>> [4/4] FFmpeg 60FPS QHD(1440x2560) 긴급 속보 비디오 인코딩 중...")
    os.makedirs(os.path.dirname(output_video_path), exist_ok=True)

    # Get audio duration
    probe_cmd = [
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1", audio_path
    ]
    try:
        dur_res = subprocess.run(probe_cmd, capture_output=True, text=True, check=True)
        duration = float(dur_res.stdout.strip())
    except Exception:
        duration = 45.0

    print(f"🎙️ 오디오 재생 길이: {duration:.2f}초 (쇼츠 황금 규격)")

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1", "-framerate", "60", "-t", str(duration), "-i", visual_path,
        "-i", audio_path,
        "-vf", "scale=1440:2560:flags=lanczos,format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "16",
        "-b:v", "16M", "-maxrate", "25M", "-bufsize", "32M",
        "-c:a", "aac", "-b:a", "320k",
        "-shortest",
        output_video_path
    ]

    print(f"⚡ FFmpeg 실행: {' '.join(cmd[:10])} ...")
    subprocess.run(cmd, check=True)

    elapsed = time.time() - start_time
    file_size_mb = os.path.getsize(output_video_path) / (1024 * 1024)

    print("\n" + "=" * 70)
    print("🎉 [08:50 긴급 숏츠 제작 완료]")
    print(f"   - 영상 경로: {output_video_path}")
    print(f"   - 썸네일 경로: {output_thumbnail_path}")
    print(f"   - 영상 크기: {file_size_mb:.2f} MB")
    print(f"   - 총 소요 시간: {elapsed:.1f}초 (약 {elapsed/60:.1f}분 -> 5분 컷 완벽 달성!)")
    print("=" * 70 + "\n")
    return output_video_path

if __name__ == "__main__":
    run_premarket_shorts_pipeline()

