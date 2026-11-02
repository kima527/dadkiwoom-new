import os
import sys
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.patches as patches
from matplotlib import font_manager

# Ensure UTF-8 output
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Setup Korean font (strictly Malgun Gothic for crisp, modern rendering)
korean_font_prop = font_manager.FontProperties(fname='C:/Windows/Fonts/malgun.ttf')
korean_font_bold = font_manager.FontProperties(fname='C:/Windows/Fonts/malgunbd.ttf')
if not os.path.exists('C:/Windows/Fonts/malgun.ttf'):
    korean_font_prop = font_manager.FontProperties(family='sans-serif')
if not os.path.exists('C:/Windows/Fonts/malgunbd.ttf'):
    korean_font_bold = korean_font_prop

def create_shorts_cover_page(
    json_path: str = ".tmp/market_anomaly_today.json",
    output_path: str = ".tmp/shorts_cover_today.png"
):
    """
    Creates a high-CTR, curiosity-inducing vertical cover page (1080x1920)
    designed to stop the scroll on YouTube Shorts and maximize retention.
    """
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {}

    kor = data.get("korea_indicators", {})
    sox = kor.get("sox") or data.get("key_indices", {}).get("sox") or {"price": 10688.8, "change_pct": -7.2}
    k2 = kor.get("kospi200_night") or {"price": 918.65, "change_pct": 2.13}
    kq = kor.get("kosdaq150_night") or {"price": 1229.0, "change_pct": 2.09}

    sox_pct = sox.get("change_pct", -7.2)
    k2_pct = k2.get("change_pct", 2.13)
    sox_sign = "+" if sox_pct >= 0 else ""
    k2_sign = "+" if k2_pct >= 0 else ""

    # Dimensions: 1080 x 1920 (9:16)
    dpi = 100
    fig_w, fig_h = 10.8, 19.2
    fig = plt.figure(figsize=(fig_w, fig_h), dpi=dpi, facecolor='#06090F')
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_facecolor('#06090F')
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis('off')

    # 1. Subtle Dark Tech Ambient Glow
    top_glow = patches.Rectangle((0, 0.65), 1.0, 0.35, facecolor='#111827', alpha=0.45, zorder=1)
    ax.add_patch(top_glow)
    
    # Outer Tech Frame Border
    frame = patches.Rectangle((0.035, 0.02), 0.93, 0.96, linewidth=2.0, edgecolor='#00E5FF', facecolor='none', alpha=0.4, zorder=2)
    ax.add_patch(frame)
    inner_frame = patches.Rectangle((0.045, 0.026), 0.91, 0.948, linewidth=1.0, edgecolor='#1E293B', facecolor='none', zorder=2)
    ax.add_patch(inner_frame)

    # 2. Top Channel Tag / Live Indicator
    tag_box = patches.FancyBboxPatch(
        (0.25, 0.925), 0.50, 0.032,
        boxstyle="round,pad=0.006,rounding_size=0.015",
        facecolor="#00E5FF", edgecolor="none", alpha=0.15, zorder=3
    )
    ax.add_patch(tag_box)
    ax.text(0.50, 0.941, "DAILY QUANT  |  모닝 퀀트 긴급 속보", color='#00E5FF',
            fontproperties=korean_font_bold, fontsize=18, ha='center', va='center', weight='bold', zorder=4)

    # 3. Urgent Alert Badge (High Contrast Pill)
    alert_badge = patches.FancyBboxPatch(
        (0.16, 0.852), 0.68, 0.048,
        boxstyle="round,pad=0.008,rounding_size=0.02",
        facecolor="#E11D48", edgecolor="#FDA4AF", linewidth=1.6, zorder=5
    )
    ax.add_patch(alert_badge)
    ax.text(0.50, 0.876, "◆ [ 오늘 아침 9시 국내 증시 긴급 점검 ] ◆", color='#FFFFFF',
            fontproperties=korean_font_bold, fontsize=23, ha='center', va='center', weight='bold', zorder=6)

    # 4. Massive Viral Hook Title (The Scroll Stopper)
    # Line 1: 오늘 9시 개장 직전,
    ax.text(0.50, 0.795, "오늘 아침 9시 개장 직전,", color='#F8FAFC',
            fontproperties=korean_font_bold, fontsize=41, ha='center', va='center', weight='bold', zorder=5)
    
    # Line 2: '이것' 모르면 (Vivid Gold Badge)
    hook_highlight_bg = patches.FancyBboxPatch(
        (0.18, 0.718), 0.64, 0.055,
        boxstyle="round,pad=0.006,rounding_size=0.016",
        facecolor="#FBBF24", edgecolor="#FDE68A", linewidth=1.5, zorder=4
    )
    ax.add_patch(hook_highlight_bg)
    ax.text(0.50, 0.745, "‘이것’ 모르면", color='#0F172A',
            fontproperties=korean_font_bold, fontsize=45, ha='center', va='center', weight='heavy', zorder=5)

    # Line 3: 시초가에 다 털립니다! (Vivid Red Badge for maximum contrast!)
    danger_bg = patches.FancyBboxPatch(
        (0.12, 0.645), 0.76, 0.056,
        boxstyle="round,pad=0.006,rounding_size=0.016",
        facecolor="#BE123C", edgecolor="#FB7185", linewidth=1.5, zorder=4
    )
    ax.add_patch(danger_bg)
    ax.text(0.50, 0.673, "시초가에 다 털립니다!", color='#FFFFFF',
            fontproperties=korean_font_bold, fontsize=43, ha='center', va='center', weight='heavy', zorder=5)

    # Sub-hook: Target audience callout
    subhook_box = patches.FancyBboxPatch(
        (0.15, 0.585), 0.70, 0.038,
        boxstyle="round,pad=0.006,rounding_size=0.012",
        facecolor="#0F172A", edgecolor="#334155", linewidth=1.2, zorder=4
    )
    ax.add_patch(subhook_box)
    ax.text(0.50, 0.604, "[긴급 필독] 삼성전자 · SK하이닉스 주주 필독", color='#FCD34D',
            fontproperties=korean_font_bold, fontsize=20, ha='center', va='center', weight='bold', zorder=5)

    # 5. Middle Dramatic Contrast Showcase (SOX vs Night Futures Clash)
    clash_bg = patches.FancyBboxPatch(
        (0.08, 0.380), 0.84, 0.180,
        boxstyle="round,pad=0.01,rounding_size=0.022",
        facecolor="#0B111E", edgecolor="#22314E", linewidth=1.5, zorder=3
    )
    ax.add_patch(clash_bg)

    ax.text(0.50, 0.528, "밤사이 엇갈린 극과 극 선행 시그널", color='#94A3B8',
            fontproperties=korean_font_bold, fontsize=19, ha='center', va='center', zorder=4)

    # Divider line inside clash card
    ax.plot([0.50, 0.50], [0.395, 0.510], color='#22314E', linewidth=1.5, zorder=4)

    # Left: Semiconductor Shock
    ax.text(0.29, 0.485, "필라델피아 반도체", color='#CBD5E1',
            fontproperties=korean_font_bold, fontsize=20, ha='center', va='center', zorder=4)
    ax.text(0.29, 0.435, f"{sox_sign}{sox_pct:.1f}% 폭락", color='#FF4D6D',
            fontproperties=korean_font_bold, fontsize=31, ha='center', va='center', weight='bold', zorder=4)
    ax.text(0.29, 0.400, f"종가 {sox['price']:,.0f} pt", color='#94A3B8',
            fontproperties=korean_font_bold, fontsize=17, ha='center', va='center', zorder=4)

    # Right: Night Futures Rebound
    ax.text(0.71, 0.485, "국내 야간 코스피선물", color='#CBD5E1',
            fontproperties=korean_font_bold, fontsize=20, ha='center', va='center', zorder=4)
    ax.text(0.71, 0.435, f"{k2_sign}{k2_pct:.1f}% 반등", color='#10B981',
            fontproperties=korean_font_bold, fontsize=31, ha='center', va='center', weight='bold', zorder=4)
    ax.text(0.71, 0.400, f"종가 {k2['price']:,.2f} pt", color='#94A3B8',
            fontproperties=korean_font_bold, fontsize=17, ha='center', va='center', zorder=4)

    # 6. Curiosity Bullets Card ("오늘 영상 핵심 내용 3가지")
    bullets_bg = patches.FancyBboxPatch(
        (0.08, 0.145), 0.84, 0.210,
        boxstyle="round,pad=0.01,rounding_size=0.022",
        facecolor="#0B1322", edgecolor="#00E5FF", linewidth=1.5, alpha=0.95, zorder=3
    )
    ax.add_patch(bullets_bg)

    ax.text(0.50, 0.325, "◆ [ 오늘 영상에서 밝혀지는 3대 핵심 팩트 ] ◆", color='#00E5FF',
            fontproperties=korean_font_bold, fontsize=21, ha='center', va='center', weight='bold', zorder=4)
    
    # Inner subtle divider
    ax.plot([0.13, 0.87], [0.302, 0.302], color='#1E293B', linewidth=1.2, zorder=4)

    bullets = [
        ("1.", "미국 반도체 급락 쇼크, 국내 증시 어디까지 밀릴까?"),
        ("2.", "야간 선물 상승은 '진짜 기회'일까, '치명적 덫'일까?"),
        ("3.", "9시 개장 직후 15분, 계좌 지키는 실전 매매 대응법")
    ]

    start_y = 0.266
    step_y = 0.046
    for i, (num, text) in enumerate(bullets):
        y = start_y - (i * step_y)
        # Bullet number badge
        num_bg = patches.FancyBboxPatch(
            (0.12, y - 0.014), 0.050, 0.028,
            boxstyle="round,pad=0.003,rounding_size=0.008",
            facecolor="#E11D48" if i == 0 else ("#10B981" if i == 1 else "#FBBF24"),
            edgecolor="none", zorder=4
        )
        ax.add_patch(num_bg)
        ax.text(0.145, y, num, color='#0F172A',
                fontproperties=korean_font_bold, fontsize=18, ha='center', va='center', weight='bold', zorder=5)
        # Bullet text
        ax.text(0.190, y, text, color='#F8FAFC',
                fontproperties=korean_font_bold, fontsize=19, ha='left', va='center', zorder=5)

    # 7. Bottom Call to Action (CTA) Box
    cta_box = patches.FancyBboxPatch(
        (0.12, 0.060), 0.76, 0.055,
        boxstyle="round,pad=0.008,rounding_size=0.02",
        facecolor="#1E293B", edgecolor="#38BDF8", linewidth=1.6, zorder=4
    )
    ax.add_patch(cta_box)
    ax.text(0.50, 0.088, "▶ 지금 바로 55초 만에 확인하세요! (필독) ◀", color='#38BDF8',
            fontproperties=korean_font_bold, fontsize=21, ha='center', va='center', weight='bold', zorder=5)

    # Clean bottom disclaimer
    ax.text(0.50, 0.033, "※ 본 영상은 데이터 기반 분석 정보이며 투자 권유가 아닙니다.",
            color='#64748B', fontproperties=korean_font_prop, fontsize=13, ha='center', va='center', zorder=4)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    plt.savefig(output_path, dpi=dpi, facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close()
    print(f"✅ 커버페이지 생성 완료: {output_path}")
    return output_path

if __name__ == "__main__":
    create_shorts_cover_page()
