# Publisher Benchmark Tool

Evaluates a **single publisher's** data quality. Faster than `quick_benchmark.py` because it only queries one publisher.

## When to Use

| Scenario | Use This Tool |
|----------|---------------|
| Evaluate one specific publisher | Yes |
| Onboard a new publisher | Yes |
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
```

## Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--csv` | CSV file with feed_id,date,mode columns (required) | - |
| `--publisher-id` | Publisher ID to evaluate | Extracted from filename |
| `--output` | Output CSV path | `publisher_{id}_benchmark_results.csv` |
| `--workers` | Parallel workers | 4 |
| `--include-asset-class` | Only process these asset classes | All |
| `--exclude-asset-class` | Skip these asset classes | None |
| `--list-asset-classes` | List asset classes in CSV and exit | - |

## Output

Results CSV contains:

| Column | Meaning |
|--------|---------|
| `publisher_id` | The publisher that was evaluated |
| `feed_id` | The feed that was evaluated |
| `symbol` | Feed symbol (e.g., EUR/USD) |
| `passes` | `True` if rmse/spread <= 1.0 |
| `n_observations` | Number of matched data points |
| `rmse` | Root Mean Square Error vs benchmark |
| `mean_spread` | Average benchmark spread |
| `rmse_over_spread` | RMSE divided by spread |
| `error` | Error message if evaluation failed |

## Pass/Fail Criteria

- **Publisher PASSES** if: `rmse_over_spread <= 1.0`
- Minimum 100 observations required for valid evaluation

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

Example console output:
```
============================================================
SUMMARY - Publisher 55
============================================================
Total feeds evaluated: 92
PASS (rmse/spread <= 1.0): 67
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
