import cv2
import numpy as np
import mediapipe as mp

video_path = r"D:\download\bts_mma_source.mp4"
out_img = r"D:\BTS\test_ai_morphology_face.jpg"

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

# 2. Track Face & Extract Landmarks
mp_pose = mp.solutions.pose
with mp_pose.Pose(static_image_mode=True, min_detection_confidence=0.5) as pose:
    rgb = cv2.cvtColor(proportioned, cv2.COLOR_BGR2RGB)
    res = pose.process(rgb)

if res.pose_landmarks:
    lm = res.pose_landmarks.landmark
    nose = lm[0]
    s_lex, s_ley = int(lm[5].x * out_w), int(lm[5].y * out_h)
    s_rex, s_rey = int(lm[2].x * out_w), int(lm[2].y * out_h)
    nx, ny = int(nose.x * out_w), int(nose.y * out_h)
    l_ear = lm[7]
    r_ear = lm[8]
    l_mouth = lm[9]
    r_mouth = lm[10]
    
    dX = s_rex - s_lex
    dY = s_rey - s_ley
    eye_dist = np.sqrt(dX**2 + dY**2)
    angle = np.degrees(np.arctan2(dY, dX))
    
    # Face ROI
    head_r = int(eye_dist * 2.0)
    fx1, fx2 = max(0, nx - head_r), min(out_w, nx + head_r)
    fy1, fy2 = max(0, ny - int(head_r * 1.1)), min(out_h, ny + int(head_r * 1.3))
    
    face_roi = proportioned[fy1:fy2, fx1:fx2].copy()
    
    # A. Porcelain Glass Skin Smoothing (High-frequency texture removal while preserving sharp edges)
    smooth_skin = cv2.edgePreservingFilter(face_roi, flags=1, sigma_s=45, sigma_r=0.35)
    
    # B. Eye & Pupil Clarification & Anime Eye Shine
    # Enhance local contrast around eye line
    ycrcb = cv2.cvtColor(smooth_skin, cv2.COLOR_BGR2YCrCb)
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    ycrcb[:, :, 0] = clahe.apply(ycrcb[:, :, 0])
    clarified_face = cv2.cvtColor(ycrcb, cv2.COLOR_YCrCb2BGR)
    
    # C. V-Line Chin Sculpting (Subtle pinch at bottom of face ROI)
    fr_h, fr_w = face_roi.shape[:2]
    Y_grid, X_grid = np.meshgrid(np.arange(fr_h, dtype=np.float32), np.arange(fr_w, dtype=np.float32), indexing='ij')
    
    # Pinch effect towards center x for lower jaw (y > 0.65 * fr_h)
    chin_mask = np.clip((Y_grid - fr_h * 0.60) / (fr_h * 0.35), 0, 1.0)
    center_fx = fr_w / 2.0
    # Pull X towards center by up to 8%
    dist_x = X_grid - center_fx
    warped_X = X_grid - dist_x * (chin_mask * 0.08)
    vline_face = cv2.remap(clarified_face, warped_X, Y_grid, interpolation=cv2.INTER_LINEAR)
    
    # D. Radiant Idol Warm Tone & Rose Lips
    hsv = cv2.cvtColor(vline_face, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 1.12, 0, 255) # vibrance
    hsv[:, :, 2] = np.clip(hsv[:, :, 2] * 1.06, 0, 255) # luminous glow
    radiant_face = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
    
    # E. Feathered Elliptical Blend into Real Hair & Neck
    mask = np.zeros((fr_h, fr_w), dtype=np.float32)
    cv2.ellipse(mask, (fr_w // 2, int(fr_h * 0.48)), (int(fr_w * 0.38), int(fr_h * 0.45)), angle, 0, 360, 1.0, -1)
    mask = cv2.GaussianBlur(mask, (25, 25), 0)
    mask_3c = np.stack([mask]*3, axis=-1)
    
    proportioned[fy1:fy2, fx1:fx2] = (face_roi * (1.0 - mask_3c) + radiant_face * mask_3c).astype(np.uint8)

cv2.imwrite(out_img, proportioned, [cv2.IMWRITE_JPEG_QUALITY, 95])
print("Saved AI morphology face image:", out_img)

