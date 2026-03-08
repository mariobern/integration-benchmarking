# Design: Incorporate Research PRs #264 & #265

**Date:** 2026-03-08
**Source:** pyth-network/research PRs #264 (qualifier filter) and #265 (aggregate feed as publisher 0)
**Scope:** `feed_readiness.py`, `quick_benchmark.py`, and supporting `lib/` modules

## PR #264: Qualifier Filter for US Equities

### Problem

Datascope benchmark data for US equities includes irregular trade conditions (odd lots, contingent trades, price discovery trades) that distort benchmark quality comparisons.

### Solution

Add a SQL WHERE clause filter to exclude irregular qualifiers from `datascope_global_equities_benchmark_data` queries when `mode == "us-equities"` only.

### SQL Filter

```sql
AND (
  qualifiers IS NULL
  OR (
    qualifiers NOT LIKE '%CON[IRGCOND]%'
    AND qualifiers NOT LIKE '%ODD[IRGCOND]%'
    AND qualifiers NOT LIKE '%378[IRGCOND]%'
    AND qualifiers NOT LIKE '%2315[IRGCOND]%'
    AND qualifiers NOT LIKE '%DAP[IRGCOND]%'
    AND NOT match(qualifiers, 'PD_[A-Za-z0-9_]*')
  )
)
```

### Implementation

- New function `get_qualifier_filter_sql(mode)` in `lib/sql_filters.py`
- Returns the filter for `us-equities`, empty string for all other modes
- Injected into all benchmark query locations in `lib/benchmark_core.py` and `lib/publisher_eval.py`

### Injection Points

1. `lib/benchmark_core.py`: `evaluate_feed_two_queries()` benchmark query
2. `lib/benchmark_core.py`: `evaluate_session_for_all_publishers()` benchmark query
3. `lib/publisher_eval.py`: `evaluate_publisher_feed()` benchmark query
4. `lib/publisher_eval.py`: `evaluate_session_metrics()` benchmark query
5. `lib/publisher_eval.py`: extended hours session benchmark queries

## PR #265: Aggregate Feed as Publisher 0

### Problem

The aggregated price feed output is not currently evaluated alongside individual publishers, making it invisible to quality monitoring.

### Solution

Query the `price_feeds` table (Lazer's aggregated output), treat it as "publisher 0", evaluate it with full metrics, but exclude it from readiness/passing counts.

### New Query Function

`query_aggregate_feed()` in `lib/benchmark_core.py`:

- Queries `price_feeds` table with `publisher_id = 0`
- Tries channels 1, 2, 3 in sequence; uses first with data
- Applies same market hours filter and price divisor as publisher queries
- Returns result rows compatible with publisher data format

### Integration

- `benchmark_core.evaluate_feed_two_queries()`: After querying `publisher_updates`, query `price_feeds`. Merge publisher 0 rows before per-publisher metrics loop. Publisher 0 gets full metrics but is excluded from `passing_publishers`/`failing_publishers` lists.
- `readiness_core.merge_results()`: Publisher 0 excluded from readiness buckets and `fully_passing` count.

### Model Changes

- `BenchmarkResult`: Add `agg_metrics: Optional[PublisherFeedMetrics] = None` to hold publisher 0's evaluation separately.

### CLI Changes

- `feed_readiness.py`: Add `--no-agg` flag (default: aggregate included)
- `quick_benchmark.py`: Add `--no-agg` flag (default: aggregate included)
- Thread `include_agg` boolean through `process_csv()` → `evaluate_feed_two_queries()`

### Output

- Publisher 0 appears in CSV output rows with `publisher_id=0`
- Console summary notes aggregate metrics separately
- Publisher 0 does NOT count toward `passing_pub_count` or readiness determination

### Error Handling

- If `price_feeds` table doesn't exist or query fails: log warning, continue without publisher 0
- If no data on any channel: skip publisher 0 silently

## Out of Scope

- `publisher_benchmark.py` — not touched
- `lib/thresholds.py` — no threshold changes
- `lib/uptime_core.py` — no uptime evaluation for publisher 0
- Existing pass/fail logic and output formats remain backward-compatible
