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

# Filepath for watchlist Excel
WATCHLIST_PATH = config.WATCHLIST_FILE

def export_holdings_to_excel(client: KiwoomClient, filepath: str):
    """Fetches holdings and exports them to an Excel file."""
    logger.info("Connecting to Kiwoom to fetch holdings for Excel export...")
    holdings = client.get_holdings()
    
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "My Pick"
    ws.append(["종목코드", "종목명", "보유수량", "매입단가", "현재가"])
    
    for h in holdings:
        ws.append([h["code"], h["name"], h["quantity"], h["buy_price"], h["current_price"]])
        
    wb.save(filepath)
    logger.info(f"Successfully exported {len(holdings)} holdings to {filepath}.")

def load_watchlist(filepath: str) -> list:
    """Loads watchlisted stocks from Excel file."""
    if not os.path.exists(filepath):
        logger.warning(f"Excel file {filepath} not found.")
        return []
        
    try:
        wb = openpyxl.load_workbook(filepath)
        ws = wb.active
        watchlist = []
        # Row 1 is header
        for r in range(2, ws.max_row + 1):
            code_cell = ws.cell(row=r, column=1).value
            name_cell = ws.cell(row=r, column=2).value
            if code_cell:
                # Pad stock code to 6 digits (e.g. 5930 -> 005930)
                code = str(code_cell).strip().zfill(6)
                name = str(name_cell).strip() if name_cell else "알 수 없음"
                watchlist.append({"code": code, "name": name})
        logger.info(f"Loaded {len(watchlist)} stocks from {filepath}.")
        return watchlist
    except Exception as e:
        logger.error(f"Error loading watchlist Excel file: {e}")
        return []

def is_market_open() -> bool:
    """Checks if the Korean stock market is currently open (Mon-Fri 09:00 - 15:30 KST)."""
    kst = timezone(timedelta(hours=9))
    now = datetime.now(kst)
    # 0 = Monday, 6 = Sunday
    if now.weekday() >= 5:
        return False
        
    market_start = dt_time(9, 0, 0)
    market_end = dt_time(15, 30, 0)
    current_time = now.time()
    
    return market_start <= current_time <= market_end

