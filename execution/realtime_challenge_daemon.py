"""
realtime_challenge_daemon.py - 장중 실시간 가상 매매 상주 데몬 & 매도 체결 즉시 유튜브 쇼츠 자동 업로드
======================================================================================================
1. [장중 골든타임 상주 (09:00 ~ 15:20)]
   - 08:55 ~ 09:00: 장 시작 전 대기 및 NXT 프리마켓 주도주 로드
   - 09:00 ~ 09:05: 시초가 갭 덫 방어 (5분 쿨다운 관망)
   - 09:05 ~ 09:40: [제1 골든타임] 1분봉 3·5·20 정배열 3선 눌림목 실시간 매수 감시
   - 11:30 ~ 13:00: [점심 데드존] 휩소 방어 (신규 매수 금지)
   - 13:00 ~ 14:30: [제2 골든타임] 15분봉 4대 수식 거래대금 돌파봉 감시
   - 15:00 ~ 15:20: 당일 100% 전량 청산 (오버나이트 0%)
2. [실시간 매수 체결]
   - 매수 조건 포착 즉시 가상 매수 체결 + 스마트폰 텔레그램 매수 알림 발송
3. [🔥 매도 체결 직후 즉각 유튜브 업로드 (Instant Post-Trade Pipeline)]
   - 목표 익절가(+3.0%) 도달 또는 3일선(M/3) 지지 매도 체결 즉시:
     ① 가상 계좌 원장(virtual_account_ledger.json) 즉각 갱신
     ② 60FPS 1080x1920 세로형 쇼츠 즉시 렌더링 (약 20초 소요)
     ③ 유튜브 쇼츠 즉시 Public 자동 업로드
     ④ 스마트폰 텔레그램으로 "🎯 방금 매도 체결 쇼츠가 유튜브에 게시되었습니다!" 즉시 링크 발송
"""

import os
import sys
import json
import time
import argparse
from datetime import datetime

# UTF-8 콘솔 출력 보장
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXEC_DIR = os.path.join(ROOT_DIR, "execution")
if EXEC_DIR not in sys.path:
    sys.path.insert(0, EXEC_DIR)

from virtual_account_ledger import load_ledger, record_trade
from virtual_trading_engine import (
    fetch_realtime_futures_indicators,
    select_daily_target_stock,
    run_real_strategy_execution
)
from render_virtual_challenge_video import render_full_challenge_shorts
from upload_youtube_shorts import upload_youtube_shorts
from send_telegram_shorts import send_shorts_to_telegram

def get_current_krx_phase():
    """
    현재 시각 기준 KRX 장중 골든타임 페이즈 반환
    """
    now = datetime.now()
    hm = now.strftime("%H:%M")
    
    if hm < "09:00":
        return "PRE_MARKET_WAIT", "장 시작 전 대기 (08:50~09:00)"
    elif "09:00" <= hm < "09:05":
        return "GAP_TRAP_COOLDOWN", "시초가 갭 덫 방어 쿨다운 (09:00~09:05)"
    elif "09:05" <= hm < "09:40":
        return "ZONE_1_MORNING_SCALP", "제1 골든타임 1분봉 3·5·20 눌림목 (09:05~09:40)"
    elif "09:40" <= hm < "11:30":
        return "MID_MORNING", "오전 중반 추세 추종 구간 (09:40~11:30)"
    elif "11:30" <= hm < "13:00":
        return "LUNCH_DEAD_ZONE", "점심 거래량 급감 데드존 (11:30~13:00)"
    elif "13:00" <= hm < "14:30":
        return "ZONE_2_AFTERNOON_WAVE", "제2 골든타임 15분봉 4대 수식 돌파 (13:00~14:30)"
    elif "14:30" <= hm < "15:20":
        return "CLOSING_LIQUIDATION", "당일 전량 현금화 청산 구간 (14:30~15:20)"
    else:
        return "MARKET_CLOSED", "정규장 마감 (15:30 이후)"

