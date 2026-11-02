import os
import sys
import time
import asyncio

# Ensure UTF-8
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from run_golden_cross_backtest import generate_golden_cross_backtest_data
from generate_longform_thumbnail import generate_longform_thumbnail
from generate_longform_slides import generate_all_slides
from generate_longform_script_audio import synthesize_all_audio
from render_longform_video import render_longform_video

def build_longform_episode_1():
    """
    End-to-End Master Builder for Long-Form Episode 1:
    '골든크로스의 배신: 10년간 믿고 샀더니 계좌가 반토막 난 이유'
    """
    start_total = time.time()
    print("=" * 75)
    print("🚀 [퀀트 팩트체크 3부작] 롱폼 1편 원클릭 전자동 제작 파이프라인 가동")
    print("=" * 75 + "\n")

    # Step 1: Run Backtest
    print(">>> [1/5] 코스피 200 10개년(2014~2024) 전수조사 백테스트 수행 중...")
    json_path = ".tmp/backtest_golden_cross.json"
    generate_golden_cross_backtest_data(json_path)
    print()

    # Step 2: Generate High-CTR Thumbnail
    print(">>> [2/5] 16:9 Full HD 고대비 썸네일(커버페이지) 렌더링 중...")
    thumb_path = r"D:\DailyQuant\LongForm_Ep1_Thumbnail.png"
    generate_longform_thumbnail(json_path, thumb_path)
    print()

    # Step 3: Generate Presentation Slides
    print(">>> [3/5] 7개 챕터 16:9 와이드스크린 슬라이드 일괄 렌더링 중...")
    slides_dir = ".tmp/slides"
    generate_all_slides(slides_dir, json_path)
    print()

    # Step 4: Synthesize Neural Audio
    print(">>> [4/5] 7개 챕터 전문 퀀트 내레이션 AI 신경망 음성 합성 중...")
    audio_dir = ".tmp/audio"
    asyncio.run(synthesize_all_audio(audio_dir))
    print()

    # Step 5: Render Video
    print(">>> [5/5] FFmpeg 1080p 30FPS 풀 렌더링 및 썸네일 아트워크 내장 중...")
    output_video = r"D:\DailyQuant\LongForm_Ep1_GoldenCross_FactCheck.mp4"
    render_longform_video(
        timing_json=".tmp/longform_script_timing.json",
        slides_dir=slides_dir,
        output_video_path=output_video,
        thumbnail_path=thumb_path
    )
    print()

    elapsed = time.time() - start_total
    print("=" * 75)
    print(f"🎉 [롱폼 1편 제작 완료!] 총 소요 시간: {elapsed:.1f}초 ({elapsed/60:.2f}분)")
    print(f"📁 완성 영상: {output_video}")
    print(f"🖼️ 썸네일   : {thumb_path}")
    print(f"📝 메타데이터: D:\\DailyQuant\\LongForm_Ep1_YouTube_Metadata.txt")
    print("=" * 75 + "\n")

if __name__ == "__main__":
    build_longform_episode_1()
