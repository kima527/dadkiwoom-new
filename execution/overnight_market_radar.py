"""
overnight_market_radar.py - 글로벌 선행 지수 & 야간선물 2612 (코스피200·코스닥150) 연동 시장 기상도 레이더

[기능 및 역할]
1. 밤사이 마감된 글로벌 선행 지표 및 야간선물 2612 월물 자동 수집:
   - 코스피200 선물 2612 (2026년 12월 만기 최근월물 / 야간선물)
   - 코스닥150선물 2612 (2026년 12월 만기 최근월물 / 야간선물)
   - 미국 필라델피아 반도체 지수 (SOX)
   - 미국 나스닥 종합 지수 (IXIC)
2. 코스피 vs 코스닥 1:1 분리 시장 레짐(Regime) 판정:
   - 코스피 종목 ➔ 코스피200 선물 2612 & 필반지수(SOX) 매칭
   - 코스닥 종목 ➔ 코스닥150선물 2612 & 나스닥(IXIC) 매칭
3. 4단계 시장 날씨 판정:
   - STRONG_BULL (선물 +0.5% 이상 강세): 프리마켓 갭상승 진성 주도주 선취매
   - NORMAL_BULL (보합 -0.7% ~ +0.5%): 정석 120틱 파동 매매
   - CAUTION_DEFENSE (하락 -0.7% ~ -1.5%): 불트랩 경계, 역행 대장주만 진입
   - CRASH_LOCK (폭락 -1.5% 이하): 프리마켓 신규 매수 100% 잠금 (정규장 투매 소화 대기)
4. 주도 섹터(반도체, 테크/SW 등) 우선순위 가산점 부여
5. 10분 인메모리 캐싱 및 무중단 fallback
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

def fetch_kospi200_futures_2612() -> Dict[str, Any]:
    """
    👑 [증권플러스 / KRX 기준] '코스피200 선물 2612' (2026년 12월 만기 최근월물) 야간/주간 시세 조회
    - 단축코드: A016C / 101VC000 / F001 / 2612
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://finance.daum.net/domestic/futures"
    }
    # 1. 다음 금융 코스피200 선물 최근월물 (F001 / 101VC000)
    endpoints = [
        "https://finance.daum.net/api/quotes/101VC000",
        "https://finance.daum.net/api/quotes/F001"
    ]
    for url in endpoints:
        try:
            resp = requests.get(url, headers=headers, timeout=2.5)
            if resp.status_code == 200:
                data = resp.json()
                trade_price = float(data.get("tradePrice", 0.0) or 0.0)
                change_rate = float(data.get("changeRate", 0.0) or 0.0) * 100.0
                if trade_price > 0:
                    return {
                        "name": "코스피200 선물 2612",
                        "price": trade_price,
                        "flu_pct": round(change_rate, 2),
                        "source": "Daum/증권플러스연동"
                    }
        except Exception:
            continue

    # 2. Naver 코스피200 파생/지수 fallback
    n_res = fetch_naver_index("KOSPI200")
    if n_res and n_res.get("price", 0) > 0:
        return {
            "name": "코스피200 선물 2612",
            "price": n_res["price"],
            "flu_pct": n_res["flu_pct"],
            "source": "NaverIndexFallback"
        }

    return {"name": "코스피200 선물 2612", "price": 0.0, "flu_pct": 0.0, "source": "DEFAULT"}

def fetch_kosdaq150_futures_2612() -> Dict[str, Any]:
    """
    👑 [증권플러스 / KRX 기준] '코스닥150선물 2612' (2026년 12월 만기 최근월물) 야간/주간 시세 조회
    - 단축코드: 106VC000 / KSFA001 / 2612
    """
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://finance.daum.net/domestic/futures"
    }
    # 1. 다음 금융 코스닥150선물 최근월물 엔드포인트
    endpoints = [
        "https://finance.daum.net/api/quotes/106VC000",
        "https://finance.daum.net/api/quotes/106V12"
    ]
    for url in endpoints:
        try:
            resp = requests.get(url, headers=headers, timeout=2.5)
            if resp.status_code == 200:
                data = resp.json()
                trade_price = float(data.get("tradePrice", 0.0) or 0.0)
                change_rate = float(data.get("changeRate", 0.0) or 0.0) * 100.0
                if trade_price > 0:
                    return {
                        "name": "코스닥150선물 2612",
                        "price": trade_price,
                        "flu_pct": round(change_rate, 2),
                        "source": "Daum/증권플러스연동"
                    }
        except Exception:
            continue

    # 2. Naver 코스닥150 파생/지수 fallback
    n_res = fetch_naver_index("KOSDAQ150")
    if n_res and n_res.get("price", 0) > 0:
        return {
            "name": "코스닥150선물 2612",
            "price": n_res["price"],
            "flu_pct": n_res["flu_pct"],
            "source": "NaverIndexFallback"
        }

    return {"name": "코스닥150선물 2612", "price": 0.0, "flu_pct": 0.0, "source": "DEFAULT"}

