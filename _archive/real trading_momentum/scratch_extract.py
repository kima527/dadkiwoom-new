import sys
log_path = r'C:\Users\zoela\.gemini\antigravity-ide\brain\8de741c4-1cc2-4e7c-8fae-8fe305d7c37b\.system_generated\tasks\task-879.log'
lines = open(log_path, encoding='utf-8').readlines()
block = []
for l in reversed(lines):
    if '주도주/보유주도' in l:
        block.append(l.strip())
    if '시장 주도주 랭킹 분석 시작' in l:
        break
block.reverse()

# Parse into a nice markdown table
headers = ["순위", "종목명(코드)", "주도주 점수", "등락률", "체결강도", "세력개입(1억매수)"]
md_lines = []
md_lines.append(f"| {' | '.join(headers)} |")
md_lines.append(f"|{'|'.join(['---']*len(headers))}|")

for b in block:
    # Example line: 2026-06-15 12:44:07,992 [INFO]   #1 018880_AL(018880_AL) [🔥주도주/보유주도] | 점수: 503.06점 | 정배열=False, 이격확장=False(기울기:+0.00%) | 등락률: +22.77% (급등:+0.00%) | 이격도: N/A | 수급돌파: False | 일봉보너스: False | 주봉보너스: False | 체결강도: 137.7% | 1억매수: 0건
    try:
        rank_part = b.split('   #')[1].split(' ')[0]
        name_code = b.split(f"#{rank_part} ")[1].split(' [')[0]
        score = b.split('점수: ')[1].split(' |')[0]
        change = b.split('등락률: ')[1].split(' (')[0]
        strength = b.split('체결강도: ')[1].split(' |')[0]
        big_buy = b.split('1억매수: ')[1]
        
        md_lines.append(f"| {rank_part} | {name_code} | {score} | {change} | {strength} | {big_buy} |")
    except Exception as e:
        pass

with open(r'C:\Users\zoela\.gemini\antigravity-ide\brain\8de741c4-1cc2-4e7c-8fae-8fe305d7c37b\market_leaders_report.md', 'w', encoding='utf-8') as f:
    f.write("# 🏆 실시간 시장 주도주 랭킹 리포트 (TOP 40)\n\n")
    f.write(f"> **데이터 기준 시각:** 2026-06-15 12:44\n> **기준:** 다이내믹 풀 `my_pick.xlsx` 내 거래대금 및 수급 점수 기준 상위 40종목\n\n")
    for m in md_lines:
        f.write(m + '\n')
