import sys
import time
import os
import pandas as pd
import numpy as np
from collections import deque
from multiprocessing import Process, Queue
from PyQt5.QtWidgets import QApplication
from PyQt5.QAxContainer import QAxWidget
from PyQt5.QtCore import QEventLoop, QTimer

# ---------------------------------------------------------------------------
# [가속도 로직 상수]
# ---------------------------------------------------------------------------
WINDOW_SIZE_SECS = 3       # 가속도를 측정할 타임 윈도우 (3초)
MIN_TICKS_PER_SEC = 30     # 최대 가속도 인정 최소 기준 (1초당 30건 이상 체결)
SPEED_DROP_RATIO = 0.4     # 직전 최고 속도 대비 40% 감소 시 꺾임으로 판단


# ---------------------------------------------------------------------------
# [CORE LOGIC 1] 실시간 초당 체결 가속도 분석기
# ---------------------------------------------------------------------------
class OrderBookAccelerator:
    def __init__(self, stock_code):
        self.stock_code = stock_code
        self.tick_timestamps = deque()
        self.max_ticks_per_sec = 0
        self.is_accelerating = False
        self.has_bought = False  # 중복 매수 방지 플래그

    def push_tick(self):
        """실시간 체결 패킷이 들어올 때마다 타임스탬프 적치"""
        current_time = time.time()
        self.tick_timestamps.append(current_time)
        self.clean_expired_ticks(current_time)

    def clean_expired_ticks(self, current_time):
        """윈도우 크기(3초)를 벗어난 오래된 데이터는 메모리 확보를 위해 즉시 삭제"""
        while self.tick_timestamps and (current_time - self.tick_timestamps[0] > WINDOW_SIZE_SECS):
            self.tick_timestamps.popleft()

    def analyze_acceleration(self):
        """
        초당 체결 건수 및 가속도 임계점 판단 로직
        리턴값: 'HOLD' (유지), 'BUY_NOW' (가속 진입 매수), 'SELL_NOW' (가속도 꺾임 매도)
        """
        current_time = time.time()
        self.clean_expired_ticks(current_time)

        total_ticks = len(self.tick_timestamps)
        if total_ticks == 0:
            return "HOLD"

        # 1. 현재 1초당 평균 체결 건수 계산 (Ticks Per Second)
        current_tps = total_ticks / WINDOW_SIZE_SECS

        # 2. 광기 구간 진입 여부 판별 (초당 체결 건수가 임계치 돌파 시)
        if current_tps >= MIN_TICKS_PER_SEC:
            # 방금 막 임계점을 돌파했고, 아직 산 적이 없다면 즉시 매수 신호
            if not self.is_accelerating and not self.has_bought:
                self.is_accelerating = True
                self.has_bought = True
                self.max_ticks_per_sec = current_tps
                return "BUY_NOW"

            # 이미 가속 중이라면 최고 속도를 실시간 리프레시
            self.is_accelerating = True
            if current_tps > self.max_ticks_per_sec:
                self.max_ticks_per_sec = current_tps

        # 3. 가속도 꺾임(탈출) 판별 — 매수 후에만 매도 판단
        if self.is_accelerating and self.has_bought:
            drop_threshold = self.max_ticks_per_sec * (1 - SPEED_DROP_RATIO)
            if current_tps < drop_threshold:
                return "SELL_NOW"

        return "HOLD"


# ---------------------------------------------------------------------------
# [엔진] 백그라운드 실시간 초고속 연산 프로세스
# ---------------------------------------------------------------------------
def real_data_processing_worker(data_queue, signal_queue):
    """키움 API와 무관하게 CPU 파워만으로 가속도를 연산하는 격리된 프로세스"""
    monitored_stocks = {}

    while True:
        if not data_queue.empty():
            packet = data_queue.get()
            if packet == "STOP":
                break

            stock_code = packet['code']

            # 검색식에서 처음 넘어온 종목은 딕셔너리에 가속도 객체 동적 생성
            if stock_code not in monitored_stocks:
                monitored_stocks[stock_code] = OrderBookAccelerator(stock_code)

            accelerator = monitored_stocks[stock_code]
            accelerator.push_tick()

            # 실시간 가속도 추이 연산
            signal = accelerator.analyze_acceleration()

            if signal == "BUY_NOW":
                # 가속 진입 감지 → 메인 스레드로 매수 신호 전송
                signal_queue.put({"action": "BUY", "code": stock_code, "quantity": 100})
            elif signal == "SELL_NOW":
                # 꺾임 감지 → 메인 스레드로 매도 신호 전송 후 감시 목록에서 제거
                signal_queue.put({"action": "SELL", "code": stock_code, "quantity": 100})
                del monitored_stocks[stock_code]


