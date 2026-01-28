# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This repository contains standalone benchmark scripts for Pyth Network Lazer feeds. It evaluates publisher data quality against external benchmarks (Datascope) to assess feed readiness.

## Common Commands

### Setup
```bash
pip install -r requirements.txt
cp config.yaml.sample config.yaml  # then fill in ClickHouse credentials
```

### Running Quick Benchmark

```bash
# Process feeds from CSV file
python quick_benchmark.py --csv price_id_list.csv

# Process a single feed
python quick_benchmark.py --feed-id 327 --date 2025-10-06 --mode fx

# Custom output and target publisher count
python quick_benchmark.py --csv feeds.csv --output results.csv --target-pub-count 6

# Increase parallel workers for faster processing
python quick_benchmark.py --csv price_id_list.csv --workers 8

# List asset classes in a CSV file (discover what's available)
python quick_benchmark.py --csv publisher_11_feeds.csv --list-asset-classes

# Include only specific asset classes (filter by what has benchmark data)
python quick_benchmark.py --csv feeds.csv --include-asset-class fx metals us-equities

# Exclude asset classes without benchmark data
python quick_benchmark.py --csv feeds.csv --exclude-asset-class crypto funding-rate nav
```

### Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--csv` | CSV file with feed_id,date,mode columns | - |
| `--feed-id` | Single feed ID to evaluate | - |
| `--date` | Date for single feed (YYYY-MM-DD) | - |
| `--mode` | Market type: `fx`, `metals`, `us-equities` | - |
| `--output` | Output CSV path | `quick_benchmark_results.csv` |
| `--target-pub-count` | Min publishers for feed readiness | 4 |
| `--workers` | Parallel workers for CSV processing | 4 |
| `--include-asset-class` | Only process these asset classes | - |
| `--exclude-asset-class` | Skip these asset classes | - |
| `--list-asset-classes` | List unique asset classes in CSV and exit | - |

## Pass/Fail Criteria

- **Publisher PASSES** if: `rmse_over_spread <= 1.0`
- **Feed is READY** if: `passing_publisher_count >= target_publisher_count`

## Database Configuration

Requires ClickHouse access configured in `config.yaml`:
- `lazer_clickhouse_prod`: Lazer production cluster (publisher data, feed metadata)
- `analytics_clickhouse`: Analytics cluster (Datascope benchmark data)

If connection fails with "EOF occurred in violation of protocol", the hostname is wrong.

## Input CSV Format

CSV files for batch processing (no header required):
```
feed_id,date,mode
327,2025-10-06,fx
1163,2025-10-02,us-equities
346,2025-10-02,metals
```

### Asset Classes (Modes)

Asset classes with benchmark data available:
- `fx` - Foreign exchange
- `metals` / `metal` - Precious metals
- `us-equities` / `equity-us` - US equities (includes equity index futures)
- `commodity` - Commodities (includes commodity futures)
- `us-treasuries` / `treasuries` / `rates` - US Treasury bonds (uses yield values instead of prices)

Asset classes WITHOUT benchmark data (will error):
- `crypto` - Cryptocurrency
- `crypto-redemption-rate` - Crypto redemption rates
- `funding-rate` - Funding rates
- `nav` - Net asset value

Use `--list-asset-classes` to discover asset classes in your CSV file.

### Futures Support

The scripts automatically detect futures contracts by their symbol pattern and use the appropriate benchmark table (`datascope_futures_benchmark_data`).

**Futures contract naming convention:**
- Symbol ends with `[MONTH_CODE][YEAR_DIGIT]` (e.g., `CCH6`, `EMH6`)
- Month codes: F=Jan, G=Feb, H=Mar, J=Apr, K=May, M=Jun, N=Jul, Q=Aug, U=Sep, V=Oct, X=Nov, Z=Dec
- Year digit: 5=2025, 6=2026, 7=2027, etc.

**Supported futures:**
- **Commodity futures**: `Commodities.CCH6/USD` (Copper), `Commodities.WTIH6/USD` (WTI Crude)
- **Equity index futures**:
  - `Equity.US.EMH6/USD` - E-Mini S&P 500 March 2026
  - `Equity.US.NMH6/USD` - Nasdaq Mini March 2026
  - `Equity.US.DMH6/USD` - Dow Jones Mini March 2026
  - `Equity.US.BRENTH6/USD` - Brent Crude March 2026

