import re

with open('main.py', 'r', encoding='utf-8') as f:
    content = f.read()

start_marker = '            if "tracking_mode" not in sent_alerts[code]:'
end_marker = '        # Update the watchlist Excel file with latest positions and prices'

if start_marker in content and end_marker in content:
    start_idx = content.find(start_marker)
    end_idx = content.find(end_marker)
    
    new_logic = """            tracking_mode = "15m"
            sent_alerts[code]["tracking_mode"] = tracking_mode
            
            latest_15m = stock_data.get("latest", {})
            candles_15m = stock_data.get("candles_15m", [])
            
            # ── 1. 매수 조건 확인 (15분봉 전용) ──
            if is_buy_window and not is_held:
                if sent_alerts[code].get("buy") != candle_time:
                    buy_condition_met = False
                    cond_type = ""
                    
                    if len(candles_15m) >= 2:
                        curr_15m = candles_15m[-1]
                        prev_15m = candles_15m[-2]
                        
                        curr_t3 = curr_15m.get("tema3")
                        curr_t60 = curr_15m.get("tema60")
                        curr_gate = curr_15m.get("tema_gate_line")
                        curr_vol_avg3 = curr_15m.get("vol_avg_3", 0)
                        curr_vol = curr_15m.get("volume", 0)
                        close_price_15m = curr_15m.get("close")
                        
                        # 1. 15m TEMA3 > TEMA60 (Golden Cross state)
                        is_golden_cross_state = (curr_t3 is not None and curr_t60 is not None and curr_t3 > curr_t60)
                        
                        # 2. Gate Line Support
                        is_gate_supported = (curr_gate is not None and close_price_15m is not None and close_price_15m >= curr_gate)
                        
                        # 3. Volume Spike (1.5x)
                        is_volume_spike = (curr_vol_avg3 > 0 and curr_vol >= curr_vol_avg3 * 1.5)
                        
                        # Breakout Condition (existing logic: L-line & whale_line breakout)
                        is_breakout = curr_15m.get("signal_perfect_breakout", False)
                        
                        # Rebuy Condition: touches BB20 lower band
                        bb20_lower = curr_15m.get("bb20_lower")
                        low_price = curr_15m.get("low")
                        is_bb_rebuy = (bb20_lower is not None and low_price is not None and low_price <= bb20_lower and close_price_15m > bb20_lower)
                        
                        # Evaluate final entry
                        if is_golden_cross_state and is_gate_supported and is_volume_spike:
                            buy_condition_met = True
                            cond_type = "15m 골든크로스+관문선지지+거래량급증"
                        elif is_breakout:
                            buy_condition_met = True
                            cond_type = "15m 완벽 돌파(Breakout)"
                        elif is_bb_rebuy and is_golden_cross_state: # Only rebuy if still in macro uptrend
                            buy_condition_met = True
                            cond_type = "15m 볼린저하단 반등 재매수"
                            
                    if buy_condition_met:
                        last_sell_time = sent_alerts[code].get("last_sell_time", 0)
                        if time.time() - last_sell_time < 60:
                            logger.info(f"⏳ [쿨타임] {name}({code}) - 매도 후 60초가 경과하지 않아 신규 진입을 보류합니다.")
                        else:
                            from indicator import adjust_price_by_ticks
                            buy_price = get_ext_adjusted_price(client, code, close_price, "buy", 1)
                            logger.info(f"🚀 [최종 관문 통과 매수 진입] {name} ({code}) {cond_type} | 현재가: {close_price:,.0f}원 → 매수가: {buy_price:,.0f}원 (+1호가)")
                            
                            sent_alerts[code]["buy"] = candle_time
                            sent_alerts[code]["buy_reason"] = cond_type
                            
                            budget = cash * 0.95
                            qty = int(budget // buy_price)
                            if getattr(config, 'TEST_MODE_1_SHARE', False):
                                qty = 1
                            
                            if qty > 0:
                                order_res = client.place_buy_order(code, qty, price=buy_price, order_type="0")
                                if order_res and order_res.get("return_code") == 0:
                                    sent_alerts[code]["sold_qty"] = 0
                                    msg = (
                                        f"🚀 <b>[매수 체결 - {cond_type}]</b>\\n"
                                        f"종목: {name} ({code})\\n"
                                        f"체결단가: {buy_price:,.0f}원 (+1호가 지정가)\\n"
                                        f"수량: {qty}주\\n"
                                        f"시간: {candle_time}\\n"
                                        f"주문번호: {order_res.get('ord_no')}"
                                    )
                                    notifier.send_all(msg)
                                    _add_alert("buy", f"{cond_type} 매수 {qty}주 @ {buy_price:,.0f}원", code, name)
                                else:
                                    err_msg = order_res.get("return_msg") if order_res else "응답 없음"
                                    logger.error(f"❌ [매수 실패] {name} ({code}): {err_msg}")
                                    _add_alert("error", f"매수 실패: {err_msg}", code, name)
            
            # ── 2. 매도 로직 (15분봉 전용) ──
            if is_held and held_info:
                if len(candles_15m) >= 1:
                    curr_15m = candles_15m[-1]
                    curr_t3 = curr_15m.get("tema3")
                    curr_t60 = curr_15m.get("tema60")
                    
                    # Exit Condition: TEMA3 < TEMA60
                    if curr_t3 is not None and curr_t60 is not None and curr_t3 < curr_t60:
                        if sent_alerts[code].get("sell") != candle_time:
                            sent_alerts[code]["sell"] = candle_time
                            qty_to_sell = held_info["quantity"]
                            
                            logger.info(f"🚨 [15m 데드크로스 감지] 전량 매도 처리: {name} ({code})")
                            
                            from indicator import adjust_price_by_ticks
                            sell_price = get_ext_adjusted_price(client, code, close_price, "sell", -2)
                            order_res = client.place_sell_order(code, qty_to_sell, price=sell_price, order_type="0")
                            
                            if order_res and order_res.get("return_code") == 0:
                                sent_alerts[code]["sold_qty"] = qty_to_sell
                                pur_price = held_info["buy_price"]
                                ret_rate = ((sell_price - pur_price) / pur_price) * 100.0
                                
                                trade_info = {
                                    "time": datetime.now(KST).strftime("%Y-%m-%d %H:%M:%S"),
                                    "code": code,
                                    "name": name,
                                    "buy_price": pur_price,
                                    "sell_price": sell_price,
                                    "return_pct": round(ret_rate, 2),
                                    "reason": "15m TEMA3 데드크로스"
                                }
                                BOT_STATE["completed_trades"].insert(0, trade_info)
                                if len(BOT_STATE["completed_trades"]) > 50:
                                    BOT_STATE["completed_trades"].pop()
                                    
                                msg = (
                                    f"📉 <b>[매도 체결 - 15m TEMA3 데드크로스]</b>\\n"
                                    f"종목: {name} ({code})\\n"
                                    f"매도단가: {sell_price:,.0f}원 (지정가 -2호가)\\n"
                                    f"매수단가: {pur_price:,.0f}원\\n"
                                    f"매도수량: {qty_to_sell}주\\n"
                                    f"<b>실현수익률: {ret_rate:+.2f}%</b>\\n"
                                    f"시간: {candle_time}"
                                )
                                notifier.send_all(msg)
                                _add_alert("sell", f"데드크로스 매도 {qty_to_sell}주 @ {sell_price:,.0f}원 | {ret_rate:+.2f}%", code, name)
                                sent_alerts[code]["last_sell_time"] = time.time()
                            else:
                                err_msg = order_res.get("return_msg") if order_res else "응답 없음"
                                logger.error(f"❌ [매도 실패] {name} ({code}): {err_msg}")
                                _add_alert("error", f"매도 실패: {err_msg}", code, name)
"""
    new_content = content[:start_idx] + new_logic + "\n" + content[end_idx:]
    with open('main.py', 'w', encoding='utf-8') as f:
        f.write(new_content)
    print('Replacement successful.')
else:
    print('Markers not found.')
