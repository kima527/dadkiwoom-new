import requests
from bs4 import BeautifulSoup
import logging
from urllib.parse import urljoin

logger = logging.getLogger(__name__)

class ThemeManager:
    """
    네이버 증권 테마 실시간 API 및 차등 가중치 분석 매니저 (Step 1 고도화)
    - 테마 내 거래대금 및 등락률 기반 대장주(Leader) / 부대장주(Second) / 후발주(Follower) 자동 식별
    - 대장주 우선 가중치 부여 (최대 1.40x) 및 후발주 페널티(0.85x) 적용으로 뇌동매매 원천 차단
    """
    def __init__(self):
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        }
        self.api_theme_url = "https://m.stock.naver.com/api/stocks/theme"
        self.theme_cache = {}          # { "stock_code": ["테마명1", "테마명2"] }
        self.stock_weight_cache = {}   # { "stock_code": float } 종목별 최고 가중치 저장
        self.stock_role_cache = {}     # { "stock_code": "LEADER" | "SECOND" | "FOLLOWER" }
        self.stock_detail_cache = {}   # { "stock_code": dict } 테마 내 상세 스펙
        self.hot_theme_codes = set()   # O(1) 판별을 위한 6자리 종목코드 set
        self.top_themes_summary = []   # 당일 상위 테마 요약 리스트

    def load_top_themes(self, limit: int = 30):
        """
        당일 가장 핫한 테마 상위 N개를 고속 JSON API로 조회하고
        테마 내 거래대금 및 등락률을 기준으로 '대장주'와 '부대장주'를 자동 선별합니다.
        
        [가중치 부여 체계]
        - Top 1~3위 테마 (초강력 주도 테마):
            * 👑 대장주(1등): 1.40x
            * 🥈 부대장주(2등): 1.20x
            * 🥉 3등 이하 후발주: 0.85x (감점 페널티)
        - Top 4~10위 테마 (주력 테마):
            * 👑 대장주(1등): 1.30x
            * 🥈 부대장주(2등): 1.10x
            * 🥉 3등 이하 후발주: 0.85x
        - Top 11~30위 테마 (일반 테마):
            * 👑 대장주(1등): 1.20x
            * 🥈 부대장주(2등): 1.05x
            * 🥉 3등 이하 후발주: 0.85x
        - 기타/미포함 종목: 1.00x
        """
        logger.info(f"🔄 [테마매니저] 네이버 증권 상위 {limit}개 테마 및 대장주 선별 크롤링 시작...")

        self.theme_cache.clear()
        self.stock_weight_cache.clear()
        self.stock_role_cache.clear()
        self.stock_detail_cache.clear()
        self.hot_theme_codes.clear()
        self.top_themes_summary.clear()

        # 1. 고속 모바일 JSON API 시도
        success = self._load_via_json_api(limit)
        if not success:
            logger.warning("⚠️ 모바일 JSON API 응답 실패. PC 웹 크롤링 폴백 진행...")
            self._load_via_html_scraping(limit)

        logger.info(
            f"✅ [테마매니저] 테마 분석 완료! 총 {len(self.theme_cache)}개 종목 매핑 | "
            f"👑 대장주 등록: {sum(1 for r in self.stock_role_cache.values() if r == 'LEADER')}개, "
            f"🥈 부대장주: {sum(1 for r in self.stock_role_cache.values() if r == 'SECOND')}개"
        )

    def _load_via_json_api(self, limit: int) -> bool:
        try:
            url = f"{self.api_theme_url}?page=1&pageSize={limit}"
            res = requests.get(url, headers=self.headers, timeout=5)
            if res.status_code != 200:
                return False

            data = res.json()
            groups = data.get('groups', [])
            if not groups:
                return False

            for i, g in enumerate(groups[:limit]):
                theme_rank = i + 1
                theme_no = g.get('no')
                theme_name = g.get('name', '').strip()
                theme_chg = float(g.get('changeRate', 0.0))

                # 테마 내 소속 종목 조회
                sub_url = f"{self.api_theme_url}/{theme_no}?page=1&pageSize=50"
                sub_res = requests.get(sub_url, headers=self.headers, timeout=5)
                if sub_res.status_code != 200:
                    continue

                sub_data = sub_res.json()
                stocks = sub_data.get('stocks', [])
                if not stocks:
                    continue

                # 종목 정렬: 거래대금(accumulatedTradingValueRaw) 최우선, 등락률(fluctuationsRatio) 차우선
                def stock_sort_key(s):
                    try:
                        tv = float(s.get('accumulatedTradingValueRaw') or 0.0)
                    except Exception:
                        tv = 0.0
                    try:
                        fluc = float(s.get('fluctuationsRatio') or 0.0)
                    except Exception:
                        fluc = 0.0
                    return (tv, fluc)

                sorted_stocks = sorted(stocks, key=stock_sort_key, reverse=True)

                leader_code = None
                leader_name = None

                for s_idx, s in enumerate(sorted_stocks):
                    code = s.get('itemCode', '')
                    name = s.get('stockName', '')
                    if not code or len(code) != 6:
                        continue

                    try:
                        fluc_rate = float(s.get('fluctuationsRatio') or 0.0)
                    except Exception:
                        fluc_rate = 0.0

                    try:
                        trade_val = float(s.get('accumulatedTradingValueRaw') or 0.0)
                    except Exception:
                        trade_val = 0.0

                    # 역할(Role) 및 순위별 차등 가중치 계산
                    if s_idx == 0:
                        role = "LEADER"  # 👑 1등 대장주
                        leader_code = code
                        leader_name = name
                        if theme_rank <= 3:
                            weight = 1.40
                        elif theme_rank <= 10:
                            weight = 1.30
                        else:
                            weight = 1.20
                    elif s_idx == 1:
                        role = "SECOND"  # 🥈 2등 부대장주
                        if theme_rank <= 3:
                            weight = 1.20
                        elif theme_rank <= 10:
                            weight = 1.10
                        else:
                            weight = 1.05
                    else:
                        role = "FOLLOWER"  # 🥉 3등 이하 후발주 (추격 매수 방지 감점)
                        weight = 0.85

                    # 캐시 등록
                    if code not in self.theme_cache:
                        self.theme_cache[code] = []
                    if theme_name not in self.theme_cache[code]:
                        self.theme_cache[code].append(theme_name)

                    prev_w = self.stock_weight_cache.get(code, 1.0)
                    # 복수 테마 소속 시 더 높은 가중치 우선 적용
                    if weight > prev_w or code not in self.stock_weight_cache:
                        self.stock_weight_cache[code] = weight
                        self.stock_role_cache[code] = role
                        self.stock_detail_cache[code] = {
                            'theme': theme_name,
                            'theme_rank': theme_rank,
                            'role': role,
                            'fluctuation': fluc_rate,
                            'trading_value': trade_val,
                            'name': name
                        }

                    self.hot_theme_codes.add(code)

                # 테마 요약 기록
                self.top_themes_summary.append({
                    'rank': theme_rank,
                    'name': theme_name,
                    'change_rate': theme_chg,
                    'leader_code': leader_code,
                    'leader_name': leader_name,
                    'stock_count': len(sorted_stocks)
                })

            return True

        except Exception as e:
            logger.error(f"JSON 테마 수집 실패: {e}")
            return False

    def _load_via_html_scraping(self, limit: int):
        """PC 웹 크롤링 폴백 (API 실패 시)"""
        try:
            base_url = "https://finance.naver.com/sise/theme.naver"
            res = requests.get(base_url, headers=self.headers, timeout=5)
            soup = BeautifulSoup(res.content.decode('euc-kr', 'replace'), 'html.parser')
            themes = soup.select('.col_type1 > a')

            for i, t in enumerate(themes[:limit]):
                rank = i + 1
                theme_name = t.text.strip()
                sub_url = urljoin(base_url, t['href'])
                sub_soup = BeautifulSoup(requests.get(sub_url, headers=self.headers, timeout=5).content.decode('euc-kr', 'replace'), 'html.parser')
                
                stock_tags = sub_soup.select('div.name_area > a')
                for s_idx, st in enumerate(stock_tags):
                    href = st.get('href', '')
                    if 'code=' in href:
                        code = href.split('code=')[-1]
                        if s_idx == 0:
                            weight = 1.35 if rank <= 3 else (1.25 if rank <= 10 else 1.15)
                            role = "LEADER"
                        else:
                            weight = 0.90
                            role = "FOLLOWER"

                        self.theme_cache.setdefault(code, []).append(theme_name)
                        if weight > self.stock_weight_cache.get(code, 1.0):
                            self.stock_weight_cache[code] = weight
                            self.stock_role_cache[code] = role
                        self.hot_theme_codes.add(code)
        except Exception as e:
            logger.error(f"HTML 폴백 테마 수집 실패: {e}")

    def get_stock_weight(self, stock_code: str) -> float:
        """종목의 테마 및 대장주 여부에 따른 차등 가중치 반환 (기본 1.0)"""
        return self.stock_weight_cache.get(stock_code, 1.0)

    def get_stock_role(self, stock_code: str) -> str:
        """종목의 테마 내 역할 반환 ('LEADER', 'SECOND', 'FOLLOWER', 'NONE')"""
        return self.stock_role_cache.get(stock_code, "NONE")

    def is_theme_leader(self, stock_code: str) -> bool:
        """해당 종목이 테마 대장주(1등 또는 2등)인지 판별"""
        return self.stock_role_cache.get(stock_code) in ["LEADER", "SECOND"]

    def get_stock_themes(self, stock_code: str) -> list:
        """특정 종목의 주도 테마 리스트 반환"""
        return self.theme_cache.get(stock_code, [])

    def get_stock_details(self, stock_code: str) -> dict:
        """특정 종목의 테마 상세 스펙 반환"""
        return self.stock_detail_cache.get(stock_code, {})

    def has_hot_theme(self, stock_code: str) -> bool:
        """[HFT 최적화] 6자리 종목코드가 상위 테마에 속하는지 O(1) 속도로 즉각 판별"""
        return stock_code in self.hot_theme_codes

    def get_top_themes_summary(self) -> list:
        """상위 테마 목록 및 대장주 정보 반환"""
        return self.top_themes_summary


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    tm = ThemeManager()
    tm.load_top_themes(limit=10)
    print("\n[상위 3개 테마 요약]")
    for item in tm.get_top_themes_summary()[:3]:
        print(f"  #{item['rank']} {item['name']} (+{item['change_rate']}%) - 👑대장주: {item['leader_name']}({item['leader_code']})")
