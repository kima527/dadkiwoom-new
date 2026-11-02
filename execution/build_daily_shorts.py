import os
import sys
import time
import json

# Ensure UTF-8 output
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from fetch_market_anomaly import fetch_market_data, analyze_anomalies
from generate_cover_page import create_shorts_cover_page
from generate_financial_chart import create_shorts_infographic
from generate_market_script import generate_script_and_audio
from render_financial_shorts import render_financial_shorts

def run_full_pipeline(output_video_path=r"D:\DailyQuant\Daily_Quant_Shorts_Sample.mp4"):
    """
    Executes the entire end-to-end Daily Financial YouTube Shorts Pipeline in one click.
    Features:
      1. US/Domestic Market Data & Headline News Fetch
      2. High-CTR Viral Hook Cover Page Generation (1080x1920)
      3. 9:16 Full HD Dark Mode Infographic Generation (1080x1920)
      4. Tight 50~55s 4-Stage Script & Edge-TTS Neural Audio Synthesis
      5. FFmpeg 60FPS Video Rendering with Cinematic Cover Intro Transition
    """
    start_time = time.time()
    print("=" * 70)
    print("🚀 [모닝 퀀트] 유튜브 쇼츠 100% 완전 자동 제작 파이프라인 가동")
    print("=" * 70 + "\n")

    # Step 1: Data & Anomaly
    print(">>> [1/5] 미국/국내 증시 데이터 및 핵심 헤드라인 뉴스 수집 중...")
    data = fetch_market_data()
    if not data:
        print("❌ 실패: 데이터 수집에 실패했습니다.")
        return False
    report = analyze_anomalies(data)
    os.makedirs(".tmp", exist_ok=True)
    json_path = ".tmp/market_anomaly_today.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    headlines_count = len(report.get('market_headlines', []))
    sox_pct = report.get('korea_indicators', {}).get('sox', {}).get('change_pct', 0)
    print(f"✅ 1단계 완료: 핵심 헤드라인 {headlines_count}건 수집 완료, 필라델피아 반도체({sox_pct}%)\n")

    # Step 2: High-CTR Cover Page
    print(">>> [2/5] 시선 집중! 고반응 바이럴 훅 커버페이지 렌더링 중...")
    cover_path = ".tmp/shorts_cover_today.png"
    create_shorts_cover_page(json_path, cover_path)
    print()

    # Step 3: Main Infographic
    print(">>> [3/5] 9:16 모바일 최적화 고대비 다크모드 차트 렌더링 중...")
    image_path = ".tmp/shorts_visual_today.png"
    create_shorts_infographic(json_path, image_path)
    print()

    # Step 4: Script & Audio
    print(">>> [4/5] 4단계 황금 구조 대본 및 신경망 AI 내레이션 음성 합성 중...")
    script_path = ".tmp/shorts_script.txt"
    audio_path = ".tmp/shorts_narration.mp3"
    generate_script_and_audio(json_path, script_path, audio_path)
    print()

    # Step 5: Video Render
    print(">>> [5/5] FFmpeg 60FPS 커버 인트로 전환 비디오 렌더링 중...")
    render_financial_shorts(
        image_path=image_path,
        audio_path=audio_path,
        output_path=output_video_path,
        cover_path=cover_path,
        cover_duration=2.5,
        fade_duration=0.4
    )
    print()

    elapsed = time.time() - start_time
    print("=" * 70)
    print(f"🎉 [제작 성공] 총 소요 시간: {elapsed:.1f}초 (약 {elapsed/60:.1f}분)")
    print(f"📁 완성된 유튜브 쇼츠 파일: {output_video_path}")
    print("=" * 70)
    return True

if __name__ == "__main__":
    run_full_pipeline()
