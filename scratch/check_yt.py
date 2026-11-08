import urllib.request
import re

url = "https://www.youtube.com/watch?v=WDA1GSE1QHU"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
try:
    with urllib.request.urlopen(req) as resp:
        html = resp.read().decode("utf-8", errors="ignore")
        titles = re.findall(r"<title>(.*?)</title>", html)
        print("Page Title:", titles)
        channels = re.findall(r'"ownerChannelName":"([^"]+)"', html)
        print("Owner Channel:", channels)
        channel_ids = re.findall(r'"channelId":"([^"]+)"', html)
        print("Channel IDs:", channel_ids[:3])
except Exception as e:
    print("Error:", e)

