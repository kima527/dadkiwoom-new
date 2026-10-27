import os
from dataclasses import dataclass

@dataclass
class StrategyConfig:
    # 지표 기간 설정
    TEMA_FAST: int = 5          # 기간1 (TEMA fast)
    TEMA_SLOW: int = 20         # 기간2 (TEMA slow)
    
    # 기준선 (M선) 이평 기간
    SMA_FAST: int = 5
    SMA_MID: int = 20
    SMA_SLOW: int = 60
    
    # 자금 관리
    FIRST_BUY_RATIO: float = 0.50   # 1차 매수 비중 (50%)
    SECOND_BUY_RATIO: float = 0.50  # 2차 매수 비중 (50%)
    
    # 리스크 관리
    GATE_STOP_LOSS_PCT: float = 0.015  # 관문선 하향 이탈 손절 버퍼 (-1.5%)
    MAX_REENTRY_COUNT: int = 5         # 일봉 데드크로스 전까지 최대 재매수 횟수
    
    # 수수료 및 슬리피지 (백테스트용)
    FEE_BUY: float = 0.00015           # 매수 수수료 (0.015%)
    FEE_SELL: float = 0.00215          # 매도 수수료 + 증권거래세 (0.215%)
    SLIPPAGE_PCT: float = 0.0005       # 호가 슬리피지 (0.05%)

DEFAULT_CONFIG = StrategyConfig()
