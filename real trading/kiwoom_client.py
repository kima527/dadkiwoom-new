import sys
import io
import os
import logging
from datetime import datetime

# Windows 콘솔에서 한국어(UTF-8)가 깨지지 않도록 안전하게 설정
if sys.platform.startswith("win"):
    try:
        if sys.stdout and not sys.stdout.closed:
            sys.stdout.reconfigure(encoding="utf-8")
        if sys.stderr and not sys.stderr.closed:
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Add parent or local config import
sys.path.append(os.path.abspath(os.path.dirname(__file__)))
import config

# Set environment variables required by the kiwoom-rest-api library
os.environ["KIWOOM_API_KEY"] = config.KIWOOM_APP_KEY
os.environ["KIWOOM_API_SECRET"] = config.KIWOOM_REAL_APP_SECRET
os.environ["KIWOOM_USE_SANDBOX"] = "false" # 실전 거래는 무조건 false 고정

from kiwoom_rest_api.auth.token import TokenManager
from kiwoom_rest_api.koreanstock.account import Account
from kiwoom_rest_api.koreanstock.chart import Chart
from kiwoom_rest_api.koreanstock.order import Order
from kiwoom_rest_api.koreanstock.rank_info import RankInfo

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

class KiwoomRealClient:
    def __init__(self):
        # 실전용 API 주소 고정 (https://api.kiwoom.com)
        self.base_url = "https://api.kiwoom.com"
        
        logger.info("Initializing Live Kiwoom REST Client (REAL TRADING MODE)...")
        
        # TokenManager가 실전용 APP_KEY와 APP_SECRET을 가지고 실시간 토큰 발급 및 자동 갱신을 주도합니다.
        self.token_manager = TokenManager()
        
        # API 모듈 인스턴스화
        self.account_api = Account(base_url=self.base_url, token_manager=self.token_manager)
        self.chart_api = Chart(base_url=self.base_url, token_manager=self.token_manager)
        self.order_api = Order(base_url=self.base_url, token_manager=self.token_manager)
        self.rank_api = RankInfo(base_url=self.base_url, token_manager=self.token_manager)

    def test_connection(self) -> bool:
        """
        Tests the API authentication and token issues.
        Returns True if successful, False otherwise.
        """
        logger.info("Verifying Live API authentication token...")
        try:
            token = self.token_manager.get_access_token()
            if token:
                logger.info("✅ Live OAuth 2.0 Access Token successfully issued and validated!")
                return True
            else:
                logger.error("❌ Failed to retrieve Access Token. Please verify APP_KEY and APP_SECRET.")
                return False
        except Exception as e:
            logger.error(f"❌ Connection test failed with error: {e}")
            return False

    def get_holdings(self) -> list:
        """
        실전 계좌의 보유 주식 현황을 조회합니다.
        """
        logger.info("Fetching real account holdings...")
        try:
            result = self.account_api.account_evaluation_balance_detail_request_kt00018(
                query_type="1",
                domestic_exchange_type="KRX"
            )
            if not result:
                return []
                
            positions_raw = result.get("acnt_evlt_remn_indv_tot", [])
            holdings = []
            
            for item in positions_raw:
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
            return holdings
        except Exception as e:
            logger.error(f"Error fetching holdings: {e}")
            return []

    def get_cash_balance(self) -> float:
        """
        실전 계좌의 매수 가능 예수금을 조회합니다.
        """
        logger.info("Fetching real cash balance...")
        try:
            result = self.account_api.account_evaluation_balance_detail_request_kt00018(
                query_type="2",
                domestic_exchange_type="KRX"
            )
            if not result:
                return 0.0
            
            cash_str = result.get("prsm_dpst_aset_amt", "0")
            return float(cash_str)
        except Exception as e:
            logger.error(f"Error fetching cash balance: {e}")
            return 0.0

    def get_15min_candles(self, stock_code: str, last_n_days: int = 7) -> list:
        """
        주식 종목의 15분봉 차트 데이터를 조회합니다.
        """
        logger.info(f"Fetching 15-minute candles for stock code {stock_code}...")
        try:
            result = self.chart_api.stock_minute_chart_request_ka10080(
                stk_cd=stock_code,
                tic_scope="15",
                upd_stkpc_tp="1"
            )
            if not result:
                return []
                
            raw_candles = result.get("stk_min_pole_chart_qry", [])
            if not raw_candles:
                return []
                
            parsed_candles = []
            for item in raw_candles:
                raw_time = item.get("cntr_tm", "").strip()
                if len(raw_time) < 12:
                    continue
                dt_str = f"{raw_time[:4]}-{raw_time[4:6]}-{raw_time[6:8]} {raw_time[8:10]}:{raw_time[10:12]}:00"
                date_only = f"{raw_time[:4]}-{raw_time[4:6]}-{raw_time[6:8]}"
                
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
            unique_dates = sorted(list(set(c["date"] for c in parsed_candles)))
            target_dates = unique_dates[-last_n_days:]
            return [c for c in parsed_candles if c["date"] in target_dates]
        except Exception as e:
            logger.error(f"Error fetching 15-min candles: {e}")
            return []

    def get_top_trading_value_stocks(self, market_type: str = "000", limit: int = 100) -> list:
        """
        국내주식 실시간 거래대금 상위 종목을 조회합니다.
        """
        try:
            result = self.rank_api.top_trading_value_request_ka10032(
                mrkt_tp=market_type,
                mang_stk_incls="0",
                stex_tp="3"
            )
            if not result:
                return []
            raw_list = result.get("trde_prica_upper", [])
            return [item.get("stk_cd", "").strip() for item in raw_list[:limit] if item.get("stk_cd")]
        except Exception as e:
            logger.error(f"Error fetching top trading value: {e}")
            return []

    # 🔒 [CRITICAL LOGIC LOCK - DO NOT MODIFY]
    # ── get_top_fluctuation_stocks_with_rates (실시간 등락률 조회 모듈) ──
    def get_top_fluctuation_stocks_with_rates(self, market_type: str = "000", limit: int = 100) -> dict:
        """
        국내주식 실시간 대비 상승 등락률 상위 종목을 조회합니다.
        """
        try:
            result = self.rank_api.top_day_over_day_change_rate_request_ka10027(
                mrkt_tp=market_type,
                sort_tp="1",
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
            logger.error(f"Error fetching top fluctuation rates: {e}")
            return {}

    def _determine_exchange_and_order_type(self, order_type: str, price: float = None) -> tuple:
        """
        실전 NXT 대체거래소 세션 시간대에 맞춰 적합한 거래소 구분 및 주문타입을 매핑합니다.
        """
        import datetime
        from datetime import timezone, timedelta
        
        kst = timezone(timedelta(hours=9))
        now = datetime.datetime.now(kst)
        current_time = now.time()
        
        t_0800 = datetime.time(8, 0, 0)
        t_0850 = datetime.time(8, 50, 0)
        t_1540 = datetime.time(15, 40, 0)
        t_2000 = datetime.time(20, 0, 0)
        
        is_pre_market = (t_0800 <= current_time < t_0850)
        is_after_market = (t_1540 <= current_time < t_2000)
        
        # 프리마켓, 애프터마켓 거래 시 지정가('0') 강제 전환
        if (is_pre_market or is_after_market) and order_type == "3":
            if price is not None:
                logger.info("Extended trading hours session detected. Converting Market order to Limit order.")
                return "SOR", "0", price
            else:
                logger.warning("Extended hours detected but no price was provided for conversion. Fallback to market.")
                return "SOR", order_type, price
                
        return "SOR", order_type, price

    def place_buy_order(self, stock_code: str, quantity: int, price: float = None, order_type: str = "3") -> dict:
        """
        실전 매수 주문을 발송합니다. (실거래이므로 각별히 예산 조절 주의 요망)
        """
        dmst_stex_tp, actual_order_type, actual_price = self._determine_exchange_and_order_type(order_type, price)
        price_int = int(actual_price) if actual_price is not None else None
        
        logger.warning(
            f"⚠️ SENDING REAL BUY ORDER: {stock_code} | Qty: {quantity} | Price: {price_int} | "
            f"Type: {actual_order_type} | Exchange: {dmst_stex_tp}"
        )
        try:
            result = self.order_api.stock_buy_order_request_kt10000(
                dmst_stex_tp=dmst_stex_tp,
                stk_cd=stock_code,
                ord_qty=str(quantity),
                trde_tp=actual_order_type,
                ord_uv=str(price_int) if price_int is not None else ""
            )
            return result
        except Exception as e:
            logger.error(f"Error placing buy order: {e}")
            return None

    def place_sell_order(self, stock_code: str, quantity: int, price: float = None, order_type: str = "3") -> dict:
        """
        실전 매도 주문을 발송합니다.
        """
        dmst_stex_tp, actual_order_type, actual_price = self._determine_exchange_and_order_type(order_type, price)
        price_int = int(actual_price) if actual_price is not None else None
        
        logger.warning(
            f"⚠️ SENDING REAL SELL ORDER: {stock_code} | Qty: {quantity} | Price: {price_int} | "
            f"Type: {actual_order_type} | Exchange: {dmst_stex_tp}"
        )
        try:
            result = self.order_api.stock_sell_order_request_kt10001(
                dmst_stex_tp=dmst_stex_tp,
                stk_cd=stock_code,
                ord_qty=str(quantity),
                trde_tp=actual_order_type,
                ord_uv=str(price_int) if price_int is not None else ""
            )
            return result
        except Exception as e:
            logger.error(f"Error placing sell order: {e}")
            return None

if __name__ == "__main__":
    client = KiwoomRealClient()
    # 실행 시 간단한 로그인 테스트 진행
    client.test_connection()
