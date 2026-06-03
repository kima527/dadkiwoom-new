import os
import re
import sys
import subprocess

# Patterns to scan for potential secrets
SECRET_PATTERNS = [
    # Telegram Bot Token: e.g. 1234567890:ABCdefGhIJKlmNoPQRsTUVwxyZ
    re.compile(r'\b\d{8,10}:[A-Za-z0-9_-]{35}\b'),
    # Kiwoom App Key/Secret or Account Num assignments with real values
    re.compile(r'(KIWOOM_REAL_APP_KEY|KIWOOM_REAL_APP_SECRET|KIWOOM_REAL_ACCOUNT_NUM|TELEGRAM_BOT_TOKEN|TELEGRAM_CHAT_ID)\s*=\s*["\']([^"\']+)["\']')
]

# Files/Directories to ignore during scan
IGNORE_DIRS = {'.git', '__pycache__', '.gemini', '.idea', '.vscode', 'scratch'}
IGNORE_FILES = {'.gitignore', 'README.md', 'security_check.py'}

# Safe/Placeholder values to ignore
SAFE_VALUES = {
    "", "실전용_APP_KEY_입력", "실전용_APP_SECRET_입력", "실전용_계좌번호_입력(예: 5012345611)",
    "TELEGRAM_BOT_TOKEN_HERE", "TELEGRAM_CHAT_ID_HERE", "실전용_계좌번호_입력",
    "텔레그램_토큰_입력", "텔레그램_채팅방ID_입력", "텔레그램_봇_토큰_입력", "텔레그램_챗_아이디_입력"
}

def run_security_check():
    print("=" * 60)
    print("          RUNNING SECURITY PRE-COMMIT CHECK")
    print("=" * 60)
    
    passed = True
    
    # 1. Check if any .env or sensitive file is tracked in git index
    try:
        res = subprocess.run(['git', 'ls-files'], capture_output=True, text=True, check=True, encoding='utf-8')
        tracked_files = res.stdout.splitlines()
        for f in tracked_files:
            if '.env' in f or 'my_pick.xlsx' in f:
                print(f"[FAIL] Sensitive file is currently tracked in Git: {f}")
                passed = False
    except Exception as e:
        print(f"[WARN] Failed to run 'git ls-files': {e}")

    # 2. Scan codebase for hardcoded secrets
    for root, dirs, files in os.walk('.'):
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        
        for file in files:
            if file in IGNORE_FILES:
                continue
            if not file.endswith(('.py', '.json', '.js', '.html', '.css', '.example')):
                continue
                
            filepath = os.path.join(root, file)
            try:
                content = ""
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        content = f.read()
                except UnicodeDecodeError:
                    with open(filepath, 'r', encoding='cp949', errors='ignore') as f:
                        content = f.read()
                
                lines = content.splitlines()
                for line_num, line in enumerate(lines, 1):
                    for pattern in SECRET_PATTERNS:
                        matches = pattern.findall(line)
                        for match in matches:
                            if isinstance(match, tuple):
                                var_name, var_val = match
                                if var_val.strip() in SAFE_VALUES:
                                    continue
                                print(f"[FAIL] Hardcoded credential found in {filepath}:{line_num}")
                                print(f"    -> Variable '{var_name}' assigned sensitive value: '***{var_val[-4:] if len(var_val) > 4 else ''}'")
                                passed = False
                            else:
                                # Direct token match (e.g. Telegram token regex)
                                val = match.strip()
                                # Check if it matches dummy placeholder format
                                if "abc" in val or "123" in val:
                                    continue
                                print(f"[FAIL] Raw token pattern found in {filepath}:{line_num}")
                                print(f"    -> Token: '***{val[-4:] if len(val) > 4 else ''}'")
                                passed = False
            except Exception as e:
                print(f"[WARN] Could not read {filepath}: {e}")

    print("-" * 60)
    if passed:
        print("[SUCCESS] Security check passed. No hardcoded credentials detected.")
        print("=" * 60)
        sys.exit(0)
    else:
        print("[FAIL] Security check failed! Please fix the errors before committing.")
        print("=" * 60)
        sys.exit(1)

if __name__ == '__main__':
    run_security_check()
