# Quick Benchmark Tool

Evaluates **feed readiness** by benchmarking all publishers for each feed against Datascope data.

## When to Use

| Scenario                                      | Use This Tool                |
| --------------------------------------------- | ---------------------------- |
| Check if a feed has enough passing publishers | Yes                          |
| Batch feed readiness across many feeds        | Yes                          |
| Evaluate one specific publisher in depth      | Use `publisher_benchmark.py` |

## Usage

```bash
# Process feeds from CSV file
python quick_benchmark.py --csv price_id_list.csv

# Process a single feed
python quick_benchmark.py --feed-id 327 --date 2025-10-06 --mode fx

# Process a single feed for multiple explicit dates
python quick_benchmark.py --feed-id 327 --date 2025-10-06 2025-10-07 --mode fx

# Process a single feed for an inclusive date range
python quick_benchmark.py --feed-id 327 --start-date 2025-10-06 --end-date 2025-10-10 --mode fx

# Custom output and readiness threshold
python quick_benchmark.py --csv feeds.csv --output results.csv --target-pub-count 6

# Faster processing with more workers
python quick_benchmark.py --csv price_id_list.csv --workers 8

# US equities: include pre-market + after-hours session checks
python quick_benchmark.py --feed-id 1163 --date 2025-10-02 --mode us-equities --extended-hours

# US equities: include overnight check against reference publisher 32
python quick_benchmark.py --feed-id 1163 --date 2025-10-02 --mode us-equities --overnight

# Skip scipy statistical tests for faster runs
python quick_benchmark.py --csv price_id_list.csv --skip-scipy-tests

# Append per-publisher detail rows to output CSV
python quick_benchmark.py --csv price_id_list.csv --detailed

# Multi-date detailed run with cross-date publisher consistency summary
python quick_benchmark.py --feed-id 922 --start-date 2026-02-09 --end-date 2026-02-12 \
  --mode us-equities --extended-hours --overnight --detailed --workers 16 --output 922_test.csv

# Restrict CSV run to specific feed IDs
python quick_benchmark.py --csv price_id_list.csv --filter-feed-id 327 1163
```

## Arguments

| Argument                | Description                                                                                          | Default                       |
| ----------------------- | ---------------------------------------------------------------------------------------------------- | ----------------------------- |
| `--csv`                 | CSV file with `feed_id,date,mode` rows                                                               | -                             |
| `--feed-id`             | Single feed ID to evaluate                                                                           | -                             |
| `--date`                | Date(s) for single-feed mode (`YYYY-MM-DD` list)                                                     | -                             |
| `--start-date`          | Range start date (inclusive) for single-feed mode                                                    | -                             |
| `--end-date`            | Range end date (inclusive) for single-feed mode                                                      | -                             |
| `--mode`                | Single-feed mode: `fx`, `metals`, `us-equities`, `commodity`, `us-treasuries`, `treasuries`, `rates` | -                             |
| `--output`              | Output CSV path                                                                                      | `quick_benchmark_results.csv` |
| `--target-pub-count`    | Minimum passing publishers for feed readiness                                                        | `4`                           |
| `--workers`             | Parallel worker threads                                                                              | `4`                           |
| `--include-asset-class` | Only process these asset classes (CSV mode only)                                                     | All                           |
| `--exclude-asset-class` | Exclude these asset classes (CSV mode only)                                                          | None                          |
| `--extended-hours`      | Include US equities pre-market + after-hours checks                                                  | Off                           |
| `--overnight`           | Include US equities overnight checks vs publisher `32`                                               | Off                           |
| `--skip-scipy-tests`    | Skip t-test / Wilcoxon / normality metrics                                                           | Off                           |
| `--detailed`            | Append per-publisher detail rows to CSV                                                              | Off                           |
| `--filter-feed-id`      | Only process these feed IDs (CSV mode only)                                                          | All                           |
| `--hit-rate-threshold`  | Hit rate threshold for conditional pass (Path 2)                                                     | `95`                          |
| `--list-asset-classes`  | List unique asset classes in CSV and exit                                                            | Off                           |

## Input Mode Rules

- Use either `--csv` **or** single-feed mode (`--feed-id`, `--mode`, and either `--date` or `--start-date/--end-date`).
- `--date` and `--start-date/--end-date` are mutually exclusive.
- `--include-asset-class`, `--exclude-asset-class`, `--filter-feed-id`, and `--list-asset-classes` apply to CSV mode only.
- `--extended-hours` and `--overnight` only apply to `us-equities`; other modes run normal regular-session checks.

