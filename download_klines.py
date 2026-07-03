import os
import time
import email.utils
from typing import Dict
import pandas as pd
import requests

def _parse_retry_after_seconds(retry_after_value: str, fallback_seconds: float) -> float:
    """Parse HTTP Retry-After header into seconds. Supports either delta-seconds or IMF-fixdate formats."""
    try:
        parsed_seconds = float(retry_after_value)
        return max(parsed_seconds, 0.0)
    except (TypeError, ValueError):
        parsed_dt = email.utils.parsedate_to_datetime(str(retry_after_value))
        if parsed_dt is None:
            return float(fallback_seconds)
        now_utc = pd.Timestamp.now(tz="UTC").to_pydatetime()
        if parsed_dt.tzinfo is None:
            parsed_dt = parsed_dt.replace(tzinfo=now_utc.tzinfo)
        wait_seconds = (parsed_dt - now_utc).total_seconds()
        return max(float(wait_seconds), 0.0)

def _fetch_binance_klines(symbol: str, start_str: str, end_str: str, config: Dict) -> pd.DataFrame:
    """Config-driven paginated fetch."""
    data_cfg = config["data"]
    const = config["reproducibility"]["constants"]
    base_url = data_cfg["binance_api_url"]
    limit = data_cfg.get("binance", {}).get("limit_per_request", const["binance_limit_int"])
    all_data = []
    
    start_ts = pd.Timestamp(start_str)
    if start_ts.tz is None:
        start_ts = start_ts.tz_localize("UTC")
    end_ts = pd.Timestamp(end_str)
    if end_ts.tz is None:
        end_ts = end_ts.tz_localize("UTC")
        
    end_ms = int(end_ts.timestamp() * const["ms_factor_int"])
    current = int(start_ts.timestamp() * const["ms_factor_int"])
    one_i = const["one_int"]
    request_count = 0
    
    while True:
        params = {
            "symbol": symbol,
            "interval": data_cfg["intervals"][const["zero_int"]],
            "limit": limit,
            "startTime": current,
        }
        
        # Robust Retry Loop with Adaptive + Exponential Backoff
        data = None
        max_retries = data_cfg.get("binance", {}).get("max_retries", 5)
        base_backoff = data_cfg.get("binance", {}).get("base_backoff_s", 5)
        rate_limit_base = data_cfg.get("binance", {}).get("rate_limit_backoff_s", 30)
        
        for attempt in range(max_retries):
            try:
                resp = requests.get(base_url, params=params, timeout=const["fifteen_int"])
                if resp.status_code == const["rate_limit_status"]:
                    retry_after = resp.headers.get("Retry-After")
                    if retry_after is not None:
                        backoff = _parse_retry_after_seconds(retry_after, rate_limit_base)
                        print(f"[WARNING] Binance rate-limited (HTTP 429). Retry-After header: {backoff}s. Sleeping...")
                    else:
                        backoff = rate_limit_base * (attempt + const["one_int"])
                        print(f"[WARNING] Binance rate-limited (HTTP 429). Attempt {attempt + 1}/{max_retries}. Sleeping {backoff}s...")
                    time.sleep(backoff)
                    continue
                resp.raise_for_status()
                data = resp.json()
                break
            except Exception as exc:
                backoff = base_backoff * (attempt + const["one_int"])
                print(f"[WARNING] Network/Server glitch (Attempt {attempt + 1}/{max_retries}): {exc}. Retrying in {backoff}s...")
                time.sleep(backoff)
                
        if data is None:
            raise RuntimeError("Fatal: Binance historical fetch aborted due to persistent network or rate-limit failures.")
        if not data:
            break
            
        df_chunk = pd.DataFrame(data, columns=[
            "timestamp", "open", "high", "low", "close", "volume", 
            "close_time", "quote_vol", "trades", "taker_buy_base", "taker_buy_quote", "ignore"
        ])
        df_chunk["datetime"] = pd.to_datetime(df_chunk["timestamp"], unit="ms", utc=True)
        df_chunk[["open", "high", "low", "close", "volume"]] = df_chunk[["open", "high", "low", "close", "volume"]].astype(float)
        df_chunk = df_chunk[["open", "high", "low", "close", "volume", "datetime"]]
        all_data.append(df_chunk)
        
        last_ms = int(data[-1][const["zero_int"]])
        if last_ms >= end_ms:
            break
        current = last_ms + one_i
        request_count += 1
        
        # Print progress every 50 requests
        if request_count % const["fifty_int"] == const["zero_int"]:
            current_dt = df_chunk["datetime"].iloc[-1].strftime("%Y-%m-%d %H:%M:%S")
            print(f"[INFO] Download Progress: Fetch request {request_count} complete. Reached date: {current_dt}")
            
        if len(data) < limit:
            break
        time.sleep(data_cfg.get("binance", {}).get("sleep_time_f", const["half_float"]))
        
    if all_data:
        df_res = pd.concat(all_data, ignore_index=True)
        df_res = df_res[df_res["datetime"] <= end_ts]
        return df_res.sort_values("datetime").reset_index(drop=True)
    return pd.DataFrame()

