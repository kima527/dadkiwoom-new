"""
analyze_0904_intraday.py - 9월 4일 당일 기준 0904.csv 전 종목 매수/패스 정밀 시뮬레이션
====================================================================================
1. 0904.csv의 41개 종목에 대해 9월 4일 당일(09:00~15:30) 15분봉 시계열을 전수 분석
2. [매수 대상 종목]: 9월 4일 당일 신호 발생 시간, 조합 유형(Combo 3+4, W자 등), 우선순위 점수, 당일 장중 최고수익률 및 청산 결과
3. [패스/탈락 종목]: 탈락 사유(시총 10조 초과 대형주, 거래대금 미달, 3일선 변곡 미발생, 시가 이탈 등) 상세 분류
4. [원픽 1종목 최종 선택]: 9월 4일 우리 봇이 실제로 진입했을 '단 1개의 대장주' 선별
"""

import os
import sys
import logging
from datetime import datetime
import pandas as pd
import numpy as np

# 경로 설정
current_dir = os.path.dirname(os.path.abspath(__file__))
execution_dir = os.path.join(current_dir, "MovingAveragelineTraid", "execution")
if execution_dir not in sys.path:
    sys.path.insert(0, execution_dir)

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Analyze0904")

try:
    import yfinance as yf
except ImportError:
    yf = None

from strategy_15m_turnaround import analyze_15m_signals, evaluate_15m_entry, Turnaround15mParams
from backtest_0904 import load_0904_stocks, fetch_stock_candles


