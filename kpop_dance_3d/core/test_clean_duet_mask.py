import cv2
import numpy as np
import mediapipe as mp

video_path = r"D:\download\bts_mma_source.mp4"
out_img = r"D:\BTS\test_clean_duet_mask.jpg"

cap = cv2.VideoCapture(video_path)
cap.set(cv2.CAP_PROP_POS_FRAMES, 1500)
ret, frame = cap.read()
cap.release()

src_h, src_w = frame.shape[:2]
crop_w = 1550 # Generous width to comfortably fit duet dancers side-by-side
center_x = int(src_w * 0.50)
x1 = max(0, center_x - crop_w // 2)
x2 = min(src_w, x1 + crop_w)
cropped = frame[:, x1:x2].copy()

out_w, out_h = 1080, 1920
raw_1080 = cv2.resize(cropped, (out_w, out_h), interpolation=cv2.INTER_LANCZOS4)

# 8-head proportion (legs ~7% longer, upper body & face completely natural)
split_y = int(out_h * 0.42)
y_indices = np.arange(out_h, dtype=np.float32)
src_y = np.where(y_indices < split_y,
                 y_indices,
                 split_y + (y_indices - split_y) * 0.935).astype(np.float32)
src_x = np.tile(np.arange(out_w, dtype=np.float32), (out_h, 1))
src_y_grid = np.tile(src_y[:, np.newaxis], (1, out_w))
proportioned = cv2.remap(raw_1080, src_x, src_y_grid, interpolation=cv2.INTER_LINEAR)

# MediaPipe Pose & Neural Segmentation
mp_pose = mp.solutions.pose
with mp_pose.Pose(static_image_mode=True, enable_segmentation=True, min_detection_confidence=0.5) as pose:
    res = pose.process(cv2.cvtColor(cv2.resize(proportioned, (360, 640)), cv2.COLOR_BGR2RGB))

if res.segmentation_mask is not None:
    raw_mask = res.segmentation_mask
    mask_1080 = cv2.resize(raw_mask, (out_w, out_h), interpolation=cv2.INTER_LINEAR)
    
    # Clean binary cut + morphological smoothing to eliminate wall slat artifacts
    binary_mask = (mask_1080 > 0.55).astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    closed_mask = cv2.morphologyEx(binary_mask, cv2.MORPH_CLOSE, kernel)
    smooth_mask = cv2.GaussianBlur(closed_mask.astype(np.float32) / 255.0, (19, 19), 0)
    smooth_mask_3c = np.stack([smooth_mask]*3, axis=-1)

    # Clean Dark Stage with subtle floor reflection
    Y_arr, X_arr = np.ogrid[:out_h, :out_w]
    dist_spot = np.sqrt(((X_arr - out_w//2) / 450.0)**2 + ((Y_arr - 1100) / 900.0)**2)
    spot = np.clip(1.0 - dist_spot * 0.75, 0.0, 1.0)
    spot_3c = np.stack([cv2.GaussianBlur(spot.astype(np.float32), (61, 61), 0)]*3, axis=-1)

    # Sleek dark stage
    dark_stage = np.zeros_like(proportioned)
    floor_y = int(out_h * 0.72)
    dark_stage[floor_y:, :] = (proportioned[floor_y:, :] * 0.25).astype(np.uint8)
    dark_stage = (dark_stage.astype(np.float32) * spot_3c).astype(np.uint8)

    clean_composite = (proportioned.astype(np.float32) * smooth_mask_3c + dark_stage.astype(np.float32) * (1.0 - smooth_mask_3c)).astype(np.uint8)
else:
    clean_composite = proportioned

cv2.imwrite(out_img, clean_composite, [cv2.IMWRITE_JPEG_QUALITY, 95])
print("Saved clean duet mask test image:", out_img)

