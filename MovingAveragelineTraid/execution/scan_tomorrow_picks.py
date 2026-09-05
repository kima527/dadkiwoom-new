"""
scan_tomorrow_picks.py - 내일의 공략주(돌파 임박 / W자 반등) 자동 스캔 및 저장 시스템
=============================================================================
매일 20:00(장마감 후)에 자동 실행되어:
1. 거래대금 상위주 + 주도 테마주 + 기존 관심종목군(약 150~200종목) 전수 차트 분석
2. 4대 핵심 전략 기준에 부합하는 '돌파 임박 종목' 엄선:
   - [조건 1] 30분봉 260이평 W자 반등 완성 또는 260이평선 사정권(-3.0% ~ +0.5%) 진입 종목
   - [조건 2] 일봉 20이평선 상향 돌파 임박(-2.0% ~ +0.5%) 종목
   - [조건 3] 30분봉 3일선-5일선 골든크로스 초수렴(0.5% 이내) 종목
   - [조건 4] 가중 5-20 고가선(HH) 돌파 임박(-1.5% ~ 0.0%) 종목
3. 우선순위 점수(Priority Score) 순으로 상위 20~30종목을 today_picks.json에 자동 저장.
4. 다음 날 09:00 트레이딩 봇(trading_bot.py)이 시작할 때 즉시 사전 장착되어 최우선 매수 집행!
"""

import os
import sys
import json
import time
import logging
from datetime import datetime
import pandas as pd
import numpy as np

# Windows 콘솔 인코딩 설정
if sys.platform.startswith("win"):
    try:
        if sys.stdout and not sys.stdout.closed:
            sys.stdout.reconfigure(encoding="utf-8")
        if sys.stderr and not sys.stderr.closed:
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 경로 설정
current_dir = os.path.dirname(os.path.abspath(__file__))
real_trading_dir = os.path.abspath(os.path.join(current_dir, "..", "..", "real trading"))

if current_dir not in sys.path:
    sys.path.insert(0, current_dir)
if real_trading_dir not in sys.path:
    sys.path.insert(0, real_trading_dir)

from real_api_adapter import RealAPIAdapter
from strategy_buy import analyze_buy_signals, calculate_hh, calculate_realtime_day_smas, detect_w_rebound_30m, wma
from theme_manager import ThemeManager

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("TomorrowScanner")


