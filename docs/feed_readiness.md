# Feed Readiness Tool

Evaluates **combined feed readiness** by running both:

- benchmark quality (`quick_benchmark.py` logic via `lib/benchmark_core.py`)
- publisher uptime (`feed_uptime.py` logic via `lib/uptime_core.py`)

A feed is marked **READY** only if enough publishers pass **both** checks.

## When to Use

| Scenario                                        | Use This Tool            |
| ----------------------------------------------- | ------------------------ |
| Single verdict that combines benchmark + uptime | Yes                      |
| Batch readiness checks across many feeds/dates  | Yes                      |
| Benchmark-only analysis                         | Use `quick_benchmark.py` |
| Uptime-only analysis                            | Use `feed_uptime.py`     |

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

# CSV batch with READY-only summary
python feed_readiness.py --csv price_id_list.csv --summary
```

## Arguments

| Argument                      | Description                                            | Default                      |
| ----------------------------- | ------------------------------------------------------ | ---------------------------- |
| `--csv`                       | CSV with `feed_id,date,mode` rows                      | -                            |
| `--feed-id`                   | Feed ID(s) (single-feed mode)                          | -                            |
| `--date`                      | Date(s) `YYYY-MM-DD`                                   | -                            |
| `--start-date` / `--end-date` | Inclusive date range                                   | -                            |
| `--mode`                      | Asset class (single-feed mode)                         | -                            |
| `--output`                    | Output CSV path                                        | `feed_readiness_results.csv` |
| `--detailed`                  | Append publisher detail + consistency sections         | Off                          |
| `--target-pub-count`          | Minimum fully-passing publishers for readiness         | `4`                          |
| `--skip-scipy-tests`          | Skip benchmark statistical tests for faster runs       | Off                          |
| `--precise`                   | Use gap-based uptime method instead of 1-second window | Off                          |
| `--gap-threshold`             | Gap threshold in ms for `--precise` mode               | `200`                        |
| `--uptime-threshold`          | Regular-session uptime pass threshold                  | `95.0`                       |
| `--extended-hours`            | Include premarket + afterhours for US equities         | Off                          |
| `--overnight`                 | Include overnight session for US equities              | Off                          |
| `--workers`                   | Parallel workers                                       | `4`                          |
| `--include-asset-class`       | Only these classes (CSV mode)                          | All                          |
| `--exclude-asset-class`       | Exclude these classes (CSV mode)                       | None                         |
| `--filter-feed-id`            | Only these feed IDs (CSV mode)                         | All                          |
| `--summary`                   | Write a summary CSV of READY feeds only                | Off                          |
| `--list-asset-classes`        | List asset classes in CSV and exit                     | Off                          |

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

### Asset-Class Thresholds

Commodity and metals feeds use relaxed benchmark thresholds (NRMSE auto-pass < 0.05,
conditional < 0.15, hit rate >= 85%) due to lower liquidity and wider spreads. This is
automatic — no CLI flag needed. See `lib/thresholds.py` for the full routing logic.

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

Optional per-session readiness columns (with `--extended-hours` / `--overnight`):

For each session (`premarket`, `afterhours`, `overnight`):

- `{session}_ready` — boolean, session-level readiness
- `{session}_fully_passing_count` — publishers passing both benchmark and uptime for this session
- `{session}_fully_passing_publishers` — semicolon-separated publisher IDs
- `{session}_uptime_passing_count`, `{session}_uptime_failing_count`
- `{session}_median_uptime_pct`

Legacy columns (still present for backward compatibility):

- `premarket_benchmark_passing_count`, `afterhours_benchmark_passing_count`, `overnight_benchmark_passing_count`

### Detailed section (`--detailed`)

CSV appends:

- blank line
- `PUBLISHER DETAIL`
- one row per publisher per feed/date with:
  - `fully_passes`, `benchmark_passes`, `uptime_passes`
  - benchmark metrics (`benchmark_nrmse`, `benchmark_hit_rate`, `benchmark_n_observations`)
  - `uptime_pct`
  - `benchmark_error`, `uptime_error`
  - extended session metrics (when `--extended-hours` / `--overnight`), per session:
    `{session}_benchmark_passes`, `{session}_benchmark_nrmse`,
    `{session}_benchmark_hit_rate`, `{session}_benchmark_n_observations`,
    `{session}_uptime_pct`, `{session}_uptime_passes`

### Consistency section (multi-date + `--detailed`)

When multiple dates are evaluated, CSV appends:

- `PUBLISHER CONSISTENCY` (cross-date pass/fail matrix for regular hours)
- `PUBLISHER CLASSIFICATIONS`
  - `regular_always_passing`
  - `regular_always_failing`
  - `regular_intermittent`

With `--extended-hours`, additional sections are appended for each extended session:

- `PREMARKET PUBLISHER CONSISTENCY` + `PREMARKET PUBLISHER CLASSIFICATIONS`
  - `premarket_always_passing`, `premarket_always_failing`, `premarket_intermittent`
- `AFTERHOURS PUBLISHER CONSISTENCY` + `AFTERHOURS PUBLISHER CLASSIFICATIONS`
  - `afterhours_always_passing`, `afterhours_always_failing`, `afterhours_intermittent`

With `--overnight`, an additional section is appended:

- `OVERNIGHT PUBLISHER CONSISTENCY` + `OVERNIGHT PUBLISHER CLASSIFICATIONS`
  - `overnight_always_passing`, `overnight_always_failing`, `overnight_intermittent`

Session consistency uses the same pass logic as regular hours: a publisher PASSES a session if both session-specific benchmark AND session-specific uptime pass. Publishers with no data for a session (0% uptime or null) are excluded from that session's table.

## Console Summary

Console output includes:

- combined readiness rates (both pass, benchmark-only ready, uptime-only ready)
- benchmark distributions (`NRMSE`, `Hit rate`)
- regular-session uptime distribution
- per-asset-class breakdown
- optional per-date breakdown (multi-date)
- timing summary

With `--extended-hours` or `--overnight`, an **EXTENDED SESSION READINESS** table is printed showing per-session readiness rates:

```
EXTENDED SESSION READINESS
Session      Ready  Fully Pass  Uptime Pass  Median Uptime
premarket    3/5    3           4            98.50%
afterhours   2/5    2           3            96.20%
overnight    1/5    1           2            91.40%
```

With multi-date and `--detailed`, a `PUBLISHER CONSISTENCY` report is also printed.

## Summary CSV (`--summary`)

When `--summary` is used, a second CSV is written containing only feeds with `ready=True`.
The file uses a curated subset of columns for quick readability and sharing.

**Default filename:** `feed_readiness_summary.csv` (or `<stem>_summary.csv` if `--output` is customized).

### Columns (always present)

| Column                     | Description                                            |
| -------------------------- | ------------------------------------------------------ |
| `feed_id`                  | Feed identifier                                        |
| `symbol`                   | Human-readable symbol name                             |
| `date`                     | Evaluation date                                        |
| `mode`                     | Asset class                                            |
| `fully_passing_count`      | Number of publishers passing both benchmark and uptime |
| `target_pub_count`         | Required publisher threshold                           |
| `median_nrmse`             | Median NRMSE across publishers                         |
| `median_hit_rate`          | Median hit rate (%) across publishers                  |
| `median_uptime_pct`        | Median uptime (%) for regular session                  |
| `fully_passing_publishers` | Semicolon-separated publisher IDs                      |

### Extended session columns (with `--extended-hours`)

| Column                                | Description                       |
| ------------------------------------- | --------------------------------- |
| `premarket_ready`                     | Pre-market session readiness      |
| `premarket_fully_passing_count`       | Publishers passing pre-market     |
| `premarket_fully_passing_publishers`  | Pre-market passing publisher IDs  |
| `afterhours_ready`                    | After-hours session readiness     |
| `afterhours_fully_passing_count`      | Publishers passing after-hours    |
| `afterhours_fully_passing_publishers` | After-hours passing publisher IDs |

### Overnight columns (with `--overnight`)

| Column                               | Description                     |
| ------------------------------------ | ------------------------------- |
| `overnight_ready`                    | Overnight session readiness     |
| `overnight_fully_passing_count`      | Publishers passing overnight    |
| `overnight_fully_passing_publishers` | Overnight passing publisher IDs |

Session publisher-list columns use semicolon-separated publisher IDs (for example, `12;13;19`). These fields are empty strings when the session is disabled, unavailable, or has no passing publishers.
