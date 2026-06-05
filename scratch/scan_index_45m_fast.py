import sys
import os
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Add real trading folder to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "real trading")))

import config
from kiwoom_client import KiwoomClient
from kiwoom_rest_api.koreanstock.sector import Sector
from indicator import calculate_indicators_pure

def fetch_index_components(client, sector_api, mrkt_tp, inds_cd, market_name):
    print(f"Fetching component list for {market_name}...")
    stocks = []
    cont_yn = "N"
    next_key = ""
    
    while True:
        try:
            res = sector_api.industrywise_stock_price_request_ka20002(
                mrkt_tp=mrkt_tp,
                inds_cd=inds_cd,
                stex_tp="1",
                cont_yn=cont_yn,
                next_key=next_key
            )
            if not res or res.get("return_code") != 0:
                print(f"Failed to fetch components for {market_name}: {res}")
                break
                
            items = res.get("inds_stkpc", [])
            for item in items:
                code = item.get("stk_cd", "").strip()
                name = item.get("stk_nm", "").strip()
                if code:
                    stocks.append({"code": code, "name": name, "market": market_name})
            
            next_key = res.get("next-key", "").strip()
            cont_yn = res.get("cont-yn", "N").strip()
            
            if not next_key or cont_yn == "N" or cont_yn == "":
                break
                
            time.sleep(0.35)
        except Exception as e:
            print(f"Error fetching components for {market_name}: {e}")
            break
            
    print(f"Loaded {len(stocks)} stocks for {market_name}.")
    return stocks

def get_45min_candles(client, stock_code, last_n_days=10):
    try:
        result = client.chart_api.stock_minute_chart_request_ka10080(
            stk_cd=stock_code,
            tic_scope="45",
            upd_stkpc_tp="1"
        )
        if not result:
            return []
        raw_candles = result.get("stk_min_pole_chart_qry", [])
        if not raw_candles:
            return []
            
        parsed_candles = []
        for item in raw_candles:
            raw_time = item.get("cntr_tm", "").strip()
            if len(raw_time) < 12:
                continue
            dt_str = f"{raw_time[:4]}-{raw_time[4:6]}-{raw_time[6:8]} {raw_time[8:10]}:{raw_time[10:12]}:00"
            date_only = f"{raw_time[:4]}-{raw_time[4:6]}-{raw_time[6:8]}"
            try:
                close_prc = abs(float(item.get("cur_prc", 0.0)))
                open_prc = abs(float(item.get("open_pric", 0.0)))
                high_prc = abs(float(item.get("high_pric", 0.0)))
                low_prc = abs(float(item.get("low_pric", 0.0)))
                volume = int(item.get("trde_qty", 0))
            except (ValueError, TypeError):
                continue
            parsed_candles.append({
                "time": dt_str,
                "date": date_only,
                "open": open_prc,
                "high": high_prc,
                "low": low_prc,
                "close": close_prc,
                "volume": volume
            })
        parsed_candles.sort(key=lambda x: x["time"])
        unique_dates = sorted(list(set(c["date"] for c in parsed_candles)))
        target_dates = unique_dates[-last_n_days:]
        return [c for c in parsed_candles if c["date"] in target_dates]
    except Exception:
        return []

def scan_single_stock(client, s, threshold_pct):
    code = s["code"]
    name = s["name"]
    market = s["market"]
    
    candles = get_45min_candles(client, code, last_n_days=10)
    if not candles or len(candles) < 60:
        return None
        
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
    
    dist_L = None
    dist_L_pct = None
    if l_line is not None and l_line > 0:
        dist_L = close_price - l_line
        dist_L_pct = (dist_L / l_line) * 100
        
    dist_gate = None
    dist_gate_pct = None
    if gate_line is not None and gate_line > 0:
        dist_gate = close_price - gate_line
        dist_gate_pct = (dist_gate / gate_line) * 100
        
    is_close_L = dist_L_pct is not None and abs(dist_L_pct) <= threshold_pct
    
    if is_close_L:
        s5 = latest.get("sma5")
        s20 = latest.get("sma20")
        s60 = latest.get("sma60")
        trend_ok = s5 is not None and s20 is not None and s60 is not None and s5 > s20 and s20 > s60
        
        min_dist = abs(dist_L_pct)
        
        return {
            "code": code,
            "name": name,
            "market": market,
            "close": close_price,
            "L": l_line,
            "dist_L_pct": dist_L_pct,
            "gate": gate_line,
            "dist_gate_pct": dist_gate_pct,
            "trend_ok": trend_ok,
            "min_dist": min_dist
        }
    return None

