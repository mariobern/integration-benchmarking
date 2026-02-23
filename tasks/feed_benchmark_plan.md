# Plan: Upgrade quick_benchmark.py to Full Feed-Level Benchmark

## Context

`quick_benchmark.py` evaluates feed readiness (all publishers for a feed) but lacks most features from `publisher_benchmark.py`. The goal is to bring full feature parity — making `quick_benchmark.py` a feed-level equivalent of `publisher_benchmark.py` with all metrics, session support, and statistical analysis.

**Architectural difference**: `publisher_benchmark.py` evaluates one publisher across many feeds. `quick_benchmark.py` evaluates one feed across all publishers. The adaptation computes per-publisher metrics within the feed evaluation, then aggregates. A `--detailed` flag outputs per-publisher rows.

---

## Full Feature List

1. Regular hours time filtering for US equities (9:30 AM - 4:00 PM EST)
2. Extended hours (`--extended-hours`): pre-market + after-hours
3. Overnight (`--overnight`): publisher 32 as benchmark
4. Updated pass/fail: `nrmse < 0.01` OR (`nrmse < 0.05` AND `hit_rate >= 98%`)
5. New core metrics: `nrmse`, `hit_rate`, `benchmark_price_range`
6. Advanced statistical metrics: `mean_diff`, `std_diff`, `mean_pct_diff`, `std_pct_diff`, `mae`, `t_statistic`, `t_pvalue`, `wilcoxon_statistic`, `wilcoxon_pvalue`, `normality_pvalue`, `mean_abs_z_score`
7. `--skip-scipy-tests` optimization flag
8. Futures contract detection and benchmark table routing
9. US Treasuries support (yield columns)
10. `--filter-feed-id` for CSV filtering
11. Session-aware min observation thresholds (regular: 100, extended/overnight: 50)
12. `--detailed` flag for per-publisher output rows
13. Enhanced summary statistics (percentiles, per-asset-class breakdown, session summaries)
14. Interpretation guide

---

## Implementation Steps

### Step 1: Add imports, constants, enums, and helper functions

Copy from `publisher_benchmark.py` into `quick_benchmark.py`:

**New imports:**

- `from enum import Enum`
- `from datetime import datetime`
- `from functools import lru_cache`
- `from zoneinfo import ZoneInfo`
- `import statistics`
- `from scipy import stats` (lazy import, only when needed)

**Constants & enums** (from publisher_benchmark.py:47-99):

- `TradingSession` enum
- All market hours constants (`US_EQUITY_MARKET_OPEN_HOUR`, etc.)
- `OVERNIGHT_REFERENCE_PUBLISHER_ID = 32`
- `FUTURES_MONTH_CODES`

**Helper functions** (from publisher_benchmark.py):

- `is_futures_symbol()` (lines 102-146)
- `get_market_hours_filter_sql()` with `@lru_cache` (lines 149-195)
- `get_extended_hours_filter_sql()` with `@lru_cache` (lines 198-259)
- `get_overnight_hours_filter_sql()` with `@lru_cache` (lines 262-314)
- `get_benchmark_table()` (lines 317-337)
- `get_benchmark_columns()` (lines 340-355)
- `compute_statistical_metrics()` (lines 358-434)

**Update existing:**

- `ASSET_CLASS_ALIASES`: add `"us-treasuries"`, `"treasuries"` → `"us-treasuries"`, `"rates"` → `"us-treasuries"`
- `BENCHMARKABLE_ASSET_CLASSES`: add `"us-treasuries"`

### Step 2: Add data structures

**New dataclasses** (from publisher_benchmark.py):

- `ExtendedHoursMetrics` (lines 437-449)
- `OvernightMetrics` (lines 452-471)

**New dataclass for per-publisher detail:**

