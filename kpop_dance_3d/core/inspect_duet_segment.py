import cv2
import os

video_path = r"D:\download\bts_mma_source.mp4"
cap = cv2.VideoCapture(video_path)
fps = cap.get(cv2.CAP_PROP_FPS)

out_dir = r"D:\BTS\duet_inspect"
os.makedirs(out_dir, exist_ok=True)

for sec in [8, 12, 16, 20, 24]:
    frame_idx = int(sec * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ret, frame = cap.read()
    if ret:
        small = cv2.resize(frame, (960, 540))
        cv2.imwrite(os.path.join(out_dir, f"frame_{sec}s.jpg"), small)
        print(f"Saved frame at {sec}s")

cap.release()

