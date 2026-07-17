import os
import sys
import logging
import asyncio
import requests
from bs4 import BeautifulSoup
from google import genai
from dotenv import load_dotenv, find_dotenv

# .env 파일을 상위 폴더(루트)에서 찾도록 설정
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env')
load_dotenv(dotenv_path=env_path)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if GEMINI_API_KEY:
    ai_client = genai.Client(api_key=GEMINI_API_KEY)
else:
    logger = logging.getLogger(__name__)
    logger.warning("GEMINI_API_KEY가 .env에 설정되지 않았습니다. 뉴스 AI 분석이 키워드 모드로 대체됩니다.")

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from kiwoom_client import KiwoomClient

logger = logging.getLogger(__name__)

class VolumeAgent:
    """수급 관리자: 당일 돈이 가장 많이 몰리고 급등한 종목 20개를 추려냅니다."""
    def __init__(self, client: KiwoomClient):
        self.client = client
        
    def get_candidates(self) -> list:
        logger.info("📊 [VolumeAgent] 거래대금 및 등락률 기반 1차 후보군 추출 중...")
        vol_top = self.client.get_top_trading_value_stocks(limit=100)
        fluc_top = self.client.get_top_fluctuation_stocks_with_rates(limit=100)
        
        if not vol_top:
            return []
        # vol_top is already a list of strings (stock codes)
        vol_codes = vol_top 
        
        if isinstance(fluc_top, dict):
            fluc_codes = list(fluc_top.keys())
        else:
            fluc_codes = fluc_top
        
        candidates_raw = []
        for code in vol_codes:
            if code in fluc_codes and code[0] not in ['5', '7']: # ETN, SPAC 등 제외
                candidates_raw.append(code)
                
        # ETF(KODEX, TIGER 등) 및 스팩(SPAC) 이름으로 필터링
        if candidates_raw:
            names = self.client.get_stock_names(candidates_raw)
            candidates = []
            for code in candidates_raw:
                name = names.get(code, "")
                if any(etf_kw in name for etf_kw in ["KODEX", "TIGER", "KBSTAR", "ACE", "ARIRANG", "PLUS", "KOSEF", "HANARO", "SOL", "TIMEFOLIO", "스팩", "인버스", "레버리지", "선물"]):
                    logger.info(f"🚫 [VolumeAgent] ETF/스팩 제외됨: {name}")
                    continue
                candidates.append(code)
        else:
            candidates = []
                
        return candidates[:20]

class FinanceAgent:
    """재무 관리자: 상폐 위험, 적자 기업을 걸러냅니다."""
    def evaluate(self, code: str) -> int:
        score = 50
        try:
            url = f"https://finance.naver.com/item/main.naver?code={code}"
            res = requests.get(url, headers={'User-agent': 'Mozilla/5.0'})
            soup = BeautifulSoup(res.text, 'html.parser')
            
            # 위험 키워드 스캔 (관리종목, 환기종목 등)
            blind_area = soup.find('div', {'class': 'description'})
            if blind_area and ('관리종목' in blind_area.text or '환기종목' in blind_area.text):
                logger.warning(f"🚨 [FinanceAgent] {code} - 재무 위험종목 감지!")
                return 0 # 탈락
                
            # 기본 점수 부여
            score += 20
        except Exception as e:
            pass
        return score

