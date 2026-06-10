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

# ─────────────────────────────────────────────────────────
# 이전 스캔 주기의 등락률 저장소 (급등/모멘텀 추적용)
# ─────────────────────────────────────────────────────────
PREV_FLU_RATES = {}

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
            theme_cell = ws.cell(row=r, column=6).value
            if code_cell:
                code = str(code_cell).strip().zfill(6)
                name = str(name_cell).strip() if name_cell else "알 수 없음"
                theme = str(theme_cell).strip() if theme_cell else "기타"
                watchlist.append({"code": code, "name": name, "theme": theme})
        return watchlist
    except Exception as e:
        logger.error(f"Error loading raw watchlist: {e}")
        return []


def update_watchlist_excel(client: KiwoomClient, filepath: str):
    """
    Updates the watchlist Excel file with latest holdings and current prices,
    without deleting watchlist stocks that are not currently held.
    """
    logger.info("Updating watchlist Excel file with latest holdings...")
    holdings = client.get_holdings()
    
    holdings_map = {h["code"]: h for h in holdings}
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
        ws.append(["종목코드", "종목명", "보유수량", "매입단가", "현재가", "테마"])
        
    # Parse existing rows
    rows_to_keep = []
    seen_codes = set()
    header = ["종목코드", "종목명", "보유수량", "매입단가", "현재가", "테마"]
    
    for r in range(2, ws.max_row + 1):
        code_cell = ws.cell(row=r, column=1).value
        name_cell = ws.cell(row=r, column=2).value
        theme_cell = ws.cell(row=r, column=6).value
        if code_cell:
            code = str(code_cell).strip().zfill(6)
            name = str(name_cell).strip() if name_cell else "알 수 없음"
            theme = str(theme_cell).strip() if theme_cell else "기타"
            
            seen_codes.add(code)
            
            clean_code = code.replace('_AL', '').replace('_NX', '')
            if clean_code in holdings_map:
                h = holdings_map[clean_code]
                rows_to_keep.append([code, name, h["quantity"], h["buy_price"], h["current_price"], theme])
            else:
                rows_to_keep.append([code, name, "", "", "", theme])
                
    # 보유 종목이라도 엑셀에 명시적으로 등록되지 않은 종목은 자동 추가하지 않음 (사용자 요청)
    # for code, h in holdings_map.items():
    #     if code not in seen_codes: ...


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


def get_ext_adjusted_price(client, code, base_price, side, default_ticks):
    import datetime
    from datetime import timezone, timedelta
    from indicator import adjust_price_by_ticks
    
    kst = timezone(timedelta(hours=9))
    now = datetime.datetime.now(kst).time()
    t_0800 = datetime.time(8, 0, 0)
    t_0850 = datetime.time(8, 50, 0)
    t_1540 = datetime.time(15, 40, 0)
    t_2000 = datetime.time(20, 0, 0)
    
    is_ext = (t_0800 <= now < t_0850) or (t_1540 <= now < t_2000)
    
    if is_ext:
        hoga = client.get_nxt_hoga(code)
        if hoga:
            if side == "buy" and hoga["best_ask"] > 0:
                # 매수 시 최우선 매도호가 +1틱
                return adjust_price_by_ticks(hoga["best_ask"], 1)
            elif side == "sell" and hoga["best_bid"] > 0:
                # 매도 시 최우선 매수호가 -1틱
                return adjust_price_by_ticks(hoga["best_bid"], -1)
                
    # Fallback to standard
    return adjust_price_by_ticks(base_price, default_ticks)

