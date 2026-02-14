# Feed Uptime Tool

Measures **per-publisher uptime** for each feed/date/mode tuple from a feed-centric view.

This is the feed-level counterpart to `verify_uptime.py`:
- `verify_uptime.py`: one publisher across many feeds
- `feed_uptime.py`: one or many feeds, with all contributing publishers

## When to Use

| Scenario | Use This Tool |
|----------|---------------|
| Compare publishers on the same feed | Yes |
| Batch uptime checks across many feeds/dates | Yes |
| Validate 1s-window vs gap-based methods for one publisher | Use `verify_uptime.py` |

## Usage

```bash
# CSV mode (feed_id,date,mode rows)
python feed_uptime.py --csv price_id_list.csv

# Single feed/date
python feed_uptime.py --feed-id 922 --date 2026-02-09 --mode us-equities

# Multi-date range
python feed_uptime.py --feed-id 922 --start-date 2026-02-09 --end-date 2026-02-12 --mode us-equities

# US equities sessions
python feed_uptime.py --feed-id 922 --date 2026-02-09 --mode us-equities --extended-hours --overnight

# CSV filters
python feed_uptime.py --csv feeds.csv --include-asset-class us-equities fx
python feed_uptime.py --csv feeds.csv --exclude-asset-class crypto
python feed_uptime.py --csv feeds.csv --filter-feed-id 922 327
python feed_uptime.py --csv feeds.csv --list-asset-classes

# Controls
python feed_uptime.py --csv feeds.csv --uptime-threshold 95
python feed_uptime.py --csv feeds.csv --precise --gap-threshold 100
python feed_uptime.py --csv feeds.csv --output results.csv --workers 8
```

## Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--csv` | CSV with `feed_id,date,mode` rows | - |
| `--feed-id` | Feed ID(s) (single-feed mode) | - |
| `--date` | Date(s) `YYYY-MM-DD` | - |
| `--start-date` / `--end-date` | Inclusive date range | - |
| `--mode` | Asset class (single-feed mode) | - |
| `--output` | Output CSV path | `feed_uptime_results.csv` |
| `--workers` | Parallel workers | `4` |
| `--include-asset-class` | Only these classes (CSV mode) | All |
| `--exclude-asset-class` | Exclude these classes (CSV mode) | None |
| `--list-asset-classes` | List classes and exit (CSV mode) | Off |
| `--filter-feed-id` | Only these feed IDs (CSV mode) | All |
| `--extended-hours` | Include premarket + afterhours (US equities) | Off |
| `--overnight` | Include overnight session (US equities) | Off |
| `--precise` | Use 200ms gap-based method instead of default 1s window | Off |
| `--gap-threshold` | Gap threshold in ms for `--precise` mode | `200` |
| `--uptime-threshold` | Pass threshold percentage | `95.0` |

## Input Mode Rules

- Use either `--csv` **or** single-feed mode (`--feed-id`, `--mode`, and either `--date` or `--start-date/--end-date`).
- `--date` and `--start-date/--end-date` are mutually exclusive.
- `--include-asset-class`, `--exclude-asset-class`, `--filter-feed-id`, and `--list-asset-classes` are CSV-only.
- `--gap-threshold` customization requires `--precise`.

## Uptime Methods

### Default: 1-second window

- Uptime is `seconds_with_data / total_seconds * 100`.
- Consistent with portal-style window uptime interpretation.

### `--precise`: gap-based

- Computes gaps between consecutive updates.
- For each gap above threshold, downtime contribution is `gap_ms - threshold_ms`.
- Includes start/end gap handling.
- Threshold is controlled by `--gap-threshold` (default `200ms`).

## Session Behavior

Session windows come from `portal.batch.uptime_sessions.get_session_windows(...)`.

- Default includes regular sessions.
- `--extended-hours` adds premarket and afterhours for US equities.
- `--overnight` adds overnight for US equities.
- For non-US-equities, extended/overnight flags are ignored.

## Output

Detail output is long-format: one row per `(feed_id, date, publisher_id, session)`.

### Default detail columns (1-second window)

| Column | Meaning |
|--------|---------|
| `feed_id`, `date`, `mode`, `symbol` | Feed identity |
| `publisher_id`, `session` | Publisher/session identity |
| `uptime_pct` | Uptime percentage |
| `passes` | `uptime_pct >= uptime_threshold` |
| `seconds_with_data`, `total_seconds` | 1-second method coverage |
| `updates_total`, `updates_per_second` | Update volume and rate |

### `--precise` detail columns

| Column | Meaning |
|--------|---------|
| `feed_id`, `date`, `mode`, `symbol` | Feed identity |
| `publisher_id`, `session` | Publisher/session identity |
| `uptime_pct` | Uptime percentage |
| `passes` | `uptime_pct >= uptime_threshold` |
| `downtime_ms`, `period_length_ms` | Gap-method downtime/period |
| `updates_total`, `updates_per_second` | Update volume and rate |
| `max_gap_ms`, `gaps_over_threshold` | Gap severity/count |

### Appended publisher summary matrix (multi-date runs)

When multiple dates are evaluated, CSV appends:

- blank line
- `PUBLISHER SUMMARY`
- one row per publisher with per-session date pass/fail rollups:
  - `{session}_pass_dates`
  - `{session}_fail_dates`
  - `{session}_pass_rate`
  - `{session}_results` (e.g., `02-09:PASS;02-10:FAIL`)

## Console Summary

Console output includes:
- total feeds evaluated
- unique publisher-feed combinations
- method (`1s window` or `{N}ms gap-based`)
- pass threshold
- per-session uptime distribution + pass/fail counts
- timing
- publisher consistency section for multi-date runs
