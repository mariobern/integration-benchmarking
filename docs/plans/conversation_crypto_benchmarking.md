# Conversation: Adding Crypto Benchmarking to publisher_benchmark.py

**Date:** 2025-01-27
**Status:** Paused - awaiting decisions

---

## Summary

Discussion about adding crypto benchmarking capabilities to `publisher_benchmark.py` based on the approach used in the research repo's `feed_reliability_tests.py`.

---

## Key Files Analyzed

### 1. `feed_reliability_tests.py` (Research Repo)

**Location:** `/home/mariobern/research/pythresearch/lazer/feed_reliability_tests.py`

**Purpose:** Evaluates Lazer feed reliability through three analyses:

| Analysis         | Description                                                    |
| ---------------- | -------------------------------------------------------------- |
| Publisher Uptime | Measures how consistently each publisher submits price updates |
| Feed Uptime      | Measures overall feed availability using time windows          |
| Price Deviation  | Compares publisher prices against Pyth aggregate and Binance   |

**Benchmarks Used:**

- **Pyth Aggregate** - from `PythDb.get_xc_data()`
- **Binance (publisher_id=1)** - from Lazer data itself

**Key Modules:**

- `pythresearch.lazer.reliability.deviation` - deviation calculations
- `pythresearch.lazer.reliability.uptime` - uptime calculations
- `pythresearch.data.lazer_db.LazerDb` - Lazer database access
- `pythresearch.data.pyth_db.PythDb` - Pyth aggregate data access

**CLI Usage:**

```bash
python feed_reliability_tests.py "2025-01-01 00:00:00" "2025-01-02 00:00:00" \
    --symbols "Crypto.BTC/USD,Crypto.ETH/USD" \
    --publishers "1,2,3" \
    --env prod \
    --threads 8
```

**Output:** CSV files in `./reports/`:

- `publisher_uptime_prod_YYYYMMDD_HHMMSS.csv`
- `feed_uptime_prod_YYYYMMDD_HHMMSS.csv`
- `pyth_deviation_prod_YYYYMMDD_HHMMSS.csv`
- `binance_deviation_prod_YYYYMMDD_HHMMSS.csv`

---

### 2. `publisher_benchmark.py` (Integration Benchmarking)

**Location:** `/home/mariobern/integration-benchmarking/publisher_benchmark.py`

**Purpose:** Evaluates single publisher's data quality against Datascope benchmark.

**Benchmarks Used:**

- **Datascope** (external institutional data) from `analytics_clickhouse` cluster
- Tables: `datascope_fx_benchmark_data`, `datascope_global_equities_benchmark_data`, `datascope_futures_benchmark_data`

**Supported Asset Classes:**

- `fx` - Foreign exchange
- `metals` - Precious metals
- `us-equities` - US equities (with market hours filtering)
- `commodity` - Commodities and futures

**NOT Supported (no benchmark):**

- `crypto`
- `crypto-redemption-rate`
- `funding-rate`
- `rates`
- `nav`

**Pass/Fail Criteria:**

```
PASSES if: nrmse < 0.01 OR (nrmse < 0.05 AND hit_rate >= 98%)
```

---

## Comparison: The Two Scripts

| Aspect               | `feed_reliability_tests.py` | `publisher_benchmark.py`              |
| -------------------- | --------------------------- | ------------------------------------- |
| **Primary Use**      | Crypto feeds                | TradFi feeds                          |
| **Benchmark Source** | Pyth aggregate + Binance    | Datascope (institutional)             |
| **Data Location**    | `PythDb` + `LazerDb`        | `analytics_clickhouse`                |
| **Metrics**          | % deviation from baseline   | NRMSE, hit rate, RMSE/spread          |
| **Pass/Fail**        | Informational only          | Strict criteria                       |
| **Market Hours**     | 24/7 (no filtering)         | US equities filtered to regular hours |

---

## Proposed: Adding Crypto to publisher_benchmark.py

### Benchmark Options

| Option                    | Description                        | Pros                          | Cons                                         |
| ------------------------- | ---------------------------------- | ----------------------------- | -------------------------------------------- |
| **A. Binance (pub_id=1)** | Use Binance publisher as benchmark | Already in Lazer data, simple | Circular dependency (publisher vs publisher) |
| **B. Pyth Aggregate**     | Use Pyth network aggregate price   | Independent benchmark         | Requires `PythDb` connection                 |
| **C. External API**       | CoinGecko, CoinMarketCap, etc.     | Truly independent             | New integration, rate limits                 |

### Recommendation

**Hybrid approach:**

1. **Primary:** Binance (publisher_id=1) - practical, already available
2. **Secondary:** Pyth aggregate - adds independence (optional)

### Implementation Considerations

**Pros:**

- Unified tool for all asset classes
- Consistent metrics across TradFi and crypto
- Single output format

**Cons:**

- Binance benchmark is not truly independent
- Crypto is 24/7 (no market hours filtering needed)
- Crypto spreads behave differently
- Need fallback when Binance doesn't publish for a feed

---

## Open Questions (Need Answers Before Implementing)

1. **Is Binance (pub_id=1) acceptable as a benchmark?**

   - It's not independent like Datascope
   - It's a Lazer publisher itself

2. **Do you want Pyth aggregate as a secondary benchmark?**

   - Requires adding `PythDb` access to the script
   - More complex but provides independence

3. **Should pass/fail criteria be the same for crypto?**

   - Crypto has different volatility characteristics
   - Spreads behave differently
   - Thresholds may need adjustment

4. **What about feeds where Binance doesn't publish?**
   - Some crypto feeds might not have Binance data
   - Need a fallback strategy

---

## Next Steps

When resuming this conversation:

1. Answer the open questions above
2. Decide on benchmark approach (Binance only, Pyth only, or both)
3. Discuss pass/fail threshold adjustments for crypto
4. Implement the changes

---

## Reference: Key Code Locations

```
Research Repo:
/home/mariobern/research/pythresearch/lazer/feed_reliability_tests.py
/home/mariobern/research/pythresearch/lazer/reliability/deviation.py
/home/mariobern/research/pythresearch/lazer/reliability/uptime.py
/home/mariobern/research/pythresearch/data/lazer_db.py
/home/mariobern/research/pythresearch/data/pyth_db.py

Integration Benchmarking:
/home/mariobern/integration-benchmarking/publisher_benchmark.py
/home/mariobern/integration-benchmarking/quick_benchmark.py
/home/mariobern/integration-benchmarking/config.yaml
```
