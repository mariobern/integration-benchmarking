# Publisher Performance Portal: Usage Guide

This document explains how to run and use the Publisher Performance Portal dashboard.

---

## Prerequisites

- Python environment with dependencies installed (`pip install -r requirements.txt`)
- `config.yaml` configured with ClickHouse and Postgres credentials

---

## Running the Dashboard

### 1. Start the API Server

From the repo root:

```bash
uvicorn portal.api.main:app --reload --host 0.0.0.0 --port 8000
```

### 2. Open the Dashboard

Navigate to:

```
http://localhost:8000/ui/dashboard.html
```

### 3. Using the Dashboard

1. Select a **Publisher ID** from the dropdown
2. Optionally select a **Date** (defaults to latest available)
3. View the summary cards showing:

   - Pass Rate
   - Median NRMSE
   - Median Uptime
   - Total Feeds

4. Use the tabs to switch between:
   - **Benchmark** - Feed-level benchmark results
   - **Uptime** - Feed-level uptime metrics
   - **Trends** - Historical charts (requires Chart.js)
   - **Alerts** - Failing feeds and low uptime warnings

---

## API Endpoints

### Dashboard Summary

```
GET /publishers/{publisher_id}/dashboard
GET /publishers/{publisher_id}/dashboard?target_date=2025-01-25
```

Returns combined benchmark + uptime metrics for a publisher.

### Benchmark Trend

```
GET /benchmarks/trend/benchmark?publisher_id=55&days=30&metric=pass_rate_pct
```

Metrics: `pass_rate_pct`, `median_nrmse`, `median_hit_rate`, `total_feeds`

### Uptime Trend

```
GET /benchmarks/trend/uptime?publisher_id=55&days=30&session=regular
```

Sessions: `regular`, `premarket`, `afterhours`, `overnight`, `overall`

### Per-Feed Uptime

```
GET /benchmarks/uptime?publisher_id=55&target_date=2025-01-25
```

---

## Running the Daily Batch

To populate data for the dashboard:

```bash
python -m portal.batch.daily_benchmark_runner
```

The batch runner discovers publishers and their feeds based on the **target date** — it queries `publisher_updates` for all publishers that actually published on that day and the feeds they published. By default, the target date is yesterday.

Options:

```bash
# Specific date (discovers publishers/feeds active on that date)
python -m portal.batch.daily_benchmark_runner --date 2025-01-25

# Specific publisher
python -m portal.batch.daily_benchmark_runner --publisher-id 55

# Include overnight session (US equities, uses publisher 32 as reference)
python -m portal.batch.daily_benchmark_runner --date 2025-01-25 --overnight

# Skip extended hours (faster)
python -m portal.batch.daily_benchmark_runner --date 2025-01-25 --no-extended-hours

# Dry run (no database writes)
python -m portal.batch.daily_benchmark_runner --dry-run
```

---

## Test Mode

To run with mock data (no database required):

```bash
python portal/test_api.py
```

This starts a server with sample publishers (IDs: 11, 32, 55, 99) and 7 days of test data.

---

## Uptime Calculation

The portal calculates uptime using a **200ms gap-based method**:

### How It Works

1. Orders all publisher updates by timestamp
2. Calculates the gap between each consecutive update
3. Any gap > 200ms contributes to downtime: `downtime += (gap - 200ms)`
4. Accounts for gaps at period start (first update) and end (last update)

### Why 200ms?

Publishers are expected to send updates multiple times per second. A gap > 200ms indicates a missed update cycle. This method is more accurate than simple "seconds with data" counting, which can show 100% uptime even when there are significant sub-second gaps.

### Metrics Provided

| Metric                | Description                             |
| --------------------- | --------------------------------------- |
| `uptime_pct`          | Percentage uptime (0-100)               |
| `downtime_ms`         | Total downtime in milliseconds          |
| `max_gap_ms`          | Maximum gap between consecutive updates |
| `gaps_over_threshold` | Count of gaps exceeding 200ms           |

### Verifying Uptime

Use the `verify_uptime.py` script to compare calculation methods:

```bash
# Basic verification
python verify_uptime.py --publisher-id 55 --date 2026-01-28

# Include extended hours
python verify_uptime.py --publisher-id 55 --date 2026-01-28 --extended-hours

# Export to CSV
python verify_uptime.py --publisher-id 55 --date 2026-01-28 --output results.csv
```

The script compares:

- **1-second window method** (legacy) - counts seconds with at least one update
- **200ms gap-based method** (current) - measures actual gaps between updates
