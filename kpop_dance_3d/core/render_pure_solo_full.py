import os
import sys
import time
import subprocess
import cv2
import numpy as np
import mediapipe as mp

def main():
    source_video = r"D:\download\bts_mma_source.mp4"
    out_video = r"D:\BTS\BTS_Dynamite_Pure_1Person_Solo_Full.mp4"
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
    print(f"Starting PURE 1-PERSON SOLO FULL VIDEO: {total_frames} frames ({total_frames/fps:.1f}s) @ {fps:.2f} FPS", flush=True)

    out_w, out_h = 1080, 1920
    crop_h = src_h
    crop_w = int(src_h * (9.0 / 16.0)) # 1215 in 4K

    # Precompute 8-head proportion remap grid (elongate legs ~7%)
    split_y = int(out_h * 0.42)
    y_indices = np.arange(out_h, dtype=np.float32)
    src_y = np.where(y_indices < split_y,
                     y_indices,
                     split_y + (y_indices - split_y) * 0.935).astype(np.float32)
    src_x = np.tile(np.arange(out_w, dtype=np.float32), (out_h, 1))
    src_y_grid = np.tile(src_y[:, np.newaxis], (1, out_w))

    # Precompute stage spotlight mask
    Y_arr, X_arr = np.ogrid[:out_h, :out_w]

    # FFmpeg raw video input pipe
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

    mp_pose = mp.solutions.pose
    pose = mp_pose.Pose(
        static_image_mode=False,
        model_complexity=0,
        enable_segmentation=True,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5
    )

    smooth_center_x = src_w * 0.50
    t_start = time.time()
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))

    print("Encoding pure 1-person solo frames...", flush=True)

    for idx in range(total_frames):
        ret, frame = cap.read()
        if not ret or frame is None:
            print(f"Stream completed at frame {idx}.", flush=True)
            break

        # 1. Virtual Camera Gimbal Pan (Smooth follow center dancer)
        center_x = int(smooth_center_x)
        x1 = max(0, center_x - crop_w // 2)
        x2 = min(src_w, x1 + crop_w)
        if x2 - x1 < crop_w:
            x1 = max(0, x2 - crop_w)

        cropped = frame[:, x1:x2]
        fancam_raw = cv2.resize(cropped, (out_w, out_h), interpolation=cv2.INTER_LINEAR)

        # 2. 8-Head Proportion Adjustment on Real Body
        proportioned = cv2.remap(fancam_raw, src_x, src_y_grid, interpolation=cv2.INTER_LINEAR)

        # 3. MediaPipe Pose & Segmentation (Processed at 360x640 for speed)
        small_rgb = cv2.cvtColor(cv2.resize(proportioned, (360, 640)), cv2.COLOR_BGR2RGB)
        res = pose.process(small_rgb)

        if res.pose_landmarks and res.segmentation_mask is not None:
            lm = res.pose_landmarks.landmark
            nose = lm[0]
            l_eye = lm[2]
            r_eye = lm[5]

            # Update gimbal center
            dancer_screen_x = int(nose.x * out_w)
            global_dancer_x = x1 + int(nose.x * crop_w)
            smooth_center_x = smooth_center_x * 0.96 + global_dancer_x * 0.04

            s_lex, s_ley = int(r_eye.x * out_w), int(r_eye.y * out_h)
            s_rex, s_rey = int(l_eye.x * out_w), int(l_eye.y * out_h)
            nx, ny = dancer_screen_x, int(nose.y * out_h)

            dX = s_rex - s_lex
            dY = s_rey - s_ley
            eye_dist = max(15.0, np.sqrt(dX**2 + dY**2))
            angle = np.degrees(np.arctan2(dY, dX))

            # Face transformation
            head_r = int(eye_dist * 2.0)
            fx1, fx2 = max(0, nx - head_r), min(out_w, nx + head_r)
            fy1, fy2 = max(0, ny - int(head_r * 1.1)), min(out_h, ny + int(head_r * 1.3))

            if fx2 > fx1 + 10 and fy2 > fy1 + 10:
                face_roi = proportioned[fy1:fy2, fx1:fx2].copy()
                fr_h, fr_w = face_roi.shape[:2]

                smooth_skin = cv2.edgePreservingFilter(face_roi, flags=1, sigma_s=40, sigma_r=0.35)
                ycrcb = cv2.cvtColor(smooth_skin, cv2.COLOR_BGR2YCrCb)
                ycrcb[:, :, 0] = clahe.apply(ycrcb[:, :, 0])
                clarified = cv2.cvtColor(ycrcb, cv2.COLOR_YCrCb2BGR)

                Y_grid, X_grid = np.meshgrid(np.arange(fr_h, dtype=np.float32), np.arange(fr_w, dtype=np.float32), indexing='ij')
                chin_mask = np.clip((Y_grid - fr_h * 0.60) / (fr_h * 0.35 + 1e-5), 0, 1.0)
                center_fx = fr_w / 2.0
                dist_x = X_grid - center_fx
                warped_X = X_grid - dist_x * (chin_mask * 0.08)
                vline_face = cv2.remap(clarified, warped_X, Y_grid, interpolation=cv2.INTER_LINEAR)

                hsv = cv2.cvtColor(vline_face, cv2.COLOR_BGR2HSV).astype(np.float32)
                hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 1.12, 0, 255)
                hsv[:, :, 2] = np.clip(hsv[:, :, 2] * 1.06, 0, 255)
                radiant = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

                mask_face = np.zeros((fr_h, fr_w), dtype=np.float32)
                cv2.ellipse(mask_face, (fr_w // 2, int(fr_h * 0.48)), (int(fr_w * 0.38), int(fr_h * 0.45)), angle, 0, 360, 1.0, -1)
                mask_face = cv2.GaussianBlur(mask_face, (25, 25), 0)
                mask_face_3c = np.stack([mask_face]*3, axis=-1)

                proportioned[fy1:fy2, fx1:fx2] = (face_roi * (1.0 - mask_face_3c) + radiant * mask_face_3c).astype(np.uint8)

            # 4. Strict Solo Dancer Isolation (Eliminating all other members)
            mask_1080 = cv2.resize(res.segmentation_mask, (out_w, out_h), interpolation=cv2.INTER_LINEAR)
            dancer_mask = np.where(mask_1080 > 0.65, 1.0, np.where(mask_1080 > 0.35, (mask_1080 - 0.35) / 0.30, 0.0)).astype(np.float32)

            # Remove any side members outside dancer's width
            X_coords = np.tile(np.arange(out_w), (out_h, 1))
            dist_from_dancer_x = np.abs(X_coords - nx)
            dancer_mask = dancer_mask * np.clip(1.0 - (dist_from_dancer_x - 290) / 90.0, 0.0, 1.0)
            dancer_mask = cv2.GaussianBlur(dancer_mask, (15, 15), 0)
            dancer_mask_3c = np.stack([dancer_mask]*3, axis=-1)

            # Stage Spotlight Background
            dist_spot = np.sqrt(((X_arr - nx) / 380.0)**2 + ((Y_arr - 1100) / 950.0)**2)
            spot = np.clip(1.0 - dist_spot * 0.85, 0.0, 1.0)
            spot_blur = cv2.GaussianBlur(spot.astype(np.float32), (81, 81), 0)

            dark_stage = np.zeros_like(proportioned)
            floor_y = int(out_h * 0.72)
            floor_crop = proportioned[floor_y:, :].copy()
            floor_dark = (cv2.boxFilter(floor_crop, -1, (35, 35)) * 0.35).astype(np.uint8)
            dark_stage[floor_y:, :] = floor_dark
            dark_stage = (dark_stage.astype(np.float32) * np.stack([spot_blur]*3, axis=-1)).astype(np.uint8)

            final_frame = (proportioned.astype(np.float32) * dancer_mask_3c + dark_stage.astype(np.float32) * (1.0 - dancer_mask_3c)).astype(np.uint8)
        else:
            final_frame = proportioned

        pipe.stdin.write(final_frame.tobytes())

        if (idx + 1) % 150 == 0 or idx == total_frames - 1:
            elapsed = time.time() - t_start
            cur_fps = (idx + 1) / elapsed
            eta_sec = (total_frames - (idx + 1)) / cur_fps if cur_fps > 0 else 0
            pct = ((idx + 1) / total_frames) * 100
            print(f"Solo Production: {idx+1}/{total_frames} frames ({pct:.1f}%) | {cur_fps:.1f} FPS | ETA: {eta_sec/60:.1f} min", flush=True)

    pipe.stdin.close()
    pipe.wait()
    cap.release()
    pose.close()

    print("Encoding complete. Muxing 320k audio...", flush=True)
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
    subprocess.run(mux_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    if os.path.exists(temp_video):
        try:
            os.remove(temp_video)
        except Exception:
            pass

    out_mb = os.path.getsize(out_video) / (1024 * 1024)
    print(f"SUCCESS: PURE 1-PERSON SOLO FULL VIDEO -> {out_video} ({out_mb:.2f} MB)", flush=True)

if __name__ == "__main__":
    main()

