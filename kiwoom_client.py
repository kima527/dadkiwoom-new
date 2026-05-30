import os
import logging
from datetime import datetime
import config

# Set environment variables required by the kiwoom-rest-api library
os.environ["KIWOOM_API_KEY"] = config.KIWOOM_APP_KEY
os.environ["KIWOOM_API_SECRET"] = config.KIWOOM_APP_SECRET
os.environ["KIWOOM_USE_SANDBOX"] = str(config.KIWOOM_IS_MOCK).lower()

from kiwoom_rest_api.auth.token import TokenManager
from kiwoom_rest_api.koreanstock.account import Account
from kiwoom_rest_api.koreanstock.chart import Chart

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

class KiwoomClient:
    def __init__(self):
        self.is_mock = config.KIWOOM_IS_MOCK
        self.base_url = "https://mockapi.kiwoom.com" if self.is_mock else "https://api.kiwoom.com"
        
        logger.info(f"Initializing Kiwoom REST Client (Mode: {'Mock' if self.is_mock else 'Real'}).")
        
        # TokenManager manages OAuth token and automatically refreshes it
        self.token_manager = TokenManager()
        
        # Initialize API modules
        self.account_api = Account(base_url=self.base_url, token_manager=self.token_manager)
        self.chart_api = Chart(base_url=self.base_url, token_manager=self.token_manager)

    def get_holdings(self) -> list:
        """
        Fetches current account holdings (positions) from Kiwoom.
        Returns a list of dicts: [{'code': '005930', 'name': '삼성전자', 'quantity': 10, 'buy_price': 70000.0}]
        """
        logger.info("Fetching account holdings...")
        try:
            # Query type '1' (Summary/Detail), domestic exchange 'KRX'
            result = self.account_api.account_evaluation_balance_detail_request_kt00018(
                query_type="1",
                domestic_exchange_type="KRX"
            )
            
            # Check for error or empty responses
            if not result:
                logger.error("Empty response received from balance inquiry.")
                return []
                
            positions_raw = result.get("acnt_evlt_remn_indv_tot", [])
            holdings = []
            
            for item in positions_raw:
                # In Kiwoom, stock codes might have a leading 'A' or spaces, strip them
                raw_code = item.get("stk_cd", "").strip()
                code = raw_code[1:] if raw_code.startswith("A") else raw_code
                
                name = item.get("stk_nm", "").strip()
                
                try:
                    qty = int(item.get("rmnd_qty", 0))
                    buy_price = float(item.get("pur_pric", 0.0))
                    cur_price = float(item.get("cur_prc", 0.0))
                except (ValueError, TypeError):
                    qty = 0
                    buy_price = 0.0
                    cur_price = 0.0
                    
                if qty > 0 and code:
                    holdings.append({
                        "code": code,
                        "name": name,
                        "quantity": qty,
                        "buy_price": buy_price,
                        "current_price": cur_price
                    })
            
            logger.info(f"Successfully retrieved {len(holdings)} holdings.")
            return holdings
        except Exception as e:
            logger.error(f"Error fetching holdings: {e}")
            return []

    def get_15min_candles(self, stock_code: str, last_n_days: int = 3) -> list:
        """
        Fetches 15-minute candlestick chart data for a stock code.
        Returns a list of parsed candles sorted by date/time ascending (oldest first).
        Filters data to contain only the most recent N days of data.
        """
        logger.info(f"Fetching 15-minute candles for stock code {stock_code}...")
        try:
            # stk_cd: stock code, tic_scope: '15' (15-min), upd_stkpc_tp: '1' (modified price)
            result = self.chart_api.stock_minute_chart_request_ka10080(
                stk_cd=stock_code,
                tic_scope="15",
                upd_stkpc_tp="1"
            )
            
            if not result:
                logger.error(f"Empty response received for chart of stock {stock_code}.")
                return []
                
            raw_candles = result.get("stk_min_pole_chart_qry", [])
            if not raw_candles:
                logger.warning(f"No candlestick data returned for {stock_code}.")
                return []
                
            parsed_candles = []
            for item in raw_candles:
                # Time format: YYYYMMDDHHMMSS
                raw_time = item.get("cntr_tm", "").strip()
                if len(raw_time) < 12:
                    continue
                    
                # Format time string for readability (e.g., YYYY-MM-DD HH:MM:SS)
                dt_str = f"{raw_time[:4]}-{raw_time[4:6]}-{raw_time[6:8]} {raw_time[8:10]}:{raw_time[10:12]}:00"
                date_only = f"{raw_time[:4]}-{raw_time[4:6]}-{raw_time[6:8]}"
                
                try:
                    close_prc = float(item.get("cur_prc", 0.0))
                    # Handle absolute prices if returned negative (Kiwoom sometimes prefixes negative sign for down days)
                    close_prc = abs(close_prc)
                    open_prc = abs(float(item.get("open_pric", 0.0)))
                    high_prc = abs(float(item.get("high_pric", 0.0)))
                    low_prc = abs(float(item.get("low_pric", 0.0)))
                    volume = int(item.get("trde_qty", 0))
                except (ValueError, TypeError):
                    continue
                    
                parsed_candles.append({
                    "time": dt_str,
                    "date": date_only,
                    "open": open_prc,
                    "high": high_prc,
                    "low": low_prc,
                    "close": close_prc,
                    "volume": volume
                })
                
            # Sort candles ascending (oldest first)
            parsed_candles.sort(key=lambda x: x["time"])
            
            if not parsed_candles:
                return []
                
            # Filter to keep only the last N trading days
            # 1. Identify all unique dates in the data
            unique_dates = sorted(list(set(c["date"] for c in parsed_candles)))
            
            # 2. Get the last N days
            target_dates = unique_dates[-last_n_days:]
            logger.info(f"Available dates in data: {unique_dates}. Filtering to target dates: {target_dates}")
            
            # 3. Filter the candles
            filtered_candles = [c for c in parsed_candles if c["date"] in target_dates]
            
            logger.info(f"Retrieved {len(filtered_candles)} 15-minute candles across {len(target_dates)} days for {stock_code}.")
            return filtered_candles
            
        except Exception as e:
            logger.error(f"Error fetching 15-min candles for {stock_code}: {e}")
            return []

if __name__ == "__main__":
    # Test client (Note: will only succeed if .env credentials are valid)
    client = KiwoomClient()
    holdings = client.get_holdings()
    print("Holdings:", holdings)
    
    # Test candles for Samsung Electronics
    candles = client.get_15min_candles("005930", last_n_days=3)
    if candles:
        print(f"First candle: {candles[0]}")
        print(f"Last candle: {candles[-1]}")
        print(f"Total candles fetched: {len(candles)}")
