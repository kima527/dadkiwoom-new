import sys
import os

# Add paths
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "real trading")))
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

import config
from kiwoom_client import KiwoomClient
from kiwoom_rest_api.koreanstock.sector import Sector
from indicator import calculate_indicators_pure
from scan_index_45m_fast import get_45min_candles, fetch_index_components

def inspect_jeju():
    client = KiwoomClient()
    sector_api = Sector(base_url=client.base_url, token_manager=client.token_manager)
    
    code = "006220"
    name = "제주은행"
    
    print("--- Checking Index Membership ---")
    kospi200 = fetch_index_components(client, sector_api, "0", "201", "KOSPI 200")
    kosdaq150 = fetch_index_components(client, sector_api, "1", "150", "KOSDAQ 150")
    
    all_members = {s["code"]: s for s in (kospi200 + kosdaq150)}
    
    in_index = code in all_members
    market_name = all_members[code]["market"] if in_index else "N/A"
    print(f"[{name} ({code})] In K200/KD150: {in_index} (Market: {market_name})")
    
    # 2. Fetch candles and check indicators
    candles = get_45min_candles(client, code, last_n_days=10)
    print(f"[{name}] Candles fetched: {len(candles)} candles")
    if len(candles) >= 60:
        calculate_indicators_pure(
            candles,
            use_compressed_peak=True,
            tema_period1=config.TEMA_PERIOD_SHORT,
            tema_period2=config.TEMA_PERIOD_LONG
        )
        latest = candles[-1]
        close_price = latest["close"]
        l_line = latest.get("L")
        gate_line = latest.get("tema_gate_line")
        
        print(f"[{name}] Close Price: {close_price:,.0f} KRW")
        
        if l_line is not None:
            dist_L = close_price - l_line
            dist_L_pct = (dist_L / l_line) * 100
            print(f"  - L-line: {l_line:,.0f} KRW, Disparity: {dist_L_pct:+.2f}% (Close to L: {abs(dist_L_pct) <= 1.5})")
        else:
            print("  - L-line: None")
            
        if gate_line is not None:
            dist_gate = close_price - gate_line
            dist_gate_pct = (dist_gate / gate_line) * 100
            print(f"  - TEMA Gate-line: {gate_line:,.0f} KRW, Disparity: {dist_gate_pct:+.2f}% (Close to Gate: {abs(dist_gate_pct) <= 1.5})")
        else:
            print("  - TEMA Gate-line: None")
    else:
        print(f"[{name}] Too few candles to calculate indicators (Needs 60+, got {len(candles)})")
    print("-" * 50)

if __name__ == "__main__":
    inspect_jeju()
