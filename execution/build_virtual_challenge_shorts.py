"""
build_virtual_challenge_shorts.py - AI 500만원 주식 굴리기 챌린지 원클릭 마스터 파이프라인
======================================================================================
1. 종목 발굴 및 매수~매도 틱 시뮬레이션 (virtual_trading_engine.py)
2. 가상 계좌 원장 갱신 (virtual_account_ledger.py)
3. 60FPS 세로형 마스터 쇼츠 비디오 렌더링 (render_virtual_challenge_video.py)
4. 알고리즘 최적화 메타데이터 자동 생성 (.tmp/virtual_challenge_metadata.json)
5. 무인 유튜브 쇼츠 자동 업로드 (upload_youtube_shorts.py)
6. 스마트폰 텔레그램 실시간 알림 발송 (send_telegram_shorts.py)
"""

import os
import sys
import json
import time
import argparse
from datetime import datetime

# UTF-8 출력 보장
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from virtual_trading_engine import run_daily_virtual_trading
from render_virtual_challenge_video import render_full_challenge_shorts
from upload_youtube_shorts import upload_youtube_shorts
from send_telegram_shorts import send_shorts_to_telegram

def run_challenge_pipeline(auto_upload: bool = False, privacy_status: str = "public") -> str:
    start_time = time.time()
    print("=" * 70)
    print("🤖 [AI 500만원 주식 굴리기 30일 챌린지] 무인 자동화 파이프라인 개시")
    print("=" * 70)

    # 1단계: 가상 매매 및 원장 갱신
    print("\n>>> [1/5] 📈 당일 조건검색 종목 발굴 및 매매 틱 시뮬레이션 실행...")
    trade_data = run_daily_virtual_trading()
    day = trade_data["day"]
    stock_name = trade_data["stock_name"]
    stock_code = trade_data["stock_code"]
    return_pct = trade_data["return_pct"]
    net_pnl = trade_data["net_pnl"]
    cur_asset = trade_data["asset_after_trade"]
    cum_pct = trade_data["cum_return_pct"]

    # 2단계: 60FPS 쇼츠 비디오 렌더링
    print("\n>>> [2/5] 🎬 1080x1920 60FPS 세로형 쇼츠 비디오 렌더링...")
    output_video_path = rf"D:\DailyQuant\AI_Trading_Challenge_Day{day:02d}.mp4"
    data_json_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".tmp", "virtual_challenge_today.json")
    rendered_path = render_full_challenge_shorts(data_path=data_json_path, output_mp4_path=output_video_path)

    # 3단계: SEO 최적화 메타데이터 생성
    print("\n>>> [3/5] 📝 알고리즘 바이럴 최적화 메타데이터 구성...")
    res_keyword = "폭풍 익절" if net_pnl >= 0 else "칼손절 방어"
    sign = "+" if return_pct >= 0 else ""
    yt_title = f"AI 500만원 주식 굴리기 [Day {day}] | {stock_name} {sign}{return_pct:.2f}% {res_keyword}! #Shorts"
    if len(yt_title) > 95:
        yt_title = yt_title[:90] + " #Shorts"

    yt_description = f""""AI에게 500만 원을 주면 한 달 뒤 얼마가 되어 있을까?"
인공지능 30일 주식 굴리기 챌린지 [Day {day}]

바쁜 일상 속, 2,400개 전 종목을 실시간 감시하는 인공지능의 실전 매매 기록입니다.
영상 상단의 실시간 자산 스코어보드를 통해 매일 계좌의 성장을 확인해 보세요!

🤖 [Day {day} 공식 계좌 현황]
• 시작 자본금: 5,000,000원
• 현재 총 자산: {cur_asset:,}원 ({cum_pct:+.2f}%)
• 당일 매매 종목: {stock_name} ({stock_code})
• 당일 실현 손익: {net_pnl:+,}원 ({return_pct:+.2f}%)
• 1회 매수 단가: {trade_data['entry_price']:,}원 ({trade_data['qty']}주 전액 풀베팅)
• 매매 수수료/세금 (0.20%) 정밀 반영 완료

과연 30일 뒤 AI의 500만 원은 얼마가 되어 있을까요?
매일 실시간 계좌가 공개됩니다. 구독하고 함께 지켜보세요!

#Shorts #AI주식 #주식챌린지 #500만원굴리기 #자동매매 #주린이 #주식시황 #SK하이닉스 #삼성전자 #코스피 #재테크""".strip()

    yt_tags = [
        "Shorts", "AI주식", "주식챌린지", "500만원굴리기", "자동매매", "주식",
        "코스피", "삼성전자", "SK하이닉스", "주린이", "재테크", "퀀트투자", stock_name
    ]

    meta_dict = {
        "youtube": {
            "title": yt_title,
            "description": yt_description,
            "tags": yt_tags,
            "categoryId": "27",
            "privacyStatus": privacy_status
        }
    }

    meta_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".tmp", "virtual_challenge_metadata.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta_dict, f, ensure_ascii=False, indent=2)

    # 4단계: 유튜브 자동 업로드
    yt_url = None
    if auto_upload:
        print("\n>>> [4/5] 🚀 유튜브 쇼츠 무인 자동 업로드 진행 중...")
        try:
            yt_url = upload_youtube_shorts(video_path=rendered_path, meta_path=meta_path, privacy_status=privacy_status)
        except Exception as e:
            print(f"⚠️ 유튜브 업로드 오류: {e}")
    else:
        print("\n>>> [4/5] ℹ️ --upload 플래그 미사용: 로컬 렌더링 저장 완료 (업로드 대기)")

    # 5단계: 스마트폰 텔레그램 완료 알림 발송
    print("\n>>> [5/5] 📲 스마트폰 텔레그램으로 완료 알림 및 원본 영상 발송 중...")
    try:
        send_shorts_to_telegram(
            video_path=rendered_path,
            title=yt_title,
            tags=["#Shorts", "#AI주식", "#500만원챌린지", f"#{stock_name}"],
            youtube_url=yt_url
        )
    except Exception as e:
        print(f"⚠️ 텔레그램 발송 오류: {e}")

    elapsed = time.time() - start_time
    print("\n" + "=" * 70)
    print(f"🎉 [AI 500만원 주식 굴리기 Day {day} 파이프라인 완벽 완료]")
    print(f"   - 영상 파일: {rendered_path}")
    print(f"   - 총 소요 시간: {elapsed:.1f}초")
    if yt_url:
        print(f"   - 유튜브 URL: {yt_url}")
    print("=" * 70 + "\n")
    return rendered_path

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build and Upload AI 5M Challenge Shorts")
    parser.add_argument("--upload", action="store_true", help="Auto upload to YouTube Shorts")
    parser.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"], help="Privacy status")
    args = parser.parse_args()

    run_challenge_pipeline(auto_upload=args.upload, privacy_status=args.privacy)