def build_candidate_universe(client: RealAPIAdapter) -> dict:
    """스캔 대상 종목군 구성 (거래대금 상위 + 테마주 + 기존 관심종목)"""
    universe = {}

    exclude_keywords = [
        "KODEX", "TIGER", "KBSTAR", "KINDEX", "ARIRANG", "KOSEF", "HANARO",
        "ACE", "ETN", "스팩", "SOL", "인버스", "레버리지", "선물", "KOACT",
        "TIMEFOLIO", "WOORI", "히어로즈", "PLUS", "WON", "2X", "KRX", "합병", "RISE"
    ]

    logger.info("🔍 1. 키움 API 거래대금 상위 150종목 수집 중...")
    try:
        raw_top = client.real_client.get_top_trading_value_stocks(limit=150)
        for code_raw in raw_top:
            try:
                code = code_raw.replace("_AL", "").replace("_NX", "").lstrip("A").strip()
                if len(code) == 6 and code.isalnum():
                    name = client.get_stock_name(code) or ""
                    if not name or any(kw in name for kw in exclude_keywords) or name.endswith("우") or name.endswith("우B"):
                        continue
                    universe[code] = name
                    time.sleep(0.04)
            except Exception:
                continue
        logger.info(f" -> 거래대금 상위 {len(universe)}개 일반 종목 로드 완료")
    except Exception as e:
        logger.warning(f"거래대금 상위 수집 중 오류: {e}")

    logger.info("🔍 2. 당일 등락률 상위 100종목 수집 중...")
    try:
        rates = client.real_client.get_top_fluctuation_stocks_with_rates(limit=100)
        for code_raw in rates.keys():
            try:
                code = code_raw.replace("_AL", "").replace("_NX", "").lstrip("A").strip()
                if len(code) == 6 and code.isalnum() and code not in universe:
                    name = client.get_stock_name(code) or ""
                    if not name or any(kw in name for kw in exclude_keywords) or name.endswith("우") or name.endswith("우B"):
                        continue
                    universe[code] = name
                    time.sleep(0.04)
            except Exception:
                continue
        logger.info(f" -> 등락률 상위 포함 총 {len(universe)}개 종목 확보")
    except Exception as e:
        logger.warning(f"등락률 상위 수집 중 오류: {e}")

    # 기존 관심종목 파일들 병합
    picks_path = os.path.join(current_dir, "today_picks.json")
    if os.path.exists(picks_path):
        try:
            with open(picks_path, 'r', encoding='utf-8') as f:
                old_picks = json.load(f)
                for code, info in old_picks.items():
                    c = code.lstrip('A')
                    if len(c) == 6 and c.isalnum() and c not in universe:
                        name = info.get('name') or client.get_stock_name(c)
                        universe[c] = name
        except Exception:
            pass

    # 핵심 주도 테마주 리스트 보강 (10조 이상 초대형주 제외, 실전 탄력성 높은 중소형/주도주 중심)
    core_stocks = {
        "042700": "한미반도체", "053690": "한미글로벌", "014620": "성광벤드",
        "405100": "큐알티", "006110": "삼아알미늄", "034020": "두산에너빌리티",
        "348370": "엔켐", "178320": "서진시스템", "047080": "한빛소프트",
        "052460": "아이크래프트", "213420": "덕산네오룩스", "108490": "로보티즈",
        "052300": "오션인더블유", "0039P0": "매드업", "080220": "제주반도체",
        "153890": "져스텍", "002620": "제일파마홀딩스", "043360": "디지아이"
    }
    for c, n in core_stocks.items():
        if c not in universe:
            universe[c] = n

    logger.info(f"🎯 최종 스캔 대상 유니버스: 총 {len(universe)}개 종목 확정")
    return universe


