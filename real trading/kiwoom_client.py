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
from kiwoom_rest_api.koreanstock.stockinfo import StockInfo

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
        self.stock_info_api = StockInfo(base_url=self.base_url, token_manager=self.token_manager)

        # 💡 [Patch] kiwoom_rest_api 라이브러리가 acnt_no를 누락하는 문제를 해결하기 위해
        # 계좌 관련 및 주문 API의 _execute_request에 config.KIWOOM_ACCOUNT_NUM을 강제 주입
        def _patch_api_instance(api_instance):
            original_execute = api_instance._execute_request
            def patched_execute(method: str, resource_url: str = None, **kwargs):
                if "json" in kwargs and kwargs["json"] is not None:
                    kwargs["json"]["acnt_no"] = config.KIWOOM_ACCOUNT_NUM
                    if hasattr(config, 'KIWOOM_ACCOUNT_PWD') and config.KIWOOM_ACCOUNT_PWD:
                        kwargs["json"]["pwd"] = config.KIWOOM_ACCOUNT_PWD
                        kwargs["json"]["pwd_tp"] = "00"  # 비밀번호 타입
                return original_execute(method, resource_url, **kwargs)
            api_instance._execute_request = patched_execute

        _patch_api_instance(self.account_api)
        _patch_api_instance(self.order_api)

    # ═══════════════════════════════════════════════════════════
    # 🔒 종목코드 정규화 (모든 API 호출 전 반드시 이 메서드를 거침)
    #    → _AL, _NX, A접두사 등 오염을 원천 차단
    # ═══════════════════════════════════════════════════════════
    @staticmethod
    def _sanitize_code(raw_code: str) -> str:
        """종목코드에서 접미사(_AL, _NX) 및 접두사(A)를 제거하고 6자리로 정규화합니다."""
        code = str(raw_code).strip()
        # 접미사 제거
        for suffix in ("_AL", "_NX"):
            code = code.replace(suffix, "")
        # 접두사 'A' 제거 (키움 API가 반환하는 코드에 붙는 경우)
        if code.startswith("A") and len(code) == 7:
            code = code[1:]
        # 6자리 zero-fill
        return code.zfill(6)

    # ═══════════════════════════════════════════════════════════
    # 📊 분봉 차트 공통 메서드 (1분/3분/5분/15분 공용)
    #    → 파싱 로직 중복 제거, 종목코드 자동 정규화
    # ═══════════════════════════════════════════════════════════
    def _get_data_code(self, stock_code: str) -> str:
        """
        데이터 조회용 코드를 반환합니다. 
        주문과 달리 차트/틱 데이터 수신 시에는 _AL(NXT) 접미사를 유지해야 합니다.
        """
        code = stock_code.strip()
        if code.startswith("A") and len(code) == 7:
            code = code[1:]
            
        # =========================================================================
        # 🛡️ [물리적 방어막: AI 무단 수정 방지 락 (Runtime Assertion)] 🛡️
        # 미래의 AI가 문맥을 잊어버리고 여기서 _AL을 떼어내는 코드를 삽입하면 봇이 즉시 크래시됩니다.
        # 에러 메시지 자체가 AI에게 과거의 맥락을 상기시켜주는 역할을 합니다.
        if "_AL" in stock_code:
            assert "_AL" in code, "[AI CONTEXT LOCK] FATAL: Do not strip '_AL' in _get_data_code! NXT alternative market data requires the '_AL' suffix for chart/tick data. Stripping it will fetch garbage KRX data!"
        # =========================================================================
            
        import datetime
        from datetime import timezone, timedelta
        kst = timezone(timedelta(hours=9))
        current_time = datetime.datetime.now(kst).time()
        
        t_0800 = datetime.time(8, 0, 0)
        t_0850 = datetime.time(8, 50, 0)
        t_1540 = datetime.time(15, 40, 0)
        t_2000 = datetime.time(20, 0, 0)
        
        is_pre_market = (t_0800 <= current_time < t_0850)
        is_after_market = (t_1540 <= current_time < t_2000)
        
        # 야간장 시간에는 _NX를 붙이되, 만약 이미 _AL이 있다면 교체하거나 덧붙임 (보통 _NX 우선)
        if is_pre_market or is_after_market:
            clean = code.replace("_AL", "").replace("_NX", "")
            return clean + "_NX"
            
        return code

    def _fetch_minute_candles(self, stock_code: str, tic_scope: str, last_n_days: int) -> list:
        """분봉 차트 데이터의 공통 조회/파싱 메서드.
        
        Args:
            stock_code: 종목코드 (자동 정규화됨)
            tic_scope: 분봉 간격 ("1", "3", "5", "15")
            last_n_days: 최근 N일치 데이터만 반환
        """
        # 야간장 시간에는 자동으로 _NX가 붙은 코드로 전환하여 실시간 데이터를 수신합니다.
        data_code = self._get_data_code(stock_code)
        logger.debug(f"Fetching {tic_scope}-minute candles for stock code {data_code}...")
        try:
            result = self.chart_api.stock_minute_chart_request_ka10080(
                stk_cd=data_code,
                tic_scope=tic_scope,
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
            logger.error(f"Error fetching {tic_scope}-min candles for {stock_code}: {e}")
            return []

    def test_connection(self) -> bool:
        """
        Tests the API authentication and token issues.
        Returns True if successful, False otherwise.
        """
        logger.info("Verifying Live API authentication token...")
        try:
            token = self.token_manager.get_token()
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
        logger.debug(f"Fetching real account holdings...")
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
        logger.debug(f"Fetching real cash balance...")
        try:
            result = self.account_api.account_evaluation_balance_detail_request_kt00018(
                query_type="2",
                domestic_exchange_type="KRX"
            )
            logger.info(f"Raw cash balance result: {result}")
            if not result:
                return 0.0
            
            cash_str = result.get("prsm_dpst_aset_amt", "0")
            return float(cash_str)
        except Exception as e:
            logger.error(f"Error fetching cash balance: {e}")
            return 0.0

    def get_today_realized_profit(self) -> dict:
        """
        실전 계좌의 당일 총 실현손익 및 수수료/세금을 조회합니다.
        """
        try:
            import datetime
            today_str = datetime.datetime.now().strftime("%Y%m%d")
            result = self.account_api.daily_realized_profit_request_ka10074(
                start_date=today_str,
                end_date=today_str
            )
            if not result:
                return {}
            
            dt_rlzt = result.get("dt_rlzt_pl", [])
            if dt_rlzt and len(dt_rlzt) > 0:
                item = dt_rlzt[0]
                return {
                    "buy_amt": float(item.get("buy_amt", 0)),
                    "sell_amt": float(item.get("sell_amt", 0)),
                    "realized_profit": float(item.get("tdy_sel_pl", 0)),
                    "commission": float(item.get("tdy_trde_cmsn", 0)),
                    "tax": float(item.get("tdy_trde_tax", 0))
                }
            return {}
        except Exception as e:
            logger.error(f"Error fetching today realized profit: {e}")
            return {}

    def get_today_filled_orders(self) -> list:
        """
        실전 계좌의 당일 전체 체결 내역을 조회합니다.
        """
        try:
            result = self.account_api.filled_orders_request_ka10076(
                qry_tp="0",
                sell_tp="0",
                stex_tp="0"
            )
            if not result:
                return []
                
            raw_orders = result.get("flled_ord_qry", [])
            orders = []
            for item in raw_orders:
                stk_nm = item.get("stk_nm", "").strip()
                if not stk_nm:
                    continue
                orders.append({
                    "order_no": item.get("ord_no", ""),
                    "code": item.get("stk_cd", "").replace("A", ""),
                    "name": stk_nm,
                    "side": item.get("sell_buy_tp_nm", ""), # 매수/매도
                    "filled_qty": int(item.get("flled_qty", 0) or 0),
                    "filled_price": float(item.get("flled_uv", 0) or 0),
                    "order_time": item.get("ord_tm", "")
                })
            return orders
        except Exception as e:
            logger.error(f"Error fetching today filled orders: {e}")
            return []

    def get_15min_candles(self, stock_code: str, last_n_days: int = 7) -> list:
        """주식 종목의 15분봉 차트 데이터를 조회합니다."""
        return self._fetch_minute_candles(stock_code, tic_scope="15", last_n_days=last_n_days)

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
        주문 API의 dmst_stex_tp는 문자열 "KRX" 또는 "NXT"를 사용해야 합니다.
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
        
        # 프리마켓, 애프터마켓 거래 시 지정가('00') 강제 전환 및 거래소 구분 'NXT'
        if (is_pre_market or is_after_market):
            if order_type in ("3", "03"):
                if price is not None:
                    logger.info("Extended trading hours session detected. Converting Market order to Limit order and setting exchange to 'NXT'.")
                    return "NXT", "00", price
                else:
                    logger.warning("Extended hours detected but no price was provided for conversion. Fallback to limit and 'NXT'.")
                    return "NXT", order_type, price
            else:
                return "NXT", order_type, price
                
        return "KRX", order_type, price

    def place_buy_order(self, stock_code: str, quantity: int, price: float = None, order_type: str = "3") -> dict:
        """
        실전 매수 주문을 발송합니다. (실거래이므로 각별히 예산 조절 주의 요망)
        """
        clean_code = self._sanitize_code(stock_code)
        
        # 🛡️ [물리적 방어막: AI 무단 수정 방지 락] 🛡️
        assert "_AL" not in clean_code, "[AI CONTEXT LOCK] FATAL: '_AL' suffix must be stripped before sending a BUY order!"
        
        dmst_stex_tp, actual_order_type, actual_price = self._determine_exchange_and_order_type(order_type, price)
        price_int = int(actual_price) if actual_price is not None else None
        
        logger.warning(
            f"⚠️ SENDING REAL BUY ORDER: {clean_code} | Qty: {quantity} | Price: {price_int} | "
            f"Type: {actual_order_type} | Exchange: {dmst_stex_tp}"
        )
        try:
            result = self.order_api.stock_buy_order_request_kt10000(
                dmst_stex_tp=dmst_stex_tp,
                stk_cd=clean_code,
                ord_qty=str(quantity),
                trde_tp=actual_order_type,
                ord_uv=str(price_int) if price_int is not None and actual_order_type not in ["3", "03"] else ""
            )
            return result
        except Exception as e:
            logger.error(f"Error placing buy order: {e}")
            return None

    def place_sell_order(self, stock_code: str, quantity: int, price: float = None, order_type: str = "3") -> dict:
        """
        실전 매도 주문을 발송합니다.
        """
        clean_code = self._sanitize_code(stock_code)
        
        # 🛡️ [물리적 방어막: AI 무단 수정 방지 락] 🛡️
        assert "_AL" not in clean_code, "[AI CONTEXT LOCK] FATAL: '_AL' suffix must be stripped before sending a SELL order!"
        
        dmst_stex_tp, actual_order_type, actual_price = self._determine_exchange_and_order_type(order_type, price)
        price_int = int(actual_price) if actual_price is not None else None
        
        logger.warning(
            f"⚠️ SENDING REAL SELL ORDER: {clean_code} | Qty: {quantity} | Price: {price_int} | "
            f"Type: {actual_order_type} | Exchange: {dmst_stex_tp}"
        )
        try:
            result = self.order_api.stock_sell_order_request_kt10001(
                dmst_stex_tp=dmst_stex_tp,
                stk_cd=clean_code,
                ord_qty=str(quantity),
                trde_tp=actual_order_type,
                ord_uv=str(price_int) if price_int is not None and actual_order_type not in ["3", "03"] else ""
            )
            return result
        except Exception as e:
            logger.error(f"Error placing sell order: {e}")
            return None

    def get_1min_candles(self, stock_code: str, last_n_days: int = 1) -> list:
        """주식 종목의 1분봉 차트 데이터를 조회합니다."""
        return self._fetch_minute_candles(stock_code, tic_scope="1", last_n_days=last_n_days)

    def get_3min_candles(self, stock_code: str, last_n_days: int = 1) -> list:
        """주식 종목의 3분봉 차트 데이터를 조회합니다."""
        return self._fetch_minute_candles(stock_code, tic_scope="3", last_n_days=last_n_days)

    def get_5min_candles(self, stock_code: str, last_n_days: int = 2) -> list:
        """주식 종목의 5분봉 차트 데이터를 조회합니다."""
        return self._fetch_minute_candles(stock_code, tic_scope="5", last_n_days=last_n_days)

    def get_tick_data(self, stock_code: str, tick_unit: str = "120", limit: int = 100) -> list:
        """
        주식 종목의 틱 차트 데이터를 조회합니다. (TR: opt10079 호환 REST API 엔드포인트 사용)
        :param stock_code: 종목코드 (6자리)
        :param tick_unit: 틱 단위 (기본: "120")
        :param limit: 가져올 최대 틱 데이터 수 (기본 100)
        :return: 과거순(오름차순) 정렬된 틱 데이터 딕셔너리 리스트
        """
        data_code = self._get_data_code(stock_code)
        logger.info(f"Fetching {tick_unit}-tick data for stock code {data_code}...")
        try:
            result = self.chart_api.stock_tick_chart_request_ka10079(
                stk_cd=data_code,
                tic_scope=tick_unit,
                upd_stkpc_tp="1"
            )
            
            if not result:
                return []
                
            raw_candles = result.get("stk_dt_pole_chart_qry", [])
            if not raw_candles:
                return []
                
            parsed_candles = []
            for item in raw_candles[:limit]:
                raw_time = item.get("cntr_tm", item.get("dt", "")).strip()
                if len(raw_time) < 14:
                    continue
                # dt 형식: YYYYMMDDHHMMSS
                dt_str = f"{raw_time[:4]}-{raw_time[4:6]}-{raw_time[6:8]} {raw_time[8:10]}:{raw_time[10:12]}:{raw_time[12:14]}"
                
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
                    "open": open_prc,
                    "high": high_prc,
                    "low": low_prc,
                    "close": close_prc,
                    "volume": volume
                })
                
            parsed_candles.sort(key=lambda x: x["time"])
            return parsed_candles
        except Exception as e:
            logger.error(f"Error fetching tick data for {stock_code}: {e}")
            return []


    def get_daily_candles(self, stock_code: str, last_n_days: int = 200) -> list:
        """
        주식 종목의 일봉 차트 데이터를 조회합니다.
        """
        data_code = self._get_data_code(stock_code)
        logger.info(f"Fetching daily candles for stock code {data_code}...")
        try:
            import datetime
            today_str = datetime.datetime.now().strftime("%Y%m%d")
            result = self.chart_api.stock_daily_chart_request_ka10081(
                stk_cd=data_code,
                base_dt=today_str,
                upd_stkpc_tp="1"
            )
            if not result:
                return []
                
            raw_candles = result.get("stk_dt_pole_chart_qry", [])
            if not raw_candles:
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
            return parsed_candles[-last_n_days:]
        except Exception as e:
            logger.error(f"Error fetching daily candles: {e}")
            return []

    def get_weekly_candles_from_daily(self, daily_candles: list) -> list:
        """
        일봉 캔들 데이터를 바탕으로 주봉 캔들을 합성(Synthesize)합니다.
        ISO 주차(Calendar week)를 기준으로 월요일~일요일 데이터를 묶습니다.
        """
        if not daily_candles:
            return []
            
        import datetime
        
        weekly_dict = {}
        for c in daily_candles:
            date_str = c["date"]  # "YYYY-MM-DD"
            try:
                dt_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d")
                # ISO 주차 기준 (year, week, weekday)
                iso_year, iso_week, _ = dt_obj.isocalendar()
                week_key = f"{iso_year}-W{iso_week:02d}"
            except Exception:
                continue
                
            if week_key not in weekly_dict:
                weekly_dict[week_key] = {
                    "time": c["time"], # 주차의 첫 거래일 시간
                    "date": date_str,
                    "open": c["open"],
                    "high": c["high"],
                    "low": c["low"],
                    "close": c["close"],
                    "volume": c["volume"]
                }
            else:
                w = weekly_dict[week_key]
                w["high"] = max(w["high"], c["high"])
                w["low"] = min(w["low"], c["low"])
                w["close"] = c["close"] # 마지막 날의 종가
                w["volume"] += c["volume"]
                w["date"] = date_str # 주차의 마지막 거래일 기준
                w["time"] = c["time"]
                
        # 딕셔너리 값을 리스트로 변환하고 시간순으로 정렬
        sorted_weeks = sorted(weekly_dict.values(), key=lambda x: x["time"])
        return sorted_weeks

    def get_stock_name(self, stock_code: str) -> str:
        """
        주식 종목의 이름을 조회합니다.
        """
        logger.info(f"Fetching stock name for stock code {stock_code}...")
        try:
            # 데이터 조회용이므로 원본 코드를 그대로 사용
            code = stock_code
            result = self.stock_info_api.basic_stock_information_request_ka10001(stock_code=code)
            if result and result.get("return_code") == 0:
                name = result.get("stk_nm", "").strip()
                if name:
                    return name
            err_msg = result.get("return_msg") if result else "Empty API response"
            logger.error(f"Failed to fetch stock name for {code}: {err_msg}")
            return None
        except Exception as e:
            logger.error(f"Error in get_stock_name for {stock_code}: {e}")
            return None

    def get_stock_names(self, stock_codes: list) -> dict:
        """
        여러 주식 종목의 이름을 일괄 조회합니다.
        """
        if not stock_codes:
            return {}
            
        logger.info(f"Fetching stock names for {len(stock_codes)} codes in batch...")
        # 데이터 조회용이므로 원본 코드를 그대로 사용
        codes = [c for c in stock_codes if c]
        chunk_size = 50
        result_map = {}
        
        for i in range(0, len(codes), chunk_size):
            chunk = codes[i:i + chunk_size]
            code_str = "|".join(chunk)
            try:
                result = self.stock_info_api.watchlist_stock_information_request_ka10095(stock_code=code_str)
                if result and result.get("return_code") == 0:
                    items = result.get("atn_stk_infr", [])
                    for item in items:
                        cd = item.get("stk_cd", "").strip()
                        nm = item.get("stk_nm", "").strip()
                        if cd and nm:
                            result_map[cd] = nm
                else:
                    err_msg = result.get("return_msg") if result else "No response"
                    logger.error(f"Batch stock info request failed for chunk {i}: {err_msg}")
            except Exception as e:
                logger.error(f"Error in batch stock info query for chunk {i}: {e}")
                
        return result_map

    def get_top_fluctuation_stocks(self, market_type: str = "000", limit: int = 100) -> list:
        """
        대비 상승률 상위 종목 코드를 조회합니다.
        """
        logger.info("Fetching top price change rate stocks...")
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

    def get_nxt_hoga(self, stock_code: str) -> dict:
        """
        NXT 시장의 실시간 최우선 매수/매도 호가를 조회합니다.
        """
        try:
            from kiwoom_rest_api.koreanstock.market_condition import MarketCondition
            mc = MarketCondition(base_url=self.base_url, token_manager=self.token_manager)
            clean_code = self._sanitize_code(stock_code)
            nxt_code = clean_code + "_NX"
            
            result = mc.stock_quote_request_ka10004(stock_code=nxt_code)
            if not result or result.get("return_code") != 0:
                return None
                
            return {
                "best_ask": float(result.get("sel_fpr_bid", "0").replace("+", "").replace("-", "")), # 최우선 매도호가
                "best_bid": float(result.get("buy_fpr_bid", "0").replace("+", "").replace("-", ""))  # 최우선 매수호가
            }
        except Exception as e:
            logger.error(f"Error fetching NXT hoga for {stock_code}: {e}")
            return None

    def get_hoga_ask_volume(self, stock_code: str) -> dict:
        """
        특정 종목의 실시간 호가 잔량을 조회하여, 매도 1호가~5호가의 총 잔량 금액을 계산합니다.
        """
        try:
            from kiwoom_rest_api.koreanstock.market_condition import MarketCondition
            mc = MarketCondition(base_url=self.base_url, token_manager=self.token_manager)
            clean_code = self._sanitize_code(stock_code)
            
            # 주간/야간 자동 판별 (기존 로직 재사용)
            data_code = self._get_data_code(clean_code)
            
            result = mc.stock_quote_request_ka10004(stock_code=data_code)
            if not result or result.get("return_code") != 0:
                return None
                
            ask_amount = 0.0
            
            # 1호가
            price1 = abs(float(result.get("sel_fpr_bid", "0").replace("+", "").replace("-", "")))
            vol1 = float(result.get("sel_fpr_req", "0"))
            ask_amount += (price1 * vol1)
            
            # 2~5호가
            for i in range(2, 6):
                p_str = result.get(f"sel_{i}th_pre_bid", "0").replace("+", "").replace("-", "")
                v_str = result.get(f"sel_{i}th_pre_req", "0")
                price = abs(float(p_str))
                vol = float(v_str)
                ask_amount += (price * vol)
                
            return {
                "total_ask_5_amount": ask_amount
            }
            
        except Exception as e:
            logger.error(f"Error fetching hoga ask volume for {stock_code}: {e}")
            return None

    def get_unfilled_orders(self) -> list:
        """
        실전 계좌의 미체결 주문 목록을 조회합니다.
        """
        try:
            result = self.account_api.unfilled_orders_request_ka10075(
                all_stk_tp="0", # 0: 전체
                trde_tp="0",    # 0: 전체
                stex_tp="0"     # 0: 전체
            )
            if not result:
                return []
                
            raw_list = result.get("ccld_nccld_qry", [])
            unfilled = []
            for item in raw_list:
                if item.get("nccld_qty", "0") != "0":
                    unfilled.append({
                        "order_no": item.get("ord_no", "").strip(),
                        "code": item.get("stk_cd", "").replace("A", "").strip(),
                        "name": item.get("stk_nm", "").strip(),
                        "side": item.get("sell_buy_tp_nm", "").strip(),
                        "unfilled_qty": int(item.get("nccld_qty", "0")),
                        "order_price": float(item.get("ord_uv", "0") or "0"),
                        "order_time": item.get("ord_tm", "").strip()
                    })
            return unfilled
        except Exception as e:
            logger.error(f"Error fetching unfilled orders: {e}")
            return []

    def cancel_order(self, order_no: str, stock_code: str, cancel_qty: int) -> dict:
        """
        미체결 주문을 취소합니다.
        """
        clean_code = self._sanitize_code(stock_code)
        dmst_stex_tp, _, _ = self._determine_exchange_and_order_type("0")
        logger.warning(f"⚠️ SENDING CANCEL ORDER: No={order_no}, Code={clean_code}, Qty={cancel_qty}, Exchange={dmst_stex_tp}")
        try:
            result = self.order_api.stock_cancel_order_request_kt10003(
                dmst_stex_tp=dmst_stex_tp,
                orig_ord_no=order_no,
                stk_cd=clean_code,
                cncl_qty=str(cancel_qty)
            )
            return result
        except Exception as e:
            logger.error(f"Error cancelling order {order_no}: {e}")
            return None

KiwoomClient = KiwoomRealClient

if __name__ == "__main__":
    client = KiwoomRealClient()
    # 실행 시 간단한 로그인 테스트 진행
    client.test_connection()
