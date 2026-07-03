import os
import glob
import pandas as pd
from typing import Dict, List, Tuple

def precompute_htf_details() -> Dict[int, Tuple[int, str]]:
    """
    Precompute the HTF details for all possible daily candle numbers (1 to 1440).
    Returns a dictionary mapping: candle_number -> (htf_close_count, comma_separated_closed_htfs)
    """
    htf_map = {}
    for cn in range(1, 1441):
        divisors = [t for t in range(1, cn + 1) if cn % t == 0]
        htf_map[cn] = (len(divisors), ",".join(map(str, divisors)))
    return htf_map

def generate_features_for_file(filepath: str, output_dir: str, htf_map: Dict[int, Tuple[int, str]]) -> None:
    """
    Reads a raw 1m kline Parquet file, calculates the HTF candle numbers and divisor counts,
    and saves them in a separate feature Parquet file.
    """
    filename = os.path.basename(filepath)
    symbol = filename.split("_")[0]
    print(f"[INFO] Processing raw file: {filename} ({symbol})")
    
    # Load raw file
    df = pd.read_parquet(filepath)
    if df.empty:
        print(f"[WARNING] File {filename} is empty. Skipping.")
        return
    
    # Ensure datetime is in datetime format
    df["datetime"] = pd.to_datetime(df["datetime"])
    
    # Calculate Candle Number
    # TradingView labels candles by their open time.
    # Candle Number = (Hour * 60 + Minute) + 1
    hours = df["datetime"].dt.hour
    minutes = df["datetime"].dt.minute
    df["candle_number"] = (hours * 60 + minutes) + 1
    
    # Map the precomputed divisor counts and lists
    df["htf_close_count"] = df["candle_number"].map(lambda x: htf_map[x][0]).astype("int16")
    df["closed_htfs"] = df["candle_number"].map(lambda x: htf_map[x][1])
    
    # Prepare the feature-only dataframe (to keep raw and features decoupled)
    # Joining key is "datetime"
    df_features = df[["datetime", "candle_number", "htf_close_count", "closed_htfs"]].copy()
    
    # Define output file path
    os.makedirs(output_dir, exist_ok=True)
    out_filename = f"{symbol}_htf_features.parquet"
    out_filepath = os.path.join(output_dir, out_filename)
    
    print(f"[INFO] Saving features ({len(df_features)} rows) to: {out_filepath}")
    df_features.to_parquet(out_filepath, index=False)
    
    # Run sanity checks
    # Test specific known time: 08:44 -> Candle #525 -> 12 closed HTFs
    test_rows = df[df["datetime"].dt.strftime("%H:%M") == "08:44"]
    if not test_rows.empty:
        sample = test_rows.iloc[0]
        assert sample["candle_number"] == 525, f"Expected candle number 525, got {sample['candle_number']}"
        assert sample["htf_close_count"] == 12, f"Expected 12 closed HTFs, got {sample['htf_close_count']}"
        print(f"[OK] Sanity check passed for {symbol} at 08:44 (Candle #525, Count=12).")

def main():
    raw_dir = "data/raw shards"
    output_dir = "data/features"
    
    # Precompute all possible candle numbers to map efficiently
    print("[INFO] Precomputing HTF divisor details...")
    htf_map = precompute_htf_details()
    
    # Find all raw 1m kline files
    raw_files = glob.glob(os.path.join(raw_dir, "*_1m_*.parquet"))
    if not raw_files:
        print(f"[ERROR] No raw files found in {raw_dir}. Please run download_klines.py first.")
        return
        
    for filepath in raw_files:
        generate_features_for_file(filepath, output_dir, htf_map)
        
    print("\n[INFO] All HTF features generated successfully!")

if __name__ == "__main__":
    main()
