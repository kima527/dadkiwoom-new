# SOP: 테마 선정 및 실시간 뉴스 모멘텀 결합 매매 지침 (Theme & News Selection SOP)

## 1. 목적 (Goal)
- 주식 시장에서 자금이 집중되는 **진짜 주도 테마(Market-Leading Themes)**를 정량적으로 발굴
- 테마 내 3등 이하 후발주(Follower)를 철저히 배제하고 **오직 1등 대장주(Leader)와 2등 부대장주(Second Leader)**만 압축 매매
- 실시간 뉴스 및 모멘텀 분석을 결합하여 초대형 호재는 가점(+25점), 긴급 악재(CB, 횡령, 유상증자 등)는 선제적 매수 즉각 차단

---

## 2. 3계층 아키텍처 역할 분담 (3-Layer Architecture)

### Layer 1: Directive (지침)
- 본 문서 (`directives/theme_and_news_selection.md`)

### Layer 2: Orchestration (의사결정)
- `trading_bot.py`:
  - 08:30~08:55: `premarket_scanner.py` 자동 호출하여 당일 주도 테마 및 캡틴 대장주 사전 로드
  - 장중 15분 주기: `theme_manager.py`를 통해 실시간 테마 순위 및 대장주 가중치 동적 갱신
  - 장중 매수 검토 시: `news_agent.py`를 호출하여 긴급 악재 차단 및 뉴스 보너스 가산

### Layer 3: Execution (결정론적 실행 모듈)
- `execution/theme_manager.py`: 네이버 모바일 증권 JSON API 기반 대장주/부대장주 식별 및 가중치 산출
- `execution/news_agent.py`: 네이버 종목 뉴스 수집 + Gemini 3.8 Flash AI 분석 + 금융 특화 NLP 키워드 폴백
- `execution/premarket_scanner.py`: 장전 상위 테마 분석, 대장주 선별, 워치리스트 동기화 및 텔레그램 브리핑

---

## 3. 테마 및 대장주 판별 공식 (Theme & Leader Formula)

1. **테마 내 종목 위계(Role) 판별**:
   - `정렬 기준`: 누적 거래대금(`accumulatedTradingValueRaw`) 최우선 + 등락률(`fluctuationsRatio`) 차우선
   - **👑 1등 (LEADER, 대장주)**: 테마 내 자금이 가장 많이 쏠리고 주도하는 핵심 종목
   - **🥈 2등 (SECOND, 부대장주)**: 대장주를 바로 뒤따르는 2순위 수급 종목
   - **🥉 3등 이하 (FOLLOWER, 후발주)**: 설거지 및 뇌동매매 위험 종목

2. **차등 가중치 배분 (Differential Weighting)**:
   - **Top 1~3위 테마 (초강력 주도 테마)**: 대장주 `1.40x`, 부대장주 `1.20x`, 후발주 `0.85x` (감점)
   - **Top 4~10위 테마 (주력 테마)**: 대장주 `1.30x`, 부대장주 `1.10x`, 후발주 `0.85x` (감점)
   - **Top 11~30위 테마 (일반 테마)**: 대장주 `1.20x`, 부대장주 `1.05x`, 후발주 `0.85x` (감점)
   - **테마 미포함 일반 종목**: 기본 `1.00x`

---

## 4. 실시간 뉴스 및 모멘텀 평가 규칙 (News Momentum Rules)

1. **평가 채널**:
   - 네이버 모바일 증권 종목 뉴스 API (`https://m.stock.naver.com/api/news/stock/{code}?pageSize=5`)
2. **AI 및 NLP 이중화 체계**:
   - 1차: Gemini 3.8 Flash API를 통한 0~100점 점수화 (85점+ 초대형 호재, 40점 이하 악재)
   - 2차 (폴백): API 크레딧 소진(`402`) 또는 장애 시 금융 특화 NLP 키워드 사전 자동 동작
3. **긴급 매수 차단(Emergency Block)**:
   - 다음 키워드/악재 검출 시 즉각 매수 중단:
     - `전환사채`, `CB 발행`, `신주인수권부사채`, `BW 발행`, `유상증자`(주주배정/일반공모), `횡령`, `배임`, `압수수색`, `거래정지`, `감자`, `상장폐지`
   - 제3자배정 유상증자는 자금 유치 성격이므로 예외 허용

---

## 5. 실행 워크플로우 (Daily Timeline)

- **08:35**: `run_premarket_scan.bat` 또는 `trading_bot.py`에 의해 장전 자동 스캔 발동
  - 오늘의 주도 3대 테마 및 캡틴 대장주 5~6개 발굴
  - `today_picks.json` 및 `watchlist.json`에 가중치(1.40x/1.20x) 탑재
  - 텔레그램 브리핑 자동 발송
- **09:00 ~ 15:30**: `trading_bot.py` 정규장 매매 가동
  - 조건검색 편입(`on_insert`) 즉시 대장주 여부 및 실시간 뉴스 악재 체크 후 0.1초 스나이핑
  - 매수 검토 시: `final_score = (base_score + supply_bonus + news_bonus) * weight`
  - 15분마다 실시간 테마 및 대장주 재평가(`refresh_realtime_themes`)

---

## 6. 예외 처리 및 학습 사항 (Self-Annealing)

- **Gemini API 크레딧 소진 (402 Resource Exhausted)**:
  - AI 호출 오류를 감싸서 자동으로 `NLP_KEYWORD` 모드로 전환되도록 설계되어 시스템 다운 위험 없음
- **네이버 PC 웹 URL 개편**:
  - 네이버 웹 개편에 영향받지 않도록 초고속 모바일 JSON API(`m.stock.naver.com/api/...`)를 기본 채택
- **아티팩트 및 산출물**:
  - 장전 리포트는 `.tmp/premarket_theme_report_{YYYYMMDD}.json`에 저장 (언제든 재분석 가능)
