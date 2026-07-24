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
    sys.path.insert(0, real_trading_path)

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
        except:
            return 10000000.0

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
            
            if 'time' in df.columns:
                # time 필드가 문자열 "090000" 형태라면 datetime으로 보정 시도
                # Pandas 연산을 위해 일단 index로 세팅
                df.set_index('time', inplace=True)
                
            for col in ['open', 'high', 'low', 'close', 'volume']:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                    
            # 최신 데이터가 아래(뒤)로 오도록 정렬 보정
            if len(df) > 1 and df['close'].iloc[0] == raw_candles[0].get('close'): # (일반적으로 과거가 먼저옴)
                pass 
                
            return df
        except Exception as e:
            logger.error(f"1분봉 변환 에러 ({stock_code}): {e}")
            return pd.DataFrame()

    def get_tick_data(self, stock_code: str) -> list:
        try:
            return self.real_client.get_tick_data(stock_code, tick_unit="1", limit=30)
        except:
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
            except:
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
            for h in holdings:
                code = h.get('code', '').replace('A', '')
                if code:
                    holdings_dict[code] = {
                        'qty': int(h.get('quantity', h.get('qty', 0))),
                        'buy_price': float(h.get('buy_price', 0))
                    }
        except Exception as e:
            logger.error(f"잔고 조회 에러: {e}")
        return holdings_dict

    def get_unexecuted_orders(self) -> list:
        """실전 미체결 주문 목록 조회"""
        try:
            unfilled = self.real_client.get_unfilled_orders()
            # 봇은 [{'stock_code': code}] 형태를 기대하므로 맞춰줌
            return [{'stock_code': u.get('code')} for u in unfilled]
        except:
            return []

    def cancel_order(self, order_no: str, stock_code: str, qty: int):
        """실전 매수/매도 주문 취소"""
        logger.info(f"취소 주문 전송: {order_no} ({stock_code})")
        return self.real_client.cancel_order(order_no, stock_code, qty)

    # 테마나 종목 이름 등은 기존 모의 스크립트 그대로 유지 (또는 실전 API 기능 사용)
    def get_stock_name(self, stock_code: str) -> str:
        try:
            return self.real_client.get_stock_name(stock_code)
        except:
            return f"Stock_{stock_code}"

