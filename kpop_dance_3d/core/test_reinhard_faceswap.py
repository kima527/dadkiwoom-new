import cv2
import numpy as np
import mediapipe as mp

video_path = r"D:\download\bts_mma_source.mp4"
face_path = r"D:\BTS\anime_faces\jungkook_anime_portrait_1793453734020.jpg"
out_img = r"D:\BTS\test_reinhard_faceswap.jpg"

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

# 1. 8-Head Proportion Adjustment on Real Body (lengthen legs ~7%)
split_y = int(out_h * 0.42)
y_indices = np.arange(out_h, dtype=np.float32)
src_y = np.where(y_indices < split_y,
                 y_indices,
                 split_y + (y_indices - split_y) * 0.935).astype(np.float32)
src_x = np.tile(np.arange(out_w, dtype=np.float32), (out_h, 1))
src_y_grid = np.tile(src_y[:, np.newaxis], (1, out_w))
proportioned = cv2.remap(raw_1080, src_x, src_y_grid, interpolation=cv2.INTER_LINEAR)

# 2. Track Face via MediaPipe Pose
mp_pose = mp.solutions.pose
with mp_pose.Pose(static_image_mode=True, min_detection_confidence=0.5) as pose:
    rgb = cv2.cvtColor(proportioned, cv2.COLOR_BGR2RGB)
    res = pose.process(rgb)

if res.pose_landmarks:
    lm = res.pose_landmarks.landmark
    nose = lm[0]
    # Screen coordinates:
    # lm[5] is subject's right eye -> screen LEFT eye
    # lm[2] is subject's left eye -> screen RIGHT eye
    s_lex, s_ley = int(lm[5].x * out_w), int(lm[5].y * out_h)
    s_rex, s_rey = int(lm[2].x * out_w), int(lm[2].y * out_h)
    nx, ny = int(nose.x * out_w), int(nose.y * out_h)

    # Real eye center and angle (in degrees, horizontal is 0)
    real_eye_center = np.array([(s_lex + s_rex) / 2.0, (s_ley + s_rey) / 2.0], dtype=np.float32)
    dX = s_rex - s_lex
    dY = s_rey - s_ley
    real_eye_dist = np.sqrt(dX**2 + dY**2)
    real_angle = np.degrees(np.arctan2(dY, dX))

    print(f"Screen eyes: dist={real_eye_dist:.1f}, angle={real_angle:.1f} deg")

    anime = cv2.imread(face_path)
    ah, aw = anime.shape[:2]
    # In portrait: screen left eye is around aw*0.415, screen right eye is aw*0.585
    anime_s_le = np.array([aw * 0.415, ah * 0.312], dtype=np.float32)
    anime_s_re = np.array([aw * 0.585, ah * 0.312], dtype=np.float32)
    anime_eye_center = (anime_s_le + anime_s_re) / 2.0
    anime_eye_dist = np.linalg.norm(anime_s_re - anime_s_le)

    # Similarity Transform (Rotation + Scale + Translation)
    scale = real_eye_dist / anime_eye_dist
    M = cv2.getRotationMatrix2D(tuple(anime_eye_center), real_angle, scale)
    M[0, 2] += (real_eye_center[0] - anime_eye_center[0])
    M[1, 2] += (real_eye_center[1] - anime_eye_center[1])

    warped_anime = cv2.warpAffine(anime, M, (out_w, out_h), flags=cv2.INTER_LANCZOS4)

    # 3. Reinhard Lighting & Tone Matching
    head_r = int(real_eye_dist * 2.2)
    rx1, rx2 = max(0, nx - head_r), min(out_w, nx + head_r)
    ry1, ry2 = max(0, ny - head_r), min(out_h, ny + head_r)
    real_patch = proportioned[ry1:ry2, rx1:rx2]
    anime_patch = warped_anime[ry1:ry2, rx1:rx2]

    lab_real = cv2.cvtColor(real_patch, cv2.COLOR_BGR2LAB).astype(np.float32)
    lab_anime = cv2.cvtColor(anime_patch, cv2.COLOR_BGR2LAB).astype(np.float32)

    m_r, s_r = lab_real.mean(axis=(0,1)), lab_real.std(axis=(0,1)) + 1e-5
    m_a, s_a = lab_anime.mean(axis=(0,1)), lab_anime.std(axis=(0,1)) + 1e-5

    lab_matched = np.zeros_like(lab_anime)
    for c in range(3):
        lab_matched[:, :, c] = np.clip((lab_anime[:, :, c] - m_a[c]) * (s_r[c] / s_a[c]) + m_r[c], 0, 255)
    matched_anime_patch = cv2.cvtColor(lab_matched.astype(np.uint8), cv2.COLOR_LAB2BGR)

    # 4. Soft Elliptical Blend
    mask_patch = np.zeros((ry2 - ry1, rx2 - rx1), dtype=np.float32)
    cx_p, cy_p = nx - rx1, ny - ry1
    cv2.ellipse(mask_patch, (cx_p, cy_p), (int(real_eye_dist * 0.85), int(real_eye_dist * 1.15)), real_angle, 0, 360, 1.0, -1)
    mask_patch = cv2.GaussianBlur(mask_patch, (21, 21), 0)
    mask_3c = np.stack([mask_patch]*3, axis=-1)

    proportioned[ry1:ry2, rx1:rx2] = (
        real_patch * (1.0 - mask_3c * 0.80) + 
        matched_anime_patch * (mask_3c * 0.80)
    ).astype(np.uint8)

cv2.imwrite(out_img, proportioned, [cv2.IMWRITE_JPEG_QUALITY, 95])
print("Saved Reinhard face swapped test image:", out_img)
