# Publisher Asset Map

Maps what **every** publisher published on a specific ET trading date, across all asset
classes. Complements `publisher_feeds.py` (which covers a single publisher in a
short rolling window) by giving a sampled, all-publisher view.

## Usage

```bash
# All publishers, sampled probe windows (default grid)
python3 publisher_asset_map.py --date 2026-06-23

# Filter to one asset class
python3 publisher_asset_map.py --date 2026-06-23 --asset-class metal

# Custom output directory
python3 publisher_asset_map.py --date 2026-06-23 --output-dir output_csv
```

## Arguments

| Argument               | Description                                         | Default      |
| ---------------------- | --------------------------------------------------- | ------------ |
| `--date`               | ET trading date to analyze (`YYYY-MM-DD`), required | -            |
| `--output-dir`         | Directory for the three CSV outputs                 | `output_csv` |
| `--asset-class`        | Optional asset-class filter (e.g. `metal`, `fx`)    | All          |
| `--probe-interval-min` | Spacing between probe windows in minutes            | `30`         |
| `--probe-width-min`    | Probe window width in minutes                       | `2`          |

## How it works

For one **ET trading date**, the tool samples short **probe windows** on a uniform
24h grid (default: every 30 min, 2 min wide; tunable via `--probe-interval-min` and
`--probe-width-min`) rather than scanning the whole day. It runs one windowed
`count()` query per US-equity trading session (premarket / regular / afterhours /
overnight) and labels each update's session by which probe window it fell in. This
keeps the query fast (~2–3 min vs ~13 min for a full-day scan) while covering every
market's hours.

Equities are categorized by country from the Lazer symbol prefix
`Equity.<CC>.<TICKER>/<CCY>` (e.g. `Equity.HK.0700/HKD` -> `equity-hk`,
`Equity.US.AAPL/USD` -> `equity-us`). Only US-equity symbols (`Equity.US.*`) are
split by session; every other row (fx, metals, crypto, international equities) uses
`session = all`.

## Outputs

Three CSVs (with the date in each filename), written to `--output-dir`:

| File                                     | Granularity                                                                                   | Columns                                                                                     |
| ---------------------------------------- | --------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
| `publisher_asset_map_<date>.csv`         | one row per (publisher, feed, session)                                                        | `publisher_id, publisher_name, feed_id, symbol, asset_class, session, sampled_update_count` |
| `publisher_asset_map_summary_<date>.csv` | per (publisher, asset_class, session)                                                         | `publisher_id, publisher_name, asset_class, session, feed_count, sampled_total_updates`     |
| `publisher_asset_map_matrix_<date>.csv`  | one row per publisher (session-agnostic; a US-equity feed counts once regardless of sessions) | `publisher_id, publisher_name, <one column per asset_class>` (feed counts)                  |

Feeds with no metadata are reported as `asset_class=unknown` with a blank symbol;
publishers with no name match get a blank `publisher_name`.

> **Sampled counts:** `sampled_update_count` / `sampled_total_updates` are updates
> observed within the probe windows, NOT full-day totals. A publisher absent from a
> session's probes has no row for that session (the implicit "silent" signal).

> A US-equity feed active in multiple sessions appears as multiple detail rows
> (one per session). The matrix counts each feed once per asset class.
