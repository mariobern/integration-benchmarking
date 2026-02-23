# Plan: `feed_uptime.py` - Feed-Centric Uptime Measurement Script

## Context

Currently, `verify_uptime.py` is **publisher-centric**: given a publisher, it discovers feeds and measures that publisher's uptime. There's no tool to answer "for a given feed, how is each contributing publisher performing in terms of uptime?" across multiple feeds and asset classes.

This new script inverts the perspective: given feeds, discover all publishers per feed and measure each one's uptime. Includes a publisher consistency summary matrix for multi-date runs.

## What Gets Created

Single new file: `/home/mariobern/integration-benchmarking/feed_uptime.py`

## CLI Arguments

Follows the exact patterns from `quick_benchmark.py` / `publisher_benchmark.py`:

```bash
# CSV mode (same format: feed_id,date,mode)
python feed_uptime.py --csv price_id_list.csv

# Single-feed mode
python feed_uptime.py --feed-id 922 --date 2026-02-09 --mode us-equities

# Multi-date
python feed_uptime.py --feed-id 922 --start-date 2026-02-09 --end-date 2026-02-12 --mode us-equities

# Session flags (US equities only)
python feed_uptime.py --feed-id 922 --date 2026-02-09 --mode us-equities --extended-hours --overnight

# Asset class filtering (CSV mode)
python feed_uptime.py --csv feeds.csv --include-asset-class us-equities fx
python feed_uptime.py --csv feeds.csv --exclude-asset-class crypto
python feed_uptime.py --csv feeds.csv --list-asset-classes

# Control
python feed_uptime.py --csv feeds.csv --output results.csv --workers 8
python feed_uptime.py --csv feeds.csv --uptime-threshold 95
python feed_uptime.py --csv feeds.csv --filter-feed-id 922 327

# Precise mode (200ms gap-based instead of default 1-second window)
python feed_uptime.py --feed-id 922 --date 2026-02-09 --mode us-equities --precise
python feed_uptime.py --csv feeds.csv --precise --gap-threshold 100
```

| Argument                      | Description                            | Default                   |
| ----------------------------- | -------------------------------------- | ------------------------- |
| `--csv`                       | CSV with feed_id,date,mode             | -                         |
| `--feed-id`                   | Feed ID(s)                             | -                         |
| `--date`                      | Date(s) YYYY-MM-DD                     | -                         |
| `--start-date` / `--end-date` | Date range (inclusive)                 | -                         |
| `--mode`                      | Asset class (single-feed mode)         | -                         |
| `--output`                    | Output CSV                             | `feed_uptime_results.csv` |
| `--workers`                   | Parallel workers                       | 4                         |
| `--include-asset-class`       | Only these (CSV mode)                  | -                         |
| `--exclude-asset-class`       | Skip these (CSV mode)                  | -                         |
| `--list-asset-classes`        | List and exit                          | -                         |
| `--filter-feed-id`            | Filter CSV to these feeds              | -                         |
| `--extended-hours`            | Premarket + afterhours                 | False                     |
| `--overnight`                 | Overnight session                      | False                     |
| `--precise`                   | Use 200ms gap-based method             | False (uses 1s window)    |
| `--gap-threshold`             | Gap threshold in ms (with `--precise`) | 200                       |
| `--uptime-threshold`          | Pass threshold %                       | 95.0                      |

## Core Data Flow

```
Input (CSV or CLI args)
    |
    v
Build work list: [(feed_id, date, mode), ...]
    |
    v
ThreadPoolExecutor (--workers)
    |
    +-- For each (feed_id, date, mode):
    |   1. Get symbol from feeds_metadata_latest
    |   2. Discover publishers: SELECT DISTINCT publisher_id FROM publisher_updates
    |   3. Get session windows via uptime_sessions.get_session_windows(mode, date)
    |   4. Filter sessions based on --extended-hours / --overnight
    |   5. For each publisher x session: compute uptime (1s window or 200ms gap)
    |   6. Determine pass/fail per uptime_threshold
    |   7. Return FeedUptimeResult
    |
    v
Write CSV (detail rows + publisher summary matrix) + print console summary
```

## Uptime Calculation Methods

