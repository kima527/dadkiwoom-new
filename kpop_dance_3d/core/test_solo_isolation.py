import cv2
import numpy as np
import mediapipe as mp

video_path = r"D:\download\bts_mma_source.mp4"
face_path = r"D:\BTS\anime_faces\jungkook_anime_portrait_1793453734020.jpg"
out_img = r"D:\BTS\test_solo_isolated.jpg"

cap = cv2.VideoCapture(video_path)
cap.set(cv2.CAP_PROP_POS_FRAMES, 1500)
ret, frame = cap.read()
cap.release()

h, w = frame.shape[:2]
crop_w = int(h * (9.0 / 16.0)) # 1215
center_x = int(w * 0.50)
x1 = max(0, center_x - crop_w // 2)
x2 = min(w, x1 + crop_w)
cropped = frame[:, x1:x2]
fancam_raw = cv2.resize(cropped, (1080, 1920), interpolation=cv2.INTER_LANCZOS4)

mp_pose = mp.solutions.pose
with mp_pose.Pose(static_image_mode=True, enable_segmentation=True, min_detection_confidence=0.5) as pose:
    results = pose.process(cv2.cvtColor(fancam_raw, cv2.COLOR_BGR2RGB))

if results.pose_landmarks and results.segmentation_mask is not None:
    landmarks = results.pose_landmarks.landmark
    nose = landmarks[0]
    l_sh = landmarks[11]
    r_sh = landmarks[12]
    nx, ny = int(nose.x * 1080), int(nose.y * 1920)
    sh_w = abs(int(l_sh.x * 1080) - int(r_sh.x * 1080))
    
    # 1. Overlay Anime Face
    anime_full = cv2.imread(face_path)
    ah, aw = anime_full.shape[:2]
    anime_face = anime_full[int(ah*0.12):int(ah*0.55), int(aw*0.22):int(aw*0.78)]
    
    head_w = int(sh_w * 0.95)
    head_h = int(head_w * (anime_face.shape[0] / anime_face.shape[1]))
    resized_face = cv2.resize(anime_face, (head_w, head_h), interpolation=cv2.INTER_LANCZOS4)
    
    mask_face = np.zeros((head_h, head_w), dtype=np.float32)
    cv2.ellipse(mask_face, (head_w//2, head_h//2), (head_w//2 - 6, head_h//2 - 6), 0, 0, 360, 1.0, -1)
    mask_face = cv2.GaussianBlur(mask_face, (25, 25), 11)
    mask_face_3c = np.stack([mask_face]*3, axis=-1)
    
    hx1 = max(0, nx - head_w // 2)
    hx2 = min(1080, hx1 + head_w)
    hy1 = max(0, ny - int(head_h * 0.52))
    hy2 = min(1920, hy1 + head_h)
    
    aw_act = hx2 - hx1
    ah_act = hy2 - hy1
    fancam_raw[hy1:hy2, hx1:hx2] = (fancam_raw[hy1:hy2, hx1:hx2] * (1.0 - mask_face_3c[:ah_act, :aw_act]) + resized_face[:ah_act, :aw_act] * mask_face_3c[:ah_act, :aw_act]).astype(np.uint8)

# 2. Cel-shading manhwa filter
gray = cv2.cvtColor(fancam_raw, cv2.COLOR_BGR2GRAY)
gray_blur = cv2.medianBlur(gray, 5)
edges = cv2.adaptiveThreshold(gray_blur, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 9, 3)
color = cv2.bilateralFilter(fancam_raw, d=7, sigmaColor=75, sigmaSpace=75)
edges_rgb = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
anime_styled = cv2.bitwise_and(color, edges_rgb)

hsv = cv2.cvtColor(anime_styled, cv2.COLOR_BGR2HSV).astype(np.float32)
hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 1.30, 0, 255)
hsv[:, :, 2] = np.clip(hsv[:, :, 2] * 1.10, 0, 255)
anime_styled = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
dancer_art = cv2.addWeighted(fancam_raw, 0.35, anime_styled, 0.65, 0)

# 3. Solo Isolation: Use segmentation mask
# results.segmentation_mask is (1920, 1080) float32 in [0, 1]
seg_mask = cv2.resize(results.segmentation_mask, (1080, 1920))
# Smooth and feather segmentation
seg_mask = cv2.GaussianBlur(seg_mask, (31, 31), 0)
seg_mask_3c = np.stack([seg_mask]*3, axis=-1)

# Dim and blur background to eliminate background dancers into a sleek studio bokeh
bg_blurred = cv2.GaussianBlur(fancam_raw, (65, 65), 0)
bg_darkened = (bg_blurred.astype(np.float32) * 0.35).astype(np.uint8)

# Center spotlight effect on the studio floor
Y, X = np.ogrid[:1920, :1080]
dist_from_center = np.sqrt(((X - 540) / 450.0)**2 + ((Y - 1100) / 900.0)**2)
spotlight = np.clip(1.0 - (dist_from_center - 0.4) * 0.7, 0.25, 1.0)
spotlight_3c = np.stack([spotlight]*3, axis=-1)
bg_darkened = (bg_darkened.astype(np.float32) * spotlight_3c).astype(np.uint8)

# Final Solo Dance Composite: Isolated Dancer on Spotlight Stage
solo_composite = (dancer_art.astype(np.float32) * seg_mask_3c + bg_darkened.astype(np.float32) * (1.0 - seg_mask_3c)).astype(np.uint8)

cv2.imwrite(out_img, solo_composite, [cv2.IMWRITE_JPEG_QUALITY, 95])
print("Saved isolated solo dancer image:", out_img)
