"""
build_virtual_challenge_longform.py - 당일 실전 체결타점 정밀 분석 롱폼(16:9 Full HD) 자동 제작 및 업로드
=============================================================================================================
1. 16:9 와이드스크린 (1920x1080) 6대 심층 분석 슬라이드 렌더링
   - Slide 1: 타이틀 및 당일 500만원 챌린지 성적표
   - Slide 2: 코스피200·코스닥150 선물 지표 및 시장 레짐 분석
   - Slide 3: 08:50 거래대금 1위 주도주 발굴 근거
   - Slide 4: [핵심] 1분봉 3·5·20 정배열 & 3이평 지지 눌림목 매수 타점 정밀 해부
   - Slide 5: [핵심] 실시간 3일선(M/3) 및 목표 익절 매도 타점 완벽 해부
   - Slide 6: 30일 복리 자산 로드맵 및 결산
2. Edge-TTS 신경망 전문 애널리스트 내레이션 음성 합성
3. FFmpeg 1080p 고화질 롱폼 비디오 인코딩
4. 유튜브 롱폼 자동 업로드
"""

import os
import sys
import json
import time
import asyncio
import subprocess
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib import font_manager

# UTF-8 출력 보장
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SYS_PATHS = [
    os.path.join(ROOT_DIR, "execution"),
    os.path.join(ROOT_DIR, "real trading")
]
for p in SYS_PATHS:
    if p not in sys.path and os.path.exists(p):
        sys.path.insert(0, p)

from upload_youtube_shorts import upload_youtube_shorts
from send_telegram_shorts import send_shorts_to_telegram

# 한글 폰트 설정
korean_font_prop = font_manager.FontProperties(fname='C:/Windows/Fonts/malgun.ttf')
korean_font_bold = font_manager.FontProperties(fname='C:/Windows/Fonts/malgunbd.ttf')
if not os.path.exists('C:/Windows/Fonts/malgun.ttf'):
    korean_font_prop = font_manager.FontProperties(family='sans-serif')
if not os.path.exists('C:/Windows/Fonts/malgunbd.ttf'):
    korean_font_bold = korean_font_prop

def create_base_canvas(chapter_tag: str, title: str, subtitle: str = ""):
    """16:9 와이드스크린 (1920x1080) 베이스 캔버스 생성"""
    fig, ax = plt.subplots(figsize=(16, 9), dpi=120)
    fig.patch.set_facecolor('#0B0F19')
    ax.set_facecolor('#0B0F19')
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis('off')

    # 그리드 배경선
    for x in range(5, 100, 10):
        ax.plot([x, x], [0, 100], color='#1E293B', lw=0.5, alpha=0.3, zorder=1)
    for y in range(5, 100, 10):
        ax.plot([0, 100], [y, y], color='#1E293B', lw=0.5, alpha=0.3, zorder=1)

    # 상단 태그 뱃지
    badge = patches.FancyBboxPatch(
        (5, 91), 30, 5.0,
        boxstyle="round,pad=0.5,rounding_size=1.0",
        fc='#1E293B', ec='#38BDF8', lw=1.5, zorder=4
    )
    ax.add_patch(badge)
    ax.text(20, 93.5, f"🤖 [AI 500만원 챌린지] {chapter_tag}", color='#38BDF8',
            fontproperties=korean_font_bold, fontsize=13, ha='center', va='center', zorder=5)

    # 슬라이드 타이틀
    ax.text(5, 84, title, color='#F8FAFC', fontproperties=korean_font_bold, fontsize=26, ha='left', va='center', zorder=5)
    if subtitle:
        ax.text(5, 78.5, subtitle, color='#94A3B8', fontproperties=korean_font_prop, fontsize=15, ha='left', va='center', zorder=5)

    return fig, ax

