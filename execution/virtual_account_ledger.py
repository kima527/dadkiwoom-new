"""
virtual_account_ledger.py - AI 500만원 주식 굴리기 챌린지 가상 원장(Ledger) 관리 모듈
================================================================================
- 초기 자본금: 5,000,000원 고정
- 매일 1회 단일 종목 집중 매매 (또는 분할) 거래 내역 기록
- 수수료/세금 (0.20%) 정밀 반영
- 누적 자산, 수익률, 승률, 일차(Day count) 영구 보존
"""

import os
import json
from datetime import datetime

LEDGER_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "virtual_account_ledger.json")
INITIAL_SEED = 5_000_000
FEE_AND_TAX_RATE = 0.0020  # 매매 수수료 + 증권거래세 합산 0.20%

def get_default_ledger():
    return {
        "challenge_name": "AI 500만원 주식 굴리기 30일 챌린지",
        "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "initial_seed": INITIAL_SEED,
        "current_asset": INITIAL_SEED,
        "cumulative_pnl": 0,
        "cumulative_return_pct": 0.0,
        "current_day": 0,
        "win_count": 0,
        "loss_count": 0,
        "win_rate_pct": 0.0,
        "trades": []
    }

def load_ledger() -> dict:
    if os.path.exists(LEDGER_PATH):
        try:
            with open(LEDGER_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️ 원장 파일 로드 오류: {e}, 기본값 생성")
    ledger = get_default_ledger()
    save_ledger(ledger)
    return ledger

def save_ledger(ledger: dict):
    os.makedirs(os.path.dirname(LEDGER_PATH), exist_ok=True)
    with open(LEDGER_PATH, "w", encoding="utf-8") as f:
        json.dump(ledger, f, ensure_ascii=False, indent=2)

def record_trade(
    date_str: str,
    stock_code: str,
    stock_name: str,
    entry_time: str,
    entry_price: int,
    exit_time: str,
    exit_price: int,
    reason_buy: str = "조건검색 거래대금 폭발 및 1분봉 정배열 눌림목 돌파",
    reason_sell: str = "목표 수익률 도달 익절"
) -> dict:
    ledger = load_ledger()
    current_asset = ledger["current_asset"]

    # 500만원(또는 현재 잔고) 전액 매수 수량 산출
    qty = int(current_asset // entry_price)
    if qty <= 0:
        qty = 1

    buy_amount = qty * entry_price
    sell_amount = qty * exit_price

    gross_pnl = sell_amount - buy_amount
    fee_and_tax = int(sell_amount * FEE_AND_TAX_RATE)
    net_pnl = gross_pnl - fee_and_tax
    trade_return_pct = (net_pnl / buy_amount) * 100.0 if buy_amount > 0 else 0.0

    new_asset = current_asset + net_pnl
    cum_pnl = new_asset - INITIAL_SEED
    cum_return_pct = (cum_pnl / INITIAL_SEED) * 100.0

    new_day = ledger["current_day"] + 1
    is_win = net_pnl > 0
    win_cnt = ledger["win_count"] + (1 if is_win else 0)
    loss_cnt = ledger["loss_count"] + (0 if is_win else 1)
    total_trades = win_cnt + loss_cnt
    win_rate = (win_cnt / total_trades) * 100.0 if total_trades > 0 else 0.0

    trade_record = {
        "day": new_day,
        "date": date_str,
        "stock_code": stock_code,
        "stock_name": stock_name,
        "qty": qty,
        "entry_time": entry_time,
        "entry_price": entry_price,
        "exit_time": exit_time,
        "exit_price": exit_price,
        "buy_amount": buy_amount,
        "sell_amount": sell_amount,
        "net_pnl": net_pnl,
        "return_pct": round(trade_return_pct, 2),
        "asset_after_trade": new_asset,
        "cum_return_pct": round(cum_return_pct, 2),
        "reason_buy": reason_buy,
        "reason_sell": reason_sell
    }

    ledger["current_day"] = new_day
    ledger["current_asset"] = new_asset
    ledger["cumulative_pnl"] = cum_pnl
    ledger["cumulative_return_pct"] = round(cum_return_pct, 2)
    ledger["win_count"] = win_cnt
    ledger["loss_count"] = loss_cnt
    ledger["win_rate_pct"] = round(win_rate, 1)
    ledger["trades"].append(trade_record)

    save_ledger(ledger)
    return trade_record

def reset_ledger(seed: int = INITIAL_SEED):
    ledger = get_default_ledger()
    ledger["initial_seed"] = seed
    ledger["current_asset"] = seed
    save_ledger(ledger)
    print(f"✨ 원장 초기화 완료 (자본금: {seed:,}원)")
    return ledger

if __name__ == "__main__":
    ledger = load_ledger()
    print("현재 가상 계좌 상태:")
    print(f"- 일차: Day {ledger['current_day']}")
    print(f"- 현재 자산: {ledger['current_asset']:,}원 (누적: {ledger['cumulative_return_pct']:+.2f}%)")
    print(f"- 총 거래 횟수: {len(ledger['trades'])}건 (승률: {ledger['win_rate_pct']}%)")
