# Feed Readiness Tool

Evaluates **combined feed readiness** by running both:

- benchmark quality (`quick_benchmark_95.py` logic)
- publisher uptime (`feed_uptime.py` logic)

A feed is marked **READY** only if enough publishers pass **both** checks.

## When to Use

| Scenario | Use This Tool |
|----------|---------------|
| Single verdict that combines benchmark + uptime | Yes |
| Batch readiness checks across many feeds/dates | Yes |
| Benchmark-only analysis | Use `quick_benchmark.py` / `quick_benchmark_95.py` |
| Uptime-only analysis | Use `feed_uptime.py` |

## Usage

```bash
# Single feed, single date
python feed_readiness.py --feed-id 327 --date 2026-02-10 --mode fx

# Multi-date range
python feed_readiness.py --feed-id 327 --start-date 2026-02-10 --end-date 2026-02-12 --mode fx

# CSV batch
python feed_readiness.py --csv price_id_list.csv --workers 8

# With uptime precision + extended hours (US equities)
python feed_readiness.py --feed-id 922 --date 2026-02-10 --mode us-equities --precise --extended-hours

# Detailed output (publisher rows + consistency section)
python feed_readiness.py --feed-id 327 --date 2026-02-10 --mode fx --detailed
```

## Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--csv` | CSV with `feed_id,date,mode` rows | - |
| `--feed-id` | Feed ID(s) (single-feed mode) | - |
| `--date` | Date(s) `YYYY-MM-DD` | - |
| `--start-date` / `--end-date` | Inclusive date range | - |
| `--mode` | Asset class (single-feed mode) | - |
| `--output` | Output CSV path | `feed_readiness_results.csv` |
| `--detailed` | Append publisher detail + consistency sections | Off |
| `--target-pub-count` | Minimum fully-passing publishers for readiness | `4` |
| `--skip-scipy-tests` | Skip benchmark statistical tests for faster runs | Off |
| `--precise` | Use gap-based uptime method instead of 1-second window | Off |
| `--gap-threshold` | Gap threshold in ms for `--precise` mode | `200` |
| `--uptime-threshold` | Regular-session uptime pass threshold | `95.0` |
| `--extended-hours` | Include premarket + afterhours for US equities | Off |
| `--overnight` | Include overnight session for US equities | Off |
| `--workers` | Parallel workers | `4` |
| `--include-asset-class` | Only these classes (CSV mode) | All |
| `--exclude-asset-class` | Exclude these classes (CSV mode) | None |
| `--filter-feed-id` | Only these feed IDs (CSV mode) | All |
| `--list-asset-classes` | List asset classes in CSV and exit | Off |

## Input Mode Rules

- Use either `--csv` **or** single-feed mode (`--feed-id`, `--mode`, and either `--date` or `--start-date/--end-date`).
- `--date` and `--start-date/--end-date` are mutually exclusive.
- `--include-asset-class`, `--exclude-asset-class`, `--filter-feed-id`, and `--list-asset-classes` are CSV-only.
- `--gap-threshold` customization requires `--precise`.

## Readiness Logic

Per publisher:

- `benchmark_passes`: benchmark pass/fail from `PublisherFeedMetrics.passes`
- `uptime_passes`: regular-session pass/fail from `PublisherSessionUptime.passes`
- `fully_passes`: `benchmark_passes AND uptime_passes`

Per feed:

- `ready`: `fully_passing_count >= target_pub_count`
- `benchmark_ready`: benchmark passing publishers >= target
- `uptime_ready`: regular-session uptime passing publishers >= target

Publisher bucket classification:

- `fully_passing`
- `benchmark_only`
- `uptime_only`
- `both_failing`

Publishers missing from one side are treated as failing that side.

## Benchmarkable Modes

Benchmark checks run only for benchmarkable asset classes (`fx`, `metals`, `us-equities`, `commodity`, `us-treasuries`).

For non-benchmarkable modes:

- `benchmark_error` is set to `Asset class not benchmarkable`
- uptime still runs
- combined `ready` is `False`

## Output

### Feed-level CSV rows

Base output includes:

- identity: `feed_id`, `date`, `mode`, `symbol`
- readiness booleans: `ready`, `benchmark_ready`, `uptime_ready`
- threshold/counts: `target_pub_count`, `fully_passing_count`,
  `benchmark_only_passing_count`, `uptime_only_passing_count`, `both_failing_count`,
  `total_publisher_count`
- benchmark metrics: `benchmark_passing_count`, `benchmark_failing_count`,
  `median_nrmse`, `median_hit_rate`
- uptime metrics: `uptime_passing_count`, `uptime_failing_count`, `median_uptime_pct`
- publisher ID lists: `fully_passing_publishers`, `benchmark_only_publishers`,
  `uptime_only_publishers`, `both_failing_publishers`
- errors/timing: `benchmark_error`, `uptime_error`, `error`, `execution_time_ms`

Optional columns:

- with `--extended-hours`: `premarket_passing_count`, `afterhours_passing_count`
- with `--overnight`: `overnight_passing_count`

### Detailed section (`--detailed`)

CSV appends:

- blank line
- `PUBLISHER DETAIL`
- one row per publisher per feed/date with:
  - `fully_passes`, `benchmark_passes`, `uptime_passes`
  - benchmark metrics (`benchmark_nrmse`, `benchmark_hit_rate`, `benchmark_n_observations`)
  - `uptime_pct`
  - `benchmark_error`, `uptime_error`

### Consistency section (multi-date + `--detailed`)

When multiple dates are evaluated, CSV appends:

- `PUBLISHER CONSISTENCY` (cross-date pass/fail matrix)
- `PUBLISHER CLASSIFICATIONS`
  - `regular_always_passing`
  - `regular_always_failing`
  - `regular_intermittent`

## Console Summary

Console output includes:

- combined readiness rates (both pass, benchmark-only ready, uptime-only ready)
- benchmark distributions (`NRMSE`, `Hit rate`)
- regular-session uptime distribution
- per-asset-class breakdown
- optional per-date breakdown (multi-date)
- timing summary

With multi-date and `--detailed`, a `PUBLISHER CONSISTENCY` report is also printed.