def execute_post_trade_instant_upload(trade_sim: dict, auto_upload: bool = True, privacy_status: str = "public") -> dict:
    """
    🔥 [핵심] 매도 체결 직후 즉시 60FPS 쇼츠 렌더링 및 유튜브 자동 업로드 수행
    """
    print("\n" + "=" * 70)
    print("🔥 [매도 체결 직후 즉시 배포 엔진 가동] 실시간 유튜브 쇼츠 자동 업로드 개시!")
    print("=" * 70)

    day = trade_sim.get("day", 1)
    stock_name = trade_sim["stock_name"]
    stock_code = trade_sim["stock_code"]
    return_pct = trade_sim["return_pct"]
    net_pnl = trade_sim["net_pnl"]
    cur_asset = trade_sim["asset_after_trade"]
    cum_pct = trade_sim["cum_return_pct"]
    entry_time = trade_sim["entry_time"]
    exit_time = trade_sim["exit_time"]
    entry_price = trade_sim["entry_price"]
    exit_price = trade_sim["exit_price"]

    # 1. 텔레그램 매도 체결 즉시 속보 발송
    print("\n>>> [1/4] 📲 스마트폰 텔레그램 매도 체결 속보 발송 중...")
    sign = "+" if return_pct >= 0 else ""
    pnl_sign = "+" if net_pnl >= 0 else ""
    tg_sell_msg = (
        f"🎯 <b>[AI 500M 챌린지 실시간 가상 매도 체결!]</b>\n\n"
        f"• 종목: <b>{stock_name} ({stock_code})</b>\n"
        f"• 매수: {entry_time} @ {entry_price:,}원\n"
        f"• 매도: {exit_time} @ {exit_price:,}원\n"
        f"• 실현손익: <b>{pnl_sign}{net_pnl:,}원 ({sign}{return_pct:.2f}%)</b>\n"
        f"• 확정 총자산: <b>{cur_asset:,}원 (누적 {cum_pct:+.2f}%)</b>\n"
        f"• 청산근거: {trade_sim.get('reason_sell', '목표가 도달')}\n\n"
        f"⚡ <i>지금 즉시 60FPS 쇼츠 영상을 자동 렌더링하여 유튜브에 게시합니다 (약 25초 소요)...</i>"
    )
    try:
        from send_telegram_shorts import get_telegram_creds
        import requests
        tok, cid = get_telegram_creds()
        if tok and cid:
            requests.post(
                f"https://api.telegram.org/bot{tok}/sendMessage",
                json={"chat_id": cid, "text": tg_sell_msg, "parse_mode": "HTML"},
                timeout=10
            )
            print("✅ 텔레그램 매도 체결 알림 발송 완료!")
    except Exception as e:
        print(f"⚠️ 텔레그램 전송 알림 경고: {e}")

    # 2. 60FPS 쇼츠 비디오 즉시 렌더링
    print("\n>>> [2/4] 🎬 1080x1920 60FPS 고화질 쇼츠 즉각 렌더링 중...")
    output_dir = r"D:\DailyQuant"
    os.makedirs(output_dir, exist_ok=True)
    video_path = os.path.join(output_dir, f"AI_Trading_Challenge_Day{day:02d}.mp4")
    data_json_path = os.path.join(ROOT_DIR, ".tmp", "virtual_challenge_today.json")

    with open(data_json_path, "w", encoding="utf-8") as f:
        json.dump(trade_sim, f, ensure_ascii=False, indent=2)

    rendered_video = render_full_challenge_shorts(data_path=data_json_path, output_mp4_path=video_path)
    print(f"✅ 비디오 렌더링 완료: {rendered_video}")

    # 3. SEO 최적화 메타데이터 구성
    print("\n>>> [3/4] 📝 실시간 유튜브 쇼츠 메타데이터 구성 중...")
    res_keyword = "폭풍 익절" if net_pnl >= 0 else "칼손절 방어"
    yt_title = f"AI 500만원 주식 굴리기 [Day {day}] | {stock_name} {sign}{return_pct:.2f}% {res_keyword}! #Shorts"
    if len(yt_title) > 95:
        yt_title = yt_title[:92] + "..."

    yt_desc = (
        f"🤖 AI에게 자본금 500만 원을 주면 한 달 뒤 얼마가 될까? [Day {day} / 30]\n\n"
        f"📊 [금일 실시간 체결 기록]\n"
        f"• 매수: {entry_time} {stock_name} @ {entry_price:,}원\n"
        f"• 매도: {exit_time} @ {exit_price:,}원 ({sign}{return_pct:.2f}% {res_keyword})\n"
        f"• 실현손익: {pnl_sign}{net_pnl:,}원 (증권거래세+수수료 0.20% 정산)\n"
        f"• 현재 총자산: {cur_asset:,}원 (누적수익률 {cum_pct:+.2f}%)\n\n"
        f"🔍 매수 근거: {trade_sim.get('reason_buy')}\n"
        f"🎯 매도 근거: {trade_sim.get('reason_sell')}\n\n"
        f"※ 본 영상은 100% 가상 매매 시뮬레이션 기록이며 투자 권유가 아닙니다.\n"
        f"매일 장중 실시간 매매 체결 직후 쇼츠가 즉시 업로드됩니다! 구독과 알림 설정으로 30일 성장 과정을 함께 지켜보세요.\n\n"
        f"#AI주식 #주식챌린지 #500만원굴리기 #{stock_name} #단타 #주식쇼츠 #모닝퀀트"
    )

    meta_dict = {
        "youtube": {
            "title": yt_title,
            "description": yt_desc,
            "tags": ["Shorts", "AI주식", "주식챌린지", "500만원굴리기", stock_name, "스캘핑", "모닝퀀트"],
            "categoryId": "27",
            "privacyStatus": privacy_status
        }
    }
    meta_path = os.path.join(ROOT_DIR, ".tmp", "virtual_challenge_metadata.json")
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta_dict, f, ensure_ascii=False, indent=2)

    # 4. 무인 유튜브 쇼츠 즉각 업로드
    yt_url = None
    if auto_upload:
        print("\n>>> [4/4] 🚀 유튜브 쇼츠 즉시 자동 업로드 진행...")
        try:
            yt_url = upload_youtube_shorts(
                video_path=rendered_video,
                meta_path=meta_path,
                privacy_status=privacy_status
            )
            print(f"🎉 [유튜브 쇼츠 업로드 성공] {yt_url}")
        except Exception as e:
            print(f"⚠️ 유튜브 업로드 예외 발생: {e}")

    # 5. 유튜브 영상 링크 포함 텔레그램 최종 알림
    try:
        send_shorts_to_telegram(
            video_path=rendered_video,
            title=yt_title,
            tags=["#Shorts", "#AI주식", "#500만원챌린지", f"#{stock_name}"],
            youtube_url=yt_url
        )
        print("📲 유튜브 링크 포함 텔레그램 최종 발송 완료!")
    except Exception as e:
        print(f"⚠️ 텔레그램 최종 발송 예외: {e}")

    return {
        "status": "SUCCESS",
        "video_path": rendered_video,
        "youtube_url": yt_url,
        "trade_sim": trade_sim
    }

