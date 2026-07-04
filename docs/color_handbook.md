# Quant Breakout Dashboard: Color & Heatmap Handbook

This handbook serves as a guide for traders and developers to interpret the visual layout, color codes, and closed timeframe divisor heatmap on the dashboard.

---

## 1. Color System Quick Reference

The dashboard uses a standardized color system to represent breakout states across all charts, markers, and heatmap blocks:

| Color | CSS Variable / Hex | Technical Meaning | Trading Action |
| :--- | :--- | :--- | :--- |
| 🟢 **Green** | `var(--accent-green)` / `#00e676` | **Bullish Expansion** | Close broke above the previous HTF bar's High. |
| 🔴 **Red** | `var(--accent-red)` / `#ff3d00` | **Bearish Breakdown** | Close broke below the previous HTF bar's Low. |
| ⚪ **Gray** | `var(--neutral-gray)` / `#2d3548` | **Neutral State** | Close remained inside the previous HTF bar's range. |

---

## 2. Closed Timeframes Heatmap (Divisors Explained)

The panel below the chart lists the **Closed Timeframes (Positive Divisors)** closing on the hovered candle. 

### Why do divisors change dynamically?
Our system resets and anchors all timeframes at the daily boundary (`00:00` UTC). As time passes, different timeframe blocks complete:
* At `00:15` UTC (15 minutes elapsed), only timeframes that divide 15 evenly can close (e.g. `1m`, `3m`, `5m`, `15m`).
* At `08:30` UTC (510 minutes elapsed), timeframes that divide 510 can close (e.g. `1m`, `2m`, `3m`, `5m`, `6m`, `10m`, `15m`, `17m`, `30m`, `34m`, `51m`, `85m`, `102m`, `170m`, `255m`, `510m`).

---

## 3. Sample Heatmap Walkthrough

Let's look at a real example for **ETHUSDT** on **July 1st, 2026, at 08:35 UTC** (Candle #516).

When you hover over this candle, the heatmap displays several blocks, color-coded based on their breakout state:

```
Closed Timeframes (Positive Divisors) at 2026-07-01 08:35 UTC:
┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐ ┌──────┐
│ 1m  │ │ 2m  │ │ 3m  │ │ 4m  │ │ 5m  │ │ 43m  │ ...
└─────┘ └─────┘ └─────┘ └─────┘ └─────┘ └──────┘
   ⚪      ⚪      🔴      🔴      ⚪       🔴
```

### Breakdown of the Blocks:

#### A. 🔴 Red Blocks (`3m`, `4m`, `43m`)
* **State:** Bearish Breakdown.
* **Explanation:** 
  * The `3m` bar closing at 08:35 had a close price of **$1,571.32**, which was lower than the previous 3m bar's Low boundary (**$1,571.94**).
  * The `4m` bar also closed below its previous Low boundary (**$1,571.92**).
  * The large `43m` bar closed below its previous Low boundary (**$1,573.04**).
* **Traders' Interpretation:** High timeframe selling pressure is present. Sellers are actively pushing the price below multi-candle lows.

#### B. ⚪ Gray Blocks (`1m`, `2m`, `5m`)
* **State:** Neutral.
* **Explanation:** These timeframes closed at 08:35, but their close price remained within their previous bar's High-Low boundaries.
  * *Note: For `1m`, even though the 1-minute candle itself is green, it did not break the previous 1m High, keeping it neutral.*
* **Traders' Interpretation:** These timeframes are consolidating and trading inside their previous ranges.