# ---------------------------------------------------------------------------
# [로직] 기존 WMA 일봉 골든크로스 판별
# ---------------------------------------------------------------------------
def calculate_wma(series, length):
    weights = np.arange(1, length + 1)
    return series.rolling(window=length).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)


def check_wma_cross(df):
    if df is None or len(df) < 20:
        return False

    df['WMA5'] = calculate_wma(df['close'], 5)
    df['WMA20'] = calculate_wma(df['close'], 20)

    if len(df) < 2:
        return False

    last_row = df.iloc[-1]
    prev_row = df.iloc[-2]

    # 어제 WMA5 <= WMA20 이고, 오늘 WMA5 > WMA20 (골든크로스)
    condition = (prev_row['WMA5'] <= prev_row['WMA20']) and (last_row['WMA5'] > last_row['WMA20'])
    return condition


# ---------------------------------------------------------------------------
# [메인] 키움증권 통합 봇
# ---------------------------------------------------------------------------
class KiwoomTradingBot:
    def __init__(self, data_queue, signal_queue):
        self.kiwoom = QAxWidget("KHOPENAPI.KHOpenAPICtrl.1")
        self.kiwoom.OnEventConnect.connect(self.on_event_connect)
        self.kiwoom.OnReceiveTrData.connect(self.on_receive_tr_data)

        # 실시간 데이터 이벤트 핸들러
        self.kiwoom.OnReceiveRealData.connect(self.on_receive_real_data)

        self.data_queue = data_queue
        self.signal_queue = signal_queue

        self.login_loop = None
        self.tr_loop = None
        self.tr_data = None

        # 워커에서 보낸 매수/매도 신호를 10ms 단위로 감시하는 UI 타이머
        self.signal_checker = QTimer()
        self.signal_checker.timeout.connect(self.check_signals)
        self.signal_checker.start(10)

    def login(self):
        print("키움증권 로그인 중...")
        self.kiwoom.dynamicCall("CommConnect()")
        self.login_loop = QEventLoop()
        self.login_loop.exec_()

    def on_event_connect(self, err_code):
        if err_code == 0:
            print("로그인 성공!")
        else:
            print(f"로그인 실패 (에러코드: {err_code})")
        if self.login_loop:
            self.login_loop.exit()

    def get_stock_codes(self):
        kospi = self.kiwoom.dynamicCall("GetCodeListByMarket(QString)", "0").split(";")[:-1]
        kosdaq = self.kiwoom.dynamicCall("GetCodeListByMarket(QString)", "10").split(";")[:-1]
        return kospi + kosdaq

    def get_master_code_name(self, code):
        return self.kiwoom.dynamicCall("GetMasterCodeName(QString)", code)

    def request_daily_data(self, code):
        self.kiwoom.dynamicCall("SetInputValue(QString, QString)", "종목코드", code)
        self.kiwoom.dynamicCall("SetInputValue(QString, QString)", "기준일자", "")
        self.kiwoom.dynamicCall("SetInputValue(QString, QString)", "수정주가구분", "1")

        # opt10081: 주식일봉차트조회
        res = self.kiwoom.dynamicCall("CommRqData(QString, QString, int, QString)", "주식일봉차트조회", "opt10081", 0, "1002")

        if res == 0:
            self.tr_loop = QEventLoop()
            self.tr_loop.exec_()
        else:
            print(f"{code} TR 요청 실패")

        return self.tr_data

    def on_receive_tr_data(self, screen_no, rqname, trcode, record_name, next, unused1, unused2, unused3, unused4):
        if rqname == "주식일봉차트조회":
            count = self.kiwoom.dynamicCall("GetRepeatCnt(QString, QString)", trcode, rqname)

            data_list = []
            for i in range(count):
                date = self.kiwoom.dynamicCall("GetCommData(QString, QString, int, QString)", trcode, rqname, i, "일자").strip()
                close = self.kiwoom.dynamicCall("GetCommData(QString, QString, int, QString)", trcode, rqname, i, "현재가").strip()
                close = abs(int(close))
                data_list.append({"date": date, "close": close})

            df = pd.DataFrame(data_list)
            if not df.empty:
                # 과거에서 현재 순으로 정렬
                df = df.sort_values(by="date").reset_index(drop=True)
                self.tr_data = df
            else:
                self.tr_data = None

        if self.tr_loop:
            self.tr_loop.exit()

    # --- 실시간 연동 파트 ---
    def subscribe_realtime_data(self, target_codes):
        """WMA 크로스 충족 종목들의 실시간 체결 데이터 구독 등록"""
        screen_no = "5000"
        codes_str = ";".join(target_codes)
        print(f"\n=> 🎯 {len(target_codes)}개 타겟 종목 실시간 체결 모니터링 시작")
        # 체결 데이터(FID 10, 15, 20 등) 구독. '0'은 신규등록
        self.kiwoom.dynamicCall("SetRealReg(QString, QString, QString, QString)", screen_no, codes_str, "10;15;20", "0")

    def on_receive_real_data(self, code, real_type, real_data):
        """키움증권 실시간 체결 이벤트 — 체결 발생 즉시 워커로 타임스탬프 전달"""
        if real_type == "주식체결":
            self.data_queue.put({'code': code, 'time': time.time()})

    def check_signals(self):
        """워커 프로세스로부터 매수/매도 신호를 수신하여 메인 스레드에서 주문 집행"""
        while not self.signal_queue.empty():
            signal = self.signal_queue.get()
            is_buy = (signal["action"] == "BUY")
            self.execute_order(signal["code"], signal["quantity"], is_buy=is_buy)

    def execute_order(self, stock_code, quantity, is_buy):
        """
        매수/매도 통합 주문 실행 함수
        - 매수: 물량을 놓치지 않기 위해 시장가(03)
        - 매도: 슬리피지 방지를 위해 지정가(00)
        """
        order_type = 1 if is_buy else 2           # 1: 신규매수, 2: 신규매도
        screen_no = "4001"                         # 실시간 단타 전용 스크린 번호
        account_no = "57381000"

        # 매수는 시장가(03)로 확실히 잡고, 매도는 지정가(00)로 방어
        price_code = "03" if is_buy else "00"

        name = self.get_master_code_name(stock_code)
        action_str = "🚀 [폭발 감지] 시장가 풀매수" if is_buy else "📉 [꺾임 감지] 최우선 지정가 즉시 매도"

        print(f"\n{action_str} -> 종목: {name}({stock_code}), 수량: {quantity}")

        # 실제 주문 전송
        self.kiwoom.dynamicCall("SendOrder(QString, QString, QString, int, QString, int, int, QString, QString)",
                                "가속도주문", screen_no, account_no, order_type, stock_code, quantity, 0, price_code, "")