```python
@dataclass
class PublisherFeedMetrics:
    """Per-publisher metrics within a feed evaluation."""
    publisher_id: int
    n_observations: int
    passes: bool
    nrmse: Optional[float] = None
    hit_rate: Optional[float] = None
    rmse: Optional[float] = None
    mean_spread: Optional[float] = None
    rmse_over_spread: Optional[float] = None
    benchmark_price_range: Optional[float] = None
    # Statistical metrics
    mean_diff: Optional[float] = None
    std_diff: Optional[float] = None
    mean_pct_diff: Optional[float] = None
    std_pct_diff: Optional[float] = None
    mae: Optional[float] = None
    t_statistic: Optional[float] = None
    t_pvalue: Optional[float] = None
    wilcoxon_statistic: Optional[float] = None
    wilcoxon_pvalue: Optional[float] = None
    normality_pvalue: Optional[float] = None
    mean_abs_z_score: Optional[float] = None
    # Session metrics
    premarket_metrics: Optional[ExtendedHoursMetrics] = None
    afterhours_metrics: Optional[ExtendedHoursMetrics] = None
    overnight_metrics: Optional[OvernightMetrics] = None
    error: Optional[str] = None
```

**Update `BenchmarkResult` dataclass** (lines 52-67):

```python
@dataclass
class BenchmarkResult:
    # Existing fields (unchanged positions)
    feed_id: int
    date: str
    mode: str
    symbol: Optional[str]
    ready: bool
    target_pub_count: int
    passing_pub_count: int
    failing_pub_count: int
    passing_publishers: list[int]
    failing_publishers: list[int]
    # NEW: aggregate metrics across publishers
    median_nrmse: Optional[float] = None
    median_hit_rate: Optional[float] = None
    # NEW: per-publisher detail (populated when --detailed)
    publisher_details: Optional[list[PublisherFeedMetrics]] = None
    # NEW: extended hours aggregate counts
    premarket_passing_count: Optional[int] = None
    premarket_failing_count: Optional[int] = None
    afterhours_passing_count: Optional[int] = None
    afterhours_failing_count: Optional[int] = None
    # NEW: overnight aggregate counts
    overnight_passing_count: Optional[int] = None
    overnight_failing_count: Optional[int] = None
    overnight_reference_publisher_id: Optional[int] = None
    error: Optional[str] = None
    execution_time_ms: int = 0
```

### Step 3: Add session evaluation helpers

**`evaluate_session_for_all_publishers()`** — adapted from publisher_benchmark's `evaluate_session_metrics()` (lines 925-1041), but queries ALL publishers (no `publisher_id` filter). Returns `dict[int, dict]` mapping publisher_id to session metrics.

**`evaluate_overnight_for_all_publishers()`** — adapted from publisher_benchmark's `evaluate_overnight_session()` (lines 1044-1238), evaluating all publishers against publisher 32. Skips publisher 32 evaluating itself.

### Step 4: Update `evaluate_feed_two_queries()`

**File**: `quick_benchmark.py` lines 311-501

**Signature change:**

```python
def evaluate_feed_two_queries(
    client_lazer, client_analytics, feed_id, date, mode,
    target_pub_count=4, tolerance_seconds=60,
    include_extended_hours=False,
    include_overnight=False,
    skip_scipy_tests=False,
    include_detailed=False,
) -> BenchmarkResult:
```

**Changes inside:**

a) **Normalize mode** early: `mode = normalize_asset_class(mode)`

b) **Benchmark table** (replace lines 350-354):

```python
benchmark_table = get_benchmark_table(mode, symbol)
```

c) **Dynamic benchmark columns** (new):

```python
price_col, bid_col, ask_col = get_benchmark_columns(mode)
```

d) **Market hours time filtering** (new, inject into queries):

```python
publisher_market_filter = get_market_hours_filter_sql(mode, date, "publish_time")
benchmark_market_filter = get_market_hours_filter_sql(mode, date, "date_time")
```

e) **Update publisher query** (lines 357-370): add `{publisher_market_filter}` and use dynamic columns in benchmark query (lines 374-386).

f) **Expand per-publisher tracking** (lines 432-451):

