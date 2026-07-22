import io

with io.open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Add PREV_FLU_PCT at the top
old_globals = "PREV_RANK = {}"
new_globals = "PREV_RANK = {}\nPREV_FLU_PCT = {}"
if old_globals in content:
    content = content.replace(old_globals, new_globals)

# 2. Replace overtaking logic
old_overtake = '''        # --- Overtaking (순위 역전) 포착 로직 ---
        temp_sorted = sorted(stock_results, key=lambda x: x["flu_pct"], reverse=True)
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
            PREV_RANK[code] = curr_rank
        # ----------------------------------------'''

new_overtake = '''        # --- Overtaking (순위 역전) 포착 로직 고도화 ---
        # 1. 등락률 기준 내림차순 정렬 (39개밖에 안 되므로 Timsort 알고리즘으로 0.00001초 소요)
        temp_sorted = sorted(stock_results, key=lambda x: x["flu_pct"], reverse=True)

        for rank_idx, sr in enumerate(temp_sorted):
            curr_rank = rank_idx + 1
            code = sr["code"]
            sr["is_overtaking"] = False
            sr["curr_rank"] = curr_rank
            sr["flu_delta"] = 0.0
            
            # 1.[보완] 장전(오전 8시5분 이전)에는 백업만 수행하고 건너뛰고 8시 6분이후에 실행
            if t_hour < 8 or (t_hour == 8 and t_min < 6):
                PREV_FLU_PCT[code] = sr["flu_pct"]
                PREV_RANK[code] = curr_rank
                continue

            # 2. 직전 데이터가 존재하는 장중에만 평가
            if code in PREV_RANK:
                prev_flu = PREV_FLU_PCT.get(code, sr["flu_pct"])
                flu_delta = sr["flu_pct"] - prev_flu
                sr["flu_delta"] = flu_delta
                
                # [핵심 보완 수식] 
                # 조건 A: 순위가 실제로 상승했음 (주도주 진입)
                # 조건 B: 순위는 그대로여도(예: 계속 1등), 직전 초 대비 순수 등락률이 1% 이상 폭등함 (오후 시간대 고착화 해결)
                is_rank_up = curr_rank < PREV_RANK[code]
                is_absolute_shooting = (flu_delta >= 1.0)
                
                if (is_rank_up or curr_rank <= 3) and is_absolute_shooting:
                    # 상위 3등 이내에서 1% 이상 치솟거나, 순위가 역전된 경우만 진짜 주도주 돌파로 인정
                    sr["is_overtaking"] = True 
                    
            # 3. 데이터 백업 (globals 대피, 직관적인 고속 참조)
            PREV_FLU_PCT[code] = sr["flu_pct"]
            PREV_RANK[code] = curr_rank
        # ----------------------------------------'''

# Fallback: if old_overtake exact match fails, use regex or replace between Phase 1 and Phase 2.
import re
pattern = re.compile(r'# --- Overtaking.*?# ----------------------------------------', re.DOTALL)
if pattern.search(content):
    content = pattern.sub(new_overtake, content)
else:
    print("Could not find Overtaking block.")

# 3. Replace execution logging logic
old_exec = '''                        if not is_trend_buy and sr.get("is_overtaking", False):
                            velocity = DATA_MANAGERS[code].get_tick_velocity()
                            if velocity < 2.0:
                                is_trend_buy = True
                                trend_reason = f"순위역전 모멘텀 돌파 (체결속도: {velocity:.2f}초)"'''

new_exec = '''                        if not is_trend_buy and sr.get("is_overtaking", False):
                            velocity = DATA_MANAGERS[code].get_tick_velocity()
                            if velocity < 2.0:
                                is_trend_buy = True
                                trend_reason = f"⚡ 순위역전 모멘텀 돌파 (위치: {sr.get('curr_rank', 0)}등, 변동: +{sr.get('flu_delta', 0.0):.2f}%, 체결속도: {velocity:.2f}초)"'''

# Handle broken encoding comments in python replace
pattern_exec = re.compile(r'if not is_trend_buy and sr\.get\("is_overtaking", False\):.*?trend_reason = f".*?"', re.DOTALL)
if pattern_exec.search(content):
    content = pattern_exec.sub(new_exec, content)
else:
    print("Could not find Exec block.")

with io.open('main.py', 'w', encoding='utf-8') as f:
    f.write(content)
print('Done!')
