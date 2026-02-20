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

# Multiple feed IDs (cartesian product with dates)
python quick_benchmark.py --feed-id 327 328 329 --date 2025-10-06 --mode fx

# Multiple feed IDs × multiple dates
python quick_benchmark.py --feed-id 327 328 --date 2025-10-06 2025-10-07 --mode fx

# Date range (all calendar days between start and end)
python quick_benchmark.py --feed-id 327 --start-date 2025-10-01 --end-date 2025-10-06 --mode fx

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
| `--feed-id` | Feed ID(s) to evaluate (one or more) | - |
| `--date` | Date(s) for feed evaluation (YYYY-MM-DD, one or more) | - |
| `--start-date` | Range start date (inclusive, YYYY-MM-DD) | - |
| `--end-date` | Range end date (inclusive, YYYY-MM-DD) | - |
| `--mode` | Market type: `fx`, `metals`, `us-equities` | - |
| `--output` | Output CSV path | `quick_benchmark_results.csv` |
| `--target-pub-count` | Min publishers for feed readiness | 4 |
| `--workers` | Parallel workers for processing | 4 |
| `--include-asset-class` | Only process these asset classes (CSV mode) | - |
| `--exclude-asset-class` | Skip these asset classes (CSV mode) | - |
| `--list-asset-classes` | List unique asset classes in CSV and exit | - |
| `--extended-hours` | Include pre-market and after-hours (US equities) | False |
| `--overnight` | Include overnight session vs publisher 32 | False |
| `--skip-scipy-tests` | Skip statistical tests for faster runs | False |
| `--detailed` | Output per-publisher detailed rows | False |
| `--filter-feed-id` | Filter CSV to specific feed IDs | - |

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

## Feed Readiness

`feed_readiness.py` evaluates **combined feed readiness** by running both benchmark quality and publisher uptime checks. A feed is marked **READY** only if enough publishers pass **both** checks. This is the primary tool for assessing whether a feed is production-ready.

See [docs/feed_readiness.md](docs/feed_readiness.md) for full output schema and per-session readiness details.

### Running Feed Readiness

```bash
# Single feed, single date
python feed_readiness.py --feed-id 327 --date 2026-02-10 --mode fx

# Multi-date range
python feed_readiness.py --feed-id 327 --start-date 2026-02-10 --end-date 2026-02-14 --mode fx

# CSV batch
python feed_readiness.py --csv price_id_list.csv --workers 8

# With precise uptime + extended hours (US equities)
python feed_readiness.py --feed-id 922 --date 2026-02-10 --mode us-equities --precise --extended-hours

# Include overnight session (US equities)
python feed_readiness.py --feed-id 922 --date 2026-02-10 --mode us-equities --extended-hours --overnight

# Detailed output (publisher rows + cross-date consistency)
python feed_readiness.py --feed-id 327 --start-date 2026-02-10 --end-date 2026-02-14 --mode fx --detailed

# Fast execution (skip statistical tests)
python feed_readiness.py --csv price_id_list.csv --workers 8 --skip-scipy-tests
```

### Feed Readiness Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--csv` | CSV with `feed_id,date,mode` rows | - |
| `--feed-id` | Feed ID(s) (single-feed mode) | - |
| `--date` | Date(s) `YYYY-MM-DD` | - |
| `--start-date` / `--end-date` | Inclusive date range | - |
| `--mode` | Asset class (single-feed mode) | - |
| `--output` | Output CSV path | `feed_readiness_results.csv` |
| `--detailed` | Append publisher detail + consistency sections | Off |
| `--target-pub-count` | Minimum fully-passing publishers for readiness | `4` |
| `--skip-scipy-tests` | Skip benchmark statistical tests for faster runs | Off |
| `--precise` | Use gap-based uptime method instead of 1-second window | Off |
| `--gap-threshold` | Gap threshold in ms for `--precise` mode | `200` |
| `--uptime-threshold` | Regular-session uptime pass threshold | `95.0` |
| `--extended-hours` | Include premarket + afterhours for US equities | Off |
| `--overnight` | Include overnight session for US equities | Off |
| `--workers` | Parallel workers | `4` |
| `--include-asset-class` | Only these classes (CSV mode) | All |
| `--exclude-asset-class` | Exclude these classes (CSV mode) | None |
| `--filter-feed-id` | Only these feed IDs (CSV mode) | All |
| `--list-asset-classes` | List asset classes in CSV and exit | Off |

