import cv2
import numpy as np
import mediapipe as mp

video_path = r"D:\download\bts_mma_source.mp4"
out_img_spotlight = r"D:\BTS\test_solo_spotlight.jpg"
out_img_studio = r"D:\BTS\test_solo_studio.jpg"

cap = cv2.VideoCapture(video_path)
cap.set(cv2.CAP_PROP_POS_FRAMES, 1500)
ret, frame = cap.read()
cap.release()

h, w = frame.shape[:2]
crop_w = int(h * (9.0 / 16.0))
center_x = int(w * 0.50)
x1 = max(0, center_x - crop_w // 2)
x2 = min(w, x1 + crop_w)
cropped = frame[:, x1:x2].copy()

out_w, out_h = 1080, 1920
raw_1080 = cv2.resize(cropped, (out_w, out_h), interpolation=cv2.INTER_LANCZOS4)

# 1. 8-Head Proportion Adjustment on Real Body
split_y = int(out_h * 0.42)
y_indices = np.arange(out_h, dtype=np.float32)
src_y = np.where(y_indices < split_y,
                 y_indices,
                 split_y + (y_indices - split_y) * 0.935).astype(np.float32)
src_x = np.tile(np.arange(out_w, dtype=np.float32), (out_h, 1))
src_y_grid = np.tile(src_y[:, np.newaxis], (1, out_w))
proportioned = cv2.remap(raw_1080, src_x, src_y_grid, interpolation=cv2.INTER_LINEAR)

# 2. Track Face & Segment Center Dancer
mp_pose = mp.solutions.pose
with mp_pose.Pose(static_image_mode=True, enable_segmentation=True, min_detection_confidence=0.5) as pose:
    rgb = cv2.cvtColor(proportioned, cv2.COLOR_BGR2RGB)
    res = pose.process(rgb)

if res.pose_landmarks and res.segmentation_mask is not None:
    lm = res.pose_landmarks.landmark
    nose = lm[0]
    s_lex, s_ley = int(lm[5].x * out_w), int(lm[5].y * out_h)
    s_rex, s_rey = int(lm[2].x * out_w), int(lm[2].y * out_h)
    nx, ny = int(nose.x * out_w), int(nose.y * out_h)

    dX = s_rex - s_lex
    dY = s_rey - s_ley
    eye_dist = max(15.0, np.sqrt(dX**2 + dY**2))
    angle = np.degrees(np.arctan2(dY, dX))

    # Face transformation
    head_r = int(eye_dist * 2.0)
    fx1, fx2 = max(0, nx - head_r), min(out_w, nx + head_r)
    fy1, fy2 = max(0, ny - int(head_r * 1.1)), min(out_h, ny + int(head_r * 1.3))

    face_roi = proportioned[fy1:fy2, fx1:fx2].copy()
    fr_h, fr_w = face_roi.shape[:2]

    # Porcelain skin
    smooth_skin = cv2.edgePreservingFilter(face_roi, flags=1, sigma_s=40, sigma_r=0.35)
    ycrcb = cv2.cvtColor(smooth_skin, cv2.COLOR_BGR2YCrCb)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    ycrcb[:, :, 0] = clahe.apply(ycrcb[:, :, 0])
    clarified = cv2.cvtColor(ycrcb, cv2.COLOR_YCrCb2BGR)

    # V-Line Jaw
    Y_grid, X_grid = np.meshgrid(np.arange(fr_h, dtype=np.float32), np.arange(fr_w, dtype=np.float32), indexing='ij')
    chin_mask = np.clip((Y_grid - fr_h * 0.60) / (fr_h * 0.35 + 1e-5), 0, 1.0)
    center_fx = fr_w / 2.0
    dist_x = X_grid - center_fx
    warped_X = X_grid - dist_x * (chin_mask * 0.08)
    vline_face = cv2.remap(clarified, warped_X, Y_grid, interpolation=cv2.INTER_LINEAR)

    # Radiant Glow
    hsv = cv2.cvtColor(vline_face, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 1.12, 0, 255)
    hsv[:, :, 2] = np.clip(hsv[:, :, 2] * 1.06, 0, 255)
    radiant = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

    mask_face = np.zeros((fr_h, fr_w), dtype=np.float32)
    cv2.ellipse(mask_face, (fr_w // 2, int(fr_h * 0.48)), (int(fr_w * 0.38), int(fr_h * 0.45)), angle, 0, 360, 1.0, -1)
    mask_face = cv2.GaussianBlur(mask_face, (25, 25), 0)
    mask_face_3c = np.stack([mask_face]*3, axis=-1)
    proportioned[fy1:fy2, fx1:fx2] = (face_roi * (1.0 - mask_face_3c) + radiant * mask_face_3c).astype(np.uint8)

    # 3. Clean Center Dancer Segmentation Mask
    raw_mask = res.segmentation_mask
    mask_1080 = cv2.resize(raw_mask, (out_w, out_h), interpolation=cv2.INTER_LINEAR)
    
    # Strictly isolate center dancer: only keep mask within proximity of the center dancer landmarks
    # Distance from center line
    dancer_mask = np.where(mask_1080 > 0.65, 1.0, np.where(mask_1080 > 0.35, (mask_1080 - 0.35) / 0.30, 0.0)).astype(np.float32)
    
    # Zero out anything too far left or right (other dancers)
    X_coords = np.tile(np.arange(out_w), (out_h, 1))
    dist_from_dancer_x = np.abs(X_coords - nx)
    dancer_mask = dancer_mask * np.clip(1.0 - (dist_from_dancer_x - 300) / 100.0, 0.0, 1.0)
    
    dancer_mask = cv2.GaussianBlur(dancer_mask, (15, 15), 0)
    dancer_mask_3c = np.stack([dancer_mask]*3, axis=-1)

    # OPTION A: Dark Stage Solo Spotlight (1-Person Solo Dance)
    # Stage floor reflection + overhead spotlight
    Y_arr, X_arr = np.ogrid[:out_h, :out_w]
    dist_spot = np.sqrt(((X_arr - nx) / 380.0)**2 + ((Y_arr - 1100) / 950.0)**2)
    spot = np.clip(1.0 - dist_spot * 0.85, 0.0, 1.0)
    spot_blur = cv2.GaussianBlur(spot.astype(np.float32), (81, 81), 0)
    
    dark_stage = np.zeros_like(proportioned)
    # Give subtle wooden floor reflection under feet
    floor_y = int(out_h * 0.72)
    floor_crop = proportioned[floor_y:, :].copy()
    floor_dark = (cv2.boxFilter(floor_crop, -1, (35, 35)) * 0.35).astype(np.uint8)
    dark_stage[floor_y:, :] = floor_dark
    dark_stage = (dark_stage.astype(np.float32) * np.stack([spot_blur]*3, axis=-1)).astype(np.uint8)

    solo_spotlight = (proportioned.astype(np.float32) * dancer_mask_3c + dark_stage.astype(np.float32) * (1.0 - dancer_mask_3c)).astype(np.uint8)
    cv2.imwrite(out_img_spotlight, solo_spotlight, [cv2.IMWRITE_JPEG_QUALITY, 95])
    print("Saved solo spotlight:", out_img_spotlight)

    # OPTION B: Clean Studio Bokeh (Other members smoothly faded out)
    clean_studio = cv2.GaussianBlur(proportioned, (65, 65), 0)
    clean_studio = (clean_studio.astype(np.float32) * 0.45).astype(np.uint8)
    solo_studio = (proportioned.astype(np.float32) * dancer_mask_3c + clean_studio.astype(np.float32) * (1.0 - dancer_mask_3c)).astype(np.uint8)
    cv2.imwrite(out_img_studio, solo_studio, [cv2.IMWRITE_JPEG_QUALITY, 95])
    print("Saved solo studio:", out_img_studio)

