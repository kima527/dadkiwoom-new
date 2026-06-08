import sys
import io

# Windows 콘솔에서 한국어(UTF-8)가 깨지지 않도록 안전하게 설정
if sys.platform.startswith("win"):
    try:
        if sys.stdout and not sys.stdout.closed:
            sys.stdout.reconfigure(encoding="utf-8")
        if sys.stderr and not sys.stderr.closed:
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import time
import os
import logging
from datetime import datetime, timezone, timedelta, time as dt_time
import openpyxl
import config
from kiwoom_client import KiwoomClient
from indicator import calculate_indicators_pure
from notifier import Notifier

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────
# 실시간 봇 상태 공유 저장소 (대시보드 서버에서 임포트하여 읽음)
# ─────────────────────────────────────────────────────────
BOT_STATE = {
    "status": "idle",           # 'idle' | 'running' | 'sleeping'
    "last_updated": None,       # ISO timestamp
    "cycle_count": 0,           # 총 폴링 횟수
    "cash": 0,                  # 현재 예수금
    "holdings": [],             # 보유종목 목록
    "watchlist_count": 0,       # 감시종목 수
    "alerts": [],               # 최근 알림 (최대 50개)
    "rankings": [],             # 이격도 순위 목록
    "next_poll_at": None,       # 다음 폴링 예정 시각
    "completed_trades": [],     # 완료된 거래 내역
    "today_realized_profit": {},# 금일 실현손익 내역 (키움 API)
    "today_filled_orders": [],  # 금일 전체 체결 내역 (키움 API)
    "account_num": ""           # 현재 연동된 계좌번호
}

# Filepath for watchlist Excel
WATCHLIST_PATH = config.WATCHLIST_FILE

def load_raw_watchlist(filepath: str) -> list:
    """Loads all watchlisted stocks from Excel file without filtering."""
    if not os.path.exists(filepath):
        logger.warning(f"Excel file {filepath} not found.")
        return []
    try:
        wb = openpyxl.load_workbook(filepath)
        ws = wb.active
        watchlist = []
        for r in range(2, ws.max_row + 1):
            code_cell = ws.cell(row=r, column=1).value
            name_cell = ws.cell(row=r, column=2).value
            if code_cell:
                code = str(code_cell).strip().zfill(6)
                name = str(name_cell).strip() if name_cell else "알 수 없음"
                watchlist.append({"code": code, "name": name})
        return watchlist
    except Exception as e:
        logger.error(f"Error loading raw watchlist: {e}")
        return []

def get_daily_target_stock_code() -> str:
    """Returns the target stock code for today (either statically configured or dynamically selected)."""
    if not config.TARGET_SINGLE_STOCK_CODE:
        return ""
    if config.TARGET_SINGLE_STOCK_CODE != "AUTO":
        return config.TARGET_SINGLE_STOCK_CODE
        
    selected_file = "selected_stock.txt"
    if os.path.exists(selected_file):
        try:
            with open(selected_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                parts = content.split(",")
                if len(parts) == 3:
                    file_date, code, name = parts
                    KST = timezone(timedelta(hours=9))
                    current_date = datetime.now(KST).strftime("%Y-%m-%d")
                    if file_date == current_date:
                        return code
        except Exception as e:
            logger.error(f"Error reading daily target stock: {e}")
    return ""

def update_watchlist_excel(client: KiwoomClient, filepath: str):
    """
    Updates the watchlist Excel file with latest holdings and current prices,
    without deleting watchlist stocks that are not currently held.
    """
    logger.info("Updating watchlist Excel file with latest holdings...")
    holdings = client.get_holdings()
    
    # 실시간 다중 종목 대응을 위해 target_code 필터링을 해제합니다.
    holdings_map = {h["code"]: h for h in holdings}
    
    # target_code를 조회하여 신규 집중 종목이 편입되는지 판단하는 용도로만 사용합니다.
    target_code = get_daily_target_stock_code()
    
    # Load or create workbook
    if os.path.exists(filepath):
        try:
            wb = openpyxl.load_workbook(filepath)
            ws = wb.active
        except Exception as e:
            logger.error(f"Error opening Excel file {filepath}: {e}")
            return
    else:
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "My Pick"
        ws.append(["종목코드", "종목명", "보유수량", "매입단가", "현재가"])
        
    # Parse existing rows
    rows_to_keep = []
    seen_codes = set()
    header = ["종목코드", "종목명", "보유수량", "매입단가", "현재가"]
    
    for r in range(2, ws.max_row + 1):
        code_cell = ws.cell(row=r, column=1).value
        name_cell = ws.cell(row=r, column=2).value
        if code_cell:
            code = str(code_cell).strip().zfill(6)
            name = str(name_cell).strip() if name_cell else "알 수 없음"
            
            seen_codes.add(code)
            
            if code in holdings_map:
                h = holdings_map[code]
                rows_to_keep.append([code, name, h["quantity"], h["buy_price"], h["current_price"]])
            else:
                rows_to_keep.append([code, name, "", "", ""])
                
    for code, h in holdings_map.items():
        if code not in seen_codes:
            seen_codes.add(code)
            rows_to_keep.append([code, h["name"], h["quantity"], h["buy_price"], h["current_price"]])
            
    if target_code and target_code not in seen_codes and target_code not in holdings_map:
        name = client.get_stock_name(target_code) or "SK하이닉스"
        rows_to_keep.append([target_code, name, "", "", ""])

    ws.delete_rows(1, ws.max_row + 1)
    ws.append(header)
    for row in rows_to_keep:
        ws.append(row)
        
    try:
        wb.save(filepath)
        logger.info(f"Successfully updated watchlist Excel at {filepath}.")
    except Exception as e:
        logger.error(f"Failed to save updated watchlist Excel: {e}")

def load_watchlist(filepath: str) -> list:
    """Loads watchlisted stocks. Returns all watchlist stocks for multi-stock trading."""
    # 실시간 다중 종목 대응을 위해 항상 전체 관심종목을 반환합니다.
    return load_raw_watchlist(filepath)

def is_market_open() -> bool:
    """Checks if the Korean stock market is currently open (Mon-Fri 09:00 - 15:30 KST)."""
    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst)
    # 0 = Monday, 6 = Sunday
    if now.weekday() >= 5:
        return False
        
    market_start = dt_time(8, 0, 0)
    market_end = dt_time(20, 0, 0)
    current_time = now.time()
    
    return market_start <= current_time <= market_end

def _add_alert(alert_type: str, message: str, code: str = "", name: str = ""):
    """BOT_STATE의 alerts 목록에 새 알림을 추가. 최대 50개 유지."""
    KST = timezone(timedelta(hours=9))
    entry = {
        "time": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
        "type": alert_type,   # 'buy' | 'sell' | 'buy_prep' | 'info' | 'error'
        "code": code,
        "name": name,
        "message": message,
    }
    BOT_STATE["alerts"].insert(0, entry)
    if len(BOT_STATE["alerts"]) > 50:
        BOT_STATE["alerts"].pop()