### Readiness Logic

Per publisher:
- `benchmark_passes`: benchmark pass/fail from quality evaluation
- `uptime_passes`: regular-session uptime above threshold
- `fully_passes`: `benchmark_passes AND uptime_passes`

Per feed:
- `ready`: `fully_passing_count >= target_pub_count`
- `benchmark_ready`: benchmark passing publishers >= target
- `uptime_ready`: regular-session uptime passing publishers >= target

Publisher buckets: `fully_passing`, `benchmark_only`, `uptime_only`, `both_failing`.

### Per-Session Readiness (Extended Hours)

When `--extended-hours` or `--overnight` is enabled, feed readiness is also computed per session (premarket, afterhours, overnight). Each session gets its own:
- `{session}_ready` boolean
- `{session}_fully_passing_count` and `{session}_fully_passing_publishers`
- `{session}_uptime_passing_count`, `{session}_uptime_failing_count`
- `{session}_median_uptime_pct`

The console summary includes a per-session breakdown table showing readiness rates per session.

### Feed Readiness Output

Results CSV includes:
- identity: `feed_id`, `date`, `mode`, `symbol`
- readiness: `ready`, `benchmark_ready`, `uptime_ready`
- counts: `fully_passing_count`, `benchmark_only_passing_count`, `uptime_only_passing_count`, `both_failing_count`
- benchmark metrics: `benchmark_passing_count`, `median_nrmse`, `median_hit_rate`
- uptime metrics: `uptime_passing_count`, `median_uptime_pct`
- publisher lists: `fully_passing_publishers`, `benchmark_only_publishers`, `uptime_only_publishers`, `both_failing_publishers`

With `--detailed`, CSV appends publisher-level detail rows (per publisher per feed/date) and cross-date consistency analysis. Detail rows include regular-session benchmark metrics (`benchmark_nrmse`, `benchmark_hit_rate`, `benchmark_n_observations`) and `uptime_pct`. When `--extended-hours` or `--overnight` is enabled, each session block adds `{session}_benchmark_passes`, `{session}_benchmark_nrmse`, `{session}_benchmark_hit_rate`, `{session}_benchmark_n_observations`, `{session}_uptime_pct`, `{session}_uptime_passes`. For multi-date runs, per-session publisher consistency and classification sections are also appended (premarket/afterhours with `--extended-hours`, overnight with `--overnight`).

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

### Performance Optimization Flags

The `publisher_benchmark.py` script includes flags for faster execution:

```bash
# Skip statistical tests (t-test, Wilcoxon, normality) for faster execution
python publisher_benchmark.py --csv publisher_55_feeds.csv --skip-scipy-tests
```

| Flag | Description | Impact |
|------|-------------|--------|
| `--skip-scipy-tests` | Skip scipy statistical tests | ~30-50% faster execution. Metrics like `t_statistic`, `t_pvalue`, `wilcoxon_statistic`, `wilcoxon_pvalue`, `normality_pvalue` will be null. |

**When to use `--skip-scipy-tests`:**
- Daily batch processing where statistical metrics aren't needed
- Quick validation runs
- When you only need pass/fail results (based on NRMSE and hit rate)

**When NOT to use:**
- Deep quality analysis requiring bias detection
- Investigating specific publisher issues
- When statistical significance of errors matters

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

`publisher_benchmark.py` supports two input modes:

