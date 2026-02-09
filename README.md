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

| Tool | Purpose | Docs |
|------|---------|------|
| `quick_benchmark.py` | Evaluate all publishers for a feed (feed readiness) | [Details](docs/quick_benchmark.md) |
| `publisher_benchmark.py` | Evaluate a single publisher's data quality | [Details](docs/publisher_benchmark.md) |
| `publisher_feeds.py` | Discover feeds a publisher is actively publishing | [Details](docs/publisher_feeds.md) |
| `verify_uptime.py` | Compare uptime calculation methods | [Details](docs/portal_usage.md) |
| `check_benchmark_availability.py` | Audit Datascope instrument coverage | [Details](docs/check_benchmark_availability.md) |
| `generate_source_upload.py` | Generate CSVs for Datascope instrument onboarding | [Details](docs/generate_source_upload.md) |
| `isin_resolver_v2.py` | Resolve tickers to ISINs (multi-tier) | [Details](docs/isin_resolver_v2.md) |
| `portal/` | Self-service FastAPI dashboard + daily batch runner | [Details](docs/portal_usage.md) |

## Publisher Feeds Discovery (`publisher_feeds.py`)

Discovers all feeds a publisher is actively sending data for, outputting a CSV ready for `publisher_benchmark.py`.

```bash
# Discover feeds for publisher 29 (last 60 minutes of activity)
python publisher_feeds.py --publisher-id 29

# Filter to FX only, with date offset for yesterday
python publisher_feeds.py --publisher-id 55 --asset-class fx --date-offset 1
```

**How it works:** Two-tier query strategy — first queries the fast `feed_publisher_junction` materialized view, then falls back to `publisher_updates` if no results. Equity country codes and asset class normalization are handled automatically.

| Argument | Description | Default |
|----------|-------------|---------|
| `--publisher-id` | Publisher ID (required) | - |
| `--output` | Output CSV path | `publisher_{id}_feeds.csv` |
| `--time-window` | Minutes to look for activity | 60 |
| `--asset-class` | Filter by asset class | All |
| `--date-offset` | Days to offset from today | 0 |

See [publisher_feeds.md](docs/publisher_feeds.md) for full details.

## Publisher Benchmark (`publisher_benchmark.py`)

Evaluates a single publisher's data quality across all their feeds by comparing against Datascope benchmarks.

```bash
# Basic benchmark for publisher 55
python publisher_benchmark.py --csv publisher_55_feeds.csv --publisher-id 55

# Full evaluation: extended hours + overnight + fast mode
python publisher_benchmark.py --csv publisher_55_feeds.csv --publisher-id 55 \
  --extended-hours --overnight --skip-scipy-tests
```

**Pass/fail criteria:**
- **PASSES** if: `nrmse < 0.01` **OR** (`nrmse < 0.05` **AND** `hit_rate >= 98%`)

**Key features:**
- Extended hours (`--extended-hours`): pre-market (4-9:30 AM) and after-hours (4-8 PM)
- Overnight (`--overnight`): 8 PM - 4 AM ET, uses publisher 32 (Blue Ocean ATS) as reference
- Feed filtering (`--feed-id 327 1163`): test specific feeds without editing CSV
- Fast mode (`--skip-scipy-tests`): skip t-test/Wilcoxon/normality for ~30-50% speedup

| Argument | Description | Default |
|----------|-------------|---------|
| `--csv` | Feed CSV (feed_id,date,mode) | - |
| `--publisher-id` | Publisher ID (required) | - |
| `--output` | Output CSV path | `publisher_{id}_benchmark_results.csv` |
| `--workers` | Parallel workers | 4 |
| `--extended-hours` | Include pre-market + after-hours | Off |
| `--overnight` | Include overnight session | Off |
| `--skip-scipy-tests` | Skip statistical tests | Off |
| `--feed-id` | Filter to specific feed IDs | All |
| `--include-asset-class` | Only these asset classes | All |
| `--exclude-asset-class` | Skip these asset classes | None |
| `--list-asset-classes` | List asset classes in CSV and exit | - |

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

| Argument | Description | Default |
|----------|-------------|---------|
| `--publisher-id` | Publisher ID (required) | - |
| `--date` | Date YYYY-MM-DD (required) | - |
| `--feed-id` | Filter to specific feed | All |
| `--extended-hours` | Include pre-market + after-hours | Off |
| `--asset-class` | Filter by asset class | All |
| `--output` | Export to CSV | Console only |

See [portal_usage.md](docs/portal_usage.md) for uptime methodology details.

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

## Input CSV Format

CSV with three columns (no header):

```csv
feed_id,date,mode
327,2025-10-06,fx
1163,2025-10-02,us-equities
346,2025-10-02,metals
```

## Asset Classes

| Benchmarkable | Not Benchmarkable |
|---------------|-------------------|
| `fx`, `metals`, `us-equities`, `commodity`, `us-treasuries` | `crypto`, `funding-rate`, `nav`, `crypto-redemption-rate` |

Futures contracts are auto-detected by symbol pattern (e.g., `CCH6`, `EMH6`) and use `datascope_futures_benchmark_data`.

See [Asset Classes](docs/asset-classes.md) for futures support and details.

## Other Tools

| Tool | Purpose |
|------|---------|
| `check_benchmark_availability.py` | Audits Datascope coverage across all benchmark tables. Outputs `SUMMARY.md` + CSV. [Docs](docs/check_benchmark_availability.md) |
| `generate_source_upload.py` | Creates `source_upload` CSVs for Datascope instrument onboarding from ticker lists. [Docs](docs/generate_source_upload.md) |
| `isin_resolver_v2.py` | Resolves tickers to ISINs via manual overrides, FinanceDatabase, yfinance, and OpenFIGI. [Docs](docs/isin_resolver_v2.md) |
| Publisher Portal (`portal/`) | FastAPI self-service dashboard with benchmark results, uptime, trends, and leaderboard. Run daily batch via `portal.batch.daily_benchmark_runner`. [Docs](docs/portal_usage.md) |

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
