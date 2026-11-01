import os
import sys
import time
import subprocess
import cv2
import numpy as np

def main():
    download_dir = r"D:\download"
    source_video = None
    for f in os.listdir(download_dir):
        if "Boy With Luv" in f or "작은 것" in f:
            source_video = os.path.join(download_dir, f)
            break

    if not source_video or not os.path.exists(source_video):
        print("Error: Boy With Luv source video not found", flush=True)
        sys.exit(1)

    out_video = r"D:\BTS\BTS_BoyWithLuv_FullStage_16x9_Delogo_8Head.mp4"
    temp_raw = out_video + ".raw.mp4"
    temp_mux = out_video + ".mux.mp4"

    ffmpeg_bin = r"C:\Users\zoela\AppData\Local\Programs\Python\Python312\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"
    if not os.path.exists(ffmpeg_bin):
        ffmpeg_bin = "ffmpeg"

    os.makedirs(os.path.dirname(os.path.abspath(out_video)), exist_ok=True)

    cap_info = cv2.VideoCapture(source_video)
    total_frames = int(cap_info.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap_info.get(cv2.CAP_PROP_FPS)
    cap_info.release()

    duration_sec = total_frames / fps
    print("============================================================", flush=True)
    print("BTS 'Boy With Luv' 16:9 FULL STAGE WITH LOGO REMOVAL (DELOGO)", flush=True)
    print(f"Source: {source_video}", flush=True)
    print(f"Total Frames: {total_frames} ({duration_sec:.1f}s / {duration_sec/60:.2f}m) @ {fps:.2f} FPS", flush=True)
    print("Format: 1920x1080 FHD (16:9 Widescreen Full Room View)", flush=True)
    print("Features: Complete Top-Right Logo Erased + 8-Head Body Proportions + All 7 Members", flush=True)
    print("============================================================", flush=True)

    out_w, out_h = 1920, 1080

    # 1. Precompute 8-Head Proportion Remap Grid for 16:9
    split_y = int(out_h * 0.42) # Y = 453
    y_indices = np.arange(out_h, dtype=np.float32)
    src_y = np.where(y_indices < split_y,
                     y_indices,
                     split_y + (y_indices - split_y) * 0.935).astype(np.float32)
    src_x = np.tile(np.arange(out_w, dtype=np.float32), (out_h, 1))
    src_y_grid = np.tile(src_y[:, np.newaxis], (1, out_w))

    # 2. Input Pipe from FFmpeg with Native C delogo filter in 1080p
    # delogo at x=1680, y=35, w=190, h=100 completely covers the Big Hit watermark
    in_cmd = [
        ffmpeg_bin,
        "-i", source_video,
        "-vf", "scale=1920:1080:flags=lanczos,delogo=x=1680:y=35:w=190:h=100",
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
        temp_raw
    ]

    p_in = subprocess.Popen(in_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    p_out = subprocess.Popen(out_cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    frame_bytes = out_w * out_h * 3
    t_start = time.time()
    t_last = t_start
    frame_count = 0
    first_blackout_frame = None

    print("Encoding 16:9 full stage video with seamless logo removal...", flush=True)

    while True:
        raw = p_in.stdout.read(frame_bytes)
        if len(raw) < frame_bytes:
            break

        frame = np.frombuffer(raw, dtype=np.uint8).reshape((out_h, out_w, 3))
        
        # 8-head body proportion adjustment
        proportioned = cv2.remap(frame, src_x, src_y_grid, interpolation=cv2.INTER_LINEAR)
        
        p_out.stdin.write(proportioned.tobytes())
        frame_count += 1

        # Outro black detection in the last 15 seconds
        if frame_count > total_frames - 450:
            gray = cv2.cvtColor(proportioned, cv2.COLOR_BGR2GRAY)
            m_val = float(np.mean(gray))
            if m_val < 1.0 and first_blackout_frame is None:
                first_blackout_frame = frame_count

        if frame_count % 300 == 0:
            now = time.time()
            speed = 300.0 / (now - t_last)
            elapsed = now - t_start
            eta = (total_frames - frame_count) / max(0.1, (frame_count / elapsed))
            pct = (frame_count / total_frames) * 100.0
            print(f"[{frame_count:4d}/{total_frames} ({pct:5.1f}%)] Speed: {speed:5.1f} fps | Elapsed: {elapsed/60:4.1f}m | ETA: {eta/60:4.1f}m", flush=True)
            t_last = now

    p_in.stdout.close()
    p_in.wait()
    p_out.stdin.close()
    p_out.wait()

    total_time = time.time() - t_start
    print(f"Video stream completed: {frame_count} frames in {total_time/60:.2f}m ({frame_count/total_time:.1f} fps avg).", flush=True)

    # 4. Audio Mux
    print("Muxing original 320kbps AAC master audio...", flush=True)
    mux_cmd = [
        ffmpeg_bin, "-y",
        "-i", temp_raw,
        "-i", source_video,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "320k",
        "-shortest",
        temp_mux
    ]
    subprocess.run(mux_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    if os.path.exists(temp_raw):
        os.remove(temp_raw)

    # 5. Outro Trim if present
    cutoff = None
    if first_blackout_frame is not None and (frame_count - first_blackout_frame) > 45:
        cutoff = first_blackout_frame + 15
        print(f"Trimming trailing outro to frame {cutoff}...", flush=True)

    if cutoff is not None and cutoff < frame_count:
        trim_cmd = [
            ffmpeg_bin, "-y",
            "-i", temp_mux,
            "-frames:v", str(cutoff),
            "-c:v", "copy", "-c:a", "copy",
            out_video
        ]
        subprocess.run(trim_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        if os.path.exists(temp_mux):
            os.remove(temp_mux)
    else:
        if os.path.exists(temp_mux):
            os.replace(temp_mux, out_video)

    out_size_mb = os.path.getsize(out_video) / (1024 * 1024)
    print(f"============================================================", flush=True)
    print(f"DELOGO DELIVERABLE CREATED: {out_video}", flush=True)
    print(f"Deliverable Size: {out_size_mb:.2f} MB", flush=True)
    print("16:9 Logo-Free Full Stage Video completed successfully!", flush=True)
    print("============================================================", flush=True)

if __name__ == "__main__":
    main()

