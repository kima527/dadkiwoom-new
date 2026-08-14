import sys
import time
import pandas as pd
import numpy as np
from PyQt5.QtWidgets import QApplication
from PyQt5.QAxContainer import QAxWidget
from PyQt5.QtCore import QEventLoop

class KiwoomWeeklySearch:
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

    def get_stock_codes(self):
        kospi = self.kiwoom.dynamicCall("GetCodeListByMarket(QString)", "0").split(";")[:-1]
        kosdaq = self.kiwoom.dynamicCall("GetCodeListByMarket(QString)", "10").split(";")[:-1]
        return kospi + kosdaq

    def get_master_code_name(self, code):
        return self.kiwoom.dynamicCall("GetMasterCodeName(QString)", code)

    def request_weekly_data(self, code):
        self.kiwoom.dynamicCall("SetInputValue(QString, QString)", "종목코드", code)
        self.kiwoom.dynamicCall("SetInputValue(QString, QString)", "기준일자", "")
        self.kiwoom.dynamicCall("SetInputValue(QString, QString)", "끝일자", "")
        self.kiwoom.dynamicCall("SetInputValue(QString, QString)", "수정주가구분", "1")
        
        res = self.kiwoom.dynamicCall("CommRqData(QString, QString, int, QString)", "주식주봉차트조회", "opt10082", 0, "1001")
        
        if res == 0:
            self.tr_loop = QEventLoop()
            self.tr_loop.exec_()
        else:
            print(f"{code} TR 요청 실패")
            
        return self.tr_data

    def on_receive_tr_data(self, screen_no, rqname, trcode, record_name, next, unused1, unused2, unused3, unused4):
        if rqname == "주식주봉차트조회":
            count = self.kiwoom.dynamicCall("GetRepeatCnt(QString, QString)", trcode, rqname)
            
            data_list = []
            for i in range(count):
                date = self.kiwoom.dynamicCall("GetCommData(QString, QString, int, QString)", trcode, rqname, i, "일자").strip()
                close = self.kiwoom.dynamicCall("GetCommData(QString, QString, int, QString)", trcode, rqname, i, "현재가").strip()
                close = abs(int(close)) # 하락시 음수로 오는 경우 처리
                data_list.append({"date": date, "close": close})
                
            df = pd.DataFrame(data_list)
            if not df.empty:
                # 최신 날짜가 맨 뒤로 오도록 정렬 (과거->현재)
                df = df.sort_values(by="date").reset_index(drop=True)
                self.tr_data = df
            else:
                self.tr_data = None
                
        if self.tr_loop:
            self.tr_loop.exit()


def check_condition(df):
    if df is None or len(df) < 60:
        return "None"
        
    # 5, 20, 60주 이동평균선 계산
    df['MA5'] = df['close'].rolling(window=5).mean()
    df['MA20'] = df['close'].rolling(window=20).mean()
    df['MA60'] = df['close'].rolling(window=60).mean()
    
    # 1. 정배열 상태 (a > b && b > d && a > d)
    condition_aligned = (df['MA5'] > df['MA20']) & (df['MA20'] > df['MA60'])
    
    # 2. K 시리즈 생성 (valuewhen 구현)
    # 정배열일때 종가, 아닐때는 NaN 처리 후 이전 유효값으로 채우기(ffill)
    df['K'] = np.where(condition_aligned, df['close'], np.nan)
    df['K'] = df['K'].ffill()
    
    # 3. K(2) < K(1) and K(1) > K 
    df['K_1'] = df['K'].shift(1)
    df['K_2'] = df['K'].shift(2)
    
    peak_condition = (df['K_2'] < df['K_1']) & (df['K_1'] > df['K'])
    
    # 피크 조건이 너무 빡빡할 수 있으므로 최근 3주(이번 주 포함) 이내에 만족한 적 있는지 확인합니다.
    is_peak_recent = peak_condition.iloc[-3:].any() if len(peak_condition) >= 3 else False
    
    # 단순히 정배열 상태인지도 확인합니다 (최근 2주 중 한 번이라도)
    is_aligned_recent = condition_aligned.iloc[-2:].any() if len(condition_aligned) >= 2 else False
    
    if is_peak_recent:
        return "Peak (정배열+눌림목)"
    elif is_aligned_recent:
        return "Aligned (정배열만)"
    else:
        return "None"


if __name__ == "__main__":
    app = QApplication(sys.argv)
    kiwoom = KiwoomWeeklySearch()
    kiwoom.login()
    
    print("종목 코드를 불러오는 중...")
    codes = kiwoom.get_stock_codes()
    print(f"총 {len(codes)}개 종목 검색 시작 (예상 소요시간: 약 {len(codes) * 0.25 / 60:.1f}분)")
    
    target_stocks = []
    
    for i, code in enumerate(codes):
        name = kiwoom.get_master_code_name(code)
        
        # ETF, ETN, 스팩 등은 검색에서 제외 (필요시 수정)
        if "ETF" in name or "ETN" in name or "스팩" in name or "제" in name:
            continue
            
        print(f"[{i+1}/{len(codes)}] {name}({code}) 분석 중...", end="\r")
        
        df = kiwoom.request_weekly_data(code)
        
        status = check_condition(df)
        if status != "None":
            print(f"\n★ 종목 발견: {name} ({code}) - {status}")
            target_stocks.append({
                "code": code,
                "name": name,
                "status": status
            })
            
        # 키움증권 TR 요청 제한 방지 (1분에 100회 제한 고려하여 0.6초 대기)
        time.sleep(0.6)
        
    print("\n검색 완료!")
    
    if target_stocks:
        result_df = pd.DataFrame(target_stocks)
        result_df.to_csv("weekly_target_stocks.csv", index=False, encoding="utf-8-sig")
        print("검색된 종목이 'weekly_target_stocks.csv' 파일로 저장되었습니다.")
    else:
        print("조건을 만족하는 종목이 없습니다.")
        
    sys.exit()