1. CSV mode: `--csv feeds.csv` (optional `--feed-id` filter)
2. Single-feed mode: `--publisher-id`, `--feed-id`, `--date`/`--start-date+--end-date`, and `--mode` (no CSV required)

### Single-Feed Mode (No CSV)

```bash
# Single feed, single date
python publisher_benchmark.py --publisher-id 55 --feed-id 327 --date 2025-10-06 --mode fx

# Multiple feed IDs × multiple dates
python publisher_benchmark.py --publisher-id 55 --feed-id 327 328 --date 2025-10-06 2025-10-07 --mode us-equities

# Date range
python publisher_benchmark.py --publisher-id 55 --feed-id 327 --start-date 2025-10-01 --end-date 2025-10-06 --mode fx
```

**Notes:**
- `--csv` is optional
- In single-feed mode, `--publisher-id` and `--mode` are required
- In single-feed mode, you must provide either `--date` or `--start-date` + `--end-date`
- `--include-asset-class`, `--exclude-asset-class`, and `--list-asset-classes` are CSV-only

### Feed ID Filtering (CSV Mode)

In CSV mode, `--feed-id` filters rows from the CSV input:

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

## Source Upload CSV Generator

`generate_source_upload.py` automates creating `source_upload` CSV files for Datascope instrument onboarding. Given a list of US equity tickers, it resolves each to its Reuters Instrument Code (RIC), company name, and Pyth identifiers.

### Running Source Upload Generator

```bash
# From comma-separated tickers
python generate_source_upload.py --tickers AAPL,NVDA,META

# From a file (one ticker per line or CSV)
python generate_source_upload.py --ticker-file tickers.txt

# Custom output path
python generate_source_upload.py --tickers AAPL,NVDA --output my_upload.csv

# Offline mode (skip ClickHouse, use NASDAQ Trader only)
python generate_source_upload.py --tickers AAPL,NVDA --no-clickhouse

# Force re-download NASDAQ Trader data
python generate_source_upload.py --tickers AAPL --force-refresh
```

### Source Upload Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--tickers` | Comma-separated ticker list | - |
| `--ticker-file` | File with one ticker per line (or CSV) | - |
| `--output` | Output CSV path | `source_upload.csv` |
| `--no-clickhouse` | Skip ClickHouse lookups (offline mode) | False |
| `--us-stocks-path` | Path to US-Stock-Symbols repo | `../US-Stock-Symbols` |
| `--force-refresh` | Re-download NASDAQ Trader data (ignores cache) | False |

### RIC Resolution Strategy

Three-tier resolution (ordered by reliability):

1. **Datascope ClickHouse** (most accurate) — queries `datascope_global_equities_benchmark_data` for existing RICs. This is the exact RIC Datascope uses for benchmarking.
2. **NASDAQ Trader** (offline fallback) — downloads and parses `nasdaqlisted.txt` (all NASDAQ -> `.O`) and `otherlisted.txt` (exchange-specific suffixes). Correct for ~84% of tickers.
3. **Default `.N`** — for tickers not found in any source, defaults to NYSE suffix and flags for manual review.

### Source Upload Output Format

```csv
source_value, source_type, pyth_id, pythnet_id, pyth_lazer_id, valid_from, valid_to, ticker, asset_full_name, asset_class
AAPL.O,RIC,equity.aapl,Equity.US.AAPL/USD,922,,,AAPL,Apple Inc. - Common Stock,Equity
TSM.N,RIC,equity.tsm,Equity.US.TSM/USD,1436,,,TSM,Taiwan Semiconductor Manufacturing Company Ltd.,American Depositary Shares
```

### Edge Cases

- **Dotted tickers** (BRK.B) → RIC uses `BRKb.N` format (lowercase class, no dot)
- **Multiple Datascope RICs** (e.g., TSM.N + TSM.Z) → picks by row count, warns user
- **ADR detection** → classified as "American Depositary Shares" if name contains ADR keywords or country is non-US
- **NASDAQ Trader caching** → files cached in `.nasdaq_cache/` with 24h TTL; `--force-refresh` bypasses