```python
publisher_metrics[pub_id] = {
    "squared_errors": [],
    "spreads": [],
    "benchmark_prices": [],    # NEW
    "pct_diffs": [],           # NEW (absolute)
    "diffs": [],               # NEW (raw)
    "signed_pct_diffs": [],    # NEW
}
```

g) **Compute full metrics per publisher** (replace lines 453-469):

- `rmse`, `mean_spread`, `rmse_over_spread` (existing)
- `benchmark_range`, `nrmse`, `hit_rate` (new)
- Pass/fail: `nrmse < 0.01 or (nrmse < 0.05 and hit_rate >= 98)`
- Statistical metrics via `compute_statistical_metrics()` unless `skip_scipy_tests`
- Build `PublisherFeedMetrics` object

h) **Extended hours** (new, after main evaluation):

```python
if include_extended_hours and mode == "us-equities":
    premarket_results = evaluate_session_for_all_publishers(
        ..., session=TradingSession.PREMARKET, min_observations=50)
    afterhours_results = evaluate_session_for_all_publishers(
        ..., session=TradingSession.AFTERHOURS, min_observations=50)
    # Attach to publisher_details and compute aggregate counts
```

i) **Overnight** (new, after extended hours):

```python
if include_overnight and mode == "us-equities":
    overnight_results = evaluate_overnight_for_all_publishers(
        ..., min_observations=50)
    # Attach to publisher_details and compute aggregate counts
```

j) **Aggregate metrics**:

- `median_nrmse` = median of all publishers' nrmse values
- `median_hit_rate` = median of all publishers' hit_rate values

k) **Return enhanced `BenchmarkResult`** with all new fields populated.

### Step 5: Deprecate `evaluate_feed_fast()`

Mark the ASOF JOIN method (lines 148-308) as deprecated. It's unused (line 567 calls `evaluate_feed_two_queries`). Add a comment and leave it in place but don't update it.

### Step 6: Update CLI arguments

**File**: `quick_benchmark.py` lines 644-725

**New arguments:**

```python
--extended-hours    # store_true, pre-market + after-hours for US equities
--overnight         # store_true, overnight using publisher 32
--skip-scipy-tests  # store_true, skip statistical tests
--detailed          # store_true, output per-publisher rows
--filter-feed-id    # nargs="+", type=int, filter specific feed IDs in CSV mode
```

**Expand `--mode` choices** (line 686):

```python
choices=["fx", "metals", "us-equities", "commodity", "us-treasuries", "treasuries", "rates"]
```

**Add validation:**

