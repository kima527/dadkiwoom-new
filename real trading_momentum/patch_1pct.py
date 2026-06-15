import io

with io.open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

old_logic = '''        temp_sorted = sorted(stock_results, key=lambda x: x["flu_pct"], reverse=True)
        for rank_idx, sr in enumerate(temp_sorted):
            curr_rank = rank_idx + 1
            code = sr["code"]
            sr["is_overtaking"] = False
            if code in PREV_RANK:
                if curr_rank < PREV_RANK[code]:
                    sr["is_overtaking"] = True
            PREV_RANK[code] = curr_rank'''

new_logic = '''        temp_sorted = sorted(stock_results, key=lambda x: x["flu_pct"], reverse=True)
        for rank_idx, sr in enumerate(temp_sorted):
            curr_rank = rank_idx + 1
            code = sr["code"]
            sr["is_overtaking"] = False
            if code in PREV_RANK:
                # 1% 이상의 상승(역전)이 발생했는지 확인
                prev_flu = globals().get("PREV_RANK_FLU_PCT", {}).get(code, sr["flu_pct"])
                flu_delta = sr["flu_pct"] - prev_flu
                
                if curr_rank < PREV_RANK[code] and flu_delta >= 1.0:
                    sr["is_overtaking"] = True
                    
            if "PREV_RANK_FLU_PCT" not in globals():
                globals()["PREV_RANK_FLU_PCT"] = {}
            globals()["PREV_RANK_FLU_PCT"][code] = sr["flu_pct"]
            PREV_RANK[code] = curr_rank'''

if old_logic in content:
    content = content.replace(old_logic, new_logic)
    with io.open('main.py', 'w', encoding='utf-8') as f:
        f.write(content)
    print('Patch applied!')
else:
    print('Target not found.')