## Universal RIC Mapping Generator

`generate_ric_mapping.py` generates `pyth_mappings_export`-format CSV files for onboarding new tickers into Datascope benchmarking. Given ticker(s), looks them up in `lazer_symbols.json`, derives the Reuters Instrument Code (RIC) using asset-class-specific rules, and outputs a CSV ready for Datascope instrument onboarding. Supports all benchmarkable asset classes.

### Running RIC Mapping Generator

```bash
# Single ticker
python generate_ric_mapping.py --ticker AAPL

# Multiple tickers (all asset classes)
python generate_ric_mapping.py --ticker AAPL EURUSD AUDCAD XAUUSD CCH6 US10Y EMH6

# From a file (one ticker per line or CSV)
python generate_ric_mapping.py --ticker-file new_tickers.txt

# Custom output path
python generate_ric_mapping.py --ticker AAPL --output my_mappings.csv

# Append to existing pyth_mappings file
python generate_ric_mapping.py --ticker AAPL --append-to pyth_mappings_export.csv

# Custom lazer_symbols.json path
python generate_ric_mapping.py --ticker AAPL --symbols after.json

# Force re-download NASDAQ Trader data
python generate_ric_mapping.py --ticker AAPL --force-refresh
```

### RIC Mapping Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--ticker` | Ticker(s) to resolve (space-separated) | - |
| `--ticker-file` | File with tickers (one per line or CSV) | - |
| `--output` | Output CSV path | `ric_mappings.csv` |
| `--symbols` | Path to lazer_symbols.json | `lazer_symbols.json` |
| `--force-refresh` | Re-download NASDAQ Trader data | False |
| `--append-to` | Append to existing CSV instead of creating new | - |

### RIC Resolution Rules

Rule-based resolution engine — no ClickHouse or API dependencies (except NASDAQ Trader for equity exchange suffixes):

| Asset Class | RIC Pattern | Example |
|---|---|---|
| US Equities/ETFs | `TICKER.{EXCHANGE}` via NASDAQ Trader | `AAPL.O`, `JPM.N`, `SPY.P` |
| FX (USD pairs) | Non-USD currency + `=` | `EUR=`, `JPY=`, `AUD=` |
| FX (cross, EUR/GBP) | `BASECCY+QUOTECCY+=` | `EURGBP=`, `GBPJPY=` |
| FX (cross, AUD/NZD/CAD/CHF) | `BASECCY+QUOTECCY+=R` | `AUDCAD=R`, `NZDCHF=R` |
| FX (Dollar Index) | `.DXY` | `.DXY` |
| Metals | Fixed lookup | `XAU=`, `XAG=`, `XPT=`, `XPD=` |
| Rates | `US{TENOR}T=RRPS` | `US10YT=RRPS`, `US3MT=RRPS` |
| Commodity Futures | Pyth→RIC root mapping | `HGH26` (copper), `CLJ26` (WTI) |
| Equity Index Futures | EM→ES, NM→NQ, DM→YM | `ESH26`, `NQH26`, `YMH26` |

### RIC Mapping Output Format

```csv
source_value,source_type,pyth_id,pythnet_id,pyth_lazer_id,valid_from,valid_to,ticker,asset_full_name,asset_class
AAPL.O,RIC,equity.aapl,Equity.US.AAPL/USD,922,1970-01-01 00:00:00,,AAPL,APPLE INC / US DOLLAR,Common Stock
EUR=,RIC,fx.eurusd,FX.EUR/USD,327,1970-01-01 00:00:00,,EURUSD,EURO / US DOLLAR,Forex
HGH26,RIC,future.cch6,Commodities.CCH6/USD,2931,1970-01-01 00:00:00,,CCH6,COPPER 27 MARCH 2026 / US DOLLAR,Commodity Future
```