def run_realtime_daemon_loop(poll_interval_sec: int = 10, auto_upload: bool = True, privacy_status: str = "public"):
    """
    장중 실시간 상주 감시 메인 루프
    """
    ledger = load_ledger()
    official_start = ledger.get("official_start_date", "2026-11-06")
    today_str = datetime.now().strftime("%Y-%m-%d")

    if today_str < official_start:
        print("\n" + "=" * 70)
        print(f"⏸️ [안내] AI 500만원 주식 굴리기 챌린지 공식 시작일은 [{official_start}] 입니다.")
        print("   금일은 시스템 준비 상태를 유지하며, 내일 아침 08:55부터 Day 1이 공식 개시됩니다.")
        print("=" * 70 + "\n")
        return

    print("\n" + "=" * 70)
    print("🤖 [AI 500만원 주식 굴리기] 장중 실시간 상주 데몬 (Realtime Challenge Daemon)")
    print("   - 운영 시간: 매 영업일 08:55 ~ 15:20")
    print("   - 매매 원칙: 09:05~09:40 모닝 눌림목 & 13:00~14:30 오후 파동")
    print("   - 즉시 배포: 매도 체결 즉시 60FPS 쇼츠 렌더링 ➔ 유튜브 실시간 업로드!")
    print("=" * 70 + "\n")

    has_traded_morning = False
    has_traded_afternoon = False

    while True:
        phase_key, phase_label = get_current_krx_phase()
        now_str = datetime.now().strftime("%H:%M:%S")

        print(f"[{now_str}] 📡 시장 감시 중: [{phase_label}]", end="\r", flush=True)

        if phase_key == "PRE_MARKET_WAIT":
            time.sleep(poll_interval_sec)
            continue

        elif phase_key == "GAP_TRAP_COOLDOWN":
            time.sleep(poll_interval_sec)
            continue

        elif phase_key == "ZONE_1_MORNING_SCALP" and not has_traded_morning:
            print(f"\n⚡ [{now_str}] 🎯 [제1 골든타임 진입] 09:05 1분봉 3·5·20 정배열 3선 눌림목 조건 감시 개시!")
            
            # 종목 발굴 및 실시간 매매 체결
            target = select_daily_target_stock(session_mode="morning")
            trade_sim = run_real_strategy_execution(target, session_mode="morning")
            
            date_str = datetime.now().strftime("%Y-%m-%d")
            trade_record = record_trade(
                date_str=date_str,
                stock_code=trade_sim["stock_code"],
                stock_name=trade_sim["stock_name"],
                entry_time=trade_sim["entry_time"],
                entry_price=trade_sim["entry_price"],
                exit_time=trade_sim["exit_time"],
                exit_price=trade_sim["exit_price"],
                reason_buy=trade_sim["reason_buy"],
                reason_sell=trade_sim["reason_sell"]
            )
            trade_sim.update({
                "day": trade_record["day"],
                "net_pnl": trade_record["net_pnl"],
                "asset_after_trade": trade_record["asset_after_trade"],
                "cum_return_pct": trade_record["cum_return_pct"],
                "qty": trade_record["qty"],
                "buy_amount": trade_record["buy_amount"]
            })

            # 🔥 매도 체결 직후 즉각 유튜브 업로드
            execute_post_trade_instant_upload(trade_sim, auto_upload=auto_upload, privacy_status=privacy_status)
            has_traded_morning = True

        elif phase_key == "ZONE_2_AFTERNOON_WAVE" and not has_traded_afternoon and not has_traded_morning:
            print(f"\n⚡ [{now_str}] 🎯 [제2 골든타임 진입] 13:00 15분봉 4대 수식 수급 돌파봉 감시 개시!")
            target = select_daily_target_stock(session_mode="afternoon")
            trade_sim = run_real_strategy_execution(target, session_mode="afternoon")

            date_str = datetime.now().strftime("%Y-%m-%d")
            trade_record = record_trade(
                date_str=date_str,
                stock_code=trade_sim["stock_code"],
                stock_name=trade_sim["stock_name"],
                entry_time=trade_sim["entry_time"],
                entry_price=trade_sim["entry_price"],
                exit_time=trade_sim["exit_time"],
                exit_price=trade_sim["exit_price"],
                reason_buy=trade_sim["reason_buy"],
                reason_sell=trade_sim["reason_sell"]
            )
            trade_sim.update({
                "day": trade_record["day"],
                "net_pnl": trade_record["net_pnl"],
                "asset_after_trade": trade_record["asset_after_trade"],
                "cum_return_pct": trade_record["cum_return_pct"],
                "qty": trade_record["qty"],
                "buy_amount": trade_record["buy_amount"]
            })

            execute_post_trade_instant_upload(trade_sim, auto_upload=auto_upload, privacy_status=privacy_status)
            has_traded_afternoon = True

        elif phase_key == "MARKET_CLOSED":
            print(f"\n🏁 [{now_str}] 정규장 마감 완료. 금일 장중 실시간 감시 데몬을 안전하게 종료합니다.")
            break

        time.sleep(poll_interval_sec)

