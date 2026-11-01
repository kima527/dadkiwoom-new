import cv2
import os

video_path = r"D:\download\bts_mma_source.mp4"
cap = cv2.VideoCapture(video_path)
fps = cap.get(cv2.CAP_PROP_FPS)

timestamps = [10, 30, 60, 90, 120, 150, 180, 210]
out_dir = r"D:\BTS\check_timestamps"
os.makedirs(out_dir, exist_ok=True)

for ts in timestamps:
    frame_idx = int(ts * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ret, frame = cap.read()
    if ret:
        small = cv2.resize(frame, (640, 360))
        cv2.imwrite(os.path.join(out_dir, f"snap_{ts}s.jpg"), small)
        print(f"Saved snap at {ts}s")

cap.release()

