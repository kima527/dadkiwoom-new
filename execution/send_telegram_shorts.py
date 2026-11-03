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
    title: str = "오늘 9시 개장 직전, ‘15분 원칙’ 모르면 시초가에 다 털립니다! #Shorts",
    tags: list = None,
    youtube_url: str = None
):
    """
    Sends the rendered YouTube Shorts MP4 directly to the user's Telegram.
    Includes the live YouTube link if uploaded, or ready-to-copy text for manual review.
    """
    token, chat_id = get_telegram_creds()
    if not token or not chat_id:
        print("❌ 텔레그램 토큰 또는 Chat ID가 설정되지 않았습니다.")
        return False

    if not os.path.exists(video_path):
        print(f"❌ 비디오 파일을 찾을 수 없습니다: {video_path}")
        return False

    if tags is None:
        tags = ["#Shorts", "#주식", "#국내증시", "#모닝퀀트"]

    tag_str = " ".join(tags)

    # Dynamic caption depending on whether auto-uploaded to YouTube
    if youtube_url and "youtube.com" in youtube_url:
        caption = (
            f"🎉 <b>[유튜브 쇼츠 100% 자동 업로드 완료!]</b>\n\n"
            f"📺 <b>유튜브에서 바로 보기:</b>\n"
            f"👉 {youtube_url}\n\n"
            f"📌 <b>게시된 제목:</b>\n"
            f"<code>{title}</code>\n\n"
            f"🏷️ <b>태그:</b>\n"
            f"<code>{tag_str}</code>\n\n"
            f"✅ <i>컴퓨터가 유튜브에 자동 게시를 마쳤습니다. (첨부 영상은 모니터링/보관용 원본 파일입니다)</i>"
        )
    else:
        caption = (
            f"🚨 <b>[유튜브 쇼츠 자동 제작 완료]</b>\n\n"
            f"📌 <b>영상 제목:</b>\n"
            f"<code>{title}</code>\n\n"
            f"🏷️ <b>태그:</b>\n"
            f"<code>{tag_str}</code>\n\n"
            f"💡 <i>(첨부 영상을 확인해 보세요)</i>"
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
