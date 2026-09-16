import requests
from bs4 import BeautifulSoup
import logging
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

class ThemeManager:
    """네이버증권 인포스탁 테마 실시간 크롤링 및 차등 가중치 분석 매니저"""
    def __init__(self):
        self.base_url = "https://finance.naver.com/sise/theme.naver"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        self.theme_cache = {}        # { "stock_code": ["테마명1", "테마명2"] }
        self.stock_weight_cache = {} # { "stock_code": float } 종목별 최고 가중치 저장
        self.hot_theme_codes = set() # O(1) 판별을 위한 6자리 종목코드 set
        
    def _fetch_page(self, url):
        try:
            res = requests.get(url, headers=self.headers, timeout=5)
            res.raise_for_status()
            return BeautifulSoup(res.content.decode('euc-kr', 'replace'), 'html.parser')
        except Exception as e:
            logger.error(f"테마 페이지 가져오기 실패: {url}, {e}")
            return None
            
    def load_top_themes(self, limit=30):
        """
        당일 가장 핫한 테마 상위 N개를 불러와 종목별 차등 가중치 매핑 캐시를 생성합니다.
        - Top 1~3위 (오늘의 가장 센 캡틴 테마): 1.35x
        - Top 4~10위 (주도 테마): 1.25x
        - Top 11~30위 (일반 유효 테마): 1.15x
        - 기타/미포함: 1.00x
        """
        logger.info(f"[테마매니저] 네이버 증권 상위 {limit}개 테마 차등 크롤링 시작...")
        
        self.theme_cache.clear()
        self.stock_weight_cache.clear()
        self.hot_theme_codes.clear()
        
        soup = self._fetch_page(self.base_url)
        if not soup:
            logger.error("[테마매니저] 테마 메인 페이지에 접근할 수 없습니다.")
            return
            
        themes = soup.select('.col_type1 > a')
        for i, t in enumerate(themes[:limit]):
            rank = i + 1  # 1위 ~ limit위
            theme_name = t.text.strip()
            theme_url = urljoin(self.base_url, t['href'])
            
            # 순위별 차등 가중치 산정
            if rank <= 3:
                weight = 1.35  # 🥇 오늘의 가장 센 초강력 캡틴 테마 (Top 1~3)
            elif rank <= 10:
                weight = 1.25  # 🥈 주력 테마 (Top 4~10)
            else:
                weight = 1.15  # 🥉 일반 테마 (Top 11~30)
            
            # 테마 개별 페이지로 들어가서 소속 종목코드 가져오기
            theme_soup = self._fetch_page(theme_url)
            if not theme_soup:
                continue
                
            stock_tags = theme_soup.select('div.name_area > a')
            for st in stock_tags:
                href = st.get('href', '')
                if 'code=' in href:
                    code = href.split('code=')[-1]
                    if code not in self.theme_cache:
                        self.theme_cache[code] = []
                    if theme_name not in self.theme_cache[code]:
                        self.theme_cache[code].append(theme_name)
                    
                    # 종목이 복수 테마에 속한 경우 가장 높은 가중치 적용
                    prev_w = self.stock_weight_cache.get(code, 1.0)
                    if weight > prev_w:
                        self.stock_weight_cache[code] = weight
                        
                    self.hot_theme_codes.add(code)
                        
        logger.info(
            f"[테마매니저] 차등 테마 매핑 완료! (총 {len(self.theme_cache)}개 종목 | "
            f"Top 1~3위={1.35}x, Top 4~10위={1.25}x, Top 11~30위={1.15}x)"
        )

    def get_stock_weight(self, stock_code: str) -> float:
        """종목의 테마 순위에 따른 차등 가중치 반환 (기본 1.0)"""
        return self.stock_weight_cache.get(stock_code, 1.0)

    def get_stock_themes(self, stock_code: str) -> list:
        """특정 종목의 주도 테마 리스트를 반환합니다."""
        return self.theme_cache.get(stock_code, [])
        
    def has_hot_theme(self, stock_code: str) -> bool:
        """[HFT 최적화] 6자리 종목코드가 상위 테마에 속하는지 O(1) 속도로 즉각 판별합니다."""
        return stock_code in self.hot_theme_codes

if __name__ == "__main__":
    tm = ThemeManager()
    tm.load_top_themes(limit=10)
    print("샘플 테스트:", tm.get_stock_weight('005930'))
