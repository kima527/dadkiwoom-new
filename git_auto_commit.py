import sys
import io

# Windows 콘솔에서 한국어(UTF-8)가 깨지지 않도록 안전하게 설정
if sys.platform.startswith("win"):
    try:
        if sys.stdout and not sys.stdout.closed:
            sys.stdout.reconfigure(encoding="utf-8")
        if sys.stderr and not sys.stderr.closed:
            sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

import os
import time
import subprocess
from datetime import datetime

# 감시할 디렉토리 (현재 파일이 위치한 디렉토리)
WATCH_DIR = os.path.dirname(os.path.abspath(__file__))
INTERVAL = 5  # 5초 간격으로 확인

# 제외할 디렉토리 및 파일
IGNORE_DIRS = {'.git', '__pycache__', '.gemini', '.idea', '.vscode'}
IGNORE_FILES = {'.env', 'my_pick.xlsx', 'git_auto_commit.py'}  # .env와 자동 생성 파일 제외

def get_files_mtime():
    files_state = {}
    for root, dirs, files in os.walk(WATCH_DIR):
        # 제외할 디렉토리 스킵
        dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
        
        for file in files:
            if file in IGNORE_FILES:
                continue
            # 파이썬 코드 및 설정 관련 파일만 감시
            if not file.endswith(('.py', '.txt', '.gitignore', '.md', '.json', '.xlsx')):
                continue
            # my_pick.xlsx는 위에서 IGNORE_FILES로 걸렀으므로 그 외 xlsx가 있다면 포함
            
            filepath = os.path.join(root, file)
            try:
                mtime = os.path.getmtime(filepath)
                files_state[filepath] = mtime
            except OSError:
                pass
    return files_state

def run_git_commands():
    try:
        print(f"[{datetime.now()}] 변경 사항이 감지되어 자동 커밋 및 푸시를 진행합니다...")
        
        # 1. git add
        subprocess.run(['git', 'add', '.'], check=True, cwd=WATCH_DIR)
        
        # 2. git status로 실제 변경 사항이 존재하는지 검증
        status_res = subprocess.run(['git', 'status', '--porcelain'], capture_output=True, text=True, encoding='utf-8', check=True, cwd=WATCH_DIR)
        if not status_res.stdout.strip():
            print("커밋할 변경 사항이 없습니다.")
            return
            
        # 3. git commit
        commit_msg = f"Auto-commit: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        subprocess.run(['git', 'commit', '-m', commit_msg], check=True, cwd=WATCH_DIR)
        print(f"성공적으로 로컬 커밋 완료: {commit_msg}")
        
        # 4. git push
        push_res = subprocess.run(['git', 'push', 'origin', 'main'], capture_output=True, text=True, encoding='utf-8', cwd=WATCH_DIR)
        if push_res.returncode == 0:
            print("원격 저장소(GitHub)로 푸시 완료!")
        else:
            print(f"푸시 실패: {push_res.stderr}")
    except Exception as e:
        print(f"Git 자동 커밋 과정 중 오류 발생: {e}")

def main():
    print("=" * 60)
    print(" Git 자동 커밋 데몬이 시작되었습니다.")
    print(f" 감시 디렉토리: {WATCH_DIR}")
    print(" .env 및 민감한 정보는 자동으로 제외됩니다.")
    print("=" * 60)
    
    last_state = get_files_mtime()
    
    while True:
        try:
            time.sleep(INTERVAL)
            current_state = get_files_mtime()
            
            changed = False
            
            # 파일 수정 혹은 추가 감지
            for filepath, mtime in current_state.items():
                if filepath not in last_state or last_state[filepath] != mtime:
                    changed = True
                    break
                    
            # 파일 삭제 감지
            if not changed:
                for filepath in last_state:
                    if filepath not in current_state:
                        changed = True
                        break
            
            if changed:
                # 3초간 추가 변경 대기 (저장 안정화 시간)
                time.sleep(3)
                current_state = get_files_mtime()  # 최신 상태 업데이트
                run_git_commands()
                last_state = current_state
                
        except KeyboardInterrupt:
            print("\nGit 자동 커밋 데몬을 종료합니다.")
            break
        except Exception as e:
            print(f"데몬 실행 오류: {e}")
            time.sleep(INTERVAL)

if __name__ == '__main__':
    main()