def run_instant_replay_now(auto_upload: bool = True, privacy_status: str = "public"):
    """
    장 마감 후 또는 테스트 시 즉시 금일 실시간 매매 및 매도 직후 업로드 프로세스를 즉시 시뮬레이션
    """
    print("\n" + "=" * 70)
    print("🚀 [즉시 실행 모드] 금일 가상 매매 체결 ➔ 매도 직후 유튜브 쇼츠 업로드 파이프라인 가동")
    print("=" * 70)

    date_str = datetime.now().strftime("%Y-%m-%d")
    target = select_daily_target_stock(session_mode="morning")
    trade_sim = run_real_strategy_execution(target, session_mode="morning")

    trade_record = record_trade(
        date_str=date_str,
        stock_code=trade_sim["stock_code"],
        stock_name=trade_sim["stock_name"],
        entry_time=trade_sim["entry_time"],
        entry_price=trade_sim["entry_price"],
        exit_time=trade_sim["exit_time"],
        exit_price=trade_sim["exit_price"],
        reason_buy=trade_sim["reason_buy"],
        reason_sell=trade_sim["reason_sell"]
    )
    trade_sim.update({
        "day": trade_record["day"],
        "net_pnl": trade_record["net_pnl"],
        "asset_after_trade": trade_record["asset_after_trade"],
        "cum_return_pct": trade_record["cum_return_pct"],
        "qty": trade_record["qty"],
        "buy_amount": trade_record["buy_amount"]
    })

    return execute_post_trade_instant_upload(trade_sim, auto_upload=auto_upload, privacy_status=privacy_status)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Real-time Challenge Trading Daemon & Instant Post-Trade Upload")
    parser.add_argument("--now", action="store_true", help="Run trade and post-trade upload immediately without waiting")
    parser.add_argument("--upload", action="store_true", default=True, help="Auto upload to YouTube Shorts")
    parser.add_argument("--no-upload", dest="upload", action="store_false", help="Disable auto upload")
    parser.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"], help="YouTube privacy status")
    parser.add_argument("--interval", type=int, default=10, help="Polling interval in seconds")
    args = parser.parse_args()

    if args.now:
        run_instant_replay_now(auto_upload=args.upload, privacy_status=args.privacy)
    else:
        run_realtime_daemon_loop(poll_interval_sec=args.interval, auto_upload=args.upload, privacy_status=args.privacy)

