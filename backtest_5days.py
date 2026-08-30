import os
import sys
import json
import logging
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

# 경로 설정
current_dir = os.path.dirname(os.path.abspath(__file__))
execution_dir = os.path.join(current_dir, "MovingAveragelineTraid", "execution")
if execution_dir not in sys.path:
    sys.path.insert(0, execution_dir)

from strategy_buy import analyze_buy_signals
from strategy_sell import analyze_sell_signals

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("Backtest5Days")

try:
    import yfinance as yf
except ImportError:
    yf = None

def get_stock_data_yfinance(code: str, days: int = 40):
    """yfinance를 통한 15분봉, 30분봉, 일봉 데이터 조회 (국내 종목 심볼 매핑)"""
    if yf is None:
        return None, None, None
    
    clean_code = code.replace("A", "").strip()
    # 코스피/코스닥 심볼 시도
    symbols = [f"{clean_code}.KS", f"{clean_code}.KQ"]
    
    for sym in symbols:
        try:
            end_dt = datetime.now()
            start_dt = end_dt - timedelta(days=days)
            
            # 1. 15분봉 데이터 (최대 60일 가능)
            df_15m = yf.download(sym, start=start_dt.strftime("%Y-%m-%d"), end=end_dt.strftime("%Y-%m-%d"), interval="15m", progress=False)
            if df_15m.empty or len(df_15m) < 45:
                continue
            if isinstance(df_15m.columns, pd.MultiIndex):
                df_15m.columns = df_15m.columns.droplevel(1)
            df_15m.columns = [c.lower() for c in df_15m.columns]
            
            # 2. 30분봉 데이터 (15분봉 리샘플링 또는 30m 다운로드)
            df_30m = yf.download(sym, start=start_dt.strftime("%Y-%m-%d"), end=end_dt.strftime("%Y-%m-%d"), interval="30m", progress=False)
            if df_30m.empty:
                # 15분봉으로 30분봉 리샘플링
                df_30m = df_15m.resample('30min').agg({
                    'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
                }).dropna()
            else:
                if isinstance(df_30m.columns, pd.MultiIndex):
                    df_30m.columns = df_30m.columns.droplevel(1)
                df_30m.columns = [c.lower() for c in df_30m.columns]

            # 3. 일봉 데이터 (최근 150일)
            daily_start = end_dt - timedelta(days=200)
            daily_df = yf.download(sym, start=daily_start.strftime("%Y-%m-%d"), end=end_dt.strftime("%Y-%m-%d"), interval="1d", progress=False)
            if isinstance(daily_df.columns, pd.MultiIndex):
                daily_df.columns = daily_df.columns.droplevel(1)
            daily_df.columns = [c.lower() for c in daily_df.columns]

            return df_15m, df_30m, daily_df
        except Exception as e:
            continue
            
    return None, None, None

