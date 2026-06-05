import sys
import os

# Add paths
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "real trading")))
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

import config
from kiwoom_client import KiwoomClient
from indicator import calculate_indicators_pure, check_short_term_sugeub

def test_mtf_sugeub():
    print("=" * 60)
    print("        🧪 MULTI-TIMEFRAME SUGEUB CROSS-CHECK TEST")
    print("=" * 60)
    
    client = KiwoomClient()
    stock_code = "000660" # SK Hynix (High liquidity)
    
    # 1. Fetch 15m candles and compute main indicators
    print(f"\n1. Fetching 15-min candles for {stock_code}...")
    candles_15m = client.get_15min_candles(stock_code, last_n_days=3)
    if candles_15m:
        calculate_indicators_pure(candles_15m, use_compressed_peak=True)
        latest_15m = candles_15m[-1]
        print(f"✅ Latest 15m candle close: {latest_15m['close']:,.0f} KRW (Time: {latest_15m['time']})")
        print(f"   - 15m Sugeub value: {latest_15m.get('sugeub', 0.0):.2f} (Spike: {latest_15m.get('signal_sugeub_spike', False)})")
    else:
        print("❌ Failed to fetch 15m candles.")
        return

    # 2. Fetch 5m candles and evaluate check_short_term_sugeub
    print(f"\n2. Fetching 5-min candles for {stock_code}...")
    candles_5m = client.get_5min_candles(stock_code, last_n_days=2)
    if candles_5m:
        latest_5m = candles_5m[-1]
        sugeub_5m_ok = check_short_term_sugeub(candles_5m, 5)
        
        # Manually compute sugeub for printing
        h = latest_5m['high']
        l = latest_5m['low']
        o = latest_5m['open']
        c = latest_5m['close']
        v = latest_5m['volume']
        sugeub_5m = ((h + l + o + c) / 4.0) * v / 100000000.0
        
        print(f"✅ Latest 5m candle close: {c:,.0f} KRW (Time: {latest_5m['time']})")
        print(f"   - 5m Sugeub value: {sugeub_5m:.2f} (Threshold: >=7.0)")
        print(f"   - 5m Bullish check: {c > o} (Close: {c}, Open: {o})")
        print(f"   - 5m Volume spike (check_short_term_sugeub): {sugeub_5m_ok}")
    else:
        print("❌ Failed to fetch 5m candles.")

    # 3. Fetch 1m candles and evaluate check_short_term_sugeub
    print(f"\n3. Fetching 1-min candles for {stock_code}...")
    candles_1m = client.get_1min_candles(stock_code, last_n_days=1)
    if candles_1m:
        latest_1m = candles_1m[-1]
        sugeub_1m_ok = check_short_term_sugeub(candles_1m, 1)
        
        # Manually compute sugeub for printing
        h = latest_1m['high']
        l = latest_1m['low']
        o = latest_1m['open']
        c = latest_1m['close']
        v = latest_1m['volume']
        sugeub_1m = ((h + l + o + c) / 4.0) * v / 100000000.0
        
        print(f"✅ Latest 1m candle close: {c:,.0f} KRW (Time: {latest_1m['time']})")
        print(f"   - 1m Sugeub value: {sugeub_1m:.2f} (Threshold: >=1.5)")
        print(f"   - 1m Bullish check: {c > o} (Close: {c}, Open: {o})")
        print(f"   - 1m Volume spike (check_short_term_sugeub): {sugeub_1m_ok}")
    else:
        print("❌ Failed to fetch 1m candles.")

    print("\n" + "=" * 60)
    print("        🧪 TEST COMPLETED")
    print("=" * 60)

if __name__ == "__main__":
    test_mtf_sugeub()
