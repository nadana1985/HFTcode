# Phase 4: Interactive UX Visualization Dashboard

For quantitative traders and analysts, charts are the ultimate tool to evaluate the validity of mathematical models. Phase 4 introduces a **high-fidelity, dark-themed UX Visualization Dashboard** built using TradingView's open-source **Lightweight Charts** library. 

This dashboard connects directly to our historical datasets and event logs, allowing traders to visually overlay price action, volume, and multi-timeframe breakout events in real time.

---

## 1. Dashboard Layout & Design

The dashboard is structured into three main zones: the control header, the interactive TV candlestick viewport, and the synchronized event details panel.

```
┌────────────────────────────────────────────────────────────────────────┐
│  [ BTCUSDT ▾ ]   Select Date: [ 2026-07-02 ]   [ < Prev Day ] [ Next Day > ] │ <-- Controls
├────────────────────────────────────────────────────────────────────────┤
│                                                                        │
│  [LIGHTWEIGHT CHARTS ENGINE - UPPER HALF]                              │
│   ▲  ██                                                                │
│   │  ██    ██                                                          │
│   │  ░░ ┌──██──┐  <-- Hover crosshair snaps here                       │
│   │     │  ░░  │                                                       │
│   └─────┴──────┴────────────────────────────────────────────────────── │
├────────────────────────────────────────────────────────────────────────┤
│  [EVENT HEATMAP & STATS - LOWER HALF]                                  │
│                                                                        │
│  1m Candle Stats: O: $58,713 | H: $58,730 | L: $58,490 | C: $58,502     │
│                                                                        │
│  Closed Timeframes (Positive Divisors) at 08:33 UTC (2026-07-02)        │
│  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐                                       │
│  │ 1m  │ │ 2m  │ │257m │ │514m │                                       │ <-- Divisors Heatmap
│  └─────┘ └─────┘ └─────┘ └─────┘                                       │
│    🔴     🔴      ⚪      ⚪                                           │
│                                                                        │
│  [Footer detail text] 1m: 🔴 Bearish Breakdown (Closed below $58,713)   │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Interactive Features Explained

### A. TradingView Lightweight Charts
* **Crosshair Synchronisation:** As the mouse moves, crosshairs display vertical time-coordinates and horizontal price-coordinates.
* **Scroll-to-Zoom:** Easily zoom in on high-volatility events or zoom out to see daily trend transitions using the mouse wheel.
* **Drag-to-Pan:** Scroll backward or forward chronologically by dragging the chart body.

### B. Breakout Marker Toggle (Arrows)
* **The Toggle:** A header switch allows users to hide or show breakout markers on the chart.
* **The markers:** 
  * 🟢 **Green Up-Arrows** represent a Bullish Double-Breakout Run on the **1-minute ($T=1\text{m}$)** timeframe alone.
  * 🔴 **Red Down-Arrows** represent a Bearish Double-Breakout Run on the **1-minute ($T=1\text{m}$)** timeframe alone.
  * *Note: Drawing 1-minute markers alone keeps the chart clean and focused on immediate momentum pivots, while higher timeframe breakouts are tracked in the heatmap.*

### C. Confluence Filter Slider
* **Confluence Definition:** A confluence is when multiple timeframes experience a breakout at the exact same minute.
* **The Filter:** The slider is utilized to set thresholds for heatmap monitoring and confluence analysis. The chart markers are locked strictly to the 1m Double-Breakout events to avoid visual clutter from multi-timeframe overlays.

### D. Scroll-Free Divisor Heatmap
* **The Grid:** Traditional scrolling tables are slow. Instead, the dashboard renders a compact, color-coded grid representing all timeframes (divisors) closing on the hovered candle.
  * **Green Blocks:** Bullish breakout.
  * **Red Blocks:** Bearish breakdown.
  * **Gray Blocks:** Neutral (closed inside previous boundaries).
* **Instant Tooltips:** Hovering over any block in the grid dynamically updates a status line at the bottom, printing the exact boundaries broken and close prices.

---

## 3. Data Querying Architecture (Backend & Frontend)

To ensure high performance without complex package configurations (like Node/React or local server database installations), the system runs a dependency-free Python backend:

1. **Backend Server (`dashboard_server.py`):** Uses Python's built-in `http.server` to serve the static frontend and parse API requests:
   * `/api/klines?symbol=...&date=...`: Reads raw Parquet klines and returns daily rows in JSON format.
   * `/api/events?symbol=...&date=...`: Reads the Parquet event logs and returns matching daily breakouts in JSON format.
2. **Frontend App (`static/app.js`):** Instantiates the chart, binds DOM controls, executes API fetches, and handles crosshair move listeners to update the heatmap state in real-time.

---

## 4. Running the Dashboard
To start the visualization tool, execute the python script in your workspace:

```bash
python dashboard_server.py
```

Open your browser and navigate to:
👉 **http://localhost:8000/**
