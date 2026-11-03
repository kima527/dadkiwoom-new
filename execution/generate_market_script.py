import os
import sys
import json
import asyncio
import edge_tts
from storyteller_agent import FinancialStoryteller

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
    수석 경제 전문 스토리텔러 엔진(FinancialStoryteller)을 영입하여
    고몰입 6단계 뉴스 브리핑 서사 대본을 자동 생성하고 Edge-TTS 신경망 음성을 합성합니다.
    """
    if custom_script:
        script_text = custom_script.strip()
        script_lines = [line.strip() for line in script_text.split("\n") if line.strip()]
        print("📝 [수동 커스텀 대본 모드 가동]")
    else:
        # Storytelling Expert Engine Call
        storyteller = FinancialStoryteller(data_source=json_path)
        script_lines = storyteller.generate_story_script()
        print("📝 [스토리텔링 전문가 모드: 6단계 황금 서사 대본 자동 생성 완료]")

    full_script = " ".join(script_lines)

    os.makedirs(os.path.dirname(output_script_path), exist_ok=True)
    with open(output_script_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(script_lines))

    for i, line in enumerate(script_lines, 1):
        print(f"  [{i}단계] {line}")

    # Generate Audio via edge-tts (Rate +20% for punchy, professional YouTube delivery)
    print(f"\n🎙️ [AI 신경망 음성 합성 중...] Voice: {voice}, Speed: +20%", flush=True)
    async def run_tts():
        communicate = edge_tts.Communicate(full_script, voice, rate="+20%")
        await communicate.save(output_audio_path)

    asyncio.run(run_tts())

    audio_size_kb = os.path.getsize(output_audio_path) / 1024
    print(f"✅ [대본/음성 합성 완료] 음성 파일 생성: {output_audio_path} ({audio_size_kb:.1f} KB)")
    return output_script_path, output_audio_path

if __name__ == "__main__":
    generate_script_and_audio()