def run_backtest_on_stock(code: str, name: str, df_15m: pd.DataFrame, df_30m: pd.DataFrame, daily_df: pd.DataFrame, test_days: int = 5):
    """단일 종목에 대해 최근 5일간 시뮬레이션 백테스트 수행"""
    if df_15m is None or df_15m.empty or df_30m is None or df_30m.empty:
        return []

    # 최근 5영업일 날짜 추출
    all_dates = sorted(list(set(df_15m.index.date)))
    if len(all_dates) < test_days:
        test_dates = all_dates
    else:
        test_dates = all_dates[-test_days:]

    trades = []
    holding = False
    entry_price = 0.0
    entry_time = None
    entry_reason = ""
    
    # 15분봉 단위로 타임스텝을 진행하면서 매수/매도 시뮬레이션
    # (각 15분봉 시점에 사용 가능한 과거 30m/daily 데이터만 슬라이싱하여 룩어헤드 편향 방지)
    
    for i in range(45, len(df_15m)):
        current_15m_time = df_15m.index[i]
        current_date = current_15m_time.date()
        
        # 최근 5일 이전 데이터는 워밍업으로만 사용
        if current_date not in test_dates:
            continue

        curr_slice_15m = df_15m.iloc[:i+1]
        curr_price = float(curr_slice_15m.iloc[-1]['close'])
        
        # 해당 시점까지의 30분봉 데이터 슬라이스
        curr_slice_30m = df_30m[df_30m.index <= current_15m_time]
        if len(curr_slice_30m) < 20:
            continue

        # 해당 시점까지의 일봉 데이터 슬라이스
        if daily_df is not None and not daily_df.empty:
            curr_slice_daily = daily_df[daily_df.index.date <= current_date]
        else:
            curr_slice_daily = None

        if not holding:
            # ── 매수 조건 검사 ──
            buy_sig = analyze_buy_signals(curr_slice_30m, None, curr_slice_daily)
            if buy_sig.get('buy'):
                holding = True
                entry_price = curr_price
                entry_time = current_15m_time
                entry_reason = buy_sig.get('reason', '매수 조건 충족')
        else:
            # ── 매도 조건 검사 (15분봉 SMA5/40 데드크로스) ──
            sell_sig = analyze_sell_signals(curr_slice_15m)
            if sell_sig.get('sell'):
                exit_price = curr_price
                exit_time = current_15m_time
                # 수수료 및 거래세 0.20% 반영
                fee_tax_pct = 0.20
                gross_return = (exit_price - entry_price) / entry_price * 100
                net_return = gross_return - fee_tax_pct
                
                trades.append({
                    'code': code,
                    'name': name,
                    'entry_time': str(entry_time),
                    'entry_price': entry_price,
                    'exit_time': str(exit_time),
                    'exit_price': exit_price,
                    'gross_return': round(gross_return, 2),
                    'net_return': round(net_return, 2),
                    'entry_reason': entry_reason,
                    'exit_reason': sell_sig.get('reason', '15분봉 데드크로스 매도')
                })
                holding = False
                entry_price = 0.0
                entry_time = None

    # 마지막까지 보유 중인 포지션이 있다면 현재가로 청산 평가
    if holding:
        last_price = float(df_15m.iloc[-1]['close'])
        last_time = df_15m.index[-1]
        fee_tax_pct = 0.20
        gross_return = (last_price - entry_price) / entry_price * 100
        net_return = gross_return - fee_tax_pct
        trades.append({
            'code': code,
            'name': name,
            'entry_time': str(entry_time),
            'entry_price': entry_price,
            'exit_time': str(last_time) + " (미청산 평가)",
            'exit_price': last_price,
            'gross_return': round(gross_return, 2),
            'net_return': round(net_return, 2),
            'entry_reason': entry_reason,
            'exit_reason': '백테스트 종료 시점 보유 중'
        })

    return trades