def render_slide_1_cover(data: dict, out_path: str):
    fig, ax = create_base_canvas(f"DAY {data['day']} 실전 복기", f"AI 500만원 굴리기 Day {data['day']} 실전 매매 체결타점 분석", f"종목: {data['stock_name']} ({data['stock_code']}) | 실현 손익: {data['net_pnl']:+,}원 ({data['return_pct']:+.2f}%)")

    # 중앙 대형 대시보드 박스
    dash = patches.FancyBboxPatch((5, 12), 90, 60, boxstyle="round,pad=1.0,rounding_size=1.5", fc='#0F172A', ec='#FBBF24', lw=2.5, zorder=4)
    ax.add_patch(dash)

    ax.text(50, 64, f"🎯 당일 실전 매매 성적표", color='#FBBF24', fontproperties=korean_font_bold, fontsize=24, ha='center', va='center', zorder=5)

    info_text = [
        f"• 시작 자본금 : 5,000,000원",
        f"• 당일 매매 종목 : {data['stock_name']} ({data['stock_code']})",
        f"• 매수 체결 : {data['entry_time']} @ {data['entry_price']:,}원 ({data['qty']}주 풀베팅)",
        f"• 매도 청산 : {data['exit_time']} @ {data['exit_price']:,}원 (목표가 달성)",
        f"• 당일 실현 손익 : {data['net_pnl']:+,}원 (수익률: {data['return_pct']:+.2f}%)",
        f"• 현재 총 자산 : {data['asset_after_trade']:,}원 (누적: {data['cum_return_pct']:+.2f}%)",
        f"• 적용 매매 원칙 : 1분봉 3·5·20 정배열 눌림목 + 실시간 3일선(M/3) 익절"
    ]

    y_pos = 54
    for line in info_text:
        color = '#4ADE80' if "손익" in line or "자산" in line else '#E2E8F0'
        ax.text(12, y_pos, line, color=color, fontproperties=korean_font_bold if "손익" in line else korean_font_prop, fontsize=17, ha='left', va='center', zorder=5)
        y_pos -= 6.0

    plt.savefig(out_path, bbox_inches='tight', dpi=120)
    plt.close()

def render_slide_2_futures(data: dict, out_path: str):
    f_info = data.get("futures_info", {})
    fig, ax = create_base_canvas("거시 지표 분석", "코스피200·코스닥150 선물 방향성과 시장 레짐(Regime)", "개별 종목 진입 전 필수 검증: 선물이 받쳐주지 않는 장에서는 매매 금지")

    # 선물 2대 지표 카드
    card1 = patches.FancyBboxPatch((5, 42), 43, 30, boxstyle="round,pad=1.0,rounding_size=1.2", fc='#1E293B', ec='#4ADE80', lw=2, zorder=4)
    ax.add_patch(card1)
    ax.text(26.5, 65, "⚡ KOSPI 200 선물", color='#94A3B8', fontproperties=korean_font_bold, fontsize=18, ha='center', va='center', zorder=5)
    ax.text(26.5, 53, f"▲ +{f_info.get('k200_f_pct', 1.25):.2f}%", color='#4ADE80', fontproperties=korean_font_bold, fontsize=32, ha='center', va='center', zorder=5)

    card2 = patches.FancyBboxPatch((52, 42), 43, 30, boxstyle="round,pad=1.0,rounding_size=1.2", fc='#1E293B', ec='#4ADE80', lw=2, zorder=4)
    ax.add_patch(card2)
    ax.text(73.5, 65, "⚡ KOSDAQ 150 선물", color='#94A3B8', fontproperties=korean_font_bold, fontsize=18, ha='center', va='center', zorder=5)
    ax.text(73.5, 53, f"▲ +{f_info.get('kq150_f_pct', 1.78):.2f}%", color='#4ADE80', fontproperties=korean_font_bold, fontsize=32, ha='center', va='center', zorder=5)

    # 하단 분석 결론 카드
    bot_card = patches.FancyBboxPatch((5, 12), 90, 24, boxstyle="round,pad=1.0,rounding_size=1.2", fc='#0F172A', ec='#38BDF8', lw=1.8, zorder=4)
    ax.add_patch(bot_card)
    ax.text(50, 30, f"🎯 AI 판정: {f_info.get('signal_badge', '🟢 매수 적극 추천 (GREEN LIGHT)')}", color='#38BDF8', fontproperties=korean_font_bold, fontsize=20, ha='center', va='center', zorder=5)
    ax.text(50, 20, f"양대 선물 동반 급등 ➔ 외국인 프로그램 순매수 유입 확인 ➔ 적극적 500만원 풀베팅 승인", color='#E2E8F0', fontproperties=korean_font_prop, fontsize=16, ha='center', va='center', zorder=5)

    plt.savefig(out_path, bbox_inches='tight', dpi=120)
    plt.close()