def evaluate_stock_proximity(code: str, name: str, client: RealAPIAdapter) -> dict:
    """개별 종목의 30분봉 / 일봉 차트를 조회하여 4대 전략 근접도 평가"""
    try:
        df_30m = client.get_30m_candles(code)
        time.sleep(0.05)
        daily_df = client.get_daily_candles(code)
        time.sleep(0.05)

        if df_30m is None or df_30m.empty or len(df_30m) < 30:
            return None

        if daily_df is None or daily_df.empty or len(daily_df) < 5:
            return None

        # ── [필터 1] 5일 평균 거래대금 10억 미만 소외주 제외 ──
        trade_val_5d = (daily_df['close'] * daily_df['volume']).tail(5).mean()
        if trade_val_5d < 1_000_000_000:
            logger.debug(f"⏭️ [{name}({code})] 5일 평균 거래대금({trade_val_5d/1e8:.1f}억) 10억 미만으로 스캔 제외")
            return None

        # ── [필터 2] 시가총액 10조원 이상 초대형주 제외 (삼성전자, SK하이닉스, 현대차, NAVER 등) ──
        market_cap = client.get_market_cap(code)
        if market_cap >= 10_000_000_000_000:
            logger.info(f"⏭️ [{name}({code})] 시가총액({market_cap/1e12:.1f}조원) 10조 이상 대형주로 스캔 제외")
            return None

        curr_close = float(df_30m['close'].iloc[-1])
        if curr_close <= 0:
            return None

        # ── 1. 30분봉 260이평 W자 반등 검출 ──
        is_w, w_info = detect_w_rebound_30m(df_30m)
        sma260_val = 0.0
        diff_sma260 = 999.0
        if 'close' in df_30m.columns and len(df_30m) >= 260:
            sma260_series = df_30m['close'].rolling(260).mean()
            if not sma260_series.dropna().empty:
                sma260_val = float(sma260_series.iloc[-1])
                diff_sma260 = ((curr_close - sma260_val) / sma260_val) * 100

        # ── 2. 일봉 20이평선 상향 돌파 검출 ──
        daily_sma20 = 0.0
        diff_daily_sma20 = 999.0
        if len(daily_df) >= 20:
            daily_sma20_series = daily_df['close'].rolling(20).mean()
            daily_sma20 = float(daily_sma20_series.iloc[-1]) if not daily_sma20_series.dropna().empty else 0.0
            diff_daily_sma20 = ((curr_close - daily_sma20) / daily_sma20 * 100) if daily_sma20 > 0 else 999.0

        # ── 3. 가중 5-20 고가선(HH) 돌파 검출 ──
        hh_series = calculate_hh(df_30m)
        hh_val = float(hh_series.dropna().iloc[-1]) if not hh_series.dropna().empty else curr_close
        diff_hh = ((curr_close - hh_val) / hh_val * 100) if hh_val > 0 else 0.0

        # ── 4. 30분봉 3일선-5일선 골든크로스 수렴도 ──
        df_30m_day = calculate_realtime_day_smas(df_30m, daily_df)
        day_sma3 = float(df_30m_day['day_sma3'].iloc[-1]) if 'day_sma3' in df_30m_day.columns else 0.0
        day_sma5 = float(df_30m_day['day_sma5'].iloc[-1]) if 'day_sma5' in df_30m_day.columns else 0.0
        day_sma3_prev = float(df_30m_day['day_sma3'].iloc[-2]) if len(df_30m_day) >= 2 else day_sma3
        diff_3_5 = ((day_sma3 - day_sma5) / day_sma5 * 100) if day_sma5 > 0 else 999.0
        sma3_is_rising = day_sma3 >= day_sma3_prev

        # ── 종합 신호 분석 (현재 시점 바로 매수 타점인지 확인) ──
        live_signals = analyze_buy_signals(df_30m, None, daily_df)
        is_live_buy = live_signals.get('buy', False)

        # ── 근접 조건 점수(Score) 산출 ──
        score = 0.0
        tags = []
        notes = []

        # [W자 반등]
        if is_w:
            score += 100.0
            tags.append("🔥 [W자 반등 완성]")
            notes.append(w_info.get('description', '30분봉 260선 W자 완성'))
        elif -3.0 <= diff_sma260 <= 0.5 and len(df_30m) >= 260:
            score += 70.0
            tags.append("⚡ [260선 W자 돌파 임박]")
            notes.append(f"260이평({sma260_val:,.0f}원) 대비 {diff_sma260:+.2f}% 사정권")

        # [일봉 20선 돌파]
        if -2.0 <= diff_daily_sma20 <= 1.0 and daily_sma20 > 0:
            score += 40.0
            tags.append("🟢 [일봉 20선 돌파 임박]")
            notes.append(f"일봉 20이평({daily_sma20:,.0f}원) 대비 {diff_daily_sma20:+.2f}%")

        # [3-5일선 골든크로스 수렴]
        if sma3_is_rising and (-0.5 <= diff_3_5 <= 1.0):
            score += 35.0
            tags.append("⚡ [3-5선 수렴 돌파 임박]")
            notes.append(f"3일선({day_sma3:,.0f}) 5일선({day_sma5:,.0f}) 초수렴 ({diff_3_5:+.2f}%)")

        # [가중 고가선 HH 안착 및 돌파 사정권 (핵심 강화)]
        if -0.8 <= diff_hh <= 0.6 and hh_val > 0:
            score += 65.0  # 고가선에 바짝 안착한 종목 단독 합격권 부여!
            tags.append("🎯 [5-20 고가선(HH) 완벽 안착]")
            notes.append(f"가중고가선({hh_val:,.0f}원) 완벽안착({diff_hh:+.2f}%)")
        elif -1.8 <= diff_hh <= 1.2 and hh_val > 0:
            score += 50.0  # 고가선 사정권
            tags.append("🎯 [고가선(HH) 돌파 사정권]")
            notes.append(f"가중고가선({hh_val:,.0f}원) 대비 {diff_hh:+.2f}%")

        if is_live_buy:
            score += 50.0
            tags.insert(0, "🚀 [즉시 매수 타점]")

        # 필터: 유의미한 신호나 사정권(Score >= 50)에 든 종목만 반환
        if score < 50.0 and not is_live_buy:
            return None

        # 너무 고점 폭등한 종목(예: 260선 대비 +15% 초과 등)은 과열로 제외
        if sma260_val > 0 and diff_sma260 > 15.0:
            return None

        status_text = " | ".join(tags)
        note_text = " // ".join(notes)

        return {
            "code": code,
            "name": name,
            "weight": 1.2 if is_w else 1.0,
            "status": status_text,
            "close": curr_close,
            "target_price": max(hh_val, daily_sma20, sma260_val),
            "priority_score": round(score, 1),
            "note": note_text,
            "is_w_rebound": is_w,
            "is_live_buy": is_live_buy,
            "diff_sma260": round(diff_sma260, 2) if sma260_val > 0 else 0.0,
            "diff_daily_sma20": round(diff_daily_sma20, 2) if daily_sma20 > 0 else 0.0,
            "scanned_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }

    except Exception as e:
        logger.debug(f"[{name}({code})] 평가 중 에러: {e}")
        return None


def run_scanner(max_picks: int = 30):
    """전체 스캐너 메인 실행"""
    start_time = time.time()
    logger.info("=" * 65)
    logger.info(f" 🚀 [내일의 주도주/돌파 임박 종목 자동 스캐너] 가동 ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})")
    logger.info("=" * 65)

    client = RealAPIAdapter()
    universe = build_candidate_universe(client)

    results = []
    total = len(universe)

    logger.info(f"📊 총 {total}개 후보 종목의 30분봉 / 일봉 정밀 스캔을 시작합니다...")
    for idx, (code, name) in enumerate(universe.items(), start=1):
        if idx % 20 == 0 or idx == total:
            logger.info(f"⏳ 진행률: [{idx}/{total}] ({(idx/total)*100:.1f}%) | 발굴된 근접 후보: {len(results)}개")

        eval_res = evaluate_stock_proximity(code, name, client)
        if eval_res:
            results.append(eval_res)
            logger.info(f" ✨ 포착: [{name}({code})] {eval_res['status']} (점수: {eval_res['priority_score']}점)")

    # 정렬: W자 반등 여부 -> 우선순위 점수 -> 현재가
    results.sort(
        key=lambda x: (
            1 if x['is_w_rebound'] else 0,
            x['priority_score']
        ),
        reverse=True
    )

    top_picks = results[:max_picks]
    logger.info("=" * 65)
    logger.info(f" 🏆 스캔 완료! 최종 엄선된 내일의 공략주: {len(top_picks)}개 (상위 {max_picks}개 선정)")
    logger.info("=" * 65)

    # today_picks.json 포맷으로 저장
    picks_dict = {}
    print("\n" + "=" * 80)
    print(f"{'순위':^4} | {'종목명':^10} | {'코드':^8} | {'현재가':^10} | {'점수':^6} | {'상태 요약'}")
    print("-" * 80)

    for rank, p in enumerate(top_picks, start=1):
        code = p['code']
        picks_dict[code] = {
            "name": p['name'],
            "weight": p['weight'],
            "status": p['status'],
            "close": p['close'],
            "target_price": p['target_price'],
            "priority_score": p['priority_score'],
            "note": p['note'],
            "scanned_at": p['scanned_at']
        }
        print(f"{rank:^4} | {p['name']:<10} | {code:^8} | {p['close']:>9,.0f}원 | {p['priority_score']:>5.1f} | {p['status']}")

    print("=" * 80 + "\n")

    # 파일 저장
    picks_file = os.path.join(current_dir, "today_picks.json")
    try:
        with open(picks_file, 'w', encoding='utf-8') as f:
            json.dump(picks_dict, f, ensure_ascii=False, indent=4)
        logger.info(f"💾 [today_picks.json] 성공적으로 저장되었습니다! -> {picks_file}")
    except Exception as e:
        logger.error(f"❌ 파일 저장 실패: {e}")

    elapsed = time.time() - start_time
    logger.info(f"⏱️ 총 소요 시간: {elapsed:.1f}초. 내일 아침 봇(trading_bot.py)이 이 종목들을 즉시 감시합니다.")


if __name__ == "__main__":
    run_scanner()
