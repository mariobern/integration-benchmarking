# Tolerance-Based Benchmark Matching

**Date:** 2026-03-01
**Status:** Implemented
**Repo:** integration-benchmarking

## Problem

The current benchmark matching in `lib/benchmark_core.py` uses exact 1-second bucket matching: both publisher and benchmark data are aggregated to 1-second precision via ClickHouse's `toStartOfSecond()`, and a match only occurs when both have data in the **exact same second**.

This is too strict for less-traded assets where publisher and benchmark timestamps may not land in the same 1-second bucket. The `publisher_benchmark_eval.ipynb` notebook in the research repo uses `pd.merge_asof` with a 60-second tolerance, which captures more valid observations.

## Solution

Replace the exact dict-lookup matching with a **bisect-based nearest-match** that finds the closest benchmark timestamp within a configurable tolerance window (default: 60 seconds).

### Approach: Bisect-Based Nearest Match

- Use Python's stdlib `bisect_left` to binary-search sorted benchmark timestamps
- For each publisher timestamp, find the nearest benchmark timestamp
- Only count as a match if the distance is within `tolerance_seconds`
- No new dependencies, no ClickHouse query changes

### Why Not Alternatives

| Alternative            | Reason Rejected                                             |
| ---------------------- | ----------------------------------------------------------- |
| pandas `merge_asof`    | Adds pandas dependency, larger refactor, heavier processing |
| ClickHouse `ASOF JOIN` | Biggest change, rewrites SQL queries, harder to test        |

## Design

### New Helper Function

A shared `find_nearest_benchmark()` function in `lib/benchmark_core.py`:

```python
from bisect import bisect_left

def find_nearest_benchmark(
    sorted_ts: list[datetime],
    benchmark_by_ts: dict[datetime, tuple],
    target_ts: datetime,
    tolerance_seconds: int = 60,
) -> tuple | None:
    """Find nearest benchmark within tolerance. Returns (price, spread) or None."""
    idx = bisect_left(sorted_ts, target_ts)
    candidates = []
    if idx < len(sorted_ts):
        candidates.append(sorted_ts[idx])
    if idx > 0:
        candidates.append(sorted_ts[idx - 1])

    best = min(candidates, key=lambda t: abs((t - target_ts).total_seconds()), default=None)
    if best and abs((best - target_ts).total_seconds()) <= tolerance_seconds:
        return benchmark_by_ts[best]
    return None
```

### Matching Logic Change

**Before** (all 3 matching functions):

```python
benchmark_by_ts = {row[0]: (row[1], row[2]) for row in bench_result.result_rows if row[1] is not None}

for pub_id, ts, pub_price, _ in pub_result.result_rows:
    if ts not in benchmark_by_ts:
        continue
    bench_price, spread = benchmark_by_ts[ts]
```

**After:**

```python
benchmark_by_ts = {row[0]: (row[1], row[2]) for row in bench_result.result_rows if row[1] is not None}
sorted_bench_ts = sorted(benchmark_by_ts.keys())

for pub_id, ts, pub_price, _ in pub_result.result_rows:
    result = find_nearest_benchmark(sorted_bench_ts, benchmark_by_ts, ts, tolerance_seconds)
    if result is None:
        continue
    bench_price, spread = result
```

### CLI Parameter

New argument in `feed_readiness.py`:

```python
parser.add_argument(
    "--alignment-tolerance-sec",
    type=int,
    default=60,
    help="Max seconds between publisher and benchmark timestamps for matching (default: 60)",
)
```

Threaded through `process_csv()` and `process_work_items()` into all evaluate functions.

### Functions Modified

Three matching functions in `lib/benchmark_core.py` receive the same change:

1. `evaluate_feed_two_queries()` — already has `tolerance_seconds` param (currently unused for matching)
2. `evaluate_session_for_all_publishers()` — add `tolerance_seconds` param
3. `evaluate_overnight_for_all_publishers()` — add `tolerance_seconds` param

### Parameter Threading

```
feed_readiness.py  --alignment-tolerance-sec
    └── process_csv() / process_work_items()
        └── lib/readiness_core.py
            └── evaluate_feed_two_queries(tolerance_seconds=...)
                ├── evaluate_session_for_all_publishers(tolerance_seconds=...)
                └── evaluate_overnight_for_all_publishers(tolerance_seconds=...)
```

## Files Changed

| File                    | Change                                                                                                                    |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `lib/benchmark_core.py` | Add `find_nearest_benchmark()` helper, update 3 matching loops, add `tolerance_seconds` param to 2 functions that lack it |
| `feed_readiness.py`     | Add `--alignment-tolerance-sec` CLI arg, pass through to processing                                                       |
| `lib/readiness_core.py` | Thread `tolerance_seconds` through to benchmark function calls                                                            |

## What Stays the Same

- All ClickHouse SQL queries (no changes)
- Data volume transferred from ClickHouse
- All metrics calculations (RMSE, NRMSE, hit_rate, etc.)
- Output format and reporting
- Minimum observation thresholds (100 regular, 50 extended)

## Performance

- Binary search on ~23,400 items (6.5hr session) = ~15 comparisons per lookup
- Total: ~350K comparisons per publisher per session
- Estimated added processing time: single-digit milliseconds
- No additional ClickHouse load
