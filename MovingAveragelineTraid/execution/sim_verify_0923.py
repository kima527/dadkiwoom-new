"""
sim_verify_0923.py
9월 23일 정규장(09:00 ~ 15:30) 기준,
개편된 '돌파 찰나(Golden Moment) 스나이핑' 및
'1~3순위 우선순위 체계(380/370/360/350/340/330)' 봇 매매 시뮬레이션 검증
"""

import os
import glob
import pandas as pd
import numpy as np
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

from strategy_15m_squeeze_alignment import evaluate_15m_squeeze_alignment
from strategy_5d2v_surge_breakout import evaluate_5d2v_surge_breakout
from strategy_buy import evaluate_pivot_breakout, analyze_buy_signals
from strategy_15m_4formula_buy import evaluate_4formula_buy
from strategy_15m_turnaround import evaluate_15m_entry

CACHE_DIR = r"c:\Users\zoela\.gemini\antigravity-ide\scratch\sim_cache_0923"

NAMES = {
    "000500": "가온전선", "000880": "한화", "001820": "삼화콘덴서", "003160": "디아이",
    "003280": "흥아해운", "003350": "한국화장품제조", "004090": "한국석유", "004310": "현대약품",
    "008930": "한미반도체", "017900": "유한양행", "019170": "신풍제약", "024060": "흥구석유",
    "030530": "원익홀딩스", "032940": "원익", "041190": "우리기술투자", "042370": "비츠로테크",
    "042510": "코오롱글로벌", "043260": "성호전자", "044490": "태웅", "046970": "우리로",
    "052690": "한전기술", "053260": "스피어", "058610": "에스엠", "064550": "바이오니아",
    "072950": "빛과전자", "078350": "한올바이오파마", "079900": "유바이오로직스", "090460": "비에이치아이",
    "092790": "넥스턴바이오", "100840": "SNT에너지", "108490": "로보티즈", "115440": "우리넷",
    "124500": "한화에어로스페이스", "128940": "한미약품", "130660": "한전산업", "161580": "휴젤",
    "201490": "미투온", "229640": "LS에코에너지", "232140": "와이엠티", "234690": "녹십자웰빙",
    "249420": "일동제약", "327260": "엑세스바이오", "336260": "두산퓨얼셀", "356680": "티이엠씨",
    "356860": "TLB", "361610": "이지바이오", "382900": "엔켐", "413630": "펨트론",
    "437730": "삼현", "441270": "파라텍", "452280": "스튜디오미르", "476060": "그리드위즈",
    "484810": "씨어스테크놀로지"
}

def load_cached_data():
    files = glob.glob(os.path.join(CACHE_DIR, "*_15m.csv"))
    codes = set()
    for f in files:
        code = os.path.basename(f).split('_')[0]
        codes.add(code)
    
    datasets = {}
    for code in sorted(codes):
        p_15m = os.path.join(CACHE_DIR, f"{code}_15m.csv")
        p_30m = os.path.join(CACHE_DIR, f"{code}_30m.csv")
        p_d = os.path.join(CACHE_DIR, f"{code}_daily.csv")
        
        df_15m = pd.read_csv(p_15m) if os.path.exists(p_15m) else None
        df_30m = pd.read_csv(p_30m) if os.path.exists(p_30m) else None
        df_d = pd.read_csv(p_d) if os.path.exists(p_d) else None
        
        if df_15m is not None and not df_15m.empty and df_d is not None and not df_d.empty:
            # 시간 형식 통일
            t_col = 'time' if 'time' in df_15m.columns else df_15m.columns[0]
            df_15m['dt'] = pd.to_datetime(df_15m[t_col])
            
            # 정규 거래시간(09:00 ~ 15:30)만 포함하도록 필터 (당일)
            datasets[code] = {
                'name': NAMES.get(code, code),
                '15m': df_15m,
                '30m': df_30m,
                'daily': df_d
            }
    return datasets

