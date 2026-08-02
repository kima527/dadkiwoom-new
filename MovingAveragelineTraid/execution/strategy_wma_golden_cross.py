"""
WMA 골든크로스 기반 지지-돌파 매매 전략 (strategy_wma_golden_cross.py)
===========================================================================

전략 요약:
  1. 5일 가중이동평균(WMA5)이 20일 가중이동평균(WMA20)을 상향 돌파 (Golden Cross)
  2. 교차 시점의 WMA5 값 → Signal_1 (지지선)
  3. 교차 시점의 당일 고가  → Signal_2 (저항선)
  4. 매수 타점: 주가가 Signal_1 부근에서 지지받은 뒤 Signal_2를 종가로 상향 돌파

사용 방법:
  - 단일 종목 분석: analyze_single(df)  →  DataFrame 반환
  - 종목 스크리닝:   screen_stocks({code: df, ...})  →  매수 신호 종목 리스트

참고:
  - 이 모듈은 독립적으로 동작하며, 기존 strategy_sma.py / strategy_sma_breakout.py 와
    결합 없이 단독 사용이 가능합니다.
  - 나중에 기존 로직과 결합할 때는 이 모듈의 analyze_single() 결과를 조건으로 추가하면 됩니다.
"""

import pandas as pd
import numpy as np
import logging
from dataclasses import dataclass, field
from typing import Optional

from utils import TradeState, calculate_trade_intensity

logger = logging.getLogger(__name__)


# ===========================================================================
# 설정 파라미터
# ===========================================================================
@dataclass
class WMAGoldenCrossParams:
    """전략 파라미터를 한 곳에서 관리합니다. 백테스트 시 값을 바꿔가며 최적화 가능."""

    # WMA 기간
    wma_short: int = 5          # 단기 가중이동평균 기간
    wma_long: int = 20          # 장기 가중이동평균 기간

    # 지지 판단
    support_tolerance: float = 0.02   # 저가가 Signal_1 대비 몇 % 이내면 '근접'으로 볼 것인가
    support_lookback: int = 5         # 최근 몇 봉 이내에 지지가 있었는지 확인할 기간
    support_break_tolerance: float = 0.005  # 종가가 Signal_1을 살짝 깨도 허용할 오차 (0.5%)

    # 최소 데이터 요구량
    min_bars: int = 30          # 최소 봉 수 (wma_long + 여유분)


# ===========================================================================
# WMA (가중이동평균) 계산
# ===========================================================================
def wma(series: pd.Series, period: int) -> pd.Series:
    """
    가중이동평균(Weighted Moving Average)을 계산합니다.

    가중치: 최근 값일수록 큰 가중치 부여
      - 1일째 가중치 = 1, 2일째 = 2, ..., n일째 = n
      - WMA = Σ(가중치 × 가격) / Σ(가중치)

    Parameters
    ----------
    series : pd.Series
        종가 등 가격 시리즈
    period : int
        이동평균 기간

    Returns
    -------
    pd.Series
        WMA 값 (첫 period-1개는 NaN)
    """
    weights = np.arange(1, period + 1, dtype=float)
    weight_sum = weights.sum()

    return series.rolling(window=period, min_periods=period).apply(
        lambda prices: np.dot(prices, weights) / weight_sum,
        raw=True
    )


