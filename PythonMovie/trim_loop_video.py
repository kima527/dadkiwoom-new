import os
import cv2
import numpy as np

# MoviePy v1 및 v2 버전 호환성 처리
try:
    from moviepy import VideoFileClip
except ImportError:
    from moviepy.editor import VideoFileClip

def find_loop_end_time(video_path, sample_rate=1.0, threshold=0.98):
    """
    동영상의 첫 프레임과 이후 프레임들을 비교하여, 
    동일한 내용이 다시 시작되는(반복되는) 지점의 시간을 찾습니다.
    """
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print("동영상을 열 수 없습니다.")
        return None

    fps = cap.get(cv2.CAP_PROP_FPS)
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    if fps <= 0:
        print("동영상 FPS 정보가 올바르지 않습니다.")
        cap.release()
        return None
        
    duration = total_frames / fps
    
    # 첫 번째 프레임을 기준(Reference)으로 잡습니다.
    ret, first_frame = cap.read()
    if not ret:
        print("첫 프레임을 읽지 못했습니다.")
        cap.release()
        return None
    
    # 비교 속도를 높이기 위해 흑백 변환 및 크기 축소
    first_gray = cv2.cvtColor(first_frame, cv2.COLOR_BGR2GRAY)
    first_gray = cv2.resize(first_gray, (100, 100))

    check_interval = int(fps * sample_rate)  # 지정한 초(sample_rate) 간격으로 프레임 검사
    duplicate_start_time = None

    print("동영상 분석 중... 잠시만 기다려주세요.")
    
    # 초반 몇 초 동안은 바로 반복되지 않으므로 최소 5초 이후부터 검사 (영상의 길이에 따라 조절 가능)
    min_check_frame = int(fps * 5) 

    while True:
        current_frame_idx = int(cap.get(cv2.CAP_PROP_POS_FRAMES))
        if current_frame_idx >= total_frames:
            break
            
        ret, frame = cap.read()
        if not ret:
            break

        # 지정된 간격의 프레임만 검사
        if current_frame_idx > min_check_frame and current_frame_idx % check_interval == 0:
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.resize(gray, (100, 100))

            # 템플릿 매칭을 이용한 유사도 계산 (1.0에 가까울수록 동일함)
            res = cv2.matchTemplate(gray, first_gray, cv2.TM_CCOEFF_NORMED)
            similarity = res[0][0]

            # 설정한 임계값(threshold)보다 유사도가 높으면 반복 시작 지점으로 판단
            if similarity >= threshold:
                duplicate_start_time = current_frame_idx / fps
                print(f"[감지] {duplicate_start_time:.2f}초 지점에서 반복 재생 확인 (유사도: {similarity:.4f})")
                break
                
        # 간격 건너뛰기
        cap.set(cv2.CAP_PROP_POS_FRAMES, current_frame_idx + check_interval)

    cap.release()
    return duplicate_start_time

def trim_video(video_path, output_path, end_time):
    """
    동영상의 시작부터 반복 직전(end_time)까지 잘라내어 새 파일로 저장합니다.
    """
    print(f"영상 자르기 시작: 0초 ~ {end_time:.2f}초")
    try:
        with VideoFileClip(video_path) as video:
            # MoviePy v1 (subclip) vs v2 (subclipped) 호환 처리
            if hasattr(video, "subclipped"):
                trimmed_video = video.subclipped(0, end_time)
            else:
                trimmed_video = video.subclip(0, end_time)
            
            # Ultra HD, HDR, Dolby Vision 등 고화질 손실을 최소화하기 위해 원본 코덱 지정 유지가 중요합니다.
            # 아래 설정을 통해 고화질 인코딩을 진행합니다.
            trimmed_video.write_videofile(
                output_path, 
                codec='libx264', 
                audio_codec='aac',
                bitrate="50000k", # 고화질(12K 원본 소스 감안) 유지를 위해 높은 비트레이트 설정
                preset='slow'
            )
        print(f"편집 완료! 저장된 파일: {output_path}")
    except Exception as e:
        print(f"영상 편집 중 오류 발생: {e}")

if __name__ == "__main__":
    # 파일 경로 설정 (D드라이브 절대경로)
    input_file = r"D:\Incredible Animals Journey  12K HDR Dolby Vision Ultra HD Cinematic Experience.mp4"
    output_file = r"D:\Incredible_Animals_Journey_Trimmed.mp4"

    if os.path.exists(input_file):
        # 1. 반복 지점 탐색 (기본 임계값 0.98 설정)
        loop_point = find_loop_end_time(input_file, sample_rate=0.5, threshold=0.96)
        
        # 2. 반복 지점을 찾았다면 해당 구간까지만 자르기 실행
        if loop_point:
            trim_video(input_file, output_file, loop_point)
        else:
            print("동영상에서 자동 반복 구간을 찾지 못했습니다. threshold를 낮추거나 수동 편집이 필요할 수 있습니다.")
    else:
        print(f"파일을 찾을 수 없습니다. 경로를 확인해주세요: {input_file}")