### Edge Cases

- **Dotted tickers** (BRK.B) → RIC uses `BRKb.N` format (lowercase class, no dot)
- **Duplicate names** in lazer_symbols.json (e.g., AAPL with `.EXT` suffix, AAL as GB and US equity) → prefers US, non-EXT, benchmarkable entries
- **Non-benchmarkable assets** (crypto, funding-rate, nav, etc.) → skipped with warning
- **Non-US equities** (Equity.GB.*, Equity.FR.*) → out of scope, skipped with warning
- **Unknown tickers** → warning with fuzzy match suggestion
- **NASDAQ Trader caching** → files cached in `.nasdaq_cache/` with 24h TTL; `--force-refresh` bypasses
- **Network failures** → gracefully falls back to cached NASDAQ Trader data if available

### Confidence Levels

| Level | Meaning |
|-------|---------|
| `high` | Rule-based derivation (FX, metals, rates, futures) — deterministic |
| `medium` | NASDAQ Trader lookup (US equities) — correct ~84% of the time |
| `low` | Fallback to `.N` suffix — needs manual verification |

### Running Tests

```bash
pytest tests/test_generate_ric_mapping.py -v
```

### Programmatic Usage

```python
from generate_ric_mapping import RICResolver

resolver = RICResolver()
result = resolver.resolve("AAPL")
print(result.ric)          # AAPL.O
print(result.asset_class)  # Common Stock
print(result.confidence)   # medium

# Batch resolve
results = resolver.resolve_batch(["AAPL", "EURUSD", "CCH6", "US10Y"])
```

## ISIN Resolver

`isin_resolver.py` is a standalone utility that resolves ticker symbols to International Securities Identification Numbers (ISINs) using a multi-tier strategy. ISINs provide a universal, unambiguous identifier that can be used to look up the exact primary RIC for any security via the Datascope DSS API.

### Running the ISIN Resolver

```bash
# Resolve tickers from command line
python isin_resolver.py --tickers AAPL,MSFT,TSM,SPY

# Resolve from a file (one ticker per line or CSV)
python isin_resolver.py --ticker-file tickers.txt

# Resolve all tickers from ric.csv (strips exchange suffixes)
python isin_resolver.py --ric-csv ric.csv

# Skip yfinance lookups (faster, offline — Tier 1 only)
python isin_resolver.py --tickers AAPL,MSFT --no-yfinance

# Force re-resolve (ignore cache)
python isin_resolver.py --tickers AAPL --force-refresh

# Output results to CSV
python isin_resolver.py --ric-csv ric.csv --output isins.csv

# Verbose logging
python isin_resolver.py --tickers AAPL -v
```

### ISIN Resolver Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--tickers` | Comma-separated ticker list | - |
| `--ticker-file` | File with tickers (one per line or CSV) | - |
| `--ric-csv` | RIC CSV file (extracts tickers, strips suffix) | - |
| `--output` | Output CSV path | Console only |
| `--no-yfinance` | Skip yfinance lookups (Tier 1 only) | False |
| `--force-refresh` | Ignore cache, re-resolve all | False |
| `--verbose`, `-v` | Enable verbose logging | False |

### Resolution Strategy

Three-tier resolution (ordered by speed):

1. **FinanceDatabase** (Tier 1) — Bulk lookup from 158K+ equity database. Local, instant, free. Covers ~55% of ric.csv tickers. ETFs are NOT covered (no ISIN/CUSIP columns for ETFs in this source).
2. **yfinance** (Tier 2) — Per-ticker Yahoo Finance lookup (~1-2s each). Covers ETFs and many additional equities. Returns `-` for ~96 well-known tickers (BAC, JPM, QQQ, BRK.B, etc.) — known gap.
3. **CUSIP computation** — If Tier 1 provides a CUSIP but no ISIN, computes the ISIN algorithmically via python-stdnum (zero API calls).

