"""
watchlist_scanner.py - 통합 단타 성배 로직(60분봉 관문선/기준선 + M/3 수식선 + 일봉 상승추세) 맞춤 종목 발굴기

[핵심 역할]
지수 폭락장이나 조정장 이후 기존 보유종목들이 역배열/매물대에 갇혀 매수 타점이 부재할 때,
키움 실전 API(거래대금 상위 + 등락률 상위 + 주도 후보군)를 실시간 스캔하여
현재 `strategy.py`의 1차/2차 매수 조건에 가장 완벽히 부합하는 최정예 종목(Top 12)을 자동 발굴하고
`execution/holy_grail_watchlist.json`에 저장 및 `holdings_bot.bat`의 감시/매매 리스트에 즉시 편입시킵니다.
"""

import os
import sys
import json
import time
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional
import pandas as pd
import numpy as np

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(CURRENT_DIR)

try:
    from execution.indicators import (
        calculate_all_60m_indicators,
        calculate_daily_tema_deadcross,
        calculate_day3_m_line,
        calculate_pred_volume_ratio
    )
except ImportError:
    from indicators import (
        calculate_all_60m_indicators,
        calculate_daily_tema_deadcross,
        calculate_day3_m_line,
        calculate_pred_volume_ratio
    )

logger = logging.getLogger("ThemeGateHoldingsBot")

WATCHLIST_JSON_PATH = os.path.join(CURRENT_DIR, "holy_grail_watchlist.json")

EXCLUDE_KEYWORDS = [
    "KODEX", "TIGER", "KBSTAR", "KINDEX", "ARIRANG", "KOSEF", "HANARO",
    "ACE", "ETN", "스팩", "SOL", "인버스", "레버리지", "선물", "KOACT",
    "TIMEFOLIO", "WOORI", "히어로즈", "PLUS", "WON", "2X", "KRX", "합병",
    "RISE", "채권", "국고채", "블룸버그", "나스닥", "S&P", "배당", "리츠"
]


def _clean_code(raw_code: str) -> str:
    code = str(raw_code).strip()
    for suffix in ("_AL", "_NX"):
        code = code.replace(suffix, "")
    if code.startswith("A") and len(code) == 7:
        code = code[1:]
    return code.zfill(6) if code.isdigit() else code


def _is_excluded_name(name: str) -> bool:
    if not name:
        return False
    nm = name.strip()
    if any(kw in nm for kw in EXCLUDE_KEYWORDS):
        return True
    if nm.endswith("우") or nm.endswith("우B") or nm.endswith("우C") or "우선주" in nm:
        return True
    return False


