import os
import sys
import time
import json
import argparse

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
from distribute_all_sns import distribute_shorts_to_sns
from send_telegram_shorts import send_shorts_to_telegram

def run_full_pipeline(
    output_video_path: str = r"D:\DailyQuant\Daily_Quant_Shorts_Sample.mp4",
    auto_upload: bool = True,
    youtube_privacy: str = "public",
    dry_run_upload: bool = False
):
    """
    Executes the entire end-to-end Daily Financial Shorts & Multi-SNS Distribution Pipeline in one click:
      1. US/Domestic Market Data & Headline News Fetch
      2. High-CTR Viral Hook Cover Page Generation (1080x1920)
      3. 9:16 Full HD Dark Mode Infographic Generation (1080x1920)
      4. Storytelling Specialist 6-Stage Narrative Script & Edge-TTS Neural Audio Synthesis
      5. FFmpeg 60FPS Video Rendering with Cinematic Cover Intro Transition
      6. [Optional] Automated Multi-SNS Distribution (YouTube Shorts + Instagram Reels)
    """
    start_time = time.time()
    print("=" * 70)
    print("🚀 [모닝 퀀트] 유튜브 쇼츠 100% 완전 자동 제작 & SNS 배포 파이프라인 가동")
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

    # Step 4: Storytelling Expert Script & Audio
    print(">>> [4/5] 🎭 수석 스토리텔링 전문가 가동: 6단계 황금 서사 대본 및 AI 신경망 음성 합성 중...")
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
        cover_duration=4.0,
        fade_duration=0.5
    )
    print()

    yt_url = None
    # Step 5: Multi-SNS Auto Distribution
    if auto_upload:
        print(">>> [5/6] 🚀 유튜브 쇼츠 무인 자동 배포 엔진 가동...")
        dist_res = distribute_shorts_to_sns(
            video_path=output_video_path,
            anomaly_json_path=json_path,
            youtube_privacy=youtube_privacy,
            dry_run=dry_run_upload
        )
        if dist_res and isinstance(dist_res, dict):
            yt_url = dist_res.get("youtube")
        print()

    # Step 6: Instant Mobile Telegram Notification (with live YouTube link)
    print(">>> [6/6] 📲 스마트폰 텔레그램으로 완료 알림 및 원본 백업 발송 중...")
    try:
        top_stock = report.get("top_anomaly", {})
        top_name = top_stock.get("name", "기술주").split(" ")[0]
        m_title = "장 열리기 전 필수시청 꼭 알아야 할 주식 시장 핵심 뉴스 3가지 #shorts"
        if os.path.exists(".tmp/sns_metadata_today.json"):
            with open(".tmp/sns_metadata_today.json", "r", encoding="utf-8") as f:
                s_data = json.load(f)
                m_title = s_data.get("youtube", {}).get("title", m_title)

        send_shorts_to_telegram(
            video_path=output_video_path,
            title=m_title,
            tags=["#Shorts", "#주식", "#국내증시", "#모닝퀀트", f"#{top_name}"],
            youtube_url=yt_url
        )
    except Exception as e:
        print(f"⚠️ 텔레그램 전송 예외: {e}")
    print()

    elapsed = time.time() - start_time
    print("=" * 70)
    print(f"🎉 [파이프라인 전체 완료] 총 소요 시간: {elapsed:.1f}초 (약 {elapsed/60:.1f}분)")
    print(f"📁 완성된 유튜브 쇼츠 파일: {output_video_path}")
    print("=" * 70)
    return True

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build and Distribute Daily Financial Shorts")
    parser.add_argument("--output", default=r"D:\DailyQuant\Daily_Quant_Shorts_Sample.mp4", help="Output video path")
    parser.add_argument("--upload", action="store_true", default=True, help="Auto distribute to YouTube Shorts and Instagram Reels")
    parser.add_argument("--no-upload", dest="upload", action="store_false", help="Disable auto upload")
    parser.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"], help="YouTube privacy")
    parser.add_argument("--dry-run-upload", action="store_true", help="Simulate SNS upload without live transmission")
    args = parser.parse_args()

    run_full_pipeline(
        output_video_path=args.output,
        auto_upload=args.upload,
        youtube_privacy=args.privacy,
        dry_run_upload=args.dry_run_upload
    )
