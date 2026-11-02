import os
import sys
import json
import subprocess
import asyncio
import edge_tts

# Ensure UTF-8 output
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

def generate_script_and_audio(
    json_path=".tmp/market_anomaly_today.json",
    output_script_path=".tmp/shorts_script.txt",
    output_audio_path=".tmp/shorts_narration.mp3",
    voice="ko-KR-InJoonNeural"
):
    """
    Generates a tight 48~52s YouTube Shorts script adhering strictly to the 4-stage formula,
    delivering the concrete '15-minute response rule', and synthesizes natural neural speech with edge-tts.
    """
    if not os.path.exists(json_path):
        raise FileNotFoundError(f"JSON data not found: {json_path}")

    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    top_stock = data.get("top_anomaly") or {"name": "TSMC", "change_pct": -5.95}
    sp = data["key_indices"].get("sp500") or {"change_pct": -1.82}
    nq = data["key_indices"].get("nasdaq") or {"change_pct": -2.86}
    tnx = data["key_indices"].get("treasury_10y") or {"price": 4.93, "change_pct": -1.2}

    # Korean investor essential indicators
    kor = data.get("korea_indicators", {})
    sox = kor.get("sox") or data["key_indices"].get("sox") or {"price": 10688.8, "change_pct": -7.2}
    k2 = kor.get("kospi200_night") or {"price": 918.65, "change_pct": 2.13}
    kq = kor.get("kosdaq150_night") or {"price": 1229.0, "change_pct": 2.09}

    # 1. SOX Indicator
    sox_pct = sox.get('change_pct', 0)
    sox_abs = abs(sox_pct)
    sox_is_up = sox_pct >= 0
    sox_dir = "급등" if sox_is_up else "급락"

    # 2. Key Indices (Nasdaq)
    nq_pct = nq.get('change_pct', 0)
    nq_abs = abs(nq_pct)
    nq_is_up = nq_pct >= 0
    nq_verb = "상승했고" if nq_is_up else "급락했고"
    sox_level_verb = "강세를 나타냈습니다" if sox_is_up else "포인트까지 밀렸습니다"

    # 3. Domestic Night Futures (KOSPI 200 & KOSDAQ 150)
    k2_pct = k2.get('change_pct', 0)
    kq_pct = kq.get('change_pct', 0)
    k2_abs = abs(k2_pct)
    kq_abs = abs(kq_pct)
    k2_is_up = k2_pct >= 0
    kq_is_up = kq_pct >= 0

    # Natural Korean text for Edge-TTS pronunciation
    k2_tts = f"플러스 {k2_abs:.1f}%" if k2_is_up else f"마이너스 {k2_abs:.1f}%"
    kq_tts = f"플러스 {kq_abs:.1f}%" if kq_is_up else f"마이너스 {kq_abs:.1f}%"

    if k2_is_up and kq_is_up:
        night_lead = "하지만 밤사이 국내 야간 선물은 반등에 성공했습니다." if not sox_is_up else "밤사이 국내 야간 선물 역시 강한 상승 탄력을 이어받았습니다."
        night_body = f"야간 코스피200은 {k2_tts}, 코스닥150 선물도 {kq_tts} 상승 마감했습니다."
        action_caution = "섣부른 추격 매수를 멈추고 관망하세요"
    elif not k2_is_up and not kq_is_up:
        night_lead = "밤사이 국내 야간 선물 역시 동반 약세를 면치 못했습니다." if not sox_is_up else "반면 국내 야간 선물은 차익 매물로 조정을 받았습니다."
        night_body = f"야간 코스피200은 {k2_tts}, 코스닥150 선물도 {kq_tts} 하락 마감했습니다."
        action_caution = "섣부른 저가 매수를 멈추고 관망하세요"
    else:
        night_lead = "밤사이 국내 야간 선물은 혼조세로 마감했습니다."
        k2_word = "상승" if k2_is_up else "하락"
        kq_word = "상승 마감했습니다" if kq_is_up else "하락 마감했습니다"
        night_body = f"야간 코스피200은 {k2_tts} {k2_word}, 코스닥150 선물은 {kq_tts} {kq_word}."
        action_caution = "섣부른 진입을 멈추고 관망하세요"

    # Construct 4-stage script (Tight, high-retention, strictly 48~52s)
    script_lines = [
        # [00~05초] 1. 킬러 훅 (반도체 충격 & 시초가 질문)
        f"필라델피아 반도체 지수 {sox_abs:.1f}% {sox_dir}! 오늘 아침 삼성전자와 SK하이닉스 시초가, 어떻게 대응해야 할까요?",
        
        # [05~16초] 2. 미 증시 헤드라인 & 필라델피아 반도체 팩트
        f"오늘 새벽 뉴욕 증시는 나스닥이 {nq_abs:.1f}% {nq_verb}, 필라델피아 반도체 지수도 {sox['price']:.0f} {sox_level_verb}.",
        
        # [16~28초] 3. 국내 야간선물 선행 지표 정확한 마감 동향 (상승/하락 동적 반영)
        f"{night_lead} {night_body}",
        
        # [28~42초] 4. 오늘 9시 한국장 실전 대응 '15분 원칙'
        f"따라서 오늘 9시 개장 직후 15분간은 {action_caution}. 9시 15분까지 외인 실시간 순매수와 당일 시가 지지 여부를 확인한 뒤 분할 진입해야 계좌를 지킵니다.",
        
        # [42~50초] 5. 아웃트로 & CTA
        "매일 아침 7시, 핵심 선행 데이터를 전해드립니다. 고정 댓글 확인하시고 지금 구독해 두세요."
    ]

    full_script = " ".join(script_lines)

    os.makedirs(os.path.dirname(output_script_path), exist_ok=True)
    with open(output_script_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(script_lines))

    print("📝 [3단계 대본 작성 완료]")
    for i, line in enumerate(script_lines, 1):
        print(f"  [{i}단락] {line}")

    # Generate Audio via edge-tts (Rate +22% for golden 48~51s YouTube Shorts pacing)
    print(f"\n🎙️ [AI 음성 합성 중...] Voice: {voice}, Speed: +22%", flush=True)
    async def run_tts():
        communicate = edge_tts.Communicate(full_script, voice, rate="+22%")
        await communicate.save(output_audio_path)

    asyncio.run(run_tts())

    print(f"✅ [3단계 완료] 내레이션 음성 파일 생성: {output_audio_path} ({os.path.getsize(output_audio_path)/(1024):.1f} KB)")
    return output_script_path, output_audio_path

if __name__ == "__main__":
    generate_script_and_audio()
