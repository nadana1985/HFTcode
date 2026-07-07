# Phase 5: Quantitative Backtesting Engine & Analytics Dashboard

Quantitative trading models require strict validation. Phase 5 introduces a high-performance, strictly causal **Historical Backtesting Engine** and a companion **Interactive Analytics Viewer Dashboard** to evaluate and visualize the performance of the Multi-Timeframe Trend Continuation strategy.

---

## 1. Quantitative Strategy Engine Model

The backtesting engine mirrors the exact mathematical transition states of the live charting environment:

### A. State Resolution (Dominant Weighting Rule)
At any resampled bar close of strategy resolution $R$, we retrieve the completed divisor timeframes $d$ and evaluate their color state counts (Green = Bullish, Red = Bearish, Muted/Gray = Neutral).
We resolve the dominant direction:
* **Bullish State**: Triggered if $\text{Green Count} > \text{Red Count}$.
  * $\text{Bullish Weight} = \text{Green Count} + \text{Neutral Count}$
  * $\text{Bearish Weight} = \text{Red Count}$
* **Bearish State**: Triggered if $\text{Red Count} > \text{Green Count}$.
  * $\text{Bearish Weight} = \text{Red Count} + \text{Neutral Count}$
  * $\text{Bullish} = \text{Green Count}$
* **Tie State**: Triggered if $\text{Green Count} == \text{Red Count}$.

### B. Transition Signals & Filters
State transitions trigger entries, which must pass strict boundary validation filters to verify trend momentum:
* **BUY Entry (Gold Circle)**: Triggered when state shifts from Bearish/Tie $\rightarrow$ Bullish.
  * *Price Filter*: $\text{Current Close} > \text{Previous Close}$
* **SELL Entry (Orange Circle)**: Triggered when state shifts from Bullish/Tie $\rightarrow$ Bearish.
  * *Price Filter*: $\text{Current Close} < \text{Previous Open}$
* **Persistent Memory**: If a state shift occurs but the price filter fails, the signal is blocked and the system **remains in its previous state memory** (preventing duplicate signal spam on subsequent bars).

---

## 2. Daily Session Resets & SSOT Alignment
To align 100% with the visual charts (Single Source of Truth), the backtest engine implements **Daily Session Resets**:
* **Boundary Cleansing**: At `00:00 UTC` every day, the trend memory resets to `"Tie"` and the price filters are cleared.
* **Trade Closure**: Any active/pending trade carried from the previous day is force-closed on the last candle of the day (`23:59 UTC`) at the final bar's close price with exit reason `SESSION_RESET`.

---

## 3. Performance Metrics Definitions

Every trade's lifecycle is tracked chronologically at a 1-minute resolution (tick-by-tick) to extract accurate risk-reward data:

* **Maximum Adverse Excursion (MAE)**:
  Measures the maximum unrealized drawdown experienced during the trade's duration:
  $$\text{MAE (Long)} = \frac{\text{Entry Price} - \min(\text{1m Lows})}{\text{Entry Price}}$$
  $$\text{MAE (Short)} = \frac{\max(\text{1m Highs}) - \text{Entry Price}}{\text{Entry Price}}$$

* **Maximum Favorable Excursion (MFE)**:
  Measures the maximum unrealized run-up experienced during the trade's duration:
  $$\text{MFE (Long)} = \frac{\max(\text{1m Highs}) - \text{Entry Price}}{\text{Entry Price}}$$
  $$\text{MFE (Short)} = \frac{\text{Entry Price} - \min(\text{1m Lows})}{\text{Entry Price}}$$

* **Expectancy**:
  The average percentage return expected per trade:
  $$\text{Expectancy} = \frac{1}{N} \sum_{i=1}^{N} \text{PnL}_i$$

* **Profit Factor**:
  $$\text{Profit Factor} = \frac{\sum \text{Profits}}{\sum |\text{Losses}|}$$

---

## 4. Visual Analytics Dashboard Architecture

To visualize these metrics without client-side timezone bugs, the dashboard utilizes a decoupled browser viewer:

```
    ┌───────────────────────────┐
    │     Raw Trade CSV Log     │ <--- Outputted by python backtest engine
    └─────────────┬─────────────┘
                  │
                  ▼
    ┌───────────────────────────┐
    │   dashboard_server.py     │ <--- Exposes /api/trades JSON endpoint
    └─────────────┬─────────────┘
                  │
                  ▼
    ┌───────────────────────────┐
    │   backtest_viewer.html    │ <--- Displays UTC Date Filters & Metrics Table
    └───────────────────────────┘
```

* **UTC-Enforced UI**: All date formatting (`Intl.DateTimeFormat` with `timeZone: 'UTC'`) and date-picker filters compare ISO timestamps directly in **UTC** to prevent local browser offsets (e.g. IST +05:30) from shifting dates.
* **Smart CSV Selection**: The `/api/trades` route automatically picks the latest generated CSV file, allowing safety catches to write fallback files without crashing.

---

## 5. Execution Summary Reports (May 2, 2026 – July 3, 2026)

### BTCUSDT:
* **30m Resolution**: 822 Trades | Win Rate: 34.91% | Profit Factor: 1.08 | Max Drawdown: 10.26% | Avg Duration: 100.4 min
* **15m Resolution**: 1487 Trades | Win Rate: 32.62% | Profit Factor: 0.99 | Max Drawdown: 13.64% | Avg Duration: 57.4 min

### ETHUSDT:
* **30m Resolution**: 785 Trades | Win Rate: 34.90% | Profit Factor: 1.20 | Max Drawdown: 10.90% | Avg Duration: 104.5 min
* **15m Resolution**: 1462 Trades | Win Rate: 31.40% | Profit Factor: 1.00 | Max Drawdown: 15.87% | Avg Duration: 57.9 min
