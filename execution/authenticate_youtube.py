import os
import sys
import socket
import threading
import webbrowser
from http.server import HTTPServer, BaseHTTPRequestHandler
from google_auth_oauthlib.flow import InstalledAppFlow

# Ensure UTF-8 output
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
CLIENT_SECRETS_FILE = "client_secrets.json"
TOKEN_FILE = "token_youtube.json"
PORT = 8080

class DualStackServer(HTTPServer):
    address_family = socket.AF_INET6
    allow_reuse_address = True
    def server_bind(self):
        try:
            self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        except Exception:
            pass
        super().server_bind()

auth_code_event = threading.Event()
received_response_url = None

class OAuthCallbackHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress logging
        return

    def do_GET(self):
        global received_response_url
        if "code=" in self.path:
            # Handle both IPv4 and IPv6 callbacks
            received_response_url = f"https://localhost:{PORT}" + self.path
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            html = """
            <!DOCTYPE html>
            <html>
            <head><meta charset="utf-8"><title>인증 성공</title></head>
            <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; text-align: center; padding: 60px 20px; background: #0f172a; color: #f8fafc;">
                <div style="max-width: 500px; margin: 0 auto; background: #1e293b; border-radius: 16px; padding: 40px; box-shadow: 0 10px 25px rgba(0,0,0,0.5); border: 1px solid #334155;">
                    <h1 style="color: #4ade80; font-size: 28px; margin-bottom: 16px;">🎉 유튜브 인증 완료!</h1>
                    <p style="font-size: 16px; color: #94a3b8; line-height: 1.6;">
                        성공적으로 유튜브 업로드 권한이 부여되었습니다.<br>
                        이제 이 브라우저 창을 닫으셔도 좋습니다.
                    </p>
                </div>
            </body>
            </html>
            """
            self.wfile.write(html.encode("utf-8"))
            auth_code_event.set()
        else:
            self.send_response(404)
            self.end_headers()

def run_auth_server(server):
    while not auth_code_event.is_set():
        server.handle_request()

def main():
    print("=" * 65)
    print("🔑 [유튜브 쇼츠 자동 업로드 1회 인증 마법사]")
    print("=" * 65)

    if not os.path.exists(CLIENT_SECRETS_FILE):
        print(f"❌ {CLIENT_SECRETS_FILE} 파일이 없습니다.")
        return

    # Start dual-stack server on port 8080
    try:
        server = DualStackServer(('::', PORT), OAuthCallbackHandler)
    except Exception:
        class IPv4Server(HTTPServer):
            allow_reuse_address = True
        server = IPv4Server(('0.0.0.0', PORT), OAuthCallbackHandler)

    server.timeout = 0.5
    server_thread = threading.Thread(target=run_auth_server, args=(server,), daemon=True)
    server_thread.start()

    # Create OAuth flow
    flow = InstalledAppFlow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=SCOPES,
        redirect_uri=f"http://localhost:{PORT}/"
    )
    auth_url, _ = flow.authorization_url(prompt="consent", access_type="offline")

    print("\n👉 브라우저(Edge/Chrome)가 자동으로 열립니다.")
    print("만약 열리지 않으면 아래 링크를 직접 클릭해 주세요:\n")
    print(auth_url)
    print("\n" + "=" * 65)
    print("💡 [혹시 브라우저에서 '연결할 수 없습니다' 오류가 뜨는 경우]")
    print("브라우저 주소창의 전체 주소(http://localhost:8080/...)를 복사해서")
    print("이곳 창에 붙여넣고 [Enter]를 누르셔도 100% 즉시 인증됩니다!")
    print("=" * 65 + "\n", flush=True)

    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    # Thread to wait for manual URL paste as fallback
    def wait_for_manual_paste():
        global received_response_url
        try:
            line = sys.stdin.readline()
            if line and "code=" in line:
                url = line.strip()
                if url.startswith("http://"):
                    url = "https://" + url[7:]
                received_response_url = url
                auth_code_event.set()
        except Exception:
            pass

    paste_thread = threading.Thread(target=wait_for_manual_paste, daemon=True)
    paste_thread.start()

    # Wait up to 5 minutes
    auth_code_event.wait(timeout=300)

    try:
        server.server_close()
    except Exception:
        pass

    if not received_response_url:
        print("⏳ 인증 대기 시간이 초과되었습니다.")
        return

    try:
        flow.fetch_token(authorization_response=received_response_url)
        creds = flow.credentials

        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

        print("\n" + "=" * 65)
        print("🎉 [축하합니다! 유튜브 인증이 완벽하게 완료되었습니다!]")
        print(f"💾 영구 토큰 저장 완료: {TOKEN_FILE}")
        print("📺 이제부터 매일 07:00 모닝 쇼츠와 08:50 장전 쇼츠가")
        print("   100% 무인 자동으로 유튜브에 업로드됩니다!")
        print("=" * 65 + "\n", flush=True)
    except Exception as e:
        print(f"❌ 토큰 발급 중 오류 발생: {e}", flush=True)

if __name__ == "__main__":
    main()
