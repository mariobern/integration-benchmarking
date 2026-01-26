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
python quick_benchmark.py --csv feeds.csv --exclude-asset-class crypto funding-rate rates
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

Asset classes WITHOUT benchmark data (will error):
- `crypto` - Cryptocurrency
- `crypto-redemption-rate` - Crypto redemption rates
- `funding-rate` - Funding rates
- `rates` - Interest rates
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