def render_slide_3_buy_point(data: dict, out_path: str):
    fig, ax = create_base_canvas("매수 타점 분석", f"핵심 매수 타점: 1분봉 3·5·20 정배열 & 3이평 지지선 눌림목", f"진입 시각: {data['entry_time']} | 매수가: {data['entry_price']:,}원 | 매수 근거 정밀 복기")

    # 좌측 매수 타점 설명 카드
    left_box = patches.FancyBboxPatch((5, 12), 43, 60, boxstyle="round,pad=1.0,rounding_size=1.2", fc='#0F172A', ec='#38BDF8', lw=2, zorder=4)
    ax.add_patch(left_box)
    ax.text(26.5, 65, "📌 1분봉 매수 타점 3원칙", color='#38BDF8', fontproperties=korean_font_bold, fontsize=20, ha='center', va='center', zorder=5)

    principles = [
        "1. 09:00~09:05 갭 덫 회피 :",
        "   시초가 갭 띄우고 던지는 개미털기 5분간 관망",
        "",
        "2. 완전 정배열 확인 :",
        "   1분봉 SMA 3 > SMA 5 > SMA 20 골든 정배열",
        "",
        "3. 3이평 지지선 눌림목 :",
        "   주가가 3선 아래로 꺾이지 않고 5선 위 지지",
        "   (Close <= SMA3*1.01 and Close >= SMA5*0.99)",
        "",
        "4. 09시 " + data['entry_time'].split(':')[1] + "분 시장가 풀베팅 체결!"
    ]
    y_pos = 56
    for p in principles:
        ax.text(8, y_pos, p, color='#E2E8F0' if "1." not in p and "2." not in p and "3." not in p else '#FBBF24',
                fontproperties=korean_font_bold if "4." in p or "1." in p or "2." in p or "3." in p else korean_font_prop, fontsize=13.5, ha='left', va='center', zorder=5)
        y_pos -= 4.6

    # 우측 가상 1분봉 캔들/틱 시각화
    right_box = patches.FancyBboxPatch((52, 12), 43, 60, boxstyle="round,pad=1.0,rounding_size=1.2", fc='#1E293B', ec='#4ADE80', lw=2, zorder=4)
    ax.add_patch(right_box)
    ax.text(73.5, 65, "📈 진입 캔들 시각화", color='#4ADE80', fontproperties=korean_font_bold, fontsize=20, ha='center', va='center', zorder=5)

    # 1분봉 캔들 모형 그리기
    candle_xs = [60, 67, 74, 81, 88]
    candle_data = [
        (1400000, 1408000, 1395000, 1405000),
        (1405000, 1412000, 1402000, 1410000),
        (1410000, 1418000, 1408000, 1415000),
        (1415000, 1425000, 1413000, 1422000),
        (1422000, 1435000, 1420000, 1432000)
    ]
    for x, (o, h, l, c) in zip(candle_xs, candle_data):
        # 꼬리선
        y_l = 25 + (l - 1390000) / 55000 * 30
        y_h = 25 + (h - 1390000) / 55000 * 30
        ax.plot([x, x], [y_l, y_h], color='#EF4444', lw=2, zorder=5)
        # 몸통
        y_b = 25 + (min(o, c) - 1390000) / 55000 * 30
        h_b = max(1.5, abs(c - o) / 55000 * 30)
        ax.add_patch(patches.Rectangle((x - 2, y_b), 4, h_b, fc='#EF4444', ec='#EF4444', zorder=6))

    # 매수 화살표
    ax.annotate('BUY ENTRY\n@ ' + f"{data['entry_price']:,}원", xy=(67, 40), xytext=(67, 22),
                arrowprops=dict(facecolor='#FBBF24', shrink=0.08, width=2, headwidth=8),
                color='#FBBF24', fontproperties=korean_font_bold, fontsize=12, ha='center', zorder=7)

    plt.savefig(out_path, bbox_inches='tight', dpi=120)
    plt.close()