def run_scan():
    print("Initializing Kiwoom Client...")
    client = KiwoomClient()
    sector_api = Sector(base_url=client.base_url, token_manager=client.token_manager)
    
    # 1. Fetch Kospi 200 and Kosdaq 150 components
    kospi200_list = fetch_index_components(client, sector_api, "0", "201", "KOSPI 200")
    time.sleep(0.35)
    kosdaq150_list = fetch_index_components(client, sector_api, "1", "150", "KOSDAQ 150")
    
    candidates = kospi200_list + kosdaq150_list
    total_candidates = len(candidates)
    print(f"Total candidates to scan: {total_candidates}")
    
    results = []
    THRESHOLD_PCT = 1.5
    
    # Run concurrent threads
    # Using 5 workers to ensure absolute stability and zero computer freezing
    max_workers = 5
    print(f"Starting parallel scan with {max_workers} threads...")
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # Submit all tasks
        futures = {executor.submit(scan_single_stock, client, s, THRESHOLD_PCT): s for s in candidates}
        
        completed_count = 0
        for future in as_completed(futures):
            completed_count += 1
            if completed_count % 30 == 0 or completed_count == 1:
                print(f"Progress: {completed_count}/{total_candidates} stocks scanned...")
            try:
                res = future.result()
                if res:
                    results.append(res)
            except Exception as e:
                # Silently ignore individual stock errors to keep going
                pass
                
    # Sort results: closest first
    results.sort(key=lambda x: x["min_dist"])
    
    # Save report to markdown file in workspace root
    report_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "scan_result.md"))
    
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    md_content = f"# 🔍 45분봉 기준선(L) 근접 종목 스캔 리포트\n\n"
    md_content += f"- **기준 시간:** {now_str}\n"
    md_content += f"- **대상 지수:** KOSPI 200, KOSDAQ 150 (총 {total_candidates}개 종목)\n"
    md_content += f"- **스캔 기준:** 45분봉 차트 기준, 기준선 L 대비 **±{THRESHOLD_PCT}% 이내** 근접 종목\n"
    md_content += f"- **발견된 종목 수:** {len(results)}개\n\n"
    md_content += "| 순위 | 시장 | 종목코드 | 종목명 | 현재가 | 기준선(L) | L 이격도 | TEMA관문선 | TEMA 이격도 | 정배열(5>20>60) |\n"
    md_content += "| :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |\n"
    
    for rank, r in enumerate(results, 1):
        code = r["code"]
        name = r["name"]
        market = r["market"]
        close = f"{r['close']:,.0f}"
        
        l_str = f"{r['L']:,.0f}" if r['L'] is not None else "-"
        l_dist = f"{r['dist_L_pct']:+.2f}%" if r['dist_L_pct'] is not None else "-"
        
        gate_str = f"{r['gate']:,.0f}" if r['gate'] is not None else "-"
        gate_dist = f"{r['dist_gate_pct']:+.2f}%" if r['dist_gate_pct'] is not None else "-"
        
        trend = "✅ 정배열" if r['trend_ok'] else "❌ 역배열/혼조"
        
        md_content += f"| {rank} | {market} | `{code}` | **{name}** | {close}원 | {l_str}원 | **{l_dist}** | {gate_str}원 | **{gate_dist}** | {trend} |\n"
        
    md_content += "\n\n*이 보고서는 스크립트 실행 시마다 자동으로 갱신됩니다.*"
    
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(md_content)
        print(f"\nScan complete! Saved {len(results)} results to {report_path}")
    except Exception as e:
        print(f"Error saving report: {e}")
        
    return results

if __name__ == "__main__":
    run_scan()
