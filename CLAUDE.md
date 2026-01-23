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

Modes: `fx`, `metals`, `us-equities`

## Output

Results CSV contains:
- `feed_id`, `date`, `mode`, `symbol`
- `ready` (boolean)
- `passing_pub_count`, `failing_pub_count`
- `passing_publishers`, `failing_publishers` (semicolon-separated IDs)
- `error` (if any)
- `execution_time_ms`
