import cv2
import numpy as np
import mediapipe as mp
import os

video_path = r"D:\download\bts_mma_source.mp4"
face_path = r"C:\Users\zoela\AppData\Local\Programs\Python\Python312\..\..\..\..\..\.gemini\antigravity\brain\63272223-b3c7-4010-ad97-80ed3a4e19c5\jungkook_anime_portrait_1793453734020.jpg"
out_img = r"C:\Users\zoela\.gemini\antigravity\brain\63272223-b3c7-4010-ad97-80ed3a4e19c5\test_solo_face_blend.jpg"

# 1. Read source frame
cap = cv2.VideoCapture(video_path)
cap.set(cv2.CAP_PROP_POS_FRAMES, 1500)
ret, frame = cap.read()
cap.release()

if not ret:
    print("Failed to read video frame")
    exit(1)

h, w = frame.shape[:2]
crop_w = int(h * (9.0 / 16.0)) # 1215
center_x = int(w * 0.50)
x1 = max(0, center_x - crop_w // 2)
x2 = min(w, x1 + crop_w)
cropped = frame[:, x1:x2]
fancam_raw = cv2.resize(cropped, (1080, 1920), interpolation=cv2.INTER_LANCZOS4)

# 2. Use MediaPipe Pose to find center dancer keypoints
mp_pose = mp.solutions.pose
with mp_pose.Pose(static_image_mode=True, min_detection_confidence=0.5) as pose:
    results = pose.process(cv2.cvtColor(fancam_raw, cv2.COLOR_BGR2RGB))

if results.pose_landmarks:
    print("Pose detected successfully!")
    landmarks = results.pose_landmarks.landmark
    # Nose (0), Left eye (2), Right eye (5), Left shoulder (11), Right shoulder (12)
    nose = landmarks[0]
    l_eye = landmarks[2]
    r_eye = landmarks[5]
    l_ear = landmarks[7]
    r_ear = landmarks[8]
    l_sh = landmarks[11]
    r_sh = landmarks[12]
    
    nx, ny = int(nose.x * 1080), int(nose.y * 1920)
    sh_w = abs(int(l_sh.x * 1080) - int(r_sh.x * 1080))
    print(f"Nose: ({nx}, {ny}), Shoulder width: {sh_w}")
    
    # 3. Load Anime Face
    anime_full = cv2.imread(face_path)
    # Jungkook portrait face region roughly: y: 15% to 55%, x: 25% to 75%
    ah, aw = anime_full.shape[:2]
    anime_face = anime_full[int(ah*0.12):int(ah*0.55), int(aw*0.22):int(aw*0.78)]
    
    # Target head size
    head_w = int(sh_w * 0.95)
    head_h = int(head_w * (anime_face.shape[0] / anime_face.shape[1]))
    resized_face = cv2.resize(anime_face, (head_w, head_h), interpolation=cv2.INTER_LANCZOS4)
    
    # Create elliptical soft alpha mask
    mask = np.zeros((head_h, head_w), dtype=np.float32)
    cv2.ellipse(mask, (head_w//2, head_h//2), (head_w//2 - 4, head_h//2 - 4), 0, 0, 360, 1.0, -1)
    mask = cv2.GaussianBlur(mask, (21, 21), 11)
    mask_3c = np.stack([mask]*3, axis=-1)
    
    # Blend target coordinates
    hx1 = max(0, nx - head_w // 2)
    hx2 = min(1080, hx1 + head_w)
    hy1 = max(0, ny - int(head_h * 0.52))
    hy2 = min(1920, hy1 + head_h)
    
    actual_w = hx2 - hx1
    actual_h = hy2 - hy1
    
    sub_face = resized_face[:actual_h, :actual_w]
    sub_mask = mask_3c[:actual_h, :actual_w]
    
    # Apply to fancam
    fancam_raw[hy1:hy2, hx1:hx2] = (fancam_raw[hy1:hy2, hx1:hx2] * (1.0 - sub_mask) + sub_face * sub_mask).astype(np.uint8)

# 4. Apply Manhwa/Anime Styling to entire frame
gray = cv2.cvtColor(fancam_raw, cv2.COLOR_BGR2GRAY)
gray_blur = cv2.medianBlur(gray, 5)
edges = cv2.adaptiveThreshold(gray_blur, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 9, 3)
color = cv2.bilateralFilter(fancam_raw, d=7, sigmaColor=75, sigmaSpace=75)
edges_rgb = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
anime_styled = cv2.bitwise_and(color, edges_rgb)

# Color boost
hsv = cv2.cvtColor(anime_styled, cv2.COLOR_BGR2HSV).astype(np.float32)
hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 1.25, 0, 255)
hsv[:, :, 2] = np.clip(hsv[:, :, 2] * 1.08, 0, 255)
anime_styled = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

final_comp = cv2.addWeighted(fancam_raw, 0.40, anime_styled, 0.60, 0)
cv2.imwrite(out_img, final_comp, [cv2.IMWRITE_JPEG_QUALITY, 95])
print("Saved face blend to:", out_img)

