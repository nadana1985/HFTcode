import os
import argparse
import pandas as pd
import numpy as np
from datetime import timedelta

def parse_args():
    parser = argparse.ArgumentParser(description="Trend Continuation Backtesting Engine")
    parser.add_argument("--symbol", type=str, default="BTCUSDT", help="Symbol to backtest (default: BTCUSDT)")
    parser.add_argument("--resolution", type=str, default="30m", choices=["1m", "15m", "30m"], help="Strategy timeframe resolution (default: 30m)")
    parser.add_argument("--target_rr", type=float, default=2.0, help="Risk-to-Reward ratio for take-profit target (default: 2.0)")
    parser.add_argument("--min_risk_pct", type=float, default=0.001, help="Minimum risk as a fraction of entry price if SL is too tight (default: 0.1%)")
    return parser.parse_args()

def load_data(symbol: str):
    raw_dir = "data/raw shards"
    events_filepath = f"data/events/{symbol}_expansion_events.parquet"
    
    # Find price file
    price_files = [os.path.join(raw_dir, f) for f in os.listdir(raw_dir) if f.startswith(symbol) and f.endswith(".parquet")]
    if not price_files:
        raise FileNotFoundError(f"No price parquet files found for {symbol} in {raw_dir}")
    
    print(f"[INFO] Loading price data from: {price_files[0]}")
    df_price = pd.read_parquet(price_files[0])
    df_price["datetime"] = pd.to_datetime(df_price["datetime"])
    df_price = df_price.sort_values("datetime").reset_index(drop=True)
    
    print(f"[INFO] Loading events from: {events_filepath}")
    if not os.path.exists(events_filepath):
        raise FileNotFoundError(f"Events parquet file not found at: {events_filepath}")
    df_events = pd.read_parquet(events_filepath)
    df_events["datetime"] = pd.to_datetime(df_events["datetime"])
    df_events = df_events.sort_values("datetime").reset_index(drop=True)
    
    return df_price, df_events

