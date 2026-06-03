import sys
import io

# Windows 콘솔에서 한국어(UTF-8)가 깨지지 않도록 안전하게 설정
if sys.platform.startswith("win"):
    try:
        if sys.stdout and not sys.stdout.closed:
            sys.stdout.reconfigure(encoding="utf-8")
        if sys.stderr and not sys.stderr.closed:
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

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
from kiwoom_rest_api.koreanstock.order import Order
from kiwoom_rest_api.koreanstock.rank_info import RankInfo

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
        self.order_api = Order(base_url=self.base_url, token_manager=self.token_manager)
        self.rank_api = RankInfo(base_url=self.base_url, token_manager=self.token_manager)

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

    def get_daily_candles(self, stock_code: str, last_n_days: int = 80) -> list:
        """
        Fetches daily candlestick chart data for a stock code.
        Returns a list of parsed candles sorted by date ascending (oldest first).
        """
        logger.info(f"Fetching daily candles for stock code {stock_code}...")
        try:
            import datetime
            today_str = datetime.datetime.now().strftime("%Y%m%d")
            result = self.chart_api.stock_daily_chart_request_ka10081(
                stk_cd=stock_code,
                base_dt=today_str,
                upd_stkpc_tp="1"
            )
            
            if not result:
                logger.error(f"Empty response received for daily chart of stock {stock_code}.")
                return []
                
            raw_candles = result.get("stk_dt_pole_chart_qry", [])
            if not raw_candles:
                logger.warning(f"No daily candlestick data returned for {stock_code}.")
                return []
                
            parsed_candles = []
            for item in raw_candles:
                raw_time = item.get("dt", "").strip()
                if len(raw_time) < 8:
                    continue
                    
                date_only = f"{raw_time[:4]}-{raw_time[4:6]}-{raw_time[6:8]}"
                dt_str = f"{date_only} 09:00:00"
                
                try:
                    close_prc = abs(float(item.get("cur_prc", 0.0)))
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
                
            parsed_candles.sort(key=lambda x: x["time"])
            
            if not parsed_candles:
                return []
                
            filtered_candles = parsed_candles[-last_n_days:]
            logger.info(f"Retrieved {len(filtered_candles)} daily candles for {stock_code}.")
            return filtered_candles
            
        except Exception as e:
            logger.error(f"Error fetching daily candles for {stock_code}: {e}")
            return []

    def _determine_exchange_and_order_type(self, order_type: str, price: float = None) -> tuple:
        """
        Determines the domestic exchange type (dmst_stex_tp), actual trade type (trde_tp), 
        and limit price based on the current time and mock trading settings.
        
        NXT sessions:
          - Pre-market: 08:00 ~ 08:50 (Limit order only, no market order)
          - Main-market: 09:00:30 ~ 15:20 (Market & Limit allowed)
          - After-market: 15:40 ~ 20:00 (Limit order only, no market order)
        
        Returns:
            (dmst_stex_tp, trde_tp, price_val)
        """
        import datetime
        from datetime import timezone, timedelta
        
        # 1. If Mock trading, SOR and NXT are NOT supported by Kiwoom Mock API
        if self.is_mock:
            return "KRX", order_type, price
            
        # 2. Real Trading: determine session
        kst = timezone(timedelta(hours=9))
        now = datetime.datetime.now(kst)
        current_time = now.time()
        
        t_0800 = datetime.time(8, 0, 0)
        t_0850 = datetime.time(8, 50, 0)
        t_1540 = datetime.time(15, 40, 0)
        t_2000 = datetime.time(20, 0, 0)
        
        is_pre_market = (t_0800 <= current_time < t_0850)
        is_after_market = (t_1540 <= current_time < t_2000)
        
        # In Pre-market and After-market, NXT only supports Limit orders ('0')
        if (is_pre_market or is_after_market) and order_type == "3":
            if price is not None:
                logger.info("Extended trading hours session detected. Converting Market order to Limit order.")
                return "SOR", "0", price
            else:
                logger.warning("Extended hours detected but no price was provided for conversion. Fallback to market.")
                return "SOR", order_type, price
                
        # Main market or fallback
        return "SOR", order_type, price

    def place_buy_order(self, stock_code: str, quantity: int, price: float = None, order_type: str = "3") -> dict:
        """
        Places a buy order for a stock code.
        order_type: '0' for Limit (지정가), '3' for Market (시장가)
        """
        dmst_stex_tp, actual_order_type, actual_price = self._determine_exchange_and_order_type(order_type, price)
        price_int = int(actual_price) if actual_price is not None else None
        
        logger.info(
            f"Placing buy order for {stock_code}: quantity={quantity}, price={price_int}, "
            f"type={actual_order_type}, exchange={dmst_stex_tp}"
        )
        try:
            qty_str = str(quantity)
            price_str = str(price_int) if price_int is not None else ""
            
            result = self.order_api.stock_buy_order_request_kt10000(
                dmst_stex_tp=dmst_stex_tp,
                stk_cd=stock_code,
                ord_qty=qty_str,
                trde_tp=actual_order_type,
                ord_uv=price_str
            )
            logger.info(f"Buy order response: {result}")
            return result
        except Exception as e:
            logger.error(f"Error placing buy order for {stock_code}: {e}")
            return None

    def place_sell_order(self, stock_code: str, quantity: int, price: float = None, order_type: str = "3") -> dict:
        """
        Places a sell order for a stock code.
        order_type: '0' for Limit (지정가), '3' for Market (시장가)
        """
        dmst_stex_tp, actual_order_type, actual_price = self._determine_exchange_and_order_type(order_type, price)
        price_int = int(actual_price) if actual_price is not None else None
        
        logger.info(
            f"Placing sell order for {stock_code}: quantity={quantity}, price={price_int}, "
            f"type={actual_order_type}, exchange={dmst_stex_tp}"
        )
        try:
            qty_str = str(quantity)
            price_str = str(price_int) if price_int is not None else ""
            
            result = self.order_api.stock_sell_order_request_kt10001(
                dmst_stex_tp=dmst_stex_tp,
                stk_cd=stock_code,
                ord_qty=qty_str,
                trde_tp=actual_order_type,
                ord_uv=price_str
            )
            logger.info(f"Sell order response: {result}")
            return result
        except Exception as e:
            logger.error(f"Error placing sell order for {stock_code}: {e}")
            return None

    def get_cash_balance(self) -> float:
        """
        Gets the available cash (deposit asset amount) in the account.
        """
        logger.info("Fetching cash balance...")
        try:
            result = self.account_api.account_evaluation_balance_detail_request_kt00018(
                query_type="2",
                domestic_exchange_type="KRX"
            )
            if not result:
                logger.error("Empty response received from balance inquiry.")
                return 0.0
            
            # prsm_dpst_aset_amt contains the cash/deposit asset amount
            cash_str = result.get("prsm_dpst_aset_amt", "0")
            cash = float(cash_str)
            logger.info(f"Available Cash Balance: {cash:,.0f} KRW")
            return cash
        except Exception as e:
            logger.error(f"Error fetching cash balance: {e}")
            return 0.0

    def get_top_trading_value_stocks(self, market_type: str = "000", limit: int = 100) -> list:
        """
        Fetches top trading value stocks.
        market_type: "000" (All), "001" (KOSPI), "101" (KOSDAQ)
        Returns a list of stock codes: ['005930', '000660', ...]
        """
        logger.info("Fetching top trading value stocks...")
        try:
            result = self.rank_api.top_trading_value_request_ka10032(
                mrkt_tp=market_type,
                mang_stk_incls="0",
                stex_tp="3"
            )
            if not result:
                return []
            
            raw_list = result.get("trde_prica_upper", [])
            codes = []
            for item in raw_list[:limit]:
                code = item.get("stk_cd", "").strip()
                if code:
                    codes.append(code)
            return codes
        except Exception as e:
            logger.error(f"Error fetching top trading value stocks: {e}")
            return []

    def get_top_fluctuation_stocks(self, market_type: str = "000", limit: int = 100) -> list:
        """
        Fetches top day-over-day price change rate stocks (descending).
        market_type: "000" (All), "001" (KOSPI), "101" (KOSDAQ)
        Returns a list of stock codes: ['005930', '000660', ...]
        """
        logger.info("Fetching top price change rate stocks...")
        try:
            result = self.rank_api.top_day_over_day_change_rate_request_ka10027(
                mrkt_tp=market_type,
                sort_tp="1", # 대비 상승률순
                trde_qty_cnd="0000",
                stk_cnd="0",
                crd_cnd="0",
                updown_incls="1",
                pric_cnd="0",
                trde_prica_cnd="0",
                stex_tp="3"
            )
            if not result:
                return []
            
            raw_list = result.get("pred_pre_flu_rt_upper", [])
            codes = []
            for item in raw_list[:limit]:
                code = item.get("stk_cd", "").strip()
                if code:
                    codes.append(code)
            return codes
        except Exception as e:
            logger.error(f"Error fetching top price change rate stocks: {e}")
            return []

    # 🔒 [CRITICAL LOGIC LOCK - DO NOT MODIFY]
    # ── get_top_fluctuation_stocks_with_rates (실시간 등락률 조회 모듈) ──
    def get_top_fluctuation_stocks_with_rates(self, market_type: str = "000", limit: int = 100) -> dict:
        """
        Fetches top price change rate stocks along with their rates.
        Returns a dict: {'005930': 3.45, '000660': -1.20, ...}
        """
        logger.info("Fetching top price change rate stocks with rates...")
        try:
            result = self.rank_api.top_day_over_day_change_rate_request_ka10027(
                mrkt_tp=market_type,
                sort_tp="1", # 대비 상승률순
                trde_qty_cnd="0000",
                stk_cnd="0",
                crd_cnd="0",
                updown_incls="1",
                pric_cnd="0",
                trde_prica_cnd="0",
                stex_tp="3"
            )
            if not result:
                return {}
            
            raw_list = result.get("pred_pre_flu_rt_upper", [])
            rates_map = {}
            for item in raw_list[:limit]:
                code = item.get("stk_cd", "").strip()
                flu_rt_str = item.get("flu_rt", "0").strip()
                if code:
                    try:
                        rates_map[code] = float(flu_rt_str)
                    except ValueError:
                        rates_map[code] = 0.0
            return rates_map
        except Exception as e:
            logger.error(f"Error fetching top price change rate stocks with rates: {e}")
            return {}

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
