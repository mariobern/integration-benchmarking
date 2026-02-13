# Feed Uptime Tool

Measures **per-publisher uptime** for each feed/date/mode tuple using a gap-based method.

This is the feed-centric counterpart to `verify_uptime.py`:
- `verify_uptime.py`: one publisher across many feeds
- `feed_uptime.py`: one or many feeds, with all contributing publishers

## When to Use

| Scenario | Use This Tool |
|----------|---------------|
| Compare publishers on the same feed | Yes |
| Batch uptime checks across many feeds/dates | Yes |
| Compare 1-second vs gap-based uptime methods | Use `verify_uptime.py` |

## Usage

```bash
# Process feeds from CSV file
python feed_uptime.py --csv price_id_list.csv

# Process a single feed
python feed_uptime.py --feed-id 327 --date 2026-01-28 --mode fx

# Multiple feed IDs × multiple explicit dates (cartesian product)
python feed_uptime.py --feed-id 327 328 --date 2026-01-28 2026-01-29 --mode fx

# Inclusive date range
python feed_uptime.py --feed-id 327 --start-date 2026-01-28 --end-date 2026-01-31 --mode fx

# US equities sessions
python feed_uptime.py --csv feeds.csv --extended-hours --overnight

# CSV filters
python feed_uptime.py --csv feeds.csv --include-asset-class us-equities fx
python feed_uptime.py --csv feeds.csv --exclude-asset-class crypto
python feed_uptime.py --csv feeds.csv --filter-feed-id 327 1163
python feed_uptime.py --csv feeds.csv --list-asset-classes

# Threshold control
python feed_uptime.py --csv feeds.csv --one-second-gap
python feed_uptime.py --csv feeds.csv --gap-threshold 500

# Output + parallelism
python feed_uptime.py --csv feeds.csv --output feed_uptime_results.csv --workers 8
```

## Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--csv` | CSV file with `feed_id,date,mode` rows | - |
| `--feed-id` | Feed ID(s) for single-feed mode | - |
| `--date` | Date(s) for single-feed mode (`YYYY-MM-DD` list) | - |
| `--start-date` | Range start date (inclusive) for single-feed mode | - |
| `--end-date` | Range end date (inclusive) for single-feed mode | - |
| `--mode` | Asset class for single-feed mode (for example `fx`, `metals`, `us-equities`) | - |
| `--output` | Output CSV path | `feed_uptime_results.csv` |
| `--workers` | Parallel worker threads | `4` |
| `--include-asset-class` | Only process these asset classes (CSV mode only) | All |
| `--exclude-asset-class` | Exclude these asset classes (CSV mode only) | None |
| `--list-asset-classes` | List unique asset classes in CSV and exit | Off |
| `--filter-feed-id` | Only process these feed IDs (CSV mode only) | All |
| `--extended-hours` | Include `premarket` and `afterhours` sessions (US equities only) | Off |
| `--overnight` | Include `overnight` session (US equities only) | Off |
| `--one-second-gap` | Use 1000ms threshold instead of default 200ms | Off |
| `--gap-threshold` | Custom gap threshold in ms (mutually exclusive with `--one-second-gap`) | `200` |

## Input Mode Rules

- Use either `--csv` **or** single-feed mode (`--feed-id`, `--mode`, and either `--date` or `--start-date/--end-date`).
- `--date` and `--start-date/--end-date` are mutually exclusive.
- `--include-asset-class`, `--exclude-asset-class`, `--filter-feed-id`, and `--list-asset-classes` apply to CSV mode only.
- `--one-second-gap` and `--gap-threshold` cannot be used together.

## Session Behavior

Session windows come from `portal.batch.uptime_sessions.get_session_windows(...)`.

- Default: includes only regular sessions.
- `--extended-hours`: includes `premarket` + `afterhours` for US equities feeds.
- `--overnight`: includes `overnight` for US equities feeds.
- For non-US-equities asset classes, extended/overnight flags have no effect.

## Uptime Method

`feed_uptime.py` uses a gap-based uptime model only:

- For each publisher and session window, consecutive update gaps are measured.
- Downtime accumulates when `gap_ms > threshold_ms`:
  - contribution = `gap_ms - threshold_ms`
- Start/end gaps are also accounted for.
- `uptime_pct = (period_ms - downtime_ms) / period_ms * 100`

Threshold options:
- default: `200ms`
- `--one-second-gap`: `1000ms`
- `--gap-threshold N`: custom `N` ms

## Output

The output CSV is long-format: one row per `(feed_id, date, publisher_id, session)`.

Detail columns:

| Column | Meaning |
|--------|---------|
| `feed_id`, `date`, `mode`, `symbol` | Feed identity |
| `publisher_id` | Publisher in that feed |
| `session` | Session label (`regular`, `premarket`, `afterhours`, `overnight`, etc.) |
| `uptime_pct` | Uptime percentage for that publisher/session |
| `downtime_ms` | Total downtime in milliseconds |
| `period_length_ms` | Session window length in milliseconds |
| `updates_total` | Number of updates in session |
| `updates_per_second` | Average update rate in session |
| `max_gap_ms` | Largest observed inter-update gap |
| `gaps_over_threshold` | Count of gaps above threshold |

After detail rows, the file appends:

- blank line
- `FEED SUMMARY`
- per-feed/per-session aggregates:
  - `median_uptime_pct`
  - `mean_uptime_pct`
  - `min_uptime_pct`
  - `max_uptime_pct`

## Console Summary

Console output includes:
- total feeds evaluated
- unique publisher-feed combinations
- configured gap threshold
- per-session uptime distribution stats
- regular-session per-asset-class medians
- timing totals

If a feed fails to evaluate (for example, connection/query/session issues), the error is shown in console.
