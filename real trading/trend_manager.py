import logging
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

class TrendManager:
    """
    종목의 거시적 추세(Trend)를 분석하는 서포터입니다.
    기본적인 이평선 정배열을 넘어, 선형회귀(Linear Regression)를 통한 모멘텀 가속도,
    수급 폭발 여부, 이격도 등을 종합적으로 스코어링하여 학습합니다.
    """
    def __init__(self, kiwoom_client):
        self.client = kiwoom_client
        self.trend_cache = {} # {code: {"is_uptrend": bool, "score": float, "reason": str}}

    def _calculate_advanced_trend(self, df: pd.DataFrame) -> tuple[float, str]:
        # 20일, 60일 이동평균선
        df['sma20'] = df['close'].rolling(window=20).mean()
        df['sma60'] = df['close'].rolling(window=60).mean()
        df['vol20'] = df['volume'].rolling(window=20).mean()
        
        df = df.dropna().copy()
        if len(df) < 10:
            return 0, "데이터 부족"
            
        latest = df.iloc[-1]
        
        # 1. 20일선 기울기 (최근 10일 선형회귀)
        y = df['sma20'].tail(10).values
        x = np.arange(len(y))
        slope, _ = np.polyfit(x, y, 1)
        normalized_slope = (slope / latest['sma20']) * 100 
        
        # 2. 거래량 수급 폭발도
        recent_vol3 = df['volume'].tail(3).mean()
        base_vol20 = latest['vol20']
        vol_ratio = recent_vol3 / base_vol20 if base_vol20 > 0 else 1.0
        
        # 3. 60일선 이격도
        gap_60 = ((latest['close'] / latest['sma60']) - 1) * 100
        
        score = 0
        reason = []
        
        # [팩터 1] 우상향 기울기
        if normalized_slope > 0:
            score += 30 + min(normalized_slope * 10, 20)
            reason.append(f"우상향(기울기:{normalized_slope:.2f}%)")
        else:
            reason.append(f"하락추세(기울기:{normalized_slope:.2f}%)")
            
        # [팩터 2] 수급
        if vol_ratio > 1.5:
            score += 20 + min((vol_ratio - 1.5) * 10, 10)
            reason.append(f"수급폭발({vol_ratio:.1f}배)")
        else:
            reason.append(f"거래량평이")
            
        # [팩터 3] 과열 방지 및 정배열
        if gap_60 > 0 and gap_60 < 20:
            score += 20
            reason.append(f"이격도양호({gap_60:.1f}%)")
        elif gap_60 >= 20:
            score -= 10
            reason.append(f"단기과열({gap_60:.1f}%)")
        else:
            reason.append("역배열이탈")
            
        return score, " + ".join(reason)

    def pre_learn(self, codes: list):
        """
        주어진 종목 리스트에 대해 일봉 차트를 조회하고 추세를 심층 학습합니다.
        """
        for code in codes:
            if code in self.trend_cache:
                continue
                
            logger.info(f"📊 [TrendManager] {code} 추세 판별을 위한 심층 데이터 사전 학습 중...")
            try:
                candles = self.client.get_daily_candles(code, last_n_days=100)
                
                if not candles or len(candles) < 60:
                    self.trend_cache[code] = {
                        "is_uptrend": False,
                        "score": 0.0,
                        "reason": "일봉 데이터 부족 (신규 상장 등 60일 미만)"
                    }
                    continue
                    
                df = pd.DataFrame(candles)
                score, reason = self._calculate_advanced_trend(df)
                
                # 합격 기준: 트렌드 스코어 40점 이상 (기울기가 우상향이거나, 역배열이어도 수급이 엄청나게 터졌을 때)
                is_uptrend = score >= 40
                
                self.trend_cache[code] = {
                    "is_uptrend": is_uptrend,
                    "score": score,
                    "reason": reason
                }
                    
                logger.info(f"✅ [TrendManager] {code} 학습 완료: 스코어 {score:.1f}점 | {reason}")
                
            except Exception as e:
                logger.error(f"[TrendManager] {code} 학습 중 에러 발생: {e}")
                self.trend_cache[code] = {
                    "is_uptrend": False,
                    "score": 0.0,
                    "reason": f"데이터 수신 에러: {e}"
                }

    def check_trend(self, code: str) -> tuple[bool, str]:
        """
        학습된 캐시를 바탕으로 추세를 판단합니다.
        """
        if code not in self.trend_cache:
            self.pre_learn([code])
            
        trend_info = self.trend_cache.get(code)
        if trend_info:
            # 점수가 포함된 구체적인 사유 반환
            full_reason = f"TrendScore:{trend_info['score']:.1f} ({trend_info['reason']})"
            return trend_info["is_uptrend"], full_reason
        else:
            return False, "추세 정보 조회 불가"

    def get_trend_score(self, code: str) -> float:
        """
        학습된 트렌드 스코어(0~100)를 반환합니다.
        """
        if code not in self.trend_cache:
            self.pre_learn([code])
            
        trend_info = self.trend_cache.get(code)
        if trend_info:
            return float(trend_info["score"])
        return 0.0