# ---------------------------------------------------------------------------
# 메인 엔트리포인트
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # 1. 프로세스 간 통신을 위한 양방향 큐 생성
    api_to_calc_queue = Queue()    # 메인 → 워커: 체결 데이터 전달
    calc_to_api_queue = Queue()    # 워커 → 메인: 매수/매도 신호 회수

    # 2. 백그라운드 가속도 연산 프로세스 시작
    calc_process = Process(target=real_data_processing_worker, args=(api_to_calc_queue, calc_to_api_queue))
    calc_process.start()

    app = QApplication(sys.argv)
    bot = KiwoomTradingBot(api_to_calc_queue, calc_to_api_queue)
    bot.login()

    # 3. 기존 로직: 일봉 WMA 골든크로스 종목 추출
    print("종목 코드를 불러오는 중...")
    codes = bot.get_stock_codes()
    print(f"총 {len(codes)}개 종목 검색 시작 (예상 소요시간: 약 {len(codes) * 0.6 / 60:.1f}분)")

    target_stocks = []

    for i, code in enumerate(codes):
        name = bot.get_master_code_name(code)

        # ETF, ETN, 스팩 등은 검색에서 제외
        if any(x in name for x in ["ETF", "ETN", "스팩", "제"]):
            continue

        print(f"[{i+1}/{len(codes)}] {name}({code}) 분석 중...", end="\r")

        df = bot.request_daily_data(code)

        if check_wma_cross(df):
            print(f"\n★ 타겟 발견 (가중 골든크로스): {name} ({code})")
            target_stocks.append({
                "code": code,
                "name": name,
                "status": "가중 5-20 골든크로스 (CrossUp)"
            })

        # 키움증권 TR 요청 제한 방지 (1분에 100회 제한)
        time.sleep(0.6)

    print("\n\n검색 완료!")

    # 4. 검색 결과 CSV 저장 (기존 기능 유지)
    if target_stocks:
        result_df = pd.DataFrame(target_stocks)
        desktop_path = os.path.join(os.path.expanduser("~"), "OneDrive", "바탕 화면")
        save_path = os.path.join(desktop_path, "wma_golden_cross_stocks.csv")
        result_df.to_csv(save_path, index=False, encoding="utf-8-sig")
        print(f"\n✅ 조건을 만족하는 종목이 바탕화면에 저장되었습니다: {save_path}")

    # 5. 실시간 가속도 감시 체제 돌입
    if target_stocks:
        target_codes = [item['code'] for item in target_stocks]
        bot.subscribe_realtime_data(target_codes)

        print("🚀 실시간 체결 가속도 감시 엔진이 가동 중입니다. (종료 시 콘솔 창 닫기)")
        sys.exit(app.exec_())  # 프로그램이 종료되지 않고 이벤트 루프 대기
    else:
        print("\n조건을 만족하는 종목이 없어 감시 엔진을 종료합니다.")
        api_to_calc_queue.put("STOP")
        calc_process.join()
        sys.exit()
