import os
import sys
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
import matplotlib.patches as patches
import numpy as np
from PIL import Image

# Ensure UTF-8 output
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

FONT_PATH = "C:/Windows/Fonts/malgun.ttf"
if os.path.exists(FONT_PATH):
    font_prop = fm.FontProperties(fname=FONT_PATH)
    plt.rcParams['font.family'] = font_prop.get_name()
plt.rcParams['axes.unicode_minus'] = False

with open(".tmp/market_anomaly_today.json", "r", encoding="utf-8") as f:
    data = json.load(f)

sox = data.get("korea_indicators", {}).get("sox") or {"price": 10688.8, "change_pct": -7.2}
sox_history = [11083.5, 11482.5, 11684.0, 11518.2, 10688.8]
sox_color = "#FF4757" if sox["change_pct"] < 0 else "#00F59B"

fig = plt.figure(figsize=(10.8, 19.2), dpi=100, facecolor="#0A0E17")
ax_bg = fig.add_axes([0, 0, 1, 1], facecolor="#0A0E17")
ax_bg.axis('off')

# Header
ax_bg.text(0.5, 0.945, "DAILY QUANT  |  모닝 퀀트", color="#00F59B", fontsize=22, fontweight='bold', ha='center', fontproperties=font_prop)
ax_bg.text(0.5, 0.915, "미국 증시 마감 & 국내 개장 긴급 브리핑", color="#FFFFFF", fontsize=31, fontweight='bold', ha='center', fontproperties=font_prop)
ax_bg.text(0.5, 0.890, f"기준: {data.get('timestamp', '오늘')} 실시간 데이터", color="#8B949E", fontsize=15, ha='center', fontproperties=font_prop)

# 1. NEW: Market-Moving Headline News Card (Replaces '오늘의 핵심 이상치' badge)
# Position: [left=0.07, bottom=0.765, width=0.86, height=0.105]
ax_news = fig.add_axes([0.07, 0.765, 0.86, 0.105], facecolor="none")
ax_news.axis('off')
ax_news.set_xlim(0, 1)
ax_news.set_ylim(0, 1)

box_news = patches.FancyBboxPatch(
    (0.005, 0.005), 0.99, 0.99,
    boxstyle="round,pad=0.01,rounding_size=0.03",
    transform=ax_news.transAxes,
    linewidth=2.0,
    edgecolor="#FF4757",
    facecolor="#161B22"
)
ax_news.add_patch(box_news)

ax_news.text(0.05, 0.80, "◆ [오늘 아침 증시 영향 핵심 헤드라인 뉴스]", color="#FF6B6B", fontsize=16, fontweight='bold', ha='left', fontproperties=font_prop)
ax_news.plot([0.04, 0.96], [0.65, 0.65], color="#30363D", lw=1.2)

hl_1 = "• 반도체 대장주 급락 및 기술주 차익 실현에 나스닥 2.86% 하락 마감"
hl_2 = "• 미 10년물 국채금리 4.9% 재진입 속 글로벌 증시 밸류에이션 부담 가중"

ax_news.text(0.05, 0.43, hl_1, color="#F0F6FC", fontsize=15, fontweight='bold', ha='left', va='center', fontproperties=font_prop)
ax_news.text(0.05, 0.18, hl_2, color="#C9D1D9", fontsize=14.5, ha='left', va='center', fontproperties=font_prop)

# 2. Middle Chart: Philadelphia Semiconductor (SOX) 5-Day Trend
# Position: [left=0.07, bottom=0.535, width=0.86, height=0.205]
ax_chart = fig.add_axes([0.07, 0.535, 0.86, 0.205], facecolor="#101520")
ax_chart.spines['top'].set_visible(False)
ax_chart.spines['right'].set_visible(False)
ax_chart.spines['left'].set_color('#30363D')
ax_chart.spines['bottom'].set_color('#30363D')
ax_chart.tick_params(colors='#8B949E', labelsize=12)

x_vals = np.arange(len(sox_history))
ax_chart.plot(x_vals, sox_history, color=sox_color, lw=4, marker='o', markersize=8, markerfacecolor='#FFFFFF')
ax_chart.fill_between(x_vals, sox_history, min(sox_history)*0.98, color=sox_color, alpha=0.18)
ax_chart.set_title(f"필라델피아 반도체 지수 (SOX) 최근 5일 추이  |  10,688.8 pt (-7.2%)", color="#C9D1D9", fontsize=16, pad=10, fontproperties=font_prop)
ax_chart.grid(True, color='#21262D', linestyle='--', alpha=0.7)

