"""
overnight_market_radar.py - 글로벌 선행 지수 & 야간선물 연동 시장 기상도 레이더

[기능 및 역할]
1. 밤사이 마감된 글로벌 3대 선행 지표 자동 수집:
   - 미국 필라델피아 반도체 지수 (SOX)
   - 미국 나스닥 종합 지수 (IXIC)
   - 한국 코스피200 선물 / 야간선물 (KRX / Daum / Naver)
2. 5단계 시장 연쇄 전이 메커니즘 판정:
   - STRONG_BULL (선물/미증시 +0.5% 이상 강세): 프리마켓 갭상승 진성 주도주 선취매
   - NORMAL_BULL (보합 -0.7% ~ +0.5%): 정석 파동 매매
   - CAUTION_DEFENSE (하락 -0.7% ~ -1.5%): 불트랩 경계, 역행 대장주만 진입
   - CRASH_LOCK (폭락 -1.5% 이하): 프리마켓 신규 매수 100% 잠금 (정규장 투매 소화 대기)
3. 주도 섹터(반도체, 테크 등) 연동 가산점 산출
4. 10분 인메모리 캐싱 및 네트워크 장애 시 무중단 자동 fallback
"""

import time
import logging
from typing import Dict, Any, Optional, List
import requests

logger = logging.getLogger(__name__)

# 인메모리 캐시 (10분 TTL)
_CACHE_DATA: Optional[Dict[str, Any]] = None
_CACHE_TS: float = 0.0
_CACHE_TTL: float = 600.0  # 10분

# 반도체 및 테크 관련 대표 종목 코드 집합 (필반지수 강세 시 우선순위 가산점 부여용)
SEMICONDUCTOR_CODES = {
    '005930',  # 삼성전자
    '000660',  # SK하이닉스
    '042700',  # 한미반도체
    '281820',  # 케이씨텍
    '425040',  # 티이엠씨
    '058470',  # 리노공업
    '039030',  # 이오테크닉스
    '036540',  # 에스에프에이
    '138360',  # 앤로보틱스 (로봇/반도체자동화)
}

TECH_SOFTWARE_CODES = {
    '263860',  # 지니언스 (네트워크/보안)
    '411080',  # 샌즈랩 (AI/보안)
    '393210',  # 토마토시스템 (클라우드/SW)
    '263750',  # 펄어비스 (게임/엔터)
    '035900',  # JYP Ent. (엔터/미디어)
}

def fetch_naver_index(index_symbol: str) -> Optional[Dict[str, float]]:
    """
    네이버 모바일 증권 API를 통해 글로벌 지수 실시간/마감 등락률 조회
    (예: .SOX = 필라델피아 반도체, .IXIC = 나스닥 종합, .INX = S&P500)
    """
    url = f"https://api.stock.naver.com/index/{index_symbol}/basic"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=3.0)
        if resp.status_code == 200:
            data = resp.json()
            close_price = float(str(data.get("closePrice", "0")).replace(",", ""))
            flu_ratio = float(str(data.get("fluctuationsRatio", "0")).replace("%", "").replace(",", "").strip() or 0.0)
            return {"price": close_price, "flu_pct": flu_ratio}
    except Exception as e:
        logger.debug(f"네이버 지수 조회 실패 ({index_symbol}): {e}")
    return None

def fetch_daum_futures() -> Optional[Dict[str, float]]:
    """
    다음 금융 API를 통해 코스피200 선물(F001) 최근월물 시세 조회
    """
    url = "https://finance.daum.net/api/quotes/F001"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://finance.daum.net/domestic/futures"
    }
    try:
        resp = requests.get(url, headers=headers, timeout=3.0)
        if resp.status_code == 200:
            data = resp.json()
            trade_price = float(data.get("tradePrice", 0.0) or 0.0)
            change_rate = float(data.get("changeRate", 0.0) or 0.0) * 100.0
            return {"price": trade_price, "flu_pct": change_rate}
    except Exception as e:
        logger.debug(f"다음 선물 지수 조회 실패: {e}")
    return None

