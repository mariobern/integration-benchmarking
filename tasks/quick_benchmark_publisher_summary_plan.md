# Plan: Publisher Summary for `quick_benchmark.py`

## Context

When running `quick_benchmark.py` across multiple dates (e.g., `--feed-id 922 --start-date 2026-02-09 --end-date 2026-02-12 --detailed`), the output shows per-publisher pass/fail per date in the PUBLISHER DETAIL section, but there's no cross-date summary answering: "Which publishers consistently pass? Which are flaky? Which always fail?"

This adds a **PUBLISHER SUMMARY** section (CSV + console) that provides a cross-date consistency matrix per session.

## What Changes

**File:** `/home/mariobern/integration-benchmarking/quick_benchmark.py`

Add a new CSV section and console output when `--detailed` is used with multiple dates. No new CLI flags needed — the summary is automatically appended.

## Cross-Date Matrix Format (CSV)

Appended after the existing `PUBLISHER DETAIL` section:

```csv

PUBLISHER SUMMARY
publisher_id,dates_seen,regular_pass_dates,regular_fail_dates,regular_pass_rate,regular_results
11,4,1,3,25.00%,2026-02-09:FAIL;2026-02-10:PASS;2026-02-11:FAIL;2026-02-12:FAIL
12,4,4,0,100.00%,2026-02-09:PASS;2026-02-10:PASS;2026-02-11:PASS;2026-02-12:PASS
19,4,4,0,100.00%,2026-02-09:PASS;2026-02-10:PASS;2026-02-11:PASS;2026-02-12:PASS
```

With `--extended-hours`, add per-session columns:

```csv
publisher_id,dates_seen,regular_pass_dates,regular_fail_dates,regular_pass_rate,regular_results,premarket_pass_dates,premarket_fail_dates,premarket_pass_rate,premarket_results,afterhours_pass_dates,afterhours_fail_dates,afterhours_pass_rate,afterhours_results
```

With `--overnight`, add overnight columns:

```csv
...,overnight_pass_dates,overnight_fail_dates,overnight_pass_rate,overnight_results
```

## Console Output

Printed after the existing summary:

```
======================================================================
PUBLISHER CONSISTENCY (across 4 dates)
======================================================================

REGULAR SESSION:
  Publisher  Pass  Fail  Rate    Results
  12         4     0     100.0%  02-09:PASS 02-10:PASS 02-11:PASS 02-12:PASS
  19         4     0     100.0%  02-09:PASS 02-10:PASS 02-11:PASS 02-12:PASS
  55         3     1     75.0%   02-09:PASS 02-10:PASS 02-11:FAIL 02-12:PASS
  11         1     3     25.0%   02-09:FAIL 02-10:PASS 02-11:FAIL 02-12:FAIL

  Always passing: 12, 19 (2 publishers)
  Always failing: 41, 43 (2 publishers)
  Intermittent: 11, 55 (2 publishers)

PREMARKET (if --extended-hours):
  Publisher  Pass  Fail  Rate    Results
  ...

AFTERHOURS (if --extended-hours):
  ...

OVERNIGHT (if --overnight):
  ...
```

## Implementation Details

### New function: `compute_publisher_summary()`

```python
def compute_publisher_summary(
    results: list[BenchmarkResult],
    include_extended_hours: bool = False,
    include_overnight: bool = False,
) -> dict:
    """Build cross-date publisher pass/fail matrix from detailed results."""
```

Logic:

1. Iterate `results` (each has `publisher_details: list[PublisherFeedMetrics]`)
2. For each publisher, collect `{date: passes}` for regular session
3. If extended hours: also collect from `premarket_metrics.passes` and `afterhours_metrics.passes`
4. If overnight: collect from `overnight_metrics.passes`
5. Sort publishers by pass_rate descending (best performers first)
6. Return structured dict for both CSV writing and console printing

### New function: `write_publisher_summary_csv()`

Appended inside `write_results_csv()` after the PUBLISHER DETAIL section, gated on `include_detailed and len(unique_dates) > 1`.

### New function: `print_publisher_summary()`

Called from `main()` after `print_interpretation_guide()`, gated on same condition.

## Key Details

- **Pass/fail source**: `PublisherFeedMetrics.passes` (regular), `.premarket_metrics.passes`, `.afterhours_metrics.passes`, `.overnight_metrics.passes`
- **Sorting**: By regular pass_rate descending, then publisher_id ascending
- **Date format**: Short `MM-DD` for console, full `YYYY-MM-DD` in CSV
- **Gating**: Only shown with `--detailed` AND >1 unique date in results
- **Error handling**: If a publisher has an error on a date, show as `ERROR` in the matrix

## Files Modified

- `/home/mariobern/integration-benchmarking/quick_benchmark.py` — add ~150 lines (3 new functions + calls in `write_results_csv()` and `main()`)

## Verification

```bash
# Test publisher summary (multi-date + detailed)
python quick_benchmark.py --feed-id 922 --start-date 2026-02-09 --end-date 2026-02-12 \
  --mode us-equities --extended-hours --overnight --detailed --workers 16 --output 922_test.csv

# Verify PUBLISHER SUMMARY section appears in CSV
grep -A 20 "PUBLISHER SUMMARY" 922_test.csv

# Verify console shows PUBLISHER CONSISTENCY section
# (visible in terminal output)

# Single date — verify summary is NOT shown
python quick_benchmark.py --feed-id 922 --date 2026-02-09 \
  --mode us-equities --detailed --output 922_single.csv
grep "PUBLISHER SUMMARY" 922_single.csv  # should find nothing
```