Use `--list-asset-classes` to discover asset classes in your CSV file.

## Output

Results CSV contains:
- `feed_id`, `date`, `mode`, `symbol`
- `ready` (boolean)
- `passing_pub_count`, `failing_pub_count`
- `passing_publishers`, `failing_publishers` (semicolon-separated IDs)
- `error` (if any)
- `execution_time_ms`

## Publisher Benchmark Summary

`publisher_benchmark.py` outputs summary statistics after processing (console + CSV):

**Core metrics:**
- `pass_count`, `fail_count`, `error_count`, `pass_rate_pct`

**Quality metrics (rmse_over_spread distribution):**
- `median`, `mean`, `p90`, `p95`, `min`, `max`
- Interpretation: `< 0.5` excellent, `0.5-1.0` good, `> 1.0` failing (lower is better)

**Coverage metrics:**
- `total_observations`, `mean_observations_per_feed`, `median_observations_per_feed`

**Asset class breakdown:**
- `pass_count_{mode}`, `fail_count_{mode}`, `error_count_{mode}` per asset class

Summary is appended to output CSV under a `SUMMARY` header row.

### Advanced Statistical Metrics

The `publisher_benchmark.py` script includes advanced statistical metrics for deeper analysis:

**Per-Feed Metrics:**

| Metric | Description | Interpretation |
|--------|-------------|----------------|
| `mean_diff` | Mean of (publisher - benchmark) | Systematic bias; should be ~0 |
| `std_diff` | Std dev of price differences | Error volatility; lower is better |
| `mean_pct_diff` | Mean % difference | Relative accuracy |
| `std_pct_diff` | Std dev of % differences | Relative error volatility |
| `mae` | Mean Absolute Error | Average deviation; lower is better |
| `t_statistic` | t-test statistic | Tests if bias is significant |
| `t_pvalue` | t-test p-value | < 0.05 indicates significant bias |
| `wilcoxon_statistic` | Wilcoxon test statistic | Non-parametric bias test |
| `wilcoxon_pvalue` | Wilcoxon p-value | < 0.05 indicates significant bias |
| `normality_pvalue` | Normality test p-value | >= 0.05 means errors are normally distributed |
| `mean_abs_z_score` | Mean |z-score| | Typical deviation magnitude; ~0.8 expected |

**Summary Metrics:**

| Metric | Description |
|--------|-------------|
| `t_test_significance_rate` | % of feeds with statistically significant bias (p < 0.05) |
| `normality_rate` | % of feeds with normally distributed errors |
| `median_z_score` | Typical z-score across all feeds |

**Interpretation Guide:**

The script outputs an interpretation guide explaining:
- What each metric means
- How to interpret your results (good/bad thresholds)
- Actionable recommendations for improving data quality

### Extended Hours Support (US Equities)

The `publisher_benchmark.py` script supports evaluation of US equities during extended trading hours:

```bash
# Include extended hours evaluation
python publisher_benchmark.py --csv publisher_55_feeds.csv --extended-hours
```

**Trading Sessions:**

| Session | Time (EST) | Flag Required |
|---------|-----------|---------------|
| Regular Hours | 9:30 AM - 4:00 PM | Always evaluated |
| Pre-market | 4:00 AM - 9:30 AM | `--extended-hours` |
| After-hours | 4:00 PM - 8:00 PM | `--extended-hours` |

**Important Notes:**
- Extended hours evaluation only applies to `us-equities` asset class
- Other asset classes (fx, metals, commodity) are unaffected
- Regular hours results are always shown separately (not mixed with extended hours)
- Extended hours typically have lower liquidity and may have higher error rates
- Minimum observation threshold for extended hours is 50 (vs 100 for regular hours)

**Extended Hours Output:**

When `--extended-hours` is enabled, the CSV output includes additional columns:
- `premarket_n_observations`, `premarket_nrmse`, `premarket_hit_rate`, `premarket_passes`, `premarket_error`
- `afterhours_n_observations`, `afterhours_nrmse`, `afterhours_hit_rate`, `afterhours_passes`, `afterhours_error`

