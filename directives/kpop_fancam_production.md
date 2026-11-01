# SOP: K-Pop 9:16 콘서트 스포트라이트 직캠 자동 제작 파이프라인 (Concert Spotlight Fancam Production)

## 1. 목적 (Goal)
K-Pop 다인원 군무(Choreography) 고화질 영상(4K/FHD)을 분석하여:
1. **9:16 FHD 세로 직캠 포맷($1080 \times 1920$)**으로 자동 크롭 및 짐벌 센터링.
2. **8등신 황금 신체 비율 리매핑(골반 아래 비선형 $+7\%$ 다리 연장)**을 모든 멤버에게 자동 적용.
3. **무대 중앙 원형/타원형 콘서트 스포트라이트 조명(Center Stage Spotlight)**과 **바닥 조명 풀(Floor Highlight Pool)** 합성.
4. **멤버 무제한 보존**: 인위적인 마스킹이나 암전으로 멤버를 지우지 않고, 화면에 잡힌 모든 댄서를 100% 온전하게 보존.
5. **얼굴 100% 무손실 보존**: 어색한 2D 스티커/필터 없이 원본 아티스트의 생생한 표정 유지.
6. **엔딩 로고 자동 제거**: 피날레 안무 후 블랙 페이드아웃 지점을 감지하여 뒤따라오는 기획사 아웃트로 로고 카드를 자동 트림.
7. **마스터 고음질(320kbps AAC) 오디오 무손실 싱크 결합**.

---

## 2. 3계층 아키텍처 역할

- **Layer 1: Directive (본 문서)**: `directives/kpop_fancam_production.md`
  - 제작 원칙, 조명 수식, 비율 보정 그리드, 엔딩 트림 규칙 정의.
- **Layer 2: Orchestration (AI 에이전트)**:
  - 영상 입력/출력 경로 확인, FFmpeg 하드웨어 가속 스트림 파이프라인 제어, 렌더링 후 무결성 및 스냅샷 검증.
- **Layer 3: Execution (결정론적 파이썬 도구)**:
  - `execution/render_kpop_spotlight_fancam.py`: 독립 실행형 프로덕션 CLI 스크립트.
  - `kpop_dance_3d/core/render_concert_spotlight_full.py`: 전체 3분 50초 렌더러.

---

## 3. 핵심 수식 및 알고리즘

### (1) 8등신 신체 비율 리매핑 (8-Head Proportion Remapping)
- 상체($Y < 0.42 \times H$): 머리 크기, 얼굴 표정, 어깨 균형을 1:1 원본 비율로 보존.
- 하체($Y \ge 0.42 \times H$): 비선형 수축 계수 $0.935$를 적용하여 골반 아래 다리 라인을 약 $+7\%$ 부드럽게 연장.
```python
split_y = int(out_h * 0.42)
y_indices = np.arange(out_h, dtype=np.float32)
src_y = np.where(y_indices < split_y,
                 y_indices,
                 split_y + (y_indices - split_y) * 0.935).astype(np.float32)
src_x = np.tile(np.arange(out_w, dtype=np.float32), (out_h, 1))
src_y_grid = np.tile(src_y[:, np.newaxis], (1, out_w))
proportioned = cv2.remap(frame, src_x, src_y_grid, interpolation=cv2.INTER_LINEAR)
```

### (2) 콘서트 스포트라이트 조명 합성 (Concert Stage Spotlight)
- **상체/센터 집중 빔(Stage Cone)**:
  $$d_{\text{stage}} = \sqrt{\left(\frac{X - C_x}{R_x}\right)^2 + \left(\frac{Y - C_y}{R_y}\right)^2}$$
  - $C_x = 540$, $C_y = 1050$, $R_x = 480$, $R_y = 780$.
  - 중심부 $108\%$ 광택감, 외곽 $32\%$ 콘서트홀 어둠으로 Hermite Smoothstep 감쇄.
- **바닥 원형 조명 풀(Floor Pool)**:
  $$d_{\text{floor}} = \sqrt{\left(\frac{X - C_x}{440}\right)^2 + \left(\frac{Y - 1480}{320}\right)^2}$$
  - 바닥 영역에 $+12\%$ 은은한 하이라이트 풀 추가.
- **가우시안 페더링($61 \times 61$)**: 렌즈 광학 디퓨전 효과 연출.

### (3) 엔딩 로고 자동 트림 (Outro Logo Removal)
- 공연 종료 후 블랙 페이드아웃 지점(프레임 평균 밝기 $\le 0.05$)을 감지.
- 뒤따라오는 기획사 로고(Big Hit Entertainment 등) 시작 직전 프레임에서 무손실 트림.

---

## 4. 실행 방법 (CLI)

```bash
# 기본 실행 (BTS Dynamite 기준)
python execution/render_kpop_spotlight_fancam.py

# 파라미터 지정 실행
python execution/render_kpop_spotlight_fancam.py \
  --input "D:/download/source_video.mp4" \
  --output "D:/BTS/My_Kpop_Fancam.mp4" \
  --crop-w 1600 \
  --center-x 1820 \
  --trim-logo
```