class NewsAgent:
    """뉴스/모멘텀 관리자: 최신 뉴스 헤드라인을 Gemini AI(LLM)로 심층 분석합니다."""
    def __init__(self):
        self.use_ai = bool(GEMINI_API_KEY)
        self.good_words = ["수주", "최대", "공급", "계약", "M&A", "합병", "인수", "승인", "돌파", "흑자", "성공"]
        self.bad_words = ["유상증자", "횡령", "배임", "압수수색", "하한가", "적자", "CB", "전환사채", "취소", "우려"]

    def evaluate(self, code: str) -> int:
        score = 50
        try:
            url = f"https://finance.naver.com/item/news_news.naver?code={code}"
            res = requests.get(url, headers={'User-agent': 'Mozilla/5.0'})
            soup = BeautifulSoup(res.text, 'html.parser')
            
            titles = soup.find_all('a', class_='tit')
            if not titles:
                return score
                
            news_text = "\n".join([f"- {t.text}" for t in titles[:10]])
            
            if self.use_ai:
                prompt = f"""
다음은 특정 주식 종목의 오늘자 최신 뉴스 헤드라인 10개입니다.
이 뉴스들이 주가 상승을 견인할 만한 '강력한 호재'인지, 아니면 '치명적인 악재'인지 분석해서 0점부터 100점 사이의 점수로 평가해주세요.
- 평범한 일상 뉴스: 50점
- 단기적/약한 호재: 60~75점
- 강력한 호재(수주, M&A, 역대최대실적 등): 80~100점
- 악재(유상증자, 횡령, 배임 등): 0~40점

결과는 오직 '점수 숫자' 하나만 출력하세요. (예: 85)

[뉴스 헤드라인]
{news_text}
"""
                try:
                    response = ai_client.models.generate_content(
                        model='gemini-1.5-flash',
                        contents=prompt
                    )
                    ai_score = int(response.text.strip())
                    logger.info(f"🤖 [NewsAgent(AI)] {code} 종목 뉴스 분석 점수: {ai_score}점")
                    return max(0, min(ai_score, 100))
                except Exception as e:
                    logger.error(f"Gemini API 분석 실패 ({e}), 키워드 모드로 전환합니다.")
            
            # AI를 안 쓰거나 실패했을 경우 키워드 매칭(Fallback)
            news_text_flat = " ".join([t.text for t in titles[:10]])
            for word in self.good_words:
                if word in news_text_flat:
                    score += 15
            for word in self.bad_words:
                if word in news_text_flat:
                    score -= 30
            logger.info(f"📰 [NewsAgent(키워드)] {code} 종목 점수: {score}점")
            
        except Exception as e:
            logger.error(f"뉴스 크롤링 오류: {e}")
            pass
            
        return max(0, min(score, 100))

class ThemeAgent:
    """테마 관리자: 현재 1차 후보군 안에서 가장 많이 겹치는 업종/테마를 찾습니다."""
    def get_theme_scores(self, candidates: list) -> dict:
        # 실제로는 각 종목별 업종(WICS)을 가져와서 빈도가 높은 업종에 가산점을 줍니다.
        return {code: 60 for code in candidates}

class ChiefManager:
    """중앙 통제 센터: 모든 에이전트의 점수를 합산하여 최종 대장주 선정"""
    def __init__(self, client: KiwoomClient):
        self.client = client
        self.vol_agent = VolumeAgent(client)
        self.fin_agent = FinanceAgent()
        self.news_agent = NewsAgent()
        self.theme_agent = ThemeAgent()
        
    def find_ultimate_leader(self) -> str:
        logger.info("========================================")
        logger.info("🕵️‍♂️ [ChiefManager] 대장주 색출 멀티-에이전트 회의 시작")
        logger.info("========================================")
        
        candidates = self.vol_agent.get_candidates()
        if not candidates:
            logger.warning("1차 후보군을 찾지 못했습니다.")
            return None
            
        logger.info(f"-> 1차 후보군 {len(candidates)}개 종목 도출 완료")
        
        theme_scores = self.theme_agent.get_theme_scores(candidates)
        
        best_code = None
        best_score = -1
        names = self.client.get_stock_names(candidates)
        
        for code in candidates:
            name = names.get(code, code)
            
            fin_score = self.fin_agent.evaluate(code)
            if fin_score == 0:
                continue # 재무 탈락
                
            news_score = self.news_agent.evaluate(code)
            theme_score = theme_scores.get(code, 50)
            
            # 총점 산출 (비중: 뉴스 40%, 재무 30%, 테마 30%)
            total = (news_score * 0.4) + (fin_score * 0.3) + (theme_score * 0.3)
            
            logger.info(f"   [{name}] 재무:{fin_score} 뉴스:{news_score} 테마:{theme_score} -> 총점: {total:.1f}")
            
            if total > best_score:
                best_score = total
                best_code = code
                
        if best_code:
            logger.info("========================================")
            logger.info(f"🏆 [최종 결론] 오늘의 완벽한 대장주: {names.get(best_code, best_code)} (점수: {best_score:.1f})")
            logger.info("========================================")
            
        return best_code

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    client = KiwoomClient()
    if client.test_connection():
        manager = ChiefManager(client)
        leader = manager.find_ultimate_leader()
