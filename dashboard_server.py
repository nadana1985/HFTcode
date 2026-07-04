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
