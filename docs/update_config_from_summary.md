# Config Update from Summary CSV (update_config_from_summary.py)

Updates `after.json` publisher allowlists from a `feed_readiness.py` summary CSV. Filters out Test/Lazer publishers, intersects publishers across dates per feed, and sets per-session `allowedPublisherIds` in `marketSchedules`.

## Usage

```bash
# Dry run (preview changes without writing)
python3 update_config_from_summary.py --summary mario_tickers_summary.csv --config after.json --dry-run

# Apply changes (creates backup at after.json.bak)
python3 update_config_from_summary.py --summary mario_tickers_summary.csv --config after.json
```

## Arguments

| Argument    | Description                           | Required |
| ----------- | ------------------------------------- | -------- |
| `--summary` | Path to feed_readiness summary CSV    | Yes      |
| `--config`  | Path to after.json config file        | Yes      |
| `--dry-run` | Print changes without writing to file | No       |

## What It Does

For each feed in the summary CSV:

1. **Groups rows by feed_id** — a feed may appear on multiple dates
2. **Filters publishers** — removes 28 excluded IDs:
   - 24 Test publishers (`.Test` suffix): 23, 25, 27, 30, 31, 33, 36, 38, 39, 40, 43, 46, 47, 49, 51, 53, 56, 58, 60, 61, 63, 66, 68, 70
   - 4 Lazer publishers (`Lazer.` prefix): 1, 9, 13, 15
3. **Intersects across dates** — for each session, only publishers that passed on **every** date are included (conservative approach)
4. **Updates after.json** per feed:
   - Top-level `allowedPublisherIds`: union of all sessions
   - Top-level `minPublishers`: set to `1`
   - Per-session `allowedPublisherIds` and `minPublishers` inside `marketSchedules`
   - State: `COMING_SOON` → `STABLE` (already-STABLE feeds get publisher lists updated)
5. **Adds missing sessions** — for US equities feeds, creates `PRE_MARKET`, `POST_MARKET`, and `OVER_NIGHT` entries if the CSV shows passing publishers for those sessions
6. Creates a backup at `{config}.bak` before writing

## Input Format

The summary CSV is produced by `feed_readiness.py --summary`. Required columns:

```
feed_id,symbol,date,mode,fully_passing_count,target_pub_count,
median_nrmse,median_hit_rate,median_uptime_pct,fully_passing_publishers,
premarket_ready,premarket_fully_passing_count,premarket_fully_passing_publishers,
afterhours_ready,afterhours_fully_passing_count,afterhours_fully_passing_publishers,
overnight_ready,overnight_fully_passing_count,overnight_fully_passing_publishers
```

Publisher columns use semicolon-separated IDs (e.g., `12;19;20;21;22`). Empty string means no publishers for that session.

### Generating the Input CSV

```bash
# Run feed_readiness with --summary to generate the CSV
python3 feed_readiness.py --csv feeds.csv --extended-hours --overnight --summary mario_tickers_summary.csv

# For multiple dates, run on each date and concatenate (keeping one header):
python3 feed_readiness.py --csv feeds_day1.csv --extended-hours --overnight --summary day1.csv
python3 feed_readiness.py --csv feeds_day2.csv --extended-hours --overnight --summary day2.csv
head -1 day1.csv > combined.csv
tail -n +2 day1.csv >> combined.csv
tail -n +2 day2.csv >> combined.csv
```

## Per-Session Handling

| CSV Column                            | after.json Session | minPublishers |
| ------------------------------------- | ------------------ | ------------- |
| `fully_passing_publishers`            | `REGULAR`          | 3             |
| `premarket_fully_passing_publishers`  | `PRE_MARKET`       | 2             |
| `afterhours_fully_passing_publishers` | `POST_MARKET`      | 2             |
| `overnight_fully_passing_publishers`  | `OVER_NIGHT`       | 1             |

Extended sessions (`PRE_MARKET`, `POST_MARKET`, `OVER_NIGHT`) are only processed for `us-equities` mode. FX, metals, commodity, and treasury feeds use regular session only.

When adding new session entries to `marketSchedules`, the script uses holiday calendar templates from feed 922 (AAPL).

## Surgical JSON Modification

Like `update_lazer_symbols.py`, this script uses regex-based surgical replacements to preserve the original protobuf-JSON formatting of `after.json`. Only target fields are changed; all other fields and formatting are preserved exactly.

## Output

Console output shows per-feed results:

```
Reading summary from mario_tickers_summary.csv
Found 31 unique feeds across CSV rows

  OK: AAPL (feedId=922) -> STABLE, regular=[12, 19, 22, ...], premarket=[19, 22], ...
  UPDATE: MSFT (feedId=925) -> updated, regular=[12, 19, ...], premarket=[19, ...]
  SKIP: AIQ (feedId=930) -> no passing publishers after filtering
  WARNING: feedId=999 not found in config

==================================================
SUMMARY
==================================================
  Newly STABLE:             17
  Updated (already STABLE): 14
  Skipped (empty):          0
  Not found in config:      0
  Total processed:          31/31
```

- **OK** — `COMING_SOON` feed promoted to `STABLE`
- **UPDATE** — already-`STABLE` feed with publisher lists refreshed
- **SKIP** — feed had no passing publishers after filtering test/lazer
- **WARNING** — feed ID from CSV not found in after.json

## Safety Features

- `--dry-run` mode previews all changes without writing
- Backup created automatically before overwriting (`after.json.bak`)
- Only `COMING_SOON` and `STABLE` feeds are modified (other states like `INACTIVE` are skipped)
- Sessions with empty publisher intersection are not added
- Warns about feed IDs not found in the config

## Compared to update_lazer_symbols.py

| Feature                | `update_lazer_symbols.py`      | `update_config_from_summary.py`    |
| ---------------------- | ------------------------------ | ---------------------------------- |
| Input format           | Markdown summary table         | CSV from `feed_readiness.py`       |
| Feed matching          | By ticker name                 | By feed_id                         |
| Publisher source       | "Consistent Publishers" column | Per-session `fully_passing_*` cols |
| Publisher filtering    | None                           | Removes Test + Lazer publishers    |
| Multi-date handling    | N/A                            | Intersection across dates          |
| Per-session publishers | No (top-level only)            | Yes (REGULAR, PRE/POST, OVERNIGHT) |
| State handling         | COMING_SOON → STABLE only      | Both COMING_SOON and STABLE        |
| Adds missing sessions  | No                             | Yes (US equities only)             |

## Running Tests

```bash
pytest tests/test_update_config_from_summary.py -v
```
