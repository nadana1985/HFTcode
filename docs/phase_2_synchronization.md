# Phase 2: Mathematical Candle Synchronization & Hybrid Storage

In multi-timeframe (MTF) trading strategies, determining when higher timeframe (HTF) bars close is critical. Traders rely on bar-close signals to compute indicators, execute trades, and manage risk. However, platform-dependent timeframe engines (like TradingView's internal anchoring rules) can introduce lag, misalignment, or complex time-zone issues that skew backtesting results.

This document details the **Mathematical Candle Synchronization Model** and the **Hybrid Feature Storage Architecture** implemented in Phase 2.

---

## 1. The Mathematical Synchronization Model
To ensure complete independence from platform-specific calculations, our model uses a mathematical framework that maps timestamps to absolute daily candle indices and computes closures using integer divisor logic.

### Rule 1: Candle Labeling by OPEN Time
All candles are labeled by their opening timestamp, mirroring the standard exchange and TradingView timestamping behavior.
* **00:00** represents the minute window: `00:00:00` → `00:00:59`.
* **08:29** represents the minute window: `08:29:00` → `08:29:59`.

### Rule 2: Absolute Starting Point
The first candle of the trading day is fixed at **00:00** (UTC).

### Rule 3: The Candle Number Equation
Every 1-minute candle is mapped to an absolute integer sequence starting from `1` at `00:00` up to `1440` at `23:59`:

$$\text{Candle Number} = (\text{Hour} \times 60 + \text{Minute}) + 1$$

* **00:00** $\rightarrow$ Candle #1
* **00:01** $\rightarrow$ Candle #2
* **08:29** $\rightarrow$ Candle #510
* **23:59** $\rightarrow$ Candle #1440

### Rule 4: The Closure Condition
A higher timeframe $T$ (where $T$ represents a duration in minutes) closes on the current 1-minute candle if and only if the current Candle Number is a multiple of $T$:

$$\text{Candle Number} \pmod T == 0$$

### Rule 5: Unlimited Divisors
Unlike standard charts that only view specific sub-60 minute intervals (e.g., 5m, 15m, 1h), our quantitative model returns **all positive divisors** of the Candle Number. This includes any interval from 1 minute up to the current Candle Number itself.
* **Why this matters for traders:** It allows you to track unusual or non-standard timeframe completions (e.g., a 105-minute or 175-minute bar closing) which can signal synchronized flow across multiple classes of market participants.

---

## 2. Example: The 08:44 Candle Alignment
To demonstrate the mathematical model in action:
* **Time:** `08:44`
* **Hour:** 8, **Minute:** 44
* **Candle Number:** $(8 \times 60) + 44 + 1 = 525$
* **Divisor Factoring:** $525 = 3 \times 5^2 \times 7$
* **Closed HTFs:** `1m`, `3m`, `5m`, `7m`, `15m`, `21m`, `25m`, `35m`, `75m`, `105m`, `175m`, `525m`
* **Total HTFs Closed:** `12`

---

## 3. Hybrid Storage Architecture (Bronze/Silver Design)
To prevent schema corruption and avoid breaking historical data ingestion scripts, we decouple the price data from the derived mathematical attributes using a **Hybrid Storage Design**.

```
    ┌───────────────────────────┐
    │  Raw Parquet Price Shard  │ <--- Immutable (Raw Market Feed)
    │  - datetime, open, close  │
    └─────────────┬─────────────┘
                  │
                  │ (Join on datetime)
                  ▼
    ┌───────────────────────────┐
    │  Feature Parquet Shard    │ <--- Extracted Indicators (HTFs Closed)
    │  - candle_number          │
    │  - htf_close_count        │
    │  - closed_htfs            │
    └───────────────────────────┘
```

### Advantages for Quantitative Research:
1. **Safety:** Overwriting raw price files risks data corruption. The hybrid model leaves raw prices pristine.
2. **Speed:** Features are precalculated and mapped in $O(1)$ time using precomputed lookup tables for the 1,440 daily candles.
3. **Reproducibility:** If mathematical rules change, features can be recalculated instantly without re-downloading gigabytes of historical data.

---

## 4. Querying & Merging
To combine prices and HTF features in Python for backtesting or statistical analysis:

```python
import pandas as pd

# Load the separate datasets
df_price = pd.read_parquet("data/raw shards/BTCUSDT_1m_2026-05-01_to_2026-07-01.parquet")
df_features = pd.read_parquet("data/features/BTCUSDT_htf_features.parquet")

# Merge on-the-fly
df_merged = pd.merge(df_price, df_features, on="datetime", how="left")
```
