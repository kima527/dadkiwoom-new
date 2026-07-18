import requests
from bs4 import BeautifulSoup
import logging
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

class ThemeManager:
    """인포스탁 섹터/테마 정보 실시간 크롤링 및 분석 매니저"""
    def __init__(self):
        self.base_url = "https://finance.naver.com/sise/theme.naver"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        self.theme_cache = {}  # { "stock_code": ["테마명1", "테마명2"] }
        
    def _fetch_page(self, url):
        try:
            res = requests.get(url, headers=self.headers, timeout=5)
            res.raise_for_status()
            # 네이버 금융은 euc-kr 인코딩을 주로 사용함
            return BeautifulSoup(res.content.decode('euc-kr', 'replace'), 'html.parser')
        except Exception as e:
            logger.error(f"테마 페이지 가져오기 실패: {url}, {e}")
            return None
            
    def load_top_themes(self, limit=30):
        """당일 가장 핫한 테마 상위 N개를 불러와 종목별 매핑 캐시를 생성합니다."""
        logger.info(f"[테마담당자] 인포스탁 제공 테마 상위 {limit}개 크롤링 시작...")
        soup = self._fetch_page(self.base_url)
        if not soup:
            logger.error("[테마담당자] 테마 메인 페이지에 접근할 수 없습니다.")
            return
            
        themes = soup.select('.col_type1 > a')
        for i, t in enumerate(themes[:limit]):
            theme_name = t.text.strip()
            theme_url = urljoin(self.base_url, t['href'])
            
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
                    # 중복 테마 등록 방지
                    if theme_name not in self.theme_cache[code]:
                        self.theme_cache[code].append(theme_name)
                        
        logger.info(f"[테마담당자] 주도 테마 매핑 완료! (총 {len(self.theme_cache)}개 종목의 테마 정보 수집 완료)")

    def get_stock_themes(self, stock_code: str) -> list:
        """특정 종목의 주도 테마 리스트를 반환합니다."""
        return self.theme_cache.get(stock_code, [])

if __name__ == "__main__":
    tm = ThemeManager()
    tm.load_top_themes(limit=10) # 테스트용 10개
    print("모나미 (005360) 테마:", tm.get_stock_themes('005360'))
