# Publisher Benchmark Tool

Evaluates a **single publisher's** data quality. Faster than `quick_benchmark.py` because it only queries one publisher.

## When to Use

| Scenario                              | Use This Tool                    |
| ------------------------------------- | -------------------------------- |
| Evaluate one specific publisher       | Yes                              |
| Onboard a new publisher               | Yes                              |
| Check if a feed has enough publishers | Use `quick_benchmark.py` instead |

## Usage

```bash
# Use filename convention (extracts publisher ID automatically)
python publisher_benchmark.py --csv publisher_55_feeds.csv

# Specify publisher ID explicitly
python publisher_benchmark.py --csv feeds.csv --publisher-id 55

# Faster processing with more workers
python publisher_benchmark.py --csv publisher_55_feeds.csv --workers 8

# Filter by asset class
python publisher_benchmark.py --csv publisher_55_feeds.csv --include-asset-class fx metals

# Override CSV dates with explicit date list
python publisher_benchmark.py --csv publisher_55_feeds.csv --publisher-id 55 \
  --date 2026-02-10 2026-02-11

# Override CSV dates with inclusive date range
python publisher_benchmark.py --csv publisher_55_feeds.csv --publisher-id 55 \
  --start-date 2026-02-10 --end-date 2026-02-12
```

## Arguments

| Argument                | Description                                                   | Default                                |
| ----------------------- | ------------------------------------------------------------- | -------------------------------------- |
| `--csv`                 | CSV file with feed_id,date,mode columns (required)            | -                                      |
| `--publisher-id`        | Publisher ID to evaluate                                      | Extracted from filename                |
| `--output`              | Output CSV path                                               | `publisher_{id}_benchmark_results.csv` |
| `--workers`             | Parallel workers                                              | 4                                      |
| `--date`                | Override CSV dates with explicit date(s)                      | -                                      |
| `--start-date`          | Override CSV dates with range start (inclusive)               | -                                      |
| `--end-date`            | Override CSV dates with range end (inclusive)                 | -                                      |
| `--include-asset-class` | Only process these asset classes                              | All                                    |
| `--exclude-asset-class` | Skip these asset classes                                      | None                                   |
| `--feed-id`             | Only process these feed IDs                                   | All                                    |
| `--list-asset-classes`  | List asset classes in CSV and exit                            | -                                      |
| `--extended-hours`      | Include pre-market and after-hours evaluation for US equities | Disabled                               |
| `--overnight`           | Include overnight session evaluation for US equities          | Disabled                               |
| `--hit-rate-threshold`  | Hit rate threshold for conditional pass                       | `95`                                   |
| `--skip-scipy-tests`    | Skip t-test/Wilcoxon/normality metrics for speed              | Disabled                               |

## Date Override Behavior

Input CSV rows are `feed_id,date,mode`.

- Default behavior: uses each row's date as-is.
- With `--date` or `--start-date/--end-date`: CSV date column is ignored.
- Override mode evaluates each unique `(feed_id, mode)` pair across all selected dates.

## Output

Results CSV contains:

| Column             | Meaning                             |
| ------------------ | ----------------------------------- |
| `publisher_id`     | The publisher that was evaluated    |
| `feed_id`          | The feed that was evaluated         |
| `date`             | Evaluation date                     |
| `symbol`           | Feed symbol (e.g., EUR/USD)         |
| `passes`           | `True` if pass criteria are met     |
| `n_observations`   | Number of matched data points       |
| `rmse`             | Root Mean Square Error vs benchmark |
| `mean_spread`      | Average benchmark spread            |
| `rmse_over_spread` | RMSE divided by spread              |
| `error`            | Error message if evaluation failed  |

## Pass/Fail Criteria

- **Publisher PASSES** if: `nrmse < 0.01` OR (`nrmse < 0.05` AND `hit_rate >= 95%`)
- `nrmse` = RMSE normalized by benchmark price range (lower is better)
- `hit_rate` = % of prices within 10 basis points of benchmark (higher is better)
- Minimum 100 observations required for valid evaluation
- Use `--hit-rate-threshold` to override the default 95% (e.g., `--hit-rate-threshold 98`)

### Per-Session Thresholds (US Equities)

Extended hours use relaxed thresholds:

| Session                              | nrmse_auto_pass | nrmse_conditional | hit_rate_threshold |
| ------------------------------------ | --------------- | ----------------- | ------------------ |
| Regular (all asset classes)          | 0.01            | 0.05              | 95%                |
| Pre-Market / After-Hours / Overnight | 0.05            | 0.15              | 85%                |

Thresholds are defined in `lib/thresholds.py`. The `--hit-rate-threshold` override only affects the regular session.

## Summary Statistics

After processing, the script outputs a summary (console + CSV):

**Core metrics:** `pass_count`, `fail_count`, `error_count`, `pass_rate_pct`

**Quality metrics (rmse_over_spread distribution):**
| Metric | Meaning |
|--------|---------|
| `median_rmse_over_spread` | 50% of feeds are below this |
| `mean_rmse_over_spread` | Average across all feeds |
| `p90_rmse_over_spread` | 90% of feeds are below this |
| `p95_rmse_over_spread` | 95% of feeds are below this |
| `min/max_rmse_over_spread` | Best/worst values |

**Interpreting rmse_over_spread:**

- `< 0.5` = Excellent (price deviation < half the spread)
- `0.5 - 1.0` = Good (within tolerance)
- `> 1.0` = Failing (deviation exceeds spread)

**Coverage metrics:** `total_observations`, `mean_observations_per_feed`

**Asset class breakdown:** `pass_count_{mode}`, `fail_count_{mode}`, `error_count_{mode}`

**Per-date breakdown (when multiple dates are evaluated):**

- Console includes `PER-DATE BREAKDOWN` with total/pass/fail/error and median quality metrics per date.
- Output CSV appends a `PER_DATE_BREAKDOWN` section after `SUMMARY`.

## Extended Hours (US Equities)

Evaluate US equities during extended trading sessions using `--extended-hours`:

```bash
python publisher_benchmark.py --csv publisher_55_feeds.csv --extended-hours
```

### Trading Sessions

| Session       | Time (EST)        | Flag Required      |
| ------------- | ----------------- | ------------------ |
| Regular Hours | 9:30 AM - 4:00 PM | Always evaluated   |
| Pre-market    | 4:00 AM - 9:30 AM | `--extended-hours` |
| After-hours   | 4:00 PM - 8:00 PM | `--extended-hours` |

### Extended Hours Output

When enabled, the CSV includes additional columns:

| Column                     | Description                       |
| -------------------------- | --------------------------------- |
| `premarket_n_observations` | Data points in pre-market session |
| `premarket_nrmse`          | NRMSE for pre-market              |
| `premarket_hit_rate`       | Hit rate for pre-market           |
| `premarket_passes`         | Pass/fail for pre-market          |
| `premarket_error`          | Error message if any              |
| `afterhours_*`             | Same metrics for after-hours      |

### Notes

- Extended hours only applies to `us-equities` asset class
- Other asset classes (fx, metals, commodity) are unaffected
- Regular hours results remain separate (not mixed with extended hours)
- Lower observation threshold (50 vs 100) for extended sessions
- Extended hours typically have lower liquidity and may have higher error rates

Example console output:

```
============================================================
SUMMARY - Publisher 55
============================================================
Pass criteria: nrmse < 0.01 OR (nrmse < 0.05 AND hit_rate >= 95%)
============================================================
Total feeds evaluated: 92
PASS: 67
FAIL: 8
Errors: 17
Pass rate: 89.3%
============================================================
Median rmse/spread: 0.3421
Mean rmse/spread: 0.4156
P90 rmse/spread: 0.7823
P95 rmse/spread: 0.9102
============================================================
BREAKDOWN BY ASSET CLASS:
  fx             :  45 pass,   3 fail,   2 error (90.0% pass rate)
  metals         :   2 pass,   0 fail,   0 error (100.0% pass rate)
```

## Complete Workflow

```bash
# 1. Discover what feeds a publisher has
python publisher_feeds.py --publisher-id 55

# 2. Check what asset classes are benchmarkable
python publisher_benchmark.py --csv publisher_55_feeds.csv --list-asset-classes

# 3. Run benchmark on supported asset classes
python publisher_benchmark.py --csv publisher_55_feeds.csv --include-asset-class fx metals us-equities

# 4. Check results
cat publisher_55_benchmark_results.csv
```
