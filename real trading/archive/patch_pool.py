import sys
import re

with open("main.py", "r", encoding="utf-8") as f:
    content = f.read()

# 1. Replace Phase 0 block
phase0_old = """    from data_manager import RealtimeDataManager
    from kiwoom_websocket import KiwoomWebSocketRunner
    from data_feeder import HybridDataFeeder

    # --- Phase 0: 장 시작 전 로컬 데이터 매니저 및 웹소켓 초기화 ---
    watchlist = load_watchlist(WATCHLIST_PATH)
    DATA_MANAGERS = {}
    WS_RUNNERS = {}
    FEEDERS = {}
    
    for s in watchlist:
        c = s["code"]
        dm = RealtimeDataManager(stock_code=c, max_len=120)
        DATA_MANAGERS[c] = dm
        
        try:
            logger.info(f"[{c}] 초기 시드 데이터 전체 (1m/3m/5m/15m/daily/120t) 다운로드 중...")
            seed_1m = client.get_1min_candles(c, last_n_days=1)
            time.sleep(0.2)
            seed_3m = client.get_3min_candles(c, 2)
            time.sleep(0.2)
            seed_5m = client.get_5min_candles(c, 2)
            time.sleep(0.2)
            seed_15m = client.get_15min_candles(c, 7)
            time.sleep(0.2)
            seed_daily = client.get_daily_candles(c, 200)
            time.sleep(0.2)
            seed_120t = client.get_tick_data(c, "120", limit=100)
            time.sleep(0.2)
            
            # API 반환 형태 변환 (dict로 안정화)
            past_1m = [{'time': i['time'], 'date': i['date'], 'open': i['open'], 'high': i['high'], 'low': i['low'], 'close': i['close'], 'volume': i['volume']} for i in seed_1m]
            past_3m = [{'time': i['time'], 'date': i['date'], 'open': i['open'], 'high': i['high'], 'low': i['low'], 'close': i['close'], 'volume': i['volume']} for i in seed_3m]
            past_5m = [{'time': i['time'], 'date': i['date'], 'open': i['open'], 'high': i['high'], 'low': i['low'], 'close': i['close'], 'volume': i['volume']} for i in seed_5m]
            past_15m = [{'time': i['time'], 'date': i['date'], 'open': i['open'], 'high': i['high'], 'low': i['low'], 'close': i['close'], 'volume': i['volume']} for i in seed_15m]
            past_daily = [{'time': i.get('time', i['date']), 'date': i['date'], 'open': i['open'], 'high': i['high'], 'low': i['low'], 'close': i['close'], 'volume': i['volume']} for i in seed_daily]
            
            past_120 = [{'time': i['time'], 'open': i['open'], 'high': i['high'], 'low': i['low'], 'close': i['close'], 'volume': i['volume']} for i in seed_120t]
                
            dm.seed_initial_data(past_120, past_1m, past_3m, past_5m, past_15m, past_daily)
        except Exception as e:
            logger.error(f"[{c}] 초기 시드 주입 실패: {e}")
            
        # 웹소켓 러너 세팅 (실패 시 차선책으로 하이브리드 피더 수동가동 가능)
        ws = KiwoomWebSocketRunner(client.token_manager, dm)
        WS_RUNNERS[c] = ws
        feeder = HybridDataFeeder(client, dm, interval=1.0)
        FEEDERS[c] = feeder
        
        # 1순위: 웹소켓 가동
        ws.start()"""

