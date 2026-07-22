import os
import csv
import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

def sync_and_report_today(client, bot_state, notifier):
    """
    일간 매매 내역을 동기화하고 정산 리포트를 발송/저장합니다.
    """
    KST = timezone(timedelta(hours=9))
    today_str = datetime.now(KST).strftime("%Y%m%d")
    
    logger.info("Starting Daily Account Synchronization and Settlement...")
    
    # 1. API 데이터 추출
    filled_orders = client.get_today_filled_orders()
    realized_profit = client.get_today_realized_profit()
    local_trades = bot_state.get("completed_trades", [])
    
    # 매도 체결만 필터링
    api_sells = [o for o in filled_orders if o.get("side") == "매도"]
    
    # 2. 로컬 로그와 API 대조를 통한 슬리피지 계산
    matched_results = []
    
    # 단일 종목 다중 매도 시 가장 최신 체결가를 매핑하도록 딕셔너리로 최적화
    api_sell_map = {}
    for api_ord in api_sells:
        # 늦은 시간순으로 덮어쓰기 위해, flled_ord_qry가 과거->최신 이면 마지막 것이 남음
        api_sell_map[api_ord.get("code")] = api_ord

    for local in local_trades:
        code = local.get("code")
        expected_price = local.get("sell_price", 0)
        
        matched_api = api_sell_map.get(code)
                
        actual_price = matched_api.get("filled_price", 0) if matched_api else 0
        slippage = actual_price - expected_price if actual_price > 0 else 0
        
        # 실제 체결이 발생한 경우 혹은 조회 실패한 경우
        matched_results.append({
            "code": code,
            "name": local.get("name"),
            "reason": local.get("reason", "알수없음"),
            "expected_price": expected_price,
            "actual_price": actual_price,
            "slippage": slippage
        })
        
    # 3. CSV 파일 백업
    settlement_dir = "settlements"
    os.makedirs(settlement_dir, exist_ok=True)
    csv_path = os.path.join(settlement_dir, f"daily_settlement_{today_str}.csv")
    
    try:
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["Code", "Name", "Sell Reason", "Expected Price", "Actual Filled Price", "Slippage"])
            for r in matched_results:
                writer.writerow([r["code"], r["name"], r["reason"], r["expected_price"], r["actual_price"], r["slippage"]])
        logger.info(f"Daily settlement CSV saved to {csv_path}")
    except Exception as e:
        logger.error(f"Failed to write settlement CSV: {e}")
        
    # 4. 리포트 포맷팅 및 전송
    profit = realized_profit.get("realized_profit", 0)
    tax = realized_profit.get("tax", 0)
    commission = realized_profit.get("commission", 0)
    buy_amt = realized_profit.get("buy_amt", 0)
    sell_amt = realized_profit.get("sell_amt", 0)
    net_profit = profit - tax - commission
    
    msg_lines = [
        "📊 **[일간 매매 결산 보고서]**",
        f"📅 일자: {datetime.now(KST).strftime('%Y-%m-%d')}",
        "────────────────────────",
        f"💰 총 매수 금액: {buy_amt:,.0f}원",
        f"💸 총 매도 금액: {sell_amt:,.0f}원",
        f"📈 총 실현 손익: {profit:,.0f}원",
        f"📉 제세금/수수료: {(tax + commission):,.0f}원",
        f"🔥 **순손익: {net_profit:,.0f}원**",
        "────────────────────────",
        "🔍 **[주요 종목 매도 슬리피지 분석]**"
    ]
    
    if not matched_results:
        msg_lines.append("- 당일 로컬 매도 체결 로그 없음")
    else:
        for r in matched_results:
            slip_str = f"{r['slippage']:+,.0f}원" if r['actual_price'] > 0 else "미체결/조회실패"
            msg_lines.append(f"- {r['name']}: 로컬 {r['expected_price']:,.0f}원 → 실제 {r['actual_price']:,.0f}원 (오차: {slip_str})")
            
    msg_lines.append("────────────────────────")
    msg_lines.append(f"📁 결산 파일 저장됨: {csv_path}")
    
    final_msg = "\n".join(msg_lines)
    
    if notifier:
        notifier.send_all(final_msg)
    else:
        print(final_msg)
        
    return True

if __name__ == "__main__":
    from kiwoom_client import KiwoomClient
    from notifier import notifier
    
    print("수동 일간 매매 결산 레이어 가동...")
    client = KiwoomClient()
    
    # 수동 실행 시 로컬 로그(BOT_STATE)를 완전히 복원하긴 어려우므로
    # 빈 로그를 넘겨 키움증권 서버 기준 실현손익이라도 조회하도록 설계
    bot_state_mock = {"completed_trades": []}
    
    if client.test_connection():
        sync_and_report_today(client, bot_state_mock, notifier)
