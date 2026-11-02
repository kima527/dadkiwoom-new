import os
import sys
import json
from datetime import datetime
import yfinance as yf
import pandas as pd

# Ensure UTF-8 output
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Key market watch list
TICKERS = {
    # Major Indices
    "^GSPC": {"name": "S&P 500", "category": "index"},
    "^IXIC": {"name": "나스닥 (Nasdaq)", "category": "index"},
    "^DJI": {"name": "다우존스 (Dow)", "category": "index"},
    # Macro Indicators
    "^TNX": {"name": "미 10년물 국채금리", "category": "macro"},
    "^VIX": {"name": "VIX 변동성지수", "category": "macro"},
    "DX-Y.NYB": {"name": "달러 인덱스 (USD)", "category": "macro"},
    # Mag 7 & Semiconductors
    "NVDA": {"name": "엔비디아 (NVDA)", "category": "stock"},
    "AAPL": {"name": "애플 (AAPL)", "category": "stock"},
    "MSFT": {"name": "마이크로소프트 (MSFT)", "category": "stock"},
    "TSLA": {"name": "테슬라 (TSLA)", "category": "stock"},
    "GOOGL": {"name": "알파벳 (GOOGL)", "category": "stock"},
    "AMZN": {"name": "아마존 (AMZN)", "category": "stock"},
    "META": {"name": "메타 (META)", "category": "stock"},
    "TSM": {"name": "TSMC (TSM)", "category": "stock"},
    # Crypto & Commodities
    "BTC-USD": {"name": "비트코인 (BTC)", "category": "crypto"},
    "GC=F": {"name": "금 (Gold)", "category": "commodity"},
    "CL=F": {"name": "WTI 원유 (Oil)", "category": "commodity"}
}

def fetch_market_data():
    """Fetches real-time / latest market data and calculates changes."""
    print("📡 [1단계] 미국 증시 및 글로벌 거시 지표 데이터 수집 중...", flush=True)
    symbols = list(TICKERS.keys())
    
    # Download 5 days of data for reliable percentage change and trend
    df = yf.download(symbols, period="5d", interval="1d", progress=False)['Close']
    
    results = []
    for sym, meta in TICKERS.items():
        try:
            if sym not in df.columns:
                continue
            series = df[sym].dropna()
            if len(series) < 2:
                continue
            curr_price = float(series.iloc[-1])
            prev_price = float(series.iloc[-2])
            change_pct = ((curr_price - prev_price) / prev_price) * 100.0
            
            # 5-day change
            first_price = float(series.iloc[0])
            week_pct = ((curr_price - first_price) / first_price) * 100.0
            
            results.append({
                "symbol": sym,
                "name": meta["name"],
                "category": meta["category"],
                "price": curr_price,
                "change_pct": round(change_pct, 2),
                "week_pct": round(week_pct, 2),
                "history": [round(float(p), 2) for p in series.values]
            })
        except Exception as e:
            continue
            
    return results

def analyze_anomalies(data):
    """Detects the biggest anomalies and generates killer hooks."""
    # Sort by absolute change percentage
    stocks = [d for d in data if d["category"] in ("stock", "crypto")]
    macros = [d for d in data if d["category"] in ("index", "macro", "commodity")]
    
    stocks_sorted = sorted(stocks, key=lambda x: abs(x["change_pct"]), reverse=True)
    macros_sorted = sorted(macros, key=lambda x: abs(x["change_pct"]), reverse=True)
    
    top_stock = stocks_sorted[0] if stocks_sorted else None
    top_macro = macros_sorted[0] if macros_sorted else None
    
    # Check nasdaq and 10Y treasury
    nasdaq = next((d for d in data if d["symbol"] == "^IXIC"), None)
    tnx = next((d for d in data if d["symbol"] == "^TNX"), None)
    sp500 = next((d for d in data if d["symbol"] == "^GSPC"), None)
    
    # Formulate 3 Killer Hooks
    hooks = []
    
    # Hook 1: Top mover shock
    if top_stock:
        direction = "급등" if top_stock["change_pct"] > 0 else "급락"
        sign = "+" if top_stock["change_pct"] > 0 else ""
        hooks.append(
            f"오늘 새벽 월가를 뒤흔든 {top_stock['name']} {sign}{top_stock['change_pct']}%, 스마트머니는 왜 움직였을까?"
        )
        
    # Hook 2: Macro divergence
    if nasdaq and tnx:
        if nasdaq["change_pct"] < 0 and tnx["change_pct"] > 0:
            hooks.append("나스닥 하락 뒤에 숨겨진 10년물 국채금리 폭등, 오늘 한국장 반도체는 과연 안전할까?")
        elif nasdaq["change_pct"] > 0 and tnx["change_pct"] < 0:
            hooks.append("나스닥 반등 성공! 금리 안정세 속에 외국인이 몰래 사들인 섹터는?")
        else:
            hooks.append(f"오늘 미국 증시 마감 데이터, 수급 신호가 보내는 가장 긴급한 경고 1가지")
            
    # Hook 3: Direct account impact
    if top_stock and abs(top_stock["change_pct"]) >= 2.0:
        hooks.append(
            f"{top_stock['name']} 보유자분들 딱 1분만 보세요. 오늘 장 시작 전 반드시 알아야 할 지지선 팩트"
        )
    else:
        hooks.append("월가 기관들이 오늘 아침 조용히 포트폴리오를 교체한 결정적 데이터")

    report = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "top_anomaly": top_stock,
        "top_macro": top_macro,
        "key_indices": {
            "sp500": sp500,
            "nasdaq": nasdaq,
            "treasury_10y": tnx
        },
        "hooks": hooks,
        "all_data": data
    }
    
    return report

def main():
    data = fetch_market_data()
    if not data:
        print("❌ 데이터 수집 실패: 인터넷 연결 또는 야후 파이낸스 상태를 확인하세요.")
        return
        
    report = analyze_anomalies(data)
    
    # Save to .tmp/market_anomaly_today.json
    os.makedirs(".tmp", exist_ok=True)
    out_json = ".tmp/market_anomaly_today.json"
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
        
    print("\n" + "="*65)
    print("🎯 [모닝 퀀트] 오늘의 미국 증시 핵심 이상치(Anomaly) 분석 결과")
    print("="*65)
    
    top_stock = report["top_anomaly"]
    if top_stock:
        sign = "+" if top_stock["change_pct"] > 0 else ""
        print(f"🔥 [최대 변동 종목]: {top_stock['name']} ({sign}{top_stock['change_pct']}%) / 5일 누적: {top_stock['week_pct']}%")
        
    sp = report["key_indices"]["sp500"]
    nq = report["key_indices"]["nasdaq"]
    tnx = report["key_indices"]["treasury_10y"]
    if sp:
        print(f"📈 S&P 500 : {sp['price']:.2f} ({'+' if sp['change_pct']>0 else ''}{sp['change_pct']}%)")
    if nq:
        print(f"💻 나스닥    : {nq['price']:.2f} ({'+' if nq['change_pct']>0 else ''}{nq['change_pct']}%)")
    if tnx:
        print(f"💵 미 국채10년: {tnx['price']:.2f}% ({'+' if tnx['change_pct']>0 else ''}{tnx['change_pct']}%)")
        
    print("\n💡 [추천 3초 킬러 훅 (Hook 후보)]")
    for i, h in enumerate(report["hooks"], 1):
        print(f"  {i}. \"{h}\"")
        
    print("="*65)
    print(f"📁 구조화 데이터 저장 완료: {os.path.abspath(out_json)}\n")

if __name__ == "__main__":
    main()

