import os
import sys
import argparse
import time

# Ensure UTF-8 output
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from generate_sns_metadata import generate_sns_metadata
from upload_youtube_shorts import upload_youtube_shorts
from upload_instagram_reels import upload_instagram_reel

def distribute_shorts_to_sns(
    video_path: str = r"D:\DailyQuant\Daily_Quant_Shorts_Sample.mp4",
    anomaly_json_path: str = ".tmp/market_anomaly_today.json",
    meta_path: str = ".tmp/sns_metadata_today.json",
    youtube_privacy: str = "unlisted",
    dry_run: bool = False
):
    """
    Master Multi-SNS Distributor:
    1. Generates SEO-optimized metadata for YouTube Shorts & Instagram Reels.
    2. Publishes video to YouTube Shorts.
    3. Publishes video to Instagram Reels.
    4. Outputs structured summary report.
    """
    start_time = time.time()
    print("=" * 70)
    print("🌐 [모닝 퀀트] 멀티 SNS 자동 배포 엔진 가동 (YouTube Shorts + Instagram Reels)")
    print("=" * 70 + "\n")

    if not os.path.exists(video_path):
        print(f"❌ 배포 중단: 비디오 파일이 존재하지 않습니다 -> {video_path}")
        return False

    # Step 1: Metadata Generation
    print(">>> [1/3] 플랫폼별 최적화 메타데이터(제목, 캡션, 태그) 생성 중...")
    meta = generate_sns_metadata(json_path=anomaly_json_path, output_path=meta_path)
    print()

    results = {
        "youtube": None,
        "instagram": None
    }

    # Step 2: YouTube Shorts Upload
    print(">>> [2/3] 유튜브 쇼츠 자동 업로드 파이프라인 호출...")
    try:
        yt_res = upload_youtube_shorts(
            video_path=video_path,
            meta_path=meta_path,
            privacy_status=youtube_privacy,
            dry_run=dry_run
        )
        results["youtube"] = yt_res if yt_res else "인증 키 대기 중"
    except Exception as e:
        print(f"⚠️ 유튜브 업로드 중 예외 발생: {e}")
        results["youtube"] = f"오류: {e}"
    print()

    # Step 3: Instagram Reels Upload
    print(">>> [3/3] 인스타그램 릴스 자동 배포 파이프라인 호출...")
    try:
        ig_res = upload_instagram_reel(
            video_path=video_path,
            meta_path=meta_path,
            dry_run=dry_run
        )
        results["instagram"] = ig_res if ig_res else "환경변수 설정 대기 중"
    except Exception as e:
        print(f"⚠️ 인스타그램 배포 중 예외 발생: {e}")
        results["instagram"] = f"오류: {e}"
    print()

    elapsed = time.time() - start_time
    print("=" * 70)
    print("📊 [SNS 자동 배포 결과 종합 리포트]")
    print(f"⏱️ 총 소요 시간: {elapsed:.1f}초")
    print(f"🔴 유튜브 쇼츠     : {results['youtube']}")
    print(f"🟣 인스타그램 릴스 : {results['instagram']}")
    print("=" * 70)
    return results

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Distribute video to all SNS platforms")
    parser.add_argument("--video", default=r"D:\DailyQuant\Daily_Quant_Shorts_Sample.mp4", help="Video path")
    parser.add_argument("--privacy", default="unlisted", choices=["public", "unlisted", "private"], help="YouTube privacy")
    parser.add_argument("--dry-run", action="store_true", help="Run without sending live uploads")
    args = parser.parse_args()

    distribute_shorts_to_sns(video_path=args.video, youtube_privacy=args.privacy, dry_run=args.dry_run)

