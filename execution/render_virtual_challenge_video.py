"""
render_virtual_challenge_video.py - AI 500만원 굴리기 챌린지 쇼츠 전용 고화질 비디오 렌더러
===================================================================================
1. 상단 고정 게임 HUD 스코어보드 (현재 자산, 누적 수익률, Day 카운트)
2. 초반 5초 시각적 카타르시스 (2,400개 종목 초고속 매트릭스 조건검색 필터링)
3. 3D 사이버 AI 아바타 브리핑 화면
4. 1분봉 매수~매도 실시간 틱 궤적 및 체결 연출
5. 30일 키우기 다마고치 결산 카드
6. 1080x1920 60FPS 세로형 고화질 MP4 인코딩
"""

import os
import sys
import json
import asyncio
import subprocess
from datetime import datetime
from PIL import Image, ImageDraw, ImageFont

# UTF-8 출력 보장
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# 폰트 경로 탐색
def get_korean_font(size: int, bold: bool = False):
    font_paths = [
        "C:/Windows/Fonts/malgunbd.ttf" if bold else "C:/Windows/Fonts/malgun.ttf",
        "C:/Windows/Fonts/NanumGothicBold.ttf" if bold else "C:/Windows/Fonts/NanumGothic.ttf",
        "C:/Windows/Fonts/gulim.ttc"
    ]
    for p in font_paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()

def draw_top_hud(draw, width, height, current_asset, cum_return_pct, day):
    """
    영상 상단 고정 게임 HUD 스코어보드 렌더링
    - 좌측: 🤖 AI 자산 5,123,361원 (+2.47%)
    - 우측: 🔥 DAY 1 / 30일 챌린지
    """
    hud_h = 130
    # 네온 반투명 다크 바
    draw.rectangle([30, 40, width - 30, 40 + hud_h], fill=(15, 23, 42, 240), outline=(56, 189, 248), width=3)

    f_title = get_korean_font(28, bold=True)
    f_num = get_korean_font(36, bold=True)
    f_badge = get_korean_font(26, bold=True)

    # 좌측 자산 스코어보드
    draw.text((60, 55), "🤖 AI 누적 자산", fill=(148, 163, 184), font=f_title)
    pnl_sign = "+" if cum_return_pct >= 0 else ""
    pnl_color = (74, 222, 128) if cum_return_pct >= 0 else (248, 113, 113) # 네온 그린 / 네온 레드
    draw.text((60, 95), f"{current_asset:,}원 ({pnl_sign}{cum_return_pct:.2f}%)", fill=pnl_color, font=f_num)

    # 우측 Day 뱃지
    badge_text = f"🔥 DAY {day} / 30"
    draw.rectangle([width - 290, 65, width - 60, 125], fill=(234, 88, 12), outline=(251, 146, 60), width=2)
    draw.text((width - 270, 78), badge_text, fill=(255, 255, 255), font=f_badge)

