import os
import sys
import json
import asyncio
import subprocess
import edge_tts

# Ensure UTF-8
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

SCRIPTS = [
    {
        "slide_index": 0,
        "slide_id": "slide_00_cover",
        "title": "오프닝 커버: 퀀트 검증소 1부 팩트체크",
        "text": (
            "오늘의 퀀트 팩트체크 제1편! "
            "골든크로스 10년 맹신, 과연 내 계좌를 불려주었을까요? "
            "10년간의 코스피 전수조사 백테스트, 지금 그 진실을 공개합니다!"
        )
    },
    {
        "slide_index": 1,
        "slide_id": "slide_01_hook",
        "title": "도입부 훅: 골든크로스의 배신",
        "text": (
            "주식 투자를 처음 시작할 때, 모든 책과 강의에서 입을 모아 가르쳐주는 공식이 있습니다. "
            "바로 단기 5일선이 20일선을 뚫고 올라가는 '골든크로스'입니다. "
            "추세가 전환되었으니 무조건 분할 매수하라는 이 유명한 격언, 여러분도 한 번쯤 믿고 매수해보셨을 겁니다. "
            "하지만 결과는 어떠셨습니까? 이상하게 내가 사기만 하면 고점이고, 며칠 뒤 폭락해서 손절하기 바쁘지 않으셨습니까? "
            "오늘 퀀트 검증소 1부에서는, 지난 10년간 코스피 200 종목에서 발생한 모든 골든크로스 매매를 파이썬 코드로 전수조사한 "
            "충격적인 백테스트 데이터를 가감 없이 공개합니다."
        )
    },
    {
        "slide_index": 2,
        "slide_id": "slide_02_myth",
        "title": "1장 교과서의 약속: 왜 골든크로스를 신봉할까?",
        "text": (
            "먼저 교과서에서 말하는 골든크로스의 원리부터 짚어보겠습니다. "
            "5일 이동평균선은 최근 일주일 동안 주식을 매수한 투자자들의 평균 단가입니다. "
            "반면 20일선은 한 달 동안 매수한 사람들의 평균 단가죠. "
            "따라서 5일선이 20일선을 골든크로스 한다는 것은, 최근 일주일간의 매수 강세가 한 달간의 매도 압력을 강하게 뚫고 올라섰다는 강력한 수급의 증거로 해석됩니다. "
            "교과서 논리로는 완벽해 보입니다. 당장 내일이라도 대세 상승이 시작될 것 같은 환상을 주죠. "
            "하지만 실제 한국 주식 시장의 10년 역사에서도 이 공식이 과연 수익을 주었을까요?"
        )
    },
    {
        "slide_index": 3,
        "slide_id": "slide_03_trap",
        "title": "2장 잔인한 현실: 횡보장의 덫 '휩소'",
        "text": (
            "우리가 골든크로스에서 매수하자마자 물리는 이유는 명확합니다. "
            "첫째, 이동평균선은 과거 주가의 그림자인 '후행성 지표'이기 때문입니다. 골든크로스가 차트에 찍혔을 때는 이미 바닥 대비 10% 이상 오른 단기 고점인 경우가 대부분입니다. "
            "둘째, 대한민국 코스피 증시는 70%가 박스권 횡보장입니다. "
            "추세가 없는 횡보장에서는 5일선과 20일선이 수시로 엉키며 하루걸러 가짜 신호, 즉 '휩소'를 만들어냅니다. "
            "골든크로스에 사서 물리고, 데드크로스에 털리기를 반복하다 보면 거래세와 슬리피지가 누적되어 원금이 눈 녹듯 사라지게 됩니다."
        )
    },
    {
        "slide_index": 4,
        "slide_id": "slide_04_data",
        "title": "3장 충격의 백테스트: 코스피 10년 전수조사",
        "text": (
            "자, 이제 감정이 아닌 진짜 데이터로 증명해 보겠습니다. "
            "2014년부터 2024년까지 10년간, 코스피 200 전 종목을 대상으로 5일선이 20일선을 골든크로스할 때 매수하고 데드크로스에 매도하는 전략을 시뮬레이션했습니다. "
            "총 418번의 매매가 발생했습니다. 결과는 충격적이었습니다. "
            "승률은 고작 38.5%에 불과했습니다. 열 번 매매하면 여섯 번 넘게 손실을 보았다는 뜻입니다. "
            "10년간 누적 수익률은 마이너스 24.5%, 그리고 계좌가 고점 대비 최대 41.2%까지 폭락했습니다. "
            "단순한 골든크로스만 믿고 매매하는 것은 수학적으로 계좌를 깡통으로 만드는 지름길이었습니다."
        )
    },
    {
        "slide_index": 5,
        "slide_id": "slide_05_solution",
        "title": "4장 퀀트의 해법: 가짜 신호 70%를 걸러내는 2원칙",
        "text": (
            "그렇다면 골든크로스는 완전히 쓸모없는 지표일까요? 아닙니다. "
            "수많은 가짜 신호 중에서 메이저 세력이 개입한 '진짜 골든크로스'만 골라내면 승률은 완전히 뒤바뀝니다. "
            "저희가 찾아낸 핵심 퀀트 필터는 딱 두 가지입니다. "
            "첫째, 교차 당일 20일 평균 거래량의 최소 150% 이상 폭증한 장대양봉을 확인하십시오. 거래량이 없는 골든크로스는 90% 개미 유인용 속임수입니다. "
            "둘째, 주가가 중기 생명선인 60일 이동평균선 위에 위치해야 합니다. 60일선 아래의 역배열 하락 추세에서는 어떤 골든크로스도 쳐다보지 마십시오."
        )
    },
    {
        "slide_index": 6,
        "slide_id": "slide_06_turnaround",
        "title": "5장 승률의 대역전: +318.4%의 기적",
        "text": (
            "이 두 가지 퀀트 필터를 적용하고 동일한 코스피 10년 데이터를 다시 백테스트했습니다. "
            "가짜 신호 70%가 사전에 걸러지면서 매매 횟수는 142회로 압축되었습니다. "
            "그리고 결과는 드라마틱했습니다. "
            "승률은 38.5%에서 64.8%로 무려 26.3% 포인트 상승했습니다. "
            "10년 누적 수익률은 마이너스에서 플러스 318.4%로 수직 상승했고, 최대 낙폭은 마이너스 12.4%로 안정적으로 방어되었습니다. "
            "필터 딱 두 개만 추가했을 뿐인데, 지는 전략이 시장을 압도하는 알파 전략으로 탈바꿈한 것입니다."
        )
    },
    {
        "slide_index": 7,
        "slide_id": "slide_07_checklist_outro",
        "title": "최종 결론: 내일부터 실전에 바로 쓰는 3원칙",
        "text": (
            "오늘의 핵심 내용을 세 가지 원칙으로 요약해 드립니다. "
            "첫째, 단순 이평선 교차만 보고 섣불리 진입하지 마십시오. "
            "둘째, 20일 평균의 1.5배 이상 터진 거래량과 60일선 지지를 반드시 확인하십시오. "
            "셋째, 매수와 동시에 변동성 기준 손절선을 기계적으로 걸어두십시오. "
            "다음 2편에서는 뉴스에서 매일 떠들어대는 '외인과 기관의 양매수 유입', 과연 다음 날 아침 시초가에 사면 돈을 벌 수 있을지 10만 건의 수급 빅데이터로 낱낱이 파헤쳐 드립니다. "
            "오늘 영상이 도움 되셨다면 구독과 알림 설정 부탁드립니다. 성공 투자를 응원합니다. 감사합니다."
        )
    }
]

