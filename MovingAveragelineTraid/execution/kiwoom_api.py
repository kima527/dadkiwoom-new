import os
import time
import pandas as pd
import logging
from datetime import datetime, timedelta
import config

logger = logging.getLogger(__name__)

class KiwoomRESTClient:
    def __init__(self):
        self.app_key = config.KIWOOM_APP_KEY
        self.app_secret = config.KIWOOM_APP_SECRET
        self.account_no = config.KIWOOM_ACCOUNT_NO
        self.base_url = "https://openapi.koreainvestment.com:9443" # Example base URL (OASK)
        self.access_token = "mock_token"
        
        logger.info("Initialized KiwoomRESTClient")

    def get_cash_balance(self) -> float:
        """Mock: Fetch available cash balance."""
        # In a real scenario, this would call the balance API.
        return 10000000.0  # 10,000,000 KRW

    def get_15m_candles(self, stock_code: str) -> pd.DataFrame:
        """Mock: Fetch 15-minute candles."""
        # Return a mock DataFrame with 'close' prices to calculate SMAs
        now = datetime.now()
        data = {
            'time': [now - timedelta(minutes=15 * i) for i in range(100, 0, -1)],
            'close': [50000 + (i * 100) for i in range(100)], # Upward trend mock
            'volume': [10000 for _ in range(100)]
        }
        df = pd.DataFrame(data)
        df.set_index('time', inplace=True)
        return df

    def get_tick_data(self, stock_code: str) -> list:
        """Mock: Fetch recent tick data to calculate momentum & safety zone."""
        # Return a list of recent ticks
        return [
            {'price': 59800, 'volume': 500},
            {'price': 59900, 'volume': 1000},
            {'price': 60000, 'volume': 2000}
        ]

    def calculate_momentum(self, stock_code: str) -> float:
        """Calculate momentum (체결가속도) based on recent ticks."""
        ticks = self.get_tick_data(stock_code)
        if not ticks:
            return 1.0
        # Example logic: Total volume of recent 3 ticks
        total_vol = sum(t['volume'] for t in ticks)
        return float(total_vol) / 1000.0  # Normalized score

    def get_tick_size(self, price: float) -> int:
        """한국거래소(KRX) 코스피/코스닥 통합 호가 단위 (2023년 개정 기준)"""
        if price < 2000:
            return 1
        elif price < 5000:
            return 5
        elif price < 20000:
            return 10
        elif price < 50000:
            return 50
        elif price < 200000:
            return 100
        elif price < 500000:
            return 500
        else:
            return 1000

    def calculate_safety_zone(self, stock_code: str, sma20_price: float) -> float:
        """
        Calculate safety zone (Limit Order Price) after 3-second wait.
        It uses the recent tick lowest price or the SMA 20 line as support.
        """
        ticks = self.get_tick_data(stock_code)
        recent_low = min(t['price'] for t in ticks) if ticks else sma20_price
        
        # We try to buy at the lowest point, e.g., slightly above SMA 20 or recent low
        target_price = max(recent_low * 0.99, sma20_price) # Don't buy below SMA 20 support
        
        # 정확한 호가 단위(Tick Size)로 가격 보정
        tick_size = self.get_tick_size(target_price)
        return float((int(target_price) // tick_size) * tick_size)

    def place_buy_order(self, stock_code: str, qty: int, price: float, order_type: str = "00"):
        """Place a limit buy order."""
        logger.info(f"==> BUY ORDER: {stock_code}, Qty: {qty}, Price: {price}, Type: {order_type}")
        return f"ORD_{int(time.time())}"

    def place_sell_order(self, stock_code: str, qty: int, price: float, order_type: str = "00"):
        """Place a sell order."""
        logger.info(f"==> SELL ORDER: {stock_code}, Qty: {qty}, Price: {price}, Type: {order_type}")
        return True

    def get_account_holdings(self) -> dict:
        """Mock: Fetch current stock holdings. Returns dict {stock_code: qty}"""
        # 실제 환경에서는 실시간 잔고조회 API 호출
        return {} # 현재는 빈 계좌(보유종목 없음)로 가정

    def get_unexecuted_orders(self) -> list:
        """Mock: Fetch unexecuted orders. Returns list of dicts"""
        # 실제 환경에서는 미체결조회 API 호출
        return []

    def cancel_order(self, order_no: str, stock_code: str, qty: int):
        """Mock: Cancel an unexecuted order."""
        logger.info(f"==> CANCEL ORDER: {order_no} (Stock: {stock_code}, Qty: {qty})")
        return True

    def get_condition_search_stocks(self, condition_name: str) -> list:
        """
        Mock: Call Kiwoom API to execute a condition search and return matching stock codes.
        In reality, this involves subscribing to condition search and handling events.
        """
        logger.info(f"API CALL: Fetching stocks for condition [{condition_name}]")
        # 실제로는 급등주가 나오겠지만, 목업 테스트를 위해 변동성이 큰 종목으로 임의 지정합니다.
        return ["042700", "086520", "028300"]

    def get_stock_name(self, stock_code: str) -> str:
        """Mock: Fetch stock name."""
        names = {"042700": "한미반도체", "086520": "에코프로", "028300": "HLB"}
        return names.get(stock_code, f"Stock_{stock_code}")

    def get_stock_theme(self, stock_code: str) -> str:
        """Mock: Fetch stock theme via API or Scraping."""
        themes = {"042700": "반도체", "086520": "2차전지", "028300": "바이오"}
        return themes.get(stock_code, "개별이슈")

