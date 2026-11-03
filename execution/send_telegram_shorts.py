import os
import sys
import requests
import json

# Ensure UTF-8 output
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Add real trading path to sys.path for config
REAL_TRADING_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "real trading")
if REAL_TRADING_DIR not in sys.path:
    sys.path.insert(0, REAL_TRADING_DIR)

import config

def get_telegram_creds():
    token = getattr(config, "TELEGRAM_BOT_TOKEN", None) or os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = getattr(config, "TELEGRAM_CHAT_ID", None) or os.getenv("TELEGRAM_CHAT_ID", "")
    return token, str(chat_id)

def send_shorts_to_telegram(
    video_path: str,
    title: str = "개장 10분 전! 08:50 프리마켓 & 시초가 갭 속보 #Shorts",
    tags: list = None,
    summary_text: str = ""
):
    """
    Sends the rendered YouTube Shorts MP4 directly to the user's Telegram.
    Includes ready-to-copy YouTube title, tags, and summary for 1-click mobile upload.
    """
    token, chat_id = get_telegram_creds()
    if not token or not chat_id:
        print("❌ 텔레그램 토큰 또는 Chat ID가 설정되지 않았습니다.")
        return False

    if not os.path.exists(video_path):
        print(f"❌ 비디오 파일을 찾을 수 없습니다: {video_path}")
        return False

    if tags is None:
        tags = ["#Shorts", "#주식", "#국내증시", "#프리마켓", "#시초가", "#SK하이닉스"]

    tag_str = " ".join(tags)

    # Clean caption for mobile screen
    caption = (
        f"🚨 <b>[유튜브 쇼츠 업로드용 1초 전송]</b>\n\n"
        f"📌 <b>추천 제목 (복사해서 붙여넣기):</b>\n"
        f"<code>{title}</code>\n\n"
        f"🏷️ <b>추천 태그:</b>\n"
        f"<code>{tag_str}</code>\n\n"
        f"💡 <i>영상 우측 상단 [공유] ➡️ [YouTube] 누르면 1초 만에 쇼츠 업로드 완료!</i>"
    )

    url = f"https://api.telegram.org/bot{token}/sendVideo"
    print(f"📲 [텔레그램 전송 시작] 영상 파일: {video_path} ({os.path.getsize(video_path) / (1024*1024):.2f} MB)...")

    try:
        with open(video_path, "rb") as video_file:
            files = {"video": video_file}
            data = {
                "chat_id": chat_id,
                "caption": caption,
                "parse_mode": "HTML",
                "supports_streaming": True
            }
            res = requests.post(url, data=data, files=files, timeout=60)
            if res.status_code == 200:
                print("🎉 [텔레그램 전송 성공] 스마트폰 텔레그램으로 영상과 복사용 텍스트가 발송되었습니다!")
                return True
            else:
                print(f"⚠️ 전송 실패 (상태 코드 {res.status_code}): {res.text}")
                return False
    except Exception as e:
        print(f"❌ 텔레그램 전송 중 오류 발생: {e}")
        return False

if __name__ == "__main__":
    test_video = r"D:\DailyQuant\PreMarket_Urgent_Shorts.mp4"
    send_shorts_to_telegram(test_video)
