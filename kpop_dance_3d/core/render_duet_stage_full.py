import os
import sys
import time
import subprocess
import cv2
import numpy as np
import mediapipe as mp

def main():
    source_video = r"D:\download\bts_mma_source.mp4"
    out_video = r"D:\BTS\BTS_Dynamite_Duet_Stage_Full.mp4"
    temp_video = out_video + ".raw.mp4"

    ffmpeg_bin = r"C:\Users\zoela\AppData\Local\Programs\Python\Python312\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"
    if not os.path.exists(ffmpeg_bin):
        ffmpeg_bin = "ffmpeg"

    if not os.path.exists(source_video):
        print(f"Error: Source video not found: {source_video}", flush=True)
        sys.exit(1)

    os.makedirs(os.path.dirname(os.path.abspath(out_video)), exist_ok=True)

    cap = cv2.VideoCapture(source_video)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    duration_sec = total_frames / fps
    print(f"============================================================", flush=True)
    print(f"Starting BTS DYNAMITE DUET STAGE FULL VIDEO PRODUCTION", flush=True)
    print(f"Total Frames: {total_frames} ({duration_sec:.1f}s / {duration_sec/60:.2f} min) @ {fps:.2f} FPS", flush=True)
    print(f"Source Resolution: {src_w}x{src_h}", flush=True)
    print(f"Target Resolution: 1080x1920 (9:16 FHD Portrait)", flush=True)
    print(f"Pipeline: Duet Isolation + 8-Head Proportions + Original Natural Faces", flush=True)
    print(f"============================================================", flush=True)

    out_w, out_h = 1080, 1920
    crop_h = src_h
    crop_w = 1550  # Optimal width for duet formations (2 dancers side by side)

    # 1. Precompute 8-Head Proportion Remap Grid (~7% leg elongation below waist)
    split_y = int(out_h * 0.42)
    y_indices = np.arange(out_h, dtype=np.float32)
    src_y = np.where(y_indices < split_y,
                     y_indices,
                     split_y + (y_indices - split_y) * 0.935).astype(np.float32)
    src_x = np.tile(np.arange(out_w, dtype=np.float32), (out_h, 1))
    src_y_grid = np.tile(src_y[:, np.newaxis], (1, out_w))

    # 2. Precompute Horizontal Feathering Window for Duet Center Focus
    # 100% full opacity in center [140, 940], smooth Hermite falloff at outer margins
    x_line = np.arange(out_w, dtype=np.float32)
    left_ramp = np.clip((x_line - 50.0) / 90.0, 0.0, 1.0)
    left_smooth = left_ramp * left_ramp * (3.0 - 2.0 * left_ramp)
    right_ramp = np.clip((1030.0 - x_line) / 90.0, 0.0, 1.0)
    right_smooth = right_ramp * right_ramp * (3.0 - 2.0 * right_ramp)
    h_weight = np.minimum(left_smooth, right_smooth)
    h_weight_grid = np.tile(h_weight[np.newaxis, :], (out_h, 1))

    # 3. Precompute Stage Spotlight & Floor Lighting
    Y_arr, X_arr = np.ogrid[:out_h, :out_w]
    dist_spot = np.sqrt(((X_arr - out_w//2) / 520.0)**2 + ((Y_arr - 1100) / 950.0)**2)
    spot = np.clip(1.0 - dist_spot * 0.75, 0.0, 1.0)
    spot_3c = np.stack([cv2.GaussianBlur(spot.astype(np.float32), (61, 61), 0)] * 3, axis=-1)

    kernel_close = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (17, 17))
    floor_y = int(out_h * 0.72)

    # 4. Open FFmpeg Video Encoding Pipe (Fast H.264 encode)
    ffmpeg_cmd = [
        ffmpeg_bin,
        "-y",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-s", f"{out_w}x{out_h}",
        "-pix_fmt", "bgr24",
        "-r", f"{fps}",
        "-i", "-",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        temp_video
    ]
    pipe = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    # 5. Initialize MediaPipe Selfie Segmentation (Landscape Model 1)
    mp_selfie = mp.solutions.selfie_segmentation
    selfie = mp_selfie.SelfieSegmentation(model_selection=1)

    smooth_center_x = 1820.0
    t_start = time.time()
    t_last_log = t_start

    print("Beginning sequential frame processing...", flush=True)

    for idx in range(total_frames):
        ret, frame = cap.read()
        if not ret or frame is None:
            print(f"End of video stream at frame {idx}.", flush=True)
            break

        # Dynamic Gimbal Centering (Centered on duet dancers, strictly bounded within [1760, 1920])
        center_x = int(smooth_center_x)
        x1 = max(0, center_x - crop_w // 2)
        x2 = min(src_w, x1 + crop_w)
        if x2 - x1 < crop_w:
            x1 = max(0, x2 - crop_w)

        cropped = frame[:, x1:x2]
        fancam_raw = cv2.resize(cropped, (out_w, out_h), interpolation=cv2.INTER_LINEAR)

        # 8-Head Proportion Adjustment on Real Bodies
        proportioned = cv2.remap(fancam_raw, src_x, src_y_grid, interpolation=cv2.INTER_LINEAR)

        # MediaPipe Multi-Person Selfie Segmentation (at 360x640 for high performance)
        small_rgb = cv2.cvtColor(cv2.resize(proportioned, (360, 640)), cv2.COLOR_BGR2RGB)
        res = selfie.process(small_rgb)

        if res.segmentation_mask is not None:
            mask_small = res.segmentation_mask
            
            # Subtle smooth glide towards center of mass of dancers
            mask_active = (mask_small > 0.40).astype(np.float32)
            active_sum = np.sum(mask_active)
            if active_sum > 300:
                col_sums = np.sum(mask_active, axis=0)
                cx_rel = np.average(np.arange(len(col_sums)), weights=col_sums) / float(len(col_sums))
                target_global_x = x1 + cx_rel * crop_w
                # Clamp target to stay within core stage area
                target_clamped = np.clip(target_global_x, 1760.0, 1920.0)
                smooth_center_x = smooth_center_x * 0.99 + target_clamped * 0.01

            # High-res mask processing
            mask_1080 = cv2.resize(mask_small, (out_w, out_h), interpolation=cv2.INTER_LINEAR)
            binary = (mask_1080 > 0.48).astype(np.uint8) * 255
            closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel_close)

            # Apply horizontal feathering: Keep center duet dancers, cleanly erase outer peripheral dancers
            smooth_mask = cv2.GaussianBlur(closed.astype(np.float32) / 255.0 * h_weight_grid, (21, 21), 0)
            smooth_mask_3c = np.stack([smooth_mask] * 3, axis=-1)

            # Clean Dark Concert Stage with Floor Reflection
            dark_stage = np.zeros_like(proportioned)
            dark_stage[floor_y:, :] = (proportioned[floor_y:, :] * 0.25).astype(np.uint8)
            dark_stage = (dark_stage.astype(np.float32) * spot_3c).astype(np.uint8)

            final_frame = (proportioned.astype(np.float32) * smooth_mask_3c +
                           dark_stage.astype(np.float32) * (1.0 - smooth_mask_3c)).astype(np.uint8)
        else:
            final_frame = proportioned

        pipe.stdin.write(final_frame.tobytes())

        # Progress reporting every 300 frames (~10s)
        if idx > 0 and idx % 300 == 0:
            now = time.time()
            fps_proc = 300.0 / (now - t_last_log)
            elapsed = now - t_start
            eta = (total_frames - idx) / max(0.1, (idx / elapsed))
            pct = (idx / total_frames) * 100.0
            print(f"[{idx:4d}/{total_frames} ({pct:5.1f}%)] Proc Speed: {fps_proc:5.1f} fps | Elapsed: {elapsed/60:4.1f}m | ETA: {eta/60:4.1f}m | CamX: {smooth_center_x:.1f}", flush=True)
            t_last_log = now

    # Finalize Video Pipe
    pipe.stdin.close()
    pipe.wait()
    cap.release()
    selfie.close()

    total_proc_time = time.time() - t_start
    print(f"Video stream rendering completed in {total_proc_time/60:.2f} minutes ({total_frames/total_proc_time:.1f} fps average).", flush=True)

    # 6. Audio Muxing (Preserve full 320kbps AAC original master audio)
    print("Muxing original 320kbps AAC master audio...", flush=True)
    mux_cmd = [
        ffmpeg_bin,
        "-y",
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
    res = subprocess.run(mux_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if res.returncode != 0:
        print("FFmpeg audio mux failed, falling back to temp file as final.", flush=True)
        if os.path.exists(temp_video):
            os.replace(temp_video, out_video)
    else:
        if os.path.exists(temp_video):
            os.remove(temp_video)

    out_size_mb = os.path.getsize(out_video) / (1024 * 1024)
    print(f"FINAL DELIVERABLE CREATED: {out_video}", flush=True)
    print(f"Deliverable Size: {out_size_mb:.2f} MB", flush=True)
    print("Video production finished successfully!", flush=True)

if __name__ == "__main__":
    main()

