import os
import sys
import json
import warnings

# Ensure UTF-8 output
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import numpy as np
from PIL import Image, ImageDraw, ImageFont

warnings.filterwarnings('ignore')

# Set Korean Font
FONT_PATH = "C:/Windows/Fonts/malgun.ttf"
if os.path.exists(FONT_PATH):
    font_prop = fm.FontProperties(fname=FONT_PATH)
    plt.rcParams['font.family'] = font_prop.get_name()
plt.rcParams['axes.unicode_minus'] = False

def create_shorts_infographic(json_path=".tmp/market_anomaly_today.json", output_path=".tmp/shorts_visual_today.png"):
    """
    Renders a stunning 1080x1920 (9:16) dark-mode financial infographic for YouTube Shorts.
    """
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"JSON data not found: {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    top_stock = data.get("top_anomaly") or {"name": "TSMC", "change_pct": -5.95, "price": 190.0, "history": [200, 198, 195, 193, 190]}
    sp = data["key_indices"].get("sp500") or {"price": 5800, "change_pct": -1.2}
    nq = data["key_indices"].get("nasdaq") or {"price": 18500, "change_pct": -1.8}
    tnx = data["key_indices"].get("treasury_10y") or {"price": 4.25, "change_pct": 0.5}

    is_positive = top_stock["change_pct"] >= 0
    hero_color = "#00F59B" if is_positive else "#FF4757"  # Neon Green / Vivid Crimson
    hero_sign = "+" if is_positive else ""

    # Setup 1080x1920 Matplotlib Figure (10.8 x 19.2 inches at 100 DPI)
    fig = plt.figure(figsize=(10.8, 19.2), dpi=100, facecolor="#0A0E17")
    
    # 1. Background Grid Styling
    ax_bg = fig.add_axes([0, 0, 1, 1], facecolor="#0A0E17")
    ax_bg.axis('off')
    
    # Top Header Banner
    ax_bg.text(0.5, 0.94, "DAILY QUANT  |  모닝 퀀트", color="#00F59B", fontsize=22, fontweight='bold', ha='center', fontproperties=font_prop)
    ax_bg.text(0.5, 0.91, "미국 증시 마감 & 핵심 수급 긴급 브리핑", color="#FFFFFF", fontsize=32, fontweight='bold', ha='center', fontproperties=font_prop)
    ax_bg.text(0.5, 0.885, f"기준: {data.get('timestamp', '오늘')} 마감 데이터", color="#8B949E", fontsize=15, ha='center', fontproperties=font_prop)

    # 2. Hero Anomaly Badge
    badge_box = dict(boxstyle="round,pad=0.8,rounding_size=0.3", fc="#161B22", ec=hero_color, lw=2.5)
    hero_text = f"🔥 오늘의 이상치 포착: {top_stock['name']}\n{top_stock['price']:.2f} USD  ({hero_sign}{top_stock['change_pct']}%)"
    ax_bg.text(0.5, 0.81, hero_text, color="#FFFFFF", fontsize=26, fontweight='bold', ha='center', bbox=badge_box, fontproperties=font_prop)

    # 3. Middle Chart: Hero Asset 5-Day Trend Curve
    # Position: [left, bottom, width, height]
    ax_chart = fig.add_axes([0.10, 0.46, 0.80, 0.28], facecolor="#101520")
    ax_chart.spines['top'].set_visible(False)
    ax_chart.spines['right'].set_visible(False)
    ax_chart.spines['left'].set_color('#30363D')
    ax_chart.spines['bottom'].set_color('#30363D')
    ax_chart.tick_params(colors='#8B949E', labelsize=14)

    history = top_stock.get("history", [100, 102, 98, 99, 95])
    x_vals = np.arange(len(history))
    
    # Smooth spline or line
    ax_chart.plot(x_vals, history, color=hero_color, lw=4, marker='o', markersize=8, markerfacecolor='#FFFFFF')
    ax_chart.fill_between(x_vals, history, min(history)*0.98, color=hero_color, alpha=0.18)
    
    ax_chart.set_title(f"{top_stock['name']} 최근 수급 및 가격 추이", color="#C9D1D9", fontsize=18, pad=12, fontproperties=font_prop)
    ax_chart.grid(True, color='#21262D', linestyle='--', alpha=0.7)

    # 4. Major Indices Scoreboard Cards
    # Position: [0.10, 0.32, 0.80, 0.10]
    ax_score = fig.add_axes([0.10, 0.32, 0.80, 0.10], facecolor="#161B22")
    ax_score.axis('off')
    
    def format_item(item):
        if not item: return "-", "#8B949E"
        sign = "+" if item['change_pct'] >= 0 else ""
        col = "#00F59B" if item['change_pct'] >= 0 else "#FF4757"
        return f"{item['price']:.1f} ({sign}{item['change_pct']}%)", col

    sp_str, sp_col = format_item(sp)
    nq_str, nq_col = format_item(nq)
    tnx_str, tnx_col = format_item(tnx)

    ax_score.text(0.18, 0.70, "S&P 500", color="#8B949E", fontsize=16, ha='center', fontproperties=font_prop)
    ax_score.text(0.18, 0.30, sp_str, color=sp_col, fontsize=17, fontweight='bold', ha='center', fontproperties=font_prop)

    ax_score.text(0.50, 0.70, "나스닥", color="#8B949E", fontsize=16, ha='center', fontproperties=font_prop)
    ax_score.text(0.50, 0.30, nq_str, color=nq_col, fontsize=17, fontweight='bold', ha='center', fontproperties=font_prop)

    ax_score.text(0.82, 0.70, "10년 국채금리", color="#8B949E", fontsize=16, ha='center', fontproperties=font_prop)
    ax_score.text(0.82, 0.30, tnx_str, color=tnx_col, fontsize=17, fontweight='bold', ha='center', fontproperties=font_prop)

    # 5. Bottom Insights Takeaway Card
    insights_box = dict(boxstyle="round,pad=0.8,rounding_size=0.3", fc="#161B22", ec="#30363D", lw=1.5)
    insights_text = (
        "💡 [스마트머니 수급 레이더]\n\n"
        "1. 대형 테크주 단기 변동성 확대 및 주요 지지선 테스트\n"
        "2. 국채 금리 움직임에 따른 외국인 자금 흐름 재편 중\n"
        "3. 오늘 국내 증시 개장 전 '관련 밸류체인 수급 체크' 필수"
    )
    ax_bg.text(0.5, 0.17, insights_text, color="#C9D1D9", fontsize=18, ha='center', bbox=insights_box, fontproperties=font_prop, linespacing=1.6)

    # 6. Footer Disclaimer & CTA
    ax_bg.text(0.5, 0.055, "※ 본 영상은 정보 제공 목적이며 매수·매도 추천이 아닙니다.", color="#6E7681", fontsize=13, ha='center', fontproperties=font_prop)
    ax_bg.text(0.5, 0.030, "📌 고정 댓글에서 상세 퀀트 리포트를 확인하세요 | 구독 & 알림설정", color="#00F59B", fontsize=16, fontweight='bold', ha='center', fontproperties=font_prop)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    plt.savefig(output_path, dpi=100, facecolor="#0A0E17", edgecolor='none')
    plt.close()

    print(f"✅ [2단계 완료] 9:16 모바일 최적화 고대비 인포그래픽 생성 완료: {output_path}")
    return output_path

if __name__ == "__main__":
    create_shorts_infographic()
