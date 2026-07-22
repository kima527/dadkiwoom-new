import logging
import pandas as pd
from typing import List, Dict, Any, Tuple
import indicator

logger = logging.getLogger(__name__)

class CoreTradeManager:
    """
    모든 봇의 공통 두뇌 역할을 하는 포트폴리오/의사결정 매니저입니다.
    여러 서포터(테마, 추세, 기술적 지표, 뉴스 등)의 의견을 수합하여 매수 여부를 결정하고,
    공통된 비중 관리 및 매도 로직(3-60 이평선 데드크로스, -1.5% 손절)을 수행합니다.
    """
    def __init__(self, theme_manager=None, trend_manager=None, tech_manager=None, news_manager=None, max_holdings=5, alloc_ratio=0.05):
        self.theme_manager = theme_manager
        self.trend_manager = trend_manager
        self.tech_manager = tech_manager
        self.news_manager = news_manager
        
        self.max_holdings = max_holdings
        self.alloc_ratio = alloc_ratio
        self.stop_loss_ratio = -0.015  # -1.5% 기계적 손절

    def evaluate_buy_candidate(self, code: str, price: float, base_reasons: List[str] = None, name: str = "") -> Tuple[bool, str]:
        """
        각종 서포터(테마, 추세 등)의 의견을 수합하여 최종 매수 승인 여부를 결정합니다.
        가장 중요한 서포트인 테마(Theme)와 추세(Trend)를 필수로 통과해야 합니다.
        """
        reasons = base_reasons.copy() if base_reasons else []
        
        # 0. ETF / ETN 종목 원천 차단 (이름 기반)
        if name:
            etf_keywords = ["KODEX", "TIGER", "SOL", "KBSTAR", "ACE", "ARIRANG", "HANARO", "KOSEF", "TIMEFOLIO", "ETN", "인버스", "레버리지"]
            if any(keyword in name.upper() for keyword in etf_keywords):
                logger.info(f"🛑 [CoreTradeManager] {code}({name}) 매수 거부: ETF/ETN 종목 제외")
                return False, ""
        
        # 1. 테마 담당 (Theme Supporter) 확인
        if self.theme_manager:
            if not self.theme_manager.has_hot_theme(code):
                logger.info(f"🛑 [CoreTradeManager] {code} 매수 거부: 주도 테마 리스트에 없음.")
                return False, ""
            themes = self.theme_manager.get_stock_themes(code)
            reasons.append(f"주도 테마 ({', '.join(themes[:2])})")
            
        # 2. 추세 담당 (Trend Supporter) 확인
        if self.trend_manager:
            is_uptrend, trend_reason = self.trend_manager.check_trend(code)
            if not is_uptrend:
                logger.info(f"🛑 [CoreTradeManager] {code} 매수 거부: 추세 불량 ({trend_reason})")
                return False, ""
            reasons.append(f"추세 양호 ({trend_reason})")
            
        # 3. 기타 서포터 (Tech, News) - 향후 확장 슬롯
        if self.tech_manager:
            # tech_manager.analyze_daily_technicals() 등을 활용 가능
            pass
            
        if self.news_manager:
            # news_manager.analyze_sentiment() 등을 활용 가능
            pass

        reason_str = " + ".join(reasons)
        logger.info(f"✅ [CoreTradeManager] {code} 서포터 합의 통과! 매수 승인 -> [{reason_str}]")
        return True, reason_str

    def calculate_buy_quantity(self, holdings_count: int, total_balance: float, target_price: float) -> int:
        """비중 관리 (Position Sizing)"""
        if holdings_count >= self.max_holdings:
            logger.info(f"⚠️ [CoreTradeManager] 최대 보유 종목 수({self.max_holdings}개) 도달. 추가 매수 중단.")
            return 0
            
        alloc_cash = total_balance * self.alloc_ratio
        if target_price > 0:
            qty = int(alloc_cash // target_price)
            return qty
        return 0

    def check_sell_condition(self, code: str, buy_price: float, current_price: float, candles_1m: Any, candles_15m: Any = None) -> Tuple[bool, str]:
        """
        공통 매도 판단 로직 (Dynamic Timeframe Switching)
        1. -1.5% 기계적 손절
        2. 추세 스코어가 80점 이상일 경우 15분봉 3-60 데드크로스 적용 (수익 극대화 스윙 전환)
        3. 그 외의 경우 1분봉 3-60 데드크로스 적용 (스캘핑 타점 유지)
        """
        # 1. 기계적 손절 체크 (-1.5%)
        if buy_price > 0 and current_price <= buy_price * (1 + self.stop_loss_ratio):
            return True, f"기계적 손절 (-1.5% 도달) [현재가:{current_price:,.0f}, 평단:{buy_price:,.0f}]"
            
        # 2. 다이나믹 타임프레임 스위칭
        score = 0.0
        if self.trend_manager:
            score = self.trend_manager.get_trend_score(code)
            
        if score >= 80 and candles_15m is not None and len(candles_15m) >= 60:
            target_candles = candles_15m
            timeframe_name = "15분봉(스윙 전환)"
        else:
            target_candles = candles_1m
            timeframe_name = "1분봉(스캘핑)"
            
        if target_candles is None or len(target_candles) < 60:
            return False, ""
            
        # DataFrame 지원 및 List of Dict 지원
        if isinstance(target_candles, pd.DataFrame):
            closes = target_candles['close'].tolist()
        else:
            try:
                closes = [float(c['close']) for c in target_candles]
            except Exception as e:
                logger.error(f"[CoreTradeManager] 캔들 데이터 파싱 에러: {e}")
                return False, ""
            
        sma3 = indicator.calculate_sma(closes, 3)
        sma60 = indicator.calculate_sma(closes, 60)
        
        # 마지막 캔들과 그 직전 캔들을 비교하여 데드크로스 발생 여부 확인
        if len(sma3) >= 2 and len(sma60) >= 2:
            prev_sma3 = sma3[-2]
            prev_sma60 = sma60[-2]
            curr_sma3 = sma3[-1]
            curr_sma60 = sma60[-1]
            
            if prev_sma3 is not None and prev_sma60 is not None and curr_sma3 is not None and curr_sma60 is not None:
                # 3이평이 60이평보다 위에(또는 같게) 있다가 아래로 떨어졌을 때 (Dead Cross)
                if prev_sma3 >= prev_sma60 and curr_sma3 < curr_sma60:
                    return True, f"{timeframe_name} 3-60 이평선 데드크로스(하향 이탈)"
                    
        return False, ""
