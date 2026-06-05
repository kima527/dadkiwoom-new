import requests
from bs4 import BeautifulSoup
import re

def test_crawl(code):
    url = f"https://finance.naver.com/sise/entryJongmok.naver?code={code}&page=1"
    headers = {"User-Agent": "Mozilla/5.0"}
    res = requests.get(url, headers=headers)
    soup = BeautifulSoup(res.text, 'html.parser')
    
    items = soup.find_all('td', {'class': 'ctg'})
    print(f"--- Code: {code} ---")
    print(f"Found {len(items)} items")
    for item in items[:5]:
        link = item.a.get('href')
        stk_code = re.search(r'code=(\d+)', link).group(1)
        name = item.text.strip()
        print(f"Name: {name}, Code: {stk_code}")

if __name__ == "__main__":
    test_crawl("KPI200")
    test_crawl("KDQ150")
