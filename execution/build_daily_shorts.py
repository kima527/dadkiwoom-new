import os
import sys
import time

# Ensure UTF-8 output
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from fetch_market_anomaly import fetch_market_data, analyze_anomalies
from generate_financial_chart import create_shorts_infographic
from generate_market_script import generate_script_and_audio
from render_financial_shorts import render_financial_shorts
import json

def run_full_pipeline(output_video_path=r"D:\DailyQuant\Daily_Quant_Shorts_Sample.mp4"):
    """
    Executes the entire end-to-end Daily Financial YouTube Shorts Pipeline in one click.
    """
    start_time = time.time()
    print("=" * 70)
    print("🚀 [모닝 퀀트] 유튜브 쇼츠 100% 완전 자동 제작 파이프라인 가동")
    print("=" * 70 + "\n")

    # Step 1: Data & Anomaly
    print(">>> [1/4] 미국 증시 데이터 수집 및 킬러 훅 이상치 스캔 중...")
    data = fetch_market_data()
    if not data:
        print("❌ 실패: 데이터 수집에 실패했습니다.")
        return False
    report = analyze_anomalies(data)
    os.makedirs(".tmp", exist_ok=True)
    json_path = ".tmp/market_anomaly_today.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"✅ 1단계 완료: 오늘의 이상치 종목 -> {report['top_anomaly']['name']} ({report['top_anomaly']['change_pct']}%)\n")

    # Step 2: Infographic
    print(">>> [2/4] 9:16 모바일 최적화 고대비 다크모드 차트 렌더링 중...")
    image_path = ".tmp/shorts_visual_today.png"
    create_shorts_infographic(json_path, image_path)
    print()

    # Step 3: Script & Audio
    print(">>> [3/4] 4단계 황금 구조 대본 및 신경망 AI 내레이션 음성 합성 중...")
    script_path = ".tmp/shorts_script.txt"
    audio_path = ".tmp/shorts_narration.mp3"
    generate_script_and_audio(json_path, script_path, audio_path)
    print()

    # Step 4: Video Render
    print(">>> [4/4] FFmpeg 60FPS 시네마틱 줌 모션 비디오 렌더링 중...")
    render_financial_shorts(image_path, audio_path, output_video_path)
    print()

    elapsed = time.time() - start_time
    print("=" * 70)
    print(f"🎉 [제작 성공] 총 소요 시간: {elapsed:.1f}초 (약 {elapsed/60:.1f}분)")
    print(f"📁 완성된 유튜브 쇼츠 파일: {output_video_path}")
    print("=" * 70)
    return True

if __name__ == "__main__":
    run_full_pipeline()

