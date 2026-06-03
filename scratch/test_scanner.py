import sys
import os
import logging
from datetime import datetime, timezone, timedelta

# Add parent directory to path to import configs
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "Paper trading")))

import config
from kiwoom_client import KiwoomClient
from indicator import calculate_indicators_pure
from main import load_raw_watchlist, WATCHLIST_PATH

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

def test_scanner():
    logger.info("Initializing KiwoomClient...")
    client = KiwoomClient()
    
    KST = timezone(timedelta(hours=9))
    current_date = datetime.now(KST).strftime("%Y-%m-%d")
    
    logger.info(f"Running Momentum Score scanner test for date: {current_date}")
    raw_watchlist = load_raw_watchlist(WATCHLIST_PATH)
    logger.info(f"Loaded raw watchlist: {[s['name'] for s in raw_watchlist]}")
    
    top_value_codes = []
    top_flu_rates_map = {}
    try:
        top_value_codes = client.get_top_trading_value_stocks(market_type="000", limit=100)
        top_flu_rates_map = client.get_top_fluctuation_stocks_with_rates(market_type="000", limit=100)
        logger.info(f"Fetched top trading value codes count: {len(top_value_codes)}")
        logger.info(f"Fetched top fluctuation codes count: {len(top_flu_rates_map)}")
    except Exception as rank_err:
        logger.error(f"Failed to fetch market rankings: {rank_err}")

    top_flu_codes = list(top_flu_rates_map.keys())

    # Intersection logic
    filtered_candidates = []
    filter_reason = "Fallback (전체 관심종목)"
    
    if top_value_codes and top_flu_codes:
        val_set = set(top_value_codes)
        flu_set = set(top_flu_codes)
        leaders = val_set.intersection(flu_set)
        
        filtered_candidates = [s for s in raw_watchlist if s["code"] in leaders]
        if filtered_candidates:
            filter_reason = f"거래대금 & 등락률 상위 교집합 ({len(filtered_candidates)}종목)"
        else:
            filtered_candidates = [s for s in raw_watchlist if s["code"] in val_set or s["code"] in flu_set]
            if filtered_candidates:
                filter_reason = f"거래대금 또는 등락률 상위 부분 매칭 ({len(filtered_candidates)}종목)"
            else:
                filtered_candidates = raw_watchlist
                filter_reason = "매칭 종목 없음 -> 전체 관심종목 fallback"
    else:
        filtered_candidates = raw_watchlist
        filter_reason = "랭킹 API 호출 불가/데이터 없음 -> 전체 관심종목 fallback"

    logger.info(f"🎯 Target Candidates Group: {filter_reason}")
    logger.info(f"Candidate stocks: {[s['name'] for s in filtered_candidates]}")
    
    best_code = None
    best_name = None
    best_score = -float('inf')
    best_disp = 0.0
    best_details = ""
    
    for stock in filtered_candidates:
        code = stock["code"]
        name = stock["name"]
        try:
            # 1. 일봉 기준선/세력선 필터링 검증
            daily_candles = client.get_daily_candles(code, last_n_days=90)
            daily_breakout_ok = False
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
                    if len(daily_candles) >= 2:
                        prev_d = daily_candles[-2]
                else:
                    prev_d = daily_candles[-1]
                
                if prev_d:
                    daily_L = prev_d.get('L')
                    daily_whale = prev_d.get('whale_line')
                    if daily_L is not None and daily_whale is not None:
                        daily_breakout_ok = (prev_d['close'] >= daily_L * 0.97) and (prev_d['close'] >= daily_whale * 0.97)
            
            if not daily_breakout_ok:
                logger.info(f"-> {name} ({code}) | Skip: 일봉 기준선 조건 미달 (기준미달)")
                continue
                
            logger.info(f"Fetching candles for {name} ({code})...")
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
                
                score = 0.0
                trend_ok = False
                slope_ok = False
                slope_pct = 0.0
                
                if s5_now is not None and s20_now is not None:
                    # ① 5이평 > 20이평 (정배열 상승세) -> +100점
                    if s5_now > s20_now:
                        score += 100.0
                        trend_ok = True
                    
                    # ② 이격도를 좁히지 않고 벌어지거나 유지하며 올라가는가?
                    diff_now = s5_now - s20_now
                    if s5_prev is not None and s20_prev is not None:
                        diff_prev = s5_prev - s20_prev
                        if diff_now >= diff_prev:
                            score += 100.0
                            slope_ok = True
                            
                        if diff_prev > 0:
                            slope_pct = (diff_now - diff_prev) / diff_prev * 100.0
                            score += slope_pct * 10.0
                
                # ③ 등락률 점수 가중치 (+10 * 등락률%)
                flu_pct = top_flu_rates_map.get(code, 0.0)
                if flu_pct == 0.0:
                    if len(candles) >= 5:
                        c_start = candles[-5]
                        flu_pct = ((latest["close"] - c_start["close"]) / c_start["close"]) * 100.0
                
                score += flu_pct * 10.0
                disp = latest.get("disparity_pct", 0.0)
                
                detail_msg = (
                    f"정배열={trend_ok}, 이격확장={slope_ok}(기울기:{slope_pct:+.2f}%), "
                    f"등락률={flu_pct:+.2f}%, TEMA이격={disp:.2f}%"
                )
                
                logger.info(f"-> {name} ({code}) | Score: {score:.2f} | {detail_msg}")
                
                if score > best_score:
                    best_score = score
                    best_code = code
                    best_name = name
                    best_disp = disp
                    best_details = detail_msg
            else:
                logger.warning(f"-> {name} ({code}) has insufficient candles: {len(candles) if candles else 0}")
        except Exception as ex:
            logger.error(f"Error scanning {name} ({code}): {ex}")
            
    if not best_code and raw_watchlist:
        best_code = raw_watchlist[0]["code"]
        best_name = raw_watchlist[0]["name"]
        best_disp = 0.0
        best_details = "N/A"
        logger.warning(f"Fallback to first stock: {best_name} ({best_code})")
        
    if best_code:
        logger.info(f"🎯 FINAL MOMENTUM SELECTION: {best_name} ({best_code}) | Score: {best_score:.2f} | Details: {best_details} | Filter: {filter_reason}")
        selected_file = "selected_stock.txt"
        with open(selected_file, "w", encoding="utf-8") as f:
            f.write(f"{current_date},{best_code},{best_name}")
        logger.info(f"Saved selection to {selected_file}")

if __name__ == "__main__":
    test_scanner()
