import os
import json
import urllib.parse
from http.server import SimpleHTTPRequestHandler, HTTPServer
import pandas as pd

PORT = 8000

class DashboardHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        # Enable CORS for convenience
        self.send_header('Access-Control-Allow-Origin', '*')
        super().end_headers()

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        query_params = urllib.parse.parse_qs(parsed_url.query)

        # API: /api/klines
        if path == "/api/klines":
            self.handle_api_klines(query_params)
        # API: /api/events
        elif path == "/api/events":
            self.handle_api_events(query_params)
        # API: /api/signals
        elif path == "/api/signals":
            self.handle_api_signals(query_params)
        # API: /api/trades
        elif path == "/api/trades":
            self.handle_api_trades(query_params)
        else:
            # Fallback to serving static files or index.html
            if path == "/" or path == "":
                self.path = "/index.html"
            super().do_GET()

    def handle_api_klines(self, params):
        symbol = params.get("symbol", ["BTCUSDT"])[0]
        date_str = params.get("date", ["2026-07-01"])[0] # format: YYYY-MM-DD
        resolution = params.get("resolution", ["1m"])[0] # format: 1m, 15m, 30m
        
        # Load raw klines
        # File pattern matches: data/raw shards/{symbol}_1m_*.parquet
        raw_dir = "data/raw shards"
        files = [f for f in os.listdir(raw_dir) if f.startswith(symbol) and f.endswith(".parquet")]
        if not files:
            self.send_error_json(404, f"No data found for symbol {symbol}")
            return
            
        filepath = os.path.join(raw_dir, files[0])
        try:
            df = pd.read_parquet(filepath)
            df["datetime"] = pd.to_datetime(df["datetime"])
            
            # Filter for specific date
            # Ensure filtering works regardless of timezone
            df_filtered = df[df["datetime"].dt.strftime("%Y-%m-%d") == date_str].copy()
            df_filtered = df_filtered.sort_values("datetime")
            
            # Resample if resolution is 15m or 30m
            if resolution in ["15m", "30m"]:
                rule = "15Min" if resolution == "15m" else "30Min"
                df_filtered = df_filtered.resample(rule, on="datetime").agg({
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last",
                    "volume": "sum"
                }).dropna().reset_index()
            
            # Lightweight charts expects time in unix timestamp (seconds)
            chart_data = []
            for _, row in df_filtered.iterrows():
                chart_data.append({
                    "time": int(row["datetime"].timestamp()),
                    "open": float(row["open"]),
                    "high": float(row["high"]),
                    "low": float(row["low"]),
                    "close": float(row["close"]),
                    "volume": float(row["volume"])
                })
            
            self.send_response_json(chart_data)
        except Exception as e:
            self.send_error_json(500, f"Error processing kline data: {str(e)}")

    def handle_api_events(self, params):
        symbol = params.get("symbol", ["BTCUSDT"])[0]
        date_str = params.get("date", ["2026-07-01"])[0] # format: YYYY-MM-DD
        
        filepath = f"data/events/{symbol}_expansion_events.parquet"
        if not os.path.exists(filepath):
            self.send_response_json([])
            return
            
        try:
            df = pd.read_parquet(filepath)
            df["datetime"] = pd.to_datetime(df["datetime"])
            
            # Filter for specific date
            df_filtered = df[df["datetime"].dt.strftime("%Y-%m-%d") == date_str].copy()
            df_filtered = df_filtered.sort_values("datetime")
            
            event_data = []
            for _, row in df_filtered.iterrows():
                event_data.append({
                    "time": int(row["datetime"].timestamp()),
                    "timeframe": int(row["timeframe"]),
                    "event_type": str(row["event_type"]),
                    "price_at_close": float(row["price_at_close"])
                })
                
            self.send_response_json(event_data)
        except Exception as e:
            self.send_error_json(500, f"Error processing event data: {str(e)}")

    def handle_api_signals(self, params):
        symbol = params.get("symbol", ["BTCUSDT"])[0]
        date_str = params.get("date", ["2026-07-01"])[0] # format: YYYY-MM-DD
        resolution = params.get("resolution", ["1m"])[0] # format: 1m, 15m, 30m
        
        # Load raw klines to iterate resampled timeframe bars
        raw_dir = "data/raw shards"
        files = [f for f in os.listdir(raw_dir) if f.startswith(symbol) and f.endswith(".parquet")]
        if not files:
            self.send_error_json(404, f"No data found for symbol {symbol}")
            return
            
        filepath = os.path.join(raw_dir, files[0])
        events_filepath = f"data/events/{symbol}_expansion_events.parquet"
        
        if not os.path.exists(events_filepath):
            self.send_response_json([])
            return

        try:
            df = pd.read_parquet(filepath)
            df["datetime"] = pd.to_datetime(df["datetime"])
            
            # Filter for specific date
            df_filtered = df[df["datetime"].dt.strftime("%Y-%m-%d") == date_str].copy()
            df_filtered = df_filtered.sort_values("datetime")
            
            # Resample if resolution is 15m or 30m
            R = 1
            if resolution in ["15m", "30m"]:
                R = 15 if resolution == "15m" else 30
                rule = f"{R}Min"
                df_filtered = df_filtered.resample(rule, on="datetime").agg({
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last"
                }).dropna().reset_index()
            
            df_filtered['elapsed_minutes'] = (df_filtered['datetime'].dt.hour * 60 + df_filtered['datetime'].dt.minute) + R
            
            # Load timeframe breakout events
            events = pd.read_parquet(events_filepath)
            events["datetime"] = pd.to_datetime(events["datetime"])
            events_filtered = events[events["datetime"].dt.strftime("%Y-%m-%d") == date_str].copy()
            
            results = []
            prev_state = "Tie"
            prev_close = None
            prev_open = None
            
            for _, row in df_filtered.iterrows():
                time_val = row["datetime"]
                elapsed = int(row["elapsed_minutes"])
                curr_close = float(row["close"])
                curr_open = float(row["open"])
                
                # Positive divisors of the elapsed minutes
                divisors = [d for d in range(1, elapsed + 1) if elapsed % d == 0]
                
                curr_events = events_filtered[events_filtered["datetime"] == time_val + pd.Timedelta(minutes=R-1)]
                
                green_count = 0
                red_count = 0
                
                for d in divisors:
                    d_event = curr_events[curr_events["timeframe"] == d]
                    if not d_event.empty:
                        etype = d_event.iloc[0]["event_type"]
                        if etype == "Bullish_Expansion":
                            green_count += 1
                        elif etype == "Bearish_Expansion":
                            red_count += 1
                
                # Determine state
                if green_count > red_count:
                    curr_state = "Bullish"
                elif red_count > green_count:
                    curr_state = "Bearish"
                else:
                    curr_state = "Tie"
                
                # Detect state transitions (Sells and Buys)
                signal = ""
                if prev_state == "Tie":
                    if curr_state != "Tie":
                        prev_state = curr_state
                else:
                    if prev_state == "Bearish" and curr_state == "Bullish":
                        # Trend shift validation filter: must close higher than previous bar's close
                        if prev_close is not None and curr_close > prev_close:
                            signal = "BUY"
                    elif prev_state == "Bullish" and curr_state == "Bearish":
                        # Trend shift validation filter: must close lower than previous bar's open
                        if prev_open is not None and curr_close < prev_open:
                            signal = "SELL"
                
                if signal:
                    prev_state = curr_state
                    
                prev_close = curr_close
                prev_open = curr_open
                    
                if signal:
                    results.append({
                        "time": int(time_val.timestamp()),
                        "signal": signal
                    })
                    
            self.send_response_json(results)
        except Exception as e:
            self.send_error_json(500, f"Error calculating signals: {str(e)}")

    def handle_api_trades(self, params):
        symbol = params.get("symbol", ["BTCUSDT"])[0]
        resolution = params.get("resolution", ["30m"])[0]
        
        output_dir = "docs"
        import glob
        import numpy as np
        
        pattern = os.path.join(output_dir, f"{symbol}_{resolution}_trades*.csv")
        files = glob.glob(pattern)
        if not files:
            self.send_response_json([])
            return
            
        # Get the latest modified file (in case of timestamped safety files)
        latest_file = max(files, key=os.path.getmtime)
        try:
            df = pd.read_csv(latest_file)
            df = df.replace({np.nan: None})
            trades_data = df.to_dict(orient="records")
            self.send_response_json(trades_data)
        except Exception as e:
            self.send_error_json(500, f"Error reading trade data: {str(e)}")

    def send_response_json(self, data):
        response_bytes = json.dumps(data).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(response_bytes)))
        self.end_headers()
        self.wfile.write(response_bytes)

    def send_error_json(self, status_code, message):
        response_bytes = json.dumps({"error": message}).encode('utf-8')
        self.send_response(status_code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(response_bytes)))
        self.end_headers()
        self.wfile.write(response_bytes)

def main():
    os.makedirs("static", exist_ok=True)
    server_address = ('', PORT)
    httpd = HTTPServer(server_address, DashboardHandler)
    print(f"\n[SUCCESS] Quant Dashboard Server running at http://localhost:{PORT}/")
    print("Press Ctrl+C to terminate.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer shut down.")

if __name__ == "__main__":
    main()
