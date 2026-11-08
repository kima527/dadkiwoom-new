import urllib.request
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
url = "https://www.youtube.com/watch?v=K2HsVn2Wnxs"
req = urllib.request.Request(
    url, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
)
try:
  with urllib.request.urlopen(req) as resp:
    html = resp.read().decode("utf-8", errors="ignore")
    reasons = re.findall(r'"unplayableReason":"([^"]+)"', html)
    if reasons:
      print("Unplayable reason:", reasons)
    else:
      print("No unplayableReason found.")

    playability = re.findall(
        r'"playabilityStatus":\{"status":"([^"]+)"(?:,"reason":"([^"]+)")?',
        html,
    )
    print("Playability Status:", playability)

    # Check if video is marked private
    if "private" in html.lower():
      priv_matches = re.findall(r'"status":"([^"]+)"', html)
      print("Statuses found:", set(priv_matches))
except Exception as e:
  print("HTTP/Network Error:", e)