# ===========================================================================
# 핵심: 단일 종목 분석
# ===========================================================================
def analyze_single(
    df: pd.DataFrame,
    params: Optional[WMAGoldenCrossParams] = None,
) -> pd.DataFrame:
    """
    단일 종목의 일봉 데이터를 받아 WMA 골든크로스 지지→돌파 신호를 계산합니다.

    Parameters
    ----------
    df : pd.DataFrame
        최소 컬럼: 'Open', 'High', 'Low', 'Close' (또는 소문자)
        인덱스: 날짜순 정렬 (오름차순)
    params : WMAGoldenCrossParams, optional
        전략 파라미터. None이면 기본값 사용.

    Returns
    -------
    pd.DataFrame
        원본 df에 아래 컬럼이 추가된 복사본:
        - WMA5, WMA20         : 가중이동평균
        - GoldenCross         : 골든크로스 발생 여부 (bool)
        - Signal_1            : 교차 시점 WMA5 값 (지지선)
        - Signal_2            : 교차 시점 고가 (저항선)
        - Is_Supported_Bar    : 해당 봉이 '지지 봉'인지 여부
        - Support_Condition   : 최근 N봉 내 지지 이력 존재 여부
        - Buy_Signal          : Signal_2 종가 돌파 여부
        - Final_Entry         : 최종 매수 타점 (Support_Condition & Buy_Signal)
        - Sell_Target         : 정배열 구간에서 형성된 직전 고점 (매도가/목표가)
    """
    if params is None:
        params = WMAGoldenCrossParams()

    df = df.copy()

    # ------------------------------------------------------------------
    # 컬럼명 정규화: 소문자/대문자 혼용 대응
    # ------------------------------------------------------------------
    col_map = {}
    for col in df.columns:
        lower = col.lower()
        if lower == 'open':
            col_map[col] = 'Open'
        elif lower == 'high':
            col_map[col] = 'High'
        elif lower == 'low':
            col_map[col] = 'Low'
        elif lower == 'close':
            col_map[col] = 'Close'
        elif lower == 'volume':
            col_map[col] = 'Volume'
    df.rename(columns=col_map, inplace=True)

    # 필수 컬럼 확인
    required = {'Open', 'High', 'Low', 'Close'}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"필수 컬럼이 누락되었습니다: {missing}")

    if len(df) < params.min_bars:
        logger.warning(
            f"데이터 부족: {len(df)}행 (최소 {params.min_bars}행 필요). "
            f"신호가 부정확할 수 있습니다."
        )

    # ==================================================================
    # Step 1: 가중이동평균선 계산
    # ==================================================================
    df['WMA5'] = wma(df['Close'], params.wma_short)
    df['WMA20'] = wma(df['Close'], params.wma_long)

    # ==================================================================
    # Step 2: 골든크로스 감지
    #   - 오늘: WMA5 > WMA20
    #   - 어제: WMA5 <= WMA20
    #   → 어제까지는 단기선이 장기선 이하였는데 오늘 상향 돌파
    # ==================================================================
    df['GoldenCross'] = (
        (df['WMA5'] > df['WMA20']) &
        (df['WMA5'].shift(1) <= df['WMA20'].shift(1))
    )

    # ==================================================================
    # Step 3: ValueWhen(1, 조건, M5) & ValueWhen(1, 조건, H) 구현
    #
    # 핵심: shift(1) 처리
    #   - 골든크로스가 발생한 당일에는 아직 '확정'이 아닐 수 있으므로,
    #     지지/저항선은 '다음 봉부터' 적용하는 것이 안전합니다.
    #   - 이렇게 해야 미래참조(look-ahead bias) 없이 백테스트가 가능합니다.
    # ==================================================================
    df['_Raw_Signal_1'] = np.where(df['GoldenCross'], df['WMA5'], np.nan)
    df['_Raw_Signal_2'] = np.where(df['GoldenCross'], df['High'], np.nan)

    # ffill: 골든크로스 이후 다음 골든크로스까지 같은 값 유지
    # shift(1): 교차 발생 다음 봉부터 적용
    df['Signal_1'] = df['_Raw_Signal_1'].ffill().shift(1)
    df['Signal_2'] = df['_Raw_Signal_2'].ffill().shift(1)

    # 임시 컬럼 정리
    df.drop(columns=['_Raw_Signal_1', '_Raw_Signal_2'], inplace=True)

    # ==================================================================
    # Step 4: 지지 확인 로직 (조건 A)
    #
    # '지지 봉(Is_Supported_Bar)' 정의:
    #   조건 ①: 저가(Low)가 Signal_1의 tolerance% 이내로 근접했음
    #            → 주가가 지지선까지 내려왔다는 뜻
    #   조건 ②: 종가(Close)가 Signal_1 이상을 유지하고 있음
    #            (또는 break_tolerance 이내로만 살짝 깼을 때도 허용)
    #            → 지지선에서 반등했다는 뜻
    #
    # Support_Condition:
    #   최근 lookback 봉(오늘 제외) 중 지지 봉이 1회 이상 존재했는가?
    # ==================================================================
    # Signal_1이 NaN인 구간(골든크로스 발생 전)은 지지 판단 불가
    has_signal = df['Signal_1'].notna()

    # 조건 ①: 저가가 지지선 근처까지 내려옴
    df['_Near_Support'] = has_signal & (
        df['Low'] <= df['Signal_1'] * (1 + params.support_tolerance)
    )

    # 조건 ②: 종가가 지지선을 깨지 않음 (약간의 허용 오차 포함)
    df['_Supported'] = has_signal & (
        df['Close'] >= df['Signal_1'] * (1 - params.support_break_tolerance)
    )

    # 지지 봉 = 조건 ① AND 조건 ②
    df['Is_Supported_Bar'] = df['_Near_Support'] & df['_Supported']

    # 최근 lookback 봉(오늘 제외) 동안 지지 이력 확인
    # shift(1): 오늘 봉은 제외하고 과거 봉만 대상으로 함 (미래참조 방지)
    df['Support_Condition'] = (
        df['Is_Supported_Bar']
        .shift(1)
        .rolling(window=params.support_lookback, min_periods=1)
        .max()
        .fillna(0)
        .astype(bool)
    )

    # 임시 컬럼 정리
    df.drop(columns=['_Near_Support', '_Supported'], inplace=True)

    # ==================================================================
    # Step 5: Signal_2(고가 저항선) 돌파 포착 (조건 B)
    #
    # CrossUp 조건:
    #   - 오늘 종가 > Signal_2  (돌파)
    #   - 어제 종가 <= Signal_2 (어제까지는 아래에 있었음)
    # ==================================================================
    has_signal_2 = df['Signal_2'].notna()

    df['Buy_Signal'] = has_signal_2 & (
        (df['Close'] > df['Signal_2']) &
        (df['Close'].shift(1) <= df['Signal_2']) &
        (df['Close'] >= df['Open'])  # 돌파 캔들은 양봉(또는 보합)이어야 함 (갭상승 후 쏟아지는 음봉 휩쏘 방지)
    )

    # ==================================================================
    # Step 5.5: 매도가(K) 산출 로직 (정배열 전고점)
    #
    # a=avg(c,5); b=avg(c,20); d=avg(c,60);
    # K=valuewhen(1, a>b && b>d && a>d, C);
    # valuewhen(1, K(2)<K(1) && K(1)>K, K(1))
    # ==================================================================
    df['SMA5'] = df['Close'].rolling(window=5, min_periods=1).mean()
    df['SMA20'] = df['Close'].rolling(window=20, min_periods=1).mean()
    df['SMA60'] = df['Close'].rolling(window=60, min_periods=1).mean()

    # 정배열 판단 (SMA5 > SMA20 > SMA60)
    is_aligned = (df['SMA5'] > df['SMA20']) & (df['SMA20'] > df['SMA60'])
    
    # K: 정배열일 때의 종가. 정배열이 아닐 때는 이전 K값 유지 (ffill)
    # [수정] 종가(Close) 대신 고가(High)의 3일 이동평균을 사용하여 자잘한 음봉 휩쏘를 제거
    df['Smooth_High'] = df['High'].rolling(window=3, min_periods=1).mean()
    df['_K_Raw'] = np.where(is_aligned, df['Smooth_High'], np.nan)
    df['K'] = df['_K_Raw'].ffill()

    # K(1), K(2) - 과거 K값
    k_shift1 = df['K'].shift(1)
    k_shift2 = df['K'].shift(2)

    # 고점(산 모양) 판단: K(2) < K(1) & K(1) > K
    is_peak = (k_shift2 < k_shift1) & (k_shift1 > df['K'])

    # 고점이 확인되었을 때의 고점 가격 K(1)을 목표가로 설정
    df['_Sell_Target_Raw'] = np.where(is_peak, k_shift1, np.nan)
    df['Sell_Target'] = df['_Sell_Target_Raw'].ffill()

    # 임시 컬럼 삭제
    df.drop(columns=['SMA5', 'SMA20', 'SMA60', 'Smooth_High', '_K_Raw', 'K', '_Sell_Target_Raw'], inplace=True)

    # ==================================================================
    # Step 6: 최종 매수 타점 결합
    #
    # Final_Entry = Support_Condition AND Buy_Signal
    #   → 과거 N봉 내 지지 이력이 있고 + 오늘 종가로 저항선 돌파
    # ==================================================================
    df['Final_Entry'] = df['Support_Condition'] & df['Buy_Signal']

    return df


