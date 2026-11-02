import os
import sys
import argparse
import subprocess
import cv2

# Ensure UTF-8 output for console
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

def get_video_duration(video_path: str) -> float:
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    cnt = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()
    if fps > 0 and cnt > 0:
        return cnt / fps
    return 0.0

def process_delogo_and_bgm(video_path: str, audio_path: str, output_path: str, delogo_coords: str = "1720:45:160:155", fade_out: float = 3.0):
    """
    Applies delogo to remove watermark and sets looped BGM with end fade-out.
    """
    if not os.path.exists(video_path):
        raise FileNotFoundError(f"Video file not found: {video_path}")
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio/BGM file not found: {audio_path}")

    duration = get_video_duration(video_path)
    fade_st = max(0.0, duration - fade_out) if duration > 0 else 0.0

    ffmpeg_bin = r"C:\Users\zoela\AppData\Local\Programs\Python\Python312\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"
    if not os.path.exists(ffmpeg_bin):
        ffmpeg_bin = "ffmpeg"

    x, y, w, h = delogo_coords.split(":")
    vf_str = f"delogo=x={x}:y={y}:w={w}:h={h}"
    af_str = f"afade=t=out:st={fade_st:.2f}:d={fade_out:.2f}" if fade_st > 0 else "anull"

    print("🎬 [작업 시작] 로고 제거 및 배경음악 합성 파이프라인")
    print(f"📁 대상 영상: {video_path} (길이: {duration:.1f}초)")
    print(f"🎵 배경 음악: {audio_path}")
    print(f"🚫 로고 제거 영역: x={x}, y={y}, w={w}, h={h}")
    print(f"💾 최종 출력: {output_path}\n", flush=True)

    cmd = [
        ffmpeg_bin, "-y",
        "-i", video_path,
        "-stream_loop", "-1",
        "-i", audio_path,
        "-vf", vf_str,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-af", af_str,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "320k",
        "-shortest",
        "-movflags", "+faststart",
        output_path
    ]

    subprocess.run(cmd, check=True)
    out_size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"\n🎉 [완료] 로고 제거 및 배경음악 교체 완료!")
    print(f"   - 파일: {output_path}")
    print(f"   - 크기: {out_size_mb:.2f} MB", flush=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Remove watermark logo and replace background music.")
    parser.add_argument("--video", "-v", type=str, required=True, help="Input video path")
    parser.add_argument("--audio", "-a", type=str, required=True, help="Background music audio/video path")
    parser.add_argument("--output", "-o", type=str, required=True, help="Output video path")
    parser.add_argument("--delogo", type=str, default="1720:45:160:155", help="Delogo bbox x:y:w:h")
    parser.add_argument("--fade", type=float, default=3.0, help="Audio fade-out seconds at end")

    args = parser.parse_args()
    process_delogo_and_bgm(args.video, args.audio, args.output, delogo_coords=args.delogo, fade_out=args.fade)

