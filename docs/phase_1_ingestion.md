# Phase 1: Robust Historical Market Data Ingestion & Validation

For traders and quantitative analysts, the foundation of any backtest or trading model is high-fidelity historical data. A single missing candle, misaligned timestamp, or corrupt price point can skew indicators, trigger false backtest signals, or lead to disastrous live execution. 

This document details the architecture, design choices, and robustness protocols of our **Phase 1 Ingestion Engine**.

---

## 1. The Core Objective
The engine is designed to ingest 1-minute historical candlestick (kline) data from the Binance Spot Exchange for a specified period (e.g., May 1, 2026, to July 1, 2026) for major assets like **BTCUSDT** and **ETHUSDT**. The resulting data must be formatted, validated, and saved in high-efficiency columnar storage format (**Parquet**) to serve as the absolute source of truth.

---

## 2. Ingestion Pipeline Architecture

```
     Binance API (v3/klines)
               │
               ▼
┌──────────────────────────────┐
│  Config-Driven Rate Limiter  │
│  - Adaptive sleep timings    │
│  - Exponential backoffs      │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│     JSON Data Processing     │
│  - Standardize columns       │
│  - Normalize Unix TS to UTC  │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│  Validation & Quality Gate   │
│  - Check for NaN values      │
│  - Detect 0.0 price anomalies│
│  - Check chronological gaps  │
└──────────────┬───────────────┘
               │
               ▼
┌──────────────────────────────┐
│     Incremental Storage      │
│  - Read/Write Parquet Shard  │
└──────────────────────────────┘
```

### Key Technical Specifications:
* **API Endpoint:** `https://api.binance.com/api/v3/klines`
* **Resolution:** 1-minute (`1m`) candles.
* **Format:** Columnar Apache Parquet.
* **Storage Location:** `data/raw shards/{SYMBOL}_1m_2026-05-01_to_2026-07-01.parquet`

---

## 3. Trader-First Reliability Features

### A. Incremental Resume & Safety
Running large downloads from API servers can fail midway due to ISP dropouts, system updates, or server crashes. 
* **The Solution:** The engine inspects existing Parquet shards on startup. It automatically reads the latest recorded timestamp (`max_existing_dt`) and resumes downloading from the very next minute. This prevents duplicate downloads, saves API bandwidth, and prevents gaps.

### B. Adaptive Rate Limit Handling (HTTP 429)
Exchanges strictly enforce rate limits. If a trading bot or script ignores these limit walls, the exchange blocks the IP.
* **The Solution:** The engine features a robust parsing mechanism for the HTTP `Retry-After` header. If Binance throws an HTTP 429 status code:
  1. The code stops executing.
  2. It dynamically parses the header to see exactly how many seconds it needs to sleep.
  3. If no header is present, it executes an exponential backoff formula (`rate_limit_backoff_s * attempt`).

### C. SSL Glitch & Network Glitch Resiliency
Trading environments require uninterrupted data extraction. The script handles SSL handshake terminations and connection resets gracefully, attempting up to 5 retries with exponential backoffs before aborting.

---

## 4. Multi-Step Validation Gate (Data Integrity)
Before raw data is saved, it passes through three validation gates:

| Validation Test | Risk Addressed | Trader Impact |
| :--- | :--- | :--- |
| **NaN Verification** | Missing data fields causing calculation failures. | Prevents indicators (like RSI/MACD) from returning nulls. |
| **Zero-Price Detection** | Freezes or glitch spikes showing price as `0.0`. | Avoids extreme volatility outliers in backtests. |
| **Chronological Gap Analysis** | Missing minutes (missing bars) due to exchange downtime or packet drops. | Ensures time-series continuity; prevents time-distortion in backtests. |

---

## 5. Output Data Schema
The validated Parquet database contains the following structural columns:

| Column Name | Data Type | Description | Example |
| :--- | :--- | :--- | :--- |
| `datetime` | `datetime64[ms, UTC]` | The exact opening timestamp of the candle in UTC. | `2026-07-01 08:33:00+00:00` |
| `open` | `float64` | The opening price of the 1-minute bar. | `58502.76` |
| `high` | `float64` | The highest traded price during the minute. | `58592.01` |
| `low` | `float64` | The lowest traded price during the minute. | `58490.00` |
| `close` | `float64` | The closing price of the 1-minute bar. | `58502.76` |
| `volume` | `float64` | The total quantity of asset traded. | `15.424` |
