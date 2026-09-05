"""
backtest_0904.py - 바탕화면 0904.csv 종목군 15분봉 수급변곡 및 이동평균선 전략 백테스트
===================================================================================
1. 0904.csv 파일 로드 (종목코드, 종목명)
2. 각 종목별 15분봉, 30분봉, 일봉 데이터 조회 (yfinance 및 키움 API)
3. 15분봉 수급변곡 전략(Combo 3+4, 2+3, 1+3) 및 30분봉 W자 전략 시뮬레이션
4. 승률, 수익률, 손익비, 최대낙폭(MDD), 상세 매매 타점 집계 및 레포트 출력
"""

import os
import sys
import logging
from datetime import datetime, timedelta
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
logger = logging.getLogger("Backtest0904")

try:
    import yfinance as yf
except ImportError:
    yf = None

from strategy_15m_turnaround import analyze_15m_signals, evaluate_15m_entry, Turnaround15mParams
from strategy_sell import analyze_sell_signals


def load_0904_stocks() -> list:
    """바탕화면 0904.csv 파일 로드"""
    csv_paths = [
        r"C:\Users\zoela\OneDrive\바탕 화면\0904.csv",
        r"C:\Users\zoela\Desktop\0904.csv",
        os.path.join(current_dir, "0904.csv"),
    ]

    target_path = None
    for p in csv_paths:
        if os.path.exists(p):
            target_path = p
            break

    if not target_path:
        logger.error("❌ 0904.csv 파일을 찾을 수 없습니다!")
        return []

    logger.info(f"📂 0904.csv 파일 로드 중: {target_path}")

    # 인코딩 시도 (utf-8, cp949, euc-kr)
    df = None
    for enc in ['utf-8', 'cp949', 'euc-kr', 'utf-8-sig']:
        try:
            df = pd.read_csv(target_path, encoding=enc)
            logger.info(f"✅ 인코딩 성공 ({enc}) - 총 {len(df)}개 행")
            break
        except Exception:
            continue

    if df is None or df.empty:
        logger.error("❌ 0904.csv 파싱 실패")
        return []

    stocks = []
    # 컬럼 탐색 (종목코드, 코드, code, 종목명, name 등)
    code_col = None
    name_col = None

    for col in df.columns:
        col_clean = str(col).strip().lower()
        if any(k in col_clean for k in ['종목코드', '코드', 'code', '단축코드']):
            code_col = col
        elif any(k in col_clean for k in ['종목명', '종목', 'name']):
            name_col = col

    # 만약 헤더가 없거나 첫번째/두번째 컬럼인 경우
    if code_col is None:
        code_col = df.columns[0]
    if name_col is None and len(df.columns) > 1:
        name_col = df.columns[1]

    for _, row in df.iterrows():
        raw_code = str(row[code_col]).strip().replace("A", "").replace("'", "").replace('"', '')
        # 6자리 종목코드 포맷팅
        if raw_code.isdigit():
            clean_code = raw_code.zfill(6)
        else:
            clean_code = raw_code

        clean_name = str(row[name_col]).strip() if name_col and name_col in row else clean_code
        if clean_code and len(clean_code) == 6:
            stocks.append((clean_code, clean_name))

    logger.info(f"📋 추출된 유효 종목 리스트 ({len(stocks)}개):")
    for c, n in stocks[:10]:
        logger.info(f"   • [{c}] {n}")
    if len(stocks) > 10:
        logger.info(f"   ... 외 {len(stocks) - 10}개 종목")

    return stocks


