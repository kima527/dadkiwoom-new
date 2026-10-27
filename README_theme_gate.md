# 60분봉 테마급등관문선 & 테마기준선 순환 매매 전략

영웅문(키움 HTS) 사용자 지표 3대 수식(테마급등관문선, 급등관문고가선, 테마기준선)을 결합하여
60분봉에서 분할 매수 및 익절을 수행하고, 일봉 테마 5-20 데드크로스 발생 시 전량 청산 및 종료하는 자동매매 알고리즘입니다.

---

## 1. 3대 수식 요약

1. **테마급등관문선 (Theme Surge Gate Line)**:
   - $TEMA_1 = TEMA(C, 5)$
   - $TEMA_2 = TEMA(C, 20)$
   - 조건: `CrossUp(TEMA1, TEMA2)`
   - 지표선: `ValueWhen(1, 조건, TEMA1)`
   - 매매 규칙: 하락변곡을 하던 테마급등관문선이 **상승변곡(저점 상승 U턴)**을 시작할 때 **예수금 50% 1차 매수**.

2. **급등관문고가선 (Theme Gate High Line)**:
   - $MM = TEMA(C, 5)$, $MN = TEMA(C, 20)$
   - 조건: `CrossUp(MM, MN)`
   - 지표선: $HH = \text{ValueWhen}(1, \text{조건}, H)$
   - 매매 규칙: 주가가 급등관문고가선을 상향 돌파 시 **예수금 50% 2차 추가 매수 (100% 진입)**.

3. **테마기준선 (Theme Base Line / 피크 M선)**:
   - $a = SMA(C, 5), b = SMA(C, 20), d = SMA(C, 60)$
   - $K = \text{ValueWhen}(1, a > b \ \& \ b > d \ \& \ a > d, C)$
   - 지표선: $\text{ValueWhen}(1, K(2) < K(1) \ \& \ K(1) > K, K(1))$
   - 매매 규칙: 주가가 테마기준선을 상향 돌파 시 **전량 익절 매도**.

4. **재매수 및 순환 규칙**:
   - 익절 후 주가가 다음 테마급등관문선에 지지/도달 시 **동일 수량 재매수**.
   - 다시 테마기준선 돌파 시 **재매도 익절**.

5. **상위 종료 규칙**:
   - **일봉 기준 테마(5)-테마(20) 데드크로스** 발생 시 보유 수량 전량 시장가 청산 및 전략 사이클 종료.

---

## 2. 파일 구조 (3-Layer Architecture)

```
PythonWorksplace2/
├── directives/
│   └── theme_gate_60m_strategy.md   # [Layer 1] 전략 표준운영절차(SOP)
├── execution/                        # [Layer 3] 결정론적 파이썬 실행 모듈
│   ├── config.py                     # 기간 파라미터 및 계좌/리스크 설정
│   ├── indicators.py                 # 영웅문 수식 100% 일치 파이썬 계산 모듈
│   ├── strategy.py                   # 60분봉 상태머신 매매 전략 엔진
│   ├── backtest.py                   # 백테스트 실행 및 성과 분석
│   ├── generate_sample_data.py       # 60분봉 및 일봉 데이터셋 생성기
│   └── run_live_bot_template.py      # 실전/모의투자 실시간 연동 봇 템플릿
├── .tmp/                             # 임시 캐시 및 백테스트 로그
├── requirements.txt                  # 필수 의존 패키지
├── AGENTS.md                         # 3-Layer 아키텍처 규칙
└── README.md                         # 전략 설명서
```

---

## 3. 실행 방법

### 백테스트 실행
```powershell
python execution/backtest.py
```

### 실시간 봇 템플릿 실행
```powershell
python execution/run_live_bot_template.py
```
