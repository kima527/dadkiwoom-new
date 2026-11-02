# Directive: Automated Social Media Distribution Pipeline (YouTube Shorts & Instagram Reels)

## 1. Goal
Automatically distribute the daily rendered 9:16 Full HD financial intelligence video (`D:\DailyQuant\Daily_Quant_Shorts_Sample.mp4`) to **YouTube Shorts** and **Instagram Reels** with algorithm-optimized titles, descriptions, and hashtags without manual intervention.

---

## 2. Architecture & File Organization

### Layer 1: Directive
- `directives/sns_auto_distribution.md`: This SOP document.

### Layer 2: Orchestration (Agent)
- Orchestrates metadata synthesis, token validation, API handshakes, and multi-channel publication.

### Layer 3: Execution Tools (`execution/`)
1. `execution/generate_sns_metadata.py`: Analyzes daily closing data, semiconductor moves, and 15-minute response rules to generate SEO-rich titles, captions, and hashtags.
2. `execution/upload_youtube_shorts.py`: Uploads video via YouTube Data API v3 with resumable chunked upload and OAuth 2.0 token persistence.
3. `execution/upload_instagram_reels.py`: Publishes video via Meta Graph API (Instagram Content Publishing API) with container initialization, encoding status polling, and final publication.
4. `execution/distribute_all_sns.py`: Master multi-channel distributor coordinating concurrent or sequential uploads with structured status reporting.

### Storage & Cache
- Output Video: `D:\DailyQuant\Daily_Quant_Shorts_Sample.mp4`
- Metadata Cache: `.tmp/sns_metadata_today.json`
- Auth Tokens:
  - YouTube: `client_secrets.json` (OAuth client), `token_youtube.json` (persisted refresh token)
  - Instagram: `INSTAGRAM_ACCOUNT_ID`, `INSTAGRAM_ACCESS_TOKEN` in `.env`

---

## 3. Credentials & Initial Setup Guide

### A. YouTube Shorts (Google Cloud)
1. Visit [Google Cloud Console](https://console.cloud.google.com/).
2. Enable **YouTube Data API v3**.
3. Create **OAuth 2.0 Client ID** (Application Type: Desktop App).
4. Download JSON and save as `client_secrets.json` in project root directory.
5. On the first run, a browser window will open once to authenticate your Google Account. A `token_youtube.json` file is generated and auto-refreshed forever.

### B. Instagram Reels (Meta for Developers)
1. Ensure your Instagram account is a **Professional (Business/Creator)** account and connected to a Facebook Page.
2. Visit [Meta for Developers](https://developers.facebook.com/) and create an App (Type: Business).
3. Generate a User Access Token with permissions:
   - `instagram_basic`
   - `instagram_content_publish`
4. Add the following to your root `.env` file:
   ```env
   INSTAGRAM_ACCOUNT_ID=your_instagram_business_account_id
   INSTAGRAM_ACCESS_TOKEN=your_meta_long_lived_access_token
   ```

---

## 4. Execution Commands

```bash
# 1. Test in Dry-Run mode (Simulate without live uploads):
.venv\Scripts\python.exe execution/distribute_all_sns.py --dry-run

# 2. Live Multi-SNS Distribution:
.venv\Scripts\python.exe execution/distribute_all_sns.py --privacy unlisted

# 3. Individual Platform Upload:
# YouTube Shorts only:
.venv\Scripts\python.exe execution/upload_youtube_shorts.py --privacy unlisted

# Instagram Reels only:
.venv\Scripts\python.exe execution/upload_instagram_reels.py
```

---

## 5. Platform Rate Limits & Compliance
- **YouTube API Quota**: 10,000 units/day default. Each video upload costs 1,600 units (~6 uploads/day free tier).
- **Instagram Reels Limit**: 25 API-published posts per 24 hours per account.
- **Video Format**: Strictly 9:16 (1080x1920), H.264, AAC audio, strictly $< 60$ seconds.

