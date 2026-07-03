import os
import glob
import pandas as pd
import numpy as np
from typing import Dict, List

def setup_directories():
    os.makedirs("data/events", exist_ok=True)

def detect_and_log_gaps(df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    """
    Reindexes the DataFrame to a strict 1-minute time grid and logs any data gaps.
    """
    df = df.sort_values("datetime").reset_index(drop=True)
    df["datetime"] = pd.to_datetime(df["datetime"])
    
    # Generate the complete 1-minute grid
    min_time = df["datetime"].min()
    max_time = df["datetime"].max()
    full_grid = pd.date_range(start=min_time, end=max_time, freq="1min", tz=df["datetime"].dt.tz)
    
    original_len = len(df)
    
    # Set datetime as index to reindex
    df = df.set_index("datetime")
    df = df.reindex(full_grid)
    df = df.reset_index().rename(columns={"index": "datetime"})
    
    new_len = len(df)
    gap_count = new_len - original_len
    
    if gap_count > 0:
        print(f"[WARNING] [Data Quality - {symbol}] Found {gap_count} missing candles. Reindexing inserted NaN rows.")
        
        # Locate contiguous missing blocks for detailed logging
        # Find where prices are null
        is_null = df["close"].isna()
        # Find start and end of null blocks
        null_runs = (is_null != is_null.shift()).cumsum()
        null_blocks = df[is_null].groupby(null_runs)
        
        for _, block in null_blocks:
            start_gap = block["datetime"].min().strftime("%Y-%m-%d %H:%M")
            end_gap = block["datetime"].max().strftime("%Y-%m-%d %H:%M")
            gap_duration = len(block)
            print(f"   [WARNING] [Data Quality - {symbol}] Data gap: {start_gap} to {end_gap} UTC ({gap_duration} minutes missing).")
    else:
        print(f"[OK] [Data Quality - {symbol}] No missing chronological gaps found. Grid is 100% complete.")
        
    return df

def generate_events_for_symbol(filepath: str, symbol: str) -> None:
    print(f"\n==================================================")
    print(f"[INFO] Starting Phase 3 Event Detection for {symbol}")
    print(f"==================================================")
    
    # Load raw kline data
    df_raw = pd.read_parquet(filepath)
    if df_raw.empty:
        print(f"[ERROR] Raw price file for {symbol} is empty.")
        return
        
    # Reindex and log gaps
    df = detect_and_log_gaps(df_raw, symbol)
    
    # Precompute daily properties to speed up grouping
    # TradingView open time labeling
    hours = df["datetime"].dt.hour
    minutes = df["datetime"].dt.minute
    df["candle_number"] = (hours * 60 + minutes) + 1
    df["date_str"] = df["datetime"].dt.strftime("%Y-%m-%d")
    
    all_timeframe_events = []
    warmup_cutoff = pd.Timestamp("2026-05-02 00:00:00", tz="UTC")
    
    # Track daily boundary reset logging per timeframe to avoid console spam (log only first reset)
    logged_truncated = set()
    disqualified_count = 0
    
    # Loop over all timeframes from 1m up to 1440m
    for T in range(1, 1441):
        # Calculate daily group IDs. e.g. T=5 -> first five 1m candles are group 0
        df["group_id"] = (df["candle_number"] - 1) // T
        # Combine date_str and group_id to ensure boundary resets strictly at 00:00
        df["group_key"] = df["date_str"] + "_" + df["group_id"].astype(str)
        
        # Aggregate to HTF bars
        # Note: we use "datetime" as "first" for open, but we track the close_time of the bar.
        # The closing candle's open time is the last 1m candle's datetime.
        # E.g. for a 5m bar, the last 1m candle starts at 08:04 (labeled 08:04), and closes at 08:05.
        # So we represent the HTF bar close at the timestamp of the last 1m candle (08:04).
        htf = df.groupby("group_key").agg(
            open=("open", "first"),
            high=("high", "max"),
            low=("low", "min"),
            close=("close", "last"),
            volume=("volume", "sum"),
            close_time=("datetime", "last"),
            bar_count=("datetime", "count")
        ).reset_index()
        
        # Sort HTF bars chronologically
        htf = htf.sort_values("close_time").reset_index(drop=True)
        
        # Log boundary reset truncated bars
        # A truncated bar occurs if bar_count < T.
        # We only log it for the last group of the day if T does not divide 1440 evenly.
        if 1440 % T != 0 and T not in logged_truncated:
            truncated_rows = htf[htf["bar_count"] < T]
            if not truncated_rows.empty:
                sample_row = truncated_rows.iloc[0]
                # Extract date from group_key
                sample_date = sample_row["group_key"].split("_")[0]
                print(f"[INFO] [HTF Engine - {symbol}] Timeframe {T}m daily reset at {sample_date} 23:59. Final truncated bar duration: {sample_row['bar_count']}m (Expected {T}m).")
                logged_truncated.add(T)
        
        # Shift to get previous bar boundaries
        htf["prev_high"] = htf["high"].shift(1)
        htf["prev_low"] = htf["low"].shift(1)
        
        # Detect gaps/NaN propagation
        # If the current bar close is NaN, or the previous bar's high/low is NaN, it is disqualified.
        curr_nan = htf["close"].isna()
        prev_nan = htf["prev_high"].isna() | htf["prev_low"].isna()
        disqualified_mask = curr_nan | prev_nan
        
        # Track counts of disqualified bars (only for rows after the warm-up cutoff)
        post_warmup_mask = htf["close_time"] >= warmup_cutoff
        num_disqualified = (disqualified_mask & post_warmup_mask).sum()
        if num_disqualified > 0:
            disqualified_count += num_disqualified
            # Log sample disqualification (limit console output)
            if T <= 5: # Only log individual info messages for small timeframes to keep clean
                sample_dq = htf[disqualified_mask & post_warmup_mask].iloc[0]
                print(f"   [INFO] [HTF Engine - {symbol}] Disqualified {T}m bar ending at {sample_dq['close_time'].strftime('%Y-%m-%d %H:%M')} due to NaN propagation.")
        
        # Apply breakout rules (Double-Breakout Run for 1m, Single-Bar Breakout for other timeframes)
        curr_bullish = htf["close"] > htf["prev_high"]
        curr_bearish = htf["close"] < htf["prev_low"]
        if T == 1:
            is_bullish = curr_bullish & curr_bullish.shift(1) & (~disqualified_mask) & (~disqualified_mask.shift(1).fillna(True))
            is_bearish = curr_bearish & curr_bearish.shift(1) & (~disqualified_mask) & (~disqualified_mask.shift(1).fillna(True))
        else:
            is_bullish = curr_bullish & (~disqualified_mask)
            is_bearish = curr_bearish & (~disqualified_mask)
        
        # Filter for active occurrences after the warm-up period (May 2nd onwards)
        bullish_events = htf[is_bullish & post_warmup_mask][["close_time", "close"]].copy()
        bullish_events["timeframe"] = T
        bullish_events["event_type"] = "Bullish_Expansion"
        
        bearish_events = htf[is_bearish & post_warmup_mask][["close_time", "close"]].copy()
        bearish_events["timeframe"] = T
        bearish_events["event_type"] = "Bearish_Expansion"
        
        # Combine
        events = pd.concat([bullish_events, bearish_events], ignore_index=True)
        if not events.empty:
            all_timeframe_events.append(events)
            
    # Combine all timeframes
    if all_timeframe_events:
        df_events = pd.concat(all_timeframe_events, ignore_index=True)
        df_events = df_events.rename(columns={"close_time": "datetime", "close": "price_at_close"})
        # Sort chronologically and by timeframe
        df_events = df_events.sort_values(by=["datetime", "timeframe"]).reset_index(drop=True)
        
        # Convert category for event type
        df_events["event_type"] = df_events["event_type"].astype("category")
        df_events["timeframe"] = df_events["timeframe"].astype("int16")
        
        # Save to Parquet
        out_filepath = f"data/events/{symbol}_expansion_events.parquet"
        df_events.to_parquet(out_filepath, index=False)
        
        # Stats summary
        bullish_count = (df_events["event_type"] == "Bullish_Expansion").sum()
        bearish_count = (df_events["event_type"] == "Bearish_Expansion").sum()
        
        print(f"\n[SUCCESS] [Phase 3 - {symbol}] Event detection complete.")
        print(f"   |-- Output file: {out_filepath}")
        print(f"   |-- Date range: {df_events['datetime'].min()} to {df_events['datetime'].max()}")
        print(f"   |-- Total events detected: {len(df_events)}")
        print(f"   |-- Bullish Expansions: {bullish_count}")
        print(f"   |-- Bearish Expansions: {bearish_count}")
        print(f"   \-- Disqualified gaps: {disqualified_count} bars flagged due to NaN propagation.")
    else:
        print(f"[WARNING] No breakout events detected for {symbol}.")

def main():
    setup_directories()
    raw_dir = "data/raw shards"
    
    # Locate ingested raw kline files
    raw_files = glob.glob(os.path.join(raw_dir, "*_1m_*.parquet"))
    if not raw_files:
        print(f"[ERROR] No raw files found in {raw_dir}. Please run download_klines.py first.")
        return
        
    for filepath in raw_files:
        filename = os.path.basename(filepath)
        symbol = filename.split("_")[0]
        generate_events_for_symbol(filepath, symbol)

if __name__ == "__main__":
    main()