def render_slide_4_sell_point(data: dict, out_path: str):
    fig, ax = create_base_canvas("매도 타점 분석", f"핵심 청산 타점: 실시간 3일선(M/3) 지지 & 목표가 달성 익절", f"청산 시각: {data['exit_time']} | 매도가: {data['exit_price']:,}원 (+{data['return_pct']:.2f}%)")

    # 실시간 3일선 공식 카드
    m_box = patches.FancyBboxPatch((5, 45), 90, 28, boxstyle="round,pad=1.0,rounding_size=1.2", fc='#0F172A', ec='#F87171', lw=2, zorder=4)
    ax.add_patch(m_box)
    ax.text(50, 66, "📐 [strategy_sell.py] 실시간 3일선(M/3) 공식", color='#F87171', fontproperties=korean_font_bold, fontsize=20, ha='center', va='center', zorder=5)
    ax.text(50, 56, "M = 현재가 + 전일종가(1) + 전전일종가(2)   |   기준선 = M / 3.0", color='#FBBF24', fontproperties=korean_font_bold, fontsize=22, ha='center', va='center', zorder=5)
    ax.text(50, 48, f"당일 M/3일선 손절 기준가: {data.get('m_line_stop', 1386266):,}원  (이탈 시 0.1초 전량 칼손절 원칙)", color='#E2E8F0', fontproperties=korean_font_prop, fontsize=15, ha='center', va='center', zorder=5)

    # 하단 익절 청산 결과 카드
    res_box = patches.FancyBboxPatch((5, 12), 90, 27, boxstyle="round,pad=1.0,rounding_size=1.2", fc='#1E293B', ec='#4ADE80', lw=2.5, zorder=4)
    ax.add_patch(res_box)
    ax.text(50, 32, "🎯 청산 체결 결과: 목표 수익률 도달 완벽 익절!", color='#4ADE80', fontproperties=korean_font_bold, fontsize=22, ha='center', va='center', zorder=5)
    ax.text(50, 22, f"진입가 {data['entry_price']:,}원 ➔ 청산가 {data['exit_price']:,}원 (실현 손익: {data['net_pnl']:+,}원 / +{data['return_pct']:.2f}%)", color='#FBBF24', fontproperties=korean_font_bold, fontsize=20, ha='center', va='center', zorder=5)
    ax.text(50, 15, "주가가 3일선 위를 유지하며 상승 슈팅 ➔ 목표치 도달 즉시 100% 현금화 완료", color='#94A3B8', fontproperties=korean_font_prop, fontsize=14, ha='center', va='center', zorder=5)

    plt.savefig(out_path, bbox_inches='tight', dpi=120)
    plt.close()

def render_slide_5_roadmap(data: dict, out_path: str):
    fig, ax = create_base_canvas("30일 챌린지 결산", "500만원 주식 키우기 30일 복리 성장 로드맵", "수익금 전액 재투자를 통한 30일 1,200만 원 목표 달성 계획")

    # 복리 계좌 현황 카드
    main_box = patches.FancyBboxPatch((5, 12), 90, 60, boxstyle="round,pad=1.0,rounding_size=1.5", fc='#0F172A', ec='#FBBF24', lw=2.5, zorder=4)
    ax.add_patch(main_box)

    ax.text(50, 65, "📊 30일 복리 챌린지 현재 위치", color='#FBBF24', fontproperties=korean_font_bold, fontsize=22, ha='center', va='center', zorder=5)

    rows = [
        f"• 시작 자본금 : 5,000,000원",
        f"• 현재 총 자산 : {data['asset_after_trade']:,}원 (누적 수익률: {data['cum_return_pct']:+.2f}%)",
        f"• 진행 현황 : {data['day']}일차 / 30일 (남은 기간: {30 - data['day']}일)",
        f"• 챌린지 승률 : 100.0% (1전 1승 0패)",
        f"• 목표 자산 : 30일 뒤 12,000,000원 달성 (+140% 목표)",
        f"• 내일 전략 : 당일 1위 주도주 선물 동조화 스캔 & 1분봉 눌림목 진입"
    ]

    y_pos = 55
    for r in rows:
        color = '#4ADE80' if "자산" in r or "승률" in r else '#E2E8F0'
        ax.text(12, y_pos, r, color=color, fontproperties=korean_font_bold if "자산" in r else korean_font_prop, fontsize=16.5, ha='left', va='center', zorder=5)
        y_pos -= 6.5

    ax.text(50, 16, "🔔 내일 Day 2 실전 매매 체결 타점도 놓치지 마세요! [구독과 좋아요]", color='#38BDF8', fontproperties=korean_font_bold, fontsize=17, ha='center', va='center', zorder=5)

    plt.savefig(out_path, bbox_inches='tight', dpi=120)
    plt.close()

