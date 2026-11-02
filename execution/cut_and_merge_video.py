import os
import sys
import argparse
import subprocess
import re

# Ensure UTF-8 output for console
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

def parse_time(time_str: str) -> str:
    """Validate and normalize timestamp string (e.g. 19:28 or 00:19:28)."""
    time_str = time_str.strip()
    parts = time_str.split(':')
    if len(parts) == 2:
        m, s = int(parts[0]), float(parts[1])
        return f"{m//60:02d}:{m%60:02d}:{s:04.1f}" if m >= 60 else f"00:{m:02d}:{s:04.1f}"
    elif len(parts) == 3:
        return time_str
    else:
        raise ValueError(f"Invalid timestamp format: {time_str}")

def time_to_seconds(time_str: str) -> float:
    parts = [float(p) for p in time_str.strip().split(':')]
    if len(parts) == 2:
        return parts[0] * 60 + parts[1]
    elif len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return float(parts[0])

def cut_and_merge(input_video: str, output_video: str, ranges: list):
    """
    Cuts multiple timestamp ranges from input_video and concats them seamlessly.
    """
    if not os.path.exists(input_video):
        raise FileNotFoundError(f"Input video not found: {input_video}")

    ffmpeg_bin = r"C:\Users\zoela\AppData\Local\Programs\Python\Python312\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"
    if not os.path.exists(ffmpeg_bin):
        ffmpeg_bin = "ffmpeg"

    tmp_dir = os.path.abspath(".tmp/video_cuts")
    os.makedirs(tmp_dir, exist_ok=True)

    segment_files = []
    print(f"🎬 [시작] 총 {len(ranges)}개 구간 추출 및 병합 작업을 시작합니다.")
    print(f"📁 원본: {input_video}")
    print(f"💾 출력: {output_video}\n")

    for i, r in enumerate(ranges):
        # Range can be separated by '~' or '-'
        sep = '~' if '~' in r else '-'
        if sep not in r:
            raise ValueError(f"Range must contain '~' or '-': {r}")
        start_str, end_str = r.split(sep, 1)
        start_sec = time_to_seconds(start_str)
        end_sec = time_to_seconds(end_str)
        duration = end_sec - start_sec

        seg_out = os.path.join(tmp_dir, f"seg_{i:03d}.mp4")
        segment_files.append(seg_out)

        print(f"✂️  [{i+1}/{len(ranges)}] 구간 추출: {start_str.strip()} ~ {end_str.strip()} (길이: {duration:.1f}초)...", flush=True)

        cmd = [
            ffmpeg_bin, "-y",
            "-ss", start_str.strip(),
            "-to", end_str.strip(),
            "-i", input_video,
            "-c:v", "libx264",
            "-preset", "veryfast",
            "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-b:a", "320k",
            seg_out
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"   -> 세그먼트 생성 완료: {os.path.basename(seg_out)} ({os.path.getsize(seg_out)/(1024*1024):.2f} MB)", flush=True)

    # Concat all segments
    concat_list_file = os.path.join(tmp_dir, "concat_list.txt")
    with open(concat_list_file, "w", encoding="utf-8") as f:
        for seg in segment_files:
            escaped_path = seg.replace("\\", "/")
            f.write(f"file '{escaped_path}'\n")

    print(f"\n🔗 모든 구간을 무손실 병합 중...", flush=True)
    os.makedirs(os.path.dirname(output_video), exist_ok=True)
    concat_cmd = [
        ffmpeg_bin, "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_list_file,
        "-c", "copy",
        "-movflags", "+faststart",
        output_video
    ]
    subprocess.run(concat_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # Cleanup temporary segment files
    for seg in segment_files:
        try:
            os.remove(seg)
        except Exception:
            pass
    try:
        os.remove(concat_list_file)
    except Exception:
        pass

    out_size_mb = os.path.getsize(output_video) / (1024 * 1024)
    print(f"\n🎉 [완료] 최종 하이라이트 영상 제작 완료!")
    print(f"   - 저장 위치: {output_video}")
    print(f"   - 파일 크기: {out_size_mb:.2f} MB", flush=True)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cut video segments by timestamp ranges and merge them.")
    parser.add_argument("--input", "-i", type=str, required=True, help="Input video path")
    parser.add_argument("--output", "-o", type=str, required=True, help="Output merged video path")
    parser.add_argument("--ranges", "-r", nargs="+", required=True, help="Timestamp ranges like 19:28~23:28 23:38~24:34")

    args = parser.parse_args()

    # Allow comma-separated or space-separated ranges
    flat_ranges = []
    for item in args.ranges:
        if "," in item:
            flat_ranges.extend([x.strip() for x in item.split(",") if x.strip()])
        else:
            flat_ranges.append(item.strip())

    cut_and_merge(args.input, args.output, flat_ranges)