- `--filter-feed-id` only applies to `--csv` mode
- `--extended-hours` and `--overnight` only meaningful for US equities (warn, don't error)

### Step 7: Update `process_csv()`

**File**: `quick_benchmark.py` lines 504-597

Add parameters: `include_extended_hours`, `include_overnight`, `skip_scipy_tests`, `include_detailed`, `feed_id_filter`.

Apply `feed_id_filter` after asset class filtering (before processing).

Pass all new params through to `evaluate_feed_two_queries()`.

### Step 8: Update `write_results_csv()`

**File**: `quick_benchmark.py` lines 600-641

Accept `include_extended_hours`, `include_overnight`, `include_detailed` params.

**Default output columns** (feed-level, one row per feed):

- Existing: `feed_id`, `date`, `mode`, `symbol`, `ready`, `target_pub_count`, `passing_pub_count`, `failing_pub_count`, `passing_publishers`, `failing_publishers`
- New always: `median_nrmse`, `median_hit_rate`
- New if `--extended-hours`: `premarket_passing_count`, `premarket_failing_count`, `afterhours_passing_count`, `afterhours_failing_count`
- New if `--overnight`: `overnight_passing_count`, `overnight_failing_count`, `overnight_reference_publisher_id`
- Existing: `error`, `execution_time_ms`

**Detailed output** (when `--detailed`): After the feed-level rows, append a `PUBLISHER DETAIL` section with per-publisher rows containing:

- `feed_id`, `publisher_id`, `date`, `mode`, `symbol`, `passes`, `n_observations`
- `nrmse`, `hit_rate`, `rmse`, `mean_spread`, `rmse_over_spread`, `benchmark_price_range`
- Statistical metrics (if not skipped)
- Session metrics (if enabled)

### Step 9: Enhanced summary statistics

**File**: `quick_benchmark.py` lines 799-815

Replace minimal summary with comprehensive output:

1. **Pass/fail criteria** explanation
2. **Core counts**: Ready/Not Ready/Error
3. **NRMSE distribution** across feeds: median, mean, p90, p95
4. **Hit rate distribution**: median, mean, min, max
5. **Per-asset-class breakdown**: pass/fail/error by mode
6. **Extended hours summary** (if `--extended-hours`): aggregate premarket/afterhours pass rates
7. **Overnight summary** (if `--overnight`): aggregate pass rate, reference publisher
8. **Timing**: total time, avg per feed

### Step 10: Update module docstring

Update lines 2-16 to reflect:

- New pass/fail criteria
- New flags (`--extended-hours`, `--overnight`, `--skip-scipy-tests`, `--detailed`, `--filter-feed-id`)
- Expanded mode choices

---

## Files Modified

| File                 | Changes                        |
| -------------------- | ------------------------------ |
| `quick_benchmark.py` | All changes above (Steps 1-10) |

No new files. No changes to `publisher_benchmark.py`.

---

## Key Functions to Reuse from publisher_benchmark.py

| Function                           | Location | Purpose                                   |
| ---------------------------------- | -------- | ----------------------------------------- |
| `TradingSession`                   | :47-52   | Enum for session types                    |
| `is_futures_symbol()`              | :102-146 | Detect futures contracts                  |
| `get_market_hours_filter_sql()`    | :149-195 | SQL WHERE for regular hours               |
| `get_extended_hours_filter_sql()`  | :198-259 | SQL WHERE for pre-market/after-hours      |
| `get_overnight_hours_filter_sql()` | :262-314 | SQL WHERE for overnight                   |
| `get_benchmark_table()`            | :317-337 | Benchmark table routing                   |
| `get_benchmark_columns()`          | :340-355 | Price vs yield columns                    |
| `compute_statistical_metrics()`    | :358-434 | t-test, Wilcoxon, normality, MAE, z-score |
| `ExtendedHoursMetrics`             | :437-449 | Dataclass                                 |
| `OvernightMetrics`                 | :452-471 | Dataclass                                 |

---

## Verification

1. **FX mode** (no session filtering):

   ```bash
   python quick_benchmark.py --feed-id 327 --date 2025-10-06 --mode fx
   ```

2. **US equities with regular hours filtering**:

   ```bash
   python quick_benchmark.py --feed-id 1163 --date 2025-10-02 --mode us-equities
   ```

3. **Extended hours**:

   ```bash
   python quick_benchmark.py --feed-id 1163 --date 2025-10-02 --mode us-equities --extended-hours
   ```

4. **Overnight**:

   ```bash
   python quick_benchmark.py --feed-id 1163 --date 2025-10-02 --mode us-equities --overnight
   ```

5. **Detailed output**:

   ```bash
   python quick_benchmark.py --feed-id 1163 --date 2025-10-02 --mode us-equities --detailed
   ```

6. **CSV batch with all flags**:

   ```bash
   python quick_benchmark.py --csv price_id_list.csv --extended-hours --overnight --detailed --include-asset-class us-equities
   ```

7. **Skip scipy tests** (faster execution):

   ```bash
   python quick_benchmark.py --csv price_id_list.csv --skip-scipy-tests
   ```

8. **Feed ID filtering**:

   ```bash
   python quick_benchmark.py --csv price_id_list.csv --filter-feed-id 327 1163
   ```

9. **Backward compatibility**: Running with no new flags should work. Output adds `median_nrmse`, `median_hit_rate` columns. Pass/fail results may differ due to updated criteria.