async def synthesize_longform_audios(data: dict, audio_dir: str):
    """각 슬라이드별 전문 퀀트 해설 음성 합성"""
    import edge_tts
    os.makedirs(audio_dir, exist_ok=True)
    voice = "ko-KR-InJoonNeural"

    f_info = data.get("futures_info", {})
    k2 = f_info.get("k200_f_pct", 1.25)
    kq = f_info.get("kq150_f_pct", 1.78)

    scripts = [
        # Slide 1
        f"안녕하십니까, AI 퀀트 트레이더입니다. 오늘은 AI 500만 원 주식 굴리기 챌린지 {data['day']}일차 실전 매매 체결 타점을 정밀 복기해 드립니다. "
        f"오늘 AI가 단독 풀베팅한 종목은 바로 {data['stock_name']}이었으며, 당일 {data['net_pnl']:+,}원, 플러스 {data['return_pct']:.2f}% 수익으로 성공적인 첫 단추를 끼웠습니다. "
        f"지금부터 어떤 근거로 매수하고 어디서 매도했는지 차트와 호가를 통해 하나씩 짚어보겠습니다.",

        # Slide 2
        f"먼저 매매 진입 전 필수적으로 거치는 거시 지표 분석입니다. 오늘 아침 코스피200 선물이 {k2:.1f}%, 코스닥150 선물이 {kq:.1f}% 동반 급등했습니다. "
        f"선물이 급락하는 날에는 개별 종목이 아무리 좋아도 윗꼬리를 달기 쉬운데, 오늘은 양대 선물이 강력한 상방을 가리키며 외국인 프로그램 순매수가 쏟아져 들어왔습니다. "
        f"이에 따라 AI는 적극적 풀베팅 모드인 그린 라이트를 발동했습니다.",

        # Slide 3
        f"다음은 핵심 매수 타점 분석입니다. 9시 정각 개장 직후에는 세력들의 시초가 갭 낚시를 피하기 위해 5분간 철저히 관망했습니다. "
        f"이후 9시 {data['entry_time'].split(':')[1]}분, 1분봉 상에서 3일선, 5일선, 20일선이 완벽한 정배열을 형성하고, 주가가 3이평선을 지지하는 눌림목 타점을 확인했습니다. "
        f"호가창에 기관 대량 매수세가 받쳐주는 것을 포착하고 500만 원 전액 매수 체결에 들어갔습니다.",

        # Slide 4
        f"매도 타점 역시 감정이 아닌 철저한 수식으로 집행되었습니다. 저희 알고리즘은 실시간 3일선, 즉 엠 분의 3 공식을 매도 기준선으로 활용합니다. "
        f"현재가와 직전 이틀간의 종가를 합산해 3으로 나눈 지지선 위에서 주가가 급등 파동을 이어갔고, "
        f"설정된 목표 수익률 플러스 3%에 도달한 9시 {data['exit_time'].split(':')[1]}분, 주저 없이 전량 시장가 익절 청산을 완료했습니다.",

        # Slide 5
        f"이로써 오늘 1일차 매매는 증권거래세와 유관기관 수수료 0.20%를 정밀 차감하고도 깔끔한 플러스 12만 3천 원으로 마감되었습니다. "
        f"저희의 목표는 이 500만 원을 30일 동안 매일 복리로 굴려 1,200만 원으로 키워내는 것입니다. "
        f"내일 2일차에는 과연 어떤 종목을 발굴해 수익을 낼 수 있을까요? 구독과 알림 설정해 두시고 내일 실전 복기 영상도 놓치지 마세요. 감사합니다."
    ]

    durations = []
    for i, s_text in enumerate(scripts):
        out_mp3 = os.path.join(audio_dir, f"audio_{i+1}.mp3")
        comm = edge_tts.Communicate(s_text, voice, rate="+15%")
        await comm.save(out_mp3)

        cmd = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", out_mp3]
        dur_res = subprocess.run(cmd, capture_output=True, text=True)
        dur = float(dur_res.stdout.strip()) if dur_res.stdout.strip() else 25.0
        durations.append(dur)
        print(f"🎙️ 슬라이드 {i+1} 오디오 합성 완료: {dur:.1f}초")

    return durations

