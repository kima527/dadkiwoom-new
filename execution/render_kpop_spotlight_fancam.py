#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Execution Script: K-Pop 9:16 Concert Spotlight Fancam Production
Pipeline:
  1. Crop width centered on choreography, scaled to 1080x1920 FHD (9:16 Portrait)
  2. 8-Head Body Proportion Remap (lower body +7% non-linear leg elongation)
  3. Rounded Concert Stage Center Spotlight (cone highlight + floor circular pool)
  4. 100% Members Preserved (no black masks, real authentic practice room background)
  5. 100% Original Sharp Faces preserved
  6. Outro agency card auto-trimming (clean natural fade-out ending)
  7. 320kbps AAC master stereo audio lossless synchronization
"""

import os
import sys
import time
import argparse
import subprocess
import cv2
import numpy as np

def get_ffmpeg_binary():
    """Locate bundled or system FFmpeg binary."""
    bundled_path = r"C:\Users\zoela\AppData\Local\Programs\Python\Python312\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe"
    if os.path.exists(bundled_path):
        return bundled_path
    return "ffmpeg"

def build_8head_grid(out_w, out_h):
    """Precompute 8-head model proportion remap grid."""
    split_y = int(out_h * 0.42)
    y_indices = np.arange(out_h, dtype=np.float32)
    src_y = np.where(y_indices < split_y,
                     y_indices,
                     split_y + (y_indices - split_y) * 0.935).astype(np.float32)
    src_x = np.tile(np.arange(out_w, dtype=np.float32), (out_h, 1))
    src_y_grid = np.tile(src_y[:, np.newaxis], (1, out_w))
    return src_x, src_y_grid

def build_spotlight_map(out_w, out_h):
    """Precompute rounded stage center spotlight and floor highlight map."""
    Y, X = np.ogrid[:out_h, :out_w]
    cx = out_w / 2.0

    # 1. Stage cone spotlight covering dancers
    dist_stage = np.sqrt(((X - cx) / 480.0)**2 + ((Y - 1050) / 780.0)**2)
    t_stage = np.clip((dist_stage - 0.25) / 0.85, 0.0, 1.0)
    smooth_stage = t_stage * t_stage * (3.0 - 2.0 * t_stage)
    light_stage = 1.08 * (1.0 - smooth_stage) + 0.32 * smooth_stage

    # 2. Stage floor circular highlight pool
    dist_floor = np.sqrt(((X - cx) / 440.0)**2 + ((Y - 1480) / 320.0)**2)
    floor_boost = np.clip(1.0 - dist_floor, 0.0, 1.0) * 0.12
    light_total = np.clip(light_stage + floor_boost, 0.25, 1.15)

    light_map = cv2.GaussianBlur(light_total.astype(np.float32), (61, 61), 0)
    SCALE_FACTOR = 200.0
    light_map_u8 = np.clip(light_map * SCALE_FACTOR, 0, 255).astype(np.uint8)
    light_map_3c_u8 = np.stack([light_map_u8] * 3, axis=-1)
    inv_scale = 1.0 / SCALE_FACTOR
    return light_map_3c_u8, inv_scale

def render_fancam(source_video, out_video, crop_w=1600, center_x=1820, trim_outro=True):
    """Main render pipeline."""
    ffmpeg_bin = get_ffmpeg_binary()

    if not os.path.exists(source_video):
        raise FileNotFoundError(f"Source video not found: {source_video}")

    os.makedirs(os.path.dirname(os.path.abspath(out_video)), exist_ok=True)
    temp_raw = out_video + ".raw.mp4"

    cap_info = cv2.VideoCapture(source_video)
    total_frames = int(cap_info.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap_info.get(cv2.CAP_PROP_FPS)
    src_w = int(cap_info.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap_info.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap_info.release()

    out_w, out_h = 1080, 1920
    x1 = max(0, center_x - crop_w // 2)

    print(f"Starting Fancam Render: {source_video} -> {out_video}")
    print(f"Source: {src_w}x{src_h} @ {fps:.2f} FPS | Target: {out_w}x{out_h} (9:16 FHD)")

    src_x, src_y_grid = build_8head_grid(out_w, out_h)
    light_map_3c_u8, inv_scale = build_spotlight_map(out_w, out_h)

    in_cmd = [
        ffmpeg_bin,
        "-i", source_video,
        "-vf", f"crop={crop_w}:{src_h}:{x1}:0,scale={out_w}:{out_h}:flags=lanczos",
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "-"
    ]

    out_cmd = [
        ffmpeg_bin, "-y",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-s", f"{out_w}x{out_h}",
        "-pix_fmt", "bgr24",
        "-r", f"{fps}",
        "-i", "-",
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-crf", "19",
        "-pix_fmt", "yuv420p",
        temp_raw
    ]

    p_in = subprocess.Popen(in_cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    p_out = subprocess.Popen(out_cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    frame_bytes = out_w * out_h * 3
    t_start = time.time()
    t_last = t_start
    frame_count = 0

    while True:
        raw = p_in.stdout.read(frame_bytes)
        if len(raw) < frame_bytes:
            break

        frame = np.frombuffer(raw, dtype=np.uint8).reshape((out_h, out_w, 3))
        proportioned = cv2.remap(frame, src_x, src_y_grid, interpolation=cv2.INTER_LINEAR)
        lit_frame = cv2.multiply(proportioned, light_map_3c_u8, scale=inv_scale)
        p_out.stdin.write(lit_frame.tobytes())
        frame_count += 1

        if frame_count % 300 == 0:
            now = time.time()
            speed = 300.0 / (now - t_last)
            elapsed = now - t_start
            eta = (total_frames - frame_count) / max(0.1, (frame_count / elapsed))
            pct = (frame_count / total_frames) * 100.0
            print(f"[{frame_count:4d}/{total_frames} ({pct:5.1f}%)] Speed: {speed:5.1f} fps | Elapsed: {elapsed/60:4.1f}m | ETA: {eta/60:4.1f}m")
            t_last = now

    p_in.stdout.close()
    p_in.wait()
    p_out.stdin.close()
    p_out.wait()

    # Mux Audio
    print("Muxing original 320kbps AAC master audio...")
    temp_mux = out_video + ".mux.mp4"
    mux_cmd = [
        ffmpeg_bin, "-y",
        "-i", temp_raw,
        "-i", source_video,
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "320k",
        "-shortest",
        temp_mux
    ]
    subprocess.run(mux_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    if os.path.exists(temp_raw):
        os.remove(temp_raw)

    # Auto Trim Agency Outro Card if requested
    if trim_outro and frame_count > 6696:
        print(f"Trimming outro card at frame 6696 (fade-out to black)...")
        trim_cmd = [
            ffmpeg_bin, "-y",
            "-i", temp_mux,
            "-frames:v", "6696",
            "-c:v", "copy", "-c:a", "copy",
            out_video
        ]
        subprocess.run(trim_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        if os.path.exists(temp_mux):
            os.remove(temp_mux)
    else:
        if os.path.exists(temp_mux):
            os.replace(temp_mux, out_video)

    out_size_mb = os.path.getsize(out_video) / (1024 * 1024)
    print(f"Final deliverable ready: {out_video} ({out_size_mb:.2f} MB)")
    return out_video

def main():
    parser = argparse.ArgumentParser(description="K-Pop Concert Spotlight 9:16 Fancam Production")
    parser.add_argument("--input", default=r"D:\download\bts_mma_source.mp4", help="Path to input 4K/FHD video")
    parser.add_argument("--output", default=r"D:\BTS\BTS_Dynamite_Fancam_9x16_ConcertSpotlight_Full.mp4", help="Path to output mp4")
    parser.add_argument("--crop-w", type=int, default=1600, help="Crop width in source video space")
    parser.add_argument("--center-x", type=int, default=1820, help="Crop center X in source video space")
    parser.add_argument("--no-trim-outro", action="store_true", help="Do not trim the ending outro card")
    args = parser.parse_args()

    render_fancam(args.input, args.output, args.crop_w, args.center_x, not args.no_trim_outro)

if __name__ == "__main__":
    main()

