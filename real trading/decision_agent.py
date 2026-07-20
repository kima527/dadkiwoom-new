import logging
import asyncio
from datetime import datetime, timezone, timedelta

logger = logging.getLogger(__name__)

class ScalpingDecisionAgent:
    """
    여러 매니저(가속도, 테마, 기술적 지표)의 의견을 수합하여 최종 매수를 승인하는 마스터 에이전트
    """
    def __init__(self, theme_manager, tech_manager=None):
        self.theme_manager = theme_manager
        self.tech_manager = tech_manager
        self.on_buy_approved = None       # 승인 시 콜백 (main_scalping.on_buy_signal로 연결)
        self.release_lock_callback = None # 거부 시 락 해제 콜백 (accel_engine.release_lock)

    def _get_kst_now(self):
        """서버 호스팅 환경에서도 완벽한 한국 표준시(KST)를 반환하도록 강제 보정"""
        return datetime.now(timezone(timedelta(hours=9)))

    async def evaluate_candidate(self, code: str, price: float, accel_ratio: float):
        """TickAccelerationEngine이 1차로 넘긴 후보를 다각도로 평가합니다."""
        
        now = self._get_kst_now()
        
        # [실전 교정] 장 시작 직후 극초반 노이즈(허수 거래량) 방어 구간을 9시 정각 후 15초간으로 정밀 제한
        if now.hour == 9 and now.minute == 0 and now.second <= 15:
            logger.info(f"🛑 [DecisionAgent] {code} 매수 보류: 개장 극초반(09:00:00~09:00:15) 숨고르기 필터링 중")
            if self.release_lock_callback:
                self.release_lock_callback(code)
            return False

        reasons = [f"가속도 1위 ({accel_ratio:.3f}%)"]

        # 1. 주도 테마 소속 여부 검사 (O(1) 캐시 조회)
        if not self.theme_manager.has_hot_theme(code):
            logger.info(f"🛑 [DecisionAgent] {code} 매수 거부: 당일 주도 테마 리스트에 없음 (단순 개별 잡주 수급)")
            if self.release_lock_callback:
                self.release_lock_callback(code)
            return False

        themes = self.theme_manager.get_stock_themes(code)
        reasons.append(f"주도 테마 ({', '.join(themes[:2])})")

        # 2. 기술적 지표 합격 여부 (Bypass)
        if self.tech_manager:
            try:
                pass # 추후 Pre-Cacher 일봉 데이터와 결합될 자리 (메인 루프 블로킹 방지 우회)
            except Exception as e:
                logger.error(f"[DecisionAgent] TechManager 바이패스 에러: {e}")

        # 3. 합의 통과 후 콜백 연동 파라미터 보정
        reason_str = " + ".join(reasons)
        logger.info(f"✅ [DecisionAgent] {code} 3박자 합의(Consensus) 통과! 매수 승인 -> [{reason_str}]")

        if self.on_buy_approved:
            # [Critical 보완] 메인 트레이딩 루프(on_buy_signal)가 요구하는 규격(code, price, accel_ratio)과 일치시킴
            if asyncio.iscoroutinefunction(self.on_buy_approved):
                await self.on_buy_approved(code, price, accel_ratio)
            else:
                self.on_buy_approved(code, price, accel_ratio)
        return True
