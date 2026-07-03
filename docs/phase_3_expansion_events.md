# Phase 3: Multi-Timeframe Expansion Event Detection & Logging

In quantitative trading, breakouts are key indicators of institutional interest, momentum, and potential trend reversals. Phase 3 implements an automated, high-performance engine using a **Hybrid Breakout Configuration**:
1. **1-Minute Timeframe ($T=1\text{m}$):** Applies the **Double-Breakout Run (Consecutive Breakouts)** rule. This requires two consecutive 1-minute breakout candles to filter out high-frequency noise.
2. **Timeframes $T > 1\text{m}$:** Applies the **Single-Bar Breakout** rule (where a bar's Close breaks above the previous bar's High or below the previous Low).

---

## 1. Technical Engine Workflow

```
   Raw 1m Parquet Prices
            │
            ▼
┌──────────────────────────────┐
│    Continuous Reindexing     │  <--- Fills gaps with NaNs
└────────────┬─────────────────┘
             │
             ▼
┌──────────────────────────────┐
│  Multi-Timeframe Aggregation │  <--- Daily boundary reset at 00:00
│  For T in 1m to 1440m        │
└────────────┬─────────────────┘
             │
             ▼
┌──────────────────────────────┐
│    Temporal Adjacency        │  <--- NaN propagation ignores gaps
│    Breakout Calculation      │
└────────────┬─────────────────┘
             │
             ▼
┌──────────────────────────────┐
│    Long-Format Event Log     │  <--- Saved to data/events/
└──────────────────────────────┘
```

---

## 2. Core Quantitative Features

### A. Strict Grid Reindexing (Temporal Adjacency)
Trading systems often suffer from missing candles due to API glitches, rate limit blocks, or exchange maintenance. Simply using `.shift(1)` on a gapped dataset would compare a current bar with a historical bar that might be hours or days old.
* **The Architecture:** The engine reindexes the 1m time-series onto a strict, continuous grid. Any missing candles are filled with `NaN`.
* **NaN Propagation:** When aggregating 1-minute bars into higher timeframe ($T$) bars, if any underlying candle is `NaN`, the resulting HTF bar's OHLC values are set to `NaN`. When comparing `Close > Prev_High`, any comparison with `NaN` naturally evaluates to `False`, automatically preventing fake breakout signals.

### B. Daily Session Resets & Truncated Bars
To align with standard charting platform session rules, the engine anchors all timeframes to `00:00` UTC.
* **Resets:** Grouping keys are constructed dynamically using the date and the relative daily group index:
  $$\text{Group Key} = \text{Date} + \text{"\_"} + \lfloor \frac{\text{Candle Number} - 1}{T} \rfloor$$
* **Truncated Bars:** If a timeframe $T$ is not a perfect divisor of 1,440 minutes, the last bar of the day closes early at `23:59` as a truncated bar. This keeps the daily boundaries completely clean.

### C. Lookback Warm-Up Buffer
To prevent `NaN` values at the start of our analysis period, May 1st is treated purely as a warm-up buffer. This guarantees that when event tracking begins on May 2nd at `00:00`, the engine has a complete historical 24-hour log to calculate previous reference bars for all timeframes.

---

## 3. Storage Schema
The output events are written to a separate Parquet database: `data/events/{symbol}_expansion_events.parquet`. The data is structured in a long-format event table:

| Column Name | Data Type | Description |
| :--- | :--- | :--- |
| `datetime` | `datetime64[ms, UTC]` | The exact 1m timestamp when the breakout bar closed. |
| `timeframe` | `int16` | The timeframe $T$ (in minutes) that experienced the event. |
| `event_type` | `category` | `Bullish_Expansion` or `Bearish_Expansion`. |
| `price_at_close` | `float64` | The close price of the asset at the breakout minute. |

---

## 4. Execution Statistics (May 2, 2026 – July 3, 2026)

### BTCUSDT:
* **Total Events Detected:** 339,999
* **Bullish Expansions:** 160,693
* **Bearish Expansions:** 179,306
* **Disqualified Gaps:** 0 (Continuous data grid)

### ETHUSDT:
* **Total Events Detected:** 319,724
* **Bullish Expansions:** 151,560
* **Bearish Expansions:** 168,164
* **Disqualified Gaps:** 0 (Continuous data grid)

---

## 5. Future Work: Phase 3 Extension (Context-Rich Events)

To prevent data engineering bloat while retaining high-fidelity strategy filters, the **Context-Rich Event Approach** has been moved to a **Phase 3 Extension**. 

In this upcoming extension, we will augment the event tables with normalized, scale-free metrics to measure breakout quality without duplicating raw price feeds.

### Planned Metrics for the Extension:

1. **Breakout Magnitude (`breakout_magnitude`):**
   Measures the strength of the breakout relative to the previous boundary:
   $$\text{Magnitude} = \frac{\text{HTF Close} - \text{Prev HTF Boundary}}{\text{Prev HTF Boundary}}$$
   *(Uses `Prev HTF High` for bullish expansions, and `Prev HTF Low` for bearish breakdowns).*

2. **Wick-to-Spread Position (`close_position_in_bar`):**
   Identifies where the close lies relative to the high/low range of the bar (helps filter out shooting stars or weak closes):
   $$\text{Close Position} = \frac{\text{HTF Close} - \text{HTF Low}}{\text{HTF High} - \text{HTF Low}}$$
   *(Values near 1.0 indicate strong closes at the absolute high; values near 0.5 indicate mid-bar closes).*

3. **Relative Volume (`relative_volume`):**
   Confirms institutional participation by comparing the breakout bar's volume to a historical moving average:
   $$\text{Relative Volume} = \frac{\text{HTF Volume}}{\text{Average of Prev } N \text{ HTF Volumes}}$$

