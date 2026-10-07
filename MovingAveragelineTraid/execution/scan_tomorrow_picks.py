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
from theme_manager import ThemeManager

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

from strategy_buy import (
    analyze_buy_signals, calculate_hh, calculate_realtime_day_smas,
    detect_w_rebound_30m, wma, evaluate_user_master_strategy,
    calculate_daily_tema_line, check_recent_5bar_surge
)
from strategy_15m_4formula_buy import evaluate_4formula_buy, Formula4Params
from strategy_15m_turnaround import evaluate_15m_entry, Turnaround15mParams
from theme_manager import ThemeManager

try:
    import yfinance as yf
except ImportError:
    yf = None

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("TomorrowScanner")


def scan_40pct_surge_stocks(client: RealAPIAdapter) -> dict:
    """
    최근 10거래일 내 2일간 40% 이상 급등한 주도주 전수 검색:
    - 대상: 코스피, 코스닥 전체 상장종목 (우선주/ETF/스팩 제외)
    - 시가총액: 1,000억원 ~ 5조원
    - 증거금률: 20%, 30%, 40%, 45%, 50% (증거금 100% 잡주 제외)
    - 급등 조건: 최근 10거래일 구간에서 2일간 상승률 >= 40% (종가 또는 장중 최고 기준)
    """
    surge_stocks = {}
    if yf is None:
        logger.warning("yfinance 라이브러리 미설치로 40% 급등주 전수 스캔을 건너뜁니다.")
        return surge_stocks

    exclude_keywords = [
        "KODEX", "TIGER", "KBSTAR", "KINDEX", "ARIRANG", "KOSEF", "HANARO",
        "ACE", "ETN", "스팩", "SOL", "인버스", "레버리지", "선물", "KOACT",
        "TIMEFOLIO", "WOORI", "히어로즈", "PLUS", "WON", "2X", "KRX", "합병", "RISE"
    ]

    try:
        candidates = []
        for m in ['0', '10']:
            suffix = '.KS' if m == '0' else '.KQ'
            res = client.real_client.stock_info_api.stock_information_list_request_ka10099(market_type=m)
            for s in res.get('list', []):
                code = s.get('code', '')
                name = s.get('name', '')
                state = s.get('state', '')

                if any(kw in name for kw in exclude_keywords) or name.endswith('우') or name.endswith('우B'):
                    continue

                if not any(f'증거금{r}%' in state for r in [20, 30, 40, 45, 50]):
                    continue

                try:
                    cnt = int(s.get('listCount', '0'))
                    prc = abs(int(s.get('lastPrice', '0')))
                    mcap = cnt * prc
                    if 100_000_000_000 <= mcap <= 5_000_000_000_000:
                        candidates.append((code, name, f"{code}{suffix}", mcap, state))
                except Exception:
                    pass

        logger.info(f"⚡ [급등주 전수 스캔] 시총 1,000억~5조 & 증거금 20~50% 1차 통과: {len(candidates)}개 종목 시세 분석 중...")
        tickers = [c[2] for c in candidates]
        t_map = {c[2]: (c[0], c[1]) for c in candidates}

        batch_size = 100
        for i in range(0, len(tickers), batch_size):
            batch = tickers[i:i+batch_size]
            try:
                df = yf.download(batch, period='1mo', progress=False)
                if df.empty or 'Close' not in df:
                    continue
                close_df = df['Close']
                high_df = df['High']

                for t in batch:
                    if t not in close_df.columns:
                        continue
                    sc = close_df[t].dropna()
                    sh = high_df[t].dropna() if t in high_df.columns else sc
                    if len(sc) < 3:
                        continue

                    recent_c = sc.iloc[-12:]
                    recent_h = sh.iloc[-12:]

                    max_2d = 0.0
                    for idx in range(2, len(recent_c)):
                        base = recent_c.iloc[idx-2]
                        if base > 0:
                            g_c = (recent_c.iloc[idx] - base) / base * 100.0
                            g_h = (recent_h.iloc[idx] - base) / base * 100.0
                            max_2d = max(max_2d, g_c, g_h)

                    if max_2d >= 40.0:
                        c_code, c_name = t_map[t]
                        surge_stocks[c_code] = c_name
                        logger.info(f"  🔥 [2일 40% 급등주 포착] {c_name}({c_code}) | 2일 최고상승: +{max_2d:.1f}%")
            except Exception as e:
                logger.debug(f"배치 스캔 오류 ({i}): {e}")

        logger.info(f"✅ 최근 10거래일 2일 40% 이상 급등주 총 {len(surge_stocks)}개 발굴 완료!")
    except Exception as e:
        logger.warning(f"급등주 전수 스캔 중 예외: {e}")

    return surge_stocks


