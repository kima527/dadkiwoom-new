import os
import sys
import time
import argparse
import subprocess
import cv2
import numpy as np
import mediapipe as mp

def main():
    parser = argparse.ArgumentParser(description="Render BTS Solo Webtoon Fancam")
    parser.add_argument("--source", default=r"D:\download\bts_mma_source.mp4", help="Source 4K video")
    parser.add_argument("--face", default=r"D:\BTS\anime_faces\jungkook_anime_portrait_1793453734020.jpg", help="Anime face portrait")
    parser.add_argument("--out", default=r"D:\BTS\BTS_Dynamite_Solo_DanceBreak_Full.mp4", help="Output MP4 path")
    parser.add_argument("--start_frame", type=int, default=0, help="Start frame index")
    parser.add_argument("--num_frames", type=int, default=-1, help="Number of frames to render (-1 for all)")
    parser.add_argument("--width", type=int, default=1080, help="Output width")
    parser.add_argument("--height", type=int, default=1920, help="Output height")
    args = parser.parse_args()

    ffmpeg_bin = r"C:\Users\zoela\AppData\Local\Programs\Python\Python312\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"
    if not os.path.exists(ffmpeg_bin):
        ffmpeg_bin = "ffmpeg"

    if not os.path.exists(args.source):
        print(f"Error: Source video not found: {args.source}", flush=True)
        sys.exit(1)
    if not os.path.exists(args.face):
        print(f"Error: Face portrait not found: {args.face}", flush=True)
        sys.exit(1)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)

    # Load anime face
    anime_full = cv2.imread(args.face)
    if anime_full is None:
        print("Error: Could not read anime face image.", flush=True)
        sys.exit(1)
    ah, aw = anime_full.shape[:2]
    anime_face = anime_full[int(ah*0.12):int(ah*0.55), int(aw*0.22):int(aw*0.78)]

    # Open video capture
    cap = cv2.VideoCapture(args.source)
    total_src_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"Source video: {src_w}x{src_h} @ {fps:.2f} FPS ({total_src_frames} total frames)", flush=True)

    start_frame = max(0, min(args.start_frame, total_src_frames - 1))
    if args.num_frames > 0:
        end_frame = min(start_frame + args.num_frames, total_src_frames)
    else:
        end_frame = total_src_frames
    frames_to_process = end_frame - start_frame
    print(f"Processing frames {start_frame} to {end_frame} ({frames_to_process} frames, ~{frames_to_process/fps:.1f}s)", flush=True)

    if start_frame > 0:
        cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)
    start_sec = start_frame / fps
    dur_sec = frames_to_process / fps

    out_w, out_h = args.width, args.height
    proc_w, proc_h = 540, 960

    # Stage spotlight mask
    Y, X = np.ogrid[:proc_h, :proc_w]
    dist_from_center = np.sqrt(((X - proc_w//2) / (proc_w * 0.42))**2 + ((Y - int(proc_h * 0.58)) / (proc_h * 0.48))**2)
    spotlight = np.clip(1.0 - (dist_from_center - 0.35) * 0.8, 0.20, 1.0)
    spotlight_3c = np.stack([spotlight]*3, axis=-1).astype(np.float32)

    temp_video_only = args.out + ".temp.mp4"
    ffmpeg_cmd = [
        ffmpeg_bin,
        "-y",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-s", f"{out_w}x{out_h}",
        "-pix_fmt", "bgr24",
        "-r", f"{fps}",
        "-i", "-",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "21",
        "-pix_fmt", "yuv420p",
        temp_video_only
    ]
    pipe = subprocess.Popen(ffmpeg_cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    mp_pose = mp.solutions.pose
    pose = mp_pose.Pose(
        static_image_mode=False,
        model_complexity=0,
        enable_segmentation=True,
        min_detection_confidence=0.5,
        min_tracking_confidence=0.5
    )

    crop_h = src_h
    crop_w = int(src_h * (9.0 / 16.0)) # 1215 in 4K
    smooth_center_x = src_w * 0.50

    t_start = time.time()
    last_head_w = 40
    last_head_h = 50

    print("Pipeline running...", flush=True)
    for idx in range(frames_to_process):
        ret, frame = cap.read()
        if not ret or frame is None:
            print(f"End of stream reached at frame {start_frame + idx}.", flush=True)
            break

        # Dynamic Gimbal Pan (Smooth follow center dancer)
        center_x = int(smooth_center_x)
        x1 = max(0, center_x - crop_w // 2)
        x2 = min(src_w, x1 + crop_w)
        if x2 - x1 < crop_w:
            x1 = max(0, x2 - crop_w)

        cropped = frame[:, x1:x2]
        fancam_proc = cv2.resize(cropped, (proc_w, proc_h), interpolation=cv2.INTER_LINEAR)

        # MediaPipe pose & segmentation
        rgb = cv2.cvtColor(fancam_proc, cv2.COLOR_BGR2RGB)
        res = pose.process(rgb)

        # 1. Overlay Anime Face
        if res.pose_landmarks:
            lm = res.pose_landmarks.landmark
            nose = lm[0]
            l_sh = lm[11]
            r_sh = lm[12]
            l_ear = lm[7]
            r_ear = lm[8]

            # Orientation check
            ear_dist = abs(l_ear.x - r_ear.x)
            face_frontal_score = np.clip((ear_dist - 0.03) / 0.08, 0.2, 1.0)

            # Update smooth gimbal center towards dancer
            dancer_screen_x = int(nose.x * proc_w)
            global_dancer_x = x1 + int((nose.x * crop_w))
            smooth_center_x = smooth_center_x * 0.95 + global_dancer_x * 0.05

            nx, ny = dancer_screen_x, int(nose.y * proc_h)
            sh_w = abs(int(l_sh.x * proc_w) - int(r_sh.x * proc_w))
            if sh_w > 15:
                head_w = int(max(sh_w * 0.90, 25))
                head_h = int(head_w * (anime_face.shape[0] / anime_face.shape[1]))
                last_head_w, last_head_h = head_w, head_h
            else:
                head_w, head_h = last_head_w, last_head_h

            resized_face = cv2.resize(anime_face, (head_w, head_h))
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

        # 2. Cel-Shading Manhwa Styling
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

        # 3. Solo Isolation (Stage Spotlight & Background Dimming)
        if res.segmentation_mask is not None:
            raw_mask = res.segmentation_mask
            clean_mask = np.where(raw_mask > 0.6, 1.0, np.where(raw_mask > 0.3, (raw_mask - 0.3) / 0.3, 0.0)).astype(np.float32)
            clean_mask = cv2.GaussianBlur(clean_mask, (15, 15), 0)
            clean_mask_3c = np.stack([clean_mask]*3, axis=-1)

            bg_blur = cv2.boxFilter(fancam_proc, -1, (25, 25))
            bg_dark = (bg_blur.astype(np.float32) * 0.30 * spotlight_3c).astype(np.uint8)

            final_frame = (dancer_art.astype(np.float32) * clean_mask_3c + bg_dark.astype(np.float32) * (1.0 - clean_mask_3c)).astype(np.uint8)
        else:
            final_frame = dancer_art

        # 4. Upscale to 1080x1920 Full HD
        final_1080 = cv2.resize(final_frame, (out_w, out_h), interpolation=cv2.INTER_LINEAR)

        # Pipe raw frame to FFmpeg
        pipe.stdin.write(final_1080.tobytes())

        if (idx + 1) % 50 == 0 or idx == frames_to_process - 1:
            elapsed = time.time() - t_start
            cur_fps = (idx + 1) / elapsed
            eta = (frames_to_process - (idx + 1)) / cur_fps if cur_fps > 0 else 0
            print(f"Rendered [{idx+1}/{frames_to_process}] ({((idx+1)/frames_to_process)*100:.1f}%) | Speed: {cur_fps:.2f} FPS | ETA: {eta/60:.1f}m", flush=True)

    # Finalize video pipe
    pipe.stdin.close()
    pipe.wait()
    cap.release()
    pose.close()

    print("Video encoding completed. Muxing high-definition audio...", flush=True)
    mux_cmd = [
        ffmpeg_bin,
        "-y",
        "-ss", f"{start_sec:.3f}",
        "-t", f"{dur_sec:.3f}",
        "-i", args.source,
        "-i", temp_video_only,
        "-map", "1:v:0",
        "-map", "0:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "320k",
        "-shortest",
        args.out
    ]
    subprocess.run(mux_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    if os.path.exists(temp_video_only):
        try:
            os.remove(temp_video_only)
        except Exception:
            pass

    out_size_mb = os.path.getsize(args.out) / (1024 * 1024)
    print(f"SUCCESS: Rendered BTS Solo Fancam -> {args.out} ({out_size_mb:.2f} MB)", flush=True)

if __name__ == "__main__":
    main()