def _calc_regime_and_badge(label: str, flu_pct: float, global_pct: float) -> tuple[str, str, str]:
    """등락률과 글로벌 보조 지표를 바탕으로 4단계 레짐 및 뱃지 판정"""
    combined = round((flu_pct * 0.70) + (global_pct * 0.30), 2)
    disp_pct = flu_pct if flu_pct != 0.0 else combined
    if flu_pct <= -1.50 or combined <= -1.50:
        regime = "CRASH_LOCK"
        badge = f"🔴폭락잠금({disp_pct:+.2f}%)"
        reason = f"{label} 급락({disp_pct:+.2f}%) ➔ 신규매수 100% 잠금 (09:00 투매 소화 대기)"
    elif flu_pct <= -0.70 or combined <= -0.70:
        regime = "CAUTION_DEFENSE"
        badge = f"🟡하락방어({disp_pct:+.2f}%)"
        reason = f"{label} 약세({disp_pct:+.2f}%) ➔ 불트랩 경계, 검정점선 돌파 대장주(78점+)만 허용"
    elif flu_pct >= 0.50 or combined >= 0.50:
        regime = "STRONG_BULL"
        badge = f"🔥강세모멘텀({disp_pct:+.2f}%)"
        reason = f"{label} 강세({disp_pct:+.2f}%) ➔ 프리마켓 갭상승 진성 주도주 적극 선취매"
    else:
        regime = "NORMAL_BULL"
        badge = f"🟢정상/보합({disp_pct:+.2f}%)"
        reason = f"{label} 정상 보합({disp_pct:+.2f}%) ➔ 정석 120틱 파동 매매"
    return regime, badge, reason

def get_overnight_market_radar(force_refresh: bool = False) -> Dict[str, Any]:
    """
    👑 [증권플러스 2612 선물 완전 연동]
    코스피200 선물 2612 & 코스닥150선물 2612 + 미국 필반/나스닥 통합 레이더 반환
    """
    global _CACHE_DATA, _CACHE_TS
    now_ts = time.time()

    if not force_refresh and _CACHE_DATA is not None and (now_ts - _CACHE_TS) < _CACHE_TTL:
        return _CACHE_DATA

    # 1. 미국 필라델피아 반도체 지수(SOX) & 나스닥(IXIC)
    sox_info = fetch_naver_index(".SOX") or {"price": 0.0, "flu_pct": 0.0}
    ixic_info = fetch_naver_index(".IXIC") or {"price": 0.0, "flu_pct": 0.0}
    sox_pct = sox_info["flu_pct"]
    ixic_pct = ixic_info["flu_pct"]

    # 2. 👑 [증권플러스 기준 핵심 2612 선물 수집]
    # 1) 코스피200 선물 2612 (2026년 12월물 야간선물)
    kp_fut = fetch_kospi200_futures_2612()
    # 2) 코스닥150선물 2612 (2026년 12월물 야간선물)
    kq_fut = fetch_kosdaq150_futures_2612()

    kp_pct = kp_fut["flu_pct"]
    kq_pct = kq_fut["flu_pct"]

    # 3. 코스피 vs 코스닥 1:1 독립 레짐 판정
    kp_regime, kp_badge, kp_reason = _calc_regime_and_badge("코스피200 선물 2612", kp_pct, sox_pct)
    kq_regime, kq_badge, kq_reason = _calc_regime_and_badge("코스닥150선물 2612", kq_pct, ixic_pct)

    # 4. 주도 섹터(Leading Theme) 판정
    lead_themes: List[str] = []
    if sox_pct >= 1.0 or kp_pct >= 0.8:
        lead_themes.append("SEMICONDUCTOR")
    if ixic_pct >= 1.0 or kq_pct >= 0.8:
        lead_themes.append("TECH")

    overall_regime = "CRASH_LOCK" if ("CRASH_LOCK" in (kp_regime, kq_regime)) else (
        "STRONG_BULL" if (kp_regime == "STRONG_BULL" or kq_regime == "STRONG_BULL") else "NORMAL_BULL"
    )

    result = {
        "sox_pct": sox_pct,
        "ixic_pct": ixic_pct,
        "kospi_fut": {
            "name": "코스피200 선물 2612",
            "price": kp_fut.get("price", 0.0),
            "flu_pct": kp_pct,
            "regime": kp_regime,
            "badge": kp_badge,
            "reason": kp_reason
        },
        "kosdaq_fut": {
            "name": "코스닥150선물 2612",
            "price": kq_fut.get("price", 0.0),
            "flu_pct": kq_pct,
            "regime": kq_regime,
            "badge": kq_badge,
            "reason": kq_reason
        },
        "regimes": {
            "KOSPI": {
                "label": "코스피200 선물 2612",
                "flu_rt": kp_pct,
                "regime": kp_regime,
                "badge": kp_badge,
                "reason": kp_reason
            },
            "KOSDAQ": {
                "label": "코스닥150선물 2612",
                "flu_rt": kq_pct,
                "regime": kq_regime,
                "badge": kq_badge,
                "reason": kq_reason
            }
        },
        "lead_themes": lead_themes,
        "overall_regime": overall_regime,
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
