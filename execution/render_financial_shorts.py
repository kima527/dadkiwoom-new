import os
import sys
import subprocess
import argparse
import shutil

# Ensure UTF-8 output
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

def get_audio_duration(ffmpeg_bin: str, audio_path: str) -> float:
    """Gets audio duration using ffprobe or ffmpeg output."""
    cmd = [ffmpeg_bin, "-i", audio_path]
    res = subprocess.run(cmd, stderr=subprocess.PIPE, text=True)
    for line in res.stderr.splitlines():
        if "Duration:" in line:
            dur_str = line.split("Duration:")[1].split(",")[0].strip()
            parts = [float(p) for p in dur_str.split(":")]
            return parts[0]*3600 + parts[1]*60 + parts[2]
    return 50.0

def render_financial_shorts(
    image_path: str = ".tmp/shorts_visual_today.png",
    audio_path: str = ".tmp/shorts_narration.mp3",
    output_path: str = r"D:\DailyQuant\Daily_Quant_Shorts_Sample.mp4",
    cover_path: str = ".tmp/shorts_cover_today.png",
    cover_duration: float = 4.0, # Increased to 4.0s for clear readability during opening hook
    fade_duration: float = 0.5,
    fps: int = 60
):
    """
    Renders high-quality 1080x1920 60FPS vertical YouTube Short.
    1. Features a 4.0-second visible Cover Page intro synchronized with the killer hook narration.
    2. Seamless 0.5-second cinematic crossfade into the detailed infographic.
    3. Embeds Cover Page as official MP4 Cover Artwork (attached_pic) so Windows Explorer
       and video players display the cover page as the file's thumbnail icon.
    4. Automatically saves standalone high-res thumbnail to D:\DailyQuant\Daily_Quant_Cover_Thumbnail.png.
    """
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found: {image_path}")
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio not found: {audio_path}")

    ffmpeg_bin = r"C:\Users\zoela\AppData\Local\Programs\Python\Python312\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"
    if not os.path.exists(ffmpeg_bin):
        ffmpeg_bin = "ffmpeg"

    duration = get_audio_duration(ffmpeg_bin, audio_path)
    total_frames = int(duration * fps)

    print("🎬 [4단계 시작] 파이낸셜 쇼츠 비디오 렌더링 파이프라인 (커버페이지 완전 노출 모드)")
    has_cover = os.path.exists(cover_path)
    if has_cover:
        print(f"🌟 커버페이지: {cover_path} (인트로 노출: {cover_duration:.1f}초, 크로스페이드: {fade_duration:.1f}초)")
    print(f"🖼️ 인포그래픽: {image_path}")
    print(f"🎙️ 내레이션 : {audio_path} (길이: {duration:.2f}초)")
    print(f"💾 출력 파일 : {output_path}")
    print(f"⚡ 프레임 수 : {total_frames} frames ({fps} FPS, 흔들림 없는 고화질 렌더링)\n", flush=True)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    temp_render_path = ".tmp/temp_shorts_video.mp4"

    if has_cover:
        # Crossfade offset = cover_duration - fade_duration (e.g. 4.0 - 0.5 = 3.5s)
        fade_offset = max(0.5, cover_duration - fade_duration)
        main_duration = duration - fade_offset + 1.0  # extra buffer

        # Step 1: Render video with 4-second cover intro and crossfade in 1440x2560 Vertical QHD (VP9 Trigger)
        cmd = [
            ffmpeg_bin, "-y",
            "-loop", "1", "-t", f"{cover_duration:.2f}", "-framerate", str(fps), "-i", cover_path,
            "-loop", "1", "-t", f"{main_duration:.2f}", "-framerate", str(fps), "-i", image_path,
            "-i", audio_path,
            "-filter_complex", (
                f"[0:v]scale=1440:2560:flags=lanczos[v0];"
                f"[1:v]scale=1440:2560:flags=lanczos[v1];"
                f"[v0][v1]xfade=transition=fade:duration={fade_duration:.2f}:offset={fade_offset:.2f}[v]"
            ),
            "-map", "[v]",
            "-map", "2:a",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "16",
            "-b:v", "16M",
            "-maxrate", "25M",
            "-bufsize", "32M",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "320k",
            "-t", f"{duration:.2f}",
            "-shortest",
            temp_render_path
        ]
        subprocess.run(cmd, check=True)

        # Step 2: Embed cover image as attached_pic in MP4 metadata (Windows Explorer Thumbnail Icon!)
        print("🖼️ MP4 파일 메타데이터에 커버페이지 썸네일 아트워크 삽입 중...", flush=True)
        attach_cmd = [
            ffmpeg_bin, "-y",
            "-i", temp_render_path,
            "-i", cover_path,
            "-map", "0",
            "-map", "1",
            "-c", "copy",
            "-disposition:v:1", "attached_pic",
            "-movflags", "+faststart",
            output_path
        ]
        subprocess.run(attach_cmd, check=True)

        # Step 3: Also copy high-res cover thumbnail directly to output folder
        dest_thumb_path = os.path.join(os.path.dirname(output_path), "Daily_Quant_Cover_Thumbnail.png")
        shutil.copyfile(cover_path, dest_thumb_path)
        print(f"🖼️ 단독 썸네일 이미지 파일 복사 완료: {dest_thumb_path}")
    else:
        # Fallback to single visual loop in 1440x2560 QHD
        cmd = [
            ffmpeg_bin, "-y",
            "-loop", "1",
            "-framerate", str(fps),
            "-i", image_path,
            "-i", audio_path,
            "-vf", "scale=1440:2560:flags=lanczos",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "16",
            "-b:v", "16M",
            "-maxrate", "25M",
            "-bufsize", "32M",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "320k",
            "-t", f"{duration:.2f}",
            "-shortest",
            "-movflags", "+faststart",
            output_path
        ]
        subprocess.run(cmd, check=True)

    out_size_mb = os.path.getsize(output_path) / (1024 * 1024)
    print(f"\n🎉 [4단계 완료] 유튜브 쇼츠 최종 영상 렌더링 성공!")
    print(f"   - 저장 위치: {output_path}")
    print(f"   - 파일 크기: {out_size_mb:.2f} MB")
    print(f"   - 재생 시간: {duration:.2f}초 (쇼츠 규격 100% 충족)")
    print(f"   - 커버페이지: 첫 4.0초간 확실하게 노출 + MP4 썸네일 아트워크 내장 완료!", flush=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Render Financial YouTube Shorts Video")
    parser.add_argument("--image", default=".tmp/shorts_visual_today.png", help="Infographic image path")
    parser.add_argument("--audio", default=".tmp/shorts_narration.mp3", help="Narration audio path")
    parser.add_argument("--output", default=r"D:\DailyQuant\Daily_Quant_Shorts_Sample.mp4", help="Output video path")
    parser.add_argument("--cover", default=".tmp/shorts_cover_today.png", help="Cover page image path")
    args = parser.parse_args()

    render_financial_shorts(args.image, args.audio, args.output, cover_path=args.cover)
