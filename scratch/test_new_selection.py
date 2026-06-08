
import sys
import os
import time
from datetime import datetime

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'real trading')))
from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), '..', 'real trading', '.env'))

print("=" * 65)
print("      키움증권 API 호출을 위한 APP KEY 및 SECRET KEY 입력이 필요합니다.")
print("      (엔터만 누르시면 .env 파일의 값을 사용합니다)")
print("=" * 65)
app_key = input("Enter Kiwoom APP KEY: ").strip()
app_secret = input("Enter Kiwoom APP SECRET: ").strip()
print("=" * 65)

if app_key and app_secret:
    os.environ["KIWOOM_API_KEY"] = app_key
    os.environ["KIWOOM_API_SECRET"] = app_secret

import config
if app_key and app_secret:
    config.KIWOOM_APP_KEY = app_key
    config.KIWOOM_APP_SECRET = app_secret

from kiwoom_client import KiwoomClient
from indicator import calculate_indicators_pure
from main import load_raw_watchlist

def test_selection():
    print("Testing new selection logic on current watchlist...")
    client = KiwoomClient()
    watchlist_path = os.path.join(os.path.dirname(__file__), '..', 'real trading', 'my_pick.xlsx')
    watchlist = load_raw_watchlist(watchlist_path)
    
    if not watchlist:
        print("Watchlist is empty.")
        return

    top_flu_rates_map = {}
    try:
        top_flu_rates_map = client.get_top_fluctuation_stocks_with_rates(market_type="000", limit=100)
    except Exception as e:
        print(f"Error fetching flu rates: {e}")

    results = []
    
    for stock in watchlist:
        code = stock['code']
        name = stock['name']
        print(f"Evaluating {name} ({code})...")
        
        try:
            # 일봉 및 주봉 가산점 로직
            daily_candles = client.get_daily_candles(code, last_n_days=200)
            daily_bonus_ok = False
            weekly_bonus_ok = False
            prev_d = None
            if daily_candles and len(daily_candles) >= 2:
                calculate_indicators_pure(
                    daily_candles,
                    use_compressed_peak=True,
                    tema_period1=config.TEMA_PERIOD_SHORT,
                    tema_period2=config.TEMA_PERIOD_LONG
                )
                today_str = datetime.now().strftime("%Y-%m-%d")
                if daily_candles[-1]['date'] == today_str:
                    prev_d = daily_candles[-2] if len(daily_candles) >= 2 else None
                else:
                    prev_d = daily_candles[-1]
                
                if prev_d:
                    daily_L = prev_d.get('L')
                    daily_whale = prev_d.get('whale_line')
                    if daily_L is not None:
                        is_near_L = (daily_L * 0.97 <= prev_d['close'] <= daily_L * 1.03)
                        is_breakout = False
                        if daily_whale is not None:
                            is_breakout = (prev_d['close'] >= daily_L * 0.97) and (prev_d['close'] >= daily_whale * 0.97)
                        daily_bonus_ok = (is_near_L or is_breakout)
                        
                weekly_candles = client.get_weekly_candles_from_daily(daily_candles)
                if weekly_candles and len(weekly_candles) >= 2:
                    calculate_indicators_pure(
                        weekly_candles,
                        use_compressed_peak=True,
                        tema_period1=config.TEMA_PERIOD_SHORT,
                        tema_period2=config.TEMA_PERIOD_LONG
                    )
                    w_latest = weekly_candles[-1]
                    w_L = w_latest.get('L')
                    w_whale = w_latest.get('whale_line')
                    if w_L is not None:
                        is_near_L_w = (w_L * 0.97 <= w_latest['close'] <= w_L * 1.03)
                        is_breakout_w = False
                        if w_whale is not None:
                            is_breakout_w = (w_latest['close'] >= w_L * 0.97) and (w_latest['close'] >= w_whale * 0.97)
                        weekly_bonus_ok = (is_near_L_w or is_breakout_w)
                        
            score = 0.0
            detail_msg = "데이터 부족 (캔들 수 부족)"
                        
            candles = client.get_15min_candles(code, last_n_days=7)
            if candles and len(candles) >= 60:
                calculate_indicators_pure(
                    candles,
                    use_compressed_peak=True,
                    tema_period1=config.TEMA_PERIOD_SHORT,
                    tema_period2=config.TEMA_PERIOD_LONG
                )
                latest = candles[-1]
                prev = candles[-2] if len(candles) > 1 else latest
                
                s5_now = latest.get("sma5")
                s20_now = latest.get("sma20")
                s5_prev = prev.get("sma5")
                s20_prev = prev.get("sma20")
                
                trend_ok = False
                slope_ok = False
                slope_pct = 0.0
                
                if s5_now is not None and s20_now is not None:
                    if s5_now > s20_now:
                        score += 100.0
                        trend_ok = True
                    
                    diff_now = s5_now - s20_now
                    if s5_prev is not None and s20_prev is not None:
                        diff_prev = s5_prev - s20_prev
                        if diff_now >= diff_prev:
                            score += 100.0
                            slope_ok = True
                            
                        if diff_prev > 0:
                            slope_pct = (diff_now - diff_prev) / diff_prev * 100.0
                            score += slope_pct * 10.0
                
                flu_pct = top_flu_rates_map.get(code, 0.0)
                if flu_pct == 0.0:
                    if len(candles) >= 5:
                        c_start = candles[-5]
                        flu_pct = ((latest["close"] - c_start["close"]) / c_start["close"]) * 100.0
                
                score += flu_pct * 10.0
                
                has_recent_sugeub_spike = False
                check_len = min(8, len(candles))
                for idx_check in range(len(candles) - check_len, len(candles)):
                    if candles[idx_check].get('signal_sugeub_spike', False):
                        has_recent_sugeub_spike = True
                        break
                
                if has_recent_sugeub_spike:
                    score += 150.0
                    
                if latest.get('signal_sugeub_spike', False):
                    score += 300.0
                    
                if daily_bonus_ok:
                    score += 100.0
                if weekly_bonus_ok:
                    score += 50.0
                    
                disp = latest.get("disparity_pct", 0.0)
                
                detail_msg = (
                    f"스코어: {score:.2f}점 | "
                    f"일봉보너스={daily_bonus_ok}(+100), 주봉보너스={weekly_bonus_ok}(+50) | "
                    f"정배열={trend_ok}, 이격확장={slope_ok}(기울기:{slope_pct:+.2f}%), "
                    f"등락률={flu_pct:+.2f}%, 수급돌파={latest.get('signal_sugeub_spike', False)}"
                )
                results.append({
                    'name': name,
                    'code': code,
                    'score': score,
                    'details': detail_msg
                })
            else:
                print(f"  -> [경고] 15분봉 데이터 부족 (가져온 캔들 수: {len(candles) if candles else 0})")
        except Exception as e:
            print(f"Error evaluating {name}: {e}")
            import traceback
            traceback.print_exc()
        time.sleep(0.5)

    results.sort(key=lambda x: x['score'], reverse=True)
    print("\n" + "="*80)
    print("📈 새로운 로직 기반 관심종목 스코어 랭킹")
    print("="*80)
    if not results:
        print("결과가 없습니다. 모든 종목의 데이터 수집에 실패했습니다 (장시간 외/API 한도/키 오류 등).")
    for idx, r in enumerate(results, 1):
        print(f"[{idx}위] {r['name']} ({r['code']})")
        print(f"  -> {r['details']}")
        print("-"*80)

if __name__ == "__main__":
    test_selection()
    input("프로그램이 종료되었습니다. 창을 닫으려면 엔터를 누르세요...")
