import asyncio
import os
import sys
import requests
from bs4 import BeautifulSoup
from datetime import datetime

# 기존 키움 API 연동을 위해 경로 추가
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from kiwoom_client import KiwoomClient
from theme_manager import ThemeManager
from tech_manager import TechIndicatorManager
from telegram_bot import send_message_sync
import webbrowser

def get_tick_size(price):
    if price < 2000: return 1
    elif price < 5000: return 5
    elif price < 20000: return 10
    elif price < 50000: return 50
    elif price < 200000: return 100
    elif price < 500000: return 500
    else: return 1000

def calc_safety_zone(high_price):
    """세이프티존 (고가 대비 -6%) 계산"""
    safety_price = high_price * 0.94
    tick = get_tick_size(safety_price)
    return int((safety_price // tick) * tick)

import xml.etree.ElementTree as ET

def get_recent_news(keyword):
    """구글 뉴스 RSS를 통해 최근 뉴스 3개 추출 (네이버 크롤링 차단 방지)"""
    url = f"https://news.google.com/rss/search?q={keyword}&hl=ko&gl=KR&ceid=KR:ko"
    try:
        res = requests.get(url)
        res.raise_for_status()
        root = ET.fromstring(res.text)
        
        results = []
        for item in root.findall('.//item')[:3]:
            title = item.find('title').text
            link = item.find('link').text
            results.append({"title": title, "link": link})
        return results
    except Exception as e:
        print(f"뉴스 검색 중 오류 발생: {e}")
        return []

def generate_blog_post(candidates):
    """텔레그램/인스타그램(SNS)용 텍스트 리포트 양식 생성"""
    date_str = datetime.now().strftime("%Y년 %m월 %d일")
    
    content = f"📈 [{date_str}] 주도주 리서치 및 투매 지지선 분석\n\n"
    
    content += "💡 Daily Market View\n"
    content += "금일 거래대금이 집중되며 견고한 일봉(윗꼬리 3% 이내)을 형성한 주도주를 선별했습니다. 익일 눌림목(세이프티존)에서 기술적 반등을 노릴 수 있는 핵심 관종입니다.\n\n"
    content += "━━━━━━━━━━━━━━━━━━━━━\n\n"
    
    number_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
    
    for i, c in enumerate(candidates):
        name = c['name']
        rate = c['rate']
        close_p = c['close']
        upper_wick = c['upper_wick']
        safety = calc_safety_zone(c['high'])
        news_items = get_recent_news(name)
        
        num_emoji = number_emojis[i] if i < len(number_emojis) else f"{i+1}."
        
        theme_info = c.get('theme', '개별주 모멘텀')
        tech_info = c.get('tech_summary', '기본 지표 양호')
        
        content += f"{num_emoji} {name} (+{rate}%) [테마: {theme_info}]\n"
        content += f"🔹 종가: {close_p:,}원\n"
        content += f"🔹 캔들: 윗꼬리 {upper_wick}% 마감\n"
        content += f"🔹 기술적 분석: {tech_info}\n"
        content += f"🎯 세이프티존(매수타점): {safety:,}원 부근\n\n"
        
        content += "🔥 주요 모멘텀\n"
        if news_items:
            for news in news_items[:3]: # 인스타/텔레그램은 너무 길면 안되므로 3개까지만
                content += f" - {news['title']}\n"
        else:
            content += " - 최근 부각된 주요 모멘텀 뉴스 없음\n"
            
        content += "\n━━━━━━━━━━━━━━━━━━━━━\n\n"
        
    content += "📌 트레이딩 시나리오\n"
    content += "위 종목들은 대량의 거래대금과 함께 강력한 시세를 분출했습니다. 익일 장 초반 차익 매물 출회 시, 안내드린 '세이프티존' 구간에서 분할 매수로 접근하여 기술적 리바운딩(단기 스윙)을 노리는 전략이 유효합니다.\n\n"
    
    content += "⚠️ Disclaimer\n"
    content += "본 리포트의 세이프티존은 통계적 확률에 기반한 지지선입니다. 투자의 최종 판단과 책임은 본인에게 있으며 리스크 관리에 유의하시기 바랍니다."
    
    return content

async def run_blog_generator():
    print("🚀 블로그 포스트 생성 봇 시작...")
    client = KiwoomClient()
    
    print("0. 테마 및 기술적 지표 매니저 초기화 중...")
    theme_mgr = ThemeManager()
    tech_mgr = TechIndicatorManager()
    await asyncio.to_thread(theme_mgr.load_top_themes, 30) # 테마 상위 30개 스캔
    
    print("1. 거래대금 상위 100위 조회 중...")
    top_value_codes = await asyncio.to_thread(client.get_top_trading_value_stocks, "000", 100)
    
    print("2. 등락률 상위 100위 조회 중...")
    top_fluct_dict = await asyncio.to_thread(client.get_top_fluctuation_stocks_with_rates, "000", 100)
    
    if not top_value_codes or not top_fluct_dict:
        print("API 데이터를 가져오지 못했습니다.")
        return
        
    print("3. 종목 이름 일괄 조회 중...")
    names_dict = await asyncio.to_thread(client.get_stock_names, top_value_codes)
        
    exclude_keywords = [
        "KODEX", "TIGER", "KBSTAR", "KINDEX", "ARIRANG", "KOSEF", "HANARO", 
        "ACE", "ETN", "스팩", "SOL", "인버스", "레버리지", "선물", "KOACT", 
        "TIMEFOLIO", "WOORI", "히어로즈", "PLUS", "WON"
    ]
    blacklist = ["005930", "000660", "373220", "207940"]
    
    candidates = []
    
    print("4. 필터링 및 일봉 캔들 분석 중...")
    for code in top_value_codes:
        if code in blacklist: continue
        
        if code in top_fluct_dict:
            rate = top_fluct_dict[code]
            name = names_dict.get(code, "")
            
            # ETF, ETN, 우선주 등 제외
            if any(kw in name for kw in exclude_keywords) or name.endswith("우") or name.endswith("우B"):
                continue
                
            if rate >= 5.0: # 등락률 조건
                # 기술적 지표 분석을 위해 40일치 캔들 가져오기
                candles = await asyncio.to_thread(client.get_daily_candles, code, 40)
                if not candles:
                    continue
                    
                today_candle = candles[0]
                open_p = today_candle["open"]
                close_p = today_candle["close"]
                high_p = today_candle["high"]
                
                if close_p > open_p and close_p > 0:
                    upper_wick_ratio = (high_p - close_p) / close_p * 100
                    
                    if upper_wick_ratio <= 3.0: # 윗꼬리 조건
                        # 매니저 분석
                        pure_code = code.split('_')[0] if '_' in code else code
                        themes = theme_mgr.get_stock_themes(pure_code)
                        theme_str = ", ".join(themes) if themes else "개별 이슈"
                        
                        # 지표 매니저용: 과거->최신순 정렬
                        asc_candles = list(reversed(candles))
                        tech_summary = tech_mgr.analyze_daily_technicals(asc_candles)
                        
                        candidates.append({
                            "code": code,
                            "name": name,
                            "rate": rate,
                            "high": high_p,
                            "close": close_p,
                            "upper_wick": round(upper_wick_ratio, 2),
                            "theme": theme_str,
                            "tech_summary": tech_summary
                        })
                        
                        if len(candidates) >= 5: # 상위 5종목까지만 추출
                            break

    print("5. 블로그 포스트 생성 중...")
    if not candidates:
        print("조건을 만족하는 종목이 없어 블로그 포스트를 생성할 수 없습니다.")
        return

    blog_text = generate_blog_post(candidates)
    
    # HTML 파일로 저장하여 인터넷 브라우저가 무조건 실행되도록 강제함
    date_str = datetime.now().strftime("%Y%m%d")
    filename = f"blog_post_{date_str}.html"
    filepath = os.path.abspath(filename)
    
    html_content = f"<html><head><meta charset='utf-8'></head><body><pre style='font-size: 15px; font-family: sans-serif; line-height: 1.6;'>{blog_text}</pre></body></html>"
    
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(html_content)
        
    print(f"\n✅ 블로그 포스트가 '{filename}'에 저장되었습니다!")
    print("\n[미리보기]\n" + "="*50)
    print(blog_text)
    print("="*50)
    
    # 텔레그램으로 전송
    print("📲 텔레그램으로 리포트 전송 중...")
    send_message_sync(blog_text)
    
    # 브라우저 팝업 (가장 원초적인 윈도우 쉘 실행 방식)
    try:
        os.system(f'start "" "{filepath}"')
    except Exception as e:
        print(f"브라우저 팝업 실패: {e}")

if __name__ == "__main__":
    asyncio.run(run_blog_generator())