def run_trading_bot():
    """Main trading bot loop."""
    logger.info("Starting Kiwoom 15-Min Chart Trading Alert Bot...")
    logger.info(f"TEMA Settings: Period1={config.TEMA_PERIOD_SHORT}, Period2={config.TEMA_PERIOD_LONG}")
    
    # 1. Initialize Kiwoom client and notifier
    client = KiwoomClient()
    notifier = Notifier()
    
    # 2. Export holdings to my_pick.xlsx on startup (only if the file doesn't exist)
    if not os.path.exists(WATCHLIST_PATH):
        logger.info(f"Watchlist file '{WATCHLIST_PATH}' not found. Initializing with current holdings...")
        try:
            export_holdings_to_excel(client, WATCHLIST_PATH)
        except Exception as e:
            logger.error(f"Failed to export holdings on startup: {e}")
            logger.error("No my_pick.xlsx file found and export failed. Exiting.")
            return
    else:
        logger.info(f"Existing watchlist file '{WATCHLIST_PATH}' found. Skipping automatic holdings export to preserve user's watchlist.")

    # Keep track of sent alerts to prevent duplicate notifications for the same candle
    # Format: { stock_code: { 'buy_prep': 'last_time', ... } }
    sent_alerts = {}
    
    # Initial startup message
    notifier.send_all(
        "🤖 <b>[알림 시작]</b>\n"
        "키움 15분봉 모니터링 시스템이 가동되었습니다.\n"
        f"TEMA 관문선: 기간1={config.TEMA_PERIOD_SHORT}, 기간2={config.TEMA_PERIOD_LONG}\n"
        "대상 파일: <code>my_pick.xlsx</code>"
    )

    # 3. Main Polling Loop
    while True:
        # For mock testing, ignore market hours so user can test on weekends
        if not config.KIWOOM_IS_MOCK and not is_market_open():
            logger.info("Market is closed. Sleeping for 10 minutes...")
            time.sleep(600)
            continue
            
        logger.info("Polling market data...")
        
        # Load watchlist dynamically in case user edited the file
        watchlist = load_watchlist(WATCHLIST_PATH)
        if not watchlist:
            logger.warning("Watchlist is empty. Sleeping for 1 minute...")
            time.sleep(60)
            continue

        # ────────────────────────────────────────────────────────────
        # Phase 1: Collect data and calculate indicators for all stocks
        # ────────────────────────────────────────────────────────────
        stock_results = []

        for stock in watchlist:
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
            
            latest = candles[-1]
            disparity = latest.get("disparity_pct")

            stock_results.append({
                "code": code,
                "name": name,
                "latest": latest,
                "disparity_pct": disparity,
            })
            
            # Delay to comply with API rate limits
            time.sleep(0.5)

        # ────────────────────────────────────────────────────────────
        # Phase 2: Sort by disparity (이격도 오름차순, None은 맨 뒤)
        # ────────────────────────────────────────────────────────────
        stock_results.sort(
            key=lambda x: x["disparity_pct"] if x["disparity_pct"] is not None else float('inf')
        )

        if stock_results:
            logger.info("─── 이격도 우선순위 정렬 결과 ───")
            for rank, sr in enumerate(stock_results, 1):
                disp = f"{sr['disparity_pct']:.2f}%" if sr['disparity_pct'] is not None else "N/A"
                gate = sr['latest'].get('tema_gate_line')
                gate_str = f"{gate:,.0f}" if gate is not None else "N/A"
                logger.info(
                    f"  #{rank} {sr['name']}({sr['code']}) | "
                    f"현재가: {sr['latest']['close']:,.0f} | "
                    f"관문선: {gate_str} | 이격도: {disp}"
                )

        # ────────────────────────────────────────────────────────────
        # Phase 3: Process alerts in priority order (이격도 낮은 순)
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
            
            # Initialize tracking dict for this stock if not present
            if code not in sent_alerts:
                sent_alerts[code] = {
                    "buy_prep": "", "buy": "", "sell": "",
                    "buy_prep_tema": "", "buy_tema": ""
                }

            disp_str = f"{disparity:.2f}%" if disparity is not None else "N/A"
            gate_str = f"{gate_line:,.0f}원" if gate_line is not None else "N/A"

            # ── TEMA Gate Line Alerts (관문선 기반) ──

            # TEMA Buy Prep: 현재가가 관문선 1% 이내 밑에 도달
            if latest.get("signal_buy_prep_tema") and gate_line is not None:
                if sent_alerts[code]["buy_prep_tema"] != candle_time:
                    msg = (
                        f"⚠️ <b>[매수준비 - 관문선 접근]</b>\n"
                        f"📊 우선순위: #{rank} (이격도: {disp_str})\n"
                        f"종목: {name} ({code})\n"
                        f"현재가: {close_price:,.0f}원\n"
                        f"관문선(TEMA): {gate_str}\n"
                        f"시간: {candle_time}\n"
                        f"<i>(현재가가 TEMA 관문선 1% 이내 밑에 도달)</i>"
                    )
                    notifier.send_all(msg)
                    sent_alerts[code]["buy_prep_tema"] = candle_time

            # TEMA Buy: 현재가가 관문선 상향돌파
            if latest.get("signal_buy_tema") and gate_line is not None:
                if sent_alerts[code]["buy_tema"] != candle_time:
                    msg = (
                        f"🚀 <b>[매수신호 - 관문선 돌파!]</b>\n"
                        f"📊 우선순위: #{rank} (이격도: {disp_str})\n"
                        f"종목: {name} ({code})\n"
                        f"현재가: {close_price:,.0f}원\n"
                        f"관문선(TEMA): {gate_str}\n"
                        f"시간: {candle_time}\n"
                        f"<b>TEMA 관문선 돌파 매수 포인트!</b>"
                    )
                    notifier.send_all(msg)
                    sent_alerts[code]["buy_tema"] = candle_time

            # ── Existing L-line Alerts (기존 기준선 기반) ──

            # Check Buy Prep Signal (L-line)
            if latest["signal_buy_prep"] and l_line is not None:
                if sent_alerts[code]["buy_prep"] != candle_time:
                    msg = (
                        f"⚠️ <b>[매수준비 알림]</b>\n"
                        f"📊 우선순위: #{rank} (이격도: {disp_str})\n"
                        f"종목: {name} ({code})\n"
                        f"현재가: {close_price:,.0f}원\n"
                        f"기준선(L): {l_line:,.0f}원\n"
                        f"시간: {candle_time}\n"
                        f"<i>(현재가가 기준선 1% 이내 밑에 도달하였습니다.)</i>"
                    )
                    notifier.send_all(msg)
                    sent_alerts[code]["buy_prep"] = candle_time
                    
            # Check Buy Signal (Cross up L-line)
            if latest["signal_buy"] and l_line is not None:
                if sent_alerts[code]["buy"] != candle_time:
                    msg = (
                        f"🚀 <b>[매수신호 발생]</b>\n"
                        f"📊 우선순위: #{rank} (이격도: {disp_str})\n"
                        f"종목: {name} ({code})\n"
                        f"현재가: {close_price:,.0f}원\n"
                        f"기준선(L): {l_line:,.0f}원\n"
                        f"시간: {candle_time}\n"
                        f"<b>기준선 돌파 매수 포인트!</b>"
                    )
                    notifier.send_all(msg)
                    sent_alerts[code]["buy"] = candle_time
                    
            # Check Sell Signal (WMA 5 crosses below WMA 20)
            if latest["signal_sell"] and w5 is not None and w20 is not None:
                if sent_alerts[code]["sell"] != candle_time:
                    msg = (
                        f"📉 <b>[매도알림 발생]</b>\n"
                        f"종목: {name} ({code})\n"
                        f"현재가: {close_price:,.0f}원\n"
                        f"WMA 5: {w5:,.1f}원\n"
                        f"WMA 20: {w20:,.1f}원\n"
                        f"시간: {candle_time}\n"
                        f"<b>5이평 가중이 20이평 가중 아래로 데드크로스 하향돌파!</b>"
                    )
                    notifier.send_all(msg)
                    sent_alerts[code]["sell"] = candle_time
                    
        # Poll interval: check every 2 minutes (120 seconds)
        logger.info("Completed polling cycle. Sleeping for 2 minutes...")
        time.sleep(120)

if __name__ == "__main__":
    try:
        run_trading_bot()
    except KeyboardInterrupt:
        logger.info("Bot stopped by user.")
