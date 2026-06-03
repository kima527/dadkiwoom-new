# Kiwoom 15-Min Chart Trading Bot

이 리포지토리는 사용자의 전략에 맞춰 최적의 주도주 1종목을 선정하고 거래하는 자동매매 봇 시스템입니다.

## 🔒 핵심 로직 변경 제한 규정 (CRITICAL LOGIC LOCK)

본 봇의 종목 선정 및 정렬 로직은 사용자의 핵심 투자 철학이 반영된 설계이므로, **사용자의 명시적인 동의 없이 코드를 수정하거나 덮어쓰는 행위가 엄격히 금지**되어 있습니다.

### 1. 스캔 및 랭킹 정렬 알고리즘 (Momentum Score)
봇은 매 영업일 아침 종목을 선정하거나 실시간 모니터링 시 다음 기준을 종합해 `Score`를 산출하여 우선순위를 정합니다.

1. **정배열 상태 가산점 (+100점)**
   * `15분봉 5이평선 > 20이평선` 일 때 가산점 부여 (상승 추세 확보).
2. **이격 확장 가속도 가산점 (+100점 + 확장율 비례 점수)**
   * `(5이평 - 20이평)_현재 >= (5이평 - 20이평)_직전` 일 때 (이격이 좁혀지지 않고 벌어지거나 유지되며 올라가는 경우) 가산점 부여 및 확장 폭 기여도 가중치를 더해줌.
3. **등락률 가중치 (+10 * 등락률%)**
   * 당일 등락률이 높은 상위 주도주일수록 점수를 높게 반영하여 최우선적으로 거래되도록 제어.

### 2. 대상 소스코드 위치
* [Paper trading/main.py](file:///c:/Users/zoela/OneDrive/바탕 화면/PythonWorksplace/Paper trading/main.py)
  * `Dynamic Daily Stock Selection` 블록 (아침 종목 스캐너)
  * `Phase 1 & Phase 2` 블록 (실시간 모니터링 랭킹 정렬 및 대시보드 스냅샷 전송)
* [Paper trading/kiwoom_client.py](file:///c:/Users/zoela/OneDrive/바탕 화면/PythonWorksplace/Paper trading/kiwoom_client.py)
  * `get_top_fluctuation_stocks_with_rates` (실시간 등락률 조회 모듈)

향후 로직의 버그 수정이나 보완 시에도 이 **모멘텀 스코어 공식의 대전제**를 유지해야 합니다.