def run_backtest(df_price: pd.DataFrame, df_events: pd.DataFrame, resolution: str, target_rr: float, min_risk_pct: float):
    # Determine R in minutes
    if resolution == "15m":
        R = 15
    elif resolution == "30m":
        R = 30
    else:
        R = 1
        
    print(f"[INFO] Running backtest at {resolution} resolution (R={R}m) with target Risk-to-Reward of {target_rr}:1...")
    
    # 1. Resample 1m prices to strategy resolution R
    # We label by open time to match TradingView / server logic.
    rule = f"{R}Min"
    df_resampled = df_price.resample(rule, on="datetime").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last"
    }).dropna().reset_index()
    
    df_resampled['elapsed_minutes'] = (df_resampled['datetime'].dt.hour * 60 + df_resampled['datetime'].dt.minute) + R
    
    # Create a fast lookup for 1m klines by datetime to simulate ticks causally
    df_price_indexed = df_price.set_index("datetime")
    
    # Group events for fast lookup
    events_by_time = {}
    for dt, group in df_events.groupby("datetime"):
        events_by_time[dt] = group
        
    # Pre-calculate T_small reference bars
    # For a given timeframe T, we want to know the High/Low of the previous bar for any minute of the day.
    # Group ID = (candle_number - 1) // T
    # Previous Group ID = Group ID - 1
    # To handle this causally and quickly:
    # Let's map date -> 1m candles for looking up previous timeframe bars.
    df_price["candle_number"] = (df_price["datetime"].dt.hour * 60 + df_price["datetime"].dt.minute) + 1
    df_price["date_str"] = df_price["datetime"].dt.strftime("%Y-%m-%d")
    
    # Build helper dict of daily 1m prices for fast SL calculation
    prices_by_date = {}
    for d_str, grp in df_price.groupby("date_str"):
        prices_by_date[d_str] = grp.set_index("candle_number")
        
    def get_prev_bar_high_low(date_str: str, candle_num: int, T_small: int):
        """
        Calculates the High and Low of the previous bar of timeframe T_small relative to the current candle_num.
        """
        # Current group
        curr_group = (candle_num - 1) // T_small
        prev_group = curr_group - 1
        
        target_date = date_str
        if prev_group < 0:
            # Look at previous day's last group
            curr_dt = pd.to_datetime(date_str)
            prev_dt = curr_dt - timedelta(days=1)
            target_date = prev_dt.strftime("%Y-%m-%d")
            # If T_small is e.g. 2m, there are 1440 // 2 = 720 groups daily. The last group is 719.
            # Generally, the last group index of a day is (1440 // T_small) - 1.
            prev_group = (1440 // T_small) - 1
            
        if target_date not in prices_by_date:
            return None, None
            
        day_df = prices_by_date[target_date]
        
        # Minutes belonging to the previous group
        start_c_num = prev_group * T_small + 1
        end_c_num = (prev_group + 1) * T_small
        
        # Slice day_df for these candle numbers
        # Using .loc since candle_number is the index
        subset = day_df.loc[start_c_num:end_c_num]
        if subset.empty:
            return None, None
            
        return float(subset["high"].max()), float(subset["low"].min())

    # State tracking variables
    prev_state = "Tie"
    prev_close = None
    prev_open = None
    
    trades = []
    
    for idx, row in df_resampled.iterrows():
        time_val = row["datetime"]
        elapsed = int(row["elapsed_minutes"])
        curr_close = float(row["close"])
        curr_open = float(row["open"])
        
        # End of the current bar (e.g. 00:59 for a 30m bar starting at 00:30)
        t_close_minute = time_val + pd.Timedelta(minutes=R-1)
        
        # Find active divisors of elapsed minutes
        divisors = [d for d in range(1, elapsed + 1) if elapsed % d == 0]
        
        green_count = 0
        red_count = 0
        triggering_tfs = []
        
        # Check event log for completed divisors
        if t_close_minute in events_by_time:
            curr_events = events_by_time[t_close_minute]
            for d in divisors:
                d_event = curr_events[curr_events["timeframe"] == d]
                if not d_event.empty:
                    etype = d_event.iloc[0]["event_type"]
                    triggering_tfs.append(d)
                    if etype == "Bullish_Expansion":
                        green_count += 1
                    elif etype == "Bearish_Expansion":
                        red_count += 1
                        
        # Determine current dominant state
        if green_count > red_count:
            curr_state = "Bullish"
        elif red_count > green_count:
            curr_state = "Bearish"
        else:
            curr_state = "Tie"
            
        # Detect state transitions
        signal = None
        if prev_state == "Tie":
            if curr_state != "Tie":
                prev_state = curr_state
        else:
            if prev_state == "Bearish" and curr_state == "Bullish":
                # Trend shift validation filter
                if prev_close is not None and curr_close > prev_close:
                    signal = "BUY"
            elif prev_state == "Bullish" and curr_state == "Bearish":
                # Trend shift validation filter
                if prev_open is not None and curr_close < prev_open:
                    signal = "SELL"
                    
        # Update state memory only if filter passed
        if signal:
            prev_state = curr_state
            
        prev_close = curr_close
        prev_open = curr_open
        
    # State tracking variables
    prev_state = "Tie"
    prev_close = None
    prev_open = None
    
    trades = []
    active_trade = None
    current_date = None
    
    for idx, row in df_resampled.iterrows():
        time_val = row["datetime"]
        row_date = time_val.date()
        
        # Check for Daily Session Reset (SSOT Alignment)
        if current_date is not None and row_date != current_date:
            if active_trade is not None:
                # Force-close trade at the last minute of the previous day (23:59 UTC)
                prev_row = df_resampled.iloc[idx - 1]
                prev_time = prev_row["datetime"]
                exit_time = prev_time + pd.Timedelta(minutes=R-1)
                exit_price = float(prev_row["close"])
                
                df_slice = df_price[(df_price["datetime"] > active_trade["entry_time"]) & (df_price["datetime"] <= exit_time)]
                if not df_slice.empty:
                    highs = df_slice["high"].astype(float)
                    lows = df_slice["low"].astype(float)
                    if active_trade["direction"] == "BUY":
                        mae = active_trade["entry_price"] - lows.min()
                        mfe = highs.max() - active_trade["entry_price"]
                    else:
                        mae = highs.max() - active_trade["entry_price"]
                        mfe = active_trade["entry_price"] - lows.min()
                else:
                    mae = 0.0
                    mfe = 0.0
                
                duration_mins = int((exit_time - active_trade["entry_time"]).total_seconds() / 60)
                pnl_pct = (exit_price - active_trade["entry_price"]) / active_trade["entry_price"] if active_trade["direction"] == "BUY" else (active_trade["entry_price"] - exit_price) / active_trade["entry_price"]
                
                trades.append({
                    "entry_time": active_trade["entry_time"],
                    "exit_time": exit_time,
                    "direction": active_trade["direction"],
                    "entry_price": active_trade["entry_price"],
                    "sl_price": np.nan,
                    "tp_price": np.nan,
                    "exit_price": exit_price,
                    "exit_reason": "SESSION_RESET",
                    "pnl_pct": pnl_pct,
                    "mae_pct": mae / active_trade["entry_price"],
                    "mfe_pct": mfe / active_trade["entry_price"],
                    "duration_minutes": duration_mins,
                    "smallest_tf": active_trade["smallest_tf"]
                })
                active_trade = None
            
            # Reset trend memory to "Tie" at start of new day
            prev_state = "Tie"
            prev_close = None
            prev_open = None
            
        current_date = row_date
        elapsed = int(row["elapsed_minutes"])
        curr_close = float(row["close"])
        curr_open = float(row["open"])
        
        # End of the current bar (e.g. 00:59 for a 30m bar starting at 00:30)
        t_close_minute = time_val + pd.Timedelta(minutes=R-1)
        
        # Find active divisors of elapsed minutes
        divisors = [d for d in range(1, elapsed + 1) if elapsed % d == 0]
        
        green_count = 0
        red_count = 0
        triggering_tfs = []
        
        # Check event log for completed divisors
        if t_close_minute in events_by_time:
            curr_events = events_by_time[t_close_minute]
            for d in divisors:
                d_event = curr_events[curr_events["timeframe"] == d]
                if not d_event.empty:
                    etype = d_event.iloc[0]["event_type"]
                    triggering_tfs.append(d)
                    if etype == "Bullish_Expansion":
                        green_count += 1
                    elif etype == "Bearish_Expansion":
                        red_count += 1
                        
        # Determine current dominant state
        if green_count > red_count:
            curr_state = "Bullish"
        elif red_count > green_count:
            curr_state = "Bearish"
        else:
            curr_state = "Tie"
            
        # Detect state transitions
        signal = None
        if prev_state == "Tie":
            if curr_state != "Tie":
                prev_state = curr_state
        else:
            if prev_state == "Bearish" and curr_state == "Bullish":
                # Trend shift validation filter
                if prev_close is not None and curr_close > prev_close:
                    signal = "BUY"
            elif prev_state == "Bullish" and curr_state == "Bearish":
                # Trend shift validation filter
                if prev_open is not None and curr_close < prev_open:
                    signal = "SELL"
                    
        # Update state memory only if filter passed
        if signal:
            prev_state = curr_state
            
        prev_close = curr_close
        prev_open = curr_open
        
        # Manage exits first if we have an active opposite signal
        if active_trade is not None:
            opposite_signal = (active_trade["direction"] == "BUY" and signal == "SELL") or \
                              (active_trade["direction"] == "SELL" and signal == "BUY")
            if opposite_signal:
                # Close active trade
                exit_time = t_close_minute
                exit_price = curr_close
                
                # Fetch 1m price ticks during trade to calculate MAE / MFE
                df_slice = df_price[(df_price["datetime"] > active_trade["entry_time"]) & (df_price["datetime"] <= exit_time)]
                if not df_slice.empty:
                    highs = df_slice["high"].astype(float)
                    lows = df_slice["low"].astype(float)
                    if active_trade["direction"] == "BUY":
                        mae = active_trade["entry_price"] - lows.min()
                        mfe = highs.max() - active_trade["entry_price"]
                    else:
                        mae = highs.max() - active_trade["entry_price"]
                        mfe = active_trade["entry_price"] - lows.min()
                else:
                    mae = 0.0
                    mfe = 0.0
                
                duration_mins = int((exit_time - active_trade["entry_time"]).total_seconds() / 60)
                pnl_pct = (exit_price - active_trade["entry_price"]) / active_trade["entry_price"] if active_trade["direction"] == "BUY" else (active_trade["entry_price"] - exit_price) / active_trade["entry_price"]
                
                trades.append({
                    "entry_time": active_trade["entry_time"],
                    "exit_time": exit_time,
                    "direction": active_trade["direction"],
                    "entry_price": active_trade["entry_price"],
                    "sl_price": np.nan,
                    "tp_price": np.nan,
                    "exit_price": exit_price,
                    "exit_reason": "TRANSITION",
                    "pnl_pct": pnl_pct,
                    "mae_pct": mae / active_trade["entry_price"],
                    "mfe_pct": mfe / active_trade["entry_price"],
                    "duration_minutes": duration_mins,
                    "smallest_tf": active_trade["smallest_tf"]
                })
                active_trade = None
                
        # Open new trade on signal
        if signal and active_trade is None:
            T_small = min(triggering_tfs) if triggering_tfs else np.nan
            active_trade = {
                "entry_time": t_close_minute,
                "entry_price": curr_close,
                "direction": signal,
                "smallest_tf": T_small
            }
            
    # Handle end of dataset exit
    if active_trade is not None and not df_price.empty:
        last_tick = df_price.iloc[-1]
        exit_time = last_tick["datetime"]
        exit_price = float(last_tick["close"])
        
        df_slice = df_price[(df_price["datetime"] > active_trade["entry_time"]) & (df_price["datetime"] <= exit_time)]
        if not df_slice.empty:
            highs = df_slice["high"].astype(float)
            lows = df_slice["low"].astype(float)
            if active_trade["direction"] == "BUY":
                mae = active_trade["entry_price"] - lows.min()
                mfe = highs.max() - active_trade["entry_price"]
            else:
                mae = highs.max() - active_trade["entry_price"]
                mfe = active_trade["entry_price"] - lows.min()
        else:
            mae = 0.0
            mfe = 0.0
            
        duration_mins = int((exit_time - active_trade["entry_time"]).total_seconds() / 60)
        pnl_pct = (exit_price - active_trade["entry_price"]) / active_trade["entry_price"] if active_trade["direction"] == "BUY" else (active_trade["entry_price"] - exit_price) / active_trade["entry_price"]
        
        trades.append({
            "entry_time": active_trade["entry_time"],
            "exit_time": exit_time,
            "direction": active_trade["direction"],
            "entry_price": active_trade["entry_price"],
            "sl_price": np.nan,
            "tp_price": np.nan,
            "exit_price": exit_price,
            "exit_reason": "END_OF_DATA",
            "pnl_pct": pnl_pct,
            "mae_pct": mae / active_trade["entry_price"],
            "mfe_pct": mfe / active_trade["entry_price"],
            "duration_minutes": duration_mins,
            "smallest_tf": active_trade["smallest_tf"]
        })
        
    return pd.DataFrame(trades)

def evaluate_metrics(df_trades: pd.DataFrame, symbol: str, resolution: str, target_rr: float):
    if df_trades.empty:
        print(f"\n[WARNING] No trades were triggered for {symbol} at {resolution} resolution.")
        return
        
    total_trades = len(df_trades)
    winning_trades = df_trades[df_trades["pnl_pct"] > 0]
    losing_trades = df_trades[df_trades["pnl_pct"] <= 0]
    
    win_rate = len(winning_trades) / total_trades if total_trades > 0 else 0.0
    
    total_profit = winning_trades["pnl_pct"].sum()
    total_loss = abs(losing_trades["pnl_pct"].sum())
    profit_factor = total_profit / total_loss if total_loss > 0 else float('inf')
    
    avg_pnl = df_trades["pnl_pct"].mean()
    avg_duration = df_trades["duration_minutes"].mean()
    
    avg_mae = df_trades["mae_pct"].mean()
    avg_mfe = df_trades["mfe_pct"].mean()
    
    # Equity curve and Max Drawdown calculation
    df_trades = df_trades.sort_values("entry_time").reset_index(drop=True)
    equity = [1.0]
    for pnl in df_trades["pnl_pct"]:
        equity.append(equity[-1] * (1.0 + pnl))
    equity = np.array(equity)
    
    peaks = np.maximum.accumulate(equity)
    drawdowns = (peaks - equity) / peaks
    max_dd = drawdowns.max()
    
    print(f"\n==================================================")
    print(f" BACKTEST RESULTS: {symbol} ({resolution})")
    print(f"==================================================")
    print(f"Total Trades:         {total_trades}")
    print(f"Win Rate:             {win_rate * 100:.2f}% ({len(winning_trades)} wins, {len(losing_trades)} losses)")
    print(f"Profit Factor:        {profit_factor:.2f}")
    print(f"Expectancy:           {avg_pnl * 100:.3f}% average return per trade")
    print(f"Max Equity Drawdown:  {max_dd * 100:.2f}%")
    print(f"Avg Trade Duration:   {avg_duration:.1f} minutes")
    print(f"Avg MAE (Drawdown):   {avg_mae * 100:.2f}%")
    print(f"Avg MFE (Run-up):     {avg_mfe * 100:.2f}%")
    print(f"==================================================")
    
    # Save results to markdown file and CSV
    output_dir = "docs"
    os.makedirs(output_dir, exist_ok=True)
    out_file = os.path.join(output_dir, "backtest_results.md")
    csv_file = os.path.join(output_dir, f"{symbol}_{resolution}_trades.csv")
    
    # Append or write fresh results
    write_header = not os.path.exists(out_file)
    with open(out_file, "a" if os.path.exists(out_file) else "w", encoding="utf-8") as f:
        if write_header:
            f.write("# Historical Backtesting Reports\n\n")
            
        f.write(f"## {symbol} - Timeframe {resolution} - TP Target {target_rr}:1\n")
        f.write(f"* **Total Trades:** {total_trades}\n")
        f.write(f"* **Win Rate:** {win_rate * 100:.2f}% ({len(winning_trades)} wins / {len(losing_trades)} losses)\n")
        f.write(f"* **Profit Factor:** {profit_factor:.2f}\n")
        f.write(f"* **Expectancy (Avg Return):** {avg_pnl * 100:.3f}%\n")
        f.write(f"* **Maximum Equity Drawdown:** {max_dd * 100:.2f}%\n")
        f.write(f"* **Average Trade Duration:** {avg_duration:.1f} minutes\n")
        f.write(f"* **Average MAE:** {avg_mae * 100:.3f}%\n")
        f.write(f"* **Average MFE:** {avg_mfe * 100:.3f}%\n\n")
        
    try:
        df_trades.to_csv(csv_file, index=False)
        print(f"[SUCCESS] Trade logs saved to {csv_file}")
    except PermissionError:
        import time
        alt_filename = f"{symbol}_{resolution}_trades_{int(time.time())}.csv"
        alt_csv_file = os.path.join(output_dir, alt_filename)
        print(f"[WARNING] Permission denied for {csv_file} (is the file open in Excel/another program?).")
        try:
            df_trades.to_csv(alt_csv_file, index=False)
            print(f"[SUCCESS] Saved trade logs to alternative file: {alt_csv_file}")
        except Exception as alt_err:
            print(f"[ERROR] Could not save alternative file: {str(alt_err)}")
            
    print(f"[SUCCESS] Results saved to {out_file}")

def main():
    args = parse_args()
    try:
        df_price, df_events = load_data(args.symbol)
        df_trades = run_backtest(df_price, df_events, args.resolution, args.target_rr, args.min_risk_pct)
        evaluate_metrics(df_trades, args.symbol, args.resolution, args.target_rr)
    except Exception as e:
        print(f"[ERROR] Backtest run failed: {str(e)}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
