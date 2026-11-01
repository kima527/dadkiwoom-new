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

# Pre-generate spotlight mask (540x960)
Y, X = np.ogrid[:960, :540]
dist_from_center = np.sqrt(((X - 270) / 225.0)**2 + ((Y - 550) / 450.0)**2)
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
    
    # Process at 540x960 (4x less pixels, identical visual quality when scaled to 1080x1920)
    fancam = cv2.resize(cropped, (540, 960), interpolation=cv2.INTER_LINEAR)
    
    rgb = cv2.cvtColor(fancam, cv2.COLOR_BGR2RGB)
    res = pose.process(rgb)
    
    if res.pose_landmarks:
        lm = res.pose_landmarks.landmark
        nx, ny = int(lm[0].x * 540), int(lm[0].y * 960)
        sh_w = abs(int(lm[11].x * 540) - int(lm[12].x * 540))
        head_w = int(max(sh_w * 0.95, 30))
        head_h = int(head_w * (anime_face.shape[0] / anime_face.shape[1]))
        resized_face = cv2.resize(anime_face, (head_w, head_h))
        
        mask_f = np.zeros((head_h, head_w), dtype=np.float32)
        cv2.ellipse(mask_f, (head_w//2, head_h//2), (head_w//2 - 3, head_h//2 - 3), 0, 0, 360, 1.0, -1)
        mask_f = cv2.GaussianBlur(mask_f, (11, 11), 0)
        mask_f_3c = np.stack([mask_f]*3, axis=-1)
        
        hx1 = max(0, nx - head_w // 2)
        hx2 = min(540, hx1 + head_w)
        hy1 = max(0, ny - int(head_h * 0.52))
        hy2 = min(960, hy1 + head_h)
        aw_act = hx2 - hx1
        ah_act = hy2 - hy1
        if aw_act > 0 and ah_act > 0:
            fancam[hy1:hy2, hx1:hx2] = (fancam[hy1:hy2, hx1:hx2] * (1.0 - mask_f_3c[:ah_act, :aw_act]) + resized_face[:ah_act, :aw_act] * mask_f_3c[:ah_act, :aw_act]).astype(np.uint8)
            
    # Cel-shading
    gray = cv2.cvtColor(fancam, cv2.COLOR_BGR2GRAY)
    edges = cv2.adaptiveThreshold(cv2.medianBlur(gray, 3), 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 7, 2)
    color = cv2.bilateralFilter(fancam, 5, 40, 40)
    edges_rgb = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
    anime_styled = cv2.bitwise_and(color, edges_rgb)
    dancer_art = cv2.addWeighted(fancam, 0.35, anime_styled, 0.65, 0)
    
    if res.segmentation_mask is not None:
        seg_mask = cv2.resize(res.segmentation_mask, (540, 960))
        seg_mask = cv2.GaussianBlur(seg_mask, (15, 15), 0)
        seg_mask_3c = np.stack([seg_mask]*3, axis=-1)
        
        bg_blur = cv2.boxFilter(fancam, -1, (21, 21))
        bg_dark = (bg_blur.astype(np.float32) * 0.35 * spotlight_3c).astype(np.uint8)
        
        final_540 = (dancer_art.astype(np.float32) * seg_mask_3c + bg_dark.astype(np.float32) * (1.0 - seg_mask_3c)).astype(np.uint8)
    else:
        final_540 = dancer_art
        
    # Upscale to 1080x1920 for final output
    final_1080 = cv2.resize(final_540, (1080, 1920), interpolation=cv2.INTER_LINEAR)

t1 = time.time()
print(f"Optimized pipeline benchmark: {num_frames} frames in {t1 - t0:.2f}s ({num_frames / (t1 - t0):.2f} FPS)")
cap.release()
pose.close()