def validate_dataframe(df: pd.DataFrame, symbol: str) -> None:
    """Validates the dataframe for NaNs, zeroes in key columns, and chronological gaps."""
    if df.empty:
        print(f"[{symbol} Validation] FAIL: DataFrame is empty.")
        return
        
    print(f"\n--- Running Validation Checks for {symbol} ---")
    
    # 1. Check for NaNs
    nan_counts = df.isna().sum()
    total_nans = nan_counts.sum()
    if total_nans > 0:
        print(f"[WARNING] Found NaNs in dataframe:\n{nan_counts[nan_counts > 0]}")
    else:
        print("[OK] No NaNs found.")
        
    # 2. Check for Zeroes
    price_cols = ["open", "high", "low", "close"]
    zero_prices = (df[price_cols] == 0.0).sum()
    zero_volume = (df["volume"] == 0.0).sum()
    
    if zero_prices.sum() > 0:
        print(f"[WARNING] Found zero values in price columns:\n{zero_prices[zero_prices > 0]}")
    else:
        print("[OK] No zero values found in Open/High/Low/Close price columns.")
        
    if zero_volume > 0:
        print(f"[INFO] Found {zero_volume} rows with 0.0 volume. (This can be normal for extremely illiquid/quiet 1m candles).")
        
    # 3. Check for Chronological Gaps (Expected 1-minute intervals)
    # Assumes df is sorted by datetime
    df_sorted = df.sort_values("datetime").reset_index(drop=True)
    time_diffs = df_sorted["datetime"].diff()
    
    # Exclude the first row diff which is NaT
    gaps = time_diffs[time_diffs > pd.Timedelta(minutes=1)]
    if not gaps.empty:
        print(f"[WARNING] Chronological gaps found! Count of gaps: {len(gaps)}")
        # Print first few gaps
        for idx in gaps.index[:5]:
            prev_time = df_sorted.loc[idx - 1, "datetime"]
            curr_time = df_sorted.loc[idx, "datetime"]
            diff = time_diffs.loc[idx]
            print(f"   Gap between {prev_time} and {curr_time} (Duration: {diff})")
    else:
        print("[OK] No missing chronological gaps found (all consecutive candles are exactly 1 minute apart).")
    print(f"--- Finished Validation for {symbol} ---\n")

def run_ingestion_for_symbol(symbol: str, start_date_str: str, end_date_str: str, config: Dict) -> None:
    output_dir = "data/raw shards"
    os.makedirs(output_dir, exist_ok=True)
    filename = os.path.join(output_dir, f"{symbol}_1m_2026-05-01_to_2026-07-01.parquet")
    
    existing_df = pd.DataFrame()
    start_str = start_date_str
    
    if os.path.exists(filename):
        print(f"Found existing file: {filename}. Loading and checking for incremental update...")
        try:
            existing_df = pd.read_parquet(filename)
            if not existing_df.empty:
                max_existing_dt = existing_df["datetime"].max()
                # Ensure the timezone matches (our download function standardizes to UTC)
                if max_existing_dt.tzinfo is None:
                    max_existing_dt = max_existing_dt.tz_localize("UTC")
                
                target_end_ts = pd.Timestamp(end_date_str)
                if target_end_ts.tz is None:
                    target_end_ts = target_end_ts.tz_localize("UTC")
                
                if max_existing_dt >= target_end_ts:
                    print(f"Existing dataset already covers up to {max_existing_dt}. No new ingestion needed.")
                    validate_dataframe(existing_df, symbol)
                    return
                
                # Fetch starting from the next minute after the last recorded candle
                next_start_dt = max_existing_dt + pd.Timedelta(minutes=1)
                start_str = next_start_dt.strftime("%Y-%m-%d %H:%M:%S")
                print(f"Incremental ingestion will resume from: {start_str}")
        except Exception as e:
            print(f"[WARNING] Failed to read existing Parquet file {filename}: {e}. Performing clean download.")
            
    print(f"Starting fetch for {symbol} 1m candles from {start_str} to {end_date_str}...")
    new_df = _fetch_binance_klines(symbol, start_str, end_date_str, config)
    
    if not new_df.empty:
        if not existing_df.empty:
            print("Combining existing and newly fetched incremental data...")
            combined_df = pd.concat([existing_df, new_df], ignore_index=True)
            # Remove any duplicate timestamps if they exist
            combined_df = combined_df.drop_duplicates(subset=["datetime"]).sort_values("datetime").reset_index(drop=True)
        else:
            combined_df = new_df
            
        print(f"Saving updated dataset ({len(combined_df)} rows) to {filename}...")
        combined_df.to_parquet(filename, index=False)
        validate_dataframe(combined_df, symbol)
    else:
        print("No new data fetched.")
        if not existing_df.empty:
            validate_dataframe(existing_df, symbol)

if __name__ == "__main__":
    # Config definition mapping to parameters used in the supplied code
    config = {
        "data": {
            "binance_api_url": "https://api.binance.com/api/v3/klines",
            "intervals": ["1m"],
            "binance": {
                "limit_per_request": 1000,
                "max_retries": 5,
                "base_backoff_s": 2,
                "rate_limit_backoff_s": 10,
                "sleep_time_f": 0.2
            }
        },
        "reproducibility": {
            "constants": {
                "binance_limit_int": 500,
                "ms_factor_int": 1000,
                "one_int": 1,
                "zero_int": 0,
                "fifteen_int": 15,
                "rate_limit_status": 429,
                "fifty_int": 50,
                "half_float": 0.5
            }
        }
    }
    
    # Target period
    start_date = "2026-05-01 00:00:00"
    end_date = "2026-07-03 00:00:00"
    
    for symbol in ["BTCUSDT", "ETHUSDT"]:
        run_ingestion_for_symbol(symbol, start_date, end_date, config)
    
    print("\nAll tasks completed successfully!")
