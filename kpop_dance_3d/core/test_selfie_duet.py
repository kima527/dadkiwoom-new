import cv2
import numpy as np
import mediapipe as mp

video_path = r"D:\download\bts_mma_source.mp4"
out_img = r"D:\BTS\test_selfie_duet.jpg"

cap = cv2.VideoCapture(video_path)
cap.set(cv2.CAP_PROP_POS_FRAMES, 900) # At 30s - V & Jungkook duet section!
ret, frame = cap.read()
cap.release()

src_h, src_w = frame.shape[:2]
# Center around x = 1800 (center of duet)
crop_w = 1600
center_x = 1800
x1 = max(0, center_x - crop_w // 2)
x2 = min(src_w, x1 + crop_w)
cropped = frame[:, x1:x2].copy()

out_w, out_h = 1080, 1920
raw_1080 = cv2.resize(cropped, (out_w, out_h), interpolation=cv2.INTER_LANCZOS4)

# 8-head proportion
split_y = int(out_h * 0.42)
y_indices = np.arange(out_h, dtype=np.float32)
src_y = np.where(y_indices < split_y,
                 y_indices,
                 split_y + (y_indices - split_y) * 0.935).astype(np.float32)
src_x = np.tile(np.arange(out_w, dtype=np.float32), (out_h, 1))
src_y_grid = np.tile(src_y[:, np.newaxis], (1, out_w))
proportioned = cv2.remap(raw_1080, src_x, src_y_grid, interpolation=cv2.INTER_LINEAR)

# Use MediaPipe Selfie Segmentation (model_selection=1: landscape model)
mp_selfie = mp.solutions.selfie_segmentation
with mp_selfie.SelfieSegmentation(model_selection=1) as selfie:
    rgb = cv2.cvtColor(cv2.resize(proportioned, (360, 640)), cv2.COLOR_BGR2RGB)
    res = selfie.process(rgb)

if res.segmentation_mask is not None:
    raw_mask = res.segmentation_mask
    mask_1080 = cv2.resize(raw_mask, (out_w, out_h), interpolation=cv2.INTER_LINEAR)

    # Threshold and clean
    binary_mask = (mask_1080 > 0.50).astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    closed = cv2.morphologyEx(binary_mask, cv2.MORPH_CLOSE, kernel)
    
    # Keep duet dancers in central region [0.12 * W, 0.88 * W], fade outer background dancers
    X_coords = np.tile(np.arange(out_w), (out_h, 1))
    center_weight = np.clip(1.0 - np.abs(X_coords - out_w//2) / (out_w * 0.48), 0.0, 1.0)
    
    smooth_mask = cv2.GaussianBlur(closed.astype(np.float32) / 255.0 * center_weight, (21, 21), 0)
    smooth_mask_3c = np.stack([smooth_mask]*3, axis=-1)

    # Dark stage with floor reflection
    Y_arr, X_arr = np.ogrid[:out_h, :out_w]
    dist_spot = np.sqrt(((X_arr - out_w//2) / 500.0)**2 + ((Y_arr - 1100) / 950.0)**2)
    spot = np.clip(1.0 - dist_spot * 0.75, 0.0, 1.0)
    spot_3c = np.stack([cv2.GaussianBlur(spot.astype(np.float32), (61, 61), 0)]*3, axis=-1)

    dark_stage = np.zeros_like(proportioned)
    floor_y = int(out_h * 0.72)
    dark_stage[floor_y:, :] = (proportioned[floor_y:, :] * 0.25).astype(np.uint8)
    dark_stage = (dark_stage.astype(np.float32) * spot_3c).astype(np.uint8)

    composite = (proportioned.astype(np.float32) * smooth_mask_3c + dark_stage.astype(np.float32) * (1.0 - smooth_mask_3c)).astype(np.uint8)
else:
    composite = proportioned

cv2.imwrite(out_img, composite, [cv2.IMWRITE_JPEG_QUALITY, 95])
print("Saved selfie duet test image:", out_img)

