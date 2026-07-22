import io

with io.open('main.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

new_lines = []
i = 0
while i < len(lines):
    line = lines[i]
    if 'PREV_FLU_RATES = {}' in line:
        new_lines.append(line)
        new_lines.append('PREV_RANK = {}\n')
        i += 1
        continue
        
    if 'Phase 2: Sort by momentum score' in line:
        # Insert overtaking logic here
        new_lines.append('        # --- Overtaking (순위 역전) 포착 로직 ---\n')
        new_lines.append('        temp_sorted = sorted(stock_results, key=lambda x: x["flu_pct"], reverse=True)\n')
        new_lines.append('        for rank_idx, sr in enumerate(temp_sorted):\n')
        new_lines.append('            curr_rank = rank_idx + 1\n')
        new_lines.append('            code = sr["code"]\n')
        new_lines.append('            sr["is_overtaking"] = False\n')
        new_lines.append('            if code in PREV_RANK:\n')
        new_lines.append('                if curr_rank < PREV_RANK[code]:\n')
        new_lines.append('                    sr["is_overtaking"] = True\n')
        new_lines.append('            PREV_RANK[code] = curr_rank\n')
        new_lines.append('        # ----------------------------------------\n\n')
        
    new_lines.append(line)
    i += 1

# Now we need to find where evaluate_trend_buy is called and inject the momentum execution
# Searching for 'is_trend_buy, trend_reason = evaluate_trend_buy'
final_lines = []
for line in new_lines:
    if 'is_trend_buy, trend_reason = evaluate_trend_buy' in line:
        final_lines.append(line)
        final_lines.append('                        \n')
        final_lines.append('                        # 순위 역전 & 체결속도 폭발 진입 로직\n')
        final_lines.append('                        if not is_trend_buy and sr.get("is_overtaking", False):\n')
        final_lines.append('                            velocity = dm.get_tick_velocity()\n')
        final_lines.append('                            if velocity < 2.0:\n') # 2.0초 이내 20틱
        final_lines.append('                                is_trend_buy = True\n')
        final_lines.append('                                trend_reason = f"순위역전 모멘텀 돌파 (체결속도: {velocity:.2f}초)"\n')
        continue
        
    final_lines.append(line)

with io.open('main.py', 'w', encoding='utf-8') as f:
    f.writelines(final_lines)
print('Patch applied!')