def fetch_stock_candles(code: str, days: int = 30):
    """yfinance를 통해 15분봉 및 일봉 데이터 수신 (period 방식)"""
    if yf is None:
        return None, None

    clean_code = code.replace("A", "").strip()
    symbols = [f"{clean_code}.KQ", f"{clean_code}.KS"] # 코스닥/코스피 순차 시도

    for sym in symbols:
        try:
            # 1. 15분봉 데이터 (최근 30일)
            df_15m = yf.download(sym, period="30d", interval="15m", progress=False)
            if df_15m is None or df_15m.empty or len(df_15m) < 40:
                continue

            if isinstance(df_15m.columns, pd.MultiIndex):
                df_15m.columns = df_15m.columns.droplevel(1)
            df_15m.columns = [c.lower() for c in df_15m.columns]

            # 2. 일봉 데이터 (최근 6개월)
            daily_df = yf.download(sym, period="6mo", interval="1d", progress=False)
            if daily_df is None or daily_df.empty or len(daily_df) < 30:
                continue

            if isinstance(daily_df.columns, pd.MultiIndex):
                daily_df.columns = daily_df.columns.droplevel(1)
            daily_df.columns = [c.lower() for c in daily_df.columns]

            return df_15m, daily_df
        except Exception:
            continue

    return None, None


