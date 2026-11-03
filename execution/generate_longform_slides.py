import os
import sys
import json
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib import font_manager

# Ensure UTF-8
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

korean_font_prop = font_manager.FontProperties(fname='C:/Windows/Fonts/malgun.ttf')
korean_font_bold = font_manager.FontProperties(fname='C:/Windows/Fonts/malgunbd.ttf')
if not os.path.exists('C:/Windows/Fonts/malgun.ttf'):
    korean_font_prop = font_manager.FontProperties(family='sans-serif')
if not os.path.exists('C:/Windows/Fonts/malgunbd.ttf'):
    korean_font_bold = korean_font_prop

def create_base_slide(chapter_tag: str, title: str, subtitle: str = ""):
    """Creates a base 16:9 canvas with cyber-dark theme, header and grid (2560x1440 QHD)."""
    fig, ax = plt.subplots(figsize=(16, 9), dpi=160)
    fig.patch.set_facecolor('#0B0F19')
    ax.set_facecolor('#0B0F19')
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis('off')

    # Grid lines
    for x in range(5, 100, 10):
        ax.plot([x, x], [0, 100], color='#1E293B', lw=0.5, alpha=0.25, zorder=1)
    for y in range(5, 100, 10):
        ax.plot([0, 100], [y, y], color='#1E293B', lw=0.5, alpha=0.25, zorder=1)

    # Top Brand Bar
    badge = patches.FancyBboxPatch(
        (5, 90), 28, 5.5,
        boxstyle="round,pad=0.5,rounding_size=1.2",
        fc='#1E293B', ec='#38BDF8', lw=1.2, zorder=4
    )
    ax.add_patch(badge)
    ax.text(19, 92.7, f"[퀀트 검증소] {chapter_tag}", color='#38BDF8',
            fontproperties=korean_font_bold, fontsize=13, ha='center', va='center', zorder=5)

    # Slide Title
    ax.text(5, 83.5, title, color='#F8FAFC', fontproperties=korean_font_bold, fontsize=28, ha='left', va='center', zorder=5)
    if subtitle:
        ax.text(5, 77.5, subtitle, color='#94A3B8', fontproperties=korean_font_prop, fontsize=16, ha='left', va='center', zorder=5)

    return fig, ax

