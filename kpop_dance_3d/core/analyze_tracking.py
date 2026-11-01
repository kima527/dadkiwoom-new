import cv2
import numpy as np

video_path = r"D:\download\bts_mma_source.mp4"
cap = cv2.VideoCapture(video_path)
total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
fps = cap.get(cv2.CAP_PROP_FPS)
width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

print(f"Total frames: {total_frames}, FPS: {fps}, Res: {width}x{height}")

# Sample every 300 frames (~10 seconds)
samples = range(0, total_frames, 300)
cap.release()
print(f"Sampling points: {len(samples)} timestamps across {total_frames / fps:.1f} seconds")

