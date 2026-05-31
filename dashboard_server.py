import os
import logging
from flask import Flask, jsonify, render_template, request
import config
from kiwoom_client import KiwoomClient
from indicator import calculate_indicators_pure
from main import load_watchlist

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__, template_folder="templates", static_folder="static")

# Initialize Kiwoom client
# Note: In production/real runtime, ensure .env is correctly loaded.
kiwoom_client = KiwoomClient()

def run_backtest_simulation(candles, mode="tema", fee_tax_pct=0.20):
    """
    Runs a simulation on a list of candles with calculated indicators.
    
    Simulation logic:
      - Buy: Next candle's OPEN after buy signal is confirmed (i.e. signal == True on current candle).
      - Sell: Next candle's OPEN after sell signal is confirmed (i.e. signal_sell == True on current candle).
      
    Signals used:
      - mode='tema': buy = 'signal_buy_tema', sell = 'signal_sell'
      - mode='line': buy = 'signal_buy', sell = 'signal_sell'
    """
    trades = []
    is_holding = False
    buy_price = 0.0
    buy_time = None
    buy_index = -1
    
    buy_signal_key = "signal_buy_tema" if mode == "tema" else "signal_buy"
    sell_signal_key = "signal_sell"
    
    n = len(candles)
    for i in range(n - 1): # Scan up to n-2 to execute buy/sell on i+1
        current = candles[i]
        nxt = candles[i + 1]
        
        # Not holding -> Check Buy
        if not is_holding:
            if current.get(buy_signal_key):
                is_holding = True
                buy_price = nxt["open"]
                buy_time = nxt["time"]
                buy_index = i + 1
        
        # Holding -> Check Sell
        else:
            if current.get(sell_signal_key):
                sell_price = nxt["open"]
                sell_time = nxt["time"]
                
                # Calculate return
                gross_return = ((sell_price - buy_price) / buy_price) * 100.0
                net_return = gross_return - fee_tax_pct
                
                holding_bars = (i + 1) - buy_index
                
                trades.append({
                    "buy_time": buy_time,
                    "buy_price": buy_price,
                    "sell_time": sell_time,
                    "sell_price": sell_price,
                    "return_pct": round(net_return, 2),
                    "holding_bars": holding_bars,
                    "is_completed": True
                })
                is_holding = False
                
    # If still holding at the end of the data, calculate paper profit based on the last candle's close
    if is_holding:
        last_candle = candles[-1]
        sell_price = last_candle["close"]
        sell_time = last_candle["time"] + " (미청산 평가)"
        
        gross_return = ((sell_price - buy_price) / buy_price) * 100.0
        net_return = gross_return - fee_tax_pct
        holding_bars = (n - 1) - buy_index
        
        trades.append({
            "buy_time": buy_time,
            "buy_price": buy_price,
            "sell_time": sell_time,
            "sell_price": sell_price,
            "return_pct": round(net_return, 2),
            "holding_bars": holding_bars,
            "is_completed": False
        })
        
    return trades

@app.route('/')
def index():
    return render_template("index.html")

@app.route('/api/backtest')
def api_backtest():
    # 'tema' (TEMA Gate Line) or 'line' (L Line)
    mode = request.args.get("mode", "tema")
    # Simulation duration in days
    days = int(request.args.get("days", "14"))
    
    WATCHLIST_PATH = config.WATCHLIST_FILE
    watchlist = load_watchlist(WATCHLIST_PATH)
    
    if not watchlist:
        return jsonify({
            "success": False,
            "error": "감시 종목 파일(my_pick.xlsx)이 없거나 비어 있습니다."
        }), 400
        
    all_trades = []
    stock_performance = []
    
    total_gross_return = 0.0
    total_trades_count = 0
    winning_trades_count = 0
    
    # Daily performance tracking
    # Key: 'YYYY-MM-DD', Value: Sum of returns on trades closed on this day
    daily_returns = {}
    
    for stock in watchlist:
        code = stock["code"]
        name = stock["name"]
        
        # Get candles (retrieve extra days to warm up indicators correctly)
        candles = kiwoom_client.get_15min_candles(code, last_n_days=days)
        if not candles or len(candles) < 60:
            logger.warning(f"Skipping {name} ({code}) due to lack of candle data.")
            continue
            
        # Calculate indicators in-place
        calculate_indicators_pure(
            candles,
            use_compressed_peak=True,
            tema_period1=config.TEMA_PERIOD_SHORT,
            tema_period2=config.TEMA_PERIOD_LONG
        )
        
        # Run simulation
        trades = run_backtest_simulation(candles, mode=mode)
        
        # Aggregate performance for this stock
        stock_total_return = 0.0
        stock_wins = 0
        stock_completed = 0
        
        for t in trades:
            t["code"] = code
            t["name"] = name
            all_trades.append(t)
            
            stock_total_return += t["return_pct"]
            if t["return_pct"] > 0:
                stock_wins += 1
            if t["is_completed"]:
                stock_completed += 1
            
            # Map daily returns based on trade sell date (YYYY-MM-DD)
            # Buy time and sell time formats are 'YYYY-MM-DD HH:MM:SS'
            sell_date = t["sell_time"].split(" ")[0]
            daily_returns[sell_date] = daily_returns.get(sell_date, 0.0) + t["return_pct"]
            
        stock_performance.append({
            "code": code,
            "name": name,
            "total_return": round(stock_total_return, 2),
            "trades_count": len(trades),
            "win_rate": round((stock_wins / len(trades) * 100.0), 1) if trades else 0.0
        })
        
        total_gross_return += stock_total_return
        total_trades_count += len(trades)
        winning_trades_count += stock_wins

    # Sort all trades by buy time descending (newest first)
    all_trades.sort(key=lambda x: x["buy_time"], reverse=True)
    
    # Compile cumulative daily returns curve
    sorted_dates = sorted(list(daily_returns.keys()))
    cumulative_curve = []
    running_total = 0.0
    for d in sorted_dates:
        running_total += daily_returns[d]
        cumulative_curve.append({
            "date": d,
            "daily_return": round(daily_returns[d], 2),
            "cumulative_return": round(running_total, 2)
        })

    win_rate = round((winning_trades_count / total_trades_count * 100.0), 1) if total_trades_count > 0 else 0.0
    avg_return = round(total_gross_return / total_trades_count, 2) if total_trades_count > 0 else 0.0
    
    return jsonify({
        "success": True,
        "mode": mode,
        "days": days,
        "summary": {
            "total_return": round(total_gross_return, 2),
            "trades_count": total_trades_count,
            "win_rate": win_rate,
            "avg_return": avg_return
        },
        "stock_performance": stock_performance,
        "daily_cumulative": cumulative_curve,
        "trades": all_trades
    })

if __name__ == "__main__":
    logger.info("Starting Backtesting Dashboard Server...")
    # Open browser on startup
    import webbrowser
    webbrowser.open("http://127.0.0.1:5000")
    app.run(host="127.0.0.1", port=5000, debug=True)
