import cv2
import numpy as np
import mediapipe as mp

video_path = r"D:\download\bts_mma_source.mp4"
face_path = r"D:\BTS\anime_faces\jungkook_anime_portrait_1793453734020.jpg"
out_img = r"C:\Users\zoela\.gemini\antigravity\brain\63272223-b3c7-4010-ad97-80ed3a4e19c5\test_refined_solo.jpg"

cap = cv2.VideoCapture(video_path)
cap.set(cv2.CAP_PROP_POS_FRAMES, 1500)
ret, frame = cap.read()
cap.release()

h, w = frame.shape[:2]
crop_w = int(h * (9.0 / 16.0))
center_x = int(w * 0.50)
x1 = max(0, center_x - crop_w // 2)
x2 = min(w, x1 + crop_w)
cropped = frame[:, x1:x2]
proc_w, proc_h = 540, 960
fancam_proc = cv2.resize(cropped, (proc_w, proc_h), interpolation=cv2.INTER_LINEAR)

anime_full = cv2.imread(face_path)
ah, aw = anime_full.shape[:2]
anime_face = anime_full[int(ah*0.12):int(ah*0.55), int(aw*0.22):int(aw*0.78)]

mp_pose = mp.solutions.pose
with mp_pose.Pose(static_image_mode=True, enable_segmentation=True, min_detection_confidence=0.5) as pose:
    res = pose.process(cv2.cvtColor(fancam_proc, cv2.COLOR_BGR2RGB))

if res.pose_landmarks:
    lm = res.pose_landmarks.landmark
    nose = lm[0]
    l_sh = lm[11]
    r_sh = lm[12]
    l_ear = lm[7]
    r_ear = lm[8]
    
    # Check head pose orientation (frontal vs profile)
    ear_dist = abs(l_ear.x - r_ear.x)
    face_frontal_score = np.clip((ear_dist - 0.03) / 0.08, 0.2, 1.0)
    
    nx, ny = int(nose.x * proc_w), int(nose.y * proc_h)
    sh_w = abs(int(l_sh.x * proc_w) - int(r_sh.x * proc_w))
    head_w = int(max(sh_w * 0.90, 25))
    head_h = int(head_w * (anime_face.shape[0] / anime_face.shape[1]))
    resized_face = cv2.resize(anime_face, (head_w, head_h))

    # Seamless skin color matching
    # Sample real neck / chin color
    sample_y = min(proc_h - 1, ny + int(head_h * 0.45))
    neck_color = fancam_proc[sample_y, max(0, min(proc_w-1, nx))].astype(np.float32)

    mask_f = np.zeros((head_h, head_w), dtype=np.float32)
    cv2.ellipse(mask_f, (head_w//2, head_h//2), (head_w//2 - 4, head_h//2 - 4), 0, 0, 360, face_frontal_score * 0.85, -1)
    mask_f = cv2.GaussianBlur(mask_f, (15, 15), 0)
    mask_f_3c = np.stack([mask_f]*3, axis=-1)

    hx1 = max(0, nx - head_w // 2)
    hx2 = min(proc_w, hx1 + head_w)
    hy1 = max(0, ny - int(head_h * 0.52))
    hy2 = min(proc_h, hy1 + head_h)
    aw_act = hx2 - hx1
    ah_act = hy2 - hy1
    if aw_act > 0 and ah_act > 0:
        fancam_proc[hy1:hy2, hx1:hx2] = (
            fancam_proc[hy1:hy2, hx1:hx2] * (1.0 - mask_f_3c[:ah_act, :aw_act]) +
            resized_face[:ah_act, :aw_act] * mask_f_3c[:ah_act, :aw_act]
        ).astype(np.uint8)

# Cel-shading filter
gray = cv2.cvtColor(fancam_proc, cv2.COLOR_BGR2GRAY)
edges = cv2.adaptiveThreshold(cv2.medianBlur(gray, 3), 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 7, 2)
color = cv2.bilateralFilter(fancam_proc, 5, 40, 40)
edges_rgb = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
anime_styled = cv2.bitwise_and(color, edges_rgb)

hsv = cv2.cvtColor(anime_styled, cv2.COLOR_BGR2HSV).astype(np.float32)
hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 1.25, 0, 255)
hsv[:, :, 2] = np.clip(hsv[:, :, 2] * 1.08, 0, 255)
anime_styled = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)
dancer_art = cv2.addWeighted(fancam_proc, 0.35, anime_styled, 0.65, 0)

# Clean segmentation with thresholding
if res.segmentation_mask is not None:
    # Threshold mask to strictly keep foreground dancer
    raw_mask = res.segmentation_mask
    clean_mask = np.where(raw_mask > 0.6, 1.0, np.where(raw_mask > 0.3, (raw_mask - 0.3) / 0.3, 0.0)).astype(np.float32)
    clean_mask = cv2.GaussianBlur(clean_mask, (15, 15), 0)
    clean_mask_3c = np.stack([clean_mask]*3, axis=-1)

    Y, X = np.ogrid[:proc_h, :proc_w]
    dist_from_center = np.sqrt(((X - proc_w//2) / (proc_w * 0.42))**2 + ((Y - int(proc_h * 0.58)) / (proc_h * 0.48))**2)
    spotlight = np.clip(1.0 - (dist_from_center - 0.35) * 0.8, 0.20, 1.0)
    spotlight_3c = np.stack([spotlight]*3, axis=-1).astype(np.float32)

    bg_blur = cv2.boxFilter(fancam_proc, -1, (25, 25))
    bg_dark = (bg_blur.astype(np.float32) * 0.30 * spotlight_3c).astype(np.uint8)

    final_frame = (dancer_art.astype(np.float32) * clean_mask_3c + bg_dark.astype(np.float32) * (1.0 - clean_mask_3c)).astype(np.uint8)
else:
    final_frame = dancer_art

final_1080 = cv2.resize(final_frame, (1080, 1920), interpolation=cv2.INTER_LANCZOS4)
cv2.imwrite(out_img, final_1080, [cv2.IMWRITE_JPEG_QUALITY, 95])
print("Saved refined solo image:", out_img)