**Combined coverage against ric.csv: 86.4%** (612/708 unique tickers). Remaining 13.6% will be covered by Datascope DSS API integration (Phase 2).

### ISIN Resolver Output

Console output includes a resolution summary with per-source counts and ISIN country prefix breakdown.

CSV output (`--output`) contains:
- `ticker`, `isin`, `cusip`, `source`, `company_name`, `exchange`, `warnings`

### Caching

Results are cached in `.isin_cache/isin_map.json` with a 7-day TTL. Use `--force-refresh` to bypass.

### Programmatic Usage

```python
from isin_resolver import ISINResolver

resolver = ISINResolver(use_yfinance=True)
result = resolver.resolve("AAPL")
print(result.isin)       # US0378331005
print(result.cusip)      # 037833100
print(result.source)     # financedatabase

# Batch resolve
results = resolver.resolve_batch(["AAPL", "MSFT", "SPY"])
resolver.save_cache()
```

### Running Tests

```bash
pytest tests/test_isin_resolver.py -v
```

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
| `GET /publishers/{id}/dashboard` | Combined benchmark + uptime dashboard |
| `GET /publishers/{id}/feeds` | Publisher's feed results (filter with `?passes=false`) |
| `GET /publishers/{id}/trends` | Time series trend data |
| `GET /leaderboard/` | Publisher rankings |
| `GET /feeds/` | List all feeds |
| `GET /benchmarks/uptime` | Uptime data with session filters |
| `GET /benchmarks/uptime/summary` | Aggregated uptime by asset class |
| `GET /benchmarks/trend/benchmark` | Historical benchmark metrics |
| `GET /benchmarks/trend/uptime` | Historical uptime metrics |

### Publisher Dashboard (Frontend)

The portal includes a web-based dashboard at `/ui/dashboard.html`:

```bash
# Start the API server
uvicorn portal.api.main:app --reload

# Open dashboard in browser
open http://localhost:8000/ui/dashboard.html
```

**Dashboard Features:**
- Summary cards: Pass rate, median NRMSE, median uptime, total feeds
- Tabs: Benchmark results, Uptime data, Trends (30-day charts), Alerts
- Filtering: By publisher, date, asset class, pass/fail status
- Pagination for large result sets
- Real-time alerts for failing feeds and low uptime

### Uptime Calculation

The portal tracks publisher uptime using session-aware windows:

| Session | Time (EST) | Asset Classes |
|---------|-----------|---------------|
| Regular | 9:30 AM - 4:00 PM | US Equities |
| Premarket | 4:00 AM - 9:30 AM | US Equities |
| Afterhours | 4:00 PM - 8:00 PM | US Equities |
| Overnight | 8:00 PM - 4:00 AM | US Equities |
| Regular | 24 hours (with maintenance) | FX, Metals |

**Uptime Methodology (200ms Gap-Based):**

The portal uses a **200ms gap-based** calculation method:
- Orders all publisher updates by timestamp
- Calculates gap between each consecutive update
- Any gap > 200ms contributes to downtime: `downtime += (gap - 200ms)`
- Also accounts for gaps at period start (first update) and end (last update)

**Why 200ms threshold?**
- Publishers are expected to send updates frequently (multiple per second)
- A 200ms gap indicates the publisher missed an update cycle
- This is more accurate than 1-second window counting, which can show 100% uptime even when publishers have 500ms+ gaps

**UptimeResult fields:**
- `uptime_pct` - Percentage uptime (0-100)
- `downtime_ms` - Total downtime in milliseconds
- `max_gap_ms` - Maximum gap between consecutive updates
- `gaps_over_threshold` - Count of gaps exceeding 200ms

**Configurable threshold:**
```python
from portal.batch.uptime_calculator import UptimeCalculator

# Default 200ms threshold
calc = UptimeCalculator()

# Custom threshold (e.g., 100ms for stricter requirement)
calc = UptimeCalculator(gap_threshold_ms=100)
```

