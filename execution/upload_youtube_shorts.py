import os
import sys
import json
import argparse
import time

# Ensure UTF-8 output
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

def get_youtube_service(
    client_secrets_file: str = "client_secrets.json",
    token_file: str = "token_youtube.json"
):
    """
    Authenticates and returns the authorized YouTube Data API service.
    Handles token caching and automatic refresh.
    """
    creds = None
    if os.path.exists(token_file):
        try:
            creds = Credentials.from_authorized_user_file(token_file, SCOPES)
        except Exception as e:
            print(f"⚠️ 기존 토큰 로드 실패: {e}, 재인증을 진행합니다.")

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            print("🔄 만료된 유튜브 인증 토큰을 갱신합니다...", flush=True)
            creds.refresh(Request())
        else:
            if not os.path.exists(client_secrets_file):
                # Check alternative names
                alt_names = ["credentials_youtube.json", "credentials.json"]
                for alt in alt_names:
                    if os.path.exists(alt):
                        client_secrets_file = alt
                        break

            if not os.path.exists(client_secrets_file):
                print("\n" + "=" * 70)
                print("❌ [유튜브 인증 파일 누락 안내]")
                print(f"'{client_secrets_file}' 파일이 프로젝트 루트 폴더에 없습니다.")
                print("\n📌 [간편 설정 3단계]")
                print("1. Google Cloud Console(https://console.cloud.google.com/) 접속")
                print("2. [API 및 서비스] -> [사용자 인증 정보] -> [OAuth 클라이언트 ID] 생성 (유형: 데스크톱 앱)")
                print("3. JSON 다운로드 후 파일명을 'client_secrets.json'으로 변경하여 이 폴더에 저장")
                print("=" * 70 + "\n")
                return None

            print("🔑 최초 1회 브라우저 구글 로그인 인증을 진행합니다...", flush=True)
            flow = InstalledAppFlow.from_client_secrets_file(client_secrets_file, SCOPES)
            try:
                creds = flow.run_local_server(
                    port=8080,
                    authorization_prompt_message="👉 브라우저가 열리지 않으면 아래 링크를 직접 열어주세요:\n{url}\n",
                    success_message="🎉 인증이 성공적으로 완료되었습니다! 이 창을 닫으셔도 좋습니다.",
                    prompt="consent",
                    access_type="offline",
                    open_browser=True
                )
            except Exception as e:
                print(f"포트 8080 재시도 ({e})...", flush=True)
                creds = flow.run_local_server(
                    port=0,
                    authorization_prompt_message="👉 브라우저가 열리지 않으면 아래 링크를 직접 열어주세요:\n{url}\n",
                    success_message="🎉 인증이 성공적으로 완료되었습니다! 이 창을 닫으셔도 좋습니다.",
                    prompt="consent",
                    access_type="offline",
                    open_browser=True
                )

        # Save credentials for future automated runs
        with open(token_file, "w", encoding="utf-8") as token:
            token.write(creds.to_json())
        print(f"💾 인증 토큰 저장 완료: {token_file}")

    return build("youtube", "v3", credentials=creds)

def upload_youtube_shorts(
    video_path: str = r"D:\DailyQuant\Daily_Quant_Shorts_Sample.mp4",
    meta_path: str = ".tmp/sns_metadata_today.json",
    privacy_status: str = "unlisted",
    dry_run: bool = False
):
    """
    Uploads 9:16 vertical video directly to YouTube Shorts with resumable upload.
    """
    if not os.path.exists(video_path):
        print(f"❌ 업로드 실패: 비디오 파일을 찾을 수 없습니다 -> {video_path}")
        return False

    # Load metadata
    title = "장 열리기 전 필수시청 꼭 알아야 할 주식 시장 핵심 뉴스 3가지 #shorts"
    description = (
        "바쁜 출근길, 오늘 아침 주식 시장 트렌드를 딱 3가지로 압축해 드립니다. \n"
        "이 3가지만 알고 장에 들어가도 뇌동매매를 피할 수 있습니다. #주식시황 #증시전망 #오늘의뉴스 #경제뉴스 #투자 #주린이"
    )
    tags = ["Shorts", "주식", "코스피", "모닝퀀트"]
    category_id = "27"

    if os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            yt_data = data.get("youtube", {})
            title = yt_data.get("title", title)
            description = yt_data.get("description", description)
            tags = yt_data.get("tags", tags)
            category_id = yt_data.get("categoryId", category_id)
            if not privacy_status:
                privacy_status = yt_data.get("privacyStatus", "unlisted")

    print("\n" + "=" * 65)
    print("🚀 [유튜브 쇼츠 자동 업로드]")
    print(f"📁 파일: {video_path} ({os.path.getsize(video_path)/(1024*1024):.2f} MB)")
    print(f"🏷️ 제목: {title}")
    print(f"🔒 공개 상태: {privacy_status} (unlisted: 일부공개 / public: 즉시공개)")
    print("=" * 65 + "\n")

    if dry_run:
        print("🔍 [DRY RUN 모드] 실제 업로드는 수행하지 않고 검증을 통과했습니다.")
        return True

    youtube = get_youtube_service()
    if not youtube:
        return False

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": category_id
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False
        }
    }

    # Resumable upload chunk size: 5MB
    media = MediaFileUpload(video_path, chunksize=5*1024*1024, resumable=True, mimetype="video/mp4")

    print("📤 유튜브 서버로 영상 전송을 시작합니다...", flush=True)
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media
    )

    response = None
    start_time = time.time()
    while response is None:
        status, response = request.next_chunk()
        if status:
            progress = int(status.progress() * 100)
            print(f"  ⏳ 업로드 진행률: {progress}%", flush=True)

    elapsed = time.time() - start_time
    video_id = response.get("id")
    video_url = f"https://youtube.com/shorts/{video_id}"

    # Save last uploaded video info
    try:
        os.makedirs(".tmp", exist_ok=True)
        with open(".tmp/last_uploaded_youtube.json", "w", encoding="utf-8") as lf:
            json.dump({
                "video_id": video_id,
                "video_url": video_url,
                "title": title,
                "privacy": privacy_status,
                "uploaded_at": time.strftime("%Y-%m-%d %H:%M:%S")
            }, lf, ensure_ascii=False, indent=2)
    except Exception:
        pass

    print("\n" + "=" * 65)
    print("🎉 [유튜브 쇼츠 업로드 성공!]")
    print(f"🔗 쇼츠 링크: {video_url}")
    print(f"⚡ 소요 시간: {elapsed:.1f}초")
    print(f"🆔 비디오 ID: {video_id}")
    print("=" * 65 + "\n")
    return video_url

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload video to YouTube Shorts")
    parser.add_argument("--video", default=r"D:\DailyQuant\Daily_Quant_Shorts_Sample.mp4", help="Video file path")
    parser.add_argument("--meta", default=".tmp/sns_metadata_today.json", help="Metadata JSON path")
    parser.add_argument("--privacy", default="unlisted", choices=["public", "unlisted", "private"], help="Privacy status")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without uploading")
    args = parser.parse_args()

    upload_youtube_shorts(args.video, args.meta, args.privacy, dry_run=args.dry_run)