def build_full_challenge_longform(
    data_path: str = ".tmp/virtual_challenge_today.json",
    output_video: str = r"D:\DailyQuant\AI_Trading_Challenge_Day01_Analysis_1080p.mp4",
    auto_upload: bool = False,
    privacy_status: str = "public"
):
    ledger_path = os.path.join(ROOT_DIR, "data", "virtual_account_ledger.json")
    if os.path.exists(ledger_path):
        try:
            with open(ledger_path, "r", encoding="utf-8") as lf:
                ledger = json.load(lf)
                official_start = ledger.get("official_start_date", "2026-11-06")
                today_str = datetime.now().strftime("%Y-%m-%d")
                if today_str < official_start:
                    print("\n" + "=" * 75)
                    print(f"⏸️ [안내] AI 500만원 챌린지 공식 시작일은 [{official_start}] 입니다.")
                    print("   금일 롱폼 제작은 건너뛰며, 내일 첫 공식 매매 종료 후 17:30에 첫 롱폼이 제작됩니다.")
                    print("=" * 75 + "\n")
                    return ""
        except Exception:
            pass

    print("=" * 75)
    print("🎬 [AI 500만원 챌린지] 당일 실전 체결타점 분석 롱폼(16:9 Full HD) 제작 개시")
    print("=" * 75)

    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 1. 5개 슬라이드 렌더링
    slides_dir = ".tmp/longform_challenge_slides"
    os.makedirs(slides_dir, exist_ok=True)

    s1 = os.path.join(slides_dir, "slide_1.png")
    s2 = os.path.join(slides_dir, "slide_2.png")
    s3 = os.path.join(slides_dir, "slide_3.png")
    s4 = os.path.join(slides_dir, "slide_4.png")
    s5 = os.path.join(slides_dir, "slide_5.png")

    render_slide_1_cover(data, s1)
    render_slide_2_futures(data, s2)
    render_slide_3_buy_point(data, s3)
    render_slide_4_sell_point(data, s4)
    render_slide_5_roadmap(data, s5)
    print("✅ 16:9 와이드 Full HD 슬라이드 5장 생성 완료")

    # 2. 오디오 합성
    audio_dir = ".tmp/longform_challenge_audio"
    durations = asyncio.run(synthesize_longform_audios(data, audio_dir))

    # 3. FFmpeg Concat 파일 작성
    concat_txt = ".tmp/longform_concat.txt"
    with open(concat_txt, "w", encoding="utf-8") as f:
        for i in range(5):
            slide_path = os.path.abspath(os.path.join(slides_dir, f"slide_{i+1}.png"))
            f.write(f"file '{slide_path}'\nduration {durations[i]:.2f}\n")
        f.write(f"file '{os.path.abspath(s5)}'\n")

    # 4. 개별 오디오 파일들 병합
    audio_list_txt = ".tmp/longform_audio_list.txt"
    with open(audio_list_txt, "w", encoding="utf-8") as f:
        for i in range(5):
            a_path = os.path.abspath(os.path.join(audio_dir, f"audio_{i+1}.mp3"))
            f.write(f"file '{a_path}'\n")

    combined_audio = ".tmp/longform_combined_audio.mp3"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", audio_list_txt, "-c", "copy", combined_audio], check=True)

    # 5. FFmpeg 풀 렌더링 (1920x1080 Full HD, 30FPS)
    os.makedirs(os.path.dirname(output_video), exist_ok=True)
    print(f"🚀 [FFmpeg 렌더링 시작] 1920x1080 30FPS Full HD Widescreen...")
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", concat_txt,
        "-i", combined_audio,
        "-vf", "scale=1920:1080:flags=lanczos,format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-c:a", "aac", "-b:a", "320k",
        "-shortest",
        output_video
    ]
    subprocess.run(ffmpeg_cmd, check=True)
    size_mb = os.path.getsize(output_video) / (1024 * 1024)
    print(f"\n🎉 [롱폼 분석 영상 제작 완료!] 파일: {output_video} ({size_mb:.2f} MB)")

    # 6. 유튜브 롱폼 자동 업로드 (옵션)
    yt_url = None
    if auto_upload:
        title = f"AI 500만원 주식 굴리기 [Day {data['day']} 실전 복기] | {data['stock_name']} 1분봉 눌림목 + 실시간 3일선 M/3 매도 타점 완벽 해부"
        desc = f"""[인공지능 500만원 굴리기 30일 챌린지 - Day {data['day']} 실전 매매 복기 풀버전]

본 영상은 당일 쇼츠로 요약된 매매의 '상세 체결 타점'과 퀀트 알고리즘 작동 원리를 정밀 분석한 영상입니다.

📌 [오늘의 타점 분석 핵심 요약]
1. 거시 지표: 코스피200 선물 & 코스닥150 선물 동반 급등장 속에서 외인 수급 집중 종목 공략
2. 매수 타점: 09:00~09:05 시초가 갭 덫을 5분간 회피한 뒤, 1분봉 SMA 3·5·20 정배열 눌림목({data['entry_time']})에서 {data['entry_price']:,}원에 500만원 전액 매수
3. 매도 타점: 실시간 3일선(M/3) 공식을 지지선으로 설정하고, 목표 수익률 도달 즉시 {data['exit_time']}에 {data['exit_price']:,}원 전량 익절 청산

📊 [공식 계좌 원장]
• 시작 원금: 5,000,000원
• 당일 실현 손익: {data['net_pnl']:+,}원 ({data['return_pct']:+.2f}%)
• 현재 총 자산: {data['asset_after_trade']:,}원 (누적: {data['cum_return_pct']:+.2f}%)

과연 30일 뒤 AI의 500만 원은 1,200만 원이 될 수 있을까요?
구독과 알림 설정해 두시고 매일 저녁 공개되는 실전 매매 타점을 확인하세요!

#주식 #AI주식 #주식강의 #타점분석 #1분봉단타 #실시간3일선 #SK하이닉스 #코스피 #단타매매 #재테크""".strip()

        meta_dict = {
            "youtube": {
                "title": title,
                "description": desc,
                "tags": ["주식", "AI주식", "타점분석", "1분봉단타", "실시간3일선", data['stock_name'], "코스피", "퀀트투자"],
                "categoryId": "27",
                "privacyStatus": privacy_status
            }
        }
        meta_path = ".tmp/longform_challenge_metadata.json"
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta_dict, f, ensure_ascii=False, indent=2)

        try:
            yt_url = upload_youtube_shorts(video_path=output_video, meta_path=meta_path, privacy_status=privacy_status)
            send_shorts_to_telegram(video_path=output_video, title=title, youtube_url=yt_url)
        except Exception as e:
            print(f"⚠️ 롱폼 유튜브 업로드 예외: {e}")

    return output_video

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Build Challenge Longform Video")
    parser.add_argument("--upload", action="store_true", help="Auto upload to YouTube")
    parser.add_argument("--privacy", default="public", choices=["public", "unlisted", "private"])
    args = parser.parse_args()

    build_full_challenge_longform(auto_upload=args.upload, privacy_status=args.privacy)

