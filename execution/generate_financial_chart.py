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
import matplotlib.patches as patches
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

    # Korean investor essential indicators
    korea_ind = data.get("korea_indicators", {})
    sox = korea_ind.get("sox") or data["key_indices"].get("sox") or {"price": 10688.8, "change_pct": -7.2}
    k2 = korea_ind.get("kospi200_night") or {"price": 918.65, "change_pct": 2.13}
    kq = korea_ind.get("kosdaq150_night") or {"price": 1229.0, "change_pct": 2.09}

    is_positive = top_stock["change_pct"] >= 0
    hero_color = "#00F59B" if is_positive else "#FF4757"  # Neon Green / Vivid Crimson
    hero_sign = "+" if is_positive else ""

    # Setup 1080x1920 Matplotlib Figure (10.8 x 19.2 inches at 100 DPI)
    fig = plt.figure(figsize=(10.8, 19.2), dpi=100, facecolor="#0A0E17")
    
    # 1. Background Grid Styling
    ax_bg = fig.add_axes([0, 0, 1, 1], facecolor="#0A0E17")
    ax_bg.axis('off')
    
    # Top Header Banner
    ax_bg.text(0.5, 0.945, "DAILY QUANT  |  모닝 퀀트", color="#00F59B", fontsize=22, fontweight='bold', ha='center', fontproperties=font_prop)
    ax_bg.text(0.5, 0.915, "미국 증시 마감 & 국내 개장 긴급 브리핑", color="#FFFFFF", fontsize=31, fontweight='bold', ha='center', fontproperties=font_prop)
    ax_bg.text(0.5, 0.890, f"기준: {data.get('timestamp', '오늘')} 실시간 데이터", color="#8B949E", fontsize=15, ha='center', fontproperties=font_prop)

    # 2. Hero Anomaly Badge
    badge_box = dict(boxstyle="round,pad=0.7,rounding_size=0.3", fc="#161B22", ec=hero_color, lw=2.5)
    hero_text = f"▶ 오늘의 핵심 이상치: {top_stock['name']}\n{top_stock['price']:.2f} USD  ({hero_sign}{top_stock['change_pct']}%)"
    ax_bg.text(0.5, 0.825, hero_text, color="#FFFFFF", fontsize=25, fontweight='bold', ha='center', bbox=badge_box, fontproperties=font_prop)

    # 3. Middle Chart: Hero Asset 5-Day Trend Curve
    # Position: [left, bottom, width, height]
    ax_chart = fig.add_axes([0.07, 0.54, 0.86, 0.22], facecolor="#101520")
    ax_chart.spines['top'].set_visible(False)
    ax_chart.spines['right'].set_visible(False)
    ax_chart.spines['left'].set_color('#30363D')
    ax_chart.spines['bottom'].set_color('#30363D')
    ax_chart.tick_params(colors='#8B949E', labelsize=13)

    history = top_stock.get("history", [100, 102, 98, 99, 95])
    x_vals = np.arange(len(history))
    
    ax_chart.plot(x_vals, history, color=hero_color, lw=4, marker='o', markersize=8, markerfacecolor='#FFFFFF')
    ax_chart.fill_between(x_vals, history, min(history)*0.98, color=hero_color, alpha=0.18)
    
    ax_chart.set_title(f"{top_stock['name']} 최근 수급 및 가격 추이", color="#C9D1D9", fontsize=17, pad=10, fontproperties=font_prop)
    ax_chart.grid(True, color='#21262D', linestyle='--', alpha=0.7)

    def format_item(item):
        if not item: return "-", "#8B949E"
        sign = "+" if item['change_pct'] >= 0 else ""
        col = "#00F59B" if item['change_pct'] >= 0 else "#FF4757"
        return f"{item['price']:.1f} ({sign}{item['change_pct']}%)", col

    # 4. Major Global Indices Scoreboard Card (Row 1)
    # Position: [0.07, 0.42, 0.86, 0.088]
    ax_score = fig.add_axes([0.07, 0.42, 0.86, 0.088], facecolor="none")
    ax_score.axis('off')
    ax_score.set_xlim(0, 1)
    ax_score.set_ylim(0, 1)

    box_score = patches.FancyBboxPatch(
        (0.005, 0.005), 0.99, 0.99,
        boxstyle="round,pad=0.01,rounding_size=0.03",
        transform=ax_score.transAxes,
        linewidth=1.5,
        edgecolor="#30363D",
        facecolor="#161B22"
    )
    ax_score.add_patch(box_score)
    
    sp_str, sp_col = format_item(sp)
    nq_str, nq_col = format_item(nq)
    tnx_str, tnx_col = format_item(tnx)

    ax_score.text(0.50, 0.85, "◆ 글로벌 핵심 지표 (미 증시 & 국채금리)", color="#58A6FF", fontsize=15, fontweight='bold', ha='center', fontproperties=font_prop)
    ax_score.text(0.18, 0.52, "S&P 500", color="#8B949E", fontsize=14, ha='center', fontproperties=font_prop)
    ax_score.text(0.18, 0.18, sp_str, color=sp_col, fontsize=15, fontweight='bold', ha='center', fontproperties=font_prop)

    ax_score.text(0.50, 0.52, "나스닥", color="#8B949E", fontsize=14, ha='center', fontproperties=font_prop)
    ax_score.text(0.50, 0.18, nq_str, color=nq_col, fontsize=15, fontweight='bold', ha='center', fontproperties=font_prop)

    ax_score.text(0.82, 0.52, "10년 국채금리", color="#8B949E", fontsize=14, ha='center', fontproperties=font_prop)
    ax_score.text(0.82, 0.18, tnx_str, color=tnx_col, fontsize=15, fontweight='bold', ha='center', fontproperties=font_prop)

    # 5. Korean Pre-Market Essential Card (Row 2 - SOX & Night Futures)
    # Position: [0.07, 0.31, 0.86, 0.088]
    ax_kor = fig.add_axes([0.07, 0.31, 0.86, 0.088], facecolor="none")
    ax_kor.axis('off')
    ax_kor.set_xlim(0, 1)
    ax_kor.set_ylim(0, 1)

    box_kor = patches.FancyBboxPatch(
        (0.005, 0.005), 0.99, 0.99,
        boxstyle="round,pad=0.01,rounding_size=0.03",
        transform=ax_kor.transAxes,
        linewidth=1.8,
        edgecolor="#F2CC60",
        facecolor="#161B22"
    )
    ax_kor.add_patch(box_kor)

    sox_str, sox_col = format_item(sox)
    k2_str, k2_col = format_item(k2)
    kq_str, kq_col = format_item(kq)

    ax_kor.text(0.50, 0.85, "◆ 한국 개장 필수 체크 (반도체 & 야간선물)", color="#F2CC60", fontsize=15, fontweight='bold', ha='center', fontproperties=font_prop)
    ax_kor.text(0.18, 0.52, "필라델피아 반도체", color="#8B949E", fontsize=13, ha='center', fontproperties=font_prop)
    ax_kor.text(0.18, 0.18, sox_str, color=sox_col, fontsize=14, fontweight='bold', ha='center', fontproperties=font_prop)

    ax_kor.text(0.50, 0.52, "야간 코스피200선물", color="#8B949E", fontsize=13, ha='center', fontproperties=font_prop)
    ax_kor.text(0.50, 0.18, k2_str, color=k2_col, fontsize=14, fontweight='bold', ha='center', fontproperties=font_prop)

    ax_kor.text(0.82, 0.52, "야간 코스닥150선물", color="#8B949E", fontsize=13, ha='center', fontproperties=font_prop)
    ax_kor.text(0.82, 0.18, kq_str, color=kq_col, fontsize=14, fontweight='bold', ha='center', fontproperties=font_prop)

    # 6. Enlarged & Left-Aligned Checkpoint Card (Row 3)
    # Position: [0.07, 0.092, 0.86, 0.190]
    ax_check = fig.add_axes([0.07, 0.092, 0.86, 0.190], facecolor="none")
    ax_check.axis('off')
    ax_check.set_xlim(0, 1)
    ax_check.set_ylim(0, 1)

    box_check = patches.FancyBboxPatch(
        (0.005, 0.005), 0.99, 0.99,
        boxstyle="round,pad=0.01,rounding_size=0.04",
        transform=ax_check.transAxes,
        linewidth=2.0,
        edgecolor="#388BFD",
        facecolor="#161B22"
    )
    ax_check.add_patch(box_check)

    # Card Title (Centered)
    ax_check.text(0.50, 0.87, "◆ [오늘 아침 9시 국내 증시 핵심 체크포인트]", color="#58A6FF", fontsize=18, fontweight='bold', ha='center', fontproperties=font_prop)

    # Divider line
    ax_check.plot([0.04, 0.96], [0.77, 0.77], color="#30363D", lw=1.5)

    # Strictly LEFT-ALIGNED 1, 2, 3 Checkpoints at x = 0.05
    line1 = "1. 필라델피아 반도체 변동성  →  삼성전자·SK하이닉스 수급 직결"
    line2 = "2. 야간 코스피/코스닥 선물 흐름  →  개장 시초가 갭 형성 주시"
    line3 = "3. 섣부른 시초가 추격 매수 자제, 개장 직후 외국인 현물 순매수 확인"

    ax_check.text(0.05, 0.58, line1, color="#F0F6FC", fontsize=16.5, fontweight='bold', ha='left', va='center', fontproperties=font_prop)
    ax_check.text(0.05, 0.38, line2, color="#F0F6FC", fontsize=16.5, fontweight='bold', ha='left', va='center', fontproperties=font_prop)
    ax_check.text(0.05, 0.18, line3, color="#00F59B", fontsize=16.5, fontweight='bold', ha='left', va='center', fontproperties=font_prop)

    # 7. Footer Disclaimer & CTA
    ax_bg.text(0.5, 0.055, "※ 본 영상은 정보 제공 목적이며 매수·매도 추천이 아닙니다.", color="#6E7681", fontsize=13, ha='center', fontproperties=font_prop)
    ax_bg.text(0.5, 0.028, "▶ 고정 댓글에서 상세 퀀트 리포트를 확인하세요 | 구독 & 알림설정", color="#00F59B", fontsize=16, fontweight='bold', ha='center', fontproperties=font_prop)

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    plt.savefig(output_path, dpi=100, facecolor="#0A0E17", edgecolor='none')
    plt.close()

    print(f"✅ [2단계 완료] 9:16 모바일 최적화 고대비 인포그래픽 생성 완료: {output_path}")
    return output_path

if __name__ == "__main__":
    create_shorts_infographic()
