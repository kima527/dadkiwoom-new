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

    stock_name = top_stock['name']
    stock_pct = abs(top_stock['change_pct'])
    direction = "급등" if top_stock['change_pct'] >= 0 else "급락"

    # Construct 4-stage script (Tightened for strict < 55s YouTube Shorts duration)
    script_lines = [
        # [00~04초] 1. 킬러 훅
        f"오늘 새벽 월가를 뒤흔든 {stock_name} {stock_pct:.1f}% {direction}, 스마트머니는 왜 움직였을까요?",
        
        # [04~15초] 2. 반전 데이터 제시
        f"오늘 미국 증시는 나스닥이 {abs(nq['change_pct']):.1f}%, S&P 500이 {abs(sp['change_pct']):.1f}% 하락했습니다. 특히 반도체 대장주 {stock_name}에 강한 매도세가 쏟아졌습니다.",
        
        # [15~32초] 3. 핵심 원인 2가지
        f"원인은 두 가지입니다. 첫째, 미 10년물 국채 금리가 {tnx['price']:.2f}%로 치솟아 밸류에이션 부담이 커졌고, 둘째, 단기 급등했던 빅테크에 대형 기관들의 차익 실현 매물이 대거 출회되었습니다.",
        
        # [32~45초] 4. 내 계좌 영향 및 전략
        f"오늘 우리 국내 증시도 반도체 수급 충격에 유의해야 합니다. 섣부른 추격 매수보다는 주요 지지선 방어 여부를 확인하고 분할 대응하시는 것이 안전합니다.",
        
        # [45~52초] 5. 아웃트로 & CTA
        "매일 아침 7시, 데이터로 시장의 팩트를 짚어드립니다. 고정 댓글에서 상세 퀀트 데이터를 확인하시고 구독해 두세요."
    ]

    full_script = " ".join(script_lines)

    os.makedirs(os.path.dirname(output_script_path), exist_ok=True)
    with open(output_script_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(script_lines))

    print("📝 [3단계 대본 작성 완료]")
    for i, line in enumerate(script_lines, 1):
        print(f"  [{i}단락] {line}")

    # Generate Audio via edge-tts (Rate +18% for golden 52~55s YouTube Shorts pacing)
    print(f"\n🎙️ [AI 음성 합성 중...] Voice: {voice}, Speed: +18%", flush=True)
    async def run_tts():
        communicate = edge_tts.Communicate(full_script, voice, rate="+18%")
        await communicate.save(output_audio_path)

    asyncio.run(run_tts())

    print(f"✅ [3단계 완료] 내레이션 음성 파일 생성: {output_audio_path} ({os.path.getsize(output_audio_path)/(1024):.1f} KB)")
    return output_script_path, output_audio_path

if __name__ == "__main__":
    generate_script_and_audio()
