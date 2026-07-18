import logging
import indicator

logger = logging.getLogger(__name__)

class TechIndicatorManager:
    """기술적 지표 계산 및 상태 요약을 담당하는 매니저"""
    
    def __init__(self):
        pass

    def analyze_daily_technicals(self, candles: list) -> str:
        """
        주어진 일봉 캔들 리스트를 바탕으로 기술적 지표를 요약 반환합니다.
        candles: 오름차순(오래된 날짜 -> 최근 날짜) 리스트여야 함.
        """
        if not candles or len(candles) < 20:
            return "데이터 부족으로 기술적 분석 불가"
            
        try:
            # 원본 데이터 보호를 위해 복사본 생성
            candles_copy = [c.copy() for c in candles]
            closes = [c['close'] for c in candles_copy]
            
            # RSI 계산 (indicator.py 재사용)
            rsis = indicator.calculate_rsi(closes, period=14)
            current_rsi = rsis[-1]
            
            # SMA, 볼린저밴드 등 전체 지표 계산
            processed_candles = indicator.calculate_indicators_pure(candles_copy)
            latest = processed_candles[-1]
            
            sma5 = latest.get('sma5')
            sma20 = latest.get('sma20')
            bb20_upper = latest.get('bb20_upper')
            close_p = latest['close']
            
            summary_parts = []
            
            # 1. 이동평균선 상태
            if sma5 and sma20:
                if sma5 > sma20:
                    summary_parts.append("단기 이평 정배열 우상향")
                else:
                    summary_parts.append("단기 이평 혼조/조정 구간")
                    
            # 2. RSI 평가
            if current_rsi:
                if current_rsi >= 70:
                    summary_parts.append(f"RSI {current_rsi:.1f} (과매수 구간)")
                elif current_rsi <= 30:
                    summary_parts.append(f"RSI {current_rsi:.1f} (과매도 구간)")
                else:
                    summary_parts.append(f"RSI {current_rsi:.1f}")
                    
            # 3. 볼린저밴드 상단 돌파 여부
            if bb20_upper:
                if close_p >= bb20_upper:
                    summary_parts.append("볼린저밴드 상단 돌파(강한 수급)")
                else:
                    disparity = (bb20_upper - close_p) / close_p * 100
                    if disparity <= 5.0:
                        summary_parts.append("볼밴 상단 돌파 임박")
                        
            if not summary_parts:
                return "기본 지표 상태 양호"
                
            return " | ".join(summary_parts)
            
        except Exception as e:
            logger.error(f"기술적 분석 중 오류: {e}")
            return "분석 중 오류 발생"
