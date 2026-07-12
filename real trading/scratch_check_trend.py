import asyncio, pandas as pd, csv
from kiwoom_client import KiwoomClient

async def get_trend(client, code, name):
    try:
        daily = await asyncio.to_thread(client.get_daily_candles, code, 60)
        min15 = await asyncio.to_thread(client.get_15min_candles, code, 30)
        
        if not daily or not min15:
            return None
            
        df_d = pd.DataFrame({'close': [c['close'] for c in daily]})
        df_d['SMA20'] = df_d['close'].rolling(20).mean()
        df_d['SMA40'] = df_d['close'].rolling(40).mean()
        
        df_m = pd.DataFrame({'close': [c['close'] for c in min15]})
        df_m['SMA20'] = df_m['close'].rolling(20).mean()
        df_m['SMA40'] = df_m['close'].rolling(40).mean()
        
        d_close = df_d['close'].iloc[-1]
        d_sma20 = df_d['SMA20'].iloc[-1]
        d_sma40 = df_d['SMA40'].iloc[-1]
        
        m_close = df_m['close'].iloc[-1]
        m_sma20 = df_m['SMA20'].iloc[-1]
        m_sma40 = df_m['SMA40'].iloc[-1]
        
        # Calculate trend strength (gap between SMA20 and SMA40 as %)
        d_trend = (d_sma20 - d_sma40) / d_sma40 * 100
        m_trend = (m_sma20 - m_sma40) / m_sma40 * 100
        
        return {
            'name': name,
            'code': code,
            'd_trend_pct': d_trend,
            'm_trend_pct': m_trend,
            'd_status': '정배열(Bull)' if d_sma20 > d_sma40 else '역배열(Bear)',
            'm_status': '정배열(Bull)' if m_sma20 > m_sma40 else '역배열(Bear)',
            'price': d_close
        }
    except Exception as e:
        return None

async def main():
    client = KiwoomClient()
    stocks = []
    try:
        with open(r'C:\Users\zoela\OneDrive\바탕 화면\target.csv', 'r', encoding='cp949') as f:
            reader = csv.reader(f)
            for row in reader:
                if len(row) >= 5:
                    code = row[0].strip().replace("'", "").replace("A", "") # code in row 0
                    name = row[1].strip() # name in row 1
                    if code and code != '종목코드' and code.isdigit():
                        stocks.append((code, name))
    except Exception as e:
        print(f'Error reading csv: {e}')
        return
        
    print(f'Found {len(stocks)} stocks in target.csv')
    
    results = []
    for code, name in stocks:
        print(f'Analyzing {name} ({code})...')
        res = await get_trend(client, code, name)
        if res:
            results.append(res)
        await asyncio.sleep(0.5)
        
    # Sort by daily trend strength
    results.sort(key=lambda x: x['d_trend_pct'], reverse=True)
    
    with open('target_trend_results.txt', 'w', encoding='utf-8') as out:
        out.write('\\n--- Trend Analysis Results ---\\n')
        for r in results:
            out.write(f"[{r['name']}] Price: {r['price']:,.0f}\n")
            out.write(f"  일봉(Daily) : {r['d_status']} (이격도: {r['d_trend_pct']:.2f}%)\n")
            out.write(f"  15분봉(15m): {r['m_status']} (이격도: {r['m_trend_pct']:.2f}%)\n")
            out.write("-" * 40 + "\n")

if __name__ == '__main__':
    asyncio.run(main())
