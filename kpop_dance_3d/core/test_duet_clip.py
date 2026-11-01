import cv2
import numpy as np
import mediapipe as mp
import os
import subprocess

source_video = r"D:\download\bts_mma_source.mp4"
out_video = r"D:\BTS\test_duet_8s_13s.mp4"
temp_video = out_video + ".raw.mp4"

ffmpeg_bin = r"C:\Users\zoela\AppData\Local\Programs\Python\Python312\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"
if not os.path.exists(ffmpeg_bin):
    ffmpeg_bin = "ffmpeg"

cap = cv2.VideoCapture(source_video)
fps = cap.get(cv2.CAP_PROP_FPS)
src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

start_frame = int(8.0 * fps)
num_frames = int(6.0 * fps)
cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

out_w, out_h = 1080, 1920
crop_w = 1550
crop_h = src_h

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

mp_selfie = mp.solutions.selfie_segmentation
selfie = mp_selfie.SelfieSegmentation(model_selection=1)

smooth_center_x = 1800.0
Y_arr, X_arr = np.ogrid[:out_h, :out_w]
dist_spot = np.sqrt(((X_arr - out_w//2) / 500.0)**2 + ((Y_arr - 1100) / 950.0)**2)
spot = np.clip(1.0 - dist_spot * 0.75, 0.0, 1.0)
spot_3c = np.stack([cv2.GaussianBlur(spot.astype(np.float32), (61, 61), 0)]*3, axis=-1)

X_coords = np.tile(np.arange(out_w), (out_h, 1))
center_weight = np.clip(1.0 - np.abs(X_coords - out_w//2) / (out_w * 0.48), 0.0, 1.0)
kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))

print("Rendering test clip 8s-14s...")
for i in range(num_frames):
    ret, frame = cap.read()
    if not ret:
        break
        
    center_x = int(smooth_center_x)
    x1 = max(0, center_x - crop_w // 2)
    x2 = min(src_w, x1 + crop_w)
    if x2 - x1 < crop_w:
        x1 = max(0, x2 - crop_w)
        
    cropped = frame[:, x1:x2]
    raw_1080 = cv2.resize(cropped, (out_w, out_h), interpolation=cv2.INTER_LINEAR)
    proportioned = cv2.remap(raw_1080, src_x, src_y_grid, interpolation=cv2.INTER_LINEAR)
    
    # Process segmentation
    small_rgb = cv2.cvtColor(cv2.resize(proportioned, (360, 640)), cv2.COLOR_BGR2RGB)
    res = selfie.process(small_rgb)
    
    if res.segmentation_mask is not None:
        mask_1080 = cv2.resize(res.segmentation_mask, (out_w, out_h), interpolation=cv2.INTER_LINEAR)
        binary = (mask_1080 > 0.45).astype(np.uint8) * 255
        closed = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
        smooth_mask = cv2.GaussianBlur(closed.astype(np.float32) / 255.0 * center_weight, (21, 21), 0)
        smooth_mask_3c = np.stack([smooth_mask]*3, axis=-1)
        
        dark_stage = np.zeros_like(proportioned)
        floor_y = int(out_h * 0.72)
        dark_stage[floor_y:, :] = (proportioned[floor_y:, :] * 0.25).astype(np.uint8)
        dark_stage = (dark_stage.astype(np.float32) * spot_3c).astype(np.uint8)
        
        final_frame = (proportioned.astype(np.float32) * smooth_mask_3c + dark_stage.astype(np.float32) * (1.0 - smooth_mask_3c)).astype(np.uint8)
    else:
        final_frame = proportioned
        
    pipe.stdin.write(final_frame.tobytes())

pipe.stdin.close()
pipe.wait()
cap.release()
selfie.close()

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

print("Saved test clip:", out_video)

