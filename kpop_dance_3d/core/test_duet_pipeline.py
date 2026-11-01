import cv2
import numpy as np
import mediapipe as mp
import os

video_path = r"D:\download\bts_mma_source.mp4"
out_dir = r"D:\BTS\duet_test_frames"
os.makedirs(out_dir, exist_ok=True)

# Test on 10s, 18s, 50s, 150s
cap = cv2.VideoCapture(video_path)
fps = cap.get(cv2.CAP_PROP_FPS)

test_timestamps = [10, 18, 50, 150]
mp_pose = mp.solutions.pose
pose = mp_pose.Pose(static_image_mode=True, enable_segmentation=True, min_detection_confidence=0.5)

for ts in test_timestamps:
    cap.set(cv2.CAP_PROP_POS_FRAMES, int(ts * fps))
    ret, frame = cap.read()
    if not ret:
        continue
    
    src_h, src_w = frame.shape[:2] # 2160, 3840
    
    # 1. Detect dancers across full frame by downscaling
    small = cv2.resize(frame, (960, 540))
    rgb_small = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
    res = pose.process(rgb_small)
    
    # If pose detected, find dancer position
    if res.pose_landmarks:
        lm = res.pose_landmarks.landmark
        dancer_x_norm = lm[0].x # nose x in [0, 1]
        dancer_x_4k = int(dancer_x_norm * src_w)
    else:
        dancer_x_4k = int(src_w * 0.50)
        
    print(f"Timestamp {ts}s: Dancer X in 4K = {dancer_x_4k}")
    
    # Dynamic 9:16 crop centered on dancer
    crop_w = int(src_h * (9.0 / 16.0)) # 1215
    x1 = max(0, dancer_x_4k - crop_w // 2)
    x2 = min(src_w, x1 + crop_w)
    if x2 - x1 < crop_w:
        if x1 == 0:
            x2 = min(src_w, crop_w)
        else:
            x1 = max(0, x2 - crop_w)
            
    cropped = frame[:, x1:x2].copy()
    out_w, out_h = 1080, 1920
    raw_1080 = cv2.resize(cropped, (out_w, out_h), interpolation=cv2.INTER_LANCZOS4)
    
    # 2. 8-Head Proportion Adjustment (Lengthen legs ~7%, face/upper body unchanged)
    split_y = int(out_h * 0.42)
    y_indices = np.arange(out_h, dtype=np.float32)
    src_y = np.where(y_indices < split_y,
                     y_indices,
                     split_y + (y_indices - split_y) * 0.935).astype(np.float32)
    src_x = np.tile(np.arange(out_w, dtype=np.float32), (out_h, 1))
    src_y_grid = np.tile(src_y[:, np.newaxis], (1, out_w))
    proportioned = cv2.remap(raw_1080, src_x, src_y_grid, interpolation=cv2.INTER_LINEAR)
    
    # 3. Clean Duet Segmentation on proportioned frame
    res_crop = pose.process(cv2.cvtColor(cv2.resize(proportioned, (360, 640)), cv2.COLOR_BGR2RGB))
    
    if res_crop.pose_landmarks and res_crop.segmentation_mask is not None:
        lm_crop = res_crop.pose_landmarks.landmark
        nx = int(lm_crop[0].x * out_w)
        
        raw_mask = res_crop.segmentation_mask
        mask_1080 = cv2.resize(raw_mask, (out_w, out_h), interpolation=cv2.INTER_LINEAR)
        dancer_mask = np.where(mask_1080 > 0.60, 1.0, np.where(mask_1080 > 0.30, (mask_1080 - 0.30) / 0.30, 0.0)).astype(np.float32)
        
        # Feathered dancer mask
        dancer_mask = cv2.GaussianBlur(dancer_mask, (17, 17), 0)
        dancer_mask_3c = np.stack([dancer_mask]*3, axis=-1)
        
        # Spotlight stage floor
        Y_arr, X_arr = np.ogrid[:out_h, :out_w]
        dist_spot = np.sqrt(((X_arr - nx) / 420.0)**2 + ((Y_arr - 1100) / 950.0)**2)
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
        
    out_path = os.path.join(out_dir, f"duet_snap_{ts}s.jpg")
    cv2.imwrite(out_path, final_frame, [cv2.IMWRITE_JPEG_QUALITY, 95])
    print(f"Saved: {out_path}")

cap.release()
pose.close()