- **Default: 1-second window** — `uptime% = seconds_with_data / total_seconds`. Simpler, consistent with portal batch runner. Copied from `verify_uptime.py:126-186`.
- **`--precise`: 200ms gap-based** — More accurate for sub-second gaps. Adds extra columns (`max_gap_ms`, `gaps_over_threshold`). Copied from `verify_uptime.py:189-302`. `--gap-threshold` (default 200ms) controls detection.

## Data Structures

```python
@dataclass(frozen=True)
class PublisherSessionUptime:
    publisher_id: int
    session: str           # "regular", "premarket", "afterhours", "overnight"
    uptime_pct: float      # 0-100
    passes: bool           # uptime_pct >= uptime_threshold
    # 1-second window fields (always present)
    seconds_with_data: int
    total_seconds: int
    updates_total: int
    updates_per_second: float
    # 200ms gap fields (only with --precise)
    downtime_ms: Optional[int]
    period_length_ms: Optional[int]
    max_gap_ms: Optional[int]
    gaps_over_threshold: Optional[int]

@dataclass(frozen=True)
class FeedUptimeResult:
    feed_id: int
    date: str
    mode: str
    symbol: Optional[str]
    publisher_count: int
    publisher_uptimes: list[PublisherSessionUptime]
    error: Optional[str]
    execution_time_ms: int
```

## Key Functions

| Function                                                                   | Description                                                      |
| -------------------------------------------------------------------------- | ---------------------------------------------------------------- |
| `discover_publishers_for_feed(client, feed_id, date)`                      | **New.** Query `publisher_updates` for distinct publisher_ids    |
| `compute_uptime_1s_window(client, pub_id, feed_id, start, end)`            | **Copied from** `verify_uptime.py:126-186` (default)             |
| `compute_uptime_200ms_gap(client, pub_id, feed_id, start, end, threshold)` | **Copied from** `verify_uptime.py:189-302` (--precise)           |
| `filter_sessions(sessions, extended_hours, overnight)`                     | **New.** Filter SessionWindows by flags                          |
| `evaluate_feed_uptime(client, feed_id, date, mode, ...)`                   | **New.** Core: discover publishers, compute per-publisher uptime |
| `get_feed_symbol(client, feed_id)`                                         | **New.** Lookup symbol from `feeds_metadata_latest`              |
| `compute_publisher_summary(results)`                                       | **New.** Build cross-date pass/fail matrix                       |
| `load_config()`, `get_lazer_client()`                                      | **Copied** (standard pattern)                                    |
| `normalize_asset_class()`                                                  | **Copied** from quick_benchmark.py                               |

**Imported from existing modules:**

- `from portal.batch.uptime_sessions import get_session_windows, SessionWindow`
- `from date_utils import expand_date_args, validate_date_args`

## Output Format

### Detail CSV — default (1-second window)

```csv
feed_id,date,mode,symbol,publisher_id,session,uptime_pct,passes,seconds_with_data,total_seconds,updates_total,updates_per_second
922,2026-02-09,us-equities,Equity.US.AAPL/USD,11,regular,99.99,True,23398,23400,1777079,75.94
922,2026-02-09,us-equities,Equity.US.AAPL/USD,12,premarket,0.00,False,0,19800,0,0.00
```

### Detail CSV — with `--precise` (adds gap columns)

```csv
feed_id,date,mode,symbol,publisher_id,session,uptime_pct,passes,downtime_ms,period_length_ms,updates_total,updates_per_second,max_gap_ms,gaps_over_threshold
922,2026-02-09,us-equities,Equity.US.AAPL/USD,11,regular,99.99,True,2168,23400000,1777079,75.94,829,17
922,2026-02-09,us-equities,Equity.US.AAPL/USD,12,premarket,0.00,False,19800000,19800000,0,0.00,0,0
```

### Publisher Summary Matrix (multi-date, appended after detail rows)