The console summary includes a separate "EXTENDED HOURS" section with aggregate statistics for pre-market and after-hours sessions.

### Feed ID Filtering

The `publisher_benchmark.py` script supports filtering by specific feed IDs:

```bash
# Test specific feed IDs only
python publisher_benchmark.py --csv publisher_55_feeds.csv --feed-id 327 1163

# Combine feed ID filter with asset class filter
python publisher_benchmark.py --csv publisher_55_feeds.csv --include-asset-class us-equities --feed-id 500 501

# Test specific feed ID with overnight session
python publisher_benchmark.py --csv publisher_55_feeds.csv --feed-id 500 --overnight
```

**Notes:**
- Feed IDs are matched exactly against the CSV input
- Feed ID filtering is applied after asset class filtering
- Useful for testing specific feeds without modifying the CSV file

### Overnight Session Support (US Equities)

The `publisher_benchmark.py` script supports evaluation of US equities during the overnight session (8 PM - 4 AM ET). Unlike extended hours which use Datascope as benchmark, **overnight uses publisher 32 (Blue Ocean ATS) as the reference**.

```bash
# Include overnight session evaluation
python publisher_benchmark.py --csv publisher_55_feeds.csv --overnight

# Combine with extended hours for full 24-hour coverage
python publisher_benchmark.py --csv publisher_55_feeds.csv --extended-hours --overnight
```

**Trading Sessions:**

| Session | Time (EST) | Benchmark Source | Flag Required |
|---------|-----------|------------------|---------------|
| Regular Hours | 9:30 AM - 4:00 PM | Datascope | Always evaluated |
| Pre-market | 4:00 AM - 9:30 AM | Datascope | `--extended-hours` |
| After-hours | 4:00 PM - 8:00 PM | Datascope | `--extended-hours` |
| Overnight | 8:00 PM - 4:00 AM | Publisher 32 | `--overnight` |

**Important Caveats:**

- **Not an official benchmark:** Publisher 32 is another data provider, not a regulated exchange feed like Datascope
- **Publisher-vs-publisher comparison:** Metrics show deviation from publisher 32, not from an authoritative source
- **Circular validation risk:** If publisher 32 has errors, all comparisons will be affected
- Cannot evaluate publisher 32 against itself (will show error in results)

**Overnight Output:**

When `--overnight` is enabled, the CSV output includes additional columns:
- `overnight_n_observations`, `overnight_n_reference_observations`
- `overnight_nrmse`, `overnight_hit_rate`, `overnight_passes`
- `overnight_reference_publisher_id`, `overnight_error`

The console summary includes a separate "OVERNIGHT SESSION" section with aggregate statistics.

**Why Publisher 32?**

Publisher 32 (Blue Ocean ATS) provides overnight US equity data when Datascope is not available. This enables comparison of overnight data quality across publishers, even though it's a peer comparison rather than an official benchmark.

## Publisher Performance Portal (Self-Service API)

Located in `portal/` directory. FastAPI-based REST API for publishers to view their benchmark performance.

### Running the Test API

```bash
# Start test server with mock data (4 test publishers: 11, 32, 55, 99)
python portal/test_api.py
```

**Troubleshooting: Server won't start / shuts down immediately**

If you see `[Errno 98] address already in use`, port 8000 is occupied:
```bash
# Kill existing process on port 8000
fuser -k 8000/tcp

# Then restart
python portal/test_api.py
```

### API Endpoints

| Endpoint | Description |
|----------|-------------|
| `GET /health` | Health check |
| `GET /docs` | Interactive Swagger docs |
| `GET /publishers/` | List all publishers with summary stats |
| `GET /publishers/{id}/summary` | Publisher daily summary |
| `GET /publishers/{id}/feeds` | Publisher's feed results (filter with `?passes=false`) |
| `GET /leaderboard/` | Publisher rankings |
| `GET /feeds/` | List all feeds |

### Test Data

The test server creates:
- 4 publishers (IDs: 11, 32, 55, 99)
- 6 feeds (EUR/USD, GBP/USD, XAU/USD, AAPL, MSFT, GOOGL)
- 7 days of benchmark results
- Database: `test_benchmark.db` (SQLite)
