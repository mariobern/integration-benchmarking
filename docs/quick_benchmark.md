# Quick Benchmark Tool

Evaluates **all publishers** for a feed to determine feed readiness.

## When to Use

| Scenario | Use This Tool |
|----------|---------------|
| Check if a feed has enough publishers | Yes |
| Full feed readiness assessment | Yes |
| Evaluate one specific publisher | Use `publisher_benchmark.py` instead |

## Usage

```bash
# Process feeds from CSV file
python quick_benchmark.py --csv price_id_list.csv

# Process a single feed
python quick_benchmark.py --feed-id 327 --date 2025-10-06 --mode fx

# Custom output and target publisher count
python quick_benchmark.py --csv feeds.csv --output results.csv --target-pub-count 6

# Faster processing with more workers
python quick_benchmark.py --csv price_id_list.csv --workers 8
```

## Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--csv` | CSV file with feed_id,date,mode columns | - |
| `--feed-id` | Single feed ID to evaluate | - |
| `--date` | Date for single feed (YYYY-MM-DD) | - |
| `--mode` | Market type: `fx`, `metals`, `us-equities`, `commodity` | - |
| `--output` | Output CSV path | `quick_benchmark_results.csv` |
| `--target-pub-count` | Min publishers for feed readiness | 4 |
| `--workers` | Parallel workers | 4 |
| `--include-asset-class` | Only process these asset classes | All |
| `--exclude-asset-class` | Skip these asset classes | None |
| `--list-asset-classes` | List asset classes in CSV and exit | - |

## Output

Results CSV contains:

| Column | Meaning |
|--------|---------|
| `feed_id` | The feed that was evaluated |
| `ready` | `True` if feed has enough passing publishers |
| `passing_pub_count` | Number of publishers that passed |
| `failing_pub_count` | Number of publishers that failed |
| `passing_publishers` | IDs of passing publishers (semicolon-separated) |
| `error` | Error message if evaluation failed |

## Pass/Fail Criteria

- **Publisher PASSES** if: `rmse_over_spread <= 1.0`
- **Feed is READY** if: `passing_publishers >= target_pub_count` (default: 4)

## Asset Class Filtering

```bash
# List asset classes in a CSV file
python quick_benchmark.py --csv publisher_11_feeds.csv --list-asset-classes

# Include only benchmarkable asset classes
python quick_benchmark.py --csv feeds.csv --include-asset-class fx metals us-equities commodity

# Exclude unsupported asset classes
python quick_benchmark.py --csv feeds.csv --exclude-asset-class crypto funding-rate rates
```

See [Asset Classes](./asset-classes.md) for the full list.
