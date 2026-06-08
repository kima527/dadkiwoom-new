import sys

files = [
    r"c:\Users\zoela\OneDrive\바탕 화면\PythonWorksplace\real trading\main.py",
    r"c:\Users\zoela\OneDrive\바탕 화면\PythonWorksplace\Paper trading\main.py"
]

def search_in_file(filepath):
    print(f"\n--- Searching in {filepath} ---")
    encodings = ['utf-8', 'cp949', 'euc-kr', 'utf-16']
    for enc in encodings:
        try:
            with open(filepath, 'r', encoding=enc) as f:
                lines = f.readlines()
            print(f"Successfully read with {enc}")
            for i, line in enumerate(lines):
                if '재매수' in line or '1분' in line or 'def ' in line:
                    if 'def ' in line or '재매수' in line:
                        print(f"L{i+1}: {line.strip()}")
            return
        except UnicodeDecodeError:
            pass
        except Exception as e:
            print(f"Error {enc}: {e}")

for f in files:
    search_in_file(f)
