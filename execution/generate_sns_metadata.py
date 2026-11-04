import os
import sys
import json
from datetime import datetime

# Ensure UTF-8 output
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

def generate_sns_metadata(
    json_path: str = ".tmp/market_anomaly_today.json",
    output_path: str = ".tmp/sns_metadata_today.json"
):
    """
    Generates high-CTR, SEO-optimized metadata (Title, Description/Caption, Tags, Hashtags)
    specifically tuned for YouTube Shorts and Instagram Reels algorithms.
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
    headlines = data.get("market_headlines", [])

    sox_pct = sox.get("change_pct", -7.2)
    k2_pct = k2.get("change_pct", 2.13)
    sox_sign = "+" if sox_pct >= 0 else ""
    k2_sign = "+" if k2_pct >= 0 else ""
    sox_dir = "급등" if sox_pct >= 0 else "급락"
    k2_dir = "반등" if k2_pct >= 0 else "급락"

    if sox_pct * k2_pct < 0:
        signal_context = "엇갈린 글로벌 선행 지표"
    elif sox_pct < 0 and k2_pct < 0:
        signal_context = "동반 약세를 보인 글로벌 선행 지표"
    else:
        signal_context = "동반 강세를 보인 글로벌 선행 지표"

    date_str = datetime.now().strftime("%m월 %d일")

    # 1. YouTube Shorts Metadata (User Specified Formula)
    yt_title = "장 열리기 전 필수시청 꼭 알아야 할 주식 시장 핵심 뉴스 3가지 #shorts"

    yt_description = f"""바쁜 출근길, 오늘 아침 주식 시장 트렌드를 딱 3가지로 압축해 드립니다. 
이 3가지만 알고 장에 들어가도 뇌동매매를 피할 수 있습니다. #주식시황 #증시전망 #오늘의뉴스 #경제뉴스 #투자 #주린이

📌 [{date_str} 오늘 아침 핵심 체크 3가지]
1. 글로벌 지표: 필라델피아 반도체 지수 ({sox_sign}{sox_pct:.1f}%) & 빅테크 수급
2. 국내 야간 선물: 코스피200 야간선물 ({k2_sign}{k2_pct:.1f}%) 시초가 영향
3. 실전 대응: 09:00~09:15 외국인 수급 변곡점 및 15분 매매 원칙

※ 본 영상은 데이터 기반 분석 정보이며 매매 권유가 아닙니다.
매일 아침 7시, 가장 빠른 증시 선행 데이터를 전해드립니다. 구독과 알림 설정해 두세요!

#Shorts #주식 #국내증시 #코스피 #삼성전자 #SK하이닉스 #모닝퀀트""".strip()

    yt_tags = [
        "Shorts", "shorts", "주식시황", "증시전망", "오늘의뉴스", "경제뉴스",
        "투자", "주린이", "주식", "코스피", "코스닥", "삼성전자", "SK하이닉스",
        "필라델피아반도체", "야간선물", "모닝퀀트", "시초가매매"
    ]

    # 2. Instagram Reels Metadata
    hl_text = "\n".join([f"• {h}" for h in headlines[:2]]) if headlines else ""
    ig_caption = f"""🚨 오늘 아침 9시 개장 직전, ‘15분 원칙’ 모르면 시초가에 다 털립니다!

밤사이 필라델피아 반도체 {sox_sign}{sox_pct:.1f}% {sox_dir} vs 국내 야간 코스피 선물 {k2_sign}{k2_pct:.1f}% {k2_dir}!
{signal_context} 속에서 계좌를 지키는 실전 매매 3원칙을 1분 만에 짚어드립니다.

{hl_text if hl_text else '• 미국 반도체 쇼크 vs 국내 야간 선물 지지력 테스트'}

✅ [오늘 9시 개장 직후 15분 대응 수칙]
01. 09:00~09:15 섣부른 추격 매수 절대 금지 (관망 구간)
02. 9시 15분까지 외국인 선물·반도체 동시 순매수 확인
03. 당일 시가(Open) 지지선 안착 시에만 분할 진입

매일 아침 7시, 당일 장 시작 전 필수 선행 데이터를 가장 빠르게 전해드립니다.
팔로우하고 매일 아침 손실을 피하세요! 📊

.
.
#주식 #주식스타그램 #재테크 #코스피 #삼성전자 #SK하이닉스 #반도체 #모닝퀀트 #주식공부 #투자스타그램 #경제뉴스 #릴스 #릴스추천 #Shorts #주식초보
""".strip()

    metadata = {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "youtube": {
            "title": yt_title,
            "description": yt_description,
            "tags": yt_tags,
            "categoryId": "27", # Education (or 25: News & Politics)
            "privacyStatus": "unlisted" # Default unlisted for verification, can be 'public'
        },
        "instagram": {
            "caption": ig_caption,
            "media_type": "REELS",
            "share_to_feed": True
        }
    }

    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    print(f"✅ [SNS 메타데이터 생성 완료] 저장 위치: {output_path}")
    print(f"   - 유튜브 쇼츠 제목: {yt_title}")
    print(f"   - 인스타그램 릴스 캡션 길이: {len(ig_caption)}자")
    return metadata

if __name__ == "__main__":
    generate_sns_metadata()

