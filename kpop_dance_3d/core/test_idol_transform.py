import cv2
import numpy as np
import mediapipe as mp

video_path = r"D:\download\bts_mma_source.mp4"
out_img = r"C:\Users\zoela\.gemini\antigravity\brain\63272223-b3c7-4010-ad97-80ed3a4e19c5\test_idol_transformed.jpg"

cap = cv2.VideoCapture(video_path)
cap.set(cv2.CAP_PROP_POS_FRAMES, 1500)
ret, frame = cap.read()
cap.release()

h, w = frame.shape[:2]
# Center dancer vertical crop (9:16)
crop_w = int(h * (9.0 / 16.0)) # 1215
center_x = int(w * 0.50)
x1 = max(0, center_x - crop_w // 2)
x2 = min(w, x1 + crop_w)
cropped = frame[:, x1:x2].copy()

out_w, out_h = 1080, 1920
raw_1080 = cv2.resize(cropped, (out_w, out_h), interpolation=cv2.INTER_LANCZOS4)

# 1. 8-Head Proportion Adjustment on Real Body
# Elongate legs below waist (split_y ~ 0.42 * out_h = 800) by 7%
split_y = int(out_h * 0.42)
y_indices = np.arange(out_h, dtype=np.float32)
src_y = np.where(y_indices < split_y,
                 y_indices,
                 split_y + (y_indices - split_y) * 0.935).astype(np.float32)
src_x = np.tile(np.arange(out_w, dtype=np.float32), (out_h, 1))
src_y_grid = np.tile(src_y[:, np.newaxis], (1, out_w))
proportioned = cv2.remap(raw_1080, src_x, src_y_grid, interpolation=cv2.INTER_LINEAR)

# 2. Track Face & Transform with MediaPipe Pose
mp_pose = mp.solutions.pose
with mp_pose.Pose(static_image_mode=True, min_detection_confidence=0.5) as pose:
    rgb = cv2.cvtColor(proportioned, cv2.COLOR_BGR2RGB)
    res = pose.process(rgb)

if res.pose_landmarks:
    lm = res.pose_landmarks.landmark
    nose = lm[0]
    l_eye = lm[2]
    r_eye = lm[5]
    l_ear = lm[7]
    r_ear = lm[8]
    l_mouth = lm[9]
    r_mouth = lm[10]
    l_sh = lm[11]
    r_sh = lm[12]

    nx, ny = int(nose.x * out_w), int(nose.y * out_h)
    sh_w = abs(int(l_sh.x * out_w) - int(r_sh.x * out_w))
    head_w = int(max(sh_w * 0.85, 80))
    head_h = int(head_w * 1.25)

    # Face bounding box
    fx1 = max(0, nx - head_w // 2)
    fx2 = min(out_w, fx1 + head_w)
    fy1 = max(0, ny - int(head_h * 0.55))
    fy2 = min(out_h, fy1 + head_h)

    face_roi = proportioned[fy1:fy2, fx1:fx2].copy()
    
    # 3. Idol Porcelain Skin Smoothing on Face ROI
    skin_smooth = cv2.bilateralFilter(face_roi, d=9, sigmaColor=75, sigmaSpace=75)
    
    # Eye & Feature Sharpening
    gray_face = cv2.cvtColor(face_roi, cv2.COLOR_BGR2GRAY)
    face_edges = cv2.adaptiveThreshold(cv2.medianBlur(gray_face, 3), 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 7, 2)
    face_edges_3c = cv2.cvtColor(face_edges, cv2.COLOR_GRAY2BGR)
    
    # Subtle manhwa idol line enhancement on face features
    enhanced_face = cv2.addWeighted(skin_smooth, 0.82, cv2.bitwise_and(skin_smooth, face_edges_3c), 0.18, 0)
    
    # Color tuning for radiant idol glow
    hsv_face = cv2.cvtColor(enhanced_face, cv2.COLOR_BGR2HSV).astype(np.float32)
    hsv_face[:, :, 1] = np.clip(hsv_face[:, :, 1] * 1.15, 0, 255) # slight vibrance
    hsv_face[:, :, 2] = np.clip(hsv_face[:, :, 2] * 1.05, 0, 255) # slight brightness
    enhanced_face = cv2.cvtColor(hsv_face.astype(np.uint8), cv2.COLOR_HSV2BGR)

    # Elliptical soft mask to blend smoothly into real hair and neck
    rh, rw = face_roi.shape[:2]
    mask_face = np.zeros((rh, rw), dtype=np.float32)
    cv2.ellipse(mask_face, (rw // 2, int(rh * 0.52)), (int(rw * 0.44), int(rh * 0.46)), 0, 0, 360, 1.0, -1)
    mask_face = cv2.GaussianBlur(mask_face, (25, 25), 0)
    mask_3c = np.stack([mask_face]*3, axis=-1)

    proportioned[fy1:fy2, fx1:fx2] = (face_roi * (1.0 - mask_3c) + enhanced_face * mask_3c).astype(np.uint8)

cv2.imwrite(out_img, proportioned, [cv2.IMWRITE_JPEG_QUALITY, 95])
print("Saved idol transformed image to:", out_img)

