import os
import sys
import json
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import matplotlib.font_manager as fm

# Ensure UTF-8 output
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Configure Korean Fonts
def get_korean_font():
    candidates = [
        "C:/Windows/Fonts/malgun.ttf",
        "C:/Windows/Fonts/malgunbd.ttf",
        "C:/Windows/Fonts/NanumGothic.ttf"
    ]
    for path in candidates:
        if os.path.exists(path):
            return fm.FontProperties(fname=path)
    return fm.FontProperties(family="sans-serif")

def get_korean_bold_font():
    candidates = [
        "C:/Windows/Fonts/malgunbd.ttf",
        "C:/Windows/Fonts/malgun.ttf"
    ]
    for path in candidates:
        if os.path.exists(path):
            return fm.FontProperties(fname=path, weight='bold')
    return fm.FontProperties(family="sans-serif", weight='bold')

def create_premarket_visual(
    json_path=".tmp/premarket_anomaly_today.json",
    output_path=".tmp/premarket_visual_today.png"
):
    """
    Renders a stunning 1440x2560 QHD vertical infographic for the 08:50 Pre-Market Urgent Shorts.
    """
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {}

    font_prop = get_korean_font()
    bold_prop = get_korean_bold_font()

    # 1440x2560 QHD (9x16 at 160 DPI)
    fig, ax = plt.subplots(figsize=(9, 16), dpi=160)
    fig.patch.set_facecolor('#0B0F19')
    ax.set_facecolor('#0B0F19')
    ax.set_xlim(0, 100)
    ax.set_ylim(0, 100)
    ax.axis('off')

    # Subtle background gradient card
    bg_card = patches.FancyBboxPatch(
        (3, 3), 94, 94,
        boxstyle="round,pad=1.0,rounding_size=2.0",
        fc='#0F172A', ec='#1E293B', lw=1.5, zorder=1
    )
    ax.add_patch(bg_card)

    # -------------------------------------------------------------
    # HEADER: EMERGENCY ALERT BANNER
    # -------------------------------------------------------------
    alert_badge = patches.FancyBboxPatch(
        (15, 91.5), 70, 4.2,
        boxstyle="round,pad=0.5,rounding_size=1.2",
        fc='#DC2626', ec='#EF4444', lw=1.8, zorder=3
    )
    ax.add_patch(alert_badge)
    ax.text(50, 93.6, "🚨 [개장 10분 전 긴급 속보]", color='#FFFFFF',
            fontproperties=bold_prop, fontsize=18, ha='center', va='center', zorder=4)

    ax.text(50, 87.5, "08:50 프리마켓(NXT) & 시초가 갭 포착", color='#F8FAFC',
            fontproperties=bold_prop, fontsize=21, ha='center', va='center', zorder=4)
    ax.text(50, 84.5, "장전 50분간 수급 1위 종목과 9시 동시호가 급등 테마 팩트체크", color='#94A3B8',
            fontproperties=font_prop, fontsize=12, ha='center', va='center', zorder=4)

    # -------------------------------------------------------------
    # SECTION 1: NXT PRE-MARKET LEADER CARD
    # -------------------------------------------------------------
    nxt = data.get("nxt_premarket_leader", {
        "name": "SK하이닉스", "change_pct": 3.8, "trade_amount_krw": "553억원", "driver": "HBM4 독점 공급 속보"
    })

    card1 = patches.FancyBboxPatch(
        (8, 62), 84, 19.5,
        boxstyle="round,pad=1.0,rounding_size=1.8",
        fc='#111827', ec='#F59E0B', lw=2.0, zorder=3
    )
    ax.add_patch(card1)

    # Tag Badge
    tag1 = patches.FancyBboxPatch(
        (12, 77.2), 48, 3.2,
        boxstyle="round,pad=0.4,rounding_size=0.8",
        fc='#B45309', ec='#F59E0B', lw=1.0, zorder=4
    )
    ax.add_patch(tag1)
    ax.text(36, 78.8, "⚡ 넥스트레이드(NXT) 프리마켓 수급 1위", color='#FEF3C7',
            fontproperties=bold_prop, fontsize=12, ha='center', va='center', zorder=5)

    ax.text(14, 72.5, nxt['name'], color='#FFFFFF',
            fontproperties=bold_prop, fontsize=24, va='center', zorder=5)
    
    pct_col = '#10B981' if nxt['change_pct'] >= 0 else '#EF4444'
    sign = "+" if nxt['change_pct'] >= 0 else ""
    ax.text(86, 72.5, f"{sign}{nxt['change_pct']:.1f}%", color=pct_col,
            fontproperties=bold_prop, fontsize=26, ha='right', va='center', zorder=5)

    # Sub-data row
    ax.text(14, 67.5, f"거래대금: {nxt.get('trade_amount_krw', '500억원')}", color='#FCD34D',
            fontproperties=bold_prop, fontsize=13, va='center', zorder=5)
    ax.text(14, 64.2, f"핵심 재료: {nxt.get('driver', '장전 호재 속보')}", color='#CBD5E1',
            fontproperties=font_prop, fontsize=12, va='center', zorder=5)

    # -------------------------------------------------------------
    # SECTION 2: 9:00 OPENING EXPECTED GAP TOP 3
    # -------------------------------------------------------------
    card2 = patches.FancyBboxPatch(
        (8, 32), 84, 27,
        boxstyle="round,pad=1.0,rounding_size=1.8",
        fc='#111827', ec='#38BDF8', lw=1.8, zorder=3
    )
    ax.add_patch(card2)

    tag2 = patches.FancyBboxPatch(
        (12, 54.8), 52, 3.2,
        boxstyle="round,pad=0.4,rounding_size=0.8",
        fc='#0369A1', ec='#38BDF8', lw=1.0, zorder=4
    )
    ax.add_patch(tag2)
    ax.text(38, 56.4, "🔥 9시 정규장 시초가 예상 갭상승 TOP 3", color='#E0F2FE',
            fontproperties=bold_prop, fontsize=12, ha='center', va='center', zorder=5)

    gaps = data.get("opening_expected_gaps", [
        {"rank": 1, "name": "한미반도체", "expected_change_pct": 6.4, "catalyst": "AI 반도체 신규 장비 독점 납품"},
        {"rank": 2, "name": "삼성전자", "expected_change_pct": 2.1, "catalyst": "동시호가 순매수 150만 주 유입"},
        {"rank": 3, "name": "삼천당제약", "expected_change_pct": 5.2, "catalyst": "유럽 기술수출 본계약 임박"}
    ])

    for i, item in enumerate(gaps[:3]):
        y_pos = 48.5 - (i * 7.2)
        # Row pill container
        r_box = patches.FancyBboxPatch(
            (11, y_pos - 1.2), 78, 5.8,
            boxstyle="round,pad=0.5,rounding_size=1.0",
            fc='#1E293B', ec='#475569', lw=1.0, zorder=4
        )
        ax.add_patch(r_box)

        # Rank pill
        rnk_pill = patches.FancyBboxPatch(
            (13, y_pos + 0.3), 5.5, 3.0,
            boxstyle="round,pad=0.2,rounding_size=0.6",
            fc='#38BDF8', ec='#38BDF8', lw=0.5, zorder=5
        )
        ax.add_patch(rnk_pill)
        ax.text(15.75, y_pos + 1.8, f"#{item['rank']}", color='#0F172A',
                fontproperties=bold_prop, fontsize=12, ha='center', va='center', zorder=6)

        # Stock Name
        ax.text(21, y_pos + 1.8, item['name'], color='#FFFFFF',
                fontproperties=bold_prop, fontsize=15, va='center', zorder=5)
        # Expected %
        ax.text(56, y_pos + 1.8, f"+{item['expected_change_pct']:.1f}%", color='#34D399',
                fontproperties=bold_prop, fontsize=16, va='center', zorder=5)
        # Catalyst note
        ax.text(21, y_pos - 0.2, item.get('catalyst', ''), color='#94A3B8',
                fontproperties=font_prop, fontsize=11, va='center', zorder=5)

    # -------------------------------------------------------------
    # SECTION 3: REAL-TIME ACTION & RISK PROTECTION
    # -------------------------------------------------------------
    card3 = patches.FancyBboxPatch(
        (8, 11), 84, 18,
        boxstyle="round,pad=1.0,rounding_size=1.8",
        fc='#1A0B14', ec='#EF4444', lw=2.0, zorder=3
    )
    ax.add_patch(card3)

    tag3 = patches.FancyBboxPatch(
        (12, 24.8), 54, 3.2,
        boxstyle="round,pad=0.4,rounding_size=0.8",
        fc='#991B1B', ec='#EF4444', lw=1.0, zorder=4
    )
    ax.add_patch(tag3)
    ax.text(39, 26.4, "⚠️ [실전 행동 강령] 시초가 갭메우기 낚시 주의!", color='#FEE2E2',
            fontproperties=bold_prop, fontsize=12, ha='center', va='center', zorder=5)

    ax.text(14, 20.0, "• 9시 땡 치자마자 추격 매수 시 9시 5분 '갭메우기 급락' 위험", color='#FCA5A5',
            fontproperties=bold_prop, fontsize=12.5, va='center', zorder=5)
    ax.text(14, 16.0, "• 9시 15분까지 당일 시가 지지선 & 외인 순매수 확인 후 분할 진입", color='#FDE047',
            fontproperties=bold_prop, fontsize=12.5, va='center', zorder=5)
    ax.text(14, 12.5, "• 원칙 없는 뇌동매매 금지! 검증된 데이터로 계좌를 지키세요.", color='#E2E8F0',
            fontproperties=font_prop, fontsize=11.5, va='center', zorder=5)

    # Footer
    ax.text(50, 5.5, "매일 아침 08:50 긴급 속보 브리핑 | 퀀트 시황 채널 구독 필수", color='#64748B',
            fontproperties=font_prop, fontsize=11, ha='center', va='center', zorder=4)

    plt.subplots_adjust(left=0, right=1, top=1, bottom=0)
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    fig.savefig(output_path, dpi=160, facecolor=fig.get_facecolor(), edgecolor='none')
    plt.close(fig)

    print(f"✅ [그래픽 렌더링 완료] 1440x2560 QHD 인포그래픽: {output_path}")
    return output_path

if __name__ == "__main__":
    create_premarket_visual()

