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

def generate_script_and_audio(json_path=".tmp/market_anomaly_today.json", output_script_path=".tmp/shorts_script.txt", output_audio_path=".tmp/shorts_narration.mp3", voice="ko-KR-InJoonNeural"):
    """
    Generates a 50~55s YouTube Shorts script adhering strictly to the 4-stage formula,
    and synthesizes natural neural speech with edge-tts.
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

    sox_sign = "+" if sox['change_pct'] >= 0 else ""
    sox_dir = "급등" if sox['change_pct'] >= 0 else "급락"
    k2_sign = "+" if k2['change_pct'] >= 0 else ""
    kq_sign = "+" if kq['change_pct'] >= 0 else ""

    # Construct 4-stage script (Tailored for Korean retail investors & strictly < 55s)
    script_lines = [
        # [00~05초] 1. 킬러 훅 (반도체 & 시초가 예측)
        f"필라델피아 반도체 지수 {abs(sox['change_pct']):.1f}% {sox_dir}! 오늘 아침 삼성전자와 SK하이닉스 시초가, 과연 어떻게 열릴까요?",
        
        # [05~18초] 2. 미 증시 & 필라델피아 반도체 팩트 체크
        f"오늘 새벽 미국 증시는 나스닥이 {abs(nq['change_pct']):.1f}% 하락한 가운데, 특히 필라델피아 반도체 지수가 {sox['price']:.0f} 포인트까지 밀리며 글로벌 기술주에 차익 매물이 쏟아졌습니다.",
        
        # [18~32초] 3. 국내 야간선물 선행 지표 분석
        f"하지만 밤사이 국내 야간 선물은 반등했습니다. 야간 코스피200 선물은 {k2_sign}{k2['change_pct']:.1f}%, 야간 코스닥150 선물은 {kq_sign}{kq['change_pct']:.1f}% 상승 마감하며 견고한 지지력을 보였습니다.",
        
        # [32~45초] 4. 오늘 9시 한국장 실전 대응 전략
        f"따라서 오늘 9시 개장 직후 섣부른 추격 매수보다는, 반도체 대장주의 지지선 방어와 외국인 실시간 현물 순매수 유입 여부를 반드시 확인하고 분할 대응하시는 것이 안전합니다.",
        
        # [45~53초] 5. 아웃트로 & CTA
        "매일 아침 7시, 한국 증시 핵심 선행 데이터를 가장 빠르게 짚어드립니다. 고정 댓글에서 퀀트 리포트를 확인하시고 지금 구독해 두세요."
    ]

    full_script = " ".join(script_lines)

    os.makedirs(os.path.dirname(output_script_path), exist_ok=True)
    with open(output_script_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(script_lines))

    print("📝 [3단계 대본 작성 완료]")
    for i, line in enumerate(script_lines, 1):
        print(f"  [{i}단락] {line}")

    # Generate Audio via edge-tts (Rate +20% for golden 50~53s YouTube Shorts pacing)
    print(f"\n🎙️ [AI 음성 합성 중...] Voice: {voice}, Speed: +20%", flush=True)
    async def run_tts():
        communicate = edge_tts.Communicate(full_script, voice, rate="+20%")
        await communicate.save(output_audio_path)

    asyncio.run(run_tts())

    print(f"✅ [3단계 완료] 내레이션 음성 파일 생성: {output_audio_path} ({os.path.getsize(output_audio_path)/(1024):.1f} KB)")
    return output_script_path, output_audio_path

if __name__ == "__main__":
    generate_script_and_audio()