```csv

PUBLISHER SUMMARY
publisher_id,dates_seen,regular_pass_dates,regular_fail_dates,regular_pass_rate,regular_results,premarket_pass_dates,premarket_fail_dates,premarket_pass_rate,premarket_results,...
11,4,4,0,100.00%,02-09:PASS;02-10:PASS;02-11:PASS;02-12:PASS,4,0,100.00%,...
12,4,4,0,100.00%,...,0,4,0.00%,...
32,4,0,4,0.00%,...,0,4,0.00%,...
```

### Console Summary

```
======================================================================
FEED UPTIME REPORT
======================================================================
Feeds evaluated: 1 | Publisher-feed combos: 26 | Method: 1s window | Pass threshold: 95%

REGULAR SESSION:
  Median uptime: 49.43% | Mean: 55.12% | Min: 0.00% | Max: 99.99%
  Publishers passing (>=95%): 8 | Failing: 18

PREMARKET / AFTERHOURS / OVERNIGHT (if enabled):
  ...

======================================================================
PUBLISHER CONSISTENCY (across 4 dates)
======================================================================

REGULAR SESSION:
  Publisher  Pass  Fail  Rate    Results
  11         4     0     100.0%  02-09:PASS 02-10:PASS 02-11:PASS 02-12:PASS
  35         4     0     100.0%  02-09:PASS 02-10:PASS 02-11:PASS 02-12:PASS
  ...

  Always passing: 11, 19, 35 (3 publishers)
  Always failing: 14, 32, 40 (3 publishers)
  Intermittent: 20, 55 (2 publishers)

PREMARKET:
  ...
```

## Code Reuse

| Component                           | Source                            | Method           |
| ----------------------------------- | --------------------------------- | ---------------- |
| `compute_uptime_1s_window()`        | `verify_uptime.py:126-186`        | Copy (default)   |
| `compute_uptime_200ms_gap()`        | `verify_uptime.py:189-302`        | Copy (--precise) |
| `get_session_windows()`             | `portal/batch/uptime_sessions.py` | Import           |
| `expand_date_args()`                | `date_utils.py`                   | Import           |
| `load_config()` / client setup      | `quick_benchmark.py`              | Copy pattern     |
| `normalize_asset_class()` + aliases | `quick_benchmark.py`              | Copy             |
| ThreadPoolExecutor + as_completed   | `quick_benchmark.py`              | Follow pattern   |
| argparse structure                  | `quick_benchmark.py`              | Follow pattern   |

## Key Design Decisions

- **1-second window by default** — simpler, matches portal batch runner
- **`--precise` for 200ms gap-based** — opt-in when sub-second accuracy matters
- **Only Lazer ClickHouse** — uptime doesn't need Datascope
- **All asset classes valid** — unlike benchmarking, uptime works for crypto etc.
- **Pass threshold: 95%** — configurable via `--uptime-threshold`
- **Long-format CSV** — one row per (feed, date, publisher, session)
- **Publisher summary auto-appended** when multiple dates are present
- **Self-contained script** — copy utility functions (matching codebase convention)

## Edge Cases

| Case                           | Handling                                             |
| ------------------------------ | ---------------------------------------------------- |
| No publishers for feed         | `error="No publishers found"`, `publisher_count=0`   |
| Weekend (no sessions)          | `error="No trading sessions for date"`               |
| Feed metadata not found        | `symbol=None`, continue                              |
| `--extended-hours` with non-US | Ignored; only regular sessions                       |
| Single date (no matrix)        | Publisher summary matrix omitted, just overall stats |
| Connection error               | Catch exception, set `error=str(e)`                  |
| Empty CSV                      | Warning message, exit gracefully                     |

## Verification

```bash
# Single feed, single date
python feed_uptime.py --feed-id 922 --date 2026-02-09 --mode us-equities

# Multi-date with publisher summary
python feed_uptime.py --feed-id 922 --start-date 2026-02-09 --end-date 2026-02-12 \
  --mode us-equities --extended-hours --overnight --output 922_uptime.csv

# Verify publisher summary appears
grep -A 20 "PUBLISHER SUMMARY" 922_uptime.csv

# Cross-check with verify_uptime.py
python verify_uptime.py --publisher-id 11 --date 2026-02-09 --feed-id 922 --extended-hours

# Precise mode
python feed_uptime.py --feed-id 922 --date 2026-02-09 --mode us-equities --precise
```
