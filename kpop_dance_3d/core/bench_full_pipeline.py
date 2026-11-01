import cv2
import numpy as np
import mediapipe as mp
import time

video_path = r"D:\download\bts_mma_source.mp4"
face_path = r"D:\BTS\anime_faces\jungkook_anime_portrait_1793453734020.jpg"

cap = cv2.VideoCapture(video_path)
cap.set(cv2.CAP_PROP_POS_FRAMES, 1500)

mp_pose = mp.solutions.pose
pose = mp_pose.Pose(static_image_mode=False, model_complexity=0, enable_segmentation=True, min_detection_confidence=0.5, min_tracking_confidence=0.5)

anime_full = cv2.imread(face_path)
ah, aw = anime_full.shape[:2]
anime_face = anime_full[int(ah*0.12):int(ah*0.55), int(aw*0.22):int(aw*0.78)]

# Pre-generate spotlight mask (1080x1920)
Y, X = np.ogrid[:1920, :1080]
dist_from_center = np.sqrt(((X - 540) / 450.0)**2 + ((Y - 1100) / 900.0)**2)
spotlight = np.clip(1.0 - (dist_from_center - 0.4) * 0.7, 0.25, 1.0)
spotlight_3c = np.stack([spotlight]*3, axis=-1).astype(np.float32)

t0 = time.time()
num_frames = 20

for i in range(num_frames):
    ret, frame = cap.read()
    if not ret:
        break
    h, w = frame.shape[:2]
    crop_w = int(h * (9.0 / 16.0)) # 1215
    center_x = int(w * 0.50)
    x1 = max(0, center_x - crop_w // 2)
    x2 = min(w, x1 + crop_w)
    cropped = frame[:, x1:x2]
    fancam_raw = cv2.resize(cropped, (1080, 1920), interpolation=cv2.INTER_LINEAR)
    
    # Pose
    rgb = cv2.cvtColor(fancam_raw, cv2.COLOR_BGR2RGB)
    res = pose.process(rgb)
    
    # Face blend
    if res.pose_landmarks:
        lm = res.pose_landmarks.landmark
        nx, ny = int(lm[0].x * 1080), int(lm[0].y * 1920)
        sh_w = abs(int(lm[11].x * 1080) - int(lm[12].x * 1080))
        head_w = int(max(sh_w * 0.95, 60))
        head_h = int(head_w * (anime_face.shape[0] / anime_face.shape[1]))
        resized_face = cv2.resize(anime_face, (head_w, head_h))
        
        mask_f = np.zeros((head_h, head_w), dtype=np.float32)
        cv2.ellipse(mask_f, (head_w//2, head_h//2), (head_w//2 - 6, head_h//2 - 6), 0, 0, 360, 1.0, -1)
        mask_f = cv2.GaussianBlur(mask_f, (21, 21), 0)
        mask_f_3c = np.stack([mask_f]*3, axis=-1)
        
        hx1 = max(0, nx - head_w // 2)
        hx2 = min(1080, hx1 + head_w)
        hy1 = max(0, ny - int(head_h * 0.52))
        hy2 = min(1920, hy1 + head_h)
        aw_act = hx2 - hx1
        ah_act = hy2 - hy1
        if aw_act > 0 and ah_act > 0:
            fancam_raw[hy1:hy2, hx1:hx2] = (fancam_raw[hy1:hy2, hx1:hx2] * (1.0 - mask_f_3c[:ah_act, :aw_act]) + resized_face[:ah_act, :aw_act] * mask_f_3c[:ah_act, :aw_act]).astype(np.uint8)
    
    # Cel-shading (fast approx with bilateral or box filter)
    # Fast color quantization / smoothing:
    color = cv2.pyrMeanShiftFiltering(fancam_raw[::2, ::2], 10, 20) if False else cv2.bilateralFilter(fancam_raw, 5, 50, 50)
    gray = cv2.cvtColor(fancam_raw, cv2.COLOR_BGR2GRAY)
    edges = cv2.adaptiveThreshold(cv2.medianBlur(gray, 5), 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 9, 3)
    edges_rgb = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
    anime_styled = cv2.bitwise_and(color, edges_rgb)
    dancer_art = cv2.addWeighted(fancam_raw, 0.35, anime_styled, 0.65, 0)
    
    # Solo isolation
    if res.segmentation_mask is not None:
        seg_mask = cv2.resize(res.segmentation_mask, (1080, 1920))
        seg_mask = cv2.GaussianBlur(seg_mask, (21, 21), 0)
        seg_mask_3c = np.stack([seg_mask]*3, axis=-1)
        
        bg_blur = cv2.boxFilter(fancam_raw, -1, (41, 41))
        bg_dark = (bg_blur.astype(np.float32) * 0.35 * spotlight_3c).astype(np.uint8)
        
        final_comp = (dancer_art.astype(np.float32) * seg_mask_3c + bg_dark.astype(np.float32) * (1.0 - seg_mask_3c)).astype(np.uint8)
    else:
        final_comp = dancer_art

t1 = time.time()
print(f"Full pipeline benchmark: {num_frames} frames in {t1 - t0:.2f}s ({num_frames / (t1 - t0):.2f} FPS)")
cap.release()
pose.close()

