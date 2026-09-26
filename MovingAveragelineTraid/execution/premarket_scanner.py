import os
import sys
import json
import time
import logging
import requests
from datetime import datetime
from dotenv import load_dotenv

# 환경변수 로드
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), '.env')
load_dotenv(dotenv_path=env_path)

# 동일 디렉터리 모듈 import
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from theme_manager import ThemeManager
from news_agent import RealtimeNewsAgent

logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")


def send_telegram_alert(text: str):
    """텔레그램 장전 테마 브리핑 알림 전송"""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML"
        }
        res = requests.post(url, json=payload, timeout=5)
        if res.status_code == 200:
            logger.info("📱 텔레그램 장전 테마 알림 전송 성공")
        else:
            logger.warning(f"텔레그램 전송 실패: {res.status_code}, {res.text}")
    except Exception as e:
        logger.error(f"텔레그램 전송 예외: {e}")


class PremarketThemeScanner:
    """
    장전 테마 및 주도주 자동 발굴 엔진 (Step 3 고도화)
    - 매일 장전(08:30~08:50) 전일 시간외 및 당일 핫 테마 상위 분석
    - 테마 내 거래대금 1위 대장주 및 뉴스 모멘텀 결합
    - 악재 필터링 후 봇 워치리스트(watchlist.json / today_picks.json) 자동 동기화
    """

    def __init__(self):
        self.tm = ThemeManager()
        self.news_agent = RealtimeNewsAgent()

    def run_premarket_scan(self, top_theme_count: int = 5, send_telegram: bool = True) -> dict:
        """
        장전 스캔 실행: 상위 테마 분석 -> 대장주 선별 -> 뉴스 모멘텀 검증 -> 워치리스트 동기화
        """
        today_str = datetime.now().strftime("%Y-%m-%d")
        now_str = datetime.now().strftime("%H:%M:%S")

        logger.info("=" * 65)
        logger.info(f" 🌅 [장전 테마 브리핑 & 주도주 발굴 엔진] 가동 ({today_str} {now_str})")
        logger.info("=" * 65)

        # 1. 상위 20개 테마 및 소속 종목 수집
        self.tm.load_top_themes(limit=20)
        theme_summaries = self.tm.get_top_themes_summary()

        if not theme_summaries:
            logger.warning("상위 테마 목록을 가져오지 못했습니다.")
            return {}

        selected_themes = []
        captain_stocks = {}

        # 2. 상위 테마 중 상승세인 주도 테마 최대 top_theme_count개 선정
        for t_info in theme_summaries[:top_theme_count]:
            theme_name = t_info['name']
            theme_rank = t_info['rank']
            chg_rate = t_info['change_rate']

            # 소속 종목 중 대장주(LEADER) 및 부대장주(SECOND) 검색
            leaders = []
            for code, details in self.tm.stock_detail_cache.items():
                if details.get('theme') == theme_name and details.get('role') in ['LEADER', 'SECOND']:
                    stock_name = details.get('name', code)
                    role = details.get('role')
                    weight = self.tm.get_stock_weight(code)

                    # 3. 실시간 뉴스 스코어링 & 악재(CB/유증/횡령) 긴급 차단 검사
                    news_eval = self.news_agent.fetch_news_score(code, stock_name)
                    if news_eval.get('is_emergency_block'):
                        logger.warning(f"🚫 [{stock_name}({code})] 치명적 악재 뉴스 감지되어 장전 후보에서 제외: {news_eval['catalyst']}")
                        continue

                    leader_data = {
                        'code': code,
                        'name': stock_name,
                        'theme': theme_name,
                        'theme_rank': theme_rank,
                        'role': role,
                        'weight': weight,
                        'news_score': news_eval['score'],
                        'news_bonus': news_eval['bonus'],
                        'catalyst': news_eval['catalyst'],
                        'headline': news_eval['headline']
                    }
                    leaders.append(leader_data)
                    captain_stocks[code] = leader_data

            if leaders:
                selected_themes.append({
                    'rank': theme_rank,
                    'theme_name': theme_name,
                    'change_rate': chg_rate,
                    'leaders': leaders
                })

        logger.info(f"✨ 엄선된 주도 테마: {len(selected_themes)}개 | 총 캡틴 종목: {len(captain_stocks)}개")

        # 4. 워치리스트 (today_picks.json 및 watchlist.json) 업데이트
        self._save_to_watchlists(captain_stocks)

        # 5. .tmp 디렉터리에 장전 리포트 아티팩트 저장
        self._save_report(today_str, selected_themes, captain_stocks)

        # 6. 텔레그램 브리핑 메시지 발송
        if send_telegram and selected_themes:
            msg = self._build_telegram_message(today_str, selected_themes)
            send_telegram_alert(msg)

        return {
            'themes': selected_themes,
            'stocks': captain_stocks
        }

    def _save_to_watchlists(self, captain_stocks: dict):
        """today_picks.json 및 watchlist.json에 대장주 탑재"""
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        
        # 1. watchlist.json 갱신 (기존 종목 유지하면서 가중치/테마 정보 주입)
        watch_path = os.path.join(base_dir, "watchlist.json")
        existing_watchlist = {}
        if os.path.exists(watch_path):
            try:
                with open(watch_path, 'r', encoding='utf-8') as f:
                    existing_watchlist = json.load(f)
            except Exception:
                pass

        # 캡틴 종목 주입
        for code, info in captain_stocks.items():
            existing_watchlist[code] = {
                'name': info['name'],
                'weight': info['weight'],
                'theme': info['theme'],
                'role': info['role'],
                'catalyst': info['catalyst'],
                'source': "premarket_scanner"
            }

        try:
            with open(watch_path, 'w', encoding='utf-8') as f:
                json.dump(existing_watchlist, f, ensure_ascii=False, indent=4)
            logger.info(f"💾 [watchlist.json] {len(captain_stocks)}개 주도주 가중치 동기화 완료 (총 {len(existing_watchlist)}개)")
        except Exception as e:
            logger.error(f"watchlist.json 저장 실패: {e}")

        # 2. today_picks.json 생성
        today_picks_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "today_picks.json")
        today_picks = {}
        for code, info in captain_stocks.items():
            today_picks[code] = {
                'name': info['name'],
                'weight': info['weight'],
                'theme': info['theme'],
                'role': info['role'],
                'catalyst': info['catalyst']
            }
        try:
            with open(today_picks_path, 'w', encoding='utf-8') as f:
                json.dump(today_picks, f, ensure_ascii=False, indent=4)
            logger.info(f"💾 [today_picks.json] 당일 캡틴 주도주 {len(today_picks)}개 저장 완료")
        except Exception as e:
            logger.error(f"today_picks.json 저장 실패: {e}")

    def _save_report(self, date_str: str, selected_themes: list, captain_stocks: dict):
        """임시 디렉터리에 장전 분석 리포트 저장"""
        root_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        tmp_dir = os.path.join(root_dir, ".tmp")
        os.makedirs(tmp_dir, exist_ok=True)
        report_path = os.path.join(tmp_dir, f"premarket_theme_report_{date_str.replace('-', '')}.json")
        try:
            with open(report_path, 'w', encoding='utf-8') as f:
                json.dump({
                    'date': date_str,
                    'generated_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    'themes': selected_themes,
                    'captain_stocks': captain_stocks
                }, f, ensure_ascii=False, indent=2)
            logger.info(f"📄 [리포트 생성] {report_path}")
        except Exception as e:
            logger.debug(f"리포트 파일 저장 오류: {e}")

    def _build_telegram_message(self, date_str: str, selected_themes: list) -> str:
        """텔레그램 메시지 포맷팅"""
        lines = [
            f"<b>🌅 [전문가 원탁회의] 오늘의 주도 테마 & 캡틴주 브리핑</b>",
            f"📅 일자: {date_str} (장전 자동 스캔 완료)\n"
        ]

        for t in selected_themes[:3]:
            lines.append(f"<b>🔥 [{t['rank']}위] {t['theme_name']} (+{t['change_rate']}%)</b>")
            for leader in t['leaders']:
                role_icon = "👑 대장주" if leader['role'] == "LEADER" else "🥈 부대장주"
                lines.append(
                    f"  • {role_icon}: <b>{leader['name']}</b> ({leader['code']}) | 가중치: <b>{leader['weight']}x</b>\n"
                    f"    뉴스: {leader['catalyst']} (점수: {leader['news_score']}점)"
                )
            lines.append("")

        lines.append("🤖 <i>해당 캡틴 종목들은 trading_bot에 가중치 1.20~1.40x로 자동 탑재되었습니다.</i>")
        return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    scanner = PremarketThemeScanner()
    scanner.run_premarket_scan(top_theme_count=3, send_telegram=False)
