import cv2
import numpy as np
import mediapipe as mp
import time

video_path = r"D:\download\bts_mma_source.mp4"
face_path = r"D:\BTS\anime_faces\jungkook_anime_portrait_1793453734020.jpg"

cap = cv2.VideoCapture(video_path)
cap.set(cv2.CAP_PROP_POS_FRAMES, 1000)

mp_pose = mp.solutions.pose
pose = mp_pose.Pose(static_image_mode=False, model_complexity=0, enable_segmentation=True, min_detection_confidence=0.5, min_tracking_confidence=0.5)

# Pre-load face
anime_full = cv2.imread(face_path)
ah, aw = anime_full.shape[:2]
anime_face = anime_full[int(ah*0.12):int(ah*0.55), int(aw*0.22):int(aw*0.78)]

t0 = time.time()
num_frames = 30
for i in range(num_frames):
    ret, frame = cap.read()
    if not ret:
        break
    h, w = frame.shape[:2]
    crop_w = int(h * (9.0 / 16.0))
    center_x = int(w * 0.50)
    x1 = max(0, center_x - crop_w // 2)
    x2 = min(w, x1 + crop_w)
    cropped = frame[:, x1:x2]
    fancam = cv2.resize(cropped, (540, 960), interpolation=cv2.INTER_LINEAR) # Process at 540x960 for blazing speed, or 1080x1920
    
    # Process pose
    rgb = cv2.cvtColor(fancam, cv2.COLOR_BGR2RGB)
    res = pose.process(rgb)

t1 = time.time()
fps = num_frames / (t1 - t0)
print(f"Benchmark finished: {num_frames} frames in {t1 - t0:.2f}s ({fps:.2f} fps)")
cap.release()
pose.close()

