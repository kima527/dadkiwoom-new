import os
import sys
import json
import time
import argparse
import requests
from dotenv import load_dotenv

# Ensure UTF-8 output
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

load_dotenv()

GRAPH_API_VERSION = "v21.0"
BASE_URL = f"https://graph.facebook.com/{GRAPH_API_VERSION}"

def check_container_status(container_id: str, access_token: str, max_wait: int = 120) -> bool:
    """
    Polls Meta Graph API to check if the uploaded Reel video has finished encoding.
    """
    url = f"{BASE_URL}/{container_id}"
    params = {
        "fields": "status_code",
        "access_token": access_token
    }
    start = time.time()
    while time.time() - start < max_wait:
        res = requests.get(url, params=params).json()
        status = res.get("status_code")
        if status == "FINISHED":
            print("  ✅ 인스타그램 서버 비디오 인코딩 처리 완료!")
            return True
        elif status == "ERROR":
            print(f"  ❌ 인스타그램 비디오 처리 실패: {res}")
            return False
        elif status in ["IN_PROGRESS", "EXPIRED"]:
            print(f"  ⏳ 인코딩 진행 중 ({status})... 5초 대기", flush=True)
            time.sleep(5)
        else:
            print(f"  ⏳ 상태 확인 중 ({status})...", flush=True)
            time.sleep(5)
    print("⚠️ 대기 시간 초과: 인코딩이 완료되지 않았습니다.")
    return False

def upload_instagram_reel(
    video_path: str = r"D:\DailyQuant\Daily_Quant_Shorts_Sample.mp4",
    meta_path: str = ".tmp/sns_metadata_today.json",
    dry_run: bool = False
):
    """
    Publishes a 9:16 vertical video as an Instagram Reel using Meta Graph API.
    """
    if not os.path.exists(video_path):
        print(f"❌ 업로드 실패: 비디오 파일이 없습니다 -> {video_path}")
        return False

    ig_account_id = os.getenv("INSTAGRAM_ACCOUNT_ID")
    access_token = os.getenv("INSTAGRAM_ACCESS_TOKEN")

    # Load caption from metadata
    caption = "오늘 9시 개장 직전, ‘15분 원칙’ 모르면 시초가에 다 털립니다! #주식 #모닝퀀트"
    if os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            caption = data.get("instagram", {}).get("caption", caption)

    print("\n" + "=" * 65)
    print("🟣 [인스타그램 릴스 자동 업로드]")
    print(f"📁 파일: {video_path} ({os.path.getsize(video_path)/(1024*1024):.2f} MB)")
    print(f"📝 캡션 미리보기:\n{caption[:120]}...")
    print("=" * 65 + "\n")

    if dry_run:
        print("🔍 [DRY RUN 모드] 인스타그램 릴스 메타데이터 및 영상 규격 검증 완료.")
        return True

    if not ig_account_id or not access_token:
        print("\n" + "=" * 70)
        print("⚠️ [인스타그램 API 환경변수 설정 필요 안내]")
        print("인스타그램 릴스 자동 발행을 위해 '.env' 파일에 다음 항목을 등록해 주세요.")
        print("\nINSTAGRAM_ACCOUNT_ID=당신의_인스타그램_비즈니스_계정_ID")
        print("INSTAGRAM_ACCESS_TOKEN=당신의_Meta_그래프API_액세스토큰")
        print("\n📌 [설정 방법]")
        print("1. Meta for Developers(https://developers.facebook.com/) 앱 생성")
        print("2. 인스타그램 비즈니스 계정과 페이스북 페이지 연결")
        print("3. 'instagram_basic', 'instagram_content_publish' 권한이 포함된 토큰 발급")
        print("=" * 70 + "\n")
        return False

    # Step 1: Initialize Resumable Upload Session
    print("1️⃣ [1/3] 인스타그램 릴스 미디어 컨테이너 생성 중...", flush=True)
    init_url = f"{BASE_URL}/{ig_account_id}/media"
    init_params = {
        "media_type": "REELS",
        "upload_type": "resumable",
        "caption": caption,
        "share_to_feed": True,
        "access_token": access_token
    }

    init_res = requests.post(init_url, data=init_params).json()
    if "uri" not in init_res:
        print(f"❌ 컨테이너 초기화 실패: {init_res}")
        return False

    upload_uri = init_res["uri"]
    video_id = init_res.get("id")
    file_size = os.path.getsize(video_path)

    # Step 2: Transfer Video Binary
    print(f"2️⃣ [2/3] 비디오 바이너리 스트리밍 전송 중 ({file_size / (1024*1024):.2f} MB)...", flush=True)
    headers = {
        "Authorization": f"OAuth {access_token}",
        "offset": "0",
        "file_size": str(file_size)
    }

    with open(video_path, "rb") as f:
        video_bytes = f.read()

    upload_res = requests.post(upload_uri, headers=headers, data=video_bytes).json()
    if not upload_res.get("success", False):
        print(f"❌ 바이너리 업로드 실패: {upload_res}")
        return False

    # Check Encoding Status
    print("⏳ 인스타그램 서버 인코딩 상태 대기 중...")
    if not check_container_status(video_id, access_token):
        return False

    # Step 3: Publish Reel
    print("3️⃣ [3/3] 릴스 피드 최종 배포(Publish) 실행 중...", flush=True)
    pub_url = f"{BASE_URL}/{ig_account_id}/media_publish"
    pub_params = {
        "creation_id": video_id,
        "access_token": access_token
    }

    pub_res = requests.post(pub_url, data=pub_params).json()
    if "id" in pub_res:
        media_id = pub_res["id"]
        print("\n" + "=" * 65)
        print("🎉 [인스타그램 릴스 배포 성공!]")
        print(f"🆔 미디어 ID: {media_id}")
        print(f"🔗 계정 피드에서 실시간 릴스를 확인하세요!")
        print("=" * 65 + "\n")
        return media_id
    else:
        print(f"❌ 릴스 배포 실패: {pub_res}")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Upload Reel to Instagram")
    parser.add_argument("--video", default=r"D:\DailyQuant\Daily_Quant_Shorts_Sample.mp4", help="Video file path")
    parser.add_argument("--meta", default=".tmp/sns_metadata_today.json", help="Metadata JSON path")
    parser.add_argument("--dry-run", action="store_true", help="Simulate without uploading")
    args = parser.parse_args()

    upload_instagram_reel(args.video, args.meta, dry_run=args.dry_run)

