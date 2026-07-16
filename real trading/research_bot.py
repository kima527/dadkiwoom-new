import asyncio
import os
import sys
import datetime

# 프로젝트 루트 경로 추가
sys.path.append(os.path.abspath(os.path.dirname(__file__)))

from kiwoom_client import KiwoomClient

async def run_research():
    print("========================================")
    print("  주도주 종가 리서치 봇 (Market Research)")
    print("========================================")
    print(f"실행 시간: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    
    client = KiwoomClient()
    
    print("[1/4] 당일 거래대금 상위 100위 조회 중...")
    top_value_codes = await asyncio.to_thread(client.get_top_trading_value_stocks, "000", 100)
    
    print("[2/4] 당일 등락률 상위 100위 조회 중...")
    top_fluct_dict = await asyncio.to_thread(client.get_top_fluctuation_stocks_with_rates, "000", 100)
    
    if not top_value_codes or not top_fluct_dict:
        print("❌ API 데이터를 가져오지 못했습니다.")
        return
        
    print("[3/4] 종목 이름 일괄 조회 중...")
    names_dict = await asyncio.to_thread(client.get_stock_names, top_value_codes)
        
    # 완벽한 잡주/파생상품 차단 리스트
    exclude_keywords = [
        "KODEX", "TIGER", "KBSTAR", "KINDEX", "ARIRANG", "KOSEF", 
        "HANARO", "ACE", "SOL", "TIMEFOLIO", "WOORI", "히어로즈",
        "ETN", "ETF", "스팩", "인버스", "레버리지"
    ]
    blacklist = ["005930", "000660", "373220", "207940"] # 초대형주 제외
    
    candidates = []
    
    print("[4/4] 캔들 분석 및 윗꼬리 필터링 중 (최대 5종목 선발)...")
    for code in top_value_codes:
        if code in blacklist: continue
        
        if code in top_fluct_dict:
            rate = top_fluct_dict[code]
            name = names_dict.get(code, "")
            
            # 잡주 필터
            if any(kw in name for kw in exclude_keywords) or name.endswith("우") or name.endswith("우B"):
                continue
                
            # 등락률 5% 이상 (너무 낮으면 추세가 약함)
            if rate >= 5.0:
                candles = await asyncio.to_thread(client.get_daily_candles, code, 2)
                if not candles:
                    continue
                    
                today_candle = candles[0]
                open_p = today_candle["open"]
                close_p = today_candle["close"]
                high_p = today_candle["high"]
                
                # 양봉 조건 (종가 > 시가)
                if close_p > open_p:
                    if close_p > 0:
                        # 윗꼬리 비율 계산
                        upper_wick_ratio = (high_p - close_p) / close_p * 100
                        
                        # 윗꼬리가 3% 이하인 종목만 (상단 매물대 돌파 후 안착)
                        if upper_wick_ratio <= 3.0:
                            # _AL 등의 접미사 제거하여 순수 종목코드만 추출
                            pure_code = code.split('_')[0] if '_' in code else code
                            
                            candidates.append({
                                "code": pure_code,
                                "name": name,
                                "rate": rate,
                                "upper_wick": round(upper_wick_ratio, 2),
                                "close": close_p
                            })
                            
                            if len(candidates) >= 5:
                                break

    print("\n========================================")
    print("🎯 [내일 아침 시초가 스캘핑 관심종목]")
    print("========================================")
    
    watchlist_path = os.path.join(os.path.dirname(__file__), "watchlist.txt")
    
    if not candidates:
        print("조건을 만족하는 완벽한 주도주가 오늘은 없습니다.")
        if os.path.exists(watchlist_path):
            os.remove(watchlist_path)
    else:
        with open(watchlist_path, "w", encoding="utf-8") as f:
            for i, c in enumerate(candidates, 1):
                msg = f"{i}. {c['name']} ({c['code']}) - 등락률: +{c['rate']}%, 윗꼬리: {c['upper_wick']}%, 종가: {c['close']:,}원"
                print(msg)
                f.write(f"{c['code']}\n")
        print(f"\n✅ 위 {len(candidates)}개 종목이 '{watchlist_path}' 에 저장되었습니다.")

if __name__ == "__main__":
    asyncio.run(run_research())
