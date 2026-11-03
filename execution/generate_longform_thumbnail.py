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

def generate_longform_thumbnail(
    json_path: str = ".tmp/backtest_golden_cross.json",
    output_path: str = "D:/DailyQuant/LongForm_Ep1_Thumbnail.png"
):
    """
    Renders high-CTR 16:9 (1920x1080) YouTube Thumbnail for Episode 1.
    """
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    os.makedirs(".tmp", exist_ok=True)

    # 2560x1440 QHD (16:9, DPI=160 -> 16x9 inches)
    fig, ax = plt.subplots(figsize=(16, 9), dpi=160)
    fig.patch.set_facecolor('#0B0F19')
    ax.set_facecolor('#0B0F19')
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis('off')

    # Subtle background cyber grid
    for x in range(5, 100, 10):
        ax.plot([x, x], [0, 100], color='#1E293B', lw=0.6, alpha=0.3, zorder=1)
    for y in range(5, 100, 10):
        ax.plot([0, 100], [y, y], color='#1E293B', lw=0.6, alpha=0.3, zorder=1)

    # Load backtest data for background curve preview
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {}

    curve = data.get("curve_data", {})
    p_curve = curve.get("pure_golden_cross", [])
    f_curve = curve.get("quant_filtered", [])

    # Plot miniature decorative equity curve in right background
    if p_curve and f_curve:
        xs = np.linspace(50, 94, len(p_curve))
        # Keep curves safely inside canvas (height 20 to 65)
        p_arr = np.array(p_curve)
        f_arr = np.array(f_curve)
        p_norm = 22.0 + (p_arr - 50.0) / 60.0 * 24.0
        f_norm = 24.0 + (f_arr - 100.0) / 318.4 * 42.0
        p_norm = np.clip(p_norm, 18.0, 50.0)
        f_norm = np.clip(f_norm, 20.0, 66.0)
        
        # Area fill under filtered curve
        ax.fill_between(xs, 14.0, f_norm, color='#10B981', alpha=0.15, zorder=2)
        ax.plot(xs, f_norm, color='#10B981', lw=4.5, alpha=0.9, zorder=3)
        ax.plot(xs, p_norm, color='#EF4444', lw=3.0, alpha=0.8, linestyle='--', zorder=3)
        ax.scatter([xs[-1]], [f_norm[-1]], color='#34D399', s=80, zorder=4)

    # Top Category Pill Badge
    badge_box = patches.FancyBboxPatch(
        (5.5, 87), 35, 6.5,
        boxstyle="round,pad=0.6,rounding_size=1.5",
        fc='#1E293B', ec='#38BDF8', lw=1.5, zorder=5
    )
    ax.add_patch(badge_box)
    ax.text(23, 90.2, "[퀀트 팩트체크 3부작 1편] 코스피 10년 전수조사",
            color='#38BDF8', fontproperties=korean_font_bold, fontsize=16,
            ha='center', va='center', zorder=6)

    # Main Explosive Headline (3 lines, extreme contrast)
    ax.text(5.5, 78, "골든크로스 믿고 샀다가",
            color='#F1F5F9', fontproperties=korean_font_bold, fontsize=44,
            ha='left', va='center', zorder=6)
    
    # Highlight with yellow glow
    ax.text(5.5, 65, "계좌가 반토막 난 이유",
            color='#FACC15', fontproperties=korean_font_bold, fontsize=48,
            ha='left', va='center', zorder=6)

    ax.text(5.5, 53, "\"왜 책에서 배운 매매법은 항상 나만 잃을까?\"",
            color='#94A3B8', fontproperties=korean_font_prop, fontsize=21,
            ha='left', va='center', zorder=6)

    # Left Comparison Card 1: Pure Golden Cross (Failure)
    card_pure = patches.FancyBboxPatch(
        (5.5, 14), 22, 32,
        boxstyle="round,pad=1.0,rounding_size=2.0",
        fc='#1A1118', ec='#EF4444', lw=2.2, zorder=5
    )
    ax.add_patch(card_pure)
    ax.text(16.5, 41, "일반 골든크로스", color='#FCA5A5', fontproperties=korean_font_bold, fontsize=17, ha='center', zorder=6)
    ax.text(16.5, 33, "승률 38.5%", color='#EF4444', fontproperties=korean_font_bold, fontsize=28, ha='center', zorder=6)
    ax.text(16.5, 26, "누적 수익률: -24.5%", color='#F87171', fontproperties=korean_font_prop, fontsize=16, ha='center', zorder=6)
    ax.text(16.5, 19, "MDD: -41.2% (계좌 붕괴)", color='#94A3B8', fontproperties=korean_font_prop, fontsize=14, ha='center', zorder=6)

    # Left Comparison Card 2: Quant Filtered (Shocking Turnaround)
    card_quant = patches.FancyBboxPatch(
        (30, 14), 24, 32,
        boxstyle="round,pad=1.0,rounding_size=2.0",
        fc='#062A1F', ec='#10B981', lw=3.0, zorder=5
    )
    ax.add_patch(card_quant)
    # Recommended badge
    rec_badge = patches.FancyBboxPatch(
        (43, 44), 10.5, 4.0,
        boxstyle="round,pad=0.3,rounding_size=1.0",
        fc='#10B981', ec='none', zorder=7
    )
    ax.add_patch(rec_badge)
    ax.text(48.2, 46, "필터 1개 추가", color='#062A1F', fontproperties=korean_font_bold, fontsize=12, ha='center', zorder=8)

    ax.text(42, 41, "퀀트 필터 적용", color='#6EE7B7', fontproperties=korean_font_bold, fontsize=17, ha='center', zorder=6)
    ax.text(42, 33, "승률 64.8%", color='#10B981', fontproperties=korean_font_bold, fontsize=30, ha='center', zorder=6)
    ax.text(42, 26, "누적 수익률: +318.4%", color='#34D399', fontproperties=korean_font_bold, fontsize=17, ha='center', zorder=6)
    ax.text(42, 19, "MDD: -12.4% (안정 방어)", color='#A7F3D0', fontproperties=korean_font_prop, fontsize=14, ha='center', zorder=6)

    # Right Big Callout Badge over Curve
    callout = patches.FancyBboxPatch(
        (66, 68), 28, 14,
        boxstyle="round,pad=0.8,rounding_size=2.0",
        fc='#0F172A', ec='#FACC15', lw=2.5, zorder=6
    )
    ax.add_patch(callout)
    ax.text(80, 77.5, "10년 백테스트 최초 공개", color='#FACC15', fontproperties=korean_font_bold, fontsize=20, ha='center', zorder=7)
    ax.text(80, 72, "가짜 신호 70% 걸러내는 비기", color='#E2E8F0', fontproperties=korean_font_prop, fontsize=15, ha='center', zorder=7)

    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)
    plt.savefig(output_path, dpi=160, facecolor=fig.get_facecolor(), edgecolor='none')
    # Also save to .tmp
    plt.savefig(".tmp/longform_ep1_thumbnail.png", dpi=160, facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close(fig)

    print(f"🖼️ [16:9 썸네일 완성] 저장 완료 -> {output_path}")
    return output_path

if __name__ == "__main__":
    generate_longform_thumbnail()
