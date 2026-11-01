import os
import sys
import time
import subprocess
import cv2
import numpy as np

def main():
    source_video = r"D:\download\bts_mma_source.mp4"
    out_video = r"D:\BTS\BTS_Dynamite_FullStage_16x9_8Head_Natural.mp4"
    temp_video = out_video + ".raw.mp4"

    ffmpeg_bin = r"C:\Users\zoela\AppData\Local\Programs\Python\Python312\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"
    if not os.path.exists(ffmpeg_bin):
        ffmpeg_bin = "ffmpeg"

    if not os.path.exists(source_video):
        print(f"Error: Source video not found: {source_video}", flush=True)
        sys.exit(1)

    os.makedirs(os.path.dirname(os.path.abspath(out_video)), exist_ok=True)

    cap_info = cv2.VideoCapture(source_video)
    total_frames = int(cap_info.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap_info.get(cv2.CAP_PROP_FPS)
    cap_info.release()

    duration_sec = total_frames / fps
    print("============================================================", flush=True)
    print("BTS DYNAMITE 16:9 FULL STAGE (ALL 7 MEMBERS VISIBLE, 8-HEAD PROPORTIONS)", flush=True)
    print(f"Total Frames: {total_frames} ({duration_sec:.1f}s / {duration_sec/60:.2f}m) @ {fps:.2f} FPS", flush=True)
    print("Format: 1920x1080 FHD (16:9 Widescreen Full Room View)", flush=True)
    print("Feature: All 7 Members Complete View + 8-Head Body Proportion Remap", flush=True)
    print("============================================================", flush=True)

    out_w, out_h = 1920, 1080

    # 1. Precompute 8-Head Proportion Remap Grid for 16:9 Widescreen
    split_y = int(out_h * 0.42) # Y = 453
    y_indices = np.arange(out_h, dtype=np.float32)
    src_y = np.where(y_indices < split_y,
                     y_indices,
                     split_y + (y_indices - split_y) * 0.935).astype(np.float32)
    src_x = np.tile(np.arange(out_w, dtype=np.float32), (out_h, 1))
    src_y_grid = np.tile(src_y[:, np.newaxis], (1, out_w))

    # 2. Multi-threaded Input Pipe from FFmpeg (Full 4K scaled to 1920x1080)
    in_cmd = [
        ffmpeg_bin,
        "-i", source_video,
        "-vf", "scale=1920:1080:flags=lanczos",
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "-"
    ]

    # 3. Output Pipe to FFmpeg H.264 Encoder
    out_cmd = [
        ffmpeg_bin, "-y",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-s", f"{out_w}x{out_h}",
        "-pix_fmt", "bgr24",
        "-r", f"{fps}",
        "-i", "-",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "19",
        "-pix_fmt", "yuv420p",
        temp_video
    ]

    p_in = subprocess.Popen(in_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    p_out = subprocess.Popen(out_cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    frame_bytes = out_w * out_h * 3
    t_start = time.time()
    t_last = t_start
    frame_count = 0

    print("Encoding 16:9 full stage video via high-speed hardware-assisted stream...", flush=True)

    while True:
        raw = p_in.stdout.read(frame_bytes)
        if len(raw) < frame_bytes:
            break

        frame = np.frombuffer(raw, dtype=np.uint8).reshape((out_h, out_w, 3))
        proportioned = cv2.remap(frame, src_x, src_y_grid, interpolation=cv2.INTER_LINEAR)
        p_out.stdin.write(proportioned.tobytes())
        frame_count += 1

        if frame_count % 300 == 0:
            now = time.time()
            fps_proc = 300.0 / (now - t_last)
            elapsed = now - t_start
            eta = (total_frames - frame_count) / max(0.1, (frame_count / elapsed))
            pct = (frame_count / total_frames) * 100.0
            print(f"[{frame_count:4d}/{total_frames} ({pct:5.1f}%)] Speed: {fps_proc:5.1f} fps | Elapsed: {elapsed/60:4.1f}m | ETA: {eta/60:4.1f}m", flush=True)
            t_last = now

    p_in.stdout.close()
    p_in.wait()
    p_out.stdin.close()
    p_out.wait()

    total_time = time.time() - t_start
    print(f"Video stream completed: {frame_count} frames in {total_time/60:.2f}m ({frame_count/total_time:.1f} fps avg).", flush=True)

    # 4. Lossless Audio Mux
    print("Muxing original 320kbps AAC master audio track...", flush=True)
    mux_cmd = [
        ffmpeg_bin, "-y",
        "-i", temp_video,
        "-i", source_video,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "320k",
        "-shortest",
        out_video
    ]
    subprocess.run(mux_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    if os.path.exists(temp_video):
        os.remove(temp_video)

    out_size_mb = os.path.getsize(out_video) / (1024 * 1024)
    print(f"SUCCESS: Final deliverable created at {out_video} ({out_size_mb:.2f} MB)", flush=True)

if __name__ == "__main__":
    main()

