import cv2
import numpy as np
import mediapipe as mp
import os
import subprocess

source_video = r"D:\download\bts_mma_source.mp4"
out_video = r"D:\BTS\test_duet_intro.mp4"
temp_video = out_video + ".raw.mp4"

ffmpeg_bin = r"C:\Users\zoela\AppData\Local\Programs\Python\Python312\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"
if not os.path.exists(ffmpeg_bin):
    ffmpeg_bin = "ffmpeg"

cap = cv2.VideoCapture(source_video)
fps = cap.get(cv2.CAP_PROP_FPS)
src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

start_frame = 240 # 8.0s
num_frames = 200  # ~6.7s (8s to 15s)
cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

out_w, out_h = 1080, 1920
crop_h = src_h # 2160
# For duet, crop width can be 1400 (wider than 1215) to comfortably fit both dancers side-by-side!
crop_w = 1400

# 8-head proportion remap grid
split_y = int(out_h * 0.42)
y_indices = np.arange(out_h, dtype=np.float32)
src_y = np.where(y_indices < split_y,
                 y_indices,
                 split_y + (y_indices - split_y) * 0.935).astype(np.float32)
src_x = np.tile(np.arange(out_w, dtype=np.float32), (out_h, 1))
src_y_grid = np.tile(src_y[:, np.newaxis], (1, out_w))

ffmpeg_cmd = [
    ffmpeg_bin, "-y",
    "-f", "rawvideo", "-vcodec", "rawvideo",
    "-s", f"{out_w}x{out_h}", "-pix_fmt", "bgr24", "-r", f"{fps}",
    "-i", "-",
    "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
    temp_video
]
pipe = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

mp_pose = mp.solutions.pose
pose = mp_pose.Pose(static_image_mode=False, model_complexity=0, enable_segmentation=True, min_detection_confidence=0.4)

smooth_center_x = 1750.0 # Center of action during intro (Jungkook at x ~ 1700-1800)
Y_arr, X_arr = np.ogrid[:out_h, :out_w]

print("Rendering test duet intro (8s-15s)...")
for i in range(num_frames):
    ret, frame = cap.read()
    if not ret:
        break
        
    # Crop centered around smooth_center_x
    center_x = int(smooth_center_x)
    x1 = max(0, center_x - crop_w // 2)
    x2 = min(src_w, x1 + crop_w)
    if x2 - x1 < crop_w:
        x1 = max(0, x2 - crop_w)
        
    cropped = frame[:, x1:x2]
    raw_1080 = cv2.resize(cropped, (out_w, out_h), interpolation=cv2.INTER_LINEAR)
    
    # 8-head proportion adjustment (real body, no face change)
    proportioned = cv2.remap(raw_1080, src_x, src_y_grid, interpolation=cv2.INTER_LINEAR)
    
    # MediaPipe pose & segmentation
    small_rgb = cv2.cvtColor(cv2.resize(proportioned, (360, 640)), cv2.COLOR_BGR2RGB)
    res = pose.process(small_rgb)
    
    if res.pose_landmarks and res.segmentation_mask is not None:
        lm = res.pose_landmarks.landmark
        dancer_x_local = int(lm[0].x * out_w)
        dancer_x_global = x1 + int(lm[0].x * crop_w)
        smooth_center_x = smooth_center_x * 0.95 + dancer_x_global * 0.05
        
        # Clean duet mask: keep center dancer + partner in crop
        raw_mask = res.segmentation_mask
        mask_1080 = cv2.resize(raw_mask, (out_w, out_h), interpolation=cv2.INTER_LINEAR)
        dancer_mask = np.where(mask_1080 > 0.40, 1.0, np.where(mask_1080 > 0.15, (mask_1080 - 0.15)/0.25, 0.0)).astype(np.float32)
        dancer_mask = cv2.GaussianBlur(dancer_mask, (21, 21), 0)
        dancer_mask_3c = np.stack([dancer_mask]*3, axis=-1)
        
        # Duet stage spotlight
        dist_spot = np.sqrt(((X_arr - out_w//2) / 480.0)**2 + ((Y_arr - 1100) / 950.0)**2)
        spot = np.clip(1.0 - dist_spot * 0.80, 0.0, 1.0)
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

pipe.stdin.close()
pipe.wait()
cap.release()
pose.close()

# Mux audio
start_sec = start_frame / fps
dur_sec = num_frames / fps
mux_cmd = [
    ffmpeg_bin, "-y",
    "-ss", f"{start_sec:.3f}", "-t", f"{dur_sec:.3f}",
    "-i", source_video,
    "-i", temp_video,
    "-map", "1:v:0", "-map", "0:a:0",
    "-c:v", "copy", "-c:a", "aac", "-b:a", "320k",
    "-shortest", out_video
]
subprocess.run(mux_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
if os.path.exists(temp_video):
    os.remove(temp_video)

print("Saved test duet intro video:", out_video)