def build_candidate_universe(client: RealAPIAdapter) -> dict:
    """스캔 대상 종목군 구성: 최근 10일내 2일 40% 급등 주도주 최우선 탑재"""
    universe = {}

    exclude_keywords = [
        "KODEX", "TIGER", "KBSTAR", "KINDEX", "ARIRANG", "KOSEF", "HANARO",
        "ACE", "ETN", "스팩", "SOL", "인버스", "레버리지", "선물", "KOACT",
        "TIMEFOLIO", "WOORI", "히어로즈", "PLUS", "WON", "2X", "KRX", "합병", "RISE"
    ]

    blacklist_path = os.path.join(current_dir, "blacklist.json")
    blacklist_codes = set()
    if os.path.exists(blacklist_path):
        try:
            with open(blacklist_path, 'r', encoding='utf-8') as f:
                blacklist_codes = set(json.load(f))
            logger.info(f"🚫 블랙리스트 매수금지 종목 {len(blacklist_codes)}개 로드 완료: {blacklist_codes}")
        except Exception:
            pass

    # 1. [최우선] 최근 10거래일 내 2일간 40% 이상 급등한 주도주 전수 스캔
    logger.info("🔍 1. 최근 10거래일 내 '2일간 40% 이상 급등' 주도주 전수 발굴 중...")
    surge_universe = scan_40pct_surge_stocks(client)
    for code, name in surge_universe.items():
        if code not in blacklist_codes:
            universe[code] = name

    # 2. 기존 관심종목 파일(today_picks.json) 병합
    picks_path = os.path.join(current_dir, "today_picks.json")
    if os.path.exists(picks_path):
        try:
            with open(picks_path, 'r', encoding='utf-8') as f:
                old_picks = json.load(f)
                for code, info in old_picks.items():
                    c = code.lstrip('A')
                    if c not in blacklist_codes and len(c) == 6 and c.isalnum() and c not in universe:
                        name = info.get('name') or client.get_stock_name(c)
                        universe[c] = name
        except Exception:
            pass

    logger.info(f"🎯 최종 스캔 대상 유니버스: 총 {len(universe)}개 급등 주도주 확정")
    return universe


