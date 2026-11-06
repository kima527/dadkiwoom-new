import os
import sys
import time
import logging
import pandas as pd
from datetime import datetime

logger = logging.getLogger(__name__)

# 진짜 실전 API를 가져오기 위한 경로 설정
real_trading_path = os.path.abspath(r"C:\Users\zoela\OneDrive\바탕 화면\PythonWorksplace\real trading")
if real_trading_path not in sys.path:
    sys.path.append(real_trading_path)

try:
    from kiwoom_client import KiwoomRealClient
except ImportError as e:
    logger.error(f"실전 API(KiwoomRealClient)를 불러올 수 없습니다: {e}")
    sys.exit(1)

class RealAPIAdapter:
    """
    모의 API(KiwoomRESTClient)와 완전히 동일한 함수(메서드)를 제공하지만,
    내부적으로는 실전 API(KiwoomRealClient)를 호출하여 진짜 통신을 수행하는 어댑터 클래스입니다.
    """
    def __init__(self):
        logger.info("==================================================")
        logger.info(" ⚠️ [실전 연동 완료] 진짜 계좌로 매매가 전송됩니다 ⚠️")
        logger.info("==================================================")
        self.real_client = KiwoomRealClient()
        if not self.real_client.test_connection():
            logger.error("❌ 실전 API 연결 테스트 실패. 토큰이나 인증 설정을 확인하세요.")
            sys.exit(1)

    def extract_order_no(self, result):
        if not result: return None
        for k, v in result.items():
            if 'ord_no' in k.lower() and str(v).strip():
                return str(v).strip()
        return None

    def get_cash_balance(self) -> float:
        """실제 예수금 조회"""
        try:
            return self.real_client.get_cash_balance()
        except Exception as e:
            logger.error(f"예수금 조회 에러: {e}")
            return 0.0

    def get_1m_candles(self, stock_code: str) -> pd.DataFrame:
        """실전 1분봉 데이터를 가져와서 trading_bot이 쓰는 Pandas DataFrame으로 변환"""
        try:
            # 실전 API는 리스트 형태 반환: [{'time': '090000', 'close': 50000, ...}, ...] (추정)
            # 여기서는 get_1min_candles 를 호출한다고 가정합니다.
            raw_candles = self.real_client.get_1min_candles(stock_code, last_n_days=2)
            
            if not raw_candles:
                return pd.DataFrame()
                
            df = pd.DataFrame(raw_candles)
            # 키움 실전 API 반환값에 맞춰 컬럼명을 소문자로 통일하고 형변환
            df.columns = [col.lower() for col in df.columns]
            
            # 최신순(미래->과거)으로 오는 데이터를 과거->현재순으로 뒤집기
            df = df.iloc[::-1].reset_index(drop=True)
            
            if 'time' in df.columns:
                df['time'] = pd.to_datetime(df['time'], errors='coerce')
                df.set_index('time', inplace=True)
                df.sort_index(inplace=True)
                
            for col in ['open', 'high', 'low', 'close', 'volume']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                    
            if 'date' in df.columns:
                df.drop(columns=['date'], inplace=True)
                
            return df
        except Exception as e:
            logger.error(f"1분봉 변환 에러 ({stock_code}): {e}")
            return pd.DataFrame()

    def get_2m_candles(self, stock_code: str) -> pd.DataFrame:
        """실전 2분봉 데이터를 가져와서 trading_bot이 쓰는 Pandas DataFrame으로 변환"""
        try:
            raw_candles = []
            if hasattr(self.real_client, 'get_2min_candles'):
                raw_candles = self.real_client.get_2min_candles(stock_code, last_n_days=4)
            elif hasattr(self.real_client, '_fetch_minute_candles'):
                raw_candles = self.real_client._fetch_minute_candles(stock_code, tic_scope="2", last_n_days=4)

            df = self._convert_raw_candles_to_df(raw_candles, stock_code, "2분봉") if raw_candles else pd.DataFrame()
            
            # 2분봉 직접 조회가 부족할 경우 1분봉 데이터를 2분봉으로 리샘플링하여 합성
            if df.empty or len(df) < 20:
                df_1m = self.get_1m_candles(stock_code)
                if not df_1m.empty and len(df_1m) >= 2:
                    df = df_1m.resample('2min').agg({
                        'open': 'first',
                        'high': 'max',
                        'low': 'min',
                        'close': 'last',
                        'volume': 'sum'
                    }).dropna()
            return df
        except Exception as e:
            logger.error(f"2분봉 변환 에러 ({stock_code}): {e}")
            return pd.DataFrame()

    def get_15m_candles(self, stock_code: str) -> pd.DataFrame:
        """실전 15분봉 데이터를 가져와서 trading_bot이 쓰는 Pandas DataFrame으로 변환"""
        try:
            raw_candles = self.real_client.get_15min_candles(stock_code, last_n_days=14)
            
            if not raw_candles:
                return pd.DataFrame()
                
            df = pd.DataFrame(raw_candles)
            df.columns = [col.lower() for col in df.columns]
            
            # 최신순(미래->과거)으로 오는 데이터를 과거->현재순으로 뒤집기
            df = df.iloc[::-1].reset_index(drop=True)
            
            if 'time' in df.columns:
                # 키움 API: "2026-08-01 09:15:00" 형태 문자열 → datetime 변환
                df['time'] = pd.to_datetime(df['time'], errors='coerce')
                df.set_index('time', inplace=True)
                df.sort_index(inplace=True)  # ★ 시간순 정렬 보장 (WMA/shift 계산 필수)
                
            for col in ['open', 'high', 'low', 'close', 'volume']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # date 컬럼은 전략 계산에 불필요하므로 제거
            if 'date' in df.columns:
                df.drop(columns=['date'], inplace=True)
                    
            return df
        except Exception as e:
            logger.error(f"15분봉 변환 에러 ({stock_code}): {e}")
            return pd.DataFrame()

    def _convert_raw_candles_to_df(self, raw_candles: list, stock_code: str, label: str) -> pd.DataFrame:
        """분봉 데이터(dict 리스트)를 DataFrame으로 변환하는 공통 메서드"""
        try:
            if not raw_candles:
                return pd.DataFrame()

            df = pd.DataFrame(raw_candles)
            df.columns = [col.lower() for col in df.columns]

            # 최신순(미래->과거) → 과거->현재 순으로 뒤집기
            df = df.iloc[::-1].reset_index(drop=True)

            if 'time' in df.columns:
                df['time'] = pd.to_datetime(df['time'], errors='coerce')
                df.set_index('time', inplace=True)
                df.sort_index(inplace=True)

            for col in ['open', 'high', 'low', 'close', 'volume']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')

            if 'date' in df.columns:
                df.drop(columns=['date'], inplace=True)

            return df
        except Exception as e:
            logger.error(f"{label} 변환 에러 ({stock_code}): {e}")
            return pd.DataFrame()

    def get_daily_candles(self, stock_code: str) -> pd.DataFrame:
        """실전 일봉 데이터를 가져와서 DataFrame으로 변환"""
        try:
            # _get_data_code를 쓰지 않아도 일봉은 보통 종목코드 원형으로 조회 가능
            clean_code = stock_code.replace('_AL', '').replace('_NX', '').strip()
            if clean_code.startswith('A') and len(clean_code) == 7:
                clean_code = clean_code[1:]
                
            base_dt = datetime.now().strftime('%Y%m%d')
            result = self.real_client.chart_api.stock_daily_chart_request_ka10081(
                stk_cd=clean_code,
                base_dt=base_dt,
                upd_stkpc_tp='1'
            )
            
            if not result or "stk_dt_pole_chart_qry" not in result:
                return pd.DataFrame()
                
            raw_candles = result["stk_dt_pole_chart_qry"]
            if not raw_candles:
                return pd.DataFrame()
                
            parsed_candles = []
            for item in raw_candles:
                dt_str = item.get("dt", "").strip()
                if not dt_str:
                    continue
                try:
                    close_prc = abs(float(item.get("cur_prc", 0.0)))
                    open_prc = abs(float(item.get("open_pric", 0.0)))
                    high_prc = abs(float(item.get("high_pric", 0.0)))
                    low_prc = abs(float(item.get("low_pric", 0.0)))
                    volume = int(item.get("trde_qty", 0))
                except (ValueError, TypeError):
                    continue
                    
                parsed_candles.append({
                    "date": dt_str,
                    "open": open_prc,
                    "high": high_prc,
                    "low": low_prc,
                    "close": close_prc,
                    "volume": volume
                })
                
            # 최신 데이터가 맨 뒤로 오도록 정렬
            parsed_candles.sort(key=lambda x: x["date"])
            df = pd.DataFrame(parsed_candles)
            return df
            
        except Exception as e:
            logger.error(f"일봉 변환 에러 ({stock_code}): {e}")
            return pd.DataFrame()

    def get_5m_candles(self, stock_code: str) -> pd.DataFrame:
        """실전 5분봉 데이터를 가져와서 Pandas DataFrame으로 변환"""
        try:
            raw_candles = self.real_client.get_5min_candles(stock_code, last_n_days=3)
            return self._convert_raw_candles_to_df(raw_candles, stock_code, "5분봉")
        except Exception as e:
            logger.error(f"5분봉 조회 에러 ({stock_code}): {e}")
            return pd.DataFrame()

    def get_3m_candles(self, stock_code: str) -> pd.DataFrame:
        """실전 3분봉 데이터를 가져와서 Pandas DataFrame으로 변환"""
        try:
            raw_candles = self.real_client.get_3min_candles(stock_code, last_n_days=2)
            return self._convert_raw_candles_to_df(raw_candles, stock_code, "3분봉")
        except Exception as e:
            logger.error(f"3분봉 조회 에러 ({stock_code}): {e}")
            return pd.DataFrame()

    def get_30m_candles(self, stock_code: str) -> pd.DataFrame:
        """실전 30분봉 데이터를 가져와서 Pandas DataFrame으로 변환 (SMA260 계산을 위해 30일치 조회)"""
        try:
            raw_candles = self.real_client._fetch_minute_candles(stock_code, tic_scope="30", last_n_days=30) if hasattr(self.real_client, '_fetch_minute_candles') else []
            if not raw_candles and hasattr(self.real_client, 'get_30min_candles'):
                raw_candles = self.real_client.get_30min_candles(stock_code, last_n_days=30)
            return self._convert_raw_candles_to_df(raw_candles, stock_code, "30분봉")
        except Exception as e:
            logger.error(f"30분봉 조회 에러 ({stock_code}): {e}")
            return pd.DataFrame()

    def get_60m_candles(self, stock_code: str) -> pd.DataFrame:
        """실전 60분봉 데이터를 가져와서 Pandas DataFrame으로 변환 (HTS 60분봉 공식 차트 일치)"""
        try:
            raw_candles = []
            if hasattr(self.real_client, '_fetch_minute_candles'):
                raw_candles = self.real_client._fetch_minute_candles(stock_code, tic_scope="60", last_n_days=30)
            elif hasattr(self.real_client, 'get_60min_candles'):
                raw_candles = self.real_client.get_60min_candles(stock_code, last_n_days=30)

            df = self._convert_raw_candles_to_df(raw_candles, stock_code, "60분봉") if raw_candles else pd.DataFrame()

            # 직접 조회가 부족할 경우 30분봉 데이터를 60분봉으로 리샘플링하여 안전 합성
            if df.empty or len(df) < 10:
                df_30m = self.get_30m_candles(stock_code)
                if not df_30m.empty and len(df_30m) >= 2:
                    df = df_30m.resample('60min').agg({
                        'open': 'first',
                        'high': 'max',
                        'low': 'min',
                        'close': 'last',
                        'volume': 'sum'
                    }).dropna()
            return df
        except Exception as e:
            logger.error(f"60분봉 조회 에러 ({stock_code}): {e}")
            return pd.DataFrame()

    def get_current_price(self, stock_code: str) -> float:
        """현재가 조회 (계좌 잔고 캐시 우선)"""
        try:
            holdings = self.get_account_holdings()
            clean_code = stock_code.replace('_AL', '').replace('_NX', '').lstrip('A').strip()
            if clean_code in holdings and holdings[clean_code].get('current_price', 0) > 0:
                return float(holdings[clean_code]['current_price'])
        except Exception as e:
            logger.debug(f"현재가 조회 에러 ({stock_code}): {e}")
        return 0.0

    def get_120t_candles(self, stock_code: str) -> pd.DataFrame:
        """실전 120틱 데이터를 가져와서 Pandas DataFrame으로 변환"""
        try:
            # 120틱 데이터는 봉 개수가 많이 필요하므로 limit를 넉넉히(500) 요청합니다.
            raw_candles = self.real_client.get_tick_data(stock_code, tick_unit="120", limit=500)
            return self._convert_raw_candles_to_df(raw_candles, stock_code, "120틱")
        except Exception as e:
            logger.error(f"120틱 데이터 조회 에러 ({stock_code}): {e}")
            return pd.DataFrame()

    def get_tick_data(self, stock_code: str) -> list:
        try:
            return self.real_client.get_tick_data(stock_code, tick_unit="1", limit=30)
        except Exception as e:
            logger.error(f"틱 데이터 조회 에러 ({stock_code}): {e}")
            return []

    def calculate_momentum(self, stock_code: str) -> float:
        """체결 가속도 (모의 로직과 동일하게 유지하거나 실전 틱 활용)"""
        ticks = self.get_tick_data(stock_code)
        if not ticks:
            return 1.0
        total_vol = sum(float(t.get('volume', 0) or t.get('cnt', 0)) for t in ticks)
        return float(total_vol) / 1000.0

    def get_tick_size(self, price: float) -> int:
        if price < 2000: return 1
        elif price < 5000: return 5
        elif price < 20000: return 10
        elif price < 50000: return 50
        elif price < 200000: return 100
        elif price < 500000: return 500
        else: return 1000

    def calculate_safety_zone(self, stock_code: str, sma20_price: float) -> float:
        """안전마진 매수호가 산출 (틱 호가 보정)"""
        target_price = sma20_price
        ticks = self.get_tick_data(stock_code)
        if ticks:
            try:
                recent_low = min(float(t.get('price', t.get('close', sma20_price))) for t in ticks)
                target_price = max(recent_low * 0.99, sma20_price)
            except Exception as e:
                logger.error(f"안전마진 매수호가 산출 에러: {e}")
                pass
        tick_size = self.get_tick_size(target_price)
        return float((int(target_price) // tick_size) * tick_size)

    def place_buy_order(self, stock_code: str, qty: int, price: float, order_type: str = "00"):
        """실전 매수 주문"""
        logger.info(f"🚀 [실전 매수 쏨!] 종목:{stock_code}, 수량:{qty}, 단가:{price}, 타입:{order_type}")
        result = self.real_client.place_buy_order(stock_code, qty, price=price, order_type=order_type)
        return self.extract_order_no(result)

    def place_sell_order(self, stock_code: str, qty: int, price: float, order_type: str = "00"):
        """실전 매도 주문"""
        logger.info(f"🚨 [실전 매도 쏨!] 종목:{stock_code}, 수량:{qty}, 단가:{price}, 타입:{order_type}")
        result = self.real_client.place_sell_order(stock_code, qty, price=price, order_type=order_type)
        return self.extract_order_no(result)

    def get_account_holdings(self) -> dict:
        """실전 계좌 잔고 리스트를 봇이 원하는 dict 형태로 변환"""
        holdings_dict = {}
        try:
            holdings = self.real_client.get_holdings()
            for h in (holdings or []):
                code = h.get('code', '').lstrip('A')
                if code:
                    holdings_dict[code] = {
                        'name': str(h.get('name', '')).strip(),
                        'qty': int(h.get('quantity', h.get('qty', 0))),
                        'buy_price': float(h.get('buy_price', 0)),
                        'current_price': float(h.get('current_price', 0)),
                        'return_rate': float(h.get('return_rate', 0.0))
                    }
        except Exception as e:
            logger.error(f"잔고 조회 에러: {e}")
        return holdings_dict

    def get_unexecuted_orders(self) -> list:
        """실전 미체결 주문 목록 조회"""
        try:
            unfilled = self.real_client.get_unfilled_orders()
            res = []
            for u in unfilled:
                code = str(u.get('code', '')).replace('_AL', '').replace('_NX', '').lstrip('A').strip()
                if code:
                    res.append({
                        'stock_code': code,
                        'order_no': u.get('order_no', ''),
                        'side': u.get('side', ''),
                        'unfilled_qty': u.get('unfilled_qty', 0)
                    })
            return res
        except Exception as e:
            logger.error(f"미체결 주문 목록 조회 에러: {e}")
            return []

    def cancel_order(self, order_no: str, stock_code: str, qty: int):
        """실전 매수/매도 주문 취소"""
        logger.info(f"취소 주문 전송: {order_no} ({stock_code})")
        return self.real_client.cancel_order(order_no, stock_code, qty)

    # 테마나 종목 이름 등은 기존 모의 스크립트 그대로 유지 (또는 실전 API 기능 사용)
    def get_stock_name(self, stock_code: str) -> str:
        try:
            return self.real_client.get_stock_name(stock_code)
        except Exception as e:
            logger.error(f"종목명 조회 에러 ({stock_code}): {e}")
            return f"Stock_{stock_code}"

    def get_market_cap(self, stock_code: str) -> float:
        """
        종목의 시가총액(원 단위)을 조회합니다. (캐시 활용)
        Kiwoom basic_stock_information_request_ka10001의 'mac' 필드는 '억원' 단위.
        """
        if not hasattr(self, '_market_cap_cache'):
            self._market_cap_cache = {}

        code = stock_code.replace("_AL", "").replace("_NX", "").lstrip("A").strip()
        if code in self._market_cap_cache:
            return self._market_cap_cache[code]

        try:
            res = self.real_client.stock_info_api.basic_stock_information_request_ka10001(stock_code=code)
            if res and 'mac' in res:
                mac_val = str(res['mac']).replace(',', '').replace('+', '').replace('-', '').strip()
                if mac_val.isdigit():
                    # 억원 -> 원 변환 (1억원 = 100,000,000원)
                    cap_won = float(mac_val) * 100_000_000.0
                    self._market_cap_cache[code] = cap_won
                    return cap_won
        except Exception as e:
            logger.debug(f"시가총액 조회 에러 ({stock_code}): {e}")

        return 0.0

    def get_stock_credit_info(self, stock_code: str) -> dict:
        """
        종목의 신용 정보(신용비율, 신용한도초과 여부)를 조회합니다. (캐시 활용)
        """
        if not hasattr(self, '_credit_info_cache'):
            self._credit_info_cache = {}

        code = stock_code.replace("_AL", "").replace("_NX", "").lstrip("A").strip()
        if code in self._credit_info_cache:
            return self._credit_info_cache[code]

        res_info = {'code': code, 'crd_rt': 0.0, 'is_limit_exceeded': False, 'margin_status': '정상'}
        try:
            res = self.real_client.stock_info_api.basic_stock_information_request_ka10001(stock_code=code)
            if res and res.get('return_code') == 0:
                crd_str = str(res.get('crd_rt', '0.0')).replace('+', '').replace('-', '').strip()
                crd_val = float(crd_str) if crd_str else 0.0
                res_info['crd_rt'] = crd_val

                state_str = str(res.get('stk_state', '')) + str(res.get('return_msg', ''))
                if crd_val >= 10.0 or '신용한도초과' in state_str or '신용불가' in state_str:
                    res_info['is_limit_exceeded'] = True
                    res_info['margin_status'] = '신용한도초과'

                self._credit_info_cache[code] = res_info
                return res_info
        except Exception as e:
            logger.debug(f"신용정보 조회 에러 ({stock_code}): {e}")

        self._credit_info_cache[code] = res_info
        return res_info

    def is_credit_limit_exceeded(self, stock_code: str) -> bool:
        """종목의 신용 한도 초과 여부를 반환합니다."""
        info = self.get_stock_credit_info(stock_code)
        return info.get('is_limit_exceeded', False)

    def get_stock_market_type(self, stock_code: str) -> str:
        """
        종목의 소속 시장('KOSPI' 또는 'KOSDAQ')을 조회하여 반환합니다. (영구 메모리 캐시 활용)
        - 키움 ka10100 API의 marketCode('0': 거래소/코스피, '10': 코스닥) 및 marketName 기준
        """
        if not hasattr(self, '_market_type_cache'):
            self._market_type_cache = {}

        code = stock_code.replace("_AL", "").replace("_NX", "").lstrip("A").strip()
        if code in self._market_type_cache:
            return self._market_type_cache[code]

        market_type = "KOSDAQ"  # 개별 테마주 기본값
        try:
            res = self.real_client.stock_info_api.stock_information_inquiry_request_ka10100(stock_code=code)
            if res and isinstance(res, dict):
                m_code = str(res.get('marketCode', '')).strip()
                m_name = str(res.get('marketName', '')).strip()
                if m_code == '10' or '코스닥' in m_name:
                    market_type = "KOSDAQ"
                elif m_code == '0' or '거래소' in m_name or '코스피' in m_name:
                    market_type = "KOSPI"
                self._market_type_cache[code] = market_type
                return market_type
        except Exception as e:
            logger.debug(f"소속 시장 조회 에러 ({stock_code}): {e}")

        return market_type

    def _parse_futures_benchmark(self, label: str, long_code: str, inv_code: str) -> dict:
        """
        코스피200 선물(F-KOSPI200) / 코스닥150 선물(F-KOSDAQ150) 실시간 상태 파싱:
        - 정방향 지수/선물 ETF(long_code)와 순수 선물지수 1:1 인버스 ETF(inv_code)를 교차 검증하여
          1) 전일 대비 등락률(flu_rt)
          2) 당일 시가 대비 방향(intraday_chg_pct: 양봉 반등 vs 시가 하회 음봉 투매)
          3) 당일 고점 대비 되밀림 폭(drawdown_from_high_pct)
          을 산출하고 3단계 시장 날씨(NORMAL_BULL / CAUTION_DEFENSE / CRASH_LOCK)를 판정합니다.
        """
        default_state = {
            'label': label,
            'flu_rt': 0.0,
            'intraday_chg_pct': 0.0,
            'drawdown_from_high_pct': 0.0,
            'is_bull_candle': True,
            'regime': 'NORMAL_BULL',
            'badge': '🟢정상',
            'reason': '정상 흐름'
        }
        try:
            r_long = self.real_client.stock_info_api.basic_stock_information_request_ka10001(stock_code=long_code)
            r_inv = self.real_client.stock_info_api.basic_stock_information_request_ka10001(stock_code=inv_code)

            def _clean_float(val, abs_val=False):
                if val is None:
                    return 0.0
                s = str(val).replace(',', '').strip()
                if not s:
                    return 0.0
                v = float(s)
                return abs(v) if abs_val else v

            # 1) 순수 선물지수(F-KOSPI200: 114800 / F-KOSDAQ150: 251340) 역산값 및 정방향(069500 / 229200) 결합
            long_flu = _clean_float(r_long.get('flu_rt', 0.0)) if r_long else 0.0
            inv_flu = _clean_float(r_inv.get('flu_rt', 0.0)) if r_inv else 0.0

            # 선물 등락률: 선물지수 1:1 추종 인버스(-inv_flu)와 대표지수(long_flu) 평균(일방 누락 시 유효값 사용)
            if inv_flu != 0.0 and long_flu != 0.0:
                flu_rt = round(((-inv_flu) + long_flu) / 2.0, 2)
            elif inv_flu != 0.0:
                flu_rt = round(-inv_flu, 2)
            else:
                flu_rt = round(long_flu, 2)

            cur_p = _clean_float(r_long.get('cur_prc', 0.0), abs_val=True) if r_long else 0.0
            open_p = _clean_float(r_long.get('open_pric', 0.0), abs_val=True) if r_long else 0.0
            high_p = _clean_float(r_long.get('high_pric', 0.0), abs_val=True) if r_long else 0.0

            if cur_p > 0 and open_p > 0:
                intraday_chg_pct = round(((cur_p - open_p) / open_p) * 100.0, 2)
            else:
                # fallback via inverse ETF
                inv_cur = _clean_float(r_inv.get('cur_prc', 0.0), abs_val=True) if r_inv else 0.0
                inv_open = _clean_float(r_inv.get('open_pric', 0.0), abs_val=True) if r_inv else 0.0
                intraday_chg_pct = round(-((inv_cur - inv_open) / inv_open) * 100.0, 2) if (inv_cur > 0 and inv_open > 0) else 0.0

            if cur_p > 0 and high_p > 0 and high_p >= cur_p:
                drawdown_from_high_pct = round(((high_p - cur_p) / high_p) * 100.0, 2)
            else:
                drawdown_from_high_pct = 0.0

            is_bull_candle = (intraday_chg_pct >= -0.05)

            # 🌡️ [3단계 선물지수 날씨 판정 공식]:
            # 🔴 3단계 (CRASH_LOCK - 신규 매수 전면 잠금 서킷브레이커):
            #   Case A: 전일 대비 -1.5% 이하 하락 중이면서 동시에 당일 시가 아래 음봉 투매(intraday_chg_pct < -0.20%) 지속
            #   Case B: 전일 대비 -2.5% 이하 급락장이면서 당일 고점 대비 -0.8%p 이상 되밀리는 하락 파동 진행 중
            #   Case C: 전일 대비 -3.5% 이하 패닉 폭락장 (야간선물 폭락 후 투매장)
            #   Case D: 장중 고점 대비 -1.8%p 이상 급투매(Intraday Flash Dump) 발생 구간
            if (
                (flu_rt <= -1.50 and intraday_chg_pct < -0.20)
                or (flu_rt <= -2.50 and drawdown_from_high_pct >= 0.80)
                or (flu_rt <= -3.50)
                or (drawdown_from_high_pct >= 1.80 and flu_rt < 0.0)
            ):
                regime = "CRASH_LOCK"
                badge = f"🔴투매서킷브레이커({flu_rt:+.2f}%)"
                reason = f"{label} 급락/투매({flu_rt:+.2f}%, 시가대비 {intraday_chg_pct:+.2f}%, 고점대비 -{drawdown_from_high_pct:.2f}%p) ➔ 신규매수 잠금"
            # 🟡 2단계 (CAUTION_DEFENSE - 하락 주의 / 대장주 초엄격 선별 방어모드):
            #   - 전일 대비 -0.8% 이하 하락 중이거나, 당일 시가 대비 -0.5% 이하 음봉 눌림, 또는 고점 대비 -1.0%p 이상 조정 구간
            elif (
                flu_rt <= -0.80
                or intraday_chg_pct <= -0.50
                or drawdown_from_high_pct >= 1.00
            ):
                regime = "CAUTION_DEFENSE"
                badge = f"🟡하락방어({flu_rt:+.2f}%)"
                reason = f"{label} 약세/주의({flu_rt:+.2f}%, 시가대비 {intraday_chg_pct:+.2f}%) ➔ 노란선 줍기 차단 & 검정점선 돌파 대장주(78점+)만 허용"
            # 🟢 1단계 (NORMAL_BULL - 선물 정상/강세장):
            else:
                regime = "NORMAL_BULL"
                badge = f"🟢정상/강세({flu_rt:+.2f}%)"
                reason = f"{label} 양호({flu_rt:+.2f}%, 시가대비 {intraday_chg_pct:+.2f}%) ➔ 정석 파동 매매(노란선 1차 ➔ 검정점선 2차)"

            return {
                'label': label,
                'flu_rt': flu_rt,
                'intraday_chg_pct': intraday_chg_pct,
                'drawdown_from_high_pct': drawdown_from_high_pct,
                'is_bull_candle': is_bull_candle,
                'regime': regime,
                'badge': badge,
                'reason': reason
            }
        except Exception as e:
            logger.debug(f"{label} 상태 조회 에러: {e}")
            return default_state

    def get_futures_market_regime(self, cache_ttl: float = 25.0) -> dict:
        """
        코스피200 선물(F-KOSPI200) 및 코스닥150 선물(F-KOSDAQ150) 실시간 시장 날씨 조회 (기본 25초 캐시)
        - 반환: {'KOSPI': {...}, 'KOSDAQ': {...}}
        """
        now_ts = time.time()
        if hasattr(self, '_futures_regime_cache') and hasattr(self, '_futures_regime_ts'):
            if (now_ts - self._futures_regime_ts) < cache_ttl and self._futures_regime_cache:
                return self._futures_regime_cache

        kospi_fut = self._parse_futures_benchmark("코스피200선물", long_code="069500", inv_code="114800")
        time.sleep(0.10)
        kosdaq_fut = self._parse_futures_benchmark("코스닥150선물", long_code="229200", inv_code="251340")

        res = {
            'KOSPI': kospi_fut,
            'KOSDAQ': kosdaq_fut,
            'updated_at': now_ts
        }
        self._futures_regime_cache = res
        self._futures_regime_ts = now_ts
        return res