def collect_market_candidates(api, max_candidates: int = 45) -> List[Dict[str, Any]]:
    """
    키움 실전 REST API(ka10032 거래대금 상위 + ka10027 등락률 상위)를 통해
    3일 지수 폭락 속에서도 수급과 양봉 추세를 지키는 시장 주도 후보군을 고속 수집합니다.
    """
    candidates_map: Dict[str, Dict[str, Any]] = {}

    if not api or not hasattr(api, "real_client"):
        return []

    rc = api.real_client

    # 1. 코스피("001") & 코스닥("101") 거래대금 상위 수집 (ka10032)
    for mkt in ["001", "101"]:
        try:
            res = rc.rank_api.top_trading_value_request_ka10032(
                mrkt_tp=mkt,
                mang_stk_incls="0",
                stex_tp="3"
            )
            raw_list = (res or {}).get("trde_prica_upper", [])
            for rank_idx, item in enumerate(raw_list[:60]):
                code = _clean_code(item.get("stk_cd", ""))
                name = str(item.get("stk_nm", "")).strip()
                if len(code) != 6 or not code.isdigit() or _is_excluded_name(name):
                    continue
                try:
                    cur_prc = abs(float(str(item.get("cur_prc", "0")).replace(",", "").replace("+", "").replace("-", "")))
                except ValueError:
                    cur_prc = 0.0
                try:
                    flu_rt = float(str(item.get("flu_rt", "0")).replace(",", "").replace("+", ""))
                except ValueError:
                    flu_rt = 0.0

                # 지수 폭락장 방어 필터: 당일 너무 깊게 무너진 종목(-2.5% 이하)이나 상한가 임박(+24% 초과) 과열주 제외
                if flu_rt < -2.5 or flu_rt > 24.0:
                    continue
                if cur_prc < 1500 or cur_prc > 300000:  # 동전주 및 30만원 초과 초고가 황제주(소액 계좌 분할매수 불가) 제외
                    continue

                candidates_map[code] = {
                    "code": code,
                    "name": name,
                    "price": cur_prc,
                    "flu_rt": flu_rt,
                    "pre_score": max(50 - rank_idx, 10) + (15 if flu_rt >= 1.5 else 0)
                }
        except Exception as e:
            logger.debug(f"거래대금 상위 조회 중 예외({mkt}): {e}")

    # 2. 코스피("001") & 코스닥("101") 상승 등락률 상위 수집 (ka10027)
    for mkt in ["001", "101"]:
        try:
            res = rc.rank_api.top_day_over_day_change_rate_request_ka10027(
                mrkt_tp=mkt,
                sort_tp="1",
                trde_qty_cnd="0000",
                stk_cnd="0",
                crd_cnd="0",
                updown_incls="1",
                pric_cnd="0",
                trde_prica_cnd="0",
                stex_tp="3"
            )
            raw_list = (res or {}).get("pred_pre_flu_rt_upper", [])
            for rank_idx, item in enumerate(raw_list[:60]):
                code = _clean_code(item.get("stk_cd", ""))
                name = str(item.get("stk_nm", "")).strip()
                if len(code) != 6 or not code.isdigit() or _is_excluded_name(name):
                    continue
                try:
                    cur_prc = abs(float(str(item.get("cur_prc", "0")).replace(",", "").replace("+", "").replace("-", "")))
                except ValueError:
                    cur_prc = 0.0
                try:
                    flu_rt = float(str(item.get("flu_rt", "0")).replace(",", "").replace("+", ""))
                except ValueError:
                    flu_rt = 0.0

                # 적정 상승 모멘텀 구간 (+0.5% ~ +20.0%) 및 1,500원~300,000원 적정 호가대 우대
                if not (0.5 <= flu_rt <= 20.0) or cur_prc < 1500 or cur_prc > 300000:
                    continue

                if code in candidates_map:
                    # 거래대금 상위이면서 동시에 등락률 상위인 진성 주도주 가산점 부여!
                    candidates_map[code]["pre_score"] += 40
                    if name and not candidates_map[code].get("name"):
                        candidates_map[code]["name"] = name
                else:
                    candidates_map[code] = {
                        "code": code,
                        "name": name,
                        "price": cur_prc,
                        "flu_rt": flu_rt,
                        "pre_score": max(35 - rank_idx // 2, 5)
                    }
        except Exception as e:
            logger.debug(f"등락률 상위 조회 중 예외({mkt}): {e}")

    # 사전 점수(거래대금 + 상승률 교집합 우선) 순으로 정렬하여 상위 max_candidates개 반환
    sorted_cands = sorted(candidates_map.values(), key=lambda x: x["pre_score"], reverse=True)
    return sorted_cands[:max_candidates]


def evaluate_holy_grail_fit(code: str, name: str, hint_price: float, api) -> Optional[Dict[str, Any]]:
    """
    단일 후보 종목이 현재 `strategy.py`의 매수 로직에 부합하는지 2단계(일봉 -> 60분봉) 고속 검증:
    1) 일봉 TEMA 5>=20 상승추세(daily_bull) & 데드크로스 부재
    2) 실시간 3일선 M/3 수식선 상단 지지 (tick_close >= day3_m_line)
    3) 60분봉 정배열(5>20>60) 또는 20선 상단 지지 (is_bull_support)
    4) 60분봉 테마급등관문선 변곡/지지 또는 테마기준선(M선) 돌파/돌파임박
    """
    try:
        # ── [Stage 1] 일봉 조회 및 M/3선·일봉추세 1차 고속 필터링 ──
        df_daily = api.get_daily_candles(code)
        if df_daily is None or df_daily.empty or len(df_daily) < 15:
            return None

        # 최근 5일 평균 거래대금 15억 미만 저유동성 종목 제외
        trade_val_5d = float((df_daily["close"] * df_daily["volume"]).tail(5).mean())
        if trade_val_5d < 1_500_000_000:
            return None

        curr_price = float(hint_price) if hint_price and hint_price > 0 else float(df_daily["close"].iloc[-1])
        if curr_price <= 0:
            return None

        df_daily_calc = calculate_daily_tema_deadcross(df_daily, p1=5, p2=20)
        last_daily = df_daily_calc.iloc[-1]
        daily_dead_cross = bool(last_daily.get("daily_dead_cross", False)) if pd.notna(last_daily.get("daily_dead_cross")) else False
        daily_bull = bool(last_daily.get("daily_trend_bull", True)) if pd.notna(last_daily.get("daily_trend_bull")) else True

        # 일봉 데드크로스 또는 일봉 하락추세(TEMA 5 < 20) 종목은 strategy.py에서 매수 차단되므로 즉시 탈락 (60분봉 TR 절약!)
        if daily_dead_cross or not daily_bull:
            return None

        day3_m_line, _, pred1, _ = calculate_day3_m_line(df_daily, curr_price)
        # M/3선 아래에 크게 밀린 종목은 즉시 탈락 (M/3선 위 또는 -0.5% 돌파 임박만 통과)
        if day3_m_line > 0 and curr_price < day3_m_line * 0.995:
            return None

        # ── [Stage 2] 60분봉 조회 및 관문선/기준선/20선 지지 정밀 판정 ──
        df_60m = api.get_60m_candles(code)
        if df_60m is None or df_60m.empty or len(df_60m) < 20:
            return None

        df_60m = df_60m.copy()
        last_idx = df_60m.index[-1]
        if hint_price and hint_price > 0:
            curr_price = float(hint_price)
            df_60m.loc[last_idx, "close"] = curr_price
            if curr_price > df_60m.loc[last_idx, "high"]:
                df_60m.loc[last_idx, "high"] = curr_price
            if curr_price < df_60m.loc[last_idx, "low"]:
                df_60m.loc[last_idx, "low"] = curr_price
        else:
            curr_price = float(df_60m.loc[last_idx, "close"])

        df_60m_calc = calculate_all_60m_indicators(df_60m, p1=5, p2=20, p_slow=60)
        last_60m = df_60m_calc.iloc[-1]

        sma5 = float(last_60m.get("sma5", np.nan))
        sma20 = float(last_60m.get("sma20", np.nan))
        sma60 = float(last_60m.get("sma60", np.nan))
        gate_line = float(last_60m.get("theme_gate", np.nan))
        gijun_line = float(last_60m.get("theme_gijun", np.nan))
        is_gate_up = bool(last_60m.get("gate_up_turnaround", False))
        open_60m = float(last_60m.get("open", curr_price))
        low_60m = float(last_60m.get("low", curr_price))

        if np.isnan(sma5) or np.isnan(sma20) or sma20 <= 0:
            return None

        # 1) 60분봉 이평선 정배열/20선 지지 평가 (30점 만점)
        is_bull_support = (curr_price >= sma20 * 0.995) and (sma5 >= sma20 * 0.990)
        is_full_align = (not np.isnan(sma60)) and (sma5 > sma20 > sma60) and (curr_price >= sma20 * 0.995)

        if is_full_align:
            score_align = 30.0
            align_tag = "🟢완전정배열(5>20>60)"
        elif is_bull_support:
            score_align = 24.0
            align_tag = "🟡20선상단지지"
        elif curr_price >= sma20 * 0.985 and sma5 >= sma20 * 0.980:
            score_align = 12.0
            align_tag = "🟠20선돌파임박"
        else:
            # 60분봉 역배열/20선 하단 종목은 제외
            return None

        # 2) 관문선 지지/변곡 및 기준선(M선) 돌파 타점 평가 (40점 만점)
        gate_support = is_gate_up or (not np.isnan(gate_line) and gate_line > 0 and curr_price >= gate_line * 0.990 and low_60m <= gate_line * 1.015)
        gijun_diff_pct = ((curr_price - gijun_line) / gijun_line * 100.0) if (not np.isnan(gijun_line) and gijun_line > 0) else -99.0
        gate_diff_pct = ((curr_price - gate_line) / gate_line * 100.0) if (not np.isnan(gate_line) and gate_line > 0) else -99.0

        # 기준선 대비 +10% 초과 급등 과열 종목은 고점 추격 방지를 위해 제외
        if gijun_diff_pct > 10.0:
            return None

        is_immediate_buy_zone = False
        if 0.0 <= gijun_diff_pct <= 4.0 and is_bull_support:
            score_target = 40.0
            target_tag = f"🚀기준선돌파타점(+{gijun_diff_pct:.2f}%)"
            is_immediate_buy_zone = True
        elif gate_support and is_bull_support:
            score_target = 38.0
            target_tag = f"🔥관문선변곡/지지타점({gate_diff_pct:+.2f}%)"
            is_immediate_buy_zone = True
        elif -1.8 <= gijun_diff_pct < 0.0:
            score_target = 30.0
            target_tag = f"⚡기준선돌파임박({gijun_diff_pct:+.2f}%)"
        elif -1.5 <= gate_diff_pct <= 2.5:
            score_target = 26.0
            target_tag = f"🎯관문선사정권({gate_diff_pct:+.2f}%)"
        elif 4.0 < gijun_diff_pct <= 8.5:
            score_target = 20.0
            target_tag = f"🟢기준선상단순항(+{gijun_diff_pct:.2f}%)"
        else:
            return None

        # 3) M/3 실시간 3일선 지지 평가 (15점 만점)
        m3_diff_pct = ((curr_price - day3_m_line) / day3_m_line * 100.0) if day3_m_line > 0 else 0.0
        if m3_diff_pct >= 0.3:
            score_m3 = 15.0
        elif m3_diff_pct >= 0.0:
            score_m3 = 12.0
        else:
            score_m3 = 5.0

        # 4) 당일 양봉 순도 및 전일대비 거래량 파워 (15점 만점)
        curr_vol = float(last_daily.get("volume", 0.0))
        vol_ratio_prev, _ = calculate_pred_volume_ratio(df_daily, curr_vol)
        score_power = 0.0
        if curr_price >= open_60m:
            score_power += 8.0
        if vol_ratio_prev >= 30.0:
            score_power += 7.0
        elif vol_ratio_prev >= 10.0:
            score_power += 4.0

        total_fit_score = round(score_align + score_target + score_m3 + score_power, 1)
        day_ret_pct = ((curr_price - pred1) / pred1 * 100.0) if pred1 > 0 else 0.0

        if not name or name.startswith("종목_"):
            name = api.get_stock_name(code)

        return {
            "code": code,
            "name": name,
            "price": curr_price,
            "day_ret_pct": round(day_ret_pct, 2),
            "fit_score": total_fit_score,
            "is_immediate_buy_zone": is_immediate_buy_zone,
            "align_tag": align_tag,
            "target_tag": target_tag,
            "m3_line": round(day3_m_line, 0),
            "m3_diff_pct": round(m3_diff_pct, 2),
            "gate_line": round(gate_line, 0) if not np.isnan(gate_line) else 0,
            "gijun_line": round(gijun_line, 0) if not np.isnan(gijun_line) else 0,
            "gijun_diff_pct": round(gijun_diff_pct, 2),
            "vol_ratio_prev": round(vol_ratio_prev, 1),
            "scanned_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }
    except Exception as e:
        logger.debug(f"[{name}({code})] 타점 적합도 분석 중 예외: {e}")
        return None


def scan_and_save_holy_grail_watchlist(api, max_picks: int = 12, exclude_codes: Optional[set] = None) -> Dict[str, Dict[str, Any]]:
    """
    전 시장 주도주 중 현재 통합 성배 로직(60분봉 정배열/20선 지지 + 관문선/기준선 타점 + M/3선 지지)에
    가장 완벽히 부합하는 최정예 종목을 발굴하여 `holy_grail_watchlist.json`에 저장하고 반환합니다.
    """
    logger.info("===============================================================================")
    logger.info(" 🔍 [통합 성배 타점 스캐너 가동] 지수 조정 방어 & 즉시 매수 타점 부합 주도주 탐색 중...")
    logger.info("===============================================================================")

    raw_candidates = collect_market_candidates(api, max_candidates=42)
    if not raw_candidates:
        logger.warning("⚠️ 시장 후보군 조회 결과가 비어 있습니다. 기존 저장된 관심종목이 있으면 유지합니다.")
        return load_saved_watchlist()

    logger.info(f"⚡ 1차 수급/양봉 필터 통과 주도주 {len(raw_candidates)}개 대상 [일봉 추세 ➔ M/3선 ➔ 60분봉 관문/기준선] 정밀 검증...")

    matched: List[Dict[str, Any]] = []
    for cand in raw_candidates:
        code = cand["code"]
        if exclude_codes and code in exclude_codes:
            continue
        res = evaluate_holy_grail_fit(code, cand.get("name", ""), cand.get("price", 0.0), api)
        if res:
            matched.append(res)

    # 정렬: 1순위 즉시 매수 타점 진입 여부(is_immediate_buy_zone) -> 2순위 적합도 총점(fit_score)
    matched.sort(key=lambda x: (1 if x["is_immediate_buy_zone"] else 0, x["fit_score"]), reverse=True)
    top_picks = matched[:max_picks]

    watchlist_dict: Dict[str, Dict[str, Any]] = {}
    if top_picks:
        logger.info("-------------------------------------------------------------------------------")
        logger.info(f" 🏆 [통합 성배 로직 최적합 관심종목 {len(top_picks)}선 발굴 및 자동 편입 완료!]")
        logger.info("-------------------------------------------------------------------------------")
        for idx, p in enumerate(top_picks, start=1):
            code = p["code"]
            watchlist_dict[code] = p
            zone_badge = "🔥[즉시타점]" if p["is_immediate_buy_zone"] else "⚡[돌파임박]"
            logger.info(
                f"  {idx:2d}위. {zone_badge} [{p['name']}({code})] 적합도: {p['fit_score']}점 | "
                f"현재가: {p['price']:,.0f}원({p['day_ret_pct']:+.2f}%) | 60분: {p['align_tag']} | "
                f"M/3선: {p['m3_line']:,.0f}({p['m3_diff_pct']:+.2f}%) | {p['target_tag']}"
            )
        logger.info("-------------------------------------------------------------------------------")

        try:
            with open(WATCHLIST_JSON_PATH, "w", encoding="utf-8") as f:
                json.dump(watchlist_dict, f, ensure_ascii=False, indent=2)
            logger.info(f"💾 발굴된 타점 관심종목 저장 완료: {WATCHLIST_JSON_PATH}")
        except Exception as e:
            logger.error(f"관심종목 파일 저장 오류: {e}")
    else:
        logger.warning("⚠️ 현재 엄격한 60분봉/일봉 정배열 기준을 통과한 신규 종목이 없어 기존 관심종목을 유지합니다.")
        return load_saved_watchlist()

    return watchlist_dict


def load_saved_watchlist() -> Dict[str, Dict[str, Any]]:
    """저장된 holy_grail_watchlist.json 로드"""
    if os.path.exists(WATCHLIST_JSON_PATH):
        try:
            with open(WATCHLIST_JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception as e:
            logger.debug(f"holy_grail_watchlist.json 로드 실패: {e}")
    return {}


if __name__ == "__main__":
    # 단독 실행 시 즉시 스캔 및 저장 수행
    sys.path.insert(0, PROJECT_ROOT)
    from execution.trading_bot_holdings_only import SafeHoldingsThemeGateBot
    bot = SafeHoldingsThemeGateBot(is_real=True, dry_run=True)
    scan_and_save_holy_grail_watchlist(bot.api, max_picks=12)

