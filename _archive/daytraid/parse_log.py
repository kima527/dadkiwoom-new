import re
from collections import defaultdict

log_file = r"C:\Users\zoela\.gemini\antigravity-ide\brain\43ccba7e-3310-482d-925b-076a555eecc2\.system_generated\tasks\task-538.log"

pattern = re.compile(r"\[INFO\] \[(.*?)\] 매수: (.*?) \((.*?)원\) -> 매도: (.*?) \((.*?)원\) \| 수익률: ([\+\-0-9\.]+)% \((.*?)\)")

trades_by_date = defaultdict(list)

try:
    with open(log_file, "r", encoding="utf-8") as f:
        for line in f:
            match = pattern.search(line)
            if match:
                stock, buy_time, buy_price, sell_time, sell_price, profit, reason = match.groups()
                date = buy_time[:10] # "YYYY-MM-DD"
                trades_by_date[date].append({
                    "stock": stock,
                    "buy_time": buy_time[11:16], # HH:MM
                    "sell_time": sell_time[11:16],
                    "profit": float(profit),
                    "reason": reason
                })

    with open("daily_backtest_analysis.md", "w", encoding="utf-8") as out:
        out.write("# 📅 트레일링 스탑 적용 최종 분석 (+1244%)\n\n")
        out.write("진입 이후 형성된 최고점 대비 -1.5% 하락 시 기계적으로 매도(트레일링 스탑)하는 로직을 추가한 역대급 결과입니다.\n\n")
        
        for date in sorted(trades_by_date.keys()):
            trades = trades_by_date[date]
            daily_wins = len([t for t in trades if t['profit'] > 0])
            daily_total = len(trades)
            daily_win_rate = (daily_wins / daily_total) * 100 if daily_total > 0 else 0
            daily_profit_sum = sum(t['profit'] for t in trades)
            
            color = "red" if daily_profit_sum > 0 else "blue"
            out.write(f"## 🗓️ {date}\n")
            out.write(f"* **총 매매:** {daily_total}건 | **승률:** {daily_wins}/{daily_total} ({daily_win_rate:.1f}%) | **합산 수익률:** **<span style='color:{color}'>{daily_profit_sum:+.2f}%</span>**\n\n")
            
            # 종목별 그룹화
            from collections import defaultdict
            stock_trades = defaultdict(list)
            for t in trades:
                stock_trades[t['stock']].append(t)
                
            for stock, s_trades in stock_trades.items():
                stock_profit_sum = sum(t['profit'] for t in s_trades)
                s_color = "red" if stock_profit_sum > 0 else "blue"
                out.write(f"### 🔸 {stock} (합산: <span style='color:{s_color}'>{stock_profit_sum:+.2f}%</span>)\n")
                out.write("| 매수 시간 | 매도 시간 | 수익률 | 청산 사유 |\n")
                out.write("|---|---|---|---|\n")
                for t in s_trades:
                    t_color = "**" if t['profit'] > 0 else ""
                    out.write(f"| {t['buy_time']} | {t['sell_time']} | {t_color}{t['profit']:+.2f}%{t_color} | {t['reason']} |\n")
                out.write("\n")
            
    print("daily_backtest_analysis.md 생성 완료")
except Exception as e:
    print(f"에러 발생: {e}")