def analyze_september_4th():
    stocks = load_0904_stocks()
    if not stocks:
        return

    print("\n" + "=" * 90)
    print(" 🔍 [9월 4일(09/04) 조건검색식 41개 종목 실전 매수/패스 전수 분석]")
    print("=" * 90)

    params = Turnaround15mParams(min_daily_supply_money=20.0)

    bought_stocks = []
    passed_stocks = []

    target_date_str = None

    for code, name in stocks:
        df_15m, daily_df = fetch_stock_candles(code, days=35)
        if df_15m is None or daily_df is None:
            passed_stocks.append({
                "code": code,
                "name": name,
                "reason": "시세 데이터 수신 불가 (상장폐지/심볼 오류)",
                "details": "-"
            })
            continue

        # 최근 영업일 식별 (9월 4일)
        all_dates = sorted(list(set(pd.to_datetime(df_15m.index).date)))
        # 가장 최근 날짜 (09/04)
        target_date = all_dates[-1]
        target_date_str = str(target_date)

        # 9월 4일 이전 일봉과 9월 4일 15분봉 데이터 분리
        df_15m_today = df_15m[pd.to_datetime(df_15m.index).date == target_date]
        if df_15m_today.empty:
            passed_stocks.append({
                "code": code,
                "name": name,
                "reason": "9월 4일 거래 데이터 없음",
                "details": "-"
            })
            continue

        # ── 1. 종목 유니버스 필터 검사 ──
        # 1-1. 5일 평균 거래대금 10억 미만
        trade_val_5d = (daily_df['close'] * daily_df['volume']).tail(5).mean()
        if trade_val_5d < 1_000_000_000:
            passed_stocks.append({
                "code": code,
                "name": name,
                "reason": f"유동성 부족 제외 (5일 평균 거래대금 {trade_val_5d/1e8:.1f}억 < 10억)",
                "details": f"거래대금 {trade_val_5d/1e8:.1f}억"
            })
            continue

        # 1-2. 시가총액 10조 이상 대형주 제외
        try:
            ticker = yf.Ticker(f"{code}.KS" if f"{code}.KS" in df_15m.columns else f"{code}.KQ")
            # 대형주 코드 리스트 체크 (삼성전자, SK하이닉스, 삼성SDI 등)
            mega_caps = {"005930": "삼성전자(시총 400조)", "000660": "SK하이닉스(시총 120조)", "006400": "삼성SDI(시총 25조)"}
            if code in mega_caps:
                passed_stocks.append({
                    "code": code,
                    "name": name,
                    "reason": f"초대형주 필터 제외 ({mega_caps[code]})",
                    "details": "시총 10조 초과"
                })
                continue
        except Exception:
            pass

        # ── 2. 15분봉 전략 신호 분석 ──
        sig_df = analyze_15m_signals(df_15m, daily_df, params)
        if sig_df.empty:
            passed_stocks.append({
                "code": code,
                "name": name,
                "reason": "신호 계산 불가 (봉 수 부족)",
                "details": "-"
            })
            continue

        sig_today = sig_df[pd.to_datetime(sig_df.index).date == target_date]
        if sig_today.empty:
            continue

        # 9월 4일 당일 중 신호가 발생한 봉 탐색
        today_triggers = sig_today[sig_today['any_combo_signal']]

        if not today_triggers.empty:
            # 최초 신호 발생 봉
            first_trig = today_triggers.iloc[0]
            trig_time = str(today_triggers.index[0])
            entry_p = float(first_trig['close'])

            combo_types = []
            priority_score = 100.0

            if first_trig['combo_3_4']:
                combo_types.append("Combo 3+4(일봉20억수급+3일선변곡)")
                priority_score += 150.0
            if first_trig['combo_2_3']:
                combo_types.append("Combo 2+3(3-20골든크로스)")
                priority_score += 120.0
            if first_trig['combo_1_3']:
                combo_types.append("Combo 1+3(더블변곡)")
                priority_score += 100.0

            # 진입 후 당일 장마감까지의 주가 흐름 추적
            post_slice = sig_today.loc[today_triggers.index[0]:]
            max_p = float(post_slice['high'].max())
            min_p = float(post_slice['low'].min())
            close_p = float(post_slice['close'].iloc[-1])

            max_ret = (max_p - entry_p) / entry_p * 100.0
            min_ret = (min_p - entry_p) / entry_p * 100.0
            close_ret = (close_p - entry_p) / entry_p * 100.0

            day_supply = float(first_trig['day_supply_money'])
            m15_supply = float(first_trig['m15_money'])

            bought_stocks.append({
                "code": code,
                "name": name,
                "trig_time": trig_time[-8:-3], # "09:15" 형태
                "entry_price": entry_p,
                "combo": " / ".join(combo_types),
                "priority_score": priority_score,
                "day_supply": day_supply,
                "m15_supply": m15_supply,
                "max_ret": max_ret,
                "min_ret": min_ret,
                "close_ret": close_ret,
                "outcome": f"최고 +{max_ret:.2f}% / 종가 {close_ret:+.2f}%"
            })
        else:
            # 신호 미발생 사유 분석
            latest_bar = sig_today.iloc[-1]
            day_supply = float(latest_bar.get('day_supply_money', 0))
            is_above_open = bool(latest_bar.get('is_above_day_open', False))
            is_f4 = bool(latest_bar.get('sig_f4', False))
            is_f3 = bool(latest_bar.get('sig_f3', False))

            fail_reasons = []
            if day_supply < 20.0:
                fail_reasons.append(f"당일 수급 부족({day_supply:.1f}억 < 20억)")
            if not is_above_open:
                fail_reasons.append("당일 시가 하회(음봉 흐름)")
            if not is_f3:
                fail_reasons.append("3일선 U턴 변곡 미발생(단순 횡보/하락)")

            passed_stocks.append({
                "code": code,
                "name": name,
                "reason": ", ".join(fail_reasons) if fail_reasons else "15분봉 수급/변곡 조건 불일치",
                "details": f"당일수급 {day_supply:.1f}억 / 시가위={is_above_open}"
            })

    # ═══════════════════════════════════════════════════════════
    # 결과 출력
    # ═══════════════════════════════════════════════════════════
    print(f"\n기준일자: {target_date_str}")
    print(f"• 전체 분석 종목 수 : {len(stocks)}개")
    print(f"• ✅ 매수 조건 충족 종목 : {len(bought_stocks)}개")
    print(f"• ⏭️ 매수 패스/탈락 종목 : {len(passed_stocks)}개")
    print("=" * 90)

    # 1. 매수 체결 후보군 (우선순위 순 정렬)
    bought_stocks.sort(key=lambda x: (x['priority_score'], x['day_supply']), reverse=True)

    print("\n🟢 [1] 9월 4일 당일 '매수' 진입 대상 종목 (우선순위 순위표)")
    print("-" * 110)
    print(f"{'순위':<4} {'종목명':<12} {'신호시간':<8} {'진입가':>9} {'우선순위':>8} {'당일수급':>9} {'장중최고':>8} {'장마감수익':>10} {'타점 유형'}")
    print("-" * 110)
    for rank, b in enumerate(bought_stocks, 1):
        one_pick_mark = "👑 [1종목 원픽]" if rank == 1 else ""
        print(f"{rank:<4} {b['name']:<12} {b['trig_time']:<8} {b['entry_price']:>9,.0f}원 {b['priority_score']:>8.1f} {b['day_supply']:>8.1f}억 {b['max_ret']:>+7.2f}% {b['close_ret']:>+9.2f}%  {b['combo']} {one_pick_mark}")
    print("-" * 110)

    # 2. 패스/탈락 종목 리스트
    print("\n🔴 [2] 9월 4일 당일 '패스(탈락)' 종목 및 상세 사유")
    print("-" * 110)
    print(f"{'종목코드':<8} {'종목명':<14} {'탈락 사유':<45} {'참고 데이터'}")
    print("-" * 110)
    for p in passed_stocks:
        print(f"{p['code']:<8} {p['name']:<14} {p['reason']:<45} {p['details']}")
    print("-" * 110)


if __name__ == "__main__":
    analyze_september_4th()