# ===========================================================================
# 종목 스크리닝: 여러 종목을 한번에 분석하여 매수 신호 종목 추출
# ===========================================================================
@dataclass
class ScreenResult:
    """스크리닝 결과 한 건"""
    code: str                       # 종목 코드
    name: str = ""                  # 종목명
    signal_date: str = ""           # 매수 신호 발생일
    close_price: float = 0.0        # 매수 신호일 종가
    signal_1: float = 0.0           # 지지선 (골든크로스 시점 WMA5)
    signal_2: float = 0.0           # 저항선 (골든크로스 시점 고가)
    golden_cross_date: str = ""     # 최근 골든크로스 발생일


def screen_stocks(
    stock_data: dict[str, pd.DataFrame],
    params: Optional[WMAGoldenCrossParams] = None,
    stock_names: Optional[dict[str, str]] = None,
) -> list[ScreenResult]:
    """
    여러 종목의 일봉 데이터를 분석하여 최종 매수 신호(Final_Entry)가
    '오늘(마지막 봉)'에 발생한 종목만 추출합니다.

    Parameters
    ----------
    stock_data : dict[str, pd.DataFrame]
        {종목코드: 일봉DataFrame} 매핑
    params : WMAGoldenCrossParams, optional
        전략 파라미터
    stock_names : dict[str, str], optional
        {종목코드: 종목명} 매핑 (로그 출력용)

    Returns
    -------
    list[ScreenResult]
        매수 신호가 발생한 종목 리스트
    """
    if params is None:
        params = WMAGoldenCrossParams()
    if stock_names is None:
        stock_names = {}

    results: list[ScreenResult] = []
    errors: list[str] = []

    for code, df in stock_data.items():
        name = stock_names.get(code, code)
        try:
            if df.empty or len(df) < params.min_bars:
                logger.debug(f"[{name}] 데이터 부족으로 스킵 ({len(df)}행)")
                continue

            analyzed = analyze_single(df, params)
            latest = analyzed.iloc[-1]

            if latest.get('Final_Entry', False):
                # 최근 골든크로스 발생일 찾기
                gc_dates = analyzed[analyzed['GoldenCross']].index
                gc_date_str = str(gc_dates[-1]) if len(gc_dates) > 0 else "N/A"

                # 신호일(오늘)의 날짜
                signal_date_str = str(analyzed.index[-1])

                result = ScreenResult(
                    code=code,
                    name=name,
                    signal_date=signal_date_str,
                    close_price=float(latest['Close']),
                    signal_1=float(latest['Signal_1']) if pd.notna(latest['Signal_1']) else 0.0,
                    signal_2=float(latest['Signal_2']) if pd.notna(latest['Signal_2']) else 0.0,
                    golden_cross_date=gc_date_str,
                )
                results.append(result)

                logger.info(
                    f"✅ [{name}({code})] 매수 신호 발생! "
                    f"종가={result.close_price:,.0f} "
                    f"지지선={result.signal_1:,.0f} "
                    f"저항선={result.signal_2:,.0f} "
                    f"골든크로스일={gc_date_str}"
                )

        except Exception as e:
            errors.append(f"[{name}({code})] {e}")
            logger.error(f"❌ [{name}({code})] 분석 실패: {e}")

    logger.info(
        f"📊 스크리닝 완료: {len(stock_data)}종목 분석 → "
        f"{len(results)}종목 매수 신호 발생, {len(errors)}종목 에러"
    )

    return results


