# Pyth Lazer Feed Benchmark Tools

Evaluate Pyth Network Lazer publisher data quality against external benchmarks (Datascope). Includes feed discovery, per-publisher benchmarking, uptime verification, and a self-service portal.

## Prerequisites

- Python 3.10+
- ClickHouse database credentials (ask your team lead)

## Quick Start

```bash
# 1. Create and activate virtual environment
python3 -m venv venv
source venv/bin/activate  # Linux/macOS

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure credentials
cp config.yaml.sample config.yaml
# Edit config.yaml with your ClickHouse credentials

# 4. Run a benchmark
python quick_benchmark.py --csv price_id_list.csv
```

## Tools Overview

| Tool                              | Purpose                                                | Docs                                            |
| --------------------------------- | ------------------------------------------------------ | ----------------------------------------------- |
| `quick_benchmark.py`              | Evaluate all publishers for a feed (feed readiness)    | [Details](docs/quick_benchmark.md)              |
| `publisher_benchmark.py`          | Evaluate a single publisher's data quality             | [Details](docs/publisher_benchmark.md)          |
| `publisher_feeds.py`              | Discover feeds a publisher is actively publishing      | [Details](docs/publisher_feeds.md)              |
| `feed_uptime.py`                  | Evaluate per-publisher uptime from a feed-centric view | [Details](docs/feed_uptime.md)                  |
| `feed_readiness.py`               | Combined benchmark + uptime readiness verdict per feed | [Details](docs/feed_readiness.md)               |
| `verify_uptime.py`                | Compare uptime calculation methods                     | [Details](docs/portal_usage.md)                 |
| `check_benchmark_availability.py` | Audit Datascope instrument coverage                    | [Details](docs/check_benchmark_availability.md) |
| `generate_source_upload.py`       | Generate CSVs for Datascope instrument onboarding      | [Details](docs/generate_source_upload.md)       |
| `generate_price_list.py`          | Generate price_id_list.csv from feed IDs               | See below                                       |
| `isin_resolver_v2.py`             | Resolve tickers to ISINs (multi-tier)                  | [Details](docs/isin_resolver_v2.md)             |
| `portal/`                         | Self-service FastAPI dashboard + daily batch runner    | [Details](docs/portal_usage.md)                 |

## Quick Benchmark Notes

- `quick_benchmark.py --detailed` appends a `PUBLISHER DETAIL` section to output CSV.
- With `--detailed` and more than one evaluated date, it also appends `PUBLISHER SUMMARY` (cross-date publisher pass/fail matrix).
- In that same multi-date detailed mode, console output adds `PUBLISHER CONSISTENCY` with per-session PASS/FAIL/ERROR timelines.

## Publisher Feeds Discovery (`publisher_feeds.py`)

Discovers all feeds a publisher is actively sending data for, outputting a CSV ready for `publisher_benchmark.py`.

```bash
# Discover feeds for publisher 29 (last 60 minutes of activity)
python publisher_feeds.py --publisher-id 29 --time-window 60

# Filter to FX only, with date offset for yesterday
python publisher_feeds.py --publisher-id 55 --asset-class fx --date-offset 1

# Emit multiple dates per discovered feed
python publisher_feeds.py --publisher-id 55 --date 2026-02-10 2026-02-11

# Emit a date range per discovered feed
python publisher_feeds.py --publisher-id 55 --start-date 2026-02-10 --end-date 2026-02-12
```

**How it works:** Two-tier query strategy — first queries the fast `feed_publisher_junction` materialized view, then falls back to `publisher_updates` if no results. Equity country codes and asset class normalization are handled automatically.

| Argument         | Description                                         | Default                    |
| ---------------- | --------------------------------------------------- | -------------------------- |
| `--publisher-id` | Publisher ID (required)                             | -                          |
| `--output`       | Output CSV path                                     | `publisher_{id}_feeds.csv` |
| `--time-window`  | Minutes to look for activity                        | 1                          |
| `--asset-class`  | Filter by asset class                               | All                        |
| `--date-offset`  | Days to offset from today                           | 1                          |
| `--date`         | Explicit output date(s), overrides `--date-offset`  | -                          |
| `--start-date`   | Range start date (inclusive), requires `--end-date` | -                          |
| `--end-date`     | Range end date (inclusive), requires `--start-date` | -                          |

See [publisher_feeds.md](docs/publisher_feeds.md) for full details.

## Publisher Benchmark (`publisher_benchmark.py`)

Evaluates a single publisher's data quality across all their feeds by comparing against Datascope benchmarks.

```bash
# Basic benchmark for publisher 55
python publisher_benchmark.py --csv publisher_55_feeds.csv --publisher-id 55

# Full evaluation: extended hours + overnight + fast mode
python publisher_benchmark.py --csv publisher_55_feeds.csv --publisher-id 55 \
  --extended-hours --overnight --skip-scipy-tests

# Override CSV dates with explicit dates
python publisher_benchmark.py --csv publisher_55_feeds.csv --publisher-id 55 \
  --date 2026-02-10 2026-02-11

# Override CSV dates with a date range
python publisher_benchmark.py --csv publisher_55_feeds.csv --publisher-id 55 \
  --start-date 2026-02-10 --end-date 2026-02-12
```

