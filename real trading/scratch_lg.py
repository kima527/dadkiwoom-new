import sys
sys.path.append(r'c:\Users\zoela\OneDrive\바탕 화면\PythonWorksplace\real trading')
from kiwoom_client import KiwoomRealClient
from indicator import calculate_indicators_pure

def get_lg_data():
    c = KiwoomRealClient()
    # 066570_AL: LG전자 대체 시장 (야간/장후) 코드
    # 30일치 데이터를 명시적으로 가져옵니다 (HTS와 TEMA60 값을 일치시키기 위함)
    candles = c.get_15min_candles('066570_AL', 30)
    if not candles:
        print("데이터를 가져오지 못했습니다.")
        return
        
    print(f"가져온 15분봉 개수: {len(candles)}개")
        
    candles = calculate_indicators_pure(candles)
    last = candles[-1]
    
    print(f"--- LG전자(066570) 15분봉 실시간 계산 결과 (30일치 보정) ---")
    print(f"시간: {last.get('date', '')}")
    print(f"현재가(종가): {last.get('close', 0):,}")
    print(f"TEMA3 (단기추세선): {last.get('tema3', 0):,.2f}")
    print(f"TEMA60 (장기추세선): {last.get('tema60', 0):,.2f}")
    print(f"관문선 (Gate Line): {last.get('tema_gate_line', 0):,.2f}")
    print(f"K선 (추세지지선): {last.get('K', 0):,.2f}")
    print(f"L선 (추세저항선): {last.get('L', 0):,.2f}")

if __name__ == "__main__":
    get_lg_data()