def run_trading_bot():
    """Main trading bot loop."""
    logger.info("Starting Kiwoom 15-Min Chart Trading Alert Bot...")
    
    # Use credentials from config if present, otherwise prompt
    app_key = config.KIWOOM_APP_KEY
    app_secret = getattr(config, 'KIWOOM_REAL_APP_SECRET', getattr(config, 'KIWOOM_APP_SECRET', ''))

    if not app_key or not app_secret:
        print("=" * 65)
        print("      키움증권 API 호출을 위한 APP KEY 및 SECRET KEY 입력이 필요합니다.")
        print("=" * 65)
        app_key = input("Enter Kiwoom APP KEY: ").strip()
        app_secret = input("Enter Kiwoom APP SECRET: ").strip()
        print("=" * 65)
        
        if not app_key or not app_secret:
            logger.error("App Key and Secret Key are required to start the bot. Exiting.")
            sys.exit(1)
            
        config.KIWOOM_APP_KEY = app_key
        if hasattr(config, 'KIWOOM_REAL_APP_SECRET'):
            config.KIWOOM_REAL_APP_SECRET = app_secret
        else:
            config.KIWOOM_APP_SECRET = app_secret

    logger.info(f"TEMA Settings: Period1={config.TEMA_PERIOD_SHORT}, Period2={config.TEMA_PERIOD_LONG}")
    
    # 1. Initialize Kiwoom client and notifier
    client = KiwoomClient()
    notifier = Notifier()
    
    # 2. Initialize my_pick.xlsx with a sample watchlist if it doesn't exist
    if not os.path.exists(WATCHLIST_PATH):
        logger.info(f"Watchlist file '{WATCHLIST_PATH}' not found. Initializing with sample stocks...")
        try:
            wb = openpyxl.Workbook()
            ws = wb.active
            ws.title = "My Pick"
            ws.append(["종목코드", "종목명", "보유수량", "매입단가", "현재가"])
            ws.append(["005930", "삼성전자", "", "", ""])
            ws.append(["000660", "SK하이닉스", "", "", ""])
            ws.append(["086960", "MDS테크", "", "", ""])
            wb.save(WATCHLIST_PATH)
            logger.info(f"Successfully initialized template watchlist file at {WATCHLIST_PATH}.")
        except Exception as e:
            logger.error(f"Failed to initialize watchlist template: {e}")
            logger.error("No my_pick.xlsx file found and initialization failed. Exiting.")
            return
    else:
        logger.info(f"Existing watchlist file '{WATCHLIST_PATH}' found. Loaded for monitoring.")

    # Keep track of sent alerts to prevent duplicate notifications for the same candle
    # Format: { stock_code: { 'buy_prep': 'last_time', ... } }
    sent_alerts = {}
    BOT_STATE["status"] = "running"
    BOT_STATE["cycle_count"] = 0
    BOT_STATE["account_num"] = config.KIWOOM_ACCOUNT_NUM
    
    # Initial startup message
    notifier.send_all(
        "🤖 <b>[알림 시작]</b>\n"
        "키움 15분봉 모니터링 시스템이 가동되었습니다.\n"
        f"TEMA 관문선: 기간1={config.TEMA_PERIOD_SHORT}, 기간2={config.TEMA_PERIOD_LONG}\n"
        "대상 파일: <code>my_pick.xlsx</code>"
    )

    # 장 시작 전(Sleeping 상태)에도 대시보드에 보유 종목이 뜰 수 있도록 1회 초기화
    init_holdings = client.get_holdings()
    BOT_STATE["cash"] = client.get_cash_balance()
    BOT_STATE["holdings"] = [
        {
            "code": h["code"],
            "name": h["name"],
            "quantity": h["quantity"],
            "buy_price": h["buy_price"],
            "current_price": h.get("current_price", 0),
            "return_pct": round(
                ((h.get("current_price", h["buy_price"]) - h["buy_price"]) / h["buy_price"]) * 100, 2
            ) if h["buy_price"] > 0 else 0.0,
        }
        for h in init_holdings
    ]
    BOT_STATE["today_realized_profit"] = client.get_today_realized_profit()
    BOT_STATE["today_filled_orders"] = client.get_today_filled_orders()

    # 3. Main Polling Loop
    while True:
        # For mock testing, ignore market hours so user can test on weekends
        if not config.KIWOOM_IS_MOCK and not is_market_open():
            logger.info("Market is closed. Sleeping for 10 minutes...")
            time.sleep(600)
            continue
            
        logger.info("Polling market data...")
        BOT_STATE["status"] = "running"
        BOT_STATE["cycle_count"] += 1
        KST = timezone(timedelta(hours=9))
        BOT_STATE["last_updated"] = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")

        # 계좌 잔고 및 예수금 먼저 조회
        holdings = client.get_holdings()
        held_dict = {h["code"]: h for h in holdings}
        cash = client.get_cash_balance()

        # Load watchlist dynamically in case user edited the file
        watchlist = load_watchlist(WATCHLIST_PATH)
        
        # 관심종목과 계좌 보유 종목을 합산하여 감시 대상 리스트 구성
        monitor_dict = {s["code"]: s for s in watchlist}
        for h in holdings:
            if h["code"] not in monitor_dict:
                monitor_dict[h["code"]] = {"code": h["code"], "name": h["name"]}
        monitor_list = list(monitor_dict.values())
        
        BOT_STATE["watchlist_count"] = len(monitor_list)
        if not monitor_list:
            logger.warning("Monitor list is empty. Sleeping for 1 minute...")
            time.sleep(60)
            continue

        # ── 매일 장 시작 시 일일 매매 종목 선정 및 초기화 (오버나잇 보유 허용) ──
        liquidation_file = "last_liquidation.txt"
        last_liquidation_date = ""
        if os.path.exists(liquidation_file):
            try:
                with open(liquidation_file, "r") as f:
                    last_liquidation_date = f.read().strip()
            except Exception:
                pass

        current_date = datetime.now(KST).strftime("%Y-%m-%d")
        if is_market_open() and current_date != last_liquidation_date:
            logger.info(f"New trading day detected ({current_date}). Initializing daily parameters (overnight positions maintained).")
            
            # 🔒 [CRITICAL LOGIC LOCK - DO NOT MODIFY]
            # 이 로직은 사용자의 핵심 전략(등락률 우선 + 15분봉 5이평/20이평 정배열 상승 및 이격확장 지속)이 반영된 모멘텀 스코어링 시스템입니다.
            # 사용자의 승인 없이 이 정렬 알고리즘과 가중치(Score) 공식을 변경하는 것은 금지되어 있습니다.
            # ── Dynamic Daily Stock Selection ──
            if config.TARGET_SINGLE_STOCK_CODE == "AUTO":
                logger.info("Running Dynamic Daily Scanner with Rank intersection filtering...")
                raw_watchlist = load_raw_watchlist(WATCHLIST_PATH)
                
                # Fetch top trading value & top fluctuation stocks
                top_value_codes = []
                top_flu_rates_map = {}
                
                # NXT(넥스트레이드) 장 시작인 08:00부터 거래대금/등락률 상위를 실시간으로 조회합니다.
                now_kst = datetime.now(KST)
                
                try:
                    top_value_codes = client.get_top_trading_value_stocks(market_type="000", limit=100)
                    top_flu_rates_map = client.get_top_fluctuation_stocks_with_rates(market_type="000", limit=100)
                except Exception as rank_err:
                    logger.error(f"Failed to fetch market rankings: {rank_err}")

                top_flu_codes = list(top_flu_rates_map.keys())

                # Intersection logic
                filtered_candidates = []
                filter_reason = "Fallback (전체 관심종목)"
                
                if top_value_codes and top_flu_codes:
                    val_set = set(top_value_codes)
                    flu_set = set(top_flu_codes)
                    leaders = val_set.intersection(flu_set) # 거래대금 상위 & 등락률 상위 교집합
                    
                    # 1. 1차 교집합: 거래대금 상위 & 등락률 상위 & 내 관심종목
                    filtered_candidates = [s for s in raw_watchlist if s["code"] in leaders]
                    
                    if filtered_candidates:
                        filter_reason = f"거래대금 & 등락률 상위 교집합 ({len(filtered_candidates)}종목)"
                    else:
                        # 2. 2차 교집합: 거래대금 상위 또는 등락률 상위에 속하는 내 관심종목 (합집합 교집합)
                        filtered_candidates = [s for s in raw_watchlist if s["code"] in val_set or s["code"] in flu_set]
                        if filtered_candidates:
                            filter_reason = f"거래대금 또는 등락률 상위 부분 매칭 ({len(filtered_candidates)}종목)"
                        else:
                            # 3. 3차 Fallback: 겹치는 게 하나도 없으면 관심종목 전체
                            filtered_candidates = raw_watchlist
                            filter_reason = "매칭 종목 없음 -> 전체 관심종목 fallback"
                else:
                    # API 조회 불가(야간/휴일 등) 시 전체 관심종목으로 진행
                    filtered_candidates = raw_watchlist
                    filter_reason = "랭킹 API 호출 불가/데이터 없음 -> 전체 관심종목 fallback"
                
                logger.info(f"Candidates filtered. Target group: {filter_reason} (Total: {len(filtered_candidates)} stocks)")
                
                best_code = None
                best_name = None
                best_score = -float('inf')
                best_disp = 0.0
                best_details = ""
                
                for stock in filtered_candidates:
                    code = stock["code"]
                    name = stock["name"]
                    try:
                        # 1. 일봉 및 주봉 가산점 로직 (기존 필터 제거)
                        daily_candles = client.get_daily_candles(code, last_n_days=200)
                        daily_bonus_ok = False
                        weekly_bonus_ok = False
                        prev_d = None
                        if daily_candles and len(daily_candles) >= 2:
                            calculate_indicators_pure(
                                daily_candles,
                                use_compressed_peak=True,
                                tema_period1=config.TEMA_PERIOD_SHORT,
                                tema_period2=config.TEMA_PERIOD_LONG
                            )
                            # 전일 완성 일봉 구하기
                            today_str = datetime.now().strftime("%Y-%m-%d")
                            if daily_candles[-1]['date'] == today_str:
                                prev_d = daily_candles[-2] if len(daily_candles) >= 2 else None
                            else:
                                prev_d = daily_candles[-1]
                            
                            if prev_d:
                                daily_L = prev_d.get('L')
                                daily_whale = prev_d.get('whale_line')
                                if daily_L is not None:
                                    is_near_L = (daily_L * 0.97 <= prev_d['close'] <= daily_L * 1.03)
                                    is_breakout = False
                                    if daily_whale is not None:
                                        is_breakout = (prev_d['close'] >= daily_L * 0.97) and (prev_d['close'] >= daily_whale * 0.97)
                                    daily_bonus_ok = (is_near_L or is_breakout)
                                    
                            weekly_candles = client.get_weekly_candles_from_daily(daily_candles)
                            if weekly_candles and len(weekly_candles) >= 2:
                                calculate_indicators_pure(
                                    weekly_candles,
                                    use_compressed_peak=True,
                                    tema_period1=config.TEMA_PERIOD_SHORT,
                                    tema_period2=config.TEMA_PERIOD_LONG
                                )
                                w_latest = weekly_candles[-1]
                                w_L = w_latest.get('L')
                                w_whale = w_latest.get('whale_line')
                                if w_L is not None:
                                    is_near_L_w = (w_L * 0.97 <= w_latest['close'] <= w_L * 1.03)
                                    is_breakout_w = False
                                    if w_whale is not None:
                                        is_breakout_w = (w_latest['close'] >= w_L * 0.97) and (w_latest['close'] >= w_whale * 0.97)
                                    weekly_bonus_ok = (is_near_L_w or is_breakout_w)
                            
                        candles = client.get_15min_candles(code, last_n_days=7)
                        if candles and len(candles) >= 60:
                            calculate_indicators_pure(
                                candles,
                                use_compressed_peak=True,
                                tema_period1=config.TEMA_PERIOD_SHORT,
                                tema_period2=config.TEMA_PERIOD_LONG
                            )
                            latest = candles[-1]
                            prev = candles[-2] if len(candles) > 1 else latest
                            
                            s5_now = latest.get("sma5")
                            s20_now = latest.get("sma20")
                            s5_prev = prev.get("sma5")
                            s20_prev = prev.get("sma20")
                            
                            score = 0.0
                            trend_ok = False
                            slope_ok = False
                            slope_pct = 0.0
                            
                            if s5_now is not None and s20_now is not None:
                                # ① 5이평 > 20이평 (정배열 상승세) -> +100점
                                if s5_now > s20_now:
                                    score += 100.0
                                    trend_ok = True
                                
                                # ② 이격도를 좁히지 않고 벌어지거나 유지하며 올라가는가?
                                diff_now = s5_now - s20_now
                                if s5_prev is not None and s20_prev is not None:
                                    diff_prev = s5_prev - s20_prev
                                    if diff_now >= diff_prev:
                                        score += 100.0
                                        slope_ok = True
                                        
                                    if diff_prev > 0:
                                        slope_pct = (diff_now - diff_prev) / diff_prev * 100.0
                                        score += slope_pct * 10.0
                            
                            # ③ 등락률 점수 가중치 (+10 * 등락률%)
                            flu_pct = top_flu_rates_map.get(code, 0.0)
                            if flu_pct == 0.0:
                                if len(candles) >= 5:
                                    c_start = candles[-5]
                                    flu_pct = ((latest["close"] - c_start["close"]) / c_start["close"]) * 100.0
                            
                            score += flu_pct * 10.0
                            
                            # ④ 수급 돌파 점수 가중치 반영
                            has_recent_sugeub_spike = False
                            check_len = min(8, len(candles))
                            for idx_check in range(len(candles) - check_len, len(candles)):
                                if candles[idx_check].get('signal_sugeub_spike', False):
                                    has_recent_sugeub_spike = True
                                    break
                            
                            if has_recent_sugeub_spike:
                                score += 150.0
                                
                            if latest.get('signal_sugeub_spike', False):
                                score += 300.0
                                
                            if daily_bonus_ok:
                                score += 100.0
                            if weekly_bonus_ok:
                                score += 50.0
                                
                            disp = latest.get("disparity_pct", 0.0)
                            
                            detail_msg = (
                                f"정배열={trend_ok}, 이격확장={slope_ok}(기울기:{slope_pct:+.2f}%), "
                                f"등락률={flu_pct:+.2f}%, TEMA이격={disp:.2f}%, 수급돌파={latest.get('signal_sugeub_spike', False)}, "
                                f"일봉보너스={daily_bonus_ok}, 주봉보너스={weekly_bonus_ok}"
                            )
                            logger.info(f" -> {name} ({code}) | Score: {score:.2f} | {detail_msg}")
                            
                            if score > best_score:
                                best_score = score
                                best_code = code
                                best_name = name
                                best_disp = disp
                                best_details = detail_msg
                                
                        time.sleep(0.5)  # API rate limit
                    except Exception as ex:
                        logger.error(f"Error scanning {name} ({code}): {ex}")
                
                # If scanner failed to find any valid stock, fallback to first watchlist stock
                if not best_code and raw_watchlist:
                    best_code = raw_watchlist[0]["code"]
                    best_name = raw_watchlist[0]["name"]
                    best_disp = 0.0
                    best_details = "N/A"
                    logger.warning(f"Scanner could not calculate disparity. Falling back to first watchlist stock: {best_name} ({best_code})")
                
                if best_code:
                    selected_file = "selected_stock.txt"
                    try:
                        with open(selected_file, "w", encoding="utf-8") as f:
                            f.write(f"{current_date},{best_code},{best_name}")
                        logger.info(f"🎯 Selected stock for today: {best_name} ({best_code}) | Score: {best_score:.2f} | {best_details} ({filter_reason})")
                        
                        notifier.send_all(
                            f"🎯 <b>[금일 모멘텀 최우선 관심 종목 브리핑]</b>\n"
                            f"시장 분석을 통해 오늘 가장 모멘텀이 우수한 최우선 종목을 선정했습니다.\n"
                            f"종목명: <b>{best_name} ({best_code})</b>\n"
                            f"모멘텀 스코어: <b>{best_score:.2f}점</b>\n"
                            f"이격도: {best_disp:.2f}%\n"
                            f"상세상태: {best_details}\n"
                            f"필터조건: {filter_reason}\n"
                            f"※ 실제 매매는 전체 관심종목을 대상으로 실시간 감시하며 즉각 대응합니다."
                        )
                        _add_alert("info", f"금일 매매종목 선정: {best_name} ({best_code}) | Score: {best_score:.2f} | {best_details}", best_code, best_name)
                    except Exception as e:
                        logger.error(f"Failed to write selected stock file: {e}")
            
            try:
                with open(liquidation_file, "w") as f:
                    f.write(current_date)
            except Exception as e:
                logger.error(f"Failed to write liquidation file: {e}")

        # (계좌 잔고 및 예수금은 루프 시작부에서 일괄 조회하여 사용합니다)
        # Filter holdings to target stock if configured
        target_code = get_daily_target_stock_code()

        # ── 실시간 상태 업데이트 ──
        BOT_STATE["cash"] = cash
        BOT_STATE["holdings"] = [
            {
                "code": h["code"],
                "name": h["name"],
                "quantity": h["quantity"],
                "buy_price": h["buy_price"],
                "current_price": h.get("current_price", 0),
                "return_pct": round(
                    ((h.get("current_price", h["buy_price"]) - h["buy_price"]) / h["buy_price"]) * 100, 2
                ) if h["buy_price"] > 0 else 0.0,
            }
            for h in holdings
        ]
        
        # 키움증권 당일 실현손익 및 체결내역 직접 조회 연동
        BOT_STATE["today_realized_profit"] = client.get_today_realized_profit()
        BOT_STATE["today_filled_orders"] = client.get_today_filled_orders()

        # 🔒 [CRITICAL LOGIC LOCK - DO NOT MODIFY]
        # 이 로직은 실시간 모니터링 및 랭킹 정렬 시 사용자의 핵심 모멘텀 스코어 공식(정배열 + 이격확장 + 등락률)을 일관성 있게 유지해줍니다.
        # 사용자의 승인 없이 이 점수 산출 공식을 임의로 제거하거나 변경해서는 안 됩니다.
        # ────────────────────────────────────────────────────────────
        # Phase 1: Collect data and calculate indicators for all stocks
        # ────────────────────────────────────────────────────────────
        stock_results = []
        
        # Fetch real-time fluctuation rates map (NXT 장 개장 08시부터 실시간 조회)
        top_flu_rates_map = {}
        now_kst = datetime.now(timezone(timedelta(hours=9)))
        try:
            top_flu_rates_map = client.get_top_fluctuation_stocks_with_rates(market_type="000", limit=100)
        except Exception:
            pass

        for stock in monitor_list:
            code = stock["code"]
            name = stock["name"]
            
            # Fetch 15-min candles for last 7 days (확장: TEMA 안정적 계산 위해)
            candles = client.get_15min_candles(code, last_n_days=7)
            if not candles or len(candles) < 60:
                logger.warning(
                    f"Insufficient candles for {name} ({code}). "
                    f"Minimum 60 required. Got: {len(candles) if candles else 0}"
                )
                continue
                
            # Calculate all technical indicators (K/L + TEMA gate line)
            calculate_indicators_pure(
                candles,
                use_compressed_peak=True,
                tema_period1=config.TEMA_PERIOD_SHORT,
                tema_period2=config.TEMA_PERIOD_LONG
            )
            
            # Fetch and calculate daily/weekly conditions
            daily_candles = client.get_daily_candles(code, last_n_days=200)
            daily_bonus_ok = False
            weekly_bonus_ok = False
            prev_d = None
            if daily_candles and len(daily_candles) >= 2:
                calculate_indicators_pure(
                    daily_candles,
                    use_compressed_peak=True,
                    tema_period1=config.TEMA_PERIOD_SHORT,
                    tema_period2=config.TEMA_PERIOD_LONG
                )
                today_str = datetime.now().strftime("%Y-%m-%d")
                if daily_candles[-1]['date'] == today_str:
                    prev_d = daily_candles[-2] if len(daily_candles) >= 2 else None
                else:
                    prev_d = daily_candles[-1]
                
                if prev_d:
                    daily_L = prev_d.get('L')
                    daily_whale = prev_d.get('whale_line')
                    if daily_L is not None:
                        is_near_L = (daily_L * 0.97 <= prev_d['close'] <= daily_L * 1.03)
                        is_breakout = False
                        if daily_whale is not None:
                            is_breakout = (prev_d['close'] >= daily_L * 0.97) and (prev_d['close'] >= daily_whale * 0.97)
                        daily_bonus_ok = (is_near_L or is_breakout)
                        
                weekly_candles = client.get_weekly_candles_from_daily(daily_candles)
                if weekly_candles and len(weekly_candles) >= 2:
                    calculate_indicators_pure(
                        weekly_candles,
                        use_compressed_peak=True,
                        tema_period1=config.TEMA_PERIOD_SHORT,
                        tema_period2=config.TEMA_PERIOD_LONG
                    )
                    w_latest = weekly_candles[-1]
                    w_L = w_latest.get('L')
                    w_whale = w_latest.get('whale_line')
                    if w_L is not None:
                        is_near_L_w = (w_L * 0.97 <= w_latest['close'] <= w_L * 1.03)
                        is_breakout_w = False
                        if w_whale is not None:
                            is_breakout_w = (w_latest['close'] >= w_L * 0.97) and (w_latest['close'] >= w_whale * 0.97)
                        weekly_bonus_ok = (is_near_L_w or is_breakout_w)
            
            latest = candles[-1]
            latest['daily_bonus_ok'] = daily_bonus_ok
            latest['weekly_bonus_ok'] = weekly_bonus_ok
            latest['daily_L'] = prev_d.get('L') if prev_d else None
            latest['daily_whale_line'] = prev_d.get('whale_line') if prev_d else None
            
            prev = candles[-2] if len(candles) > 1 else latest
            
            # 모멘텀 스코어 계산
            s5_now = latest.get("sma5")
            s20_now = latest.get("sma20")
            s5_prev = prev.get("sma5")
            s20_prev = prev.get("sma20")
            
            score = 0.0
            trend_ok = False
            slope_ok = False
            slope_pct = 0.0
            
            if s5_now is not None and s20_now is not None:
                # ① 5이평 > 20이평 (정배열 상승세) -> +100점
                if s5_now > s20_now:
                    score += 100.0
                    trend_ok = True
                
                # ② 이격도를 좁히지 않고 벌어지거나 유지하며 올라가는가?
                diff_now = s5_now - s20_now
                if s5_prev is not None and s20_prev is not None:
                    diff_prev = s5_prev - s20_prev
                    if diff_now >= diff_prev:
                        score += 100.0
                        slope_ok = True
                        
                    if diff_prev > 0:
                        slope_pct = (diff_now - diff_prev) / diff_prev * 100.0
                        score += slope_pct * 10.0
            
            # ③ 등락률 점수 가중치 (+10 * 등락률%)
            flu_pct = top_flu_rates_map.get(code, 0.0)
            if flu_pct == 0.0:
                if len(candles) >= 5:
                    c_start = candles[-5]
                    flu_pct = ((latest["close"] - c_start["close"]) / c_start["close"]) * 100.0
            
            score += flu_pct * 10.0
            
            # ④ 수급 돌파 점수 가중치 반영
            has_recent_sugeub_spike = False
            check_len = min(8, len(candles))
            for idx_check in range(len(candles) - check_len, len(candles)):
                if candles[idx_check].get('signal_sugeub_spike', False):
                    has_recent_sugeub_spike = True
                    break
            
            if has_recent_sugeub_spike:
                score += 150.0
                
            if latest.get('signal_sugeub_spike', False):
                score += 300.0
                
            if daily_bonus_ok:
                score += 100.0
            if weekly_bonus_ok:
                score += 50.0
                
            disparity = latest.get("disparity_pct")

            # ⑤ 체결강도 및 1억 이상 대량매수 건수 가산점 반영 (온디맨드 실시간 비교용)
            volume_power = 100.0
            block_buy_count = 0
            try:
                # 틱 체결 데이터 조회
                tick_res = client.stock_info_api.daily_stock_price_request_ka10003(stock_code=code)
                from indicator import parse_tick_execution_data
                volume_power, block_buy_count = parse_tick_execution_data(tick_res)
                
                # 체결강도 가산점: (체결강도 - 100) * 2.0
                score += (volume_power - 100.0) * 2.0
                
                # 대량 매수 건수 가산점: 건당 +50.0
                score += block_buy_count * 50.0
            except Exception as ex_tick:
                logger.error(f"Error fetching tick details for scoring {name} ({code}): {ex_tick}")

            stock_results.append({
                "code": code,
                "name": name,
                "latest": latest,
                "disparity_pct": disparity,
                "momentum_score": score,
                "trend_ok": trend_ok,
                "slope_ok": slope_ok,
                "slope_pct": slope_pct,
                "flu_pct": flu_pct,
                "sugeub_spike": latest.get("signal_sugeub_spike", False),
                "volume_power": volume_power,
                "block_buy_count": block_buy_count,
            })
            
            # Delay to comply with API rate limits
            time.sleep(0.5)

        # ────────────────────────────────────────────────────────────
        # Phase 2: Sort by momentum score (모멘텀 스코어 내림차순)
        # ────────────────────────────────────────────────────────────
        stock_results.sort(
            key=lambda x: x["momentum_score"], reverse=True
        )

        if stock_results:
            logger.info("─── 모멘텀 우선순위 정렬 결과 ───")
            rankings_snapshot = []
            for rank, sr in enumerate(stock_results, 1):
                disp = f"{sr['disparity_pct']:.2f}%" if sr['disparity_pct'] is not None else "N/A"
                logger.info(
                    f"  #{rank} {sr['name']}({sr['code']}) | "
                    f"점수: {sr['momentum_score']:.2f}점 | "
                    f"정배열={sr['trend_ok']}, 이격확장={sr['slope_ok']}(기울기:{sr['slope_pct']:+.2f}%) | "
                    f"등락률: {sr['flu_pct']:+.2f}% | 이격도: {disp} | 수급돌파: {sr['sugeub_spike']} | 일봉보너스: {sr['latest'].get('daily_bonus_ok', False)} | 주봉보너스: {sr['latest'].get('weekly_bonus_ok', False)} | 체결강도: {sr['volume_power']:.1f}% | 1억매수: {sr['block_buy_count']}건"
                )
                trend = "uptrend" if sr['trend_ok'] else "rebound"
                rankings_snapshot.append({
                    "rank": rank,
                    "code": sr["code"],
                    "name": sr["name"],
                    "price": sr["latest"]["close"],
                    "gate_line": sr["latest"].get("tema_gate_line"),
                    "disparity_pct": sr["disparity_pct"],
                    "momentum_score": round(sr["momentum_score"], 2),
                    "trend": trend,
                    "signal_buy": bool(sr["latest"].get("signal_buy_dynamic")),
                    "signal_sell": bool(sr["latest"].get("signal_sell")),
                    "daily_breakout_ok": bool(sr["latest"].get("daily_bonus_ok", False)),
                    "weekly_bonus_ok": bool(sr["latest"].get("weekly_bonus_ok", False)),
                    "volume_power": sr["volume_power"],
                    "block_buy_count": sr["block_buy_count"],
                })
            BOT_STATE["rankings"] = rankings_snapshot

        # ────────────────────────────────────────────────────────────
        # Phase 3: Process alerts and execute orders in priority order (이격도 낮은 순)
        # ────────────────────────────────────────────────────────────
        for rank, stock_data in enumerate(stock_results, 1):
            code = stock_data["code"]
            name = stock_data["name"]
            latest = stock_data["latest"]
            disparity = stock_data["disparity_pct"]
            candle_time = latest["time"]
            close_price = latest["close"]
            gate_line = latest.get("tema_gate_line")
            l_line = latest["L"]
            w5 = latest["wma5"]
            w20 = latest["wma20"]
            
            # 🔒 [CRITICAL LOGIC LOCK - DO NOT MODIFY]
            # ── 실시간 주문 판단 및 집행부 (관문선 손절 + 볼린저 밴드 반전/재매수 보호) ──
            # Initialize tracking dict for this stock if not present
            if code not in sent_alerts:
                sent_alerts[code] = {
                    "buy_prep": "", "buy": "", "sell": "",
                    "buy_prep_tema": "", "buy_tema": "",
                    "sell_second_line": "",   # 두번째 선 하향 이탈 매도
                    "buy_ema40": "",          # EMA40(SMA20) 접촉 재매수
                    "sold_qty": 0,
                }

            disp_str = f"{disparity:.2f}%" if disparity is not None else "N/A"
            gate_str = f"{gate_line:,.0f}원" if gate_line is not None else "N/A"

            # ── 현재 실제 시각 기준 시간대 판별 ──
            # (캔들 시간이 아닌 현재 KST 시각을 사용해야 정확한 매매 윈도우 판별 가능)
            now_kst = datetime.now(timezone(timedelta(hours=9)))
            t_hour = now_kst.hour
            t_min  = now_kst.minute

            # ① 동적 매수 윈도우 (08:00 ~ 12:00)
            is_buy_window = (8 <= t_hour < 12)
            # ② 재매수 윈도우 (10:00 ~ 15:20)
            is_rebuy_window = (t_hour >= 10 and (t_hour < 15 or (t_hour == 15 and t_min < 20)))
            # ③ 10:00 이후 : L선 하향 이탈 추가 매도 활성화
            is_post_ten     = (t_hour >= 10)

            logger.debug(
                f"{name}({code}) 현재시각={t_hour:02d}:{t_min:02d} | 캔들시각={candle_time} | "
                f"buy_window={is_buy_window} rebuy={is_rebuy_window} post10={is_post_ten}"
            )

            # Check if stock is currently held
            is_held = code in held_dict
            held_info = held_dict.get(code)

            if "tracking_mode" not in sent_alerts[code]:
                if is_held:
                    sent_alerts[code]["tracking_mode"] = "1m"
                else:
                    sent_alerts[code]["tracking_mode"] = "15m"
                
            if sent_alerts[code]["tracking_mode"] == "done_today":
                if sent_alerts[code].get("done_date") != current_date:
                    sent_alerts[code]["tracking_mode"] = "15m"
                    
            tracking_mode = sent_alerts[code]["tracking_mode"]

            if tracking_mode == "1m":
                # ─── 1분봉 추적매매 모드 ───
                # A) 15분봉 SMA5/SMA60 데드크로스 발생 시 우선순위로 즉시 전량 매도 및 15m 모드 복귀
                if latest.get("signal_sell_sma5_sma60_dead"):
                    logger.info(f"🚨 [15m 데드크로스 감지] 1분봉 매매 해제 및 전량 매도 처리: {name} ({code})")
                    sent_alerts[code]["tracking_mode"] = "15m"
                    sent_alerts[code]["sold_qty"] = 0
                    
                    if is_held and held_info:
                        qty_to_sell = held_info["quantity"]
                        from indicator import adjust_price_by_ticks
                        sell_price = adjust_price_by_ticks(close_price, -2)
                        order_res = client.place_sell_order(code, qty_to_sell, price=sell_price, order_type="0")
                        if order_res and order_res.get("return_code") == 0:
                            pur_price = held_info["buy_price"]
                            ret_rate = ((sell_price - pur_price) / pur_price) * 100.0
                            trade_info = {
                                "time": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
                                "code": code,
                                "name": name,
                                "buy_price": pur_price,
                                "sell_price": sell_price,
                                "return_pct": round(ret_rate, 2),
                                "reason": "15m SMA5-60 Dead Cross"
                            }
                            BOT_STATE["completed_trades"].insert(0, trade_info)
                            if len(BOT_STATE["completed_trades"]) > 50:
                                BOT_STATE["completed_trades"].pop()
                            msg = (
                                f"📉 <b>[매도 체결 - 15m SMA5-60 Dead Cross!]</b>\n"
                                f"종목: {name} ({code})\n"
                                f"매도단가: {sell_price:,.0f}원 (지정가 -2호가)\n"
                                f"매수단가: {pur_price:,.0f}원\n"
                                f"매도수량: {qty_to_sell}주\n"
                                f"<b>실현수익률: {ret_rate:+.2f}%</b>\n"
                                f"시간: {candle_time}\n"
                            )
                            notifier.send_all(msg)
                            _add_alert("sell", f"15m SMA5-60 Dead Cross 매도 {qty_to_sell}주 @ {sell_price:,.0f}원 (지정가 -2호가)", code, name)
                    continue

                # B) 15m SMA5 <= SMA60 일 경우 1m 모드 비활성화 (15m 모드로 복귀 및 15m 매도 로직 적용)
                elif not latest.get("sma5_gt_sma60"):
                    logger.info(f"ℹ️ [15m SMA5 <= SMA60 감지] 1분봉 매매 모드 해제: {name} ({code})")
                    sent_alerts[code]["tracking_mode"] = "15m"
                    sent_alerts[code]["sold_qty"] = 0
                    tracking_mode = "15m"
                
                else:
                    # 15m SMA 5 > SMA 60 인 정상 1m 추적 상태
                    # 1분봉 데이터 및 지표 계산 (SMA40, TEMA20 등을 위해 최소 2일치 확보)
                    candles_1m = client.get_1min_candles(code, last_n_days=2)
                    if candles_1m:
                        from indicator import calculate_indicators_1min
                        calculate_indicators_1min(candles_1m)
                        latest_1m = candles_1m[-1]
                        prev_1m = candles_1m[-2] if len(candles_1m) > 1 else latest_1m
                        
                        tema20_1m = latest_1m.get("tema20")
                        sma20_1m = latest_1m.get("sma20")
                        sma40_1m = latest_1m.get("sma40")
                        
                        prev_tema20_1m = prev_1m.get("tema20")
                        prev_sma20_1m = prev_1m.get("sma20")
                        prev_sma40_1m = prev_1m.get("sma40")
                        
                        is_1m_dead_cross = False
                        is_1m_gold_cross = False
                        
                        # 데드크로스 (매도 조건): SMA20 이 SMA40 을 하향이탈
                        if (sma20_1m is not None and sma40_1m is not None 
                            and prev_sma20_1m is not None and prev_sma40_1m is not None):
                            if prev_sma20_1m >= prev_sma40_1m and sma20_1m < sma40_1m:
                                is_1m_dead_cross = True
                        
                        # 골든크로스 (재매수 조건): TEMA20 이 SMA20 을 상향돌파
                        if (tema20_1m is not None and sma20_1m is not None 
                            and prev_tema20_1m is not None and prev_sma20_1m is not None):
                            if prev_tema20_1m < prev_sma20_1m and tema20_1m >= sma20_1m:
                                is_1m_gold_cross = True
                                
                        # 1) 보유 중일 때 -> 1m SMA20 & SMA40 데드크로스 매도 또는 기준선(L) 이탈 시 매도
                        if is_held:
                            is_below_l = (l_line is not None and close_price < l_line)
                            if is_1m_dead_cross or is_below_l:
                                if sent_alerts[code]["sell"] != candle_time:
                                    sent_alerts[code]["sell"] = candle_time
                                    qty_to_sell = held_info["quantity"]
                                    order_res = client.place_sell_order(code, qty_to_sell, price=close_price, order_type="0")
                                    if order_res and order_res.get("return_code") == 0:
                                        sent_alerts[code]["sold_qty"] = qty_to_sell
                                        pur_price = held_info["buy_price"]
                                        ret_rate = ((close_price - pur_price) / pur_price) * 100.0
                                        
                                        sell_reason_str = "1m 데드크로스" if is_1m_dead_cross else "L선(기준선) 이탈 매도"
                                        
                                        trade_info = {
                                            "time": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
                                            "code": code,
                                            "name": name,
                                            "buy_price": pur_price,
                                            "sell_price": close_price,
                                            "return_pct": round(ret_rate, 2),
                                            "reason": sell_reason_str
                                        }
                                        BOT_STATE["completed_trades"].insert(0, trade_info)
                                        if len(BOT_STATE["completed_trades"]) > 50:
                                            BOT_STATE["completed_trades"].pop()
                                        
                                        msg = (
                                            f"📉 <b>[매도 체결 - {sell_reason_str}!]</b>\n"
                                            f"종목: {name} ({code})\n"
                                            f"매도단가: {close_price:,.0f}원\n"
                                            f"매수단가: {pur_price:,.0f}원\n"
                                            f"매도수량: {qty_to_sell}주\n"
                                            f"<b>실현수익률: {ret_rate:+.2f}%</b>\n"
                                            f"시간: {candle_time}\n"
                                        )
                                        notifier.send_all(msg)
                                        _add_alert("sell", f"{sell_reason_str} {qty_to_sell}주 @ {close_price:,.0f}원", code, name)
                        
                        else:
                            if is_1m_gold_cross:
                                qty_to_buy = sent_alerts[code].get("sold_qty", 0)
                                if qty_to_buy <= 0:
                                    # 봇 재시작 등으로 sold_qty 정보가 유실되었거나 수동 매도된 경우 기본 예산 사용
                                    if config.TARGET_SINGLE_STOCK_CODE == "AUTO":
                                        qty_to_buy = int(config.SINGLE_STOCK_BUDGET // close_price)
                                    else:
                                        qty_to_buy = int(config.BUDGET_PER_STOCK // close_price)
                                        
                                if qty_to_buy > 0:
                                    if sent_alerts[code]["buy"] != candle_time:
                                        # 관문선과 기준선 간격 1% 이하 시 당일 매매 종료
                                        if gate_line is not None and l_line is not None and l_line > 0:
                                            gap_pct = abs(gate_line - l_line) / l_line * 100.0
                                            if gap_pct <= 1.0:
                                                msg = (
                                                    f"🛑 <b>[매매 종료 - 간격 1% 이하]</b>\n"
                                                    f"종목: {name} ({code})\n"
                                                    f"관문선({gate_line:,.0f}원)과 기준선({l_line:,.0f}원)의 간격이 1% 이하({gap_pct:.2f}%)이므로 재매수하지 않고 당일 매매를 종료합니다."
                                                )
                                                notifier.send_all(msg)
                                                _add_alert("info", f"1m 재매수 포기 (간격 {gap_pct:.2f}% <= 1%)", code, name)
                                                sent_alerts[code]["sold_qty"] = 0
                                                sent_alerts[code]["tracking_mode"] = "done_today"
                                                sent_alerts[code]["done_date"] = current_date
                                                continue

                                        sent_alerts[code]["buy"] = candle_time
                                        from indicator import adjust_price_by_ticks
                                        buy_price = adjust_price_by_ticks(close_price, 2)
                                        order_res = client.place_buy_order(code, qty_to_buy, price=buy_price, order_type="0")
                                        if order_res and order_res.get("return_code") == 0:
                                            msg = (
                                                f"🔄 <b>[재매수 - 1분봉 골든크로스!]</b>\n"
                                                f"종목: {name} ({code})\n"
                                                f"매수단가: {buy_price:,.0f}원 (지정가 +2호가)\n"
                                                f"매수수량: {qty_to_buy}주\n"
                                                f"시간: {candle_time}\n"
                                            )
                                            notifier.send_all(msg)
                                            _add_alert("buy", f"1m 골든크로스 재매수 {qty_to_buy}주 @ {buy_price:,.0f}원 (지정가 +2호가)", code, name)
                                            sent_alerts[code]["sold_qty"] = 0
                                            sent_alerts[code]["buy_reason"] = "dynamic"
                                        else:
                                            err_msg = order_res.get("return_msg") if order_res else "응답 없음"
                                            msg = (
                                                f"❌ <b>[재매수 실패 - 1분봉 골든크로스]</b>\n"
                                                f"종목: {name} ({code})\n"
                                                f"에러내용: {err_msg}"
                                            )
                                            notifier.send_all(msg)
                                            _add_alert("error", f"1m 골든크로스 재매수 실패: {err_msg}", code, name)
                        continue
                    else:
                        logger.warning(f"Failed to fetch 1-min candles for {name} ({code}) in 1m tracking mode. Falling back to 15m logic.")

            if tracking_mode == "15m":
                # ── ① 매수 로직 (수급 신호 기반 - 1분/5분/15분 중 하나라도 수급 터지면 +1호가 매수) ─────
                if is_buy_window and not is_held:
                    # 오늘 이미 다른 종목 신규 매수를 완료했는지 체크
                    already_bought_today = False
                    buy_date_file = "last_buy_date.txt"
                    if os.path.exists(buy_date_file):
                        try:
                            with open(buy_date_file, "r") as f:
                                last_buy_date = f.read().strip()
                            if last_buy_date == current_date:
                                already_bought_today = True
                        except Exception as e:
                            logger.error(f"Error reading buy date file: {e}")

                    if not already_bought_today:
                        if sent_alerts[code]["buy"] != candle_time:
                            # ── 멀티타임프레임 수급 신호 순차 확인 (AND 조건: 1분/5분/15분 모두 수급 터져야 매수) ──
                            from indicator import check_short_term_sugeub
                            
                            # 15분봉 수급 확인 (이미 계산된 지표 활용)
                            sugeub_15m_ok = latest.get('signal_sugeub_spike', False)
                            
                            # 5분봉 수급 확인
                            sugeub_5m_ok = False
                            candles_5m = client.get_5min_candles(code, last_n_days=2)
                            if candles_5m:
                                sugeub_5m_ok = check_short_term_sugeub(candles_5m, 5)
                            
                            # 1분봉 수급 확인
                            sugeub_1m_ok = False
                            candles_1m = client.get_1min_candles(code, last_n_days=1)
                            if candles_1m:
                                sugeub_1m_ok = check_short_term_sugeub(candles_1m, 1)
                            
                            # 세 타임프레임 모두 수급 신호가 떠야 매수
                            if sugeub_15m_ok and sugeub_5m_ok and sugeub_1m_ok:
                                # 1분/5분/15분 수급 동시 확인! +1호가 매수 진행
                                from indicator import adjust_price_by_ticks
                                buy_price = adjust_price_by_ticks(close_price, 1)
                                cond_type = "수급신호(1분/5분/15분 동시)"
                                
                                logger.info(f"🚀 [수급 매수 진입] {name} ({code}) {cond_type} | 현재가: {close_price:,.0f}원 → 매수가: {buy_price:,.0f}원 (+1호가)")
                                
                                sent_alerts[code]["buy"] = candle_time
                                sent_alerts[code]["buy_reason"] = "sugeub_mtf"
                                
                                if config.TARGET_SINGLE_STOCK_CODE == "AUTO":
                                    budget = config.SINGLE_STOCK_BUDGET
                                else:
                                    budget = config.BUDGET_PER_STOCK
                                qty = int(budget // buy_price)
                                
                                if qty > 0:
                                    order_res = client.place_buy_order(code, qty, price=buy_price, order_type="0")
                                    if order_res and order_res.get("return_code") == 0:
                                        # 오늘 매수 성공 → 날짜 기록 및 1분봉 추적모드 전환
                                        try:
                                            with open(buy_date_file, "w") as f:
                                                f.write(current_date)
                                        except Exception as e:
                                            logger.error(f"Failed to write buy date file: {e}")
                                        
                                        # 매수 후 1분봉 추적 매매 모드로 전환
                                        sent_alerts[code]["tracking_mode"] = "1m"
                                        sent_alerts[code]["sold_qty"] = 0
                                        logger.info(f"➡️ [모드 전환] 매수 체결 후 1분봉 추적매매 모드로 전환: {name} ({code})")
        
                                        msg = (
                                            f"🚀 <b>[매수 체결 - {cond_type}]</b>\n"
                                            f"종목: {name} ({code})\n"
                                            f"체결단가: {buy_price:,.0f}원 (+1호가 지정가)\n"
                                            f"수량: {qty}주\n"
                                            f"시간: {candle_time}\n"
                                            f"주문번호: {order_res.get('ord_no')}\n"
                                            f"<i>매수 후 1분봉 추적매매 모드로 전환됩니다.</i>"
                                        )
                                        notifier.send_all(msg)
                                        _add_alert("buy", f"{cond_type} 매수 {qty}주 @ {buy_price:,.0f}원 (+1호가)", code, name)
                                    else:
                                        err_msg = order_res.get("return_msg") if order_res else "응답 없음"
                                        logger.error(f"❌ [매수 실패] {name} ({code}): {err_msg}")
                                        msg = (
                                            f"❌ <b>[매수 실패 - {cond_type}]</b>\n"
                                            f"종목: {name} ({code})\n"
                                            f"에러내용: {err_msg}"
                                        )
                                        notifier.send_all(msg)
                            else:
                                # 어느 타임프레임이 미달인지 로그
                                miss = []
                                if not sugeub_15m_ok: miss.append("15분봉")
                                if not sugeub_5m_ok: miss.append("5분봉")
                                if not sugeub_1m_ok: miss.append("1분봉")
                                logger.debug(f"  {name}({code}) 수급 미달: {', '.join(miss)} (15m={sugeub_15m_ok}, 5m={sugeub_5m_ok}, 1m={sugeub_1m_ok})")

                # ── ② 매도 로직 (시간대 무관하게 항상 적용) ──────────
                # A) 당일 종가 청산 강제 신호 부여 제거 (오버나잇 허용)
                pass

                # B) 매도 조건 충족 시 주문 처리 (시간대 무관하게 항상 적용)
                if latest.get("signal_sell"):
                    if sent_alerts[code]["sell"] != candle_time:
                        sent_alerts[code]["sell"] = candle_time
                        sell_reason = latest.get("sell_reason")
                        reason_kr = {
                            "Pre-Power-Line Drop": "세력선 출현 전 종가 하락",
                            "TEMA 3 Dead Cross": "TEMA 3 데드크로스",
                            "BB5 Upper Reversal": "볼린저밴드 5상한선 반전 매도",
                            "K-line Stop Loss": "K선 이탈 손실제한",
                            "L-line 1% Stop Loss": "L선 1% 이탈 손절",
                            "Gate-line 1% Stop Loss": "관문선 1% 이탈 손절",
                            "Daily Close Liquidation": "당일 종가 청산",
                            "15m SMA5-60 Dead Cross": "15m SMA5-60 데드크로스"
                        }.get(sell_reason, "전략 매도")

                        if is_held and held_info:
                            qty_to_sell = held_info["quantity"]
                            order_res = client.place_sell_order(code, qty_to_sell, price=close_price, order_type="0")
                            if order_res and order_res.get("return_code") == 0:
                                # 15m BB5 Upper Reversal 매도 시에만 1m 추적모드로 진입
                                if sell_reason == "BB5 Upper Reversal":
                                    sent_alerts[code]["tracking_mode"] = "1m"
                                    sent_alerts[code]["sold_qty"] = qty_to_sell
                                    logger.info(f"➡️ [모드 전환] BB5 Upper Reversal 매도 후 1분봉 매매 모드로 전환: {name} ({code}), 수량: {qty_to_sell}")
                                else:
                                    sent_alerts[code]["tracking_mode"] = "15m"
                                    sent_alerts[code]["sold_qty"] = 0
                                    logger.info(f"➡️ [모드 유지] {sell_reason} 매도 발생으로 15m 모드 유지 및 sold_qty 초기화: {name} ({code})")

                                pur_price = held_info["buy_price"]
                                ret_rate = ((close_price - pur_price) / pur_price) * 100.0
                                
                                # 로그 및 대시보드 연동용 Trade 기록 추가
                                logger.info(f"📉 [매도 체결] {name}({code}) | 매수가: {pur_price:,.0f}원 | 매도가: {close_price:,.0f}원 | 수익률: {ret_rate:+.2f}% | 사유: {reason_kr}")
                                trade_info = {
                                    "time": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
                                    "code": code,
                                    "name": name,
                                    "buy_price": pur_price,
                                    "sell_price": close_price,
                                    "return_pct": round(ret_rate, 2),
                                    "reason": reason_kr
                                }
                                BOT_STATE["completed_trades"].insert(0, trade_info)
                                if len(BOT_STATE["completed_trades"]) > 50:
                                    BOT_STATE["completed_trades"].pop()

                                msg = (
                                    f"📉 <b>[매도 체결 - {reason_kr}!]</b>\n"
                                    f"종목: {name} ({code})\n"
                                    f"매도단가: {close_price:,.0f}원\n"
                                    f"매수단가: {pur_price:,.0f}원\n"
                                    f"매도수량: {qty_to_sell}주\n"
                                    f"<b>실현수익률: {ret_rate:+.2f}%</b>\n"
                                    f"시간: {candle_time}\n"
                                    f"주문번호: {order_res.get('ord_no')}"
                                )
                                _add_alert("sell", f"{reason_kr} 매도 {qty_to_sell}주 @ {close_price:,.0f}원 (매수가: {pur_price:,.0f}원) | 수익률: {ret_rate:+.2f}%", code, name)
                            else:
                                err_msg = order_res.get("return_msg") if order_res else "응답 없음"
                                msg = (
                                    f"❌ <b>[매도 실패 - {reason_kr}]</b>\n"
                                    f"종목: {name} ({code})\n"
                                    f"에러내용: {err_msg}"
                                )
                                _add_alert("error", f"{reason_kr} 매도실패: {err_msg}", code, name)
                            notifier.send_all(msg)
                        else:
                            msg = (
                                f"📉 <b>[{reason_kr} 매도알림 - 미보유]</b>\n"
                                f"종목: {name} ({code})\n"
                                f"현재가: {close_price:,.0f}원\n"
                                f"시간: {candle_time}\n"
                                f"<i>(매도 신호 발생 - 보유 수량 없음)</i>"
                            )
                            notifier.send_all(msg)
                            _add_alert("sell", f"{reason_kr} (미보유) | {close_price:,.0f}원", code, name)

                # B) 세력선과 기준선 중 두번째 선 하향돌파 매도 (10:00 이후 추가 매도 조건)
                second_line_val = latest.get("second_line_val")
                if is_post_ten and latest.get("signal_sell_second_line") and second_line_val is not None:
                    if sent_alerts[code]["sell_second_line"] != candle_time:
                        sent_alerts[code]["sell_second_line"] = candle_time

                        if is_held and held_info:
                            qty_to_sell = held_info["quantity"]
                            order_res = client.place_sell_order(code, qty_to_sell, price=close_price, order_type="0")
                            if order_res and order_res.get("return_code") == 0:
                                # Stay in 15m mode and reset sold_qty to 0
                                sent_alerts[code]["tracking_mode"] = "15m"
                                sent_alerts[code]["sold_qty"] = 0
                                
                                pur_price = held_info["buy_price"]
                                ret_rate = ((close_price - pur_price) / pur_price) * 100.0
                                msg = (
                                    f"📉 <b>[매도 체결 - 두번째 선 하향돌파!]</b>\n"
                                    f"종목: {name} ({code})\n"
                                    f"매도단가: {close_price:,.0f}원\n"
                                    f"매수단가: {pur_price:,.0f}원\n"
                                    f"두번째 선: {second_line_val:,.0f}원 (이탈)\n"
                                    f"매도수량: {qty_to_sell}주\n"
                                    f"<b>실현수익률: {ret_rate:+.2f}%</b>\n"
                                    f"시간: {candle_time}\n"
                                    f"주문번호: {order_res.get('ord_no')}"
                                )
                                _add_alert("sell", f"하향돌파 매도 {qty_to_sell}주 @ {close_price:,.0f}원 | {ret_rate:+.2f}%", code, name)
                            else:
                                err_msg = order_res.get("return_msg") if order_res else "응답 없음"
                                msg = (
                                    f"❌ <b>[매도 실패 - 하향돌파]</b>\n"
                                    f"종목: {name} ({code})\n"
                                    f"에러내용: {err_msg}"
                                )
                                _add_alert("error", f"하향돌파 매도실패: {err_msg}", code, name)
                            notifier.send_all(msg)
                        else:
                            # 미보유 종목은 알림만
                            msg = (
                                f"📉 <b>[하향돌파 알림 - 미보유]</b>\n"
                                f"종목: {name} ({code})\n"
                                f"현재가: {close_price:,.0f}원 | 두번째 선: {second_line_val:,.0f}원\n"
                                f"시간: {candle_time}"
                            )
                            notifier.send_all(msg)
                            _add_alert("sell", f"하향돌파 (미보유) | {close_price:,.0f}원", code, name)

                    
        # Update the watchlist Excel file with latest positions and prices
        update_watchlist_excel(client, WATCHLIST_PATH)

        # Poll interval: check every 2 minutes (120 seconds)
        logger.info("Completed polling cycle. Sleeping for 2 minutes...")
        KST = timezone(timedelta(hours=9))
        next_poll = datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S")
        BOT_STATE["next_poll_at"] = next_poll
        BOT_STATE["status"] = "sleeping"
        time.sleep(120)




if __name__ == "__main__":
    try:
        run_trading_bot()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")