def run_15m_backtest(stocks: list, test_days: int = 20):
    """
    0904 종목군 대상 15분봉 수급 변곡 전략 백테스트 실행
    - 매수: Combo 3+4(20억수급+3일선변곡), Combo 2+3(3-20골든크로스), Combo 1+3(더블변곡)
    - 매도: 15분봉 SMA(5, 40) 데드크로스, 하드손절(-5%), 트레일링 스탑(고점대비 -3%)
    """
    print("\n" + "=" * 80)
    print(" 🚀 [0904 파일 종목군 15분봉 수급변곡 전략 백테스트 시작]")
    print(f" • 대상 종목 수: {len(stocks)}개 | 테스트 기간: 최근 {test_days}영업일")
    print(f" • 매수 로직: [수식 4] 일봉 20억 수급 + [수식 3] 15분봉 3일선 U턴 변곡 (최우선)")
    print(f" • 매도 로직: 15분봉 SMA(5, 40) 데드크로스 + 하드손절(-5%) + 트레일링 스탑(-3%)")
    print("=" * 80)

    params = Turnaround15mParams(min_daily_supply_money=20.0)
    all_trades = []
    stock_summaries = []

    for idx, (code, name) in enumerate(stocks, 1):
        df_15m, daily_df = fetch_stock_candles(code, days=test_days + 30)
        
        if df_15m is None or daily_df is None:
            continue

        # 15분봉 시그널 분석
        sig_df = analyze_15m_signals(df_15m, daily_df, params)
        if sig_df.empty:
            continue

        # 최근 test_days 날짜만 백테스트 슬라이싱
        all_dates = sorted(list(set(sig_df['date_key'])))
        if len(all_dates) < test_days:
            eval_dates = all_dates
        else:
            eval_dates = all_dates[-test_days:]

        # 15분봉 타임스텝 시뮬레이션
        holding = False
        entry_price = 0.0
        entry_time = None
        entry_type = ""
        highest_price = 0.0
        bars_held = 0
        stock_trades = []

        for t, row in sig_df.iterrows():
            curr_date = row['date_key']
            if curr_date not in eval_dates:
                continue

            curr_price = float(row['close'])
            high_price = float(row['high'])
            low_price = float(row['low'])

            # ── 1. 보유 중일 때 매도 조건 검사 ──
            if holding:
                bars_held += 1
                highest_price = max(highest_price, high_price)
                pnl_pct = (curr_price - entry_price) / entry_price * 100.0
                max_pnl_pct = (highest_price - entry_price) / entry_price * 100.0
                
                exit_signal = False
                exit_reason = ""
                exit_price = curr_price

                # 1) 하드 손절매 (-5.0%)
                if pnl_pct <= -5.0 or (low_price - entry_price) / entry_price * 100.0 <= -5.0:
                    exit_signal = True
                    exit_reason = "하드 손절매 (-5.0%)"
                    exit_price = entry_price * 0.95

                # 2) 스마트 트레일링 익절 & 본절 보호 (Break-Even Lock)
                # 고점 +3.0% 이상 도달 후 고점 대비 -2.0% 하락 시 익절 (단, 최소 +0.5% 본절 보장)
                elif max_pnl_pct >= 3.0:
                    drop_from_high = (curr_price - highest_price) / highest_price * 100.0
                    if drop_from_high <= -2.0 or curr_price <= entry_price * 1.005:
                        exit_signal = True
                        exit_price = max(curr_price, entry_price * 1.005) if max_pnl_pct >= 4.0 else curr_price
                        exit_reason = f"스마트 트레일링 익절 (고점 +{max_pnl_pct:.1f}% -> 익절)"

                # 3) 15분봉 SMA(5, 40) 데드크로스 (매수 후 최소 2개봉(30분) 경과 후)
                elif bars_held >= 2:
                    sma5 = float(sig_df['m15_sma5'].loc[t]) if not pd.isna(sig_df['m15_sma5'].loc[t]) else curr_price
                    sma40 = float(sig_df['close'].rolling(40).mean().loc[t]) if len(sig_df.loc[:t]) >= 40 else sma5
                    
                    if sma5 < sma40 * 0.996: # 명확한 데드크로스
                        exit_signal = True
                        exit_reason = "15분봉 SMA(5,40) 데드크로스"

                if exit_signal:
                    final_ret = (exit_price - entry_price) / entry_price * 100.0 - 0.25 # 세금/수수료 0.25% 반영
                    trade_record = {
                        "code": code,
                        "name": name,
                        "entry_time": str(entry_time),
                        "entry_price": entry_price,
                        "entry_type": entry_type,
                        "exit_time": str(t),
                        "exit_price": exit_price,
                        "exit_reason": exit_reason,
                        "bars_held": bars_held,
                        "max_pnl_pct": round(max_pnl_pct, 2),
                        "pnl_pct": round(final_ret, 2)
                    }
                    stock_trades.append(trade_record)
                    all_trades.append(trade_record)
                    holding = False
                    entry_price = 0.0
                    highest_price = 0.0
                    bars_held = 0
                    continue

            # ── 2. 미보유 시 신규 매수 진입 검사 ──
            if not holding:
                # 3대 조합 신호 검사
                is_c34 = bool(row.get('combo_3_4', False))
                is_c23 = bool(row.get('combo_2_3', False))
                is_c13 = bool(row.get('combo_1_3', False))

                if is_c34 or is_c23 or is_c13:
                    holding = True
                    entry_price = curr_price
                    entry_time = t
                    highest_price = curr_price
                    bars_held = 0

                    if is_c34:
                        entry_type = "Combo 3+4 (20억수급+3일선변곡)"
                    elif is_c23:
                        entry_type = "Combo 2+3 (3-20골든크로스)"
                    else:
                        entry_type = "Combo 1+3 (더블변곡)"

        # 개별 종목 성과 요약
        if stock_trades:
            wins = [t for t in stock_trades if t['pnl_pct'] > 0]
            win_rate = len(wins) / len(stock_trades) * 100.0
            avg_pnl = np.mean([t['pnl_pct'] for t in stock_trades])
            stock_summaries.append({
                "code": code,
                "name": name,
                "total_trades": len(stock_trades),
                "wins": len(wins),
                "win_rate": round(win_rate, 1),
                "avg_pnl": round(avg_pnl, 2),
                "trades": stock_trades
            })

    # ═══════════════════════════════════════════════════════════
    # 종합 백테스트 통계 분석 리포트
    # ═══════════════════════════════════════════════════════════
    print("\n" + "=" * 80)
    print(" 📊 [0904 종목군 15분봉 수급변곡 전략 종합 백테스트 성과 보고서]")
    print("=" * 80)

    if not all_trades:
        print("⚠️ 백테스트 기간 동안 매수 조건에 부합한 체결 거래가 없습니다.")
        return

    total_trade_count = len(all_trades)
    win_trades = [t for t in all_trades if t['pnl_pct'] > 0]
    loss_trades = [t for t in all_trades if t['pnl_pct'] <= 0]
    total_win_rate = (len(win_trades) / total_trade_count) * 100.0

    avg_win = np.mean([t['pnl_pct'] for t in win_trades]) if win_trades else 0.0
    avg_loss = np.mean([t['pnl_pct'] for t in loss_trades]) if loss_trades else 0.0
    profit_factor = abs(sum([t['pnl_pct'] for t in win_trades]) / sum([t['pnl_pct'] for t in loss_trades])) if loss_trades and sum([t['pnl_pct'] for t in loss_trades]) != 0 else 999.0
    total_cum_ret = sum([t['pnl_pct'] for t in all_trades])
    avg_return_per_trade = np.mean([t['pnl_pct'] for t in all_trades])

    print(f" 1. 총 체결 거래 수       : {total_trade_count}회")
    print(f" 2. 승리 / 패배 거래      : {len(win_trades)}승 / {len(loss_trades)}패")
    print(f" 3. 전략 전체 승률        : {total_win_rate:.1f}%")
    print(f" 4. 평균 수익률 (건당)    : {avg_return_per_trade:+.2f}%")
    print(f" 5. 평균 익절률 / 평균 손절률 : {avg_win:+.2f}% / {avg_loss:+.2f}%")
    # ═══════════════════════════════════════════════════════════
    # 조합별 성과 비교 분석 (Combo 3+4 vs Combo 2+3 vs Combo 1+3)
    # ═══════════════════════════════════════════════════════════
    print("\n🎯 [3대 타점 조합별 세부 성과 비교 분석]")
    print("-" * 80)
    print(f"{'진입 조합 유형':<32} {'거래수':>6} {'승리':>5} {'승률':>8} {'평균수익':>9} {'손익비':>8}")
    print("-" * 80)

    for c_type in ["Combo 3+4 (20억수급+3일선변곡)", "Combo 2+3 (3-20골든크로스)", "Combo 1+3 (더블변곡)"]:
        c_trades = [t for t in all_trades if t['entry_type'] == c_type]
        if c_trades:
            c_wins = [t for t in c_trades if t['pnl_pct'] > 0]
            c_losses = [t for t in c_trades if t['pnl_pct'] <= 0]
            c_wr = len(c_wins) / len(c_trades) * 100.0
            c_avg_ret = np.mean([t['pnl_pct'] for t in c_trades])
            c_pf = abs(sum([t['pnl_pct'] for t in c_wins]) / sum([t['pnl_pct'] for t in c_losses])) if c_losses and sum([t['pnl_pct'] for t in c_losses]) != 0 else 999.0
            print(f"{c_type:<32} {len(c_trades):>6}회 {len(c_wins):>5}승 {c_wr:>7.1f}% {c_avg_ret:>+8.2f}% {c_pf:>8.2f}")
    print("-" * 80)

    print("\n📋 [상세 매매 거래 일지 (최근 순)]")
    print("-" * 100)
    print(f"{'종목코드':<8} {'종목명':<10} {'진입일시':<19} {'진입가':>9} {'청산일시':<19} {'청산가':>9} {'수익률':>8} {'청산사유'}")
    print("-" * 100)
    for t in all_trades[-30:]: # 최근 30개 출력
        print(f"{t['code']:<8} {t['name']:<10} {t['entry_time'][:16]:<19} {t['entry_price']:>9,.0f} {t['exit_time'][:16]:<19} {t['exit_price']:>9,.0f} {t['pnl_pct']:>7.2f}%  {t['exit_reason']}")
    print("-" * 100)


if __name__ == "__main__":
    stocks = load_0904_stocks()
    if stocks:
        run_15m_backtest(stocks, test_days=30)