def main():
    print("=" * 70)
    print(" 🚀 [전략 최근 5일간 백테스트 시뮬레이터] 가동")
    print(" 전략 규칙:")
    print("  - 매수: [일봉 SMA20 돌파 & HH 돌파] OR [30분봉 당일 SMA260 돌파 & HH 돌파]")
    print("  - 매도: 15분봉 SMA5 / SMA40 데드크로스")
    print("  - 수수료 및 거래세: 0.20% 적용")
    print("=" * 70)

    # 1. 대상 종목 리스트 로드 (today_picks.json 및 시장 주도/관심 종목)
    watch_file = os.path.join(execution_dir, "today_picks.json")
    stocks_to_test = {}
    
    if os.path.exists(watch_file):
        try:
            with open(watch_file, 'r', encoding='utf-8') as f:
                picks = json.load(f)
                for code, data in list(picks.items())[:25]: # 상위 25종목
                    name = data.get('name') or f"Stock_{code}"
                    stocks_to_test[code] = name
        except Exception as e:
            logger.error(f"today_picks.json 로드 실패: {e}")

    # 주요 대형주 및 테마 대표주 추가
    major_stocks = {
        "005930": "삼성전자",
        "000660": "SK하이닉스",
        "035420": "NAVER",
        "005380": "현대차",
        "086520": "에코프로",
        "042700": "한미반도체",
        "028300": "HLB",
        "001570": "금양",
        "348370": "엔켐",
        "014620": "성광벤드",
        "006340": "대원전선"
    }
    for c, n in major_stocks.items():
        stocks_to_test[c] = n

    print(f"\n📊 총 {len(stocks_to_test)}개 종목에 대해 최근 5일간 백테스트를 실행합니다...")
    
    all_trades = []
    
    for i, (code, name) in enumerate(stocks_to_test.items(), 1):
        print(f"[{i:02d}/{len(stocks_to_test):02d}] {name} ({code}) 데이터 수집 및 백테스트 중...")
        df_15m, df_30m, daily_df = get_stock_data_yfinance(code, days=40)
        
        if df_15m is None or df_15m.empty:
            continue
            
        trades = run_backtest_on_stock(code, name, df_15m, df_30m, daily_df, test_days=5)
        if trades:
            all_trades.extend(trades)
            print(f"  👉 {len(trades)}건 매매 발생!")

    # 결과 분석 및 집계
    print("\n" + "=" * 70)
    print(" 📈 최근 5일간 백테스트 종합 결과 보고서")
    print("=" * 70)
    
    if not all_trades:
        print("❌ 최근 5일간 조건을 만족하여 체결된 거래가 없습니다.")
        return

    df_results = pd.DataFrame(all_trades)
    total_trades = len(df_results)
    winning_trades = len(df_results[df_results['net_return'] > 0])
    losing_trades = len(df_results[df_results['net_return'] <= 0])
    win_rate = (winning_trades / total_trades) * 100 if total_trades > 0 else 0.0
    
    avg_return = df_results['net_return'].mean()
    total_cum_return = df_results['net_return'].sum()
    max_return = df_results['net_return'].max()
    min_return = df_results['net_return'].min()
    
    # 승리 거래 평균 수익 vs 패배 거래 평균 손실
    win_avg = df_results[df_results['net_return'] > 0]['net_return'].mean() if winning_trades > 0 else 0.0
    loss_avg = df_results[df_results['net_return'] <= 0]['net_return'].mean() if losing_trades > 0 else 0.0
    profit_factor = abs(win_avg * winning_trades / (loss_avg * losing_trades)) if losing_trades > 0 and loss_avg != 0 else np.nan

    print(f"• 총 거래 횟수    : {total_trades}회")
    print(f"• 승 / 패        : {winning_trades}승 {losing_trades}패")
    print(f"• 승률 (Win Rate): {win_rate:.1f}%")
    print(f"• 평균 순수익률   : {avg_return:+.2f}%")
    print(f"• 총 누적 순수익률: {total_cum_return:+.2f}%")
    print(f"• 최대 개별 수익 : {max_return:+.2f}%")
    print(f"• 최대 개별 손실 : {min_return:+.2f}%")
    print(f"• 손익비 (P/F)   : {profit_factor:.2f}" if not np.isnan(profit_factor) else "• 손익비 (P/F)   : N/A")
    print("-" * 70)
    
    print("\n📋 최근 5일간 상세 거래 내역:")
    display_cols = ['name', 'entry_time', 'entry_price', 'exit_time', 'exit_price', 'net_return', 'exit_reason']
    print(df_results[display_cols].to_string(index=False))
    
    # JSON 및 CSV로 결과 저장
    output_json = os.path.join(current_dir, "backtest_5days_result.json")
    df_results.to_json(output_json, orient="records", force_ascii=False, indent=2)
    print(f"\n💾 백테스트 결과가 저장되었습니다: {output_json}")

if __name__ == "__main__":
    main()
