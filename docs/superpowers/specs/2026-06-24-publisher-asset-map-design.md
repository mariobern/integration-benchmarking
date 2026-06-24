# Publisher Asset Map — Design

**Date:** 2026-06-24
**Status:** Approved (pending spec review)

## Problem

We can currently see what a *single* publisher is publishing via `publisher_feeds.py`
(`--publisher-id N`), which captures a short rolling time-window snapshot. There is no
way to see, in one pass, what **every** publisher is contributing across asset classes.

We want to map asset-class contribution per publisher: for a given day, which feeds each
publisher sent us, what asset class each feed is, and how active the publisher was on it.

## Goal

A new script that, for a specific UTC date, produces a feed-level map of what every
publisher published, plus rolled-up summary and matrix views.

The feed-level dump is the crucial deliverable; the summary and matrix are convenience
rollups.

## Scope decisions (resolved during brainstorming)

| Decision            | Choice                                                                              |
| ------------------- | ----------------------------------------------------------------------------------- |
| Output granularity  | Feed-level detail **plus** long-form summary **plus** wide matrix                   |
| Time scope          | Specific date — full 24h UTC view (`00:00:00`–`24:00:00`)                            |
| Data source         | `publisher_updates` (precise, per-update)                                            |
| Detail columns      | `publisher_id, publisher_name, feed_id, symbol, asset_class, update_count`           |
| Publisher names     | Live from `publishers_metadata_latest` (not the static `publishers.md`)             |
| Packaging           | Three CSV files                                                                     |
| Code structure      | New script + extract shared asset-class categorization into `lib/asset_class.py`    |

## Architecture

### New components

1. **`lib/asset_class.py`** — shared asset-class categorization, extracted from
   `publisher_feeds.py` (single source of truth):
   - `EQUITY_COUNTRY_MAP` — symbol suffix → ISO country code
   - `get_equity_country(symbol) -> str`
   - `categorize_asset_class(asset_type, symbol) -> str` (equity → `equity-<country>`)

2. **`publisher_asset_map.py`** — thin CLI wrapper:
   - Parses args, connects via `lib/config.get_lazer_client()`.
   - Runs the grouped query, fetches publisher names, categorizes asset classes.
   - Writes three CSVs and prints a console summary.

3. **`docs/publisher_asset_map.md`** — usage docs (linked from the Scripts table in
   `CLAUDE.md`).

### Refactor

Move the three categorization functions + `EQUITY_COUNTRY_MAP` out of
`publisher_feeds.py` into `lib/asset_class.py`; update `publisher_feeds.py` to import
them. Behavior of `publisher_feeds.py` is unchanged.

## CLI

```bash
python3 publisher_asset_map.py --date 2026-06-23
python3 publisher_asset_map.py --date 2026-06-23 --asset-class metal
python3 publisher_asset_map.py --date 2026-06-23 --output-dir output_csv
```

| Argument             | Description                                                  | Default      |
| -------------------- | ------------------------------------------------------------ | ------------ |
| `--date`             | UTC day to analyze (`YYYY-MM-DD`), required                  | -            |
| `--output-dir`       | Directory for the three CSVs                                 | `output_csv` |
| `--asset-class`      | Optional filter (e.g. `metal`, `fx`, `equity-us`)           | All          |
| `--include-inactive` | Include publishers flagged inactive in `publishers_metadata` | Off          |

## Data flow

1. Connect via `lib/config.load_config()` + `lib/config.get_lazer_client()`.

2. One grouped aggregation over `publisher_updates` for the date:

   ```sql
   SELECT
       pu.publisher_id,
       pu.price_feed_id AS feed_id,
       count() AS update_count,
       fm.asset_type,
       fm.symbol
   FROM publisher_updates pu
   LEFT JOIN feeds_metadata_latest fm ON pu.price_feed_id = fm.pyth_lazer_id
   WHERE pu.publish_time >= {start:DateTime}
     AND pu.publish_time <  {end:DateTime}
   GROUP BY pu.publisher_id, pu.price_feed_id, fm.asset_type, fm.symbol
   ORDER BY pu.publisher_id, fm.asset_type, pu.price_feed_id
   ```

   (`start` = `<date> 00:00:00`, `end` = next day `00:00:00`; parameterized query.)

3. Fetch `publisher_id → name` (and active flag) from `publishers_metadata_latest`.

4. For each row, derive `asset_class` via `lib.asset_class.categorize_asset_class`.

5. Apply optional `--asset-class` filter (equity-country aware, matching the existing
   script's post-filter behavior).

## Outputs (three CSVs, date in filename)

**Detail — `publisher_asset_map_<date>.csv`** (with header):

```csv
publisher_id,publisher_name,feed_id,symbol,asset_class,update_count
32,Blueocean.Production,1163,AAPL,equity-us,84210
32,Blueocean.Production,345,XAU/USD,metal,12044
```

**Summary — `publisher_asset_map_summary_<date>.csv`** — one row per
(publisher, asset_class):

```csv
publisher_id,publisher_name,asset_class,feed_count,total_updates
32,Blueocean.Production,equity-us,302,25400110
32,Blueocean.Production,metal,4,48120
```

**Matrix — `publisher_asset_map_matrix_<date>.csv`** — one row per publisher, one column
per asset class (feed counts), columns sorted by asset class:

```csv
publisher_id,publisher_name,equity-us,fx,metal,...
32,Blueocean.Production,302,0,4,...
```

## Console summary

Brief block: date analyzed, number of publishers seen, total unique feeds, and per
asset-class feed totals across all publishers.

## Edge cases

- **No data for the date** (non-trading day, future date, not yet ingested): print a
  friendly message, write no files, exit 0.
- **Feed with no metadata** (no `feeds_metadata_latest` match): `asset_class = unknown`,
  `symbol` blank.
- **Publisher with no name** (no `publishers_metadata_latest` match): `publisher_name`
  blank, publisher still included.
- **Performance**: a full day of `publisher_updates` across all publishers is heavier
  than the existing 1-minute snapshot, but it is a single grouped aggregation that
  ClickHouse handles well. Document this in the script docs.

## Non-goals (YAGNI)

- No rolling-window / "current snapshot" mode (that is what `publisher_feeds.py` does).
- No first/last update timestamps per feed.
- No Excel/`.xlsx` output.
- No multi-date ranges in a single run.

## Testing

- Unit-test `lib/asset_class.py` categorization (equity suffixes, non-equity passthrough,
  empty/None symbol → `us`).
- Verify `publisher_feeds.py` still works after the refactor (imports from new module).
- Manual smoke test against a recent date; confirm the three CSVs and the console summary.