# 3. Global Scoreboard
ax_score = fig.add_axes([0.07, 0.415, 0.86, 0.088], facecolor="none")
ax_score.axis('off')
ax_score.set_xlim(0, 1)
ax_score.set_ylim(0, 1)
box_score = patches.FancyBboxPatch((0.005, 0.005), 0.99, 0.99, boxstyle="round,pad=0.01,rounding_size=0.03", transform=ax_score.transAxes, linewidth=1.5, edgecolor="#30363D", facecolor="#161B22")
ax_score.add_patch(box_score)
ax_score.text(0.50, 0.85, "◆ 글로벌 핵심 지표 (미 증시 & 국채금리)", color="#58A6FF", fontsize=15, fontweight='bold', ha='center', fontproperties=font_prop)
ax_score.text(0.18, 0.52, "S&P 500", color="#8B949E", fontsize=14, ha='center', fontproperties=font_prop)
ax_score.text(0.18, 0.18, "7580.1 (-1.8%)", color="#FF4757", fontsize=15, fontweight='bold', ha='center', fontproperties=font_prop)
ax_score.text(0.50, 0.52, "나스닥", color="#8B949E", fontsize=14, ha='center', fontproperties=font_prop)
ax_score.text(0.50, 0.18, "25437.0 (-2.9%)", color="#FF4757", fontsize=15, fontweight='bold', ha='center', fontproperties=font_prop)
ax_score.text(0.82, 0.52, "10년 국채금리", color="#8B949E", fontsize=14, ha='center', fontproperties=font_prop)
ax_score.text(0.82, 0.18, "4.93% (-1.2%)", color="#00F59B", fontsize=15, fontweight='bold', ha='center', fontproperties=font_prop)

# 4. Korea Card
ax_kor = fig.add_axes([0.07, 0.305, 0.86, 0.088], facecolor="none")
ax_kor.axis('off')
ax_kor.set_xlim(0, 1)
ax_kor.set_ylim(0, 1)
box_kor = patches.FancyBboxPatch((0.005, 0.005), 0.99, 0.99, boxstyle="round,pad=0.01,rounding_size=0.03", transform=ax_kor.transAxes, linewidth=1.8, edgecolor="#F2CC60", facecolor="#161B22")
ax_kor.add_patch(box_kor)
ax_kor.text(0.50, 0.85, "◆ 한국 개장 필수 체크 (반도체 & 야간선물)", color="#F2CC60", fontsize=15, fontweight='bold', ha='center', fontproperties=font_prop)
ax_kor.text(0.18, 0.52, "필라델피아 반도체", color="#8B949E", fontsize=13, ha='center', fontproperties=font_prop)
ax_kor.text(0.18, 0.18, "10688.8 (-7.2%)", color="#FF4757", fontsize=14, fontweight='bold', ha='center', fontproperties=font_prop)
ax_kor.text(0.50, 0.52, "야간 코스피200선물", color="#8B949E", fontsize=13, ha='center', fontproperties=font_prop)
ax_kor.text(0.50, 0.18, "918.65 (+2.1%)", color="#00F59B", fontsize=14, fontweight='bold', ha='center', fontproperties=font_prop)
ax_kor.text(0.82, 0.52, "야간 코스닥150선물", color="#8B949E", fontsize=13, ha='center', fontproperties=font_prop)
ax_kor.text(0.82, 0.18, "1229.0 (+2.1%)", color="#00F59B", fontsize=14, fontweight='bold', ha='center', fontproperties=font_prop)

# 5. Bottom Checkpoints (Enlarged & Left-aligned)
ax_check = fig.add_axes([0.07, 0.090, 0.86, 0.190], facecolor="none")
ax_check.axis('off')
ax_check.set_xlim(0, 1)
ax_check.set_ylim(0, 1)
box_check = patches.FancyBboxPatch((0.005, 0.005), 0.99, 0.99, boxstyle="round,pad=0.01,rounding_size=0.04", transform=ax_check.transAxes, linewidth=2.0, edgecolor="#388BFD", facecolor="#161B22")
ax_check.add_patch(box_check)
ax_check.text(0.50, 0.87, "◆ [오늘 아침 9시 국내 증시 핵심 체크포인트]", color="#58A6FF", fontsize=18, fontweight='bold', ha='center', fontproperties=font_prop)
ax_check.plot([0.04, 0.96], [0.77, 0.77], color="#30363D", lw=1.5)
ax_check.text(0.05, 0.58, "1. 필라델피아 반도체 변동성  →  삼성전자·SK하이닉스 수급 직결", color="#F0F6FC", fontsize=16.5, fontweight='bold', ha='left', va='center', fontproperties=font_prop)
ax_check.text(0.05, 0.38, "2. 야간 코스피/코스닥 선물 흐름  →  개장 시초가 갭 형성 주시", color="#F0F6FC", fontsize=16.5, fontweight='bold', ha='left', va='center', fontproperties=font_prop)
ax_check.text(0.05, 0.18, "3. 섣부른 시초가 추격 매수 자제, 개장 직후 외국인 현물 순매수 확인", color="#00F59B", fontsize=16.5, fontweight='bold', ha='left', va='center', fontproperties=font_prop)

# Footer
ax_bg.text(0.5, 0.052, "※ 본 영상은 정보 제공 목적이며 매수·매도 추천이 아닙니다.", color="#6E7681", fontsize=13, ha='center', fontproperties=font_prop)
ax_bg.text(0.5, 0.026, "▶ 고정 댓글에서 상세 퀀트 리포트를 확인하세요 | 구독 & 알림설정", color="#00F59B", fontsize=16, fontweight='bold', ha='center', fontproperties=font_prop)

fig.savefig(".tmp/test_headline_full.png", facecolor="#0A0E17")
plt.close()

# Save a crop of the top part (y: 0 to 900) to inspect headline card
im = Image.open(".tmp/test_headline_full.png")
top_crop = im.crop((50, 50, 1030, 850)).convert('RGB')
top_crop.save(r"C:\Users\zoela\.gemini\antigravity\brain\63272223-b3c7-4010-ad97-80ed3a4e19c5\test_headline_top_crop.jpg")
print("Headline prototype rendered successfully!")

