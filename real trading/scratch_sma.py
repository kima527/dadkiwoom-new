import asyncio
from kiwoom_client import KiwoomClient
from indicator import calculate_sma

async def main():
    client = KiwoomClient()
    candles = await asyncio.to_thread(client.get_5min_candles, '005930', 2)
    closes = [c['close'] for c in candles[-20:]]
    sma3 = calculate_sma(closes, 3)[-1]
    sma8 = calculate_sma(closes, 8)[-1]
    print(f'SMA3: {sma3:.2f}, SMA8: {sma8:.2f}')

if __name__ == "__main__":
    asyncio.run(main())