### Uptime Verification Script

Use `verify_uptime.py` to compare uptime calculation methods:

```bash
# Verify a publisher's uptime
python verify_uptime.py --publisher-id 55 --date 2026-01-28

# Include extended hours sessions
python verify_uptime.py --publisher-id 55 --date 2026-01-28 --extended-hours

# Export results to CSV
python verify_uptime.py --publisher-id 55 --date 2026-01-28 --output results.csv
```

The script compares:
- **1-second window method** - Counts seconds with at least one update (legacy)
- **200ms gap-based method** - Measures actual gaps between updates (current)

This helps identify publishers with inflated uptime numbers from the legacy method.

### Running Tests

```bash
# Run all portal tests
pytest portal/tests/ -v

# Run specific test file
pytest portal/tests/test_uptime_calculator.py -v
pytest portal/tests/test_dashboard_api.py -v
```

### Test Data

The test server creates:
- 4 publishers (IDs: 11, 32, 55, 99)
- 6 feeds (EUR/USD, GBP/USD, XAU/USD, AAPL, MSFT, GOOGL)
- 7 days of benchmark results
- Database: `test_benchmark.db` (SQLite)

### Running Daily Benchmark Batch (Production)

To populate the portal database with benchmark and uptime data for all publishers:

```bash
# Activate virtual environment
source venv/bin/activate

# Run batch for a specific date (yesterday by default)
python -m portal.batch.daily_benchmark_runner --date 2026-01-30 --overnight --workers 16

# Fast batch with all optimizations (recommended for production)
python -m portal.batch.daily_benchmark_runner --date 2026-01-30 --overnight --workers 16 --discovery-workers 8 --skip-scipy-tests

# Dry run (don't store results)
python -m portal.batch.daily_benchmark_runner --date 2026-01-30 --dry-run

# Run for specific publisher only
python -m portal.batch.daily_benchmark_runner --date 2026-01-30 --publisher-id 55

# Skip extended hours (faster)
python -m portal.batch.daily_benchmark_runner --date 2026-01-30 --no-extended-hours
```

**Performance Optimization Flags:**

| Flag | Description | Default |
|------|-------------|---------|
| `--discovery-workers` | Parallel workers for feed discovery phase | 8 |
| `--skip-scipy-tests` | Skip statistical tests for faster benchmark execution | False |

**Optimization impact:**
- `--discovery-workers 8`: Parallelizes feed discovery across publishers, reducing discovery time from sequential (~40s per publisher) to parallel (~10s total)
- `--skip-scipy-tests`: Skips t-test, Wilcoxon, and normality tests, reducing per-feed benchmark time by ~30-50%

**What it does:**
1. Discovers all active publishers from ClickHouse (last 60 minutes of activity via `feed_publisher_junction`)
2. For each publisher:
   - Generates feed list via `publisher_feeds.py`
   - Runs `publisher_benchmark.py` with all benchmarkable asset classes
   - Computes session-aware uptime via `uptime_runner.py`
   - Stores results in PostgreSQL
   - Computes daily summary aggregates

**Expected duration:**
- Per publisher: 1-10 minutes (depends on feed count)
- All publishers (~40): 60-120 minutes with 16 workers

**Database tables populated:**
- `benchmark_results` - Individual publisher/feed results (~50 metrics)
- `publisher_daily_summary` - Aggregated daily stats per publisher
- `publisher_feed_daily_uptime` - Per-feed uptime by session
- `publisher_daily_uptime_summary` - Aggregated uptime per publisher

**Known issues:**
- Publisher 71 may fail due to infinite t_statistic values - a numeric precision issue with certain edge cases.

## NASDAQ LUDP Trading Halt History

`trading_halt_history.py` downloads Limit Up-Limit Down (LUDP) trading halt data from NASDAQ Trader's public RSS feed. LUDP halts are SEC-mandated circuit breakers that trigger when a stock's price moves beyond its allowable trading band.