phase0_new = """    from data_manager import RealtimeDataManager
    from kiwoom_websocket import KiwoomWebSocketRunner
    from data_feeder import HybridDataFeeder
    from pool_manager import DynamicPoolManager

    # --- Phase 0: 장 시작 전 로컬 데이터 매니저 및 웹소켓 초기화 ---
    watchlist = load_watchlist(WATCHLIST_PATH)
    my_pick_codes = [s["code"] for s in watchlist]
    
    DATA_MANAGERS = {}
    WS_RUNNERS = {}
    FEEDERS = {}
    
    pool_manager = DynamicPoolManager(client, max_pool_size=40)
    
    # 초기에 1회 리밸런싱을 수행하여 주도주 포함 최대 40종목 가득 채우기
    to_add, _ = pool_manager.rebalance_pool([], my_pick_codes, init_holdings, [])
    initial_codes = list(set(my_pick_codes + to_add))
    
    def init_engine_for_code(c):
        dm = RealtimeDataManager(stock_code=c, max_len=120)
        DATA_MANAGERS[c] = dm
        
        try:
            logger.info(f"[{c}] 초기 시드 데이터 전체 (1m/3m/5m/15m/daily/120t) 다운로드 중...")
            seed_1m = client.get_1min_candles(c, last_n_days=1)
            time.sleep(0.2)
            seed_3m = client.get_3min_candles(c, 2)
            time.sleep(0.2)
            seed_5m = client.get_5min_candles(c, 2)
            time.sleep(0.2)
            seed_15m = client.get_15min_candles(c, 7)
            time.sleep(0.2)
            seed_daily = client.get_daily_candles(c, 200)
            time.sleep(0.2)
            seed_120t = client.get_tick_data(c, "120", limit=100)
            time.sleep(0.2)
            
            # API 반환 형태 변환
            past_1m = [{'time': i['time'], 'date': i['date'], 'open': i['open'], 'high': i['high'], 'low': i['low'], 'close': i['close'], 'volume': i['volume']} for i in seed_1m]
            past_3m = [{'time': i['time'], 'date': i['date'], 'open': i['open'], 'high': i['high'], 'low': i['low'], 'close': i['close'], 'volume': i['volume']} for i in seed_3m]
            past_5m = [{'time': i['time'], 'date': i['date'], 'open': i['open'], 'high': i['high'], 'low': i['low'], 'close': i['close'], 'volume': i['volume']} for i in seed_5m]
            past_15m = [{'time': i['time'], 'date': i['date'], 'open': i['open'], 'high': i['high'], 'low': i['low'], 'close': i['close'], 'volume': i['volume']} for i in seed_15m]
            past_daily = [{'time': i.get('time', i['date']), 'date': i['date'], 'open': i['open'], 'high': i['high'], 'low': i['low'], 'close': i['close'], 'volume': i['volume']} for i in seed_daily]
            past_120 = [{'time': i['time'], 'open': i['open'], 'high': i['high'], 'low': i['low'], 'close': i['close'], 'volume': i['volume']} for i in seed_120t]
                
            dm.seed_initial_data(past_120, past_1m, past_3m, past_5m, past_15m, past_daily)
        except Exception as e:
            logger.error(f"[{c}] 초기 시드 주입 실패: {e}")
            
        ws = KiwoomWebSocketRunner(client.token_manager, dm)
        WS_RUNNERS[c] = ws
        feeder = HybridDataFeeder(client, dm, interval=1.0)
        FEEDERS[c] = feeder
        ws.start()

    for c in initial_codes:
        init_engine_for_code(c)"""

if phase0_old in content:
    content = content.replace(phase0_old, phase0_new)
else:
    print("Failed to find phase 0 old text")

# 2. Replace Phase 1 loop beginning
phase1_old = """        # 계좌 잔고 및 예수금 먼저 조회
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

        # 시장 전체 등락률 실시간 조회(get_top_fluctuation_stocks_with_rates) API 호출 삭제됨 (사용자 요청)"""

phase1_new = """        # 계좌 잔고 및 미체결 내역, 예수금 조회
        holdings = client.get_holdings()
        unfilled_info = client.get_unfilled_orders()
        held_dict = {h["code"]: h for h in holdings}
        cash = client.get_cash_balance()

        # ── 다이내믹 주도주 풀 리밸런싱 ──
        watchlist = load_watchlist(WATCHLIST_PATH)
        my_pick_codes = [s["code"] for s in watchlist]
        
        current_active = list(DATA_MANAGERS.keys())
        to_add, to_remove = pool_manager.rebalance_pool(current_active, my_pick_codes, holdings, unfilled_info)
        
        for c in to_remove:
            if c in WS_RUNNERS:
                WS_RUNNERS[c].stop()
                del WS_RUNNERS[c]
            if c in DATA_MANAGERS:
                del DATA_MANAGERS[c]
            if c in FEEDERS:
                del FEEDERS[c]
                
        for c in to_add:
            init_engine_for_code(c)
            
        # 관심종목과 실시간 주도주, 보유 종목을 합산하여 감시 대상 리스트 구성
        monitor_list = []
        for c in DATA_MANAGERS.keys():
            # 이미 로드된 이름이 있다면 가져오거나 없으면 코드 사용 (API 낭비 방지)
            name_val = c
            for s in watchlist:
                if s["code"] == c:
                    name_val = s["name"]
                    break
            if name_val == c:
                for h in holdings:
                    if h["code"] == c:
                        name_val = h["name"]
                        break
            monitor_list.append({"code": c, "name": name_val, "theme": "주도주/보유"})
        
        BOT_STATE["watchlist_count"] = len(monitor_list)
        if not monitor_list:
            logger.warning("Monitor list is empty. Sleeping for 1 minute...")
            time.sleep(60)
            continue"""

if phase1_old in content:
    content = content.replace(phase1_old, phase1_new)
else:
    print("Failed to find phase 1 old text")

with open("main.py", "w", encoding="utf-8") as f:
    f.write(content)
print("Patch complete.")