# ===========================================================================
# 1단계 스크리닝: 골든크로스 발생 종목만 추출
# ===========================================================================
def screen_golden_cross_only(
    stock_data: dict[str, pd.DataFrame],
    params: Optional[WMAGoldenCrossParams] = None,
    stock_names: Optional[dict[str, str]] = None,
    lookback_days: int = 5,
) -> list[ScreenResult]:
    """
    '최근 N일 이내에 골든크로스가 발생한 종목'만 추출합니다.
    (아직 지지→돌파까지는 완성되지 않은, 1단계 후보군)

    Parameters
    ----------
    stock_data : dict[str, pd.DataFrame]
        {종목코드: 일봉DataFrame} 매핑
    lookback_days : int
        최근 며칠 이내의 골든크로스를 대상으로 할 것인지

    Returns
    -------
    list[ScreenResult]
        골든크로스가 발생한 종목 리스트
    """
    if params is None:
        params = WMAGoldenCrossParams()
    if stock_names is None:
        stock_names = {}

    results: list[ScreenResult] = []

    for code, df in stock_data.items():
        name = stock_names.get(code, code)
        try:
            if df.empty or len(df) < params.min_bars:
                continue

            analyzed = analyze_single(df, params)

            # 최근 N일 범위 내에서 골든크로스 발생 여부 확인
            recent = analyzed.tail(lookback_days)
            gc_bars = recent[recent['GoldenCross']]

            if not gc_bars.empty:
                gc_row = gc_bars.iloc[-1]  # 가장 최근 골든크로스
                gc_date_str = str(gc_bars.index[-1])
                latest = analyzed.iloc[-1]

                result = ScreenResult(
                    code=code,
                    name=name,
                    signal_date=gc_date_str,
                    close_price=float(gc_row['Close']),
                    signal_1=float(gc_row['WMA5']),       # 교차 시점 WMA5
                    signal_2=float(gc_row['High']),        # 교차 시점 고가
                    golden_cross_date=gc_date_str,
                )
                results.append(result)

                logger.info(
                    f"🔔 [{name}({code})] 골든크로스 발생! "
                    f"날짜={gc_date_str} "
                    f"교차가격={result.signal_1:,.0f} "
                    f"당일고가={result.signal_2:,.0f}"
                )

        except Exception as e:
            logger.error(f"❌ [{name}({code})] 분석 실패: {e}")

    logger.info(
        f"📊 1단계 스크리닝 완료: {len(stock_data)}종목 → "
        f"{len(results)}종목 골든크로스 감지 (최근 {lookback_days}일)"
    )

    return results