def simulate_day():
    datasets = load_cached_data()
    logger.info(f"총 {len(datasets)}개 종목 데이터 로드 완료")
    
    # 9월 23일 정규 거래시간(09:00 ~ 15:30)의 고유 타임스탬프 리스트 추출
    sample_code = "229640" if "229640" in datasets else list(datasets.keys())[0]
    sample_df = datasets[sample_code]['15m']
    day_str = sample_df['dt'].iloc[-1].strftime('%Y-%m-%d')
    
    # 9월 23일 09:00 ~ 15:30 타임스탬프
    day_mask = (sample_df['dt'].dt.strftime('%Y-%m-%d') == day_str) & \
               (sample_df['dt'].dt.time >= pd.to_datetime("09:00:00").time()) & \
               (sample_df['dt'].dt.time <= pd.to_datetime("15:30:00").time())
    
    regular_times = sample_df[day_mask]['dt'].tolist()
    logger.info(f"시뮬레이션 대상 거래일: {day_str} | 정규장 15분봉 개수: {len(regular_times)}개")
    
    positions = {}
    traded_today = set()  # 당일 중복 매수 방지
    trade_logs = []
    
    for t_idx, sim_time in enumerate(regular_times):
        t_str = sim_time.strftime('%H:%M')
        
        # 1. 기존 보유 종목 청산 체크 (Break-Even Stop + 트레일링 익절)
        for code in list(positions.keys()):
            pos = positions[code]
            df_15m = datasets[code]['15m']
            curr_slice = df_15m[df_15m['dt'] <= sim_time]
            if curr_slice.empty:
                continue
            curr_bar = curr_slice.iloc[-1]
            curr_high = float(curr_bar['high'])
            curr_low = float(curr_bar['low'])
            curr_close = float(curr_bar['close'])
            
            if curr_high > pos['peak_price']:
                pos['peak_price'] = curr_high
                
            peak_gain_pct = ((pos['peak_price'] - pos['buy_price']) / pos['buy_price']) * 100.0
            curr_gain_pct = ((curr_close - pos['buy_price']) / pos['buy_price']) * 100.0
            
            sell_reason = None
            sell_price = curr_close
            
            # [Break-Even Stop]: 고점 +1.0% 이상 도달 후 +0.2% 회귀 시 본전 스탑
            if peak_gain_pct >= 1.0 and curr_gain_pct <= 0.2:
                sell_reason = f"🛡️ 본전보존스탑 (최고 {peak_gain_pct:+.2f}% ➔ 현재 {curr_gain_pct:+.2f}%)"
                sell_price = pos['buy_price'] * 1.002
                
            # [다이나믹 트레일링 익절]
            elif peak_gain_pct >= 4.0 and (pos['peak_price'] - curr_close) / pos['buy_price'] * 100.0 >= 1.0:
                sell_reason = f"💰 트레일링 익절 (+4% 이상 고점대비 -1.0% 후퇴)"
                sell_price = pos['peak_price'] * 0.990
            elif peak_gain_pct >= 2.5 and (pos['peak_price'] - curr_close) / pos['buy_price'] * 100.0 >= 0.8:
                sell_reason = f"💰 트레일링 익절 (+2.5% 이상 고점대비 -0.8% 후퇴)"
                sell_price = pos['peak_price'] * 0.992
            elif peak_gain_pct >= 1.5 and (pos['peak_price'] - curr_close) / pos['buy_price'] * 100.0 >= 0.5:
                sell_reason = f"💰 트레일링 익절 (+1.5% 이상 고점대비 -0.5% 후퇴)"
                sell_price = pos['peak_price'] * 0.995
                
            # [원칙 손절 -2.0%]
            elif curr_gain_pct <= -2.0:
                sell_reason = f"🛑 원칙손절 (-2.0% 도달)"
                sell_price = pos['buy_price'] * 0.980
                
            # [장마감 청산]
            elif t_idx == len(regular_times) - 1:
                sell_reason = f"🔔 장마감 동시호가 청산"
                sell_price = curr_close
                
            if sell_reason:
                ret_pct = ((sell_price - pos['buy_price']) / pos['buy_price']) * 100.0
                trade_logs.append({
                    'code': code,
                    'name': pos['name'],
                    'strategy': pos['strategy'],
                    'buy_time': pos['buy_time'],
                    'buy_price': pos['buy_price'],
                    'sell_time': t_str,
                    'sell_price': sell_price,
                    'peak_price': pos['peak_price'],
                    'peak_gain_pct': peak_gain_pct,
                    'return_pct': ret_pct,
                    'sell_reason': sell_reason
                })
                logger.info(f"📤 [{t_str}] 매도 완료! {pos['name']}({code}) | {sell_reason} | 수익률: {ret_pct:+.2f}%")
                del positions[code]
                
        # 2. 신규 매수 후보 탐색 (바 시점 기준)
        if len(positions) >= 5:
            continue
            
        candidates = []
        for code, data in datasets.items():
            if code in positions or code in traded_today:
                continue
                
            df_15m = data['15m']
            curr_slice = df_15m[df_15m['dt'] <= sim_time]
            if len(curr_slice) < 60:
                continue
                
            curr_bar = curr_slice.iloc[-1]
            curr_c = float(curr_bar['close'])
            daily_df_curr = data['daily'].iloc[:-1]  # 전일 확정 일봉
            
            # 전략 평가
            eval_squeeze = evaluate_15m_squeeze_alignment(code, data['name'], curr_slice, daily_df_curr)
            eval_5d2v = evaluate_5d2v_surge_breakout(code, data['name'], daily_df_curr, df_15m=curr_slice, current_price=curr_c)
            eval_pivot = evaluate_pivot_breakout(curr_slice, daily_df_curr)
            eval_f4 = evaluate_4formula_buy(code, data['name'], curr_slice, current_price=curr_c)
            eval_15m = evaluate_15m_entry(code, data['name'], curr_slice, daily_df_curr, current_price=curr_c)
            
            # 1순위 (380점): 15분봉 이평 압축 정배열 돌파
            if eval_squeeze.get('is_buy_signal'):
                candidates.append({
                    'code': code,
                    'name': data['name'],
                    'strategy': '👑 1순위: 이평압축 정배열 돌파',
                    'target_price': eval_squeeze.get('target_price', curr_c),
                    'curr_close': curr_c,
                    'score': 380.0,
                    'reason': eval_squeeze['reason']
                })
            # 1.5순위 (370점): 5일선 거래량 폭증 돌파
            elif eval_5d2v.get('should_buy'):
                candidates.append({
                    'code': code,
                    'name': data['name'],
                    'strategy': '👑 1.5순위: 5일선 거래량폭증 돌파',
                    'target_price': eval_5d2v.get('target_price', curr_c),
                    'curr_close': curr_c,
                    'score': 370.0,
                    'reason': eval_5d2v['reason']
                })
            # 1.6순위 (360점): 피봇 돌파 찰나 스나이핑
            elif eval_pivot.get('should_buy'):
                candidates.append({
                    'code': code,
                    'name': data['name'],
                    'strategy': '👑 1.6순위: 피봇 돌파 찰나',
                    'target_price': eval_pivot['target_price'],
                    'curr_close': curr_c,
                    'score': 360.0,
                    'reason': eval_pivot['reason']
                })
            # 2순위 (350점): 4대 수식 올인원 M선 돌파
            elif eval_f4.get('should_buy'):
                candidates.append({
                    'code': code,
                    'name': data['name'],
                    'strategy': '👑 2순위: 4대수식 M선 돌파',
                    'target_price': eval_f4.get('target_price', curr_c),
                    'curr_close': curr_c,
                    'score': 350.0,
                    'reason': eval_f4['reason']
                })
            # 3순위 (340점): 15분봉 수급 변곡
            elif eval_15m.get('should_buy'):
                candidates.append({
                    'code': code,
                    'name': data['name'],
                    'strategy': '👑 3순위: 15분봉 수급변곡',
                    'target_price': eval_15m.get('target_price', eval_15m.get('limit_price', curr_c)),
                    'curr_close': curr_c,
                    'score': 340.0,
                    'reason': eval_15m['reason']
                })

        candidates.sort(key=lambda x: x['score'], reverse=True)
        
        for cand in candidates:
            if len(positions) >= 5:
                break
            code = cand['code']
            if code in positions or code in traded_today:
                continue
                
            tp = cand['target_price']
            cc = cand['curr_close']
            if tp > 0 and cc > tp * 1.008:
                continue
                
            buy_price = tp if tp > 0 else cc
            positions[code] = {
                'code': code,
                'name': cand['name'],
                'strategy': cand['strategy'],
                'buy_price': buy_price,
                'peak_price': buy_price,
                'buy_time': t_str
            }
            traded_today.add(code)
            logger.info(f"🎯 [{t_str}] 매수 체결! {cand['name']}({code}) - {cand['strategy']} | 매수가: {buy_price:,.0f}원")

    return trade_logs

