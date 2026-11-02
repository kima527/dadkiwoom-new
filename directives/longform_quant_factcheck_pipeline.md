# 롱폼 퀀트 팩트체크 영상 완전 자동 제작 파이프라인 SOP

## 1. 목적 (Goal)
- 주식 서적이나 커뮤니티에 널리 퍼진 기법(골든크로스, 볼린저밴드 등)을 코스피 10년 데이터로 전수조사하고, 퀀트 필터 개선 전략을 제시하는 16:9 Full HD (1920x1080) 롱폼 유튜브 영상 자동 제작.

## 2. 입력 및 산출물 (Inputs & Outputs)
- **입력 (Inputs)**:
  - 10개년 코스피 200 시뮬레이션 데이터 및 퀀트 필터 전략 조건
  - 슬라이드별 대본 및 전문 금융 내레이션(`ko-KR-InJoonNeural`)
- **최종 산출물 (Deliverables in `D:\DailyQuant`)**:
  - `LongForm_Ep1_GoldenCross_FactCheck.mp4` (Full HD 본편 영상, 오프닝 커버 포함 ~5분 30초)
  - `LongForm_Ep1_Cover_Video.mp4` (단독 14.5초 커버 홍보 영상)
  - `LongForm_Ep1_Thumbnail.png` (16:9 고대비 썸네일/커버 아트워크)
  - `LongForm_Ep1_YouTube_Metadata.txt` (유튜브 업로드용 제목, 설명글, 태그, 챕터 타임스탬프)
- **바탕화면 바로가기**:
  - `오늘의 퀀트 롱폼 본편 바로보기.lnk`
  - `오늘의 퀀트 롱폼 커버영상 바로보기.lnk`

## 3. 실행 스크립트 체계 (Execution Scripts in `execution/`)
1. `run_golden_cross_backtest.py`: 코스피 10년 전수조사 백테스트 및 자산 성장 곡선 데이터 생성 (`.tmp/backtest_golden_cross.json`)
2. `generate_longform_thumbnail.py`: 16:9 고반응 썸네일 생성 (`D:\DailyQuant\LongForm_Ep1_Thumbnail.png`)
3. `generate_longform_slides.py`: 8개 슬라이드(커버 포함) 1920x1080 고화질 렌더링 (`.tmp/slides/`)
4. `generate_longform_script_audio.py`: 8개 챕터별 Edge-TTS AI 음성 합성 및 타이밍 JSON 생성 (`.tmp/audio/`)
5. `render_longform_video.py`: FFmpeg 기반 슬라이드-오디오 파트별 인코딩, 단독 커버영상 추출, 무손실 Concat 병합
6. `build_longform_ep1.py`: 원클릭 통합 파이프라인 빌더
7. `run_longform_ep1.bat`: 윈도우 원클릭 배치 파일

## 4. 레이아웃 & 비디오 원칙 (Learned Rules)
- **Matplotlib 박스 레이아웃**:
  - 다중 텍스트 박스는 상단 기준점(`va='top'`) 및 `linespacing=1.45` 적용 필수 (중앙 정렬 시 제목-본문 겹침 방지).
  - 차트 및 곡선 좌표는 반드시 `np.clip`을 적용하여 카드 경계선(`y=24~56`)을 절대 이탈하지 않도록 엄격 제한.
- **오프닝 커버 영상**:
  - 본편 영상 시작 시 썸네일 커버 페이지와 오프닝 훅 나레이션을 0초~14.5초간 노출하여 클릭 후 이탈 방지.