## Pass/Fail Criteria

- Publisher **passes** if:
  - `nrmse < 0.01` (auto-pass), or
  - `nrmse < 0.05` and `hit_rate >= 95%` (conditional pass, default threshold)
- `nrmse = RMSE / (max_benchmark_price - min_benchmark_price)`
- `hit_rate = percent of matched observations within 10 bps (0.1%) of benchmark`
- Feed is **READY** if `passing_pub_count >= target_pub_count`.
- Use `--hit-rate-threshold` to override the regular session hit rate (e.g., `--hit-rate-threshold 98`).

### Per-Session Thresholds (US Equities)

US equities extended hours use relaxed thresholds due to lower liquidity and wider spreads:

| Session                              | nrmse_auto_pass | nrmse_conditional | hit_rate_threshold |
| ------------------------------------ | --------------- | ----------------- | ------------------ |
| Regular (all asset classes)          | 0.01            | 0.05              | 95%                |
| Pre-Market / After-Hours / Overnight | 0.05            | 0.15              | 85%                |

Non-US-equity asset classes (FX, metals, commodities, treasuries) always use regular thresholds. Thresholds are defined in `lib/thresholds.py`.

## Session Behavior

- Regular session:
  - For `us-equities`, uses regular market-hours filtering (9:30 AM to 4:00 PM ET).
  - Other asset classes use standard query behavior.
- `--extended-hours` (US equities only):
  - Pre-market: 4:00 AM to 9:30 AM ET
  - After-hours: 4:00 PM to 8:00 PM ET
- `--overnight` (US equities only):
  - 8:00 PM to 4:00 AM ET (next day), compared against reference publisher `32`.

## Output

Base output CSV columns:

| Column                                     | Meaning                                           |
| ------------------------------------------ | ------------------------------------------------- |
| `feed_id`, `date`, `mode`, `symbol`        | Feed identity                                     |
| `ready`                                    | Feed readiness result                             |
| `target_pub_count`                         | Required passing publisher count                  |
| `passing_pub_count`, `failing_pub_count`   | Pass/fail publisher counts                        |
| `passing_publishers`, `failing_publishers` | Semicolon-separated publisher IDs                 |
| `median_nrmse`, `median_hit_rate`          | Median per-publisher quality metrics for the feed |
| `error`                                    | Feed-level error (if any)                         |
| `execution_time_ms`                        | Feed evaluation time                              |

Additional columns when `--extended-hours` is enabled:

- `premarket_passing_count`
- `premarket_failing_count`
- `afterhours_passing_count`
- `afterhours_failing_count`

Additional columns when `--overnight` is enabled:

- `overnight_passing_count`
- `overnight_failing_count`
- `overnight_reference_publisher_id`

Additional section when `--detailed` is enabled:

- Adds a `PUBLISHER DETAIL` section after feed-level rows.
- Includes per-publisher metrics such as `nrmse`, `hit_rate`, `rmse_over_spread`,
  statistical metrics (`mean_diff`, `t_pvalue`, `wilcoxon_pvalue`, etc.),
  plus session-specific detail columns when `--extended-hours` / `--overnight` are used.
- If more than one unique date is evaluated, appends a `PUBLISHER SUMMARY` section:
  - Cross-date matrix per `publisher_id` for regular session (`PASS`, `FAIL`, `ERROR`)
  - Optional premarket/afterhours columns with `--extended-hours`
  - Optional overnight columns with `--overnight`
  - Pass/fail counts and pass rates per session

Console additions for multi-date detailed runs:

- Prints `PUBLISHER CONSISTENCY (across N dates)` after summary + interpretation.
- Includes regular-session table for all publishers.
- Includes premarket/afterhours and overnight tables when enabled.
- Uses short `MM-DD` date labels in console and full `YYYY-MM-DD` in CSV.

When multiple dates are evaluated in single-feed mode, console output includes a per-date readiness breakdown.

## Asset Class Filtering

```bash
# List asset classes in a CSV file
python quick_benchmark.py --csv publisher_11_feeds.csv --list-asset-classes

# Include only benchmarkable classes
python quick_benchmark.py --csv feeds.csv --include-asset-class fx metals us-equities commodity us-treasuries

# Exclude unsupported classes
python quick_benchmark.py --csv feeds.csv --exclude-asset-class crypto funding-rate nav crypto-redemption-rate
```

Alias normalization is supported (for example, `rates` and `treasuries` map to `us-treasuries`).

See [Asset Classes](./asset-classes.md) for the full list.