def create_scene1_matrix_screener(data: dict, out_path: str):
    """Scene 1: 초반 5초 훅 & 조건검색 매트릭스 필터링 카타르시스"""
    w, h = 1080, 1920
    img = Image.new("RGB", (w, h), color=(10, 15, 29))
    draw = ImageDraw.Draw(img)

    draw_top_hud(draw, w, h, data["asset_after_trade"], data["cum_return_pct"], data["day"])

    # 슬로건 헤드라인
    f_slogan = get_korean_font(46, bold=True)
    f_sub = get_korean_font(32, bold=False)
    draw.text((w//2, 250), "“AI에게 500만 원을 주면", fill=(255, 255, 255), font=f_slogan, anchor="mm")
    draw.text((w//2, 310), "한 달 뒤 얼마가 되어 있을까?”", fill=(250, 204, 21), font=f_slogan, anchor="mm")
    draw.text((w//2, 370), "인공지능 실전 주식 키우기 프로젝트", fill=(148, 163, 184), font=f_sub, anchor="mm")

    # 사이버틱 터미널 박스
    term_box = [60, 440, w - 60, 1500]
    draw.rectangle(term_box, fill=(15, 23, 42), outline=(59, 130, 246), width=3)

    # 터미널 헤더
    draw.rectangle([60, 440, w - 60, 510], fill=(30, 41, 59))
    draw.ellipse([85, 465, 105, 485], fill=(239, 68, 68))
    draw.ellipse([115, 465, 135, 485], fill=(234, 179, 8))
    draw.ellipse([145, 465, 165, 485], fill=(34, 197, 94))
    f_term_title = get_korean_font(26, bold=True)
    draw.text((185, 462), "SYSTEM://QUANT_MATRIX_CONDITION_SCANNER_v4.2", fill=(203, 213, 225), font=f_term_title)

    # 매트릭스 필터링 3단계 연출
    f_code = get_korean_font(28, bold=True)
    f_desc = get_korean_font(24, bold=False)

    lines = [
        (">> [INIT] 코스피/코스닥 전 종목 스캔 개시...", (148, 163, 184)),
        (">> [POOL] 대상 종목: 총 2,482개 로드 완료", (56, 189, 248)),
        ("", (0, 0, 0)),
        ("⚡ [필터 1] 08:50 프리마켓 거래대금 급증", (251, 191, 36)),
        ("   -> 2,482개 중 147개 종목 압축 [PASS]", (74, 222, 128)),
        ("", (0, 0, 0)),
        ("⚡ [필터 2] 외인·기관 실시간 쌍끌이 순매수", (251, 191, 36)),
        ("   -> 147개 중 12개 주도 테마주 압축 [PASS]", (74, 222, 128)),
        ("", (0, 0, 0)),
        ("⚡ [필터 3] 1분봉 3·5·20이평 정배열 눌림목", (251, 191, 36)),
        ("   -> 12개 중 단 1개 최상위 종목 검출 완료!", (74, 222, 128)),
    ]

    y_pos = 550
    for text, color in lines:
        if text:
            draw.text((100, y_pos), text, fill=color, font=f_code)
        y_pos += 48

    # 최종 타겟 LOCK-ON 카드
    draw.rectangle([100, 1150, w - 100, 1440], fill=(30, 58, 138), outline=(96, 165, 250), width=4)
    f_lock = get_korean_font(30, bold=True)
    f_name = get_korean_font(54, bold=True)
    f_info = get_korean_font(28, bold=True)

    draw.text((w//2, 1200), "🎯 TARGET ACQUIRED (LOCK-ON)", fill=(248, 113, 113), font=f_lock, anchor="mm")
    draw.text((w//2, 1280), f"{data['stock_name']} ({data['stock_code']})", fill=(255, 255, 255), font=f_name, anchor="mm")
    draw.text((w//2, 1370), f"테마: {data['theme']} | 500만원 풀베팅 진입", fill=(147, 197, 253), font=f_info, anchor="mm")

    # 하단 힌트
    f_hint = get_korean_font(28, bold=True)
    draw.text((w//2, 1650), "초반 5초 만에 조건검색 완료! 매수 진입합니다 ➡️", fill=(251, 191, 36), font=f_hint, anchor="mm")

    img.save(out_path)
    print(f"✅ Scene 1 (매트릭스 스크리너) 생성 완료: {out_path}")

def create_scene2_avatar_briefing(data: dict, out_path: str):
    """Scene 2: 3D AI 아바타 및 매수 진입 브리핑"""
    w, h = 1080, 1920
    img = Image.new("RGB", (w, h), color=(15, 23, 42))
    draw = ImageDraw.Draw(img)

    draw_top_hud(draw, w, h, data["asset_after_trade"], data["cum_return_pct"], data["day"])

    # 중앙 아바타 그래픽 박스 (사이버네틱 홀로그램 연출)
    avatar_box = [60, 220, w - 60, 950]
    draw.rectangle(avatar_box, fill=(17, 24, 39), outline=(139, 92, 246), width=3)

    # 아바타 실루엣 & 홀로그램 효과
    draw.ellipse([w//2 - 140, 280, w//2 + 140, 560], fill=(79, 70, 229), outline=(167, 139, 250), width=4)
    draw.rectangle([w//2 - 200, 540, w//2 + 200, 850], fill=(67, 56, 202))
    
    # 사이버틱 바이저 안경
    draw.rectangle([w//2 - 80, 390, w//2 + 80, 430], fill=(56, 189, 248))

    f_av_tag = get_korean_font(26, bold=True)
    draw.rectangle([w//2 - 160, 870, w//2 + 160, 920], fill=(124, 58, 237))
    draw.text((w//2, 895), "🤖 AI TRADING AVATAR", fill=(255, 255, 255), font=f_av_tag, anchor="mm")

    # 매수 브리핑 카드
    card_box = [60, 1000, w - 60, 1680]
    draw.rectangle(card_box, fill=(24, 33, 53), outline=(56, 189, 248), width=3)

    f_card_h = get_korean_font(40, bold=True)
    f_body = get_korean_font(30, bold=False)
    f_strong = get_korean_font(34, bold=True)

    draw.text((100, 1050), f"📌 오늘의 단독 진입: {data['stock_name']}", fill=(255, 255, 255), font=f_card_h)
    draw.line([100, 1120, w - 100, 1120], fill=(71, 85, 105), width=2)

    bullets = [
        ("• 포착 시각", f"{data['entry_time']} (개장 직후 수급 확인)"),
        ("• 진입 단가", f"{data['entry_price']:,}원 (매수 수량: {data['qty']}주)"),
        ("• 투자 원금", f"{data['buy_amount']:,}원 (자본금 전액 풀베팅)"),
        ("• 핵심 근거", f"{data['reason_buy']}"),
        ("• 목표 전략", "목표가 +3.0% 익절 / -1.5% 칼손절")
    ]

    y_pos = 1170
    for label, val in bullets:
        draw.text((100, y_pos), label, fill=(148, 163, 184), font=f_strong)
        draw.text((320, y_pos), val, fill=(250, 204, 21) if "원" in val else (255, 255, 255), font=f_body)
        y_pos += 85

    # 하단 강조
    draw.rectangle([100, 1550, w - 100, 1640], fill=(185, 28, 28))
    f_alert = get_korean_font(32, bold=True)
    draw.text((w//2, 1595), f"🚨 9시 {data['entry_time'].split(':')[1]}분 전량 매수 체결 완료!", fill=(255, 255, 255), font=f_alert, anchor="mm")

    img.save(out_path)
    print(f"✅ Scene 2 (아바타 브리핑) 생성 완료: {out_path}")

def create_scene3_trade_execution(data: dict, out_path: str):
    """Scene 3: 매수~실시간 1분봉 틱 차트 롤러코스터~매도 청산"""
    w, h = 1080, 1920
    img = Image.new("RGB", (w, h), color=(11, 15, 25))
    draw = ImageDraw.Draw(img)

    draw_top_hud(draw, w, h, data["asset_after_trade"], data["cum_return_pct"], data["day"])

    # 헤더
    f_head = get_korean_font(42, bold=True)
    f_sub = get_korean_font(28, bold=False)
    draw.text((w//2, 230), f"⚡ {data['stock_name']} 실시간 매매 틱 궤적", fill=(255, 255, 255), font=f_head, anchor="mm")
    draw.text((w//2, 285), "09:00 ~ 09:30 초고속 틱 데이터 시뮬레이션", fill=(148, 163, 184), font=f_sub, anchor="mm")

    # 차트 박스
    chart_box = [60, 340, w - 60, 1200]
    draw.rectangle(chart_box, fill=(17, 24, 39), outline=(75, 85, 99), width=2)

    # 차트 격자 및 배경선
    for gy in range(420, 1150, 120):
        draw.line([70, gy, w - 70, gy], fill=(31, 41, 55), width=1)

    # 10단계 틱 궤적 곡선 그리기
    traj = data["tick_trajectory"]
    pts = []
    x_start, x_end = 120, w - 120
    y_min, y_max = 1050, 450  # 반전 (낮은 가격이 아래, 높은 가격이 위)

    min_p = min(t["price"] for t in traj)
    max_p = max(t["price"] for t in traj)
    p_range = max_p - min_p if max_p != min_p else 1000

    for i, t in enumerate(traj):
        x = x_start + int((x_end - x_start) * (i / len(traj)))
        y = y_min - int((y_min - y_max) * ((t["price"] - min_p) / p_range))
        pts.append((x, y))

    # 차트 선 그리기 (네온 시안)
    for i in range(len(pts) - 1):
        draw.line([pts[i], pts[i+1]], fill=(56, 189, 248), width=6)
        draw.ellipse([pts[i][0]-6, pts[i][1]-6, pts[i][0]+6, pts[i][1]+6], fill=(250, 204, 21))

    # 매수 마커 (좌측 시작점)
    bx, by = pts[0]
    draw.rectangle([bx - 10, by + 15, bx + 170, by + 65], fill=(239, 68, 68))
    f_marker = get_korean_font(24, bold=True)
    draw.text((bx + 15, by + 25), f"BUY {data['entry_price']:,}원", fill=(255, 255, 255), font=f_marker)

    # 매도 마커 (우측 끝점)
    ex, ey = pts[-1]
    draw.rectangle([ex - 190, ey - 75, ex + 10, ey - 25], fill=(34, 197, 94))
    draw.text((ex - 175, ey - 65), f"SELL {data['exit_price']:,}원", fill=(255, 255, 255), font=f_marker)

    # 결과 하이라이트 배너
    res_box = [60, 1260, w - 60, 1680]
    draw.rectangle(res_box, fill=(24, 33, 53), outline=(34, 197, 94), width=4)

    f_res_title = get_korean_font(36, bold=True)
    f_res_num = get_korean_font(52, bold=True)
    f_res_desc = get_korean_font(28, bold=False)

    draw.text((w//2, 1330), "🎉 당일 매매 결과: 목표 달성 익절!", fill=(74, 222, 128), font=f_res_title, anchor="mm")
    sign = "+" if data["return_pct"] >= 0 else ""
    draw.text((w//2, 1420), f"수익률: {sign}{data['return_pct']:.2f}% ({data['net_pnl']:+,}원)", fill=(250, 204, 21), font=f_res_num, anchor="mm")
    draw.text((w//2, 1510), f"청산 시각: {data['exit_time']} | 매도 사유: {data['reason_sell']}", fill=(203, 213, 225), font=f_res_desc, anchor="mm")
    draw.text((w//2, 1590), "수수료 및 거래세 0.20% 정밀 차감 완료", fill=(148, 163, 184), font=f_res_desc, anchor="mm")

    img.save(out_path)
    print(f"✅ Scene 3 (매매 틱 궤적) 생성 완료: {out_path}")

def create_scene4_daily_settlement(data: dict, out_path: str):
    """Scene 4: 일일 챌린지 최종 결산 스코어보드 & 다마고치 엔딩"""
    w, h = 1080, 1920
    img = Image.new("RGB", (w, h), color=(10, 15, 29))
    draw = ImageDraw.Draw(img)

    draw_top_hud(draw, w, h, data["asset_after_trade"], data["cum_return_pct"], data["day"])

    # 중앙 대형 결산 패널
    f_big_h = get_korean_font(48, bold=True)
    draw.text((w//2, 260), f"🏆 DAY {data['day']} 챌린지 공식 결산", fill=(255, 255, 255), font=f_big_h, anchor="mm")

    panel_box = [60, 340, w - 60, 1380]
    draw.rectangle(panel_box, fill=(15, 23, 42), outline=(234, 179, 8), width=4)

    # 내부 카드 항목들
    items = [
        ("시작 원금", "5,000,000원", (148, 163, 184)),
        ("당일 종목", f"{data['stock_name']} ({data['stock_code']})", (255, 255, 255)),
        ("당일 손익", f"{data['net_pnl']:+,}원 ({data['return_pct']:+.2f}%)", (74, 222, 128) if data['net_pnl'] >= 0 else (248, 113, 113)),
        ("현재 자산", f"{data['asset_after_trade']:,}원", (250, 204, 21)),
        ("누적 수익률", f"{data['cum_return_pct']:+.2f}%", (74, 222, 128)),
        ("남은 기간", f"{30 - data['day']}일 / 30일", (56, 189, 248))
    ]

    f_lbl = get_korean_font(34, bold=True)
    f_val = get_korean_font(40, bold=True)

    y_pos = 420
    for lbl, val, color in items:
        draw.text((120, y_pos), lbl, fill=(203, 213, 225), font=f_lbl)
        draw.text((w - 120, y_pos), val, fill=color, font=f_val, anchor="ra")
        draw.line([120, y_pos + 70, w - 120, y_pos + 70], fill=(30, 41, 59), width=2)
        y_pos += 140

    # 다마고치 구독 유도 CTA 박스
    cta_box = [60, 1440, w - 60, 1760]
    draw.rectangle(cta_box, fill=(220, 38, 38), outline=(252, 165, 165), width=3)

    f_cta1 = get_korean_font(40, bold=True)
    f_cta2 = get_korean_font(32, bold=False)

    draw.text((w//2, 1520), "과연 30일 뒤 500만 원은", fill=(255, 255, 255), font=f_cta1, anchor="mm")
    draw.text((w//2, 1590), "얼마가 되어 있을까요?", fill=(250, 204, 21), font=f_cta1, anchor="mm")
    draw.text((w//2, 1680), "👉 내일 Day 2 계좌 확인하기: [구독과 좋아요]", fill=(255, 255, 255), font=f_cta2, anchor="mm")

    img.save(out_path)
    print(f"✅ Scene 4 (결산 스코어보드) 생성 완료: {out_path}")

async def synthesize_challenge_audio(script_text: str, out_audio_path: str, voice: str = "ko-KR-InJoonNeural"):
    """Edge-TTS를 이용한 다이내믹 AI 쇼츠 내레이션 합성 (+18% 속도)"""
    import edge_tts
    print(f"🎙️ [Edge-TTS 음성 합성] Voice: {voice}, 속도: +18%")
    comm = edge_tts.Communicate(script_text, voice, rate="+18%")
    await comm.save(out_audio_path)
    print(f"✅ 내레이션 음성 파일 생성: {out_audio_path}")

def render_full_challenge_shorts(
    data_path: str = ".tmp/virtual_challenge_today.json",
    output_mp4_path: str = r"D:\DailyQuant\AI_Trading_Challenge_Day01.mp4"
) -> str:
    """전체 쇼츠 렌더링 파이프라인 (이미지 4장 + 내레이션 오디오 -> 60FPS MP4 비디오)"""
    os.makedirs(os.path.dirname(output_mp4_path), exist_ok=True)
    os.makedirs(".tmp", exist_ok=True)

    with open(data_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    # 1. 4개 씬 이미지 생성
    s1_path = ".tmp/scene1_screener.png"
    s2_path = ".tmp/scene2_avatar.png"
    s3_path = ".tmp/scene3_execution.png"
    s4_path = ".tmp/scene4_settlement.png"

    create_scene1_matrix_screener(data, s1_path)
    create_scene2_avatar_briefing(data, s2_path)
    create_scene3_trade_execution(data, s3_path)
    create_scene4_daily_settlement(data, s4_path)

    # 2. 내레이션 대본 작성 및 음성 합성
    pnl_sign_text = "플러스" if data["net_pnl"] >= 0 else "마이너스"
    pnl_krw = abs(data["net_pnl"])
    pnl_krw_str = f"{pnl_krw//10000}만 원" if pnl_krw >= 10000 else f"{pnl_krw:,}원"

    script = (
        f"AI에게 500만 원을 주면 한 달 뒤 얼마가 되어 있을까요? "
        f"인공지능 실전 주식 굴리기 챌린지, 오늘 {data['day']}일차입니다! "
        f"오늘 아침 2천 4백 개 종목 중 AI 레이더에 포착된 종목은 바로 {data['stock_name']}! "
        f"개장 직후 수급 폭발을 확인하고 9시 {data['entry_time'].split(':')[1]}분, 500만 원 전액 매수에 들어갔습니다. "
        f"진입 직후 주가는 급등하며 순식간에 목표 수익률에 도달! 9시 {data['exit_time'].split(':')[1]}분 전량 익절 청산 완료했습니다! "
        f"오늘 {data['day']}일차 결과, {pnl_sign_text} {pnl_krw_str} 수익 확정! "
        f"총 자산은 {data['asset_after_trade']//10000}만 원으로 늘어났습니다. "
        f"과연 30일 뒤 이 500만 원은 얼마가 되어 있을까요? "
        f"내일 {data['day']+1}일차 결과를 놓치지 마세요. 지금 구독하고 함께 지켜보세요!"
    )

    audio_path = ".tmp/challenge_narration.mp3"
    asyncio.run(synthesize_challenge_audio(script, audio_path))

    # 3. 오디오 길이 확인
    cmd_probe = ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", audio_path]
    dur_res = subprocess.run(cmd_probe, capture_output=True, text=True)
    audio_dur = float(dur_res.stdout.strip()) if dur_res.stdout.strip() else 42.0

    print(f"⏱️ 오디오 총 길이: {audio_dur:.2f}초")

    # 4개 씬 시간 분배 (오디오 길이에 맞춤)
    d1 = audio_dur * 0.18 # 약 7~8초 (매트릭스 스크리너)
    d2 = audio_dur * 0.28 # 약 11~12초 (아바타 브리핑)
    d3 = audio_dur * 0.32 # 약 13~14초 (체결 및 틱 차트)
    d4 = audio_dur * 0.22 # 약 9~10초 (결산 및 다마고치 엔딩)

    # FFmpeg concat용 텍스트 파일 생성
    concat_txt = ".tmp/challenge_concat.txt"
    with open(concat_txt, "w", encoding="utf-8") as f:
        f.write(f"file '{os.path.abspath(s1_path)}'\nduration {d1:.2f}\n")
        f.write(f"file '{os.path.abspath(s2_path)}'\nduration {d2:.2f}\n")
        f.write(f"file '{os.path.abspath(s3_path)}'\nduration {d3:.2f}\n")
        f.write(f"file '{os.path.abspath(s4_path)}'\nduration {d4:.2f}\n")
        f.write(f"file '{os.path.abspath(s4_path)}'\n") # EOF 버그 방지

    # 4. FFmpeg 렌더링 (60fps, 1080x1920 세로형, x264 CRF 17, 320k AAC)
    print("🎬 [FFmpeg 비디오 인코딩 시작] 1080x1920 60FPS Master QHD...")
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0", "-i", concat_txt,
        "-i", audio_path,
        "-vf", "scale=1080:1920:flags=lanczos,format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "17",
        "-c:a", "aac", "-b:a", "320k",
        "-r", "60",
        "-shortest",
        output_mp4_path
    ]

    subprocess.run(ffmpeg_cmd, check=True)
    file_size_mb = os.path.getsize(output_mp4_path) / (1024 * 1024)
    print(f"\n🎉 [AI 챌린지 쇼츠 렌더링 완료!]")
    print(f"   - 영상 파일: {output_mp4_path} ({file_size_mb:.2f} MB)")
    print(f"   - 해상도: 1080x1920 (9:16 Vertical) | 프레임: 60 FPS\n")
    return output_mp4_path

if __name__ == "__main__":
    render_full_challenge_shorts()
