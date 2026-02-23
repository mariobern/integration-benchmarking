# Implementation Plan: Add Summary Metrics to publisher_benchmark.py Output

## Requirements Restatement

The user wants to enhance the `publisher_benchmark.py` script to:

1. Add summary metrics as part of the CSV output (currently only printed to console)
2. Add additional summary metrics that would be useful for evaluating publisher data quality

## Current State Analysis

**Current output**: The script writes per-feed results to CSV, then prints a summary to console:

- Total feeds evaluated
- PASS count (rmse/spread <= 1.0)
- FAIL count
- Error count
- Total time
- Average time per feed

**Current CSV columns**: publisher_id, feed_id, date, mode, symbol, passes, n_observations, rmse, mean_spread, rmse_over_spread, error, execution_time_ms

## Proposed Changes

### Phase 1: Add Summary Section to CSV

Append a summary section at the end of the CSV file with:

- Empty row separator
- Summary header row: `SUMMARY`
- Key-value pairs for summary metrics

### Phase 2: Add Additional Useful Summary Metrics

**Aggregate Statistics:**

- `total_feeds`: Total number of feeds evaluated
- `pass_count`: Number of feeds that passed (rmse/spread <= 1.0)
- `fail_count`: Number of feeds that failed (rmse/spread > 1.0)
- `error_count`: Number of feeds with errors
- `pass_rate_pct`: Pass rate as percentage

**Quality Metrics:**

- `median_rmse_over_spread`: Median rmse/spread ratio (more robust than mean)
- `mean_rmse_over_spread`: Average rmse/spread ratio for successful evaluations
- `p90_rmse_over_spread`: 90th percentile rmse/spread (identifies worst performers)
- `p95_rmse_over_spread`: 95th percentile rmse/spread
- `min_rmse_over_spread`: Best performing feed
- `max_rmse_over_spread`: Worst performing feed (excluding errors)

**Coverage Metrics:**

- `total_observations`: Total number of matched observations across all feeds
- `mean_observations_per_feed`: Average observations per feed
- `median_observations_per_feed`: Median observations per feed

**Breakdown by Asset Class:**

- `pass_count_by_mode`: Pass counts grouped by mode (fx, metals, us-equities, etc.)
- `fail_count_by_mode`: Fail counts grouped by mode

**Timing Metrics:**

- `total_time_sec`: Total execution time
- `avg_time_per_feed_ms`: Average time per feed in milliseconds

## Implementation Details

### File: `publisher_benchmark.py`

1. **Modify `write_results_csv()` function** (lines 513-554):

   - Add parameter for summary stats
   - After writing per-feed results, add summary section

2. **Create new function `compute_summary_stats()`**:

   - Takes list of PublisherBenchmarkResult
   - Returns dict of summary metrics
   - Uses Python statistics module for median/percentiles

3. **Modify `process_csv()` function** (lines 427-510):

   - Call `compute_summary_stats()` before `write_results_csv()`
   - Pass stats to `write_results_csv()`

4. **Update `main()` function** (lines 557-696):
   - Remove redundant summary calculation (now handled by `compute_summary_stats()`)

### CSV Output Format

```csv
# ... per-feed rows ...
55,2690,2026-01-21,equity-us,Equity.US.QBTS/USD,True,...

# Summary section
SUMMARY,,,,,,,,,,,,
publisher_id,55,,,,,,,,,,,
total_feeds,350,,,,,,,,,,,
pass_count,250,,,,,,,,,,,
fail_count,80,,,,,,,,,,,
error_count,20,,,,,,,,,,,
pass_rate_pct,78.12,,,,,,,,,,,
median_rmse_over_spread,0.4523,,,,,,,,,,,
mean_rmse_over_spread,0.5812,,,,,,,,,,,
p90_rmse_over_spread,0.9234,,,,,,,,,,,
p95_rmse_over_spread,1.1567,,,,,,,,,,,
min_rmse_over_spread,0.0825,,,,,,,,,,,
max_rmse_over_spread,234.49,,,,,,,,,,,
total_observations,2847563,,,,,,,,,,,
mean_observations_per_feed,8135.9,,,,,,,,,,,
median_observations_per_feed,1089,,,,,,,,,,,
total_time_sec,1247.32,,,,,,,,,,,
avg_time_per_feed_ms,3563,,,,,,,,,,,
pass_count_fx,12,,,,,,,,,,,
fail_count_fx,5,,,,,,,,,,,
pass_count_us-equities,220,,,,,,,,,,,
fail_count_us-equities,70,,,,,,,,,,,
pass_count_metals,18,,,,,,,,,,,
fail_count_metals,5,,,,,,,,,,,
```

## Dependencies

- Python `statistics` module (standard library) for median/percentiles
- No new external dependencies required

## Risks

- **LOW**: CSV format with summary section may not parse cleanly in some tools expecting pure tabular data
  - Mitigation: Use clear separator and consistent column count
- **LOW**: Large result sets could affect percentile calculation memory usage
  - Mitigation: Use `statistics.quantiles()` which is memory-efficient

## Estimated Complexity: LOW

- Single file modification
- ~80 lines of new code
- No architectural changes
- No new dependencies

## Files to Modify

1. `publisher_benchmark.py` - Add summary computation and CSV output

## Test Plan

- [ ] Run script with existing CSV input
- [ ] Verify summary section appears in output CSV
- [ ] Verify all metrics are calculated correctly
- [ ] Verify CSV still opens correctly in spreadsheet tools
- [ ] Verify console output still displays summary