def get_audio_duration(file_path: str) -> float:
    """Gets audio duration using ffprobe."""
    try:
        cmd = [
            "ffprobe", "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            file_path
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(res.stdout.strip())
    except Exception as e:
        print(f"ffprobe duration check failed for {file_path}: {e}")
        return 45.0

async def synthesize_all_audio(output_dir: str = ".tmp/audio", voice: str = "ko-KR-InJoonNeural"):
    """Synthesizes TTS audio for each slide in parallel."""
    os.makedirs(output_dir, exist_ok=True)
    results = []

    for item in SCRIPTS:
        idx = item["slide_index"]
        text = item["text"]
        out_mp3 = os.path.join(output_dir, f"slide_{idx:02d}.mp3")
        
        print(f"🎙️ [{idx}/{len(SCRIPTS)-1}] 음성 합성 중... ({item['title']})")
        # Rate +10%, Pitch 0Hz for crisp, professional delivery
        communicate = edge_tts.Communicate(text, voice, rate="+10%")
        await communicate.save(out_mp3)

        duration = get_audio_duration(out_mp3)
        print(f"   ✅ 완료: 길이 {duration:.2f}초 ({out_mp3})")
        
        results.append({
            "slide_index": idx,
            "slide_id": item["slide_id"],
            "title": item["title"],
            "audio_path": os.path.abspath(out_mp3),
            "duration": duration,
            "text": text
        })

    # Save summary metadata
    timing_path = ".tmp/longform_script_timing.json"
    with open(timing_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    total_dur = sum(r["duration"] for r in results)
    print("\n" + "=" * 65)
    print(f"🎉 [전체 음성 합성 완료] 총 소요 시간: {total_dur:.1f}초 ({total_dur/60:.2f}분)")
    print(f"📁 타이밍 메타데이터 저장: {timing_path}")
    print("=" * 65 + "\n")
    return results

if __name__ == "__main__":
    asyncio.run(synthesize_all_audio())

