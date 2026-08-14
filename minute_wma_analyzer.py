import sys
import time
import pandas as pd
import numpy as np
from PyQt5.QtWidgets import QApplication
from PyQt5.QAxContainer import QAxWidget
from PyQt5.QtCore import QEventLoop

class KiwoomMinuteWMASearch:
    def __init__(self):
        self.kiwoom = QAxWidget("KHOPENAPI.KHOpenAPICtrl.1")
        self.kiwoom.OnEventConnect.connect(self.on_event_connect)
        self.kiwoom.OnReceiveTrData.connect(self.on_receive_tr_data)
        
        self.login_loop = None
        self.tr_loop = None
        self.tr_data = None
        
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

    def get_master_code_name(self, code):
        return self.kiwoom.dynamicCall("GetMasterCodeName(QString)", code)

    def request_minute_data(self, code, tick="3"):
        """
        opt10080: 주식분봉차트조회요청
        tick: 1, 3, 5, 10, 15, 30, 45, 60
        """
        self.kiwoom.dynamicCall("SetInputValue(QString, QString)", "종목코드", code)
        self.kiwoom.dynamicCall("SetInputValue(QString, QString)", "틱범위", tick)
        self.kiwoom.dynamicCall("SetInputValue(QString, QString)", "수정주가구분", "1")
        
        res = self.kiwoom.dynamicCall("CommRqData(QString, QString, int, QString)", "주식분봉차트조회", "opt10080", 0, "1003")
        
        if res == 0:
            self.tr_loop = QEventLoop()
            self.tr_loop.exec_()
        else:
            print(f"{code} 분봉 TR 요청 실패")
            
        return self.tr_data

    def on_receive_tr_data(self, screen_no, rqname, trcode, record_name, next, unused1, unused2, unused3, unused4):
        if rqname == "주식분봉차트조회":
            count = self.kiwoom.dynamicCall("GetRepeatCnt(QString, QString)", trcode, rqname)
            
            data_list = []
            for i in range(count):
                date = self.kiwoom.dynamicCall("GetCommData(QString, QString, int, QString)", trcode, rqname, i, "체결시간").strip()
                close = self.kiwoom.dynamicCall("GetCommData(QString, QString, int, QString)", trcode, rqname, i, "현재가").strip()
                volume = self.kiwoom.dynamicCall("GetCommData(QString, QString, int, QString)", trcode, rqname, i, "거래량").strip()
                
                # 분봉 데이터가 없는 경우 방지
                if not close: continue
                    
                close = abs(int(close))
                volume = abs(int(volume))
                data_list.append({"time": date, "close": close, "volume": volume})
                
            df = pd.DataFrame(data_list)
            if not df.empty:
                # 분봉 데이터는 최신부터 나오므로, 과거->최신 순으로 정렬을 뒤집음
                df = df.iloc[::-1].reset_index(drop=True)
                self.tr_data = df
            else:
                self.tr_data = None
                
        if self.tr_loop:
            self.tr_loop.exit()

def calculate_wma(series, length):
    weights = np.arange(1, length + 1)
    return series.rolling(window=length).apply(lambda x: np.dot(x, weights) / weights.sum(), raw=True)

def analyze_minute_타점(df, code_name):
    if df is None or len(df) < 20:
        print(f"[{code_name}] 데이터가 충분하지 않습니다.")
        return
        
    df['WMA5'] = calculate_wma(df['close'], 5)
    df['WMA20'] = calculate_wma(df['close'], 20)
    
    last_row = df.iloc[-1]
    prev_row = df.iloc[-2]
    
    current_time = last_row['time']
    # 시각 포맷 변환 (YYYYMMDDHHMMSS -> HH:MM:SS)
    formatted_time = f"{current_time[8:10]}:{current_time[10:12]}:{current_time[12:14]}"
    
    print(f"\n===== {code_name} 3분봉 분석 ({formatted_time} 기준) =====")
    print(f"현재가: {int(last_row['close']):,}원")
    print(f"WMA 5선: {last_row['WMA5']:.2f} | WMA 20선: {last_row['WMA20']:.2f}")
    
    if prev_row['WMA5'] <= prev_row['WMA20'] and last_row['WMA5'] > last_row['WMA20']:
        print("💡 [강력 매수 타점] 방금 3분봉 상 WMA 5-20 골든크로스가 발생했습니다!")
        print("   -> 상승 추세 전환 가능성이 높습니다. 거래량이 실렸다면 매수 진입을 고려하세요.")
    elif prev_row['WMA5'] >= prev_row['WMA20'] and last_row['WMA5'] < last_row['WMA20']:
        print("⚠️ [매도/관망 타점] 3분봉 상 WMA 5-20 데드크로스가 발생했습니다.")
        print("   -> 하락 추세 전환 가능성이 있으니 수익 실현 또는 관망을 권장합니다.")
    elif last_row['WMA5'] > last_row['WMA20']:
        print("📈 [홀딩 구간] 현재 5선이 20선 위에 있습니다. (상승 추세 진행 중)")
        print("   -> 5선이 20선을 하향 이탈할 때까지 홀딩하는 전략이 유효합니다.")
    else:
        print("📉 [관망 구간] 현재 5선이 20선 아래에 있습니다. (하락 또는 횡보 중)")
        print("   -> 골든크로스가 나올 때까지 진입을 대기하는 것이 좋습니다.")
    print("==================================================")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    kiwoom = KiwoomMinuteWMASearch()
    kiwoom.login()
    
    # 153890 (KODEX 200선물인버스2X), 0039P0 (매드업), 0015N0 (아로마티카)
    target_codes = ["153890", "0039P0", "0015N0"]
    
    print("\n전문가 분봉 타점 분석을 시작합니다...\n")
    
    for code in target_codes:
        name = kiwoom.get_master_code_name(code)
        if not name:
            name = "알수없는종목(코드오류가능성)"
            
        print(f"[{name} ({code})] 3분봉 데이터 수집 중...")
        df = kiwoom.request_minute_data(code, tick="3")
        analyze_minute_타점(df, name)
        
        # 키움증권 TR 요청 제한 방지
        time.sleep(1.0)
        
    print("\n분석이 완료되었습니다.")
    sys.exit()