def get_overnight_market_radar(force_refresh: bool = False) -> Dict[str, Any]:
    """
    글로벌 선행 지수(SOX, IXIC) 및 야간/정규선물 지수 종합 분석 반환
    """
    global _CACHE_DATA, _CACHE_TS
    now_ts = time.time()

    if not force_refresh and _CACHE_DATA is not None and (now_ts - _CACHE_TS) < _CACHE_TTL:
        return _CACHE_DATA

    # 기본값 (통신 실패 시 정상 보합 세팅)
    sox_info = {"price": 0.0, "flu_pct": 0.0}
    ixic_info = {"price": 0.0, "flu_pct": 0.0}
    fut_info = {"price": 0.0, "flu_pct": 0.0}

    # 1. 미국 필라델피아 반도체 지수(SOX) 조회
    sox_res = fetch_naver_index(".SOX")
    if sox_res:
        sox_info = sox_res

    # 2. 미국 나스닥 종합 지수(IXIC) 조회
    ixic_res = fetch_naver_index(".IXIC")
    if ixic_res:
        ixic_info = ixic_res

    # 3. 코스피200 선물(F001) 조회 (다음 금융)
    daum_fut_res = fetch_daum_futures()
    if daum_fut_res:
        fut_info = daum_fut_res

    sox_pct = sox_info["flu_pct"]
    ixic_pct = ixic_info["flu_pct"]
    fut_pct = fut_info["flu_pct"]

    # 4. 주도 섹터(Leading Theme) 판정
    lead_themes: List[str] = []
    if sox_pct >= 1.0:
        lead_themes.append("SEMICONDUCTOR")
    if ixic_pct >= 1.0:
        lead_themes.append("TECH")

    # 5. 글로벌 & 야간선물 연쇄 전이 레짐(Regime) 판정
    # 대표 지표 가중 평균: 야간선물 45% + 필반지수 35% + 나스닥 20%
    if fut_pct != 0.0:
        combined_alpha = (fut_pct * 0.45) + (sox_pct * 0.35) + (ixic_pct * 0.20)
    else:
        combined_alpha = (sox_pct * 0.60) + (ixic_pct * 0.40)

    combined_alpha = round(combined_alpha, 2)

    # 4단계 레짐 확정
    if combined_alpha <= -1.50 or fut_pct <= -1.50 or sox_pct <= -2.50:
        regime = "CRASH_LOCK"
        badge = f"🔴글로벌투매잠금({combined_alpha:+.2f}%)"
        reason = (
            f"글로벌 증시 및 야간선물 급락 (선물 {fut_pct:+.2f}%, 필반 {sox_pct:+.2f}%, 나스닥 {ixic_pct:+.2f}%) "
            f"➔ 프리마켓 신규매수 100% 잠금 (09:00 개장 투매 소화 후 진입)"
        )
    elif combined_alpha <= -0.70 or fut_pct <= -0.70:
        regime = "CAUTION_DEFENSE"
        badge = f"🟡글로벌하락방어({combined_alpha:+.2f}%)"
        reason = (
            f"글로벌 증시 및 야간선물 약세 (선물 {fut_pct:+.2f}%, 필반 {sox_pct:+.2f}%) "
            f"➔ 불트랩 경계, 노란선 줍기 차단 & 120틱 검정점선 돌파 진성 대장주(78점+)만 허용"
        )
    elif combined_alpha >= 0.50 or sox_pct >= 1.50:
        regime = "STRONG_BULL"
        badge = f"🔥글로벌강세모멘텀({combined_alpha:+.2f}%)"
        reason = (
            f"미국 필반지수({sox_pct:+.2f}%) 및 나스닥({ixic_pct:+.2f}%) 동반 상승 ➔ 야간선물({fut_pct:+.2f}%) 강세 연계, "
            f"프리마켓 갭상승 진성 주도주 적극 선취매"
        )
    else:
        regime = "NORMAL_BULL"
        badge = f"🟢글로벌정상/보합({combined_alpha:+.2f}%)"
        reason = f"글로벌 및 선물 지수 정상 보합 흐름 ({combined_alpha:+.2f}%) ➔ 정석 120틱 파동 매매 가동"

    result = {
        "sox_pct": sox_pct,
        "sox_price": sox_info["price"],
        "ixic_pct": ixic_pct,
        "ixic_price": ixic_info["price"],
        "fut_pct": fut_pct,
        "fut_price": fut_info["price"],
        "combined_alpha": combined_alpha,
        "regime": regime,
        "badge": badge,
        "lead_themes": lead_themes,
        "reason": reason,
        "updated_at": now_ts
    }

    _CACHE_DATA = result
    _CACHE_TS = now_ts
    return result

def get_stock_theme_alignment_score(code: str, radar: Optional[Dict[str, Any]] = None) -> float:
    """
    글로벌 선행 지수 주도 섹터와 종목의 일치 여부에 따른 보너스 가산점 (+0.0 ~ +5.0점)
    - 필라델피아 반도체 지수 강세 시 반도체 관련주 +5.0점
    - 나스닥 지수 강세 시 테크/SW/게임 관련주 +3.0점
    """
    if radar is None:
        radar = get_overnight_market_radar()

    clean_code = str(code).replace("_AL", "").replace("_NX", "").lstrip("A").strip().zfill(6)
    bonus = 0.0
    lead_themes = radar.get("lead_themes", [])

    if "SEMICONDUCTOR" in lead_themes and clean_code in SEMICONDUCTOR_CODES:
        bonus += 5.0
    elif "TECH" in lead_themes and clean_code in TECH_SOFTWARE_CODES:
        bonus += 3.0

    return bonus

