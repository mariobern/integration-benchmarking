# Publisher Asset Map

Maps what **every** publisher published on a specific UTC date, across all asset
classes. Complements `publisher_feeds.py` (which covers a single publisher in a
short rolling window) by giving a full-day, all-publisher view.

## Usage

```bash
# Full day, all publishers
python3 publisher_asset_map.py --date 2026-06-23

# Filter to one asset class
python3 publisher_asset_map.py --date 2026-06-23 --asset-class metal

# Custom output directory
python3 publisher_asset_map.py --date 2026-06-23 --output-dir output_csv
```

## Arguments

| Argument        | Description                                      | Default      |
| --------------- | ------------------------------------------------ | ------------ |
| `--date`        | UTC day to analyze (`YYYY-MM-DD`), required      | -            |
| `--output-dir`  | Directory for the three CSV outputs              | `output_csv` |
| `--asset-class` | Optional asset-class filter (e.g. `metal`, `fx`) | All          |

## How it works

Runs one grouped aggregation over `publisher_updates` for the full UTC day
(`[date 00:00:00, date+1 00:00:00)`), joining `feeds_metadata_latest` for symbol
and asset type, then joins publisher names live from `publishers_metadata_latest`.
Equities are categorized by ISO country code from the symbol suffix
(`.L` → `equity-gb`, `.HK` → `equity-hk`, etc.; plain symbols → `equity-us`).

> **Performance:** this scans a full day of `publisher_updates` across all
> publishers — heavier than `publisher_feeds.py`'s 1-minute snapshot, but a single
> grouped aggregation ClickHouse handles well.

## Outputs

Three CSVs (with the date in each filename), written to `--output-dir`:

| File                                     | Granularity                  | Columns                                                                    |
| ---------------------------------------- | ---------------------------- | -------------------------------------------------------------------------- |
| `publisher_asset_map_<date>.csv`         | one row per (publisher,feed) | `publisher_id, publisher_name, feed_id, symbol, asset_class, update_count` |
| `publisher_asset_map_summary_<date>.csv` | per (publisher, asset_class) | `publisher_id, publisher_name, asset_class, feed_count, total_updates`     |
| `publisher_asset_map_matrix_<date>.csv`  | one row per publisher        | `publisher_id, publisher_name, <one column per asset_class>` (feed counts) |

Feeds with no metadata are reported as `asset_class=unknown` with a blank symbol;
publishers with no name match get a blank `publisher_name`.
