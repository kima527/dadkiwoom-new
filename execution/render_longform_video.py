import os
import sys
import json
import time
import subprocess

# Ensure UTF-8
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

def render_longform_video(
    timing_json: str = ".tmp/longform_script_timing.json",
    slides_dir: str = ".tmp/slides",
    output_video_path: str = r"D:\DailyQuant\LongForm_Ep1_GoldenCross_FactCheck.mp4",
    thumbnail_path: str = r"D:\DailyQuant\LongForm_Ep1_Thumbnail.png"
):
    """
    Stitches slide images and audio segments into a Full HD (1920x1080) 30FPS Long-Form Video.
    Embeds thumbnail as cover artwork.
    """
    start_time = time.time()
    os.makedirs(os.path.dirname(output_video_path), exist_ok=True)
    temp_dir = ".tmp/video_parts"
    os.makedirs(temp_dir, exist_ok=True)

    with open(timing_json, "r", encoding="utf-8") as f:
        timing_data = json.load(f)

    print("=" * 70)
    print("🎬 [롱폼 1편 렌더링 시작] 16:9 Full HD (1920x1080) 비디오 인코딩")
    print(f"📁 총 슬라이드 수: {len(timing_data)}개 파트")
    print("=" * 70 + "\n")

    part_files = []
    
    # Step 1: Render each slide part
    for item in timing_data:
        idx = item["slide_index"]
        slide_id = item["slide_id"]
        audio_path = item["audio_path"]
        slide_img = os.path.join(slides_dir, f"{slide_id}.png")
        part_out = os.path.join(temp_dir, f"part_{idx:02d}.mp4")
        
        if not os.path.exists(slide_img):
            raise FileNotFoundError(f"Slide image not found: {slide_img}")
        if not os.path.exists(audio_path):
            raise FileNotFoundError(f"Audio not found: {audio_path}")

        print(f"🎥 [{idx}/{len(timing_data)}] 파트 렌더링 중: {item['title']} (길이: {item['duration']:.1f}초)")

        cmd = [
            "ffmpeg", "-y",
            "-loop", "1",
            "-framerate", "30",
            "-i", os.path.abspath(slide_img),
            "-i", os.path.abspath(audio_path),
            "-c:v", "libx264",
            "-tune", "stillimage",
            "-c:a", "aac",
            "-b:a", "192k",
            "-pix_fmt", "yuv420p",
            "-s", "1920x1080",
            "-shortest",
            os.path.abspath(part_out)
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
        if res.returncode != 0:
            print(f"❌ Part {idx} 렌더링 실패:\n{res.stderr}")
            return False

        part_files.append(os.path.abspath(part_out))

    # Step 2: Concatenate all parts
    print("\n🔗 [전체 파트 병합 중] FFmpeg Concat Demuxer 가동...")
    concat_list_path = os.path.abspath(os.path.join(temp_dir, "concat_list.txt"))
    with open(concat_list_path, "w", encoding="utf-8") as f:
        for p in part_files:
            # Escape single quotes and backslashes for FFmpeg concat format
            safe_p = p.replace("\\", "/")
            f.write(f"file '{safe_p}'\n")

    unmerged_mp4 = os.path.abspath(os.path.join(temp_dir, "merged_raw.mp4"))
    cmd_concat = [
        "ffmpeg", "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_list_path,
        "-c", "copy",
        unmerged_mp4
    ]
    res_c = subprocess.run(cmd_concat, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res_c.returncode != 0:
        print(f"❌ Concat 병합 실패:\n{res_c.stderr}")
        return False

    # Step 3: Embed thumbnail artwork and write final video
    print("🖼️ [썸네일 아트워크 내장 중] 최종 MP4 패키징...")
    if os.path.exists(thumbnail_path):
        cmd_final = [
            "ffmpeg", "-y",
            "-i", unmerged_mp4,
            "-i", os.path.abspath(thumbnail_path),
            "-map", "0",
            "-map", "1",
            "-c", "copy",
            "-disposition:v:1", "attached_pic",
            "-movflags", "+faststart",
            os.path.abspath(output_video_path)
        ]
    else:
        cmd_final = [
            "ffmpeg", "-y",
            "-i", unmerged_mp4,
            "-c", "copy",
            "-movflags", "+faststart",
            os.path.abspath(output_video_path)
        ]

    res_f = subprocess.run(cmd_final, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if res_f.returncode != 0:
        print(f"❌ 최종 MP4 생성 실패:\n{res_f.stderr}")
        return False

    elapsed = time.time() - start_time
    file_size_mb = os.path.getsize(output_video_path) / (1024 * 1024)

    print("\n" + "=" * 70)
    print("🎉 [롱폼 1편 최종 비디오 렌더링 완료!]")
    print(f"📁 완성된 파일: {output_video_path}")
    print(f"📦 파일 크기  : {file_size_mb:.2f} MB")
    print(f"⏱️ 렌더링 시간: {elapsed:.1f}초")
    print("=" * 70 + "\n")
    return output_video_path

if __name__ == "__main__":
    render_longform_video()

