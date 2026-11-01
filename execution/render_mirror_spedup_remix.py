import os
import sys
import argparse
import subprocess
import json

def get_audio_sample_rate(ffmpeg_bin: str, input_path: str) -> int:
    """Probe audio sample rate using ffmpeg/ffprobe or fallback to 44100."""
    ffprobe_bin = ffmpeg_bin.replace("ffmpeg.exe", "ffprobe.exe").replace("ffmpeg-win-x86_64-v7.1.exe", "ffprobe.exe")
    if os.path.exists(ffprobe_bin):
        try:
            cmd = [
                ffprobe_bin, "-v", "error",
                "-select_streams", "a:0",
                "-show_entries", "stream=sample_rate",
                "-of", "default=noprint_wrappers=1:nokey=1",
                input_path
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, check=True)
            sr = int(res.stdout.strip())
            return sr
        except Exception:
            pass
    return 44100

def render_mirror_spedup(input_path: str, output_path: str, speed: float = 1.06, mirror: bool = True):
    """
    Renders video in Mirror (hflip) and Sped Up (speed + pitch shift) mode.
    Ideal for bypassing YouTube Content ID while creating viral K-pop dance cover edits.
    """
    if not os.path.exists(input_path):
        raise FileNotFoundError(f"Input file not found: {input_path}")

    out_dir = os.path.dirname(output_path)
    if out_dir and not os.path.exists(out_dir):
        os.makedirs(out_dir, exist_ok=True)

    ffmpeg_bin = r"C:\Users\zoela\AppData\Local\Programs\Python\Python312\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"
    if not os.path.exists(ffmpeg_bin):
        ffmpeg_bin = "ffmpeg"

    sr = get_audio_sample_rate(ffmpeg_bin, input_path)
    print(f"[Info] Input: {input_path}")
    print(f"[Info] Output: {output_path}")
    print(f"[Info] Sample rate: {sr} Hz, Speed: {speed:.2f}x, Mirror: {mirror}")

    # Build filters
    vf_list = []
    if mirror:
        vf_list.append("hflip")
    vf_list.append(f"setpts=PTS/{speed}")
    vf_str = ",".join(vf_list)

    new_sr = int(sr * speed)
    af_str = f"asetrate={new_sr},aresample={sr}"

    cmd = [
        ffmpeg_bin, "-y",
        "-i", input_path,
        "-vf", vf_str,
        "-af", af_str,
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "19",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac",
        "-b:a", "320k",
        "-movflags", "+faststart",
        output_path
    ]

    print(f"[Process] Executing FFmpeg command:\n{' '.join(cmd)}\n")
    proc = subprocess.run(cmd, check=True)
    print(f"\n[Success] Rendered successfully: {output_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Render Mirror & Sped Up Remix Video")
    parser.add_argument("--input", "-i", type=str, required=True, help="Input video file path")
    parser.add_argument("--output", "-o", type=str, required=True, help="Output video file path")
    parser.add_argument("--speed", "-s", type=float, default=1.06, help="Playback speed multiplier (default: 1.06)")
    parser.add_argument("--no-mirror", action="store_true", help="Disable horizontal flip")

    args = parser.parse_args()
    render_mirror_spedup(args.input, args.output, speed=args.speed, mirror=not args.no_mirror)

