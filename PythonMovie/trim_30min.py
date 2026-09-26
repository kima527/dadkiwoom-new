import os
import subprocess
import imageio_ffmpeg

def trim_first_30min(input_file, output_file, duration_seconds=1800):
    """
    고화질 (12K HDR Dolby Vision) 원본 손실을 방지하고 빠른 속도로 
    동영상의 앞쪽 30분(1800초)을 추출합니다 (-c copy 방식 사용).
    """
    if not os.path.exists(input_file):
        print(f"오류: 입력 파일을 찾을 수 없습니다: {input_file}")
        return False

    print(f"입력 파일: {input_file}")
    print(f"출력 파일: {output_file}")
    print(f"앞쪽 {duration_seconds // 60}분 (0초 ~ {duration_seconds}초) 추출 중...")

    try:
        ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
        cmd = [
            ffmpeg_exe,
            "-y",
            "-ss", "0",
            "-to", str(duration_seconds),
            "-i", input_file,
            "-c", "copy",
            output_file
        ]

        result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
        if result.returncode == 0:
            file_size_mb = os.path.getsize(output_file) / (1024 * 1024)
            print(f"[성공] 30분 영상 추출 완료: {output_file} (용량: {file_size_mb:.2f} MB)")
            return True
        else:
            print(f"[오류] ffmpeg 오류 발생:\n{result.stderr}")
            return False
    except Exception as e:
        print(f"[오류] 발생: {e}")
        return False

if __name__ == "__main__":
    input_video = r"D:\Incredible Animals Journey  12K HDR Dolby Vision Ultra HD Cinematic Experience.mp4"
    output_video = r"D:\Incredible_Animals_Journey_30min.mp4"

    trim_first_30min(input_video, output_video, duration_seconds=1800)
