# Plan: `feed_readiness.py` — Combined Benchmark + Uptime Script

## Context

Currently, evaluating whether a feed is production-ready requires running two scripts separately:

- `quick_benchmark_95.py` — benchmark quality (NRMSE, hit rate against Datascope)
- `feed_uptime.py` — publisher uptime (data availability/gaps)

This creates friction. A single `feed_readiness.py` script will run both evaluations per feed and produce a unified readiness verdict: a feed is **READY** only when enough publishers pass **both** benchmark quality AND uptime.

## Approach: Import & Orchestrate

New file `feed_readiness.py` imports evaluation functions from existing scripts — no duplication of benchmark/uptime logic.

## Files

| File                    | Action                                 |
| ----------------------- | -------------------------------------- |
| `feed_readiness.py`     | **Create** — new combined script       |
| `quick_benchmark_95.py` | Read-only import source                |
| `feed_uptime.py`        | Read-only import source                |
| `date_utils.py`         | Read-only import (shared date parsing) |

## Key Imports

```python
from quick_benchmark_95 import (
    evaluate_feed_two_queries,  # (client_lazer, client_analytics, feed_id, date, mode, ...) → BenchmarkResult
    BenchmarkResult,
    PublisherFeedMetrics,
    load_config,
    get_clients,               # returns (client_lazer, client_analytics)
    normalize_asset_class,
    BENCHMARKABLE_ASSET_CLASSES,
    ASSET_CLASS_ALIASES,
    list_asset_classes_in_csv,
)

from feed_uptime import (
    evaluate_feed_uptime,      # (client, feed_id, date, mode, ...) → FeedUptimeResult
    FeedUptimeResult,
    PublisherSessionUptime,
    DEFAULT_GAP_THRESHOLD_MS,  # 200
    DEFAULT_UPTIME_THRESHOLD_PCT,  # 95.0
)

from date_utils import expand_date_args, validate_date_args
```

## Readiness Logic

```
Per publisher:
  benchmark_passes = PublisherFeedMetrics.passes (nrmse < 0.01 OR (nrmse < 0.05 AND hit_rate >= 95%))
  uptime_passes    = PublisherSessionUptime.passes for "regular" session (uptime_pct >= threshold)
  fully_passes     = benchmark_passes AND uptime_passes

Per feed:
  ready          = fully_passing_count >= target_pub_count
  benchmark_ready = benchmark passing_count >= target_pub_count  (from BenchmarkResult.ready)
  uptime_ready    = uptime passing_count >= target_pub_count
```

Publishers are matched by ID across both evaluations. A publisher missing from one evaluation fails that check.

## New Dataclasses

### `PublisherReadinessDetail`

```
publisher_id: int
benchmark_passes: bool
benchmark_nrmse: Optional[float]
benchmark_hit_rate: Optional[float]
benchmark_n_observations: int
benchmark_error: Optional[str]
uptime_passes: bool              # regular session only
uptime_pct: Optional[float]      # regular session
uptime_error: Optional[str]
fully_passes: bool               # benchmark AND uptime
benchmark_detail: Optional[PublisherFeedMetrics]     # for --detailed CSV
uptime_sessions: Optional[list[PublisherSessionUptime]]  # for --detailed CSV
```

### `FeedReadinessResult`

```
feed_id, date, mode, symbol
ready: bool                      # combined verdict
benchmark_ready: bool
uptime_ready: bool
target_pub_count: int
fully_passing_count: int         # pass both
benchmark_only_passing_count: int
uptime_only_passing_count: int
both_failing_count: int
total_publisher_count: int
benchmark_passing_count, benchmark_failing_count
median_nrmse, median_hit_rate
uptime_passing_count, uptime_failing_count
median_uptime_pct: Optional[float]
fully_passing_publishers: list[int]       # semicolon-separated in CSV
benchmark_only_publishers: list[int]
uptime_only_publishers: list[int]
both_failing_publishers: list[int]
premarket_passing_count, afterhours_passing_count, overnight_passing_count  # optional
benchmark_error, uptime_error, error: Optional[str]
execution_time_ms: int
publisher_details: Optional[list[PublisherReadinessDetail]]
```

## Per-Feed Evaluation Flow

```python
def evaluate_feed_readiness(client_lazer, client_analytics, feed_id, date, mode, ...):
    start = time.time()

    # 1. Benchmark (needs both clients)
    benchmark_result = evaluate_feed_two_queries(
        client_lazer, client_analytics, feed_id, date, mode,
        target_pub_count=target_pub_count,
        include_extended_hours=include_extended_hours,
        include_overnight=include_overnight,
        skip_scipy_tests=skip_scipy_tests,
    )

    # 2. Uptime (needs lazer client only)
    uptime_result = evaluate_feed_uptime(
        client_lazer, feed_id, date, mode,
        include_extended_hours=include_extended_hours,
        include_overnight=include_overnight,
        precise=precise,
        gap_threshold_ms=gap_threshold_ms,
        uptime_threshold_pct=uptime_threshold_pct,
    )

    # 3. Merge by publisher ID
    return merge_results(benchmark_result, uptime_result, target_pub_count)
```

## Merge Logic (`merge_results`)

1. Build `benchmark_by_pub: dict[int, PublisherFeedMetrics]` from `benchmark_result.publisher_details`
2. Build `uptime_by_pub: dict[int, PublisherSessionUptime]` from uptime regular-session entries
3. Union all publisher IDs from both sets
4. Classify each publisher into four buckets:
   - **fully_passing** — benchmark PASS + uptime PASS
   - **benchmark_only** — benchmark PASS + uptime FAIL
   - **uptime_only** — benchmark FAIL + uptime PASS
   - **both_failing** — benchmark FAIL + uptime FAIL
