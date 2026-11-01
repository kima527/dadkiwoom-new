import cv2
import numpy as np
import os

video_path = r"D:\download\bts_mma_source.mp4"
face_path = r"C:\Users\zoela\.gemini\antigravity\brain\63272223-b3c7-4010-ad97-80ed3a4e19c5\jungkook_anime_portrait_1793453734020.jpg"
out_img = r"C:\Users\zoela\.gemini\antigravity\brain\63272223-b3c7-4010-ad97-80ed3a4e19c5\test_solo_fancam.jpg"

cap = cv2.VideoCapture(video_path)
cap.set(cv2.CAP_PROP_POS_FRAMES, 1500) # At 50s - active dance break
ret, frame = cap.read()
cap.release()

if not ret or frame is None:
    print("Failed to read frame!")
    exit(1)

h, w = frame.shape[:2] # 2160, 3840
print(f"Original Frame: {w}x{h}")

# 9:16 vertical aspect ratio
crop_h = h # 2160 (full height)
crop_w = int(h * (9.0 / 16.0)) # 1215

# Center dancer is around x = 1920
center_x = int(w * 0.50)
x1 = max(0, center_x - crop_w // 2)
x2 = min(w, x1 + crop_w)
if x2 - x1 < crop_w:
    x1 = max(0, x2 - crop_w)

cropped = frame[:, x1:x2]

# Resize to standard Full HD Vertical: 1080x1920
fancam_raw = cv2.resize(cropped, (1080, 1920), interpolation=cv2.INTER_LANCZOS4)

# Apply Anime/Manhwa Cel-Shading Filter to the Body
# 1. Edge detection for crisp manhwa line-art
gray = cv2.cvtColor(fancam_raw, cv2.COLOR_BGR2GRAY)
gray_blur = cv2.medianBlur(gray, 5)
edges = cv2.adaptiveThreshold(gray_blur, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY, 9, 3)

# 2. Bilateral filter for smooth manhwa skin & fabric tones
color = cv2.bilateralFilter(fancam_raw, d=7, sigmaColor=75, sigmaSpace=75)

# 3. Composite cartoon edges with color
edges_rgb = cv2.cvtColor(edges, cv2.COLOR_GRAY2BGR)
anime_styled = cv2.bitwise_and(color, edges_rgb)

# 4. Subtle color boost for vibrant K-pop stage look
hsv = cv2.cvtColor(anime_styled, cv2.COLOR_BGR2HSV).astype(np.float32)
hsv[:, :, 1] = np.clip(hsv[:, :, 1] * 1.25, 0, 255) # Saturation +25%
hsv[:, :, 2] = np.clip(hsv[:, :, 2] * 1.08, 0, 255) # Value +8%
anime_styled = cv2.cvtColor(hsv.astype(np.uint8), cv2.COLOR_HSV2BGR)

# Soft blend between original crisp details and anime styling (40% anime, 60% realistic motion)
final_composite = cv2.addWeighted(fancam_raw, 0.45, anime_styled, 0.55, 0)

# Save test image
cv2.imwrite(out_img, final_composite, [cv2.IMWRITE_JPEG_QUALITY, 95])
print(f"Saved test solo fancam image to: {out_img}")

