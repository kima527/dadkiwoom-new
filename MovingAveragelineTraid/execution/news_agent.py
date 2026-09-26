import os
import time
import requests
import logging
from dotenv import load_dotenv

# 상위 디렉터리 .env 로드
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env')
load_dotenv(dotenv_path=env_path)

logger = logging.getLogger(__name__)

class RealtimeNewsAgent:
    """
    실시간 뉴스 및 모멘텀 AI 스코어링 모듈 (Step 2 고도화)
    - 네이버 모바일 증권 초고속 뉴스 API 실시간 파싱
    - Gemini 3.8 Flash 초저지연 LLM 재료 가치 평가
    - LLM 할당량/크레딧 부족 시 금융 특화 정밀 자연어(NLP) 키워드 엔진 자동 폴백
    - 긴급 악재(CB발행, 횡령, 유상증자 등) 포착 시 선제적 매수 즉각 차단(Emergency Block)
    """

    def __init__(self, api_key: str = None, cache_ttl_sec: int = 600):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        self.api_url = "https://m.stock.naver.com/api/news/stock"
        self.cache_ttl_sec = cache_ttl_sec
        self.news_cache = {}  # { code: { 'score': int, 'bonus': float, 'catalyst': str, 'headline': str, 'block': bool, 'time': float } }

        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.ai_client = None

        if self.api_key:
            try:
                from google import genai
                self.ai_client = genai.Client(api_key=self.api_key)
                logger.info("🤖 [NewsAgent] Gemini Flash AI 클라이언트 초기화 완료.")
            except Exception as e:
                logger.warning(f"⚠️ [NewsAgent] Gemini 클라이언트 초기화 실패 ({e}). 키워드 모드로 자동 동작합니다.")

        # ── 금융 NLP 모멘텀 키워드 사전 정의 ──
        self.catalysts_super_positive = [
            "단독 공급", "공급 계약", "대규모 수주", "역대 최대 실적", "흑자 전환",
            "FDA 승인", "경영권 분쟁", "무상증자", "인수합병", "M&A", "특허 취득",
            "독점 공급", "지분 취득", "사상 최대", "글로벌 빅테크"
        ]
        self.catalysts_positive = [
            "급등", "강세", "호실적", "신제품", "제휴", "협력", "수혜주",
            "목표가 상향", "특징주", "양산", "진출", "상한가", "돌파"
        ]
        self.catalysts_super_negative = [
            "유상증자", "전환사채", "CB 발행", "신주인수권부사채", "BW 발행",
            "횡령", "배임", "압수수색", "하한가", "거래정지", "상장폐지",
            "감자 결정", "적자 지속", "관리종목", "불성실공시", "소송 제기", "계약 해지"
        ]
        self.catalysts_negative = [
            "약세", "하락", "차익실현", "우려", "부진", "실적 악화", "매도", "축소"
        ]

    def fetch_news_score(self, code: str, stock_name: str = "") -> dict:
        """
        특정 종목의 최신 뉴스를 수집하고 모멘텀 점수를 산출합니다.
        반환값:
        {
            'score': int (0~100),
            'bonus': float (-25.0 ~ +25.0 점수 보너스),
            'catalyst': str (핵심 재료 요약),
            'headline': str (최신 헤드라인),
            'is_emergency_block': bool (악재로 인한 즉각 매수 금지 여부),
            'mode': 'AI' | 'NLP_KEYWORD' | 'NEUTRAL'
        }
        """
        now = time.time()
        # 캐시 확인 (10분 TTL)
        cached = self.news_cache.get(code)
        if cached and (now - cached['time'] < self.cache_ttl_sec):
            return cached['result']

        try:
            url = f"{self.api_url}/{code}?pageSize=5"
            res = requests.get(url, headers=self.headers, timeout=4)
            if res.status_code != 200:
                result = self._get_neutral_result("API 호출 실패 (중립)")
                self.news_cache[code] = {'time': now, 'result': result}
                return result

            data = res.json()
            items = []
            if isinstance(data, list) and len(data) > 0 and 'items' in data[0]:
                items = data[0]['items']
            elif isinstance(data, dict):
                items = data.get('items', [])

            if not items:
                result = self._get_neutral_result("최근 뉴스 없음 (중립)")
                self.news_cache[code] = {'time': now, 'result': result}
                return result

            headlines = []
            snippets = []
            for it in items[:4]:
                t = it.get('title', '').strip()
                b = it.get('body', '').strip()
                if t:
                    headlines.append(t)
                if b:
                    snippets.append(b[:80])

            joined_news = " | ".join(headlines)
            first_headline = headlines[0] if headlines else ""

            # 1. Gemini AI 평가 시도
            ai_eval = None
            if self.ai_client:
                ai_eval = self._evaluate_with_gemini(code, stock_name, headlines)

            # 2. AI 실패 또는 비활성화 시 NLP 키워드 평가
            if ai_eval:
                result = ai_eval
            else:
                result = self._evaluate_with_nlp(joined_news, first_headline)

            self.news_cache[code] = {'time': now, 'result': result}
            return result

        except Exception as e:
            logger.debug(f"뉴스 수집 중 예외 ({code}): {e}")
            result = self._get_neutral_result("뉴스 처리 예외 (중립)")
            self.news_cache[code] = {'time': now, 'result': result}
            return result

    def _evaluate_with_gemini(self, code: str, stock_name: str, headlines: list) -> dict:
        """Gemini 3.8 Flash를 활용한 뉴스 임팩트 분석"""
        try:
            titles_text = "\n".join([f"- {h}" for h in headlines[:3]])
            prompt = f"""당신은 한국 주식시장 전문 데이트레이더입니다.
종목: {stock_name} ({code})
최신 뉴스 헤드라인:
{titles_text}

이 뉴스들이 당일 주가 상승을 견인할 '강력한 호재'인지, 아니면 '치명적인 악재'인지 평가하세요.
- 85~100점: 초대형 호재(대규모 수주, FDA 승인, 사상 최대 실적, M&A 등)
- 65~80점: 일반 호재(특징주 급등, 신제품 출시, MOU 등)
- 45~64점: 평이한 일반 시황/중립 뉴스
- 0~40점: 치명적 악재(유상증자, CB/전환사채 발행, 횡령, 배임, 압수수색 등)

반드시 아래 형식으로만 한 줄로 출력하세요:
점수|핵심이유(15자 이내)
예시: 88|대규모 수주 계약 체결
"""
            response = self.ai_client.models.generate_content(
                model='gemini-3.8-flash',
                contents=prompt
            )
            text = response.text.strip().replace('\n', ' ')
            parts = text.split('|')
            score_str = parts[0].strip()
            score = int(''.join(filter(str.isdigit, score_str))) if any(c.isdigit() for c in score_str) else 50
            score = max(0, min(100, score))
            catalyst = parts[1].strip() if len(parts) > 1 else "AI 분석 완료"

            bonus = (score - 50) * 0.5  # 80점 -> +15점, 30점 -> -10점
            is_emergency = (score <= 35)

            return {
                'score': score,
                'bonus': round(bonus, 1),
                'catalyst': f"🤖[AI] {catalyst}",
                'headline': headlines[0] if headlines else "",
                'is_emergency_block': is_emergency,
                'mode': 'AI'
            }
        except Exception as e:
            logger.debug(f"Gemini AI 뉴스 분석 실패 ({e}), NLP 키워드 모드로 전환합니다.")
            return None

    def _evaluate_with_nlp(self, joined_text: str, first_headline: str) -> dict:
        """금융 특화 고속 자연어(NLP) 키워드 스코어러"""
        score = 50
        matched_catalysts = []
        is_emergency = False

        # 치명적 악재 검출 (최우선 판정)
        for bad in self.catalysts_super_negative:
            if bad in joined_text:
                # 제3자배정 유상증자는 보통 호재/중립이므로 예외 처리
                if bad == "유상증자" and "제3자배정" in joined_text:
                    continue
                score -= 30
                matched_catalysts.append(f"🚨{bad}")
                is_emergency = True

        if not is_emergency:
            # 일반 악재
            for bad in self.catalysts_negative:
                if bad in joined_text:
                    score -= 10
                    matched_catalysts.append(f"⚠️{bad}")

            # 초강력 호재
            for good in self.catalysts_super_positive:
                if good in joined_text:
                    score += 25
                    matched_catalysts.append(f"🔥{good}")

            # 일반 호재
            for good in self.catalysts_positive:
                if good in joined_text:
                    score += 10
                    matched_catalysts.append(f"✨{good}")

        score = max(0, min(100, score))
        bonus = (score - 50) * 0.5

        if matched_catalysts:
            catalyst_summary = " ".join(matched_catalysts[:2])
        else:
            catalyst_summary = "일반 시황/중립"

        return {
            'score': score,
            'bonus': round(bonus, 1),
            'catalyst': f"📰[NLP] {catalyst_summary}",
            'headline': first_headline,
            'is_emergency_block': is_emergency or (score <= 35),
            'mode': 'NLP_KEYWORD'
        }

    def _get_neutral_result(self, reason: str) -> dict:
        return {
            'score': 50,
            'bonus': 0.0,
            'catalyst': f"⚪ {reason}",
            'headline': "",
            'is_emergency_block': False,
            'mode': 'NEUTRAL'
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    agent = RealtimeNewsAgent()
    print("\n--- [뉴스 스코어링 테스트] ---")
    res1 = agent.fetch_news_score("005930", "삼성전자")
    print(f"삼성전자: {res1['score']}점 (보너스: {res1['bonus']}점) | {res1['catalyst']} | 모드: {res1['mode']}")
    print(f"  헤드라인: {res1['headline']}")
