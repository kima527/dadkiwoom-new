import requests
import json
import yfinance as yf

def fetch_korea_special_indices():
    results = {}
    
    # 1. Philadelphia Semiconductor Index (^SOX)
    try:
        t = yf.Ticker("^SOX")
        hist = t.history(period="5d")
        if len(hist) >= 2:
            curr = float(hist['Close'].iloc[-1])
            prev = float(hist['Close'].iloc[-2])
            pct = ((curr - prev) / prev) * 100.0
            results["SOX"] = {
                "symbol": "^SOX",
                "name": "필라델피아 반도체 (SOX)",
                "price": round(curr, 2),
                "change_pct": round(pct, 2),
                "category": "semi"
            }
    except Exception as e:
        print("SOX error:", e)

    # 2. TradingView Futures (KOSPI 200 Futures & KOSDAQ 150 Futures)
    try:
        url = 'https://scanner.tradingview.com/futures/scan'
        payload = {
            'symbols': {'tickers': ['KRX:K2I1!', 'KRX:KQI1!']},
            'columns': ['name', 'close', 'change', 'change_abs', 'description']
        }
        r = requests.post(url, json=payload, headers={'User-Agent': 'Mozilla/5.0'}, timeout=5)
        if r.status_code == 200:
            data = r.json().get('data', [])
            for item in data:
                s = item.get('s')
                d = item.get('d', [])
                if s == 'KRX:K2I1!':
                    results["KOSPI200_FUT"] = {
                        "symbol": "K2I1!",
                        "name": "야간 코스피200 선물",
                        "price": round(float(d[1]), 2),
                        "change_pct": round(float(d[2]), 2),
                        "change_abs": round(float(d[3]), 2) if d[3] is not None else 0.0,
                        "category": "korea_futures"
                    }
                elif s == 'KRX:KQI1!':
                    results["KOSDAQ150_FUT"] = {
                        "symbol": "KQI1!",
                        "name": "야간 코스닥150 선물",
                        "price": round(float(d[1]), 2),
                        "change_pct": round(float(d[2]), 2),
                        "change_abs": round(float(d[3]), 2) if d[3] is not None else 0.0,
                        "category": "korea_futures"
                    }
    except Exception as e:
        print("TradingView futures error:", e)

    return results

if __name__ == "__main__":
    res = fetch_korea_special_indices()
    print(json.dumps(res, ensure_ascii=False, indent=2))