def evaluate_stock_proximity(code: str, name: str, client: RealAPIAdapter, tm: ThemeManager = None) -> dict:
    """개별 종목의 30분봉 / 일봉 차트를 조회하여 4대 전략 근접도 및 테마 순위 가중치 평가"""
    try:
        df_15m = client.get_15m_candles(code)
        time.sleep(0.04)
        df_30m = client.get_30m_candles(code)
        time.sleep(0.04)
        daily_df = client.get_daily_candles(code)
        time.sleep(0.04)

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

        # ── 0. 유저 지정 4대 수식 & 타점 평가 ──
        is_naver_theme = tm.has_hot_theme(code) if tm else True
        eval_master = evaluate_user_master_strategy(df_15m, df_30m, daily_df, is_naver_theme=is_naver_theme) if (df_15m is not None and daily_df is not None) else {"should_buy": False}
        is_master_complete = eval_master.get("should_buy", False)

        # ── 0-1. 15분봉 4대 수식 올인원 완성 검출 ──
        eval_f4 = evaluate_4formula_buy(code, name, df_15m, current_price=curr_close) if (df_15m is not None and len(df_15m) >= 60) else {"should_buy": False, "details": {}}
        is_f4_complete = eval_f4.get("should_buy", False)
        f4_details = eval_f4.get("details", {})
        f4_m_line = f4_details.get("M선_저항가", 0.0)
        diff_f4_m = ((curr_close - f4_m_line) / f4_m_line * 100) if f4_m_line > 0 else 999.0

        # ── 0-2. 15분봉 20억 수급 및 3일선 U턴 변곡 검출 ──
        eval_15m = evaluate_15m_entry(code, name, df_15m, daily_df, current_price=curr_close) if (df_15m is not None and not df_15m.empty) else {"should_buy": False}
        is_15m_turnaround = eval_15m.get("should_buy", False)

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

        # ── 3. 일봉 기반 가중 5-20 고가선(HH) 돌파 및 안착 검출 ──
        hh_df_target = daily_df if (daily_df is not None and len(daily_df) >= 20) else df_30m
        hh_series = calculate_hh(hh_df_target)
        hh_val = float(hh_series.dropna().iloc[-1]) if not hh_series.dropna().empty else curr_close
        diff_hh = ((curr_close - hh_val) / hh_val * 100) if hh_val > 0 else 0.0

        # ── 4. 30분봉 3일선-5일선 골든크로스 수렴도 ──
        df_30m_day = calculate_realtime_day_smas(df_30m, daily_df)
        day_sma3 = float(df_30m_day['day_sma3'].iloc[-1]) if 'day_sma3' in df_30m_day.columns else 0.0
        day_sma5 = float(df_30m_day['day_sma5'].iloc[-1]) if 'day_sma5' in df_30m_day.columns else 0.0
        day_sma3_prev = float(df_30m_day['day_sma3'].iloc[-2]) if len(df_30m_day) >= 2 else day_sma3
        diff_3_5 = ((day_sma3 - day_sma5) / day_sma5 * 100) if day_sma5 > 0 else 999.0
        sma3_is_rising = day_sma3 >= day_sma3_prev

        # ── 근접 조건 점수(Score) 산출 ──
        score = 0.0
        tags = []
        notes = []

        # [유저 정의 4대 수식 완벽 부합]
        if is_master_complete:
            score += 350.0
            tags.append("🔥 [유저 4대수식 완벽 부합]")
            notes.append(eval_master.get('reason', '유저 정의 수식 완벽 부합 타점'))

        # [15분봉 4대 수식 올인원]
        if is_f4_complete:
            score += 150.0
            tags.append("🎯 [15분봉 4대수식 완성]")
            notes.append(eval_f4.get('reason', '15분봉 4대수식 완성'))
        elif f4_details.get('수식1_수급_캔들완성') and f4_details.get('수식3_1_20_60_첫정배열') and (-2.0 <= diff_f4_m <= 0.8):
            score += 85.0
            tags.append("⚡ [15분봉 4대수식 돌파 임박]")
            notes.append(f"15분봉 M선({f4_m_line:,.0f}원) 대비 {diff_f4_m:+.2f}% 사정권")

        # [15분봉 20억 수급 변곡]
        if is_15m_turnaround:
            score += 120.0
            tags.append("🚀 [15분봉 20억 수급변곡 완성]")
            notes.append(eval_15m.get('reason', '15분봉 20억 수급변곡'))

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

        # [가중 고가선 HH 수급 돌파 & 숨고르기 지지 안착 (핵심 강화)]
        if -1.8 <= diff_hh <= 2.0 and hh_val > 0:
            score += 100.0  # 일봉 HH선 돌파 후 숨고르기 지지 안착 종목 최우선 고득점 부여!
            tags.append("🎯 [일봉 HH선 숨고르기 안착 / 2차 폭발 임박]")
            notes.append(f"일봉 가중고가선({hh_val:,.0f}원) 완벽 안착({diff_hh:+.2f}%) ➔ 숨고르기 후 2차 급등 사정권")
        elif -3.0 <= diff_hh <= 3.5 and hh_val > 0:
            score += 65.0  # 고가선 사정권
            tags.append("🎯 [고가선(HH) 돌파 사정권]")
            notes.append(f"가중고가선({hh_val:,.0f}원) 대비 {diff_hh:+.2f}%")

        if is_live_buy:
            score += 50.0
            tags.insert(0, "🚀 [즉시 매수 타점]")

        # ── [신용한도초과 감지 및 경고 태그 부여] ──
        if hasattr(client, 'get_stock_credit_info'):
            try:
                credit_info = client.get_stock_credit_info(code)
                if credit_info.get('is_limit_exceeded'):
                    tags.append("⚠️ [신용한도초과]")
                    notes.append(f"신용한도초과 (신용비율 {credit_info.get('crd_rt', 0):.1f}%)")
                    score -= 30.0  # 신용 과열 종목 감점
            except Exception:
                pass

        # 필터: 유의미한 신호나 사정권(Score >= 50)에 든 종목만 반환
        if score < 50.0 and not is_live_buy:
            return None

        # 너무 고점 폭등한 종목(예: 260선 대비 +15% 초과 등)은 과열로 제외
        if sma260_val > 0 and diff_sma260 > 15.0:
            return None

        status_text = " | ".join(tags)
        note_text = " // ".join(notes)

        theme_w = tm.get_stock_weight(code) if tm else (1.2 if is_w else 1.0)
        return {
            "code": code,
            "name": name,
            "weight": theme_w,
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

    # 네이버증권 실시간 핫 테마 수집 (1~3위 1.35x, 4~10위 1.25x, 11~30위 1.15x)
    tm = ThemeManager()
    tm.load_top_themes(limit=30)

    client = RealAPIAdapter()
    universe = build_candidate_universe(client)

    results = []
    total = len(universe)

    logger.info(f"📊 총 {total}개 후보 종목의 30분봉 / 일봉 정밀 스캔을 시작합니다...")
    for idx, (code, name) in enumerate(universe.items(), start=1):
        if idx % 20 == 0 or idx == total:
            logger.info(f"⏳ 진행률: [{idx}/{total}] ({(idx/total)*100:.1f}%) | 발굴된 근접 후보: {len(results)}개")

        eval_res = evaluate_stock_proximity(code, name, client, tm=tm)
        if eval_res:
            results.append(eval_res)
            logger.info(f" ✨ 포착: [{name}({code})] {eval_res['status']} (점수: {eval_res['priority_score']}점, 테마배율: {eval_res['weight']}x)")

    # 정렬: W자 반등 여부 -> (우선순위 점수 * 테마 차등 가중치)
    results.sort(
        key=lambda x: (
            1 if x['is_w_rebound'] else 0,
            x['priority_score'] * x['weight']
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