**Pass/fail criteria:**

- **PASSES** if: `nrmse < 0.01` **OR** (`nrmse < 0.05` **AND** `hit_rate >= 98%`)

**Key features:**

- Extended hours (`--extended-hours`): pre-market (4-9:30 AM) and after-hours (4-8 PM)
- Overnight (`--overnight`): 8 PM - 4 AM ET, uses publisher 32 (Blue Ocean ATS) as reference
- Feed filtering (`--feed-id 327 1163`): test specific feeds without editing CSV
- Fast mode (`--skip-scipy-tests`): skip t-test/Wilcoxon/normality for ~30-50% speedup
- Date override (`--date` or `--start-date/--end-date`): ignore CSV date column and evaluate each `(feed_id, mode)` across selected dates

| Argument                | Description                                    | Default                                |
| ----------------------- | ---------------------------------------------- | -------------------------------------- |
| `--csv`                 | Feed CSV (feed_id,date,mode)                   | -                                      |
| `--publisher-id`        | Publisher ID (required)                        | -                                      |
| `--output`              | Output CSV path                                | `publisher_{id}_benchmark_results.csv` |
| `--workers`             | Parallel workers                               | 4                                      |
| `--date`                | Override CSV date column with explicit date(s) | -                                      |
| `--start-date`          | Override CSV date column with range start      | -                                      |
| `--end-date`            | Override CSV date column with range end        | -                                      |
| `--extended-hours`      | Include pre-market + after-hours               | Off                                    |
| `--overnight`           | Include overnight session                      | Off                                    |
| `--skip-scipy-tests`    | Skip statistical tests                         | Off                                    |
| `--feed-id`             | Filter to specific feed IDs                    | All                                    |
| `--include-asset-class` | Only these asset classes                       | All                                    |
| `--exclude-asset-class` | Skip these asset classes                       | None                                   |
| `--list-asset-classes`  | List asset classes in CSV and exit             | -                                      |

See [publisher_benchmark.md](docs/publisher_benchmark.md) for statistical metrics and interpretation.

## Uptime Verification (`verify_uptime.py`)

Compares two uptime calculation methods to identify publishers with inflated numbers from the legacy approach.

```bash
# Verify publisher 55's uptime for a specific date
python verify_uptime.py --publisher-id 55 --date 2026-01-28

# Include extended hours and export to CSV
python verify_uptime.py --publisher-id 55 --date 2026-01-28 --extended-hours --output results.csv
```

**Why two methods?** The legacy 1-second window method counts seconds with at least one update, which can show 100% uptime even when publishers have 500ms+ gaps. The 200ms gap-based method measures actual gaps between consecutive updates — any gap > 200ms contributes to downtime, catching sub-second issues the window method misses.

| Argument           | Description                      | Default      |
| ------------------ | -------------------------------- | ------------ |
| `--publisher-id`   | Publisher ID (required)          | -            |
| `--date`           | Date YYYY-MM-DD (required)       | -            |
| `--feed-id`        | Filter to specific feed          | All          |
| `--extended-hours` | Include pre-market + after-hours | Off          |
| `--asset-class`    | Filter by asset class            | All          |
| `--output`         | Export to CSV                    | Console only |

See [portal_usage.md](docs/portal_usage.md) for uptime methodology details.

## Feed Uptime (`feed_uptime.py`)

Evaluates uptime from a **feed-centric** perspective: for each feed/date/mode, it discovers all contributing publishers and computes per-publisher/session uptime.

```bash
# Process feeds from CSV
python feed_uptime.py --csv price_id_list.csv

# Single feed/date
python feed_uptime.py --feed-id 922 --date 2026-02-09 --mode us-equities

# Multi-date range
python feed_uptime.py --feed-id 922 --start-date 2026-02-09 --end-date 2026-02-12 --mode us-equities

# US equities session flags
python feed_uptime.py --feed-id 922 --date 2026-02-09 --mode us-equities --extended-hours --overnight

# Threshold options
python feed_uptime.py --csv feeds.csv --uptime-threshold 95
python feed_uptime.py --csv feeds.csv --precise --gap-threshold 100
```

**Key behavior:**

- Default method is `1s window` uptime.
- `--precise` switches to gap-based uptime (default threshold `200ms`).
- `--uptime-threshold` controls pass/fail classification (default `95.0`).
- Supports CSV filtering with `--include-asset-class`, `--exclude-asset-class`, and `--filter-feed-id`.
- Writes long-format per-publisher rows and appends a `PUBLISHER SUMMARY` matrix for multi-date runs.

See [feed_uptime.md](docs/feed_uptime.md) for full usage and output details.

