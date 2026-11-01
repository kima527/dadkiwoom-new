import cv2
import numpy as np

video_path = r"D:\download\bts_mma_source.mp4"
cap = cv2.VideoCapture(video_path)

# Let's read sequentially every 600 frames (~20 sec)
total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
print(f"Total frames: {total_frames}")

for f_idx in range(300, total_frames, 600):
    cap.set(cv2.CAP_PROP_POS_FRAMES, f_idx)
    ret, frame = cap.read()
    if not ret:
        break
    # Find brightest / motion center or person in the middle
    # Check center slice: [1000:3000]
    h, w = frame.shape[:2]
    # Small thumbnail
    thumb = cv2.resize(frame, (960, 540))
    # In 960 width, center 50% is [240:720], corresponding to [960:2880] in 3840
    print(f"Frame {f_idx}: Read OK ({w}x{h})")

cap.release()
print("Check completed.")

