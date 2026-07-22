import re

file_path = "c:/Users/zoela/OneDrive/바탕 화면/PythonWorksplace/real trading/main.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# 1. Remove get_daily_target_stock_code function
content = re.sub(r'def get_daily_target_stock_code\(\) -> str:.*?return ""\n', '', content, flags=re.DOTALL)

# 2. Remove target_code lines in update_watchlist_excel
content = re.sub(r'\s*# target_code를 조회하여 신규 집중 종목이 편입되는지 판단하는 용도로만 사용합니다\.\n\s*target_code = get_daily_target_stock_code\(\)\n', '', content)

# 3. Remove the daily scanner block and target_code usage
# We find the start: "            # 🔒 \[CRITICAL LOGIC LOCK - DO NOT MODIFY\]"
# And the end: "        # \(계좌 잔고 및 예수금은 루프 시작부에서 일괄 조회하여 사용합니다\)"
pattern = r'(\s*# 🔒 \[CRITICAL LOGIC LOCK - DO NOT MODIFY\].*?logger\.error\(f"Failed to write selected stock file: \{e\}"\)\s*)\n\s*try:'
content = re.sub(pattern, r'\n            try:', content, flags=re.DOTALL)

# 4. Remove the target_code assignment at the end of the block
content = re.sub(r'\s*# Filter holdings to target stock if configured\n\s*target_code = get_daily_target_stock_code\(\)\n', '', content)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)
print("Done")
