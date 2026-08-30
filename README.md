# 🚀 Kiwoom 이평선 돌파 + 15분봉 추세추종 실전 자동매매 시스템

키움증권 REST OpenAPI 및 실시간 웹소켓을 기반으로 **일봉/30분봉 이평 돌파 + 가중 5-20 고가선(HH)** 타점을 포착하고, **15분봉 SMA 5-40 데드크로스**로 수익을 극대화하는 자동매매 봇입니다.

---

## 📈 핵심 매매 전략 (Strategy Specification)

### 1. 🟢 매수 로직 (2가지 조건 중 선착순 충족 시 매수)
* **[조건 1 - 일봉 돌파]**: 당일 일봉 단순 20이평선(SMA20)을 상향 돌파하고, 종가가 가중 5-20 고가선(`ValueWhen(1, CrossUp(WMA5, WMA20), High)`) 위에 위치할 때.
* **[조건 2 - 30분봉 돌파]**: 당일 30분봉 단순 260이평선(SMA260) 위로 올라탄 종목 중 가중 5-20 고가선을 돌파할 때.
* **필터**: 1주 가격 <= 30만 원 (종목당 30만 원 매수 예산), 유통주식수 500만~4,000만 주 탄력 중소형주 우선.

### 2. 🔴 매도 로직 (추세 추종 청산)
* **15분봉 단순 5이평선이 40이평선을 하향 돌파(Dead Cross)** 할 때 보유 물량 전량 시장가 매도.
* 불필요한 단기 노이즈에 털리지 않고 1~3일간 상승 랠리를 온전히 향유하며, 추세 이탈 시 최소 손실로 방어.

### 3. 🛡️ 시장 지수 급락 방어 (MarketIndexGuard)
* 코스피(`069500`) 또는 코스닥(`229200`) 당일 지수가 **-1.5% 이하로 급락**하거나 15분봉 하락 추세 시 **신규 매수를 자동으로 일시 정지**하여 자산을 보호.

---

## 📂 핵심 소스코드 구조 (Core Architecture)

```text
├── MovingAveragelineTraid/execution/
│   ├── trading_bot.py           # 🤖 메인 트레이딩 봇 (BuyManager, SellManager, MarketIndexGuard)
│   ├── strategy_buy.py          # 🎯 일봉/30분봉 + WMA(5,20) 고가선 매수 시그널 분석기
│   ├── strategy_sell.py         # 🚪 15분봉 SMA(5,40) 데드크로스 매도 시그널 분석기
│   ├── real_api_adapter.py      # 🔌 키움 REST API 어댑터 (15분봉, 30분봉, 일봉 캔들 조회)
│   ├── utils.py                 # 🛠️ 호가 단위(Tick) 계산 및 TradeState 상태 관리
│   └── today_picks.json         # 📋 실시간 감시 종목 리스트 (스캐너 및 웹소켓 자동 연동)
│
├── real trading/
│   ├── kiwoom_client.py         # 🔑 키움 REST API 인증, 잔고 조회 및 주문 발송 엔진
│   ├── websocket_client.py      # ⚡ 키움 실시간 조건검색(편입/이탈) 웹소켓 클라이언트
│   └── config.py                # ⚙️ 환경변수(.env) 설정 로더
│
├── scan_weekend_picks.py        # 🔍 전략 맞춤형 유망 공략주 사전 발굴 스캐너
├── backtest_5days.py            # 📊 최근 5일간 실전 캔들 시뮬레이션 백테스터
└── run_moving_average_bot.bat   # 🚀 원클릭 봇 실행 배치 파일
```

---

## ⚙️ 실행 방법

### 1. 환경변수 설정 (`.env`)
프로젝트 루트 또는 `real trading/` 폴더의 `.env` 파일에 키움증권 API 키를 설정합니다:
```env
KIWOOM_APP_KEY="your_app_key"
KIWOOM_REAL_APP_SECRET="your_app_secret"
KIWOOM_REAL_ACCOUNT_NUM="your_account_number"
```

### 2. 주말/휴장일 유망주 사전 스캔
```bash
python scan_weekend_picks.py
```

### 3. 실전 자동매매 봇 가동
```bash
run_moving_average_bot.bat
```
또는
```bash
python "MovingAveragelineTraid\execution\trading_bot.py"
```
