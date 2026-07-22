import os
import sys
import json
import logging

# 로거 설정
logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

# 실전 트레이딩 경로 추가
base_path = r"c:\Users\zoela\OneDrive\바탕 화면\PythonWorksplace"
real_path = os.path.join(base_path, "real trading")
sys.path.insert(0, real_path)

from kiwoom_client import KiwoomRealClient
from trend_manager import TrendManager

def main():
    logger.info("📡 키움증권 실전 API 연결 시도 중...")
    client = KiwoomRealClient()
    if not client.test_connection():
        logger.error("연결 실패")
        return
        
    logger.info("✅ 연결 성공. 전종목 스캔을 준비합니다.")
    
    codes_to_learn = set()
    
    # 당일 거래대금 상위 200종목을 스캔 (유동성이 풍부한 주도주 위주)
    logger.info("🔥 당일 거래대금 상위 200종목을 불러옵니다. (ETF/ETN 제외 필터링 중...)")
    top_stocks = client.get_top_trading_value_stocks(market_type="000", limit=200)
    
    etf_keywords = ["KODEX", "TIGER", "SOL", "KBSTAR", "ACE", "ARIRANG", "HANARO", "KOSEF", "TIMEFOLIO", "ETN", "인버스", "레버리지", "스팩"]
    
    for code in top_stocks:
        name = client.get_stock_name(code)
        if name:
            # ETF/ETN/스팩주 제외
            if any(keyword in name.upper() for keyword in etf_keywords):
                continue
        codes_to_learn.add(code)
        
    codes = list(codes_to_learn)
    logger.info(f"필터링 완료. 총 {len(codes)}개 순수 주식 종목에 대해 '추세 판단 에이전트'가 심층 스캔을 시작합니다...\n")
    
    # 추세 판단 에이전트(TrendManager)에게 전면 스캔 지시
    trend_agent = TrendManager(client)
    trend_agent.pre_learn(codes)
    
    # 결과 수합 및 정렬
    valid_stocks = []
    
    for code in codes:
        is_up, reason = trend_agent.check_trend(code)
        score = trend_agent.get_trend_score(code)
        name = client.get_stock_name(code) or code
        
        # 40점 이상(우상향 또는 강력한 수급 동반) 종목만 픽업
        if score >= 40:
            valid_stocks.append({
                "code": code,
                "name": name,
                "score": score,
                "reason": reason
            })
            
    # 점수 높은 순으로 내림차순 정렬
    valid_stocks.sort(key=lambda x: x["score"], reverse=True)
    
    logger.info("\n=======================================================")
    logger.info(f"🏆 추세가 살아있는(우상향/수급폭발) 종목 TOP {len(valid_stocks)} 발굴 완료!")
    logger.info("=======================================================")
    
    for i, st in enumerate(valid_stocks, 1):
        logger.info(f"{i}위. {st['name']} | 스코어: {st['score']:.1f}점 | {st['reason']}")
        
    # JSON 파일로 저장하여 다른 봇이 읽어갈 수 있도록 처리
    learned_path = os.path.join(real_path, "living_trend_stocks.json")
    with open(learned_path, 'w', encoding='utf-8') as f:
        json.dump(valid_stocks, f, ensure_ascii=False, indent=4)
        
    logger.info(f"\n🚀 추세 발굴 결과가 {learned_path} 에 저장되었습니다.")
    
if __name__ == "__main__":
    main()
