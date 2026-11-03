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
    voice="ko-KR-InJoonNeural",
    custom_script=None
):
    """
    Generates a high-retention 'Today's Market Briefing' storytelling script.
    Focuses on the 'WHY' behind market moves (oil drop vs tech crash, AI Capex fear, semiconductor shock),
    rather than mechanically reading numbers on screen.
    """
    if os.path.exists(json_path):
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    else:
        data = {}

    if custom_script:
        script_text = custom_script.strip()
        script_lines = [line.strip() for line in script_text.split("\n") if line.strip()]
    else:
        # Default High-Retention "Today's Market Briefing" News Narrative (User's Formula)
        script_lines = [
            # [오프닝 훅]
            "개장 전 반드시 알아야 할 핵심 뉴스만 전해드리는 ‘오늘의 증시 브리핑’ 시작합니다.",
            "유가가 7%나 폭락했는데, 오늘 밤 나스닥은 왜 무너졌을까요? 1분 만에 정리해 드립니다!",
            
            # [간밤 미 증시 양극화 & 원인 요약]
            "간밤 미 증시는 극과 극이었습니다. 다우지수는 올랐지만, 기술주 중심의 나스닥은 1% 넘게 떨어졌는데요. 원인은 크게 두 가지입니다.",
            
            # [원인 1: 유가 급락과 인플레 완화]
            "첫째, 미·이란 종전 협상 기대감에 국제 유가가 7% 넘게 급락했습니다. 인플레이션 우려가 꺾이면서 전통 우량주들은 웃었습니다.",
            
            # [원인 2: AI 빅테크 비용 공포 & 반도체주 줄폭락]
            "하지만 문제는 AI 빅테크였습니다. 오라클이 AI 데이터센터 지으려고 200억 달러라는 역대급 자금 조달에 나선다는 소식이 터진 건데요. 시장은 'AI에 돈이 얼마나 더 들어가는 거냐'라며 비용 공포증이 도졌습니다. 여기에 마벨 테크놀로지 쇼크까지 겹치며 AMD 7%, 마이크론 5% 등 반도체주가 줄폭락했고, 필라델피아 반도체 지수도 3% 넘게 밀렸습니다.",
            
            # [국장 연결 & 실전 대응 가이드]
            "당장 오늘 밤 미 중간선거라는 초대형 이벤트까지 있어서 증시가 잔뜩 얼어붙었는데요. 오늘 국장 반도체 투톱도 변동성이 커질 수 있으니, 무리한 추격 매수보다는 관망세로 대응하시길 권합니다.",
            
            # [아웃트로 & 구독 CTA]
            "구독 누르시고 내일 아침도 빠르게 시황 받아보세요!"
        ]

    full_script = " ".join(script_lines)

    os.makedirs(os.path.dirname(output_script_path), exist_ok=True)
    with open(output_script_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(script_lines))

    print("📝 [3단계 대본 작성 완료: 오늘의 증시 브리핑 스토리텔링 모드]")
    for i, line in enumerate(script_lines, 1):
        print(f"  [{i}단락] {line}")

    # Generate Audio via edge-tts (Rate +20% for punchy, professional YouTube delivery)
    print(f"\n🎙️ [AI 음성 합성 중...] Voice: {voice}, Speed: +20%", flush=True)
    async def run_tts():
        communicate = edge_tts.Communicate(full_script, voice, rate="+20%")
        await communicate.save(output_audio_path)

    asyncio.run(run_tts())

    print(f"✅ [3단계 완료] 내레이션 음성 파일 생성: {output_audio_path} ({os.path.getsize(output_audio_path)/(1024):.1f} KB)")
    return output_script_path, output_audio_path

if __name__ == "__main__":
    generate_script_and_audio()
