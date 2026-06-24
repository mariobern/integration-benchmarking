# Publisher Asset Map — International Equity + Session Tracking — Design

**Date:** 2026-06-24
**Status:** Approved (pending spec review)
**Extends:** `publisher_asset_map` (PR #45), spec
`2026-06-24-publisher-asset-map-design.md`

## Problem

Two gaps in `publisher_asset_map`:

1. **International equities all collapse to `equity-us`.** Lazer equity symbols are
   formatted `Equity.<CC>.<TICKER>/<CCY>` (e.g. `Equity.CN.600519/CNY`,
   `Equity.HK.0700/HKD`, `Equity.DE.ADS/EUR`). The current `get_equity_country` in
   `lib/asset_class.py` matches **RIC-style suffixes** (`.HK`, `.T`, `.KS`), which never
   match these symbols (they end in `/CNY`, `/EUR`, …), so every equity defaults to
   `us`. We cannot tell who publishes HK/JP/KR/CN/etc. equities. This bug also affects
   `publisher_feeds.py`, which shares the same lib function.

2. **No US-equity session breakdown.** US equities trade across pre-market, regular,
   after-hours, and overnight sessions, but the tool aggregates the full day. We cannot
   tell who publishes which symbols in which session.

## Goal

- Categorize equities by country from the `Equity.<CC>.` prefix (fix in shared lib).
- Add a `session` dimension to the output that buckets US-equity activity into
  pre-market / regular / after-hours / overnight; non-US rows carry `session = all`.

## Scope decisions (resolved during brainstorming)

| Decision                | Choice                                                          |
| ----------------------- | --------------------------------------------------------------- |
| Country fix location    | Shared `lib/asset_class.py` (corrects `publisher_feeds.py` too) |
| Session representation  | A `session` column in the detail CSV (its own dimension)        |
| Session scope           | US equities only (`Equity.US.%`)                                |
| Non-US session value    | `all` (whole-day; NOT `regular` — avoids filter collisions)     |
| Session bucketing basis | Each update's ET wall-clock time (tiles 24h, DST-aware)         |
| Matrix CSV              | Unchanged / session-agnostic (publisher × asset_class)          |

## 1. Country categorization fix (`lib/asset_class.py`)

Extend `get_equity_country(symbol)` to parse the Lazer prefix first:

- Split `symbol` on `.`. If the first segment is `Equity` and there are at least 3
  segments, return `segments[1].lower()` (the country code).
- Otherwise fall back to the existing `EQUITY_COUNTRY_MAP` RIC-suffix lookup.
- Otherwise default to `us`.

`categorize_asset_class(asset_type, symbol)` is unchanged in shape: for equities it
returns `equity-<country>`. No fixed country allow-list — codes are derived from the
symbol, so new countries work automatically.

Examples:

```
Equity.US.AAPL/USD   → us  → equity-us
Equity.US.EMH6/USD   → us  → equity-us   (futures; second segment still US)
Equity.HK.0700/HKD   → hk  → equity-hk
Equity.CN.600519/CNY → cn  → equity-cn
Equity.DE.ADS/EUR    → de  → equity-de
AAPL                 → us  → equity-us   (no prefix, no suffix → default)
VOD.L                → gb  → equity-gb   (RIC-suffix fallback preserved)
```

Backward compatible: the RIC-suffix fallback means any existing RIC-formatted caller is
unaffected; US equities still map to `equity-us`.

## 2. Session classification (US equities only)

Each update is bucketed by its **ET wall-clock time** into one session. In SQL this uses
`toTimeZone(publish_time, 'America/New_York')`; the minute-of-day boundaries are derived
from the existing constants in `lib/sql_filters.py` (single source of truth):

| session      | ET window   | minute-of-day      |
| ------------ | ----------- | ------------------ |
| `premarket`  | 04:00–09:30 | `[240, 570)`       |
| `regular`    | 09:30–16:00 | `[570, 960)`       |
| `afterhours` | 16:00–20:00 | `[960, 1200)`      |
| `overnight`  | 20:00–04:00 | `>= 1200 or < 240` |

These tile the full 24h ET clock with no gaps or overlaps, so every update lands in
exactly one session. DST is handled automatically by the timezone conversion.

Only symbols matching `Equity.US.%` are bucketed; all other symbols get
`session = 'all'`. A new helper `session_case_sql(column, symbol_column)` in
`lib/publisher_asset_map_core.py` builds the SQL expression from the `sql_filters`
constants:

```sql
multiIf(
  <symbol_col> NOT LIKE 'Equity.US.%', 'all',
  m >= 1200 OR m < 240, 'overnight',
  m < 570,  'premarket',
  m < 960,  'regular',
  'afterhours'
)
-- where m = toHour(et)*60 + toMinute(et), et = toTimeZone(<column>, 'America/New_York')
```

The grouped query then groups by `(publisher_id, feed_id, asset_type, symbol, session)`.

## 3. Output schema changes

### Detail — `publisher_asset_map_<date>.csv`

Adds a `session` column:

```csv
publisher_id,publisher_name,feed_id,symbol,asset_class,session,update_count
28,MEMX.Production,1163,Equity.US.AAPL/USD,equity-us,regular,84210
28,MEMX.Production,1163,Equity.US.AAPL/USD,equity-us,premarket,5120
32,Blueocean.Production,2001,Equity.HK.0700/HKD,equity-hk,all,9044
1,Lazer.Binance,1,Crypto.BTC/USD,crypto,all,1473951
```

A US-equity feed active in N sessions yields N rows. Detail rows are sorted by
`(publisher_id, asset_class, feed_id, session)`.

### Summary — `publisher_asset_map_summary_<date>.csv`

Now keyed by `(publisher, asset_class, session)`:

```csv
publisher_id,publisher_name,asset_class,session,feed_count,total_updates
28,MEMX.Production,equity-us,premarket,300,1500000
28,MEMX.Production,equity-us,regular,302,25400110
32,Blueocean.Production,equity-hk,all,40,360000
```

Sorted by `(publisher_id, asset_class, session)`.

### Matrix — `publisher_asset_map_matrix_<date>.csv`

**Unchanged / session-agnostic**: one row per publisher, one column per asset class,
distinct-feed counts. A US-equity feed counts once in `equity-us` regardless of how many
sessions it appears in (`feeds_by_asset_class` / `build_matrix` already dedupe by
`feed_id`). The matrix remains the high-level "who touches what asset class" view;
session detail lives in detail + summary.

### Console summary

In addition to the existing block (publishers seen, unique feeds, per-asset-class
distinct-feed counts), print a small per-session distinct-feed count for US equities,
e.g.:

```
US-equity feeds by session:
  premarket: 300
  regular: 302
  afterhours: 280
  overnight: 64
```

## Code structure & testing

- **`lib/asset_class.py`**: extend `get_equity_country` (prefix parse + suffix fallback).
  Tests: `Equity.US.AAPL/USD`→us, `Equity.HK.0700/HKD`→hk, `Equity.CN.600519/CNY`→cn,
  `Equity.JP.7203/JPY`→jp, `Equity.KR.005930/KRW`→kr, `Equity.DE.ADS/EUR`→de,
  futures `Equity.US.EMH6/USD`→us, RIC fallback `VOD.L`→gb, plain `AAPL`→us, None/""→us.
  Confirm `categorize_asset_class` returns `equity-hk` etc.
- **`lib/publisher_asset_map_core.py`**:
  - Add `session_case_sql(column, symbol_column)` built from `sql_filters` constants.
  - Add `session: str` to `PublisherFeedRow`.
  - Update the query (SELECT/GROUP BY include the session expression).
  - Update `build_summary` to key by `(publisher_id, asset_class, session)` and emit the
    `session` column.
  - Update `write_outputs` detail + summary writers (new column, new sort keys).
  - `build_matrix` and `feeds_by_asset_class` are unchanged (session-agnostic).
  - Add `feeds_by_session(rows)` helper for the console US-equity per-session counts.
  - Tests (fake client): session bucketing for US-equity rows across the four ET
    windows, `all` for non-US symbols, summary keyed by session, detail/summary CSV
    columns and sort order, matrix still session-agnostic.
- **`publisher_asset_map.py`**: print the per-session US-equity console block via
  `feeds_by_session`.
- **`docs/publisher_asset_map.md`**: document the `session` column, the four sessions +
  `all`, the international-equity categorization, and updated CSV schemas.

All changes land on the existing `feat/publisher-asset-map` branch (PR #45).

## Non-goals (YAGNI)

- No per-session split for non-US equities (international equities keep `session = all`;
  their local sessions are out of scope).
- No session dimension in the matrix CSV.
- No change to the date model (still a single full UTC day; sessions are a per-update
  ET-clock label within that day, not an ET-trading-date realignment).
- No new CLI flags (session breakdown is always produced).