### Running the Halt History Downloader

```bash
# Download all LUDP halts from the past year (default: 365 days)
python trading_halt_history.py

# Custom lookback period (e.g., last 30 days)
python trading_halt_history.py --days 30

# Custom output path
python trading_halt_history.py --output my_halts.csv

# Slower request rate (be more polite to the server)
python trading_halt_history.py --delay 0.5
```

### Trading Halt Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--days` | Number of calendar days to look back | 365 |
| `--output` | Output CSV file path | `ludp_halts.csv` |
| `--delay` | Delay between requests in seconds | 0.2 |

### Data Source

- **NASDAQ Trader RSS feed**: `https://www.nasdaqtrader.com/rss.aspx?feed=tradehalts&haltdate=MMDDYYYY`
- Free, public, no authentication required
- One request per business day (~250 requests for a full year)
- Only business days are queried (weekends/holidays return empty feeds)

### How It Works

1. Generates all business days in the lookback period using `pandas.bdate_range()`
2. Fetches the RSS halt feed for each business day
3. Parses the HTML table in each RSS entry to extract halt details
4. Filters for `LUDP` reason code only (ignores other halt types like `M`, `T1`, etc.)
5. Sorts results by date (ascending), then halt time (ascending)
6. Writes to CSV and prints a summary with top halted tickers

### Output CSV Format

```csv
date,ticker,halt_time,resume_time,market
2025-02-10,BOWNU,09:30:18,09:35:18,Q
2025-02-10,BDRX,09:32:52,09:37:52,Q
```

| Column | Description |
|--------|-------------|
| `date` | Halt date (YYYY-MM-DD) |
| `ticker` | Stock symbol |
| `halt_time` | Time halt began (HH:MM:SS ET) |
| `resume_time` | Time trading resumed (HH:MM:SS ET) |
| `market` | Exchange code: Q=NASDAQ, P=NYSE Arca, A=NYSE American, Z=BATS |

### LUDP Halt Reason Codes

The script filters for `LUDP` only. Other common halt reason codes in the feed (excluded):
- `M` — Volatility Trading Pause (Market-Wide Circuit Breaker)
- `T1` — News Pending
- `T2` — News Dissemination
- `T12` — IPO Halt / Additional Information Requested

### Performance

- ~250 requests for a full year at 0.2s delay = ~2-3 minutes total
- Retries failed requests up to 3 times with exponential backoff
- Progress logged every 10 business days

### Typical Results (1 Year)

- ~9,000-10,000 LUDP halts per year
- ~1,200 unique tickers
- Most halts occur in small-cap/micro-cap stocks
- Halts cluster around market open (9:30-10:30 AM ET)

## Publisher Health Report

`publisher_report.py` combines benchmark quality and uptime into a unified per-feed health classification (HEALTHY / DEGRADED / FAILING) for a single publisher. See [docs/publisher_report.md](docs/publisher_report.md) for full details.

```bash
python publisher_report.py --csv publisher_55_feeds.csv
python publisher_report.py --publisher-id 55 --feed-id 327 --date 2026-02-17 --mode fx
```

## Feed Promotion (update_lazer_symbols.py)

`update_lazer_symbols.py` promotes feeds from `COMING_SOON` to `STABLE` in `after.json` using a benchmark summary markdown as input. Sets per-ticker `allowedPublisherIds` and `minPublishers`. See [docs/update_lazer_symbols.md](docs/update_lazer_symbols.md) for full details.

```bash
python3 update_lazer_symbols.py --summary feeds_ready_170226_summary.md --config after.json --dry-run
```

## Benchmark Results Interpretation Guide

`docs/benchmark_results_guide.md` is a standalone guide for publishers explaining how to read and interpret benchmark CSV output. Covers pass/fail criteria, core quality metrics, session breakdowns, and advanced statistical tests. See [docs/benchmark_results_guide.md](docs/benchmark_results_guide.md).