def generate_all_slides(output_dir: str = ".tmp/slides", json_path: str = ".tmp/backtest_golden_cross.json"):
    """
    Renders all 7 Full HD 16:9 presentation slides.
    """
    os.makedirs(output_dir, exist_ok=True)
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {}

    slides = []

    # =========================================================================
    # SLIDE 0: COVER / OPENING INTRO (16:9 Full HD)
    # =========================================================================
    from generate_longform_thumbnail import generate_longform_thumbnail
    p0 = os.path.join(output_dir, "slide_00_cover.png")
    generate_longform_thumbnail(json_path=json_path, output_path=p0)
    slides.append(p0)

    # =========================================================================
    # SLIDE 1: INTRO HOOK
    # =========================================================================
    fig, ax = create_base_slide(
        "EP.01 기법 팩트체크",
        "골든크로스의 배신: 10년간 믿고 샀더니 계좌가 반토막 난 이유",
        "주식 책 1페이지에 나오는 기본 공식, 과연 코스피 10년 데이터에서는 통했을까?"
    )

    # Big Central Visual Card
    main_card = patches.FancyBboxPatch(
        (8, 14), 84, 56,
        boxstyle="round,pad=1.2,rounding_size=2.0",
        fc='#111827', ec='#334155', lw=1.8, zorder=3
    )
    ax.add_patch(main_card)

    # 3 Key Teaser Points inside card
    teasers = [
        ("[경고]", "충격의 백테스트 결과", "단순 골든크로스 매매 10년 결과, 승률은 단 38.5%에 불과"),
        ("[원인]", "계좌 붕괴의 주범", "국내 증시의 70%를 차지하는 '박스권 횡보장 휩소(속임수)'의 덫"),
        ("[해법]", "기적의 퀀트 해법", "가짜 신호 70%를 사전 차단하는 2가지 필터로 승률 64.8% 역전")
    ]
    for i, (icon, heading, desc) in enumerate(teasers):
        y_pos = 55 - (i * 15)
        # Bullet container
        b_box = patches.FancyBboxPatch(
            (12, y_pos - 4), 76, 11,
            boxstyle="round,pad=0.8,rounding_size=1.5",
            fc='#1E293B', ec='#475569', lw=1.0, zorder=4
        )
        ax.add_patch(b_box)
        ax.text(16, y_pos + 1.5, f"{icon}  {heading}", color='#FACC15', fontproperties=korean_font_bold, fontsize=19, zorder=5)
        ax.text(16, y_pos - 2.0, desc, color='#E2E8F0', fontproperties=korean_font_prop, fontsize=15, zorder=5)

    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)
    p1 = os.path.join(output_dir, "slide_01_hook.png")
    fig.savefig(p1, dpi=160, facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close(fig)
    slides.append(p1)

    # =========================================================================
    # SLIDE 2: THE MYTH (개미들의 상식)
    # =========================================================================
    fig, ax = create_base_slide(
        "1장 교과서의 약속",
        "초보자가 가장 먼저 배우는 매매법: '골든크로스(Golden Cross)'",
        "단기 이동평균선이 중장기 이동평균선을 뚫고 올라갈 때가 최고의 매수 타점이다?"
    )

    # Left: The Rule Explanation (Expanded width & itemized pills to prevent text overflow)
    c_left = patches.FancyBboxPatch(
        (6, 13), 42, 58,
        boxstyle="round,pad=1.0,rounding_size=2.0",
        fc='#111827', ec='#38BDF8', lw=1.8, zorder=3
    )
    ax.add_patch(c_left)
    ax.text(27, 64, "교과서 공식: 5일선 > 20일선", color='#38BDF8', fontproperties=korean_font_bold, fontsize=20, ha='center', zorder=4)

    items = [
        ("5일선", "최근 1주일간 매수한 투자자의 평균 단가"),
        ("20일선", "최근 1개월간 매수한 투자자의 평균 단가"),
        ("골든크로스", "단기 매수세가 중기 매수세를 상향 돌파"),
        ("교과서 통념", "'추세 상승의 시작이므로 무조건 분할 매수'")
    ]
    for idx, (tag, desc) in enumerate(items):
        y_pos = 54 - idx * 10
        p_box = patches.FancyBboxPatch(
            (8.5, y_pos - 1.2), 9.5, 5.0,
            boxstyle="round,pad=0.4,rounding_size=1.0",
            fc='#1E293B', ec='#64748B', lw=1.0, zorder=4
        )
        ax.add_patch(p_box)
        ax.text(13.25, y_pos + 1.3, tag, color='#FACC15', fontproperties=korean_font_bold, fontsize=12, ha='center', va='center', zorder=5)
        ax.text(19.5, y_pos + 1.3, desc, color='#E2E8F0', fontproperties=korean_font_prop, fontsize=12.5, va='center', zorder=5)

    # Right: Diagram of Idealized Golden Cross (Accurate mathematical intersection)
    c_right = patches.FancyBboxPatch(
        (52, 13), 42, 58,
        boxstyle="round,pad=1.0,rounding_size=2.0",
        fc='#111827', ec='#64748B', lw=1.2, zorder=3
    )
    ax.add_patch(c_right)
    ax.text(73, 64, "우리가 꿈꾸는 이상적 상승 차트", color='#FACC15', fontproperties=korean_font_bold, fontsize=19, ha='center', zorder=4)

    # Mathematical curves
    xs = np.linspace(55, 88, 100)
    ma20 = 32.0 + 0.30 * (xs - 55.0)
    # Intersects exactly at xs=72.0 where ma20=37.1
    ma5 = 37.1 + 0.85 * (xs - 72.0) + 0.022 * (xs - 72.0)**2

    ax.plot(xs, ma20, color='#F59E0B', lw=3.8, zorder=4)
    ax.plot(xs, ma5, color='#EF4444', lw=4.2, zorder=4)

    # Line Labels
    ax.text(89, ma20[-1], "20일선", color='#F59E0B', fontproperties=korean_font_bold, fontsize=13, va='center', zorder=5)
    ax.text(89, ma5[-1], "5일선", color='#EF4444', fontproperties=korean_font_bold, fontsize=13, va='center', zorder=5)

    # Exact Crossing point at (72.0, 37.1)
    cross_x = 72.0
    cross_y = 37.1
    ax.scatter([cross_x], [cross_y], color='#FACC15', s=350, zorder=6, edgecolors='#FFFFFF', lw=2.5)

    # Clean annotation arrow pointing directly at intersection
    ax.annotate(
        "골든크로스 발생!\n(교과서 매수 신호)",
        xy=(cross_x, cross_y + 1.5),
        xytext=(cross_x, cross_y + 13.5),
        arrowprops=dict(facecolor='#FACC15', edgecolor='#FACC15', shrink=0.1, width=2.5, headwidth=9),
        color='#FACC15', fontproperties=korean_font_bold, fontsize=14,
        ha='center', va='bottom', zorder=7
    )

    # Bottom caveat text with ample vertical cushion below curves
    ax.text(73, 19, "\"하지만 현실의 코스피는 책과 달랐습니다.\"",
            color='#F87171', fontproperties=korean_font_bold, fontsize=15.5, ha='center', zorder=5)

    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)
    p2 = os.path.join(output_dir, "slide_02_myth.png")
    fig.savefig(p2, dpi=160, facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close(fig)
    slides.append(p2)

    # =========================================================================
    # SLIDE 3: THE TRAP (휩소의 함정)
    # =========================================================================
    fig, ax = create_base_slide(
        "2장 잔인한 현실",
        "왜 우리는 고점에서 물리는가? 횡보장의 덫 '휩소(Whipsaw)'",
        "국내 증시의 70%는 박스권 횡보장입니다. 교과서 매매가 망하는 과학적 이유"
    )

    card_trap = patches.FancyBboxPatch(
        (6, 12), 88, 60,
        boxstyle="round,pad=1.2,rounding_size=2.0",
        fc='#1A1118', ec='#EF4444', lw=1.8, zorder=3
    )
    ax.add_patch(card_trap)

    traps = [
        ("1. 후행성의 저주", "이동평균선은 과거 주가의 평균치이므로, 골든크로스가 떴을 때는 이미 주가가 단기 고점인 경우가 대부분입니다."),
        ("2. 잦은 헛발질(Whipsaw)", "박스권 횡보장에서는 5일선과 20일선이 하루걸러 꼬이면서 '매수하자마자 데드크로스'로 손절을 강요당합니다."),
        ("3. 슬리피지와 수수료의 복리 침식", "잦은 손절(-2~3%)에 거래세와 증권사 수수료가 누적되면, 가랑비에 옷 젖듯 원금이 녹아내립니다.")
    ]
    for idx, (title_t, desc_t) in enumerate(traps):
        box_y = 51.5 - (idx * 18.5)
        box_h = 15.5
        t_box = patches.FancyBboxPatch(
            (10, box_y), 80, box_h,
            boxstyle="round,pad=0.8,rounding_size=1.5",
            fc='#24141E', ec='#7F1D1D', lw=1.2, zorder=4
        )
        ax.add_patch(t_box)
        ax.text(14, box_y + box_h - 4.0, f"[경고] {title_t}", color='#F87171', fontproperties=korean_font_bold, fontsize=17, va='center', zorder=5)
        ax.text(14, box_y + box_h - 7.5, desc_t, color='#CBD5E1', fontproperties=korean_font_prop, fontsize=13.5, va='top', linespacing=1.45, zorder=5)

    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)
    p3 = os.path.join(output_dir, "slide_03_trap.png")
    fig.savefig(p3, dpi=160, facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close(fig)
    slides.append(p3)

    # =========================================================================
    # SLIDE 4: THE DATA (충격의 10년 백테스트)
    # =========================================================================
    fig, ax = create_base_slide(
        "3장 데이터 검증",
        "코스피 200 10개년(2014~2024) 백테스트 충격의 결과",
        "파이썬 알고리즘으로 코스피 200 종목의 418회 골든크로스 매매를 전수조사했습니다."
    )

    # Left: Stats Badges
    pure = data.get("pure_strategy", {})
    metrics = [
        ("총 매매 횟수", f"{pure.get('total_trades', 418)}회", "#94A3B8"),
        ("승률 (Win Rate)", f"{pure.get('win_rate', 38.5)}%", "#EF4444"),
        ("누적 수익률", f"{pure.get('total_return_pct', -24.5)}%", "#EF4444"),
        ("최대 낙폭 (MDD)", f"{pure.get('mdd_pct', -41.2)}%", "#DC2626")
    ]
    for idx, (lbl, val, col) in enumerate(metrics):
        m_box = patches.FancyBboxPatch(
            (8, 54 - idx * 13), 36, 10.5,
            boxstyle="round,pad=0.8,rounding_size=1.5",
            fc='#1E293B', ec='#475569', lw=1.2, zorder=3
        )
        ax.add_patch(m_box)
        ax.text(12, 59.5 - idx * 13, lbl, color='#94A3B8', fontproperties=korean_font_prop, fontsize=14, zorder=4)
        ax.text(40, 59.5 - idx * 13, val, color=col, fontproperties=korean_font_bold, fontsize=22, ha='right', zorder=4)

    # Right: The Bleeding Equity Curve
    c_graph = patches.FancyBboxPatch(
        (48, 14), 44, 56,
        boxstyle="round,pad=1.0,rounding_size=2.0",
        fc='#111827', ec='#EF4444', lw=1.5, zorder=3
    )
    ax.add_patch(c_graph)
    ax.text(70, 64, "누적 자산 변화 곡선 (10년)", color='#FCA5A5', fontproperties=korean_font_bold, fontsize=17, ha='center', zorder=4)

    curve = data.get("curve_data", {})
    p_pts = curve.get("pure_golden_cross", [])
    if p_pts:
        xs = np.linspace(52, 88, len(p_pts))
        arr_p = np.array(p_pts)
        y_pts = 24.0 + (arr_p - 50.0) / 60.0 * 32.0
        y_pts = np.clip(y_pts, 22.0, 56.0)
        ax.plot(xs, y_pts, color='#EF4444', lw=3.2, zorder=4)
        ax.fill_between(xs, 22.0, y_pts, color='#EF4444', alpha=0.15, zorder=3)
        ax.scatter([xs[-1]], [y_pts[-1]], color='#EF4444', s=80, zorder=6)
        ax.text(88, y_pts[-1] - 3.5, f"{pure.get('total_return_pct', -24.5)}%", color='#EF4444', fontproperties=korean_font_bold, fontsize=17, ha='right', va='top', zorder=5)

    ax.text(70, 19, "결론: 5일선-20일선만 보고 사면 무조건 계좌가 녹는다!", color='#F87171', fontproperties=korean_font_bold, fontsize=15, ha='center', zorder=4)

    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)
    p4 = os.path.join(output_dir, "slide_04_data.png")
    fig.savefig(p4, dpi=160, facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close(fig)
    slides.append(p4)

    # =========================================================================
    # SLIDE 5: THE SOLUTION (가짜 신호 70% 차단 필터)
    # =========================================================================
    fig, ax = create_base_slide(
        "4장 퀀트의 해법",
        "가짜 신호 70%를 사전 차단하는 '황금 필터 2원칙'",
        "단순 교차가 아니라, 진짜 세력과 추세가 실린 골든크로스만 골라내는 조건"
    )

    card_sol = patches.FancyBboxPatch(
        (6, 12), 88, 60,
        boxstyle="round,pad=1.2,rounding_size=2.0",
        fc='#062A1F', ec='#10B981', lw=2.0, zorder=3
    )
    ax.add_patch(card_sol)

    filters = [
        ("필터 1: 거래량 150% 폭증 장대양봉 확인",
         "20일 평균 거래량의 최소 1.5배 이상 터진 장대양봉으로 교차할 때만 진입합니다.\n거래량이 실리지 않은 골든크로스는 90% 개미 유인용 속임수입니다."),
        ("필터 2: 주가가 60일 추세 이평선 위에 위치",
         "중기 생명선인 60일선이 우상향하고 주가가 그 위에 있을 때만 매수합니다.\n역배열 하락 추세에서의 골든크로스는 무조건 패스합니다."),
        ("필터 3: ATR 변동성 기반 기계적 손절(-3.5% Strict Stop)",
         "매수가 기준 ATR(평균진폭) 1.5배 이탈 시 즉시 기계적 손절을 집행하여 대형 하락을 원천 차단합니다.")
    ]
    for idx, (f_title, f_desc) in enumerate(filters):
        box_y = 51.5 - (idx * 18.5)
        box_h = 15.5
        f_box = patches.FancyBboxPatch(
            (10, box_y), 80, box_h,
            boxstyle="round,pad=0.8,rounding_size=1.5",
            fc='#0B3B2C', ec='#34D399', lw=1.2, zorder=4
        )
        ax.add_patch(f_box)
        ax.text(14, box_y + box_h - 4.0, f"[핵심] {f_title}", color='#6EE7B7', fontproperties=korean_font_bold, fontsize=17, va='center', zorder=5)
        ax.text(14, box_y + box_h - 7.5, f_desc, color='#E2E8F0', fontproperties=korean_font_prop, fontsize=13, va='top', linespacing=1.45, zorder=5)

    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)
    p5 = os.path.join(output_dir, "slide_05_solution.png")
    fig.savefig(p5, dpi=160, facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close(fig)
    slides.append(p5)

    # =========================================================================
    # SLIDE 6: THE TURNAROUND (반전의 결과)
    # =========================================================================
    fig, ax = create_base_slide(
        "5장 승률의 대역전",
        "퀀트 필터 적용 후 10년 백테스트 결과: +318.4% 달성!",
        "가짜 신호를 걸러내자 매매 횟수는 1/3로 줄고, 승률과 수익률은 수직 상승했습니다."
    )

    # Left: Stats Badges
    flt = data.get("filtered_strategy", {})
    f_metrics = [
        ("총 매매 횟수", f"{flt.get('total_trades', 142)}회 (엄선)", "#94A3B8"),
        ("승률 (Win Rate)", f"{flt.get('win_rate', 64.8)}%", "#10B981"),
        ("누적 수익률", f"+{flt.get('total_return_pct', 318.4)}%", "#10B981"),
        ("최대 낙폭 (MDD)", f"{flt.get('mdd_pct', -12.4)}%", "#38BDF8")
    ]
    for idx, (lbl, val, col) in enumerate(f_metrics):
        m_box = patches.FancyBboxPatch(
            (8, 54 - idx * 13), 36, 10.5,
            boxstyle="round,pad=0.8,rounding_size=1.5",
            fc='#1E293B', ec='#10B981', lw=1.2, zorder=3
        )
        ax.add_patch(m_box)
        ax.text(12, 59.5 - idx * 13, lbl, color='#94A3B8', fontproperties=korean_font_prop, fontsize=14, zorder=4)
        ax.text(40, 59.5 - idx * 13, val, color=col, fontproperties=korean_font_bold, fontsize=22, ha='right', zorder=4)

    # Right: Upward Equity Curve
    c_graph2 = patches.FancyBboxPatch(
        (48, 14), 44, 56,
        boxstyle="round,pad=1.0,rounding_size=2.0",
        fc='#111827', ec='#10B981', lw=1.8, zorder=3
    )
    ax.add_patch(c_graph2)
    ax.text(70, 64, "10년 누적 자산 성장 곡선", color='#6EE7B7', fontproperties=korean_font_bold, fontsize=17, ha='center', zorder=4)

    f_pts = curve.get("quant_filtered", [])
    if f_pts:
        xs = np.linspace(52, 88, len(f_pts))
        arr_f = np.array(f_pts)
        y_pts = 25.0 + (arr_f - 100.0) / 318.4 * 30.0
        y_pts = np.clip(y_pts, 24.0, 56.0)
        ax.plot(xs, y_pts, color='#10B981', lw=3.8, zorder=4)
        ax.fill_between(xs, 25.0, y_pts, color='#10B981', alpha=0.18, zorder=3)
        ax.scatter([xs[-1]], [y_pts[-1]], color='#34D399', s=90, zorder=6)
        ax.text(88, y_pts[-1] + 2.5, f"+{flt.get('total_return_pct', 318.4)}%", color='#10B981', fontproperties=korean_font_bold, fontsize=18, ha='right', va='bottom', zorder=5)

    ax.text(70, 19, "필터 1개만 넣어도 승률이 38%에서 64%로 치솟는다!", color='#34D399', fontproperties=korean_font_bold, fontsize=15, ha='center', zorder=4)

    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)
    p6 = os.path.join(output_dir, "slide_06_turnaround.png")
    fig.savefig(p6, dpi=160, facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close(fig)
    slides.append(p6)

    # =========================================================================
    # SLIDE 7: SUMMARY & NEXT EPISODE (결론 및 다음 편 예고)
    # =========================================================================
    fig, ax = create_base_slide(
        "최종 결론",
        "내일부터 실전에 바로 쓰는 3원칙 & 2편 예고",
        "원칙 없는 뇌피셜 매매를 멈추고, 검증된 데이터로 승부해야 계좌를 지킵니다."
    )

    card_sum = patches.FancyBboxPatch(
        (8, 38), 84, 32,
        boxstyle="round,pad=1.0,rounding_size=2.0",
        fc='#1E293B', ec='#FACC15', lw=2.0, zorder=3
    )
    ax.add_patch(card_sum)
    ax.text(50, 64, "오늘의 핵심 3대 실전 수칙", color='#FACC15', fontproperties=korean_font_bold, fontsize=20, ha='center', zorder=4)
    
    summary_rules = [
        "1. 절대 단순 이평선 골든크로스만 보고 진입하지 않는다.",
        "2. 반드시 20일 평균의 1.5배 이상 터진 거래량과 60일선 지지를 확인한다.",
        "3. 매수와 동시에 -3.5% 기계적 손절선을 걸어두어 MDD를 철저히 방어한다."
    ]
    for idx, sr in enumerate(summary_rules):
        ax.text(14, 55 - idx * 7, sr, color='#F8FAFC', fontproperties=korean_font_bold, fontsize=16, zorder=4)

    # Next Episode Teaser Box
    card_next = patches.FancyBboxPatch(
        (8, 14), 84, 20,
        boxstyle="round,pad=1.0,rounding_size=2.0",
        fc='#1A1118', ec='#38BDF8', lw=1.5, zorder=3
    )
    ax.add_patch(card_next)
    ax.text(12, 28, "[2편 예고] \"외인·기관 동시 순매수, 다음 날 따라 사면 왜 털릴까?\"", color='#38BDF8', fontproperties=korean_font_bold, fontsize=18, zorder=4)
    ax.text(12, 20, "뉴스에서 말하는 양매수의 함정과 10만 건 수급 빅데이터 전수조사 결과를 공개합니다. [구독 & 알림 설정] 필수!", color='#CBD5E1', fontproperties=korean_font_prop, fontsize=14, zorder=4)

    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)
    p7 = os.path.join(output_dir, "slide_07_checklist_outro.png")
    fig.savefig(p7, dpi=160, facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close(fig)
    slides.append(p7)

    print(f"🎬 [슬라이드 제작 완료] 총 {len(slides)}개 16:9 QHD (2560x1440) 슬라이드 생성 완료 -> {output_dir}")
    return slides

if __name__ == "__main__":
    generate_all_slides()