5. Compute `ready = len(fully_passing) >= target_pub_count`

## Error Handling

| Scenario                              | Behavior                                                                  |
| ------------------------------------- | ------------------------------------------------------------------------- |
| Benchmark errors, uptime succeeds     | `benchmark_ready=False`, `uptime_ready` computed, `ready=False`           |
| Benchmark succeeds, uptime errors     | `uptime_ready=False`, `benchmark_ready` computed, `ready=False`           |
| Both error                            | `ready=False`, both error fields populated                                |
| Non-benchmarkable asset class         | `benchmark_error="Asset class not benchmarkable"`, uptime still evaluated |
| Publisher in benchmark but not uptime | `uptime_passes=False` for that publisher                                  |
| Publisher in uptime but not benchmark | `benchmark_passes=False` for that publisher                               |

## CLI Interface

Same patterns as existing scripts. Combines args from both:

```
Input:        --csv, --feed-id, --date, --start-date/--end-date, --mode
Output:       --output (default: feed_readiness_results.csv), --detailed
Benchmark:    --target-pub-count (4), --skip-scipy-tests
Uptime:       --precise, --gap-threshold (200), --uptime-threshold (95.0)
Sessions:     --extended-hours, --overnight
Execution:    --workers (4)
Filtering:    --include-asset-class, --exclude-asset-class, --filter-feed-id, --list-asset-classes
```

## CSV Output

### Feed-level rows (default)

```
feed_id, date, mode, symbol,
ready, benchmark_ready, uptime_ready,
target_pub_count, fully_passing_count,
benchmark_only_passing_count, uptime_only_passing_count, both_failing_count,
total_publisher_count,
benchmark_passing_count, benchmark_failing_count, median_nrmse, median_hit_rate,
uptime_passing_count, uptime_failing_count, median_uptime_pct,
fully_passing_publishers, benchmark_only_publishers, uptime_only_publishers, both_failing_publishers,
[premarket_passing_count, afterhours_passing_count]   # if --extended-hours
[overnight_passing_count]                              # if --overnight
benchmark_error, uptime_error, error, execution_time_ms
```

### PUBLISHER DETAIL section (with `--detailed`)

```
feed_id, publisher_id, date, mode, symbol,
fully_passes, benchmark_passes, uptime_passes,
benchmark_nrmse, benchmark_hit_rate, benchmark_n_observations,
uptime_pct,
benchmark_error, uptime_error
```

### PUBLISHER CONSISTENCY section (multi-date, with `--detailed`)

Same pattern as quick_benchmark — cross-date pass/fail matrix + classifications.

## Console Summary

```
======================================================================
FEED READINESS REPORT
======================================================================
Feeds evaluated: 150 | Target publishers: 4
Benchmark: nrmse < 0.01 OR (nrmse < 0.05 AND hit_rate >= 95%)
Uptime: regular session >= 95.0% (1s window)
======================================================================

COMBINED READINESS:
  Ready (both pass): 120 / 150 (80.0%)
  Benchmark-only ready: 135 / 150 (90.0%)
  Uptime-only ready: 128 / 150 (85.3%)

BENCHMARK QUALITY:
  NRMSE: median=0.0023 mean=0.0036 p90=0.0089 p95=0.0120
  Hit rate: median=99.45% mean=98.90% min=72.30% max=100.00%

UPTIME (REGULAR SESSION):
  Median: 99.87% | Mean: 99.45% | Min: 82.30% | Max: 100.00%

BY ASSET CLASS:
  fx              ready=50  not_ready=5   error=1
  us-equities     ready=50  not_ready=12  error=4
  metals          ready=20  not_ready=3   error=0

Timing: 45.2s total, 301ms avg/feed
```

## Implementation Steps

1. Create `feed_readiness.py` with imports, dataclasses, `merge_results()`
2. Implement `evaluate_feed_readiness()` calling both evaluation functions
3. Implement `process_csv()` / `process_work_items()` (reuse pattern from quick_benchmark_95)
4. Implement `write_results_csv()` with combined columns
5. Implement `compute_summary_stats()` and `print_console_summary()`
6. Implement `main()` with argparse and validation
7. Test with a few feeds across asset classes

## Verification

```bash
source venv/bin/activate

# Single feed, single date
python3 feed_readiness.py --feed-id 327 --date 2026-02-10 --mode fx --output /tmp/test_fr.csv

# Multi-date range
python3 feed_readiness.py --feed-id 327 --start-date 2026-02-10 --end-date 2026-02-12 --mode fx

# CSV batch
python3 feed_readiness.py --csv price_id_list.csv --output /tmp/batch_fr.csv --workers 8

# With uptime precision + extended hours
python3 feed_readiness.py --feed-id 922 --date 2026-02-10 --mode us-equities --precise --extended-hours

# Detailed mode
python3 feed_readiness.py --feed-id 327 --date 2026-02-10 --mode fx --detailed
```

Check:

- CSV has combined readiness columns (ready, benchmark_ready, uptime_ready)
- Publisher lists are correctly classified into 4 buckets
- Console shows combined summary with both benchmark and uptime stats
- Single-date and multi-date both work
- Non-benchmarkable asset classes report benchmark_error gracefully