def check_and_cancel_unfilled(client, notifier):
    import datetime
    from datetime import timezone, timedelta
    kst = timezone(timedelta(hours=9))
    now = datetime.datetime.now(kst)
    
    unfilled = client.get_unfilled_orders()
    for u in unfilled:
        try:
            # ord_tm format usually HHMMSS
            tm_str = u["order_time"]
            if len(tm_str) == 6:
                ord_dt = now.replace(hour=int(tm_str[0:2]), minute=int(tm_str[2:4]), second=int(tm_str[4:6]))
                # Check if it was yesterday (e.g. crossing midnight, though unlikely in KRX)
                if ord_dt > now:
                    ord_dt = ord_dt - timedelta(days=1)
                
                diff_minutes = (now - ord_dt).total_seconds() / 60.0
                if diff_minutes >= 3.0:
                    client.cancel_order(u["order_no"], u["code"], u["unfilled_qty"])
                    notifier.send_all(f"⏳ [미체결 타임아웃 취소] {u['name']} 주문번호 {u['order_no']} (3분 경과)")
        except Exception as e:
            pass


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
        logger.error("APP KEY 또는 SECRET KEY가 .env 파일에 설정되어 있지 않습니다. 봇을 종료합니다.")
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
    # notifier.send_all(
    #     "🤖 <b>[알림 시작]</b>\n"
    #     "키움 15분봉 모니터링 시스템이 가동되었습니다.\n"
    #     f"TEMA 관문선: 기간1={config.TEMA_PERIOD_SHORT}, 기간2={config.TEMA_PERIOD_LONG}\n"
    #     "대상 파일: <code>my_pick.xlsx</code>"
    # )

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

        # ── 🔒 [CRITICAL LOGIC LOCK - DO NOT MODIFY] ──
        # 종목 선정은 반드시 my_pick.xlsx 파일에 있는 종목으로만 매매하도록 제한합니다. (전체 종목 스캔 방지)
        watchlist = load_watchlist(WATCHLIST_PATH)
        
        # 관심종목과 계좌 보유 종목을 합산하여 감시 대상 리스트 구성
        monitor_dict = {s["code"]: s for s in watchlist}
        for h in holdings:
            if h["code"] not in monitor_dict:
                monitor_dict[h["code"]] = {"code": h["code"], "name": h["name"], "theme": "기타"}
        monitor_list = list(monitor_dict.values())
        
        BOT_STATE["watchlist_count"] = len(monitor_list)
        if not monitor_list:
            logger.warning("Monitor list is empty. Sleeping for 1 minute...")
            time.sleep(60)
            continue

        # 시장 전체 등락률 실시간 조회(get_top_fluctuation_stocks_with_rates) API 호출 삭제됨 (사용자 요청)

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
            try:
                with open(liquidation_file, "w") as f:
                    f.write(current_date)
            except Exception as e:
                logger.error(f"Failed to write liquidation file: {e}")

        # (계좌 잔고 및 예수금은 루프 시작부에서 일괄 조회하여 사용합니다)
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
        
        import concurrent.futures
        
        for stock in monitor_list:
            code = stock["code"]
            name = stock["name"]
            
            # ────────────────────────────────────────────────────────────
            # Phase 1: 병렬 데이터 수집 (Task Fan-out)
            # ────────────────────────────────────────────────────────────
            candles_15m = []
            candles_3m = []
            candles_1m = []
            daily_candles = []
            tick_res = {}
            
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                f_15m = executor.submit(client.get_15min_candles, code, 7)
                f_3m = executor.submit(client.get_3min_candles, code, 2)
                f_1m = executor.submit(client.get_1min_candles, code, 1)
                f_daily = executor.submit(client.get_daily_candles, code, 200)
                f_tick = executor.submit(client.stock_info_api.daily_stock_price_request_ka10003, stock_code=code)
                
                candles_15m = f_15m.result()
                candles_3m = f_3m.result()
                candles_1m = f_1m.result()
                daily_candles = f_daily.result()
                
                try:
                    tick_res = f_tick.result()
                except Exception:
                    tick_res = {}
                    
            # ────────────────────────────────────────────────────────────
            # Phase 2: 데이터 무결성 독립 검증 (Sanity Check)
            # ────────────────────────────────────────────────────────────
            if not candles_15m or len(candles_15m) < 60:
                logger.warning(f"Insufficient 15m candles for {name} ({code}). Minimum 60 required. Got: {len(candles_15m) if candles_15m else 0}")
                time.sleep(0.5)
                continue
                
            if not candles_3m or not candles_1m or not daily_candles:
                logger.warning(f"Missing auxiliary candle data for {name} ({code}). Skipping to prevent wrong analysis.")
                time.sleep(0.5)
                continue

            def validate_candles(c_list, name_str):
                for c in c_list[-5:]:  # Check only the most recent 5 candles for efficiency
                    if c['close'] <= 0 or c['open'] <= 0 or c['high'] <= 0 or c['low'] <= 0:
                        logger.warning(f"[{name_str}] Zero or negative price detected for {name} ({code}).")
                        return False
                    if c['high'] < c['low']:
                        logger.warning(f"[{name_str}] High < Low detected for {name} ({code}).")
                        return False
                return True
                
            if not (validate_candles(candles_15m, "15m") and 
                    validate_candles(candles_3m, "3m") and 
                    validate_candles(candles_1m, "1m") and 
                    validate_candles(daily_candles, "Daily")):
                time.sleep(0.5)
                continue
                
            # ────────────────────────────────────────────────────────────
            # Phase 3: 분봉 간 교차 검증 (Cross-Validation)
            # ────────────────────────────────────────────────────────────
            latest_15m_close = float(candles_15m[-1]['close'])
            latest_3m_close = float(candles_3m[-1]['close'])
            latest_1m_close = float(candles_1m[-1]['close'])
            
            tick_current_price = latest_1m_close
            try:
                if tick_res and "cntr_infr" in tick_res and len(tick_res["cntr_infr"]) > 0:
                    tick_current_price = float(abs(int(tick_res["cntr_infr"][0].get("cur_prc", latest_1m_close))))
            except Exception:
                pass
                
            prices_to_check = [latest_15m_close, latest_3m_close, latest_1m_close, tick_current_price]
            max_p = max(prices_to_check)
            min_p = min(prices_to_check)
            
            if min_p > 0:
                diff_pct = (max_p - min_p) / min_p * 100.0
                if diff_pct > 1.5:  # 1.5% 이상 차이나면 데이터 오염/꼬임으로 간주
                    logger.warning(f"⚠️ [Data Cross-Validation Failed] {name}({code}) Prices mismatch > 1.5%: 15m={latest_15m_close}, 3m={latest_3m_close}, 1m={latest_1m_close}, Tick={tick_current_price}. Skipping.")
                    time.sleep(0.5)
                    continue

            # ==========================================
            # 모든 검증 통과 (Data is Valid) - 기존 계산 로직 수행
            # ==========================================
            candles = candles_15m
                
            # Calculate all technical indicators (K/L + TEMA gate line)
            calculate_indicators_pure(
                candles,
                use_compressed_peak=True,
                tema_period1=config.TEMA_PERIOD_SHORT,
                tema_period2=config.TEMA_PERIOD_LONG
            )
            
            # Fetch and calculate daily/weekly conditions
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
            
            # 모멘텀 스코어 계산 (사용자 요청: 정배열 기준 = TEMA3 > TEMA60)
            t3_now = latest.get("tema3")
            t60_now = latest.get("tema60")
            t3_prev = prev.get("tema3")
            t60_prev = prev.get("tema60")
            
            score = 0.0
            trend_ok = False
            slope_ok = False
            slope_pct = 0.0
            
            if t3_now is not None and t60_now is not None:
                # ① TEMA3 > TEMA60 (정배열 상승세) -> +100점
                if t3_now > t60_now:
                    score += 100.0
                    trend_ok = True
                
                # ② 이격도를 좁히지 않고 벌어지거나 유지하며 올라가는가?
                diff_now = t3_now - t60_now
                if t3_prev is not None and t60_prev is not None:
                    diff_prev = t3_prev - t60_prev
                    if diff_now >= diff_prev:
                        score += 100.0
                        slope_ok = True
                        
                    if diff_prev > 0:
                        slope_pct = (diff_now - diff_prev) / diff_prev * 100.0
                        score += slope_pct * 10.0
            
            # ③ 당일 등락률 점수 가중치 (+10 * 등락률%)
            flu_pct = 0.0
            if daily_candles and len(daily_candles) >= 2:
                prev_close = daily_candles[-2]['close']
                if prev_close > 0:
                    flu_pct = ((latest["close"] - prev_close) / prev_close) * 100.0
            
            score += flu_pct * 10.0
            
            # 💡 [신규 로직] 직전 스캔 대비 등락률 급등(모멘텀 폭발) 추적
            flu_delta = 0.0
            if code in PREV_FLU_RATES:
                flu_delta = flu_pct - PREV_FLU_RATES[code]
                if flu_delta >= 1.0:
                    score += 200.0
                    logger.info(f"🚀 [모멘텀 폭발] {name}({code}) 3분만에 등락률 +{flu_delta:.2f}% 급등! 가산점 +200점 부여")
            
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
                # 틱 체결 데이터 파싱 (미리 병렬 수집된 tick_res 사용)
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
                "theme": stock.get("theme", "기타"),
                "latest": latest,
                "disparity_pct": disparity,
                "momentum_score": score,
                "trend_ok": trend_ok,
                "slope_ok": slope_ok,
                "slope_pct": slope_pct,
                "flu_pct": flu_pct,
                "flu_delta": flu_delta,
                "sugeub_spike": latest.get("signal_sugeub_spike", False),
                "volume_power": volume_power,
                "block_buy_count": block_buy_count,
                "candles_1m": candles_1m,
                "candles_3m": candles_3m,
                "daily_candles": daily_candles,
            })
            
            # 다음 스캔 비교를 위해 현재 등락률 저장
            PREV_FLU_RATES[code] = flu_pct
            
            # Delay to comply with API rate limits
            time.sleep(0.5)

        # ────────────────────────────────────────────────────────────
        # [NEW] Phase 1B: Calculate Theme Momentum and apply Bonus
        # ────────────────────────────────────────────────────────────
        theme_flu_rates = {}
        for sr in stock_results:
            theme = sr.get("theme", "기타")
            if theme != "기타":
                if theme not in theme_flu_rates:
                    theme_flu_rates[theme] = []
                theme_flu_rates[theme].append(sr["flu_pct"])

        theme_avg_flu = {}
        for theme, rates in theme_flu_rates.items():
            if len(rates) > 0:
                theme_avg_flu[theme] = sum(rates) / len(rates)
        
        # 주도 테마 선정 (평균 등락률 +2.0% 이상인 테마 모두)
        hot_themes = [t for t, avg in theme_avg_flu.items() if avg >= 2.0]
        
        if hot_themes:
            hot_themes_str = ", ".join([f"{t}({theme_avg_flu[t]:+.2f}%)" for t in hot_themes])
            logger.info(f"🔥 [핫 테마 포착] {hot_themes_str} -> 소속 종목에 +200점 보너스 적용")

        for sr in stock_results:
            theme = sr.get("theme", "기타")
            if theme in hot_themes:
                sr["momentum_score"] += 200.0
                sr["theme_bonus"] = True
            else:
                sr["theme_bonus"] = False

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
                theme_str = f" [🔥{sr['theme']}주도]" if sr.get("theme_bonus") else f" [{sr.get('theme', '기타')}]"
                logger.info(
                    f"  #{rank} {sr['name']}({sr['code']}){theme_str} | "
                    f"점수: {sr['momentum_score']:.2f}점 | "
                    f"정배열={sr['trend_ok']}, 이격확장={sr['slope_ok']}(기울기:{sr['slope_pct']:+.2f}%) | "
                    f"등락률: {sr['flu_pct']:+.2f}% (급등:{sr['flu_delta']:+.2f}%) | 이격도: {disp} | 수급돌파: {sr['sugeub_spike']} | 일봉보너스: {sr['latest'].get('daily_bonus_ok', False)} | 주봉보너스: {sr['latest'].get('weekly_bonus_ok', False)} | 체결강도: {sr['volume_power']:.1f}% | 1억매수: {sr['block_buy_count']}건"
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
                    "flu_pct": round(sr["flu_pct"], 2),
                    "flu_delta": round(sr["flu_delta"], 2),
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
                if is_held or code == "005930":
                    sent_alerts[code]["tracking_mode"] = "3m"
                else:
                    sent_alerts[code]["tracking_mode"] = "15m"
                
            if sent_alerts[code]["tracking_mode"] == "done_today":
                if sent_alerts[code].get("done_date") != current_date:
                    sent_alerts[code]["tracking_mode"] = "15m"
                    
            tracking_mode = sent_alerts[code]["tracking_mode"]

            if tracking_mode == "3m":
                # ─── 3분봉 추적매매 모드 ───
                # A) 15분봉 TEMA3/TEMA60 데드크로스 발생 시 우선순위로 즉시 전량 매도 및 15m 모드 복귀
                if latest.get("signal_sell_tema3_tema60_dead") and code != "005930":
                    logger.info(f"🚨 [15m TEMA3 데드크로스 감지] 3분봉 매매 해제 및 전량 매도 처리: {name} ({code})")
                    sent_alerts[code]["tracking_mode"] = "15m"
                    sent_alerts[code]["sold_qty"] = 0
                    
                    if is_held and held_info:
                        qty_to_sell = held_info["quantity"]
                        from indicator import adjust_price_by_ticks
                        sell_price = get_ext_adjusted_price(client, code, close_price, "sell", -2)
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
                                "reason": "15m TEMA3-TEMA60 Dead Cross"
                            }
                            BOT_STATE["completed_trades"].insert(0, trade_info)
                            if len(BOT_STATE["completed_trades"]) > 50:
                                BOT_STATE["completed_trades"].pop()
                            msg = (
                                f"📉 <b>[매도 체결 - 15m TEMA3-TEMA60 Dead Cross!]</b>\n"
                                f"종목: {name} ({code})\n"
                                f"매도단가: {sell_price:,.0f}원 (지정가 -2호가)\n"
                                f"매수단가: {pur_price:,.0f}원\n"
                                f"매도수량: {qty_to_sell}주\n"
                                f"<b>실현수익률: {ret_rate:+.2f}%</b>\n"
                                f"시간: {candle_time}\n"
                            )
                            notifier.send_all(msg)
                            _add_alert("sell", f"15m TEMA3-TEMA60 Dead Cross 매도 {qty_to_sell}주 @ {sell_price:,.0f}원 (지정가 -2호가)", code, name)
                    continue

                # B) 15m TEMA3 <= TEMA60 일 경우 3m 모드 비활성화 (15m 모드로 복귀 및 15m 매도 로직 적용)
                elif not latest.get("tema3_gt_tema60") and code != "005930":
                    logger.info(f"ℹ️ [15m TEMA3 <= TEMA60 감지] 3분봉 매매 모드 해제: {name} ({code})")
                    sent_alerts[code]["tracking_mode"] = "15m"
                    sent_alerts[code]["sold_qty"] = 0
                    tracking_mode = "15m"
                
                else:
                    # 15m TEMA3 > TEMA60 인 정상 3m 추적 상태
                    # 3분봉 데이터 및 지표 계산
                    logger.info(f"🔍 [3분봉 매매 모드 동작 중] {name}({code}) 3분봉 데이터를 기반으로 TEMA3 데드크로스 및 기준선 이탈 여부 실시간 감시 중...")
                    candles_3m = stock_data.get("candles_3m")
                    if candles_3m:
                        from indicator import calculate_indicators_3min, calculate_indicators_1min
                        calculate_indicators_3min(candles_3m)
                        latest_3m = candles_3m[-1]
                        prev_3m = candles_3m[-2] if len(candles_3m) > 1 else latest_3m
                        
                        candles_1m = stock_data.get("candles_1m", [])
                        if candles_1m:
                            calculate_indicators_1min(candles_1m)
                            latest_1m = candles_1m[-1]
                            prev_1m = candles_1m[-2] if len(candles_1m) > 1 else latest_1m
                        else:
                            latest_1m = {}
                            prev_1m = {}
                        
                        tema3_3m = latest_3m.get("tema3")
                        tema60_3m = latest_3m.get("tema60")
                        
                        prev_tema3_3m = prev_3m.get("tema3")
                        prev_tema60_3m = prev_3m.get("tema60")
                        
                        is_3m_dead_cross = False
                        is_3m_gold_cross = False
                        
                        # 3분봉 TEMA3/TEMA60 값 로깅
                        logger.info(f"📊 [3분봉 지표] {name}({code}) | 현재: TEMA3={tema3_3m:,.0f}, TEMA60={tema60_3m:,.0f} | 이전: TEMA3={prev_tema3_3m:,.0f}, TEMA60={prev_tema60_3m:,.0f}" if all(v is not None for v in [tema3_3m, tema60_3m, prev_tema3_3m, prev_tema60_3m]) else "")
                        
                        # 데드크로스 (매도 조건): 이전 캔들에서 TEMA3 >= TEMA60 → 현재 캔들에서 TEMA3 < TEMA60 교차
                        # 또는 현재 TEMA3 < TEMA60 상태 (이미 크로스 지나갔어도 캐치)
                        if tema3_3m is not None and tema60_3m is not None:
                            if tema3_3m < tema60_3m:
                                is_3m_dead_cross = True
                                logger.info(f"🔴 [3분봉 데드크로스 감지] {name}({code}) TEMA3({tema3_3m:,.0f}) < TEMA60({tema60_3m:,.0f})")
                        
                        # 골든크로스 (재매수 조건) + OBV 및 거래량 150% 필터 + 1분봉 선행 지표
                        # 추가 조건: TEMA60 지표 선의 기울기가 +0.05% 이상일 때만 (상승 턴)
                        if tema3_3m is not None and tema60_3m is not None and prev_tema60_3m is not None and prev_tema60_3m != 0:
                            slope_3m = ((tema60_3m - prev_tema60_3m) / prev_tema60_3m) * 100
                            if tema3_3m >= tema60_3m and slope_3m >= 0.05:
                                vol_3m = latest_3m.get("volume", 0)
                                vol_avg_3 = latest_3m.get("vol_avg_3", 0)
                                obv_now = latest_3m.get("obv", 0)
                                obv_prev = prev_3m.get("obv", 0)
                                
                                is_vol_surge = (vol_avg_3 > 0 and vol_3m >= vol_avg_3 * 1.5)
                                is_obv_rising = (obv_now > obv_prev)
                                
                                # 1분봉 선행 필터: 1분봉 수급폭발이 있거나 1분봉 TEMA3가 상승 중일 때
                                from indicator import check_short_term_sugeub
                                sugeub_1m_ok = False
                                if candles_1m:
                                    sugeub_1m_ok = check_short_term_sugeub(candles_1m, 1)
                                
                                is_1m_ok = sugeub_1m_ok
                                
                                if is_vol_surge and is_obv_rising and is_1m_ok:
                                    is_3m_gold_cross = True
                                    logger.info(f"🟢 [3분봉 재매수 확정] {name}({code}) TEMA3>=TEMA60, 거래량급증({vol_3m}/{vol_avg_3:.0f}), OBV상승, 1분봉수급OK")
                                else:
                                    logger.info(f"⏳ [3분봉 재매수 보류] {name}({code}) 크로스발생이나 필터미달(vol:{is_vol_surge}, obv:{is_obv_rising}, 1m:{is_1m_ok})")
                                
                        # ── 🔒 [CRITICAL LOGIC LOCK - DO NOT MODIFY] ──
                        # 1) 보유 중일 때 -> 3m 매도 방어망 작동 (최후의 보루, L선 이탈, 변곡 쌍봉 감지, 데드크로스)
                        if is_held:
                            sell_reason_str = ""
                            should_sell = False
                            
                            latest_15m = stock_data["latest"]
                            
                            # 방어망 1: 15분봉 최후의 보루 (관문선 1% 이탈)
                            gate_line = latest_15m.get("tema_gate_line")
                            if gate_line and close_price < gate_line * 0.99:
                                should_sell = True
                                sell_reason_str = "관문선 1% 하향 이탈 (최후 방어선 붕괴)"
                                
                            # 방어망 2: 15분봉 L선 (추세 지지선) 이탈
                            L_line = latest_15m.get("L")
                            if not should_sell and L_line and close_price < L_line:
                                should_sell = True
                                sell_reason_str = "전고점 지지선(L선) 붕괴"
                                
                            # 방어망 3: K선 변곡 도달 실패 (쌍봉 예측) + 1분봉 선행 지표 결합
                            candles_15m = stock_data.get("candles_15m", [])
                            if not should_sell and len(candles_15m) >= 6 and tema3_3m is not None and prev_tema3_3m is not None:
                                target_price = candles_15m[-6]["close"]
                                # 기존 3분봉 꺾임 조건
                                is_3m_dropping = (close_price < target_price and tema3_3m < prev_tema3_3m)
                                
                                # 1분봉 선행 꺾임 조건 (빠른 쌍봉 예측)
                                tema3_1m = latest_1m.get("tema3")
                                prev_tema3_1m = prev_1m.get("tema3")
                                is_1m_dropping = False
                                if tema3_1m is not None and prev_tema3_1m is not None:
                                    is_1m_dropping = (close_price < target_price and tema3_1m < prev_tema3_1m)
                                
                                if is_3m_dropping or is_1m_dropping:
                                    should_sell = True
                                    if is_1m_dropping and not is_3m_dropping:
                                        sell_reason_str = f"1분봉 선행 꺾임 감지 (목표가 {target_price:,.0f}원 미달)"
                                    else:
                                        sell_reason_str = f"상승 동력 고갈 (목표가 {target_price:,.0f}원 미달 및 꺾임)"
                                    
                            # 방어망 4: 기존 3분봉 데드크로스
                            if not should_sell and is_3m_dead_cross:
                                should_sell = True
                                sell_reason_str = "3분봉 데드크로스 하락"

                            if should_sell:
                                if sent_alerts[code]["sell"] != candle_time:
                                    sent_alerts[code]["sell"] = candle_time
                                    qty_to_sell = held_info["quantity"]
                                    order_res = client.place_sell_order(code, qty_to_sell, price=close_price, order_type="0")
                                    if order_res and order_res.get("return_code") == 0:
                                        sent_alerts[code]["sold_qty"] = qty_to_sell
                                        pur_price = held_info["buy_price"]
                                        ret_rate = ((close_price - pur_price) / pur_price) * 100.0
                                        
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
                            if is_3m_gold_cross:
                                qty_to_buy = sent_alerts[code].get("sold_qty", 0)
                                if qty_to_buy <= 0:
                                    # 봇 재시작 등으로 sold_qty 정보가 유실되었거나 수동 매도된 경우 주문가능금액(예수금) 95% 풀매수
                                    budget = cash * 0.95
                                    qty_to_buy = int(budget // close_price)
                                if getattr(config, 'TEST_MODE_1_SHARE', False):
                                    qty_to_buy = 1
                                        
                                if qty_to_buy > 0:
                                    if sent_alerts[code]["buy"] != candle_time:
                                        # 관문선과 기준선 이격 2% 미만 시 관망 (당일 종료 아님)
                                        if gate_line is not None and l_line is not None and l_line > 0:
                                            gap_pct = abs(gate_line - l_line) / l_line * 100.0
                                            if gap_pct < 2.0:
                                                _add_alert("info", f"3m 재매수 관망 (이격 {gap_pct:.2f}% < 2%)", code, name)
                                                continue

                                        sent_alerts[code]["buy"] = candle_time
                                        from indicator import adjust_price_by_ticks
                                        buy_price = get_ext_adjusted_price(client, code, close_price, "buy", 1)
                                        order_res = client.place_buy_order(code, qty_to_buy, price=buy_price, order_type="0")
                                        if order_res and order_res.get("return_code") == 0:
                                            msg = (
                                                f"🔄 <b>[재매수 - 3분봉 골든크로스!]</b>\n"
                                                f"종목: {name} ({code})\n"
                                                f"매수단가: {buy_price:,.0f}원 (지정가 +1호가)\n"
                                                f"매수수량: {qty_to_buy}주\n"
                                                f"시간: {candle_time}\n"
                                            )
                                            notifier.send_all(msg)
                                            _add_alert("buy", f"3m 골든크로스 재매수 {qty_to_buy}주 @ {buy_price:,.0f}원 (지정가 +1호가)", code, name)
                                            sent_alerts[code]["sold_qty"] = 0
                                            sent_alerts[code]["buy_reason"] = "dynamic"
                                        else:
                                            err_msg = order_res.get("return_msg") if order_res else "응답 없음"
                                            msg = (
                                                f"❌ <b>[재매수 실패 - 3분봉 골든크로스]</b>\n"
                                                f"종목: {name} ({code})\n"
                                                f"에러내용: {err_msg}"
                                            )
                                            # 실패 알림 제거
                                            # notifier.send_all(msg)
                                            _add_alert("error", f"3m 골든크로스 재매수 실패: {err_msg}", code, name)
                        continue
                    else:
                        logger.warning(f"Failed to fetch 1-min candles for {name} ({code}) in 1m tracking mode. Falling back to 15m logic.")

            if tracking_mode == "15m":
                # ── ① 매수 로직 (15분봉 정배열 + 1분봉 수급폭발 진입) ─────
                if not is_buy_window and not is_held:
                    if rank <= 3:
                        logger.info(f"🔎 [모니터링: {rank}위] {name}({code}) ➡️ 보류: 신규 매수 시간(08:00~12:00)이 아님")
                        
                if is_buy_window and not is_held:
                    # 계좌에 이미 보유 중인 종목이 있다면 신규 매수 차단 (1종목 몰빵 규칙)
                    if len(holdings) >= 1:
                        if rank <= 3:
                            logger.info(f"🔎 [모니터링: {rank}위] {name}({code}) ➡️ 보류: 이미 보유 중인 종목이 있음 (1종목 몰빵 규칙)")
                        continue

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

                    if already_bought_today:
                        if rank <= 3:
                            logger.info(f"🔎 [모니터링: {rank}위] {name}({code}) ➡️ 보류: 오늘 이미 신규 매수를 진행한 이력이 있음")
                        continue
                        
                    if not already_bought_today:
                        if sent_alerts[code]["buy"] != candle_time:
                            # ── 1분봉 수급폭발 확인 (유일한 수급 조건) ──
                            from indicator import check_short_term_sugeub
                            
                            # 1분봉 수급 확인
                            sugeub_1m_ok = False
                            candles_1m = stock_data.get("candles_1m")
                            if candles_1m:
                                sugeub_1m_ok = check_short_term_sugeub(candles_1m, 1)
                            
                            # 3분봉 정배열 확인 (TEMA3 > TEMA60) 및 TEMA60 기울기 확인
                            trend_3m_ok = False
                            candles_3m = stock_data.get("candles_3m")
                            if candles_3m and len(candles_3m) >= 60:
                                calculate_indicators_pure(
                                    candles_3m,
                                    use_compressed_peak=True,
                                    tema_period1=config.TEMA_PERIOD_SHORT,
                                    tema_period2=config.TEMA_PERIOD_LONG
                                )
                                latest_3m = candles_3m[-1]
                                prev_3m = candles_3m[-2] if len(candles_3m) > 1 else latest_3m
                                t3_3m = latest_3m.get("tema3")
                                t60_3m = latest_3m.get("tema60")
                                prev_t60_3m = prev_3m.get("tema60")
                                
                                if t3_3m is not None and t60_3m is not None and prev_t60_3m is not None and prev_t60_3m != 0:
                                    slope = ((t60_3m - prev_t60_3m) / prev_t60_3m) * 100
                                    if t3_3m > t60_3m and slope >= 0.05:
                                        trend_3m_ok = True
                                        logger.info(f"✅ [TEMA60 기울기 만족] {name}({code}) 기울기: {slope:+.3f}% (기준: +0.05%)")
                            
                            # ── 🔒 [CRITICAL LOGIC LOCK - DO NOT MODIFY] ──
                            # 매수 4대 핵심 관문 (15분봉 정배열 + 가산점 + 3분봉 기울기 + 1분봉 수급)
                            trend_15m_ok = stock_data.get("trend_ok", False)
                            has_bonus = stock_data.get("theme_bonus", False) or (stock_data.get("flu_delta", 0.0) >= 1.0)
                            
                            buy_condition_met = trend_15m_ok and has_bonus and trend_3m_ok and sugeub_1m_ok
                            cond_type = "15m정배열 + 가산점 + 3m기울기 + 1m수급"
                            
                            if not buy_condition_met:
                                if rank <= 3:
                                    reasons = []
                                    if not trend_15m_ok: reasons.append("15분봉 정배열 아님(역배열)")
                                    if not has_bonus: reasons.append("가산점(테마/급등/수급) 없음")
                                    if not trend_3m_ok: reasons.append("3분봉 TEMA60 기울기 0.05% 미만 또는 역배열")
                                    if not sugeub_1m_ok: reasons.append("1분봉 수급 부족")
                                    
                                    logger.info(f"🔎 [모니터링: {rank}위] {name}({code}) ➡️ 보류 사유: {', '.join(reasons)}")
                                    
                            if buy_condition_met:
                                # 수급 동시 확인! +1호가 매수 진입
                                from indicator import adjust_price_by_ticks
                                buy_price = get_ext_adjusted_price(client, code, close_price, "buy", 1)
                                
                                logger.info(f"🚀 [최종 관문 통과 매수 진입] {name} ({code}) {cond_type} | 현재가: {close_price:,.0f}원 → 매수가: {buy_price:,.0f}원 (+1호가)")
                                
                                sent_alerts[code]["buy"] = candle_time
                                sent_alerts[code]["buy_reason"] = "sugeub_mtf"
                                
                                # 주문가능금액(예수금) 95% 풀매수
                                budget = cash * 0.95
                                qty = int(budget // buy_price)
                                if getattr(config, 'TEST_MODE_1_SHARE', False):
                                    qty = 1
                                
                                if qty > 0:
                                    order_res = client.place_buy_order(code, qty, price=buy_price, order_type="0")
                                    if order_res and order_res.get("return_code") == 0:
                                        # 오늘 매수 성공 → 날짜 기록 및 3분봉 추적모드 전환
                                        try:
                                            with open(buy_date_file, "w") as f:
                                                f.write(current_date)
                                        except Exception as e:
                                            logger.error(f"Failed to write buy date file: {e}")
                                        
                                        # 매수 후 3분봉 추적 매매 모드로 전환
                                        sent_alerts[code]["tracking_mode"] = "3m"
                                        sent_alerts[code]["sold_qty"] = 0
                                        logger.info(f"➡️ [모드 전환] 매수 체결 후 3분봉 추적매매 모드로 전환: {name} ({code})")
        
                                        msg = (
                                            f"🚀 <b>[매수 체결 - {cond_type}]</b>\n"
                                            f"종목: {name} ({code})\n"
                                            f"체결단가: {buy_price:,.0f}원 (+1호가 지정가)\n"
                                            f"수량: {qty}주\n"
                                            f"시간: {candle_time}\n"
                                            f"주문번호: {order_res.get('ord_no')}\n"
                                            f"<i>매수 후 3분봉 추적매매 모드로 전환됩니다.</i>"
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
                                        # 매수 실패 알림 제거
                                        # notifier.send_all(msg)
                            else:
                                # 수급 미달 로그
                                miss = []
                                if not sugeub_1m_ok: miss.append("1분봉")
                                logger.debug(f"  {name}({code}) 수급 미달(단기모드): {', '.join(miss)} (1m={sugeub_1m_ok})")

                # ── ② 매도 로직 (시간대 무관하게 항상 적용) ──────────
                # A) 당일 종가 청산 강제 신호 부여 제거 (오버나잇 허용)
                pass

                # B) 매도 조건 충족 시 주문 처리 (시간대 무관하게 항상 적용)
                if latest.get("signal_sell"):
                    sell_reason = latest.get("sell_reason")
                    if tracking_mode == "3m" and sell_reason == "BB5 Upper Reversal":
                        pass  # 3분봉 모드에서는 볼린저밴드 매도를 무시
                    elif sent_alerts[code]["sell"] != candle_time:
                        sent_alerts[code]["sell"] = candle_time
                        reason_kr = {
                            "Pre-Power-Line Drop": "세력선 출현 전 종가 하락",
                            "TEMA 3 Dead Cross": "TEMA 3 데드크로스",
                            "BB5 Upper Reversal": "볼린저밴드 5상한선 반전 매도",
                            "K-line Stop Loss": "K선 이탈 손실제한",
                            "L-line 1% Stop Loss": "L선 1% 이탈 손절",
                            "Gate-line 1% Stop Loss": "관문선 1% 이탈 손절",
                            "Daily Close Liquidation": "당일 종가 청산",
                            "15m TEMA3-TEMA60 Dead Cross": "15m TEMA3-TEMA60 데드크로스"
                        }.get(sell_reason, "전략 매도")

                        if is_held and held_info:
                            qty_to_sell = held_info["quantity"]
                            order_res = client.place_sell_order(code, qty_to_sell, price=close_price, order_type="0")
                            if order_res and order_res.get("return_code") == 0:
                                # 15m BB5 Upper Reversal 매도 시에만 3m 추적모드로 진입
                                if sell_reason == "BB5 Upper Reversal":
                                    sent_alerts[code]["tracking_mode"] = "3m"
                                    sent_alerts[code]["sold_qty"] = qty_to_sell
                                    logger.info(f"➡️ [모드 전환] BB5 Upper Reversal 매도 후 3분봉 매매 모드로 전환: {name} ({code}), 수량: {qty_to_sell}")
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
                            # 매도 실패 알림 제거
                            # notifier.send_all(msg)
                        else:
                            msg = (
                                f"📉 <b>[{reason_kr} 매도알림 - 미보유]</b>\n"
                                f"종목: {name} ({code})\n"
                                f"현재가: {close_price:,.0f}원\n"
                                f"시간: {candle_time}\n"
                                f"<i>(매도 신호 발생 - 보유 수량 없음)</i>"
                            )
                            # 미보유 매도 신호 알림 제거
                            # notifier.send_all(msg)
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
                            # 하향돌파 매도 실패 알림 제거
                            # notifier.send_all(msg)
                        else:
                            # 미보유 종목은 알림만
                            msg = (
                                f"📉 <b>[하향돌파 알림 - 미보유]</b>\n"
                                f"종목: {name} ({code})\n"
                                f"현재가: {close_price:,.0f}원 | 두번째 선: {second_line_val:,.0f}원\n"
                                f"시간: {candle_time}"
                            )
                            # 하향돌파 미보유 알림 제거
                            # notifier.send_all(msg)
                            _add_alert("sell", f"하향돌파 (미보유) | {close_price:,.0f}원", code, name)

                    
        # Update the watchlist Excel file with latest positions and prices
        update_watchlist_excel(client, WATCHLIST_PATH)

        # Poll interval: check every 2 minutes (120 seconds)
        KST = timezone(timedelta(hours=9))
        now_kst = datetime.now(KST)
        
        sleep_time = 120
        if (now_kst.hour == 8 and now_kst.minute >= 59) or (now_kst.hour == 9 and now_kst.minute <= 15):
            sleep_time = 30
            logger.info("장 초반 변동성 구간 (08:59~09:15). 30초 대기 후 스캔합니다...")
        else:
            logger.info("Completed polling cycle. Sleeping for 2 minutes...")

        next_poll = (now_kst + timedelta(seconds=sleep_time)).strftime("%Y-%m-%d %H:%M:%S")
        BOT_STATE["next_poll_at"] = next_poll
        BOT_STATE["status"] = "sleeping"
        time.sleep(sleep_time)




if __name__ == "__main__":
    try:
        run_trading_bot()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")