# ===========================================================================
# 봇 연동을 위한 인터페이스 함수
# ===========================================================================
def calculate_wma_breakout_signals(
    df: pd.DataFrame,
    state: TradeState,
    hold_buy_price: float = 0.0,
    tick_data: list | None = None,
) -> dict:
    """
    trading_bot.py 에서 호출하는 인터페이스 함수입니다.
    """
    if state.trade_ended or df.empty:
        return {"buy": False, "sell": False}

    # 파라미터 최적화 (실전 15분봉용)
    params = WMAGoldenCrossParams(
        wma_short=5,
        wma_long=20,
        support_tolerance=0.03,
        support_lookback=7,
        support_break_tolerance=0.01
    )

    analyzed = analyze_single(df, params)
    latest = analyzed.iloc[-1]
    close_price = float(latest['Close'])

    if not state.is_holding:
        # [신규 매수]
        if latest.get('Final_Entry', False):
            # 체결 강도 필터
            intensity = calculate_trade_intensity(tick_data or [])
            if intensity['is_strong']:
                reason_parts = [
                    f"WMA 골든크로스 지지돌파(지지={latest['Signal_1']:,.0f}, 저항={latest['Signal_2']:,.0f})",
                    f"체결강도 {intensity['ratio']}배"
                ]
                
                # 상태 객체에 동적으로 매도가/손절가 저장
                target = float(latest['Sell_Target']) if pd.notna(latest['Sell_Target']) else 0.0
                state.sell_target = target if target > close_price else close_price * 1.10 # 산출 안되면 10% 디폴트
                state.stop_loss = float(latest['Signal_1']) * 0.98 if pd.notna(latest['Signal_1']) else close_price * 0.98
                
                return {
                    "buy": True,
                    "buy_reason": " + ".join(reason_parts),
                    "price": close_price,
                    "is_reentry": False
                }
    else:
        # [매도/청산]
        # ★ 봇 재시작 대비: state에 sell_target/stop_loss가 없으면 현재 데이터로 재산출
        if not hasattr(state, 'sell_target') or state.sell_target <= 0:
            target = float(latest['Sell_Target']) if pd.notna(latest.get('Sell_Target')) else 0.0
            state.sell_target = target if target > close_price else close_price * 1.10
            logger.info(f"[재산출] 목표가(sell_target)={state.sell_target:,.0f}")
        if not hasattr(state, 'stop_loss') or state.stop_loss <= 0:
            state.stop_loss = float(latest['Signal_1']) * 0.98 if pd.notna(latest.get('Signal_1')) else close_price * 0.95
            logger.info(f"[재산출] 손절가(stop_loss)={state.stop_loss:,.0f}")
        
        # 1. 목표가 도달 (전량 익절)
        if state.sell_target > 0 and close_price >= state.sell_target:
            return {
                "sell": True,
                "sell_reason": f"정배열 전고점 목표가({state.sell_target:,.0f}) 도달 전량 익절",
                "price": close_price
            }
        
        # 2. 손절선 이탈
        if close_price <= state.stop_loss:
            return {
                "sell": True,
                "sell_reason": f"지지선 기반 손절가({state.stop_loss:,.0f}) 하향 이탈",
                "price": close_price
            }
            
        # 3. 트레일링 스탑 (수익 3% 이상일 때 WMA20 이탈 시)
        if hold_buy_price > 0 and (close_price - hold_buy_price) / hold_buy_price >= 0.03:
            wma20 = float(latest['WMA20'])
            if close_price < wma20:
                return {
                    "sell": True,
                    "sell_reason": f"수익권(3%이상) 후 WMA20({wma20:,.0f}) 이탈 트레일링 익절",
                    "price": close_price
                }

    return {"buy": False, "sell": False}

