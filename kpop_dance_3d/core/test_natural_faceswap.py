import cv2
import numpy as np
import mediapipe as mp
import os

video_path = r"D:\download\bts_mma_source.mp4"
face_path = r"D:\BTS\anime_faces\jungkook_anime_portrait_1793453734020.jpg"
out_img = r"C:\Users\zoela\.gemini\antigravity\brain\63272223-b3c7-4010-ad97-80ed3a4e19c5\test_natural_face.jpg"

cap = cv2.VideoCapture(video_path)
cap.set(cv2.CAP_PROP_POS_FRAMES, 1500)
ret, frame = cap.read()
cap.release()

h, w = frame.shape[:2]
crop_w = int(h * (9.0 / 16.0)) # 1215
center_x = int(w * 0.50)
x1 = max(0, center_x - crop_w // 2)
x2 = min(w, x1 + crop_w)
cropped = frame[:, x1:x2].copy()

# 1. 8-Head Proportion Adjustment on Real Body
# Gently stretch the lower body (legs) vertically by ~7% while keeping upper body/head normal
out_h, out_w = 1920, 1080
resized_raw = cv2.resize(cropped, (out_w, out_h), interpolation=cv2.INTER_LANCZOS4)

# Apply subtle leg lengthening: 
# Top 40% (head to chest) unchanged, 40%-95% (legs) slightly elongated
y_indices = np.arange(out_h, dtype=np.float32)
# Map y: for y > 0.4*H, apply slight compression in sampling -> creates leg elongation
split_y = out_h * 0.42
src_y = np.where(y_indices < split_y, 
                 y_indices, 
                 split_y + (y_indices - split_y) * 0.94).astype(np.float32)
src_x = np.tile(np.arange(out_w, dtype=np.float32), (out_h, 1))
src_y_grid = np.tile(src_y[:, np.newaxis], (1, out_w))
proportioned_body = cv2.remap(resized_raw, src_x, src_y_grid, interpolation=cv2.INTER_LINEAR)

# 2. Face Detection & Tracking with MediaPipe Face Mesh
mp_face_mesh = mp.solutions.face_mesh
with mp_face_mesh.FaceMesh(static_image_mode=True, max_num_faces=1, refine_landmarks=True) as fm:
    rgb = cv2.cvtColor(proportioned_body, cv2.COLOR_BGR2RGB)
    res = fm.process(rgb)

if res.multi_face_landmarks:
    landmarks = res.multi_face_landmarks[0].landmark
    # Key face points:
    # 33: left eye outer, 263: right eye outer, 1: nose tip, 61: mouth left, 291: mouth right, 152: chin
    pts = np.array([(int(lm.x * out_w), int(lm.y * out_h)) for lm in landmarks])
    
    le_x, le_y = pts[33]
    re_x, re_y = pts[263]
    nose_x, nose_y = pts[1]
    chin_x, chin_y = pts[152]
    
    # Calculate face angle (tilt)
    dY = re_y - le_y
    dX = re_x - le_x
    angle = np.degrees(np.arctan2(dY, dX))
    eye_dist = np.sqrt(dX**2 + dY**2)
    
    print(f"Face detected: eyes dist={eye_dist:.1f}, angle={angle:.1f} deg, chin=({chin_x}, {chin_y})")
    
    # 3. Load Anime Face and Align with Affine Transform
    anime_img = cv2.imread(face_path)
    ah, aw = anime_img.shape[:2]
    
    # Anime face eye coordinates in the portrait:
    # In jungkook_anime_portrait:
    # left eye ~ (aw * 0.42, ah * 0.31), right eye ~ (aw * 0.58, ah * 0.31)
    src_le = np.array([aw * 0.42, ah * 0.31], dtype=np.float32)
    src_re = np.array([aw * 0.58, ah * 0.31], dtype=np.float32)
    src_nose = np.array([aw * 0.50, ah * 0.38], dtype=np.float32)
    
    dst_le = np.array([le_x, le_y], dtype=np.float32)
    dst_re = np.array([re_x, re_y], dtype=np.float32)
    dst_nose = np.array([nose_x, nose_y], dtype=np.float32)
    
    src_tri = np.float32([src_le, src_re, src_nose])
    dst_tri = np.float32([dst_le, dst_re, dst_nose])
    
    M = cv2.getAffineTransform(src_tri, dst_tri)
    warped_anime = cv2.warpAffine(anime_img, M, (out_w, out_h), flags=cv2.INTER_LANCZOS4)
    
    # Create face hull mask from facial landmarks
    # Indices 10 (forehead), 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152 (chin),
    # 148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109
    hull_idx = [10, 338, 297, 332, 284, 251, 389, 356, 454, 323, 361, 288, 397, 365, 379, 378, 400, 377, 152,
                148, 176, 149, 150, 136, 172, 58, 132, 93, 234, 127, 162, 21, 54, 103, 67, 109]
    hull_pts = np.array([pts[i] for i in hull_idx if i < len(pts)], dtype=np.int32)
    
    mask = np.zeros((out_h, out_w), dtype=np.uint8)
    cv2.fillConvexPoly(mask, hull_pts, 255)
    
    # Smooth & shrink mask slightly so jawline and hairline blend naturally
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    mask_eroded = cv2.erode(mask, kernel, iterations=1)
    mask_blurred = cv2.GaussianBlur(mask_eroded, (35, 35), 0)
    
    # Use Seamless Clone (Poisson Blending) for 100% lighting & skin tone matching!
    face_center = (int(nose_x), int((le_y + chin_y) // 2))
    try:
        blended = cv2.seamlessClone(warped_anime, proportioned_body, mask_eroded, face_center, cv2.NORMAL_CLONE)
    except Exception as e:
        print("Seamless clone fallback:", e)
        alpha = (mask_blurred.astype(np.float32) / 255.0)[:, :, np.newaxis]
        blended = (warped_anime.astype(np.float32) * alpha + proportioned_body.astype(np.float32) * (1 - alpha)).astype(np.uint8)
        
    final_output = blended
else:
    print("No face detected, keeping proportioned body")
    final_output = proportioned_body

cv2.imwrite(out_img, final_output, [cv2.IMWRITE_JPEG_QUALITY, 95])
print("Saved natural face swapped test image:", out_img)

