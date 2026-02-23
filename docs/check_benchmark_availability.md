# Benchmark Availability Checker

Discovers and tracks all instruments available in Datascope benchmark tables.

## When to Use

| Scenario                                 | Use This Tool                        |
| ---------------------------------------- | ------------------------------------ |
| See what instruments have benchmark data | Yes                                  |
| Track benchmark coverage over time       | Yes                                  |
| Find pyth_lazer_id for a specific RIC    | Yes                                  |
| Audit benchmark data availability        | Yes                                  |
| Run benchmarks against Datascope         | Use `publisher_benchmark.py` instead |

## Usage

```bash
# Run with defaults (outputs to benchmark_availability/)
python check_benchmark_availability.py

# Custom output directory
python check_benchmark_availability.py --output-dir my_output/

# Custom date label (for tracking purposes)
python check_benchmark_availability.py --date 2026-01-15
```

## Arguments

| Argument       | Description                          | Default                   |
| -------------- | ------------------------------------ | ------------------------- |
| `--output-dir` | Directory for output files           | `benchmark_availability/` |
| `--date`       | Date label for tracking (YYYY-MM-DD) | Today                     |

## Output Files

The script generates three output files:

### 1. SUMMARY.md

Human-readable summary with instrument counts and breakdowns:

```markdown
# Datascope Benchmark Data Availability

Last updated: 2026-02-05

## Summary

| Asset Class   | Instruments | Earliest   | Latest     |
| ------------- | ----------- | ---------- | ---------- |
| Us Equities   | 620         | 2025-08-22 | 2026-02-04 |
| Fx            | 74          | 2025-09-08 | 2026-02-04 |
| Futures       | 22          | 2025-11-06 | 2026-02-04 |
| Us Treasuries | 10          | 2025-12-01 | 2026-02-04 |

**Total: 726 instruments**

## US Equities Breakdown

- NYSE: 424
- NASDAQ: 178
  ...
```

### 2. instruments\_{date}.csv

Full instrument list with columns:

| Column            | Description                                           |
| ----------------- | ----------------------------------------------------- |
| `asset_class`     | Asset class (us-equities, fx, futures, us-treasuries) |
| `benchmark_table` | Source Datascope table                                |
| `pyth_lazer_id`   | Pyth Lazer feed ID                                    |
| `ric`             | Reuters Instrument Code                               |
| `earliest_date`   | First date with benchmark data                        |
| `latest_date`     | Most recent date with benchmark data                  |

Example:

```csv
asset_class,benchmark_table,pyth_lazer_id,ric,earliest_date,latest_date
us-equities,datascope_global_equities_benchmark_data,500,AAPL.O,2025-08-22,2026-02-04
fx,datascope_fx_benchmark_data,327,EUR=,2025-09-08,2026-02-04
```

### 3. history.csv

Append-only log for tracking availability over time:

| Column             | Description                 |
| ------------------ | --------------------------- |
| `check_date`       | Date the check was run      |
| `asset_class`      | Asset class                 |
| `instrument_count` | Number of instruments found |
| `earliest_date`    | Earliest data date          |
| `latest_date`      | Latest data date            |

Each run appends 4 rows (one per asset class), enabling trend analysis.

## Benchmark Tables

The script queries these Datascope tables:

| Table                                      | Asset Class   | Includes                                        |
| ------------------------------------------ | ------------- | ----------------------------------------------- |
| `datascope_global_equities_benchmark_data` | us-equities   | US stocks (NYSE, NASDAQ, etc.)                  |
| `datascope_fx_benchmark_data`              | fx            | FX pairs + Precious metals (XAU, XAG, XPT, XPD) |
| `datascope_futures_benchmark_data`         | futures       | Equity index & commodity futures                |
| `datascope_us_treasury_benchmark_data`     | us-treasuries | Treasury yields (1M to 30Y)                     |

## Git Tracking

The `.gitignore` is configured to:

- **Track:** `SUMMARY.md`, `history.csv` (committed to repo)
- **Ignore:** `instruments_*.csv` (regenerated on each run)

## Example Workflow

```bash
# 1. Check current availability
python check_benchmark_availability.py

# 2. View summary
cat benchmark_availability/SUMMARY.md

# 3. Find a specific instrument
grep "AAPL" benchmark_availability/instruments_2026-02-05.csv

# 4. Track changes over time
cat benchmark_availability/history.csv
```

## Requirements

- `config.yaml` with `analytics_clickhouse` credentials
- Python packages: `clickhouse-connect`, `pyyaml`

## Related Tools

- [Asset Classes](./asset-classes.md) - Supported asset class reference
- [Publisher Benchmark](./publisher_benchmark.md) - Run benchmarks against Datascope data
- [Quick Benchmark](./quick_benchmark.md) - Fast feed readiness checks