if __name__ == "__main__":
    trades = simulate_day()
    df_trades = pd.DataFrame(trades)
    print("\n" + "=" * 90)
    print("📊 [9월 23일 정규장 돌파 찰나 스나이핑 & 우선순위 재정렬 매매 성적표]")
    print("=" * 90)
    if df_trades.empty:
        print("체결된 거래가 없습니다.")
    else:
        for idx, row in df_trades.iterrows():
            print(f"[{row['buy_time']} ➔ {row['sell_time']}] {row['name']}({row['code']}) | 전략: {row['strategy']}")
            print(f"   매수가: {row['buy_price']:,.0f}원 | 최고가: {row['peak_price']:,.0f}원({row['peak_gain_pct']:+.2f}%) | 매도가: {row['sell_price']:,.0f}원 ➔ 수익률: {row['return_pct']:+.2f}%")
            print(f"   청산사유: {row['sell_reason']}")
            print("-" * 90)
        win_count = len(df_trades[df_trades['return_pct'] > 0])
        even_count = len(df_trades[df_trades['return_pct'] == 0])
        loss_count = len(df_trades[df_trades['return_pct'] < 0])
        total_ret = df_trades['return_pct'].sum()
        avg_ret = df_trades['return_pct'].mean()
        print(f"총 거래 수: {len(df_trades)}건 | 승: {win_count}건, 본전: {even_count}건, 패: {loss_count}건")
        print(f"승률(본전 포함): {(win_count + even_count) / len(df_trades) * 100:.1f}% | 평균 수익률: {avg_ret:+.2f}% | 총 누적 수익률: {total_ret:+.2f}%")
        print("=" * 90)
