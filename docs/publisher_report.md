# Publisher Health Report

`publisher_report.py` combines benchmark quality evaluation and uptime measurement into a unified health view per feed for a single publisher.

## Health Classification

Each feed is classified based on benchmark pass/fail and uptime:

| Status | Condition | Meaning |
|--------|-----------|---------|
| **HEALTHY** | Benchmark passes AND uptime >= threshold | Feed is production-ready |
| **DEGRADED** | One of benchmark or uptime fails, but not both | Feed needs attention |
| **FAILING** | Benchmark fails AND uptime < threshold | Feed has serious issues |

Default uptime threshold: 95%.

## Usage

```bash
# CSV mode (reads publisher ID from filename pattern)
python publisher_report.py --csv publisher_55_feeds.csv

# Single-feed mode
python publisher_report.py --publisher-id 55 --feed-id 327 --date 2026-02-17 --mode fx

# Multiple feeds × dates
python publisher_report.py --publisher-id 55 --feed-id 327 328 --date 2026-02-17 2026-02-18 --mode us-equities

# Date range
python publisher_report.py --publisher-id 55 --feed-id 327 --start-date 2026-02-10 --end-date 2026-02-14 --mode fx

# With extended hours and overnight
python publisher_report.py --csv publisher_55_feeds.csv --extended-hours --overnight

# Custom uptime threshold
python publisher_report.py --csv publisher_55_feeds.csv --uptime-threshold 99.0

# Skip statistical tests for faster execution
python publisher_report.py --csv publisher_55_feeds.csv --skip-scipy-tests
```

## Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--csv` | CSV with `feed_id,date,mode` columns | - |
| `--publisher-id` | Publisher ID (required in single-feed mode) | - |
| `--feed-id` | Feed ID(s) to filter | - |
| `--date` | Date(s) `YYYY-MM-DD` | - |
| `--start-date` / `--end-date` | Inclusive date range | - |
| `--mode` | Asset class (single-feed mode) | - |
| `--output` | Output CSV path | Auto-generated |
| `--workers` | Parallel workers | `4` |
| `--uptime-threshold` | Minimum uptime % for HEALTHY | `95.0` |
| `--extended-hours` | Include premarket + afterhours (US equities) | Off |
| `--overnight` | Include overnight session (US equities) | Off |
| `--skip-scipy-tests` | Skip statistical tests for faster runs | Off |
| `--include-asset-class` | Only these classes (CSV mode) | All |
| `--exclude-asset-class` | Exclude these classes (CSV mode) | None |
| `--list-asset-classes` | List asset classes in CSV and exit | Off |

## How It Works

1. Runs benchmark evaluation (via `publisher_benchmark_95.py`) for each feed
2. Computes uptime using 1-second window method per trading session
3. Merges results into `FeedHealthResult` with health classification
4. Outputs console report + CSV

## Console Report Sections

1. **Executive Summary** — overall HEALTHY/DEGRADED/FAILING counts, benchmark pass rate, median NRMSE, uptime stats
2. **Feeds Needing Attention** — non-HEALTHY feeds with diagnostics (bias, outliers, low uptime)
3. **All Feeds** — full table with symbol, status, benchmark pass, NRMSE, uptime %
4. **Action Items** — what to fix based on DEGRADED/FAILING patterns

## CSV Output

Per-feed columns:
- `publisher_id`, `feed_id`, `date`, `mode`, `symbol`
- `health_status` (HEALTHY / DEGRADED / FAILING)
- `passes` (benchmark), `nrmse`, `hit_rate`, `n_observations`
- `uptime_pct`, `seconds_with_data`, `total_seconds`, `updates_per_second`
- Statistical diagnostics: `mean_diff`, `t_pvalue`, `normality_pvalue`, `mean_abs_z_score`
- Extended hours (optional): `premarket_*`, `afterhours_*`, `overnight_*`
- `error`, `execution_time_ms`

A `SUMMARY` section is appended with aggregate statistics.

## Uptime Method

Uses the **1-second window** method: counts seconds with at least one publisher update. This matches the portal dashboard calculation.

Trading sessions (US equities):

| Session | Time (EST) | Flag |
|---------|-----------|------|
| Regular | 9:30 AM - 4:00 PM | Always |
| Premarket | 4:00 AM - 9:30 AM | `--extended-hours` |
| Afterhours | 4:00 PM - 8:00 PM | `--extended-hours` |
| Overnight | 8:00 PM - 4:00 AM | `--overnight` |

FX, metals, commodity, and us-treasuries use a 24-hour regular session.

## Running Tests

```bash
pytest tests/test_publisher_report.py -v
```