## Feed Readiness (`feed_readiness.py`)

Evaluates feed readiness using **both** benchmark quality and regular-session uptime.
A feed is marked ready only when enough publishers pass both checks.

```bash
# Single feed/date
python feed_readiness.py --feed-id 327 --date 2026-02-10 --mode fx

# Multi-date combined readiness
python feed_readiness.py --feed-id 327 --start-date 2026-02-10 --end-date 2026-02-12 --mode fx

# CSV batch
python feed_readiness.py --csv price_id_list.csv --output feed_readiness_results.csv --workers 8
```

See [feed_readiness.md](docs/feed_readiness.md) for full usage and output details.

## End-to-End Workflow

```bash
# 1. Discover feeds for a publisher
python publisher_feeds.py --publisher-id 55 --date-offset 1

# 2. Benchmark data quality
python publisher_benchmark.py --csv publisher_55_feeds.csv --publisher-id 55 --extended-hours --overnight

# 3. Verify uptime
python verify_uptime.py --publisher-id 55 --date 2026-01-28 --extended-hours

# 4. Run daily batch to populate portal (production)
python -m portal.batch.daily_benchmark_runner --date 2026-01-28 --overnight --workers 16
```

## Generating Input CSVs (`generate_price_list.py`)

Generates `price_id_list.csv` from feed IDs by resolving each feed's asset class from `lazer_symbols.json`. No ClickHouse connection needed.

```bash
# Single date
python3 generate_price_list.py --feed-id 327 340 346 --date 2026-02-27

# Date range (one row per feed per date)
python3 generate_price_list.py --feed-id 327 340 --start-date 2026-02-24 --end-date 2026-02-27

# Feed IDs from file
python3 generate_price_list.py --feed-ids-file feeds.txt --date 2026-02-27

# Custom output and symbols paths
python3 generate_price_list.py --feed-id 327 --date 2026-02-27 --output my_batch.csv --symbols lazer_symbols1.json
```

| Argument          | Description                               | Default              |
| ----------------- | ----------------------------------------- | -------------------- |
| `--feed-id`       | Space-separated feed IDs                  | -                    |
| `--feed-ids-file` | Text file with one feed ID per line       | -                    |
| `--date`          | Single date (YYYY-MM-DD)                  | -                    |
| `--start-date`    | Start of date range (requires --end-date) | -                    |
| `--end-date`      | End of date range (requires --start-date) | -                    |
| `--output`        | Output CSV path                           | `price_id_list.csv`  |
| `--symbols`       | Path to lazer_symbols.json                | `lazer_symbols.json` |

Non-benchmarkable feeds (crypto, nav, etc.) and non-US equities are automatically skipped with warnings.

## Input CSV Format

CSV with three columns (no header):

```csv
feed_id,date,mode
327,2025-10-06,fx
1163,2025-10-02,us-equities
346,2025-10-02,metals
```

## Asset Classes

| Benchmarkable                                               | Not Benchmarkable                                         |
| ----------------------------------------------------------- | --------------------------------------------------------- |
| `fx`, `metals`, `us-equities`, `commodity`, `us-treasuries` | `crypto`, `funding-rate`, `nav`, `crypto-redemption-rate` |

Futures contracts are auto-detected by symbol pattern (e.g., `CCH6`, `EMH6`) and use `datascope_futures_benchmark_data`.

See [Asset Classes](docs/asset-classes.md) for futures support and details.

## Other Tools

| Tool                              | Purpose                                                                                                                                                                         |
| --------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `check_benchmark_availability.py` | Audits Datascope coverage across all benchmark tables. Outputs `SUMMARY.md` + CSV. [Docs](docs/check_benchmark_availability.md)                                                 |
| `generate_source_upload.py`       | Creates `source_upload` CSVs for Datascope instrument onboarding from ticker lists. [Docs](docs/generate_source_upload.md)                                                      |
| `isin_resolver_v2.py`             | Resolves tickers to ISINs via manual overrides, FinanceDatabase, yfinance, and OpenFIGI. [Docs](docs/isin_resolver_v2.md)                                                       |
| Publisher Portal (`portal/`)      | FastAPI self-service dashboard with benchmark results, uptime, trends, and leaderboard. Run daily batch via `portal.batch.daily_benchmark_runner`. [Docs](docs/portal_usage.md) |

## Database Configuration

Requires two ClickHouse clusters configured in `config.yaml`:

- **`lazer_clickhouse_prod`** — Lazer production cluster (publisher data, feed metadata)
- **`analytics_clickhouse`** — Analytics cluster (Datascope benchmark data)

Copy `config.yaml.sample` and fill in your credentials.

## Troubleshooting

See [Troubleshooting Guide](docs/troubleshooting.md) for common issues.

**Quick fixes:**

- `config.yaml not found` → `cp config.yaml.sample config.yaml`
- `EOF occurred in violation of protocol` → Check hostname in config.yaml
- `No benchmark data found` → Use `--list-asset-classes` to check availability