# ===========================================================================
# 디버그/시각화 헬퍼
# ===========================================================================
def get_signal_summary(df: pd.DataFrame) -> pd.DataFrame:
    """
    analyze_single() 결과에서 주요 신호 컬럼만 추출하여 보기 좋게 정리합니다.
    디버그나 로그 출력용.
    """
    cols = [
        'Close', 'High', 'Low',
        'WMA5', 'WMA20',
        'GoldenCross',
        'Signal_1', 'Signal_2',
        'Is_Supported_Bar', 'Support_Condition',
        'Buy_Signal', 'Final_Entry', 'Sell_Target'
    ]
    available = [c for c in cols if c in df.columns]
    summary = df[available].copy()

    # 숫자 컬럼은 소수점 정리
    for col in summary.select_dtypes(include=[np.number]).columns:
        summary[col] = summary[col].round(2)

    return summary


# ===========================================================================
# 메인: 단독 실행 시 테스트
# ===========================================================================
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s"
    )

    # ----- 테스트용 시뮬레이션 데이터 생성 -----
    np.random.seed(42)
    n_days = 60
    dates = pd.bdate_range(end="2026-08-01", periods=n_days)

    # 가격 시뮬레이션: 상승 → 골든크로스 → 눌림목 → 재돌파 패턴
    base_prices = []
    price = 10000
    for i in range(n_days):
        if i < 20:
            # 초기 하락/횡보
            price += np.random.randint(-100, 80)
        elif i < 30:
            # 상승 추세 (골든크로스 유도)
            price += np.random.randint(50, 200)
        elif i < 40:
            # 눌림목 (조정)
            price += np.random.randint(-150, 50)
        else:
            # 재상승 (돌파)
            price += np.random.randint(0, 250)
        price = max(price, 5000)  # 최소 가격 보장
        base_prices.append(price)

    closes = np.array(base_prices, dtype=float)
    highs = closes + np.random.randint(50, 300, size=n_days)
    lows = closes - np.random.randint(50, 300, size=n_days)
    opens = closes + np.random.randint(-150, 150, size=n_days)

    test_df = pd.DataFrame({
        'Open': opens,
        'High': highs,
        'Low': lows,
        'Close': closes,
        'Volume': np.random.randint(10000, 500000, size=n_days),
    }, index=dates)

    # ----- 분석 실행 -----
    logger.info("=" * 60)
    logger.info("WMA 골든크로스 전략 테스트 실행")
    logger.info("=" * 60)

    result_df = analyze_single(test_df)
    summary = get_signal_summary(result_df)

    # 골든크로스 발생일 출력
    gc_days = result_df[result_df['GoldenCross']]
    if not gc_days.empty:
        logger.info(f"\n🔵 골든크로스 발생일:")
        for idx, row in gc_days.iterrows():
            logger.info(
                f"  {idx.strftime('%Y-%m-%d')} | "
                f"WMA5={row['WMA5']:,.0f} WMA20={row['WMA20']:,.0f} "
                f"→ Signal_1(지지)={row['WMA5']:,.0f}, Signal_2(저항)={row['High']:,.0f}"
            )

    # 지지 봉 출력
    sup_days = result_df[result_df['Is_Supported_Bar']]
    if not sup_days.empty:
        logger.info(f"\n🟡 지지 봉:")
        for idx, row in sup_days.iterrows():
            logger.info(
                f"  {idx.strftime('%Y-%m-%d')} | "
                f"Low={row['Low']:,.0f} ≈ Signal_1={row['Signal_1']:,.0f} "
                f"& Close={row['Close']:,.0f} >= Signal_1"
            )

    # 최종 매수 신호 출력
    entries = result_df[result_df['Final_Entry']]
    if not entries.empty:
        logger.info(f"\n🟢 최종 매수 타점 (Final_Entry):")
        for idx, row in entries.iterrows():
            logger.info(
                f"  ★ {idx.strftime('%Y-%m-%d')} | "
                f"종가={row['Close']:,.0f} > 저항선={row['Signal_2']:,.0f} 돌파! "
                f"(지지선={row['Signal_1']:,.0f}에서 지지 확인 후)"
            )
    else:
        logger.info("\n⚪ 최종 매수 신호 없음 (시뮬레이션 데이터에서는 발생하지 않을 수 있습니다)")

    # 최근 5일 요약 출력
    logger.info(f"\n📋 최근 5일 신호 요약:")
    print(summary.tail(5).to_string())

    # ----- 스크리닝 테스트 -----
    logger.info("\n" + "=" * 60)
    logger.info("종목 스크리닝 테스트")
    logger.info("=" * 60)

    # 여러 종목 시뮬레이션
    test_stocks = {
        "005930": test_df.copy(),  # 삼성전자 (테스트)
        "000660": test_df.copy(),  # SK하이닉스 (테스트)
    }
    test_names = {"005930": "삼성전자", "000660": "SK하이닉스"}

    # 2단계: 최종 매수 신호 스크리닝
    final_picks = screen_stocks(test_stocks, stock_names=test_names)
    for pick in final_picks:
        logger.info(
            f"  → {pick.name}({pick.code}) 매수! "
            f"종가={pick.close_price:,.0f}"
        )

    # 1단계: 골든크로스 후보군 스크리닝
    gc_picks = screen_golden_cross_only(
        test_stocks, stock_names=test_names, lookback_days=10
    )
    for pick in gc_picks:
        logger.info(
            f"  → {pick.name}({pick.code}) 골든크로스 감지! "
            f"교차가격={pick.signal_1:,.0f}"
        )
