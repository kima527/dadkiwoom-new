import os
import sys
import json
import asyncio
import edge_tts
import subprocess

# Ensure UTF-8 output
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

class PreMarketStoryteller:
    """
    08:50 개장 10분 전 전용 수석 스토리텔러 엔진.
    넥스트레이드(NXT) 프리마켓 수급과 9시 시초가 갭상승 예상 종목을
    45초 분량의 초긴급 속보 서사 구조로 즉시 창작합니다.
    """

    def __init__(self, data_source=".tmp/premarket_anomaly_today.json"):
        if isinstance(data_source, dict):
            self.data = data_source
        elif os.path.exists(data_source):
            with open(data_source, "r", encoding="utf-8") as f:
                self.data = json.load(f)
        else:
            self.data = {}

    def generate_script(self) -> list[str]:
        nxt = self.data.get("nxt_premarket_leader", {})
        nxt_name = nxt.get("name", "SK하이닉스")
        nxt_pct = nxt.get("change_pct", 3.8)
        nxt_amount = nxt.get("trade_amount_krw", "500억원")
        nxt_driver = nxt.get("driver", "차세대 HBM 독점 공급 소식")

        gaps = self.data.get("opening_expected_gaps", [])
        gap1 = gaps[0] if len(gaps) > 0 else {"name": "한미반도체", "expected_change_pct": 6.4}
        gap2 = gaps[1] if len(gaps) > 1 else {"name": "삼성전자", "expected_change_pct": 2.1}

        lines = [
            # [1단계: 개장 카운트다운 훅]
            "개장 10분 전 긴급 속보! 방금 8시 50분에 마감된 넥스트레이드 프리마켓에서 돈이 가장 많이 몰린 종목 1위는?",

            # [2단계: NXT 프리마켓 1위 팩트]
            f"{nxt_name}가 거래대금 {nxt_amount}을 터뜨리며 플러스 {nxt_pct:.1f}% 갭상승 마감했습니다.",

            # [3단계: 9시 시초가 갭상승 & 테마 촉매]
            f"원인은 장전 터진 {nxt_driver} 때문인데요. 9시 정규장 동시호가에서도 {gap1['name']}가 플러스 {gap1['expected_change_pct']:.1f}%, {gap2['name']}가 플러스 {gap2['expected_change_pct']:.1f}% 갭을 띄우고 있습니다.",

            # [4단계: 시초가 갭메우기 낚시 주의 & 15분 행동 강령]
            "하지만 9시 땡 치자마자 추격 매수하면 9시 5분 갭메우기 하락에 그대로 물릴 수 있습니다. 9시 15분까지 시가 지지선과 외국인 수급을 반드시 확인하고 분할 진입하세요!",

            # [5단계: 클로징 & 구독 CTA]
            "매일 아침 8시 50분, 개장 10분 전 속보를 빠르게 받아보시려면 지금 구독해 두세요!"
        ]
        return lines

def generate_premarket_script_and_audio(
    json_path=".tmp/premarket_anomaly_today.json",
    output_script_path=".tmp/premarket_script.txt",
    output_audio_path=".tmp/premarket_narration.mp3",
    voice="ko-KR-InJoonNeural"
):
    storyteller = PreMarketStoryteller(json_path)
    lines = storyteller.generate_script()
    full_script = " ".join(lines)

    os.makedirs(os.path.dirname(output_script_path), exist_ok=True)
    with open(output_script_path, "w", encoding="utf-8") as f:
        f.write("\n\n".join(lines))

    print("📝 [08:50 긴급 스토리텔링 대본 작성 완료]")
    for i, line in enumerate(lines, 1):
        print(f"  [{i}단계] {line}")

    # Synthesize at +22% speed for high-urgency breaking news delivery
    print(f"\n🎙️ [AI 신경망 속보 음성 합성 중...] Speed: +22%, Voice: {voice}", flush=True)
    async def run_tts():
        communicate = edge_tts.Communicate(full_script, voice, rate="+22%")
        await communicate.save(output_audio_path)

    asyncio.run(run_tts())

    size_kb = os.path.getsize(output_audio_path) / 1024
    print(f"✅ [음성 합성 완료] {output_audio_path} ({size_kb:.1f} KB)")
    return output_script_path, output_audio_path

if __name__ == "__main__":
    generate_premarket_script_and_audio()

