import os
import sys
import json
import logging
from datetime import datetime, timedelta
import pandas as pd
import numpy as np

# 경로 설정
current_dir = os.path.dirname(os.path.abspath(__file__))
execution_dir = os.path.join(current_dir, "MovingAveragelineTraid", "execution")
real_trading_dir = os.path.join(current_dir, "real trading")

if execution_dir not in sys.path:
    sys.path.insert(0, execution_dir)
if real_trading_dir not in sys.path:
    sys.path.insert(0, real_trading_dir)

from strategy_buy import analyze_buy_signals, calculate_hh, wma
from strategy_sell import analyze_sell_signals

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("WeekendScanner")

try:
    import yfinance as yf
except ImportError:
    yf = None

try:
    from kiwoom_client import KiwoomRealClient
except ImportError:
    KiwoomRealClient = None

def get_market_universe():
    """스캔할 대상 종목군 구성 (거래대금 상위주 + 조건검색 기존 후보군 + 테마 주도주)"""
    universe = {}

    # ETF/ETN/스팩/선물/우선주 제외 키워드
    exclude_keywords = [
        "KODEX", "TIGER", "KBSTAR", "KINDEX", "ARIRANG", "KOSEF", "HANARO", 
        "ACE", "ETN", "스팩", "SOL", "인버스", "레버리지", "선물", "KOACT", 
        "TIMEFOLIO", "WOORI", "히어로즈", "PLUS", "WON", "2X", "KRX"
    ]

    # 1. Kiwoom API 연결 시도하여 거래대금 상위 100종목 가져오기
    if KiwoomRealClient is not None:
        try:
            client = KiwoomRealClient()
            top_stocks = client.get_top_trading_value_stocks(limit=100)
            if top_stocks:
                for s in top_stocks:
                    clean = s.replace("_AL", "").replace("_NX", "").lstrip("A").strip()
                    if len(clean) == 6 and clean.isdigit():
                        name = client.get_stock_name(clean)
                        if any(kw in name for kw in exclude_keywords) or name.endswith("우") or name.endswith("우B"):
                            continue
                        universe[clean] = name
                logger.info(f"✅ 키움 API 거래대금 상위 {len(universe)}개 일반주 로드 완료")
        except Exception as e:
            logger.warning(f"키움 API 종목 로드 스킵 ({e})")

    # 2. today_picks.json 후보군 병합
    picks_path = os.path.join(execution_dir, "today_picks.json")
    if os.path.exists(picks_path):
        try:
            with open(picks_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for code, info in data.items():
                    clean = code.replace("_AL", "").replace("_NX", "").lstrip("A").strip()
                    if len(clean) == 6 and clean.isdigit():
                        name = info.get('name') or f"Stock_{clean}"
                        if any(kw in name for kw in exclude_keywords) or name.endswith("우"):
                            continue
                        universe[clean] = name
        except Exception as e:
            logger.warning(f"today_picks.json 로드 에러: {e}")

    # 3. 주요 활성 테마/중소형 주도주 기본 리스트 추가 (누락 방지)
    core_watchlist = {
        "053690": "한미글로벌", "079900": "전진건설로봇", "100840": "SNT에너지",
        "189860": "서전기전", "405100": "큐알티", "014620": "성광벤드",
        "006340": "대원전선", "199820": "제일일렉트릭", "084110": "휴온스글로벌",
        "042700": "한미반도체", "348370": "엔켐", "033170": "시그네틱스",
        "089890": "코세스", "091580": "상신이디피", "006110": "삼아알미늄",
        "020120": "키다리스튜디오", "243840": "신흥에스이씨", "452190": "한빛레이저",
        "300120": "라온피플", "258790": "소프트캠프", "184230": "SGA솔루션즈",
        "005930": "삼성전자", "000660": "SK하이닉스", "086520": "에코프로",
        "028300": "HLB", "005380": "현대차", "035420": "NAVER"
    }
    for c, n in core_watchlist.items():
        universe[c] = n

    return universe

def download_data(code: str):
    """종목의 15분봉, 30분봉, 일봉 데이터 다운로드"""
    if yf is None:
        return None, None, None
    
    clean_code = code.replace("A", "").strip()
    symbols = [f"{clean_code}.KS", f"{clean_code}.KQ"]
    
    for sym in symbols:
        try:
            end_dt = datetime.now()
            start_dt = end_dt - timedelta(days=45)
            
            # 15m
            df_15m = yf.download(sym, start=start_dt.strftime("%Y-%m-%d"), end=end_dt.strftime("%Y-%m-%d"), interval="15m", progress=False)
            if df_15m.empty or len(df_15m) < 45:
                continue
            if isinstance(df_15m.columns, pd.MultiIndex):
                df_15m.columns = df_15m.columns.droplevel(1)
            df_15m.columns = [c.lower() for c in df_15m.columns]
            
            # 30m
            df_30m = yf.download(sym, start=start_dt.strftime("%Y-%m-%d"), end=end_dt.strftime("%Y-%m-%d"), interval="30m", progress=False)
            if df_30m.empty:
                df_30m = df_15m.resample('30min').agg({
                    'open': 'first', 'high': 'max', 'low': 'min', 'close': 'last', 'volume': 'sum'
                }).dropna()
            else:
                if isinstance(df_30m.columns, pd.MultiIndex):
                    df_30m.columns = df_30m.columns.droplevel(1)
                df_30m.columns = [c.lower() for c in df_30m.columns]

            # Daily (최근 180일)
            daily_start = end_dt - timedelta(days=220)
            daily_df = yf.download(sym, start=daily_start.strftime("%Y-%m-%d"), end=end_dt.strftime("%Y-%m-%d"), interval="1d", progress=False)
            if isinstance(daily_df.columns, pd.MultiIndex):
                daily_df.columns = daily_df.columns.droplevel(1)
            daily_df.columns = [c.lower() for c in daily_df.columns]

            return df_15m, df_30m, daily_df
        except Exception:
            continue
            
    return None, None, None

def evaluate_stock_opportunity(code: str, name: str, df_15m: pd.DataFrame, df_30m: pd.DataFrame, daily_df: pd.DataFrame):
    """전략 기준 현재 상태 평가 (매수 신호 충족 여부 및 돌파 임박도 측정)"""
    if df_30m is None or df_30m.empty or daily_df is None or daily_df.empty:
        return None

    current_price = float(df_30m.iloc[-1]['close'])

    # 1주당 30만원 초과 고가주는 예산(종목당 30만원) 초과로 매수 불가하므로 제외
    if current_price >= 300000:
        return None
    
    # 1. 즉시 매수 조건 검사
    buy_signals = analyze_buy_signals(df_30m, None, daily_df)
    
    # 2. 일봉 지표 세부 계산
    df_d = daily_df.copy()
    df_d['sma20'] = df_d['close'].rolling(window=20, min_periods=20).mean()
    df_d['hh'] = calculate_hh(df_d)
    
    d_latest_sma20 = float(df_d.iloc[-1]['sma20']) if pd.notna(df_d.iloc[-1]['sma20']) else 0.0
    d_latest_hh = float(df_d.iloc[-1]['hh']) if pd.notna(df_d.iloc[-1]['hh']) else 0.0
    
    # 3. 30분봉 지표 세부 계산
    df30 = df_30m.copy()
    if len(df30) >= 260:
        df30['sma260'] = df30['close'].rolling(window=260, min_periods=260).mean()
        df30['hh'] = calculate_hh(df30)
        m30_latest_sma260 = float(df30.iloc[-1]['sma260']) if pd.notna(df30.iloc[-1]['sma260']) else 0.0
        m30_latest_hh = float(df30.iloc[-1]['hh']) if pd.notna(df30.iloc[-1]['hh']) else 0.0
    else:
        m30_latest_sma260 = 0.0
        m30_latest_hh = 0.0

    # 4. 돌파 임박도 (Proximity) 분석
    # 일봉 SMA20 및 HH와의 이격도 (%)
    daily_sma20_diff_pct = ((current_price - d_latest_sma20) / d_latest_sma20 * 100) if d_latest_sma20 > 0 else 999.0
    daily_hh_diff_pct = ((current_price - d_latest_hh) / d_latest_hh * 100) if d_latest_hh > 0 else 999.0

    # 30분봉 SMA260 및 HH와의 이격도 (%)
    m30_sma260_diff_pct = ((current_price - m30_latest_sma260) / m30_latest_sma260 * 100) if m30_latest_sma260 > 0 else 999.0
    m30_hh_diff_pct = ((current_price - m30_latest_hh) / m30_latest_hh * 100) if m30_latest_hh > 0 else 999.0

    # 5. 상태 분류
    status = "관망"
    status_score = 0
    note = ""

    if buy_signals.get('buy'):
        status = "🔥 매수 타점 충족"
        status_score = 100
        note = buy_signals.get('reason')
    elif (-3.0 <= daily_sma20_diff_pct <= 3.0) and (-5.0 <= daily_hh_diff_pct <= 3.0):
        status = "⚡ 일봉 돌파 임박 (저격 대기)"
        status_score = 80
        note = f"일봉 20이평({d_latest_sma20:,.0f}, {daily_sma20_diff_pct:+.1f}%) 및 고가선({d_latest_hh:,.0f}) 근접"
    elif (-2.0 <= m30_sma260_diff_pct <= 3.0) and (-4.0 <= m30_hh_diff_pct <= 4.0):
        status = "🎯 30분봉 돌파 임박"
        status_score = 75
        note = f"30분봉 260이평({m30_latest_sma260:,.0f}, {m30_sma260_diff_pct:+.1f}%) 및 고가선 근접"
    elif current_price > d_latest_sma20 and current_price > d_latest_hh:
        status = "📈 일봉 정배열 상승 중"
        status_score = 60
        note = f"일봉 20이평선 및 고가선 위 안착 유지"

    return {
        'code': code,
        'name': name,
        'current_price': current_price,
        'status': status,
        'status_score': status_score,
        'daily_sma20': d_latest_sma20,
        'daily_hh': d_latest_hh,
        'm30_sma260': m30_latest_sma260,
        'note': note
    }

def main():
    print("=" * 75)
    print(" 🏖️ [휴장일 특별 기획] 전략 맞춤형 내일의 공략주 사전 발굴 스캐너")
    print("=" * 75)

    universe = get_market_universe()
    print(f"\n🔍 총 {len(universe)}개 후보 종목을 정밀 분석합니다...")

    candidates = []
    
    for i, (code, name) in enumerate(universe.items(), 1):
        if i % 10 == 0 or i == len(universe):
            print(f"  [진행률: {i:02d}/{len(universe):02d}] 데이터 분석 중...")
            
        df_15m, df_30m, daily_df = download_data(code)
        if df_30m is None or df_30m.empty:
            continue
            
        eval_res = evaluate_stock_opportunity(code, name, df_15m, df_30m, daily_df)
        if eval_res and eval_res['status_score'] >= 60:
            candidates.append(eval_res)

    # 정렬: 매수 타점 충족 -> 돌파 임박 순
    candidates.sort(key=lambda x: x['status_score'], reverse=True)

    print("\n" + "=" * 75)
    print(f" 🏆 발굴 결과: 총 {len(candidates)}개 유력 공략주 선정!")
    print("=" * 75)

    if not candidates:
        print("현재 조건에 부합하는 종목이 없습니다.")
        return

    df_cand = pd.DataFrame(candidates)
    display_cols = ['name', 'code', 'current_price', 'status', 'daily_sma20', 'daily_hh', 'note']
    print(df_cand[display_cols].to_string(index=False))

    # 1. 봇 연동을 위해 today_picks.json 자동 업데이트
    ready_watchlist = {}
    for item in candidates:
        ready_watchlist[item['code']] = {
            'name': item['name'],
            'weight': 1.2 if "매수" in item['status'] else 1.0,
            'status': item['status'],
            'note': item['note']
        }

    output_path = os.path.join(execution_dir, "today_picks.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(ready_watchlist, f, ensure_ascii=False, indent=4)
    print(f"\n💾 [자동 연동 완료] 봇 관심종목 파일({output_path})에 {len(ready_watchlist)}개 종목이 등록되었습니다.")

    # 2. JSON 결과 저장
    output_result = os.path.join(current_dir, "weekend_scanned_picks.json")
    df_cand.to_json(output_result, orient="records", force_ascii=False, indent=2)
    print(f"💾 상세 스캔 결과가 저장되었습니다: {output_result}")

if __name__ == "__main__":
    main()
