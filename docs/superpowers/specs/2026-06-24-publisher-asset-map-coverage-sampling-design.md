# Publisher Asset Map — Coverage Sampling (exact counts, sampled hours) — Design

**Date:** 2026-06-24
**Status:** Approved (pending spec review)
**Supersedes:** the session data-layer of
`2026-06-24-publisher-asset-map-sessions-intl-equity-design.md` (the
international-equity country fix from that spec is KEPT; the exhaustive
full-day session query is REPLACED by this design).

## Problem

The exhaustive approach scans a full UTC day of `publisher_updates` and buckets
every update into a session via per-row `toTimeZone`. Measured runtime is
10–15 minutes (scan-bound; the count and the timezone math are cheap, the
full-day **scan** is the cost). That is impractical for routine use.

The tool's real purpose is to map **who publishes which symbols, in which
session** — a coverage question, not an exact-volume question. `publisher_updates`
is time-ordered, so narrow time-range queries use the primary index and read
only that slice (a 10-min window probe returns in ~20s vs 13+ min for the day).

## Approach

Sample a few short **probe windows** inside each trading session instead of
scanning the whole day. Report **real update counts within the probes**
(not full-day totals). Session is determined by **which probe window** an update
falls in — eliminating per-row `toTimeZone` entirely.

## Scope decisions (resolved during brainstorming)

| Decision                 | Choice                                                                     |
| ------------------------ | -------------------------------------------------------------------------- |
| Metric                   | Exact update counts, but only within sampled probe windows                 |
| Sampling default         | Uniform 24h grid: a probe every 30 min, 2 min wide (configurable)          |
| Session attribution      | By which ET session each probe falls in (no per-row `toTimeZone`)          |
| Branch                   | Replace the exhaustive session work on `feat/publisher-asset-map-sessions` |
| International equity fix | KEPT as-is (`get_equity_country` prefix parse, already implemented)        |
| Explicit gap flagging    | Out of scope (coverage data makes gaps visible; see Non-goals)             |

## Sessions and probe windows

`--date` is the **ET trading date**. Session ET ranges come from
`lib/sql_filters.py` constants:

| session      | ET range                    | length (min) |
| ------------ | --------------------------- | ------------ |
| `premarket`  | 04:00–09:30                 | 330          |
| `regular`    | 09:30–16:00                 | 390          |
| `afterhours` | 16:00–20:00                 | 240          |
| `overnight`  | 20:00 → 04:00 (next ET day) | 480          |

Probes are placed on a **uniform 24h grid**, NOT clustered per session — so that
markets with their own schedules (HK/JP/KR/CN/EU equities, etc.) get even
coverage rather than being under-sampled in the wide gaps of the 8-hour overnight
session. Starting at premarket open (04:00 ET), a probe is placed every
`interval` (default 30) minutes, each `width` (default 2) minutes wide, across
the full 24h trading day (04:00 ET `D` → 04:00 ET `D+1`). That is
`1440 / interval` probes (48 at the default).

Each probe's start time is converted to a UTC `DateTime` string using the date's
ET offset, resolved DST-aware via `zoneinfo.ZoneInfo("America/New_York")`. Each
probe is **labeled with the ET session that contains its start time** (the four
sessions tile the 24h clock, so every probe falls in exactly one). Because the
overnight session crosses ET midnight, the late probes land on the next UTC day.

A probe window is `(session_label, start_utc, end_utc)`.

**Why a uniform grid (not per-session counts):** measured on the live cluster,
query cost is ~linear in total sampled minutes (~1.7s/min) and concurrency does
NOT help (the cluster is scan-bound and already parallelizes within a query; 12
concurrent workers gave only ~20% over sequential). A uniform grid lets coverage
density and runtime be tuned by two simple knobs (`interval`, `width`) while
guaranteeing even 24h coverage. The default (every 30 min × 2 min = 96 sampled
min) runs in ~2.7 min, vs ~13 min for the exhaustive full-day scan.

## Data flow

1. Connect via `lib/config.get_lazer_client()`; fetch publisher names from
   `publishers_metadata_latest` (unchanged).
2. Compute the uniform-grid probe windows and group them by their session label.
3. Run **one query per session** (4 queries). Each query restricts
   `publish_time` to that session's probe windows (an `OR` of `[start,end)`
   ranges, parameterized) and groups by `(publisher_id, feed_id, asset_type,
symbol)` with `count() AS sampled_update_count`. No session SQL, no
   `toTimeZone`.
4. Assemble rows. For each returned row:
   - `asset_class = categorize_asset_class(asset_type or "unknown", symbol or "")`
     (the kept international-equity prefix parse).
   - `session = <this query's session label>` if `symbol` starts with
     `Equity.US.`, else `all`.
   - Accumulate per `(publisher_id, feed_id, asset_class, session)`, **summing**
     `sampled_update_count` across that session's probes (and, for `all` rows,
     across all four session queries).
5. Apply the optional `--asset-class` filter to the assembled (categorized) rows.

The four session queries run **sequentially** by default. Concurrency was
measured to give only ~20% (the cluster is scan-bound), so it is not worth the
added complexity of multiple clients; keep it simple and sequential. Print
progress as each session query completes, plus total elapsed time, so a ~2.7 min
run never looks hung.

## Output schema

The `update_count` field is renamed **`sampled_update_count`** for honesty (it
is updates seen in the probes, not a full-day total). Session column stays.

- **Detail** `publisher_asset_map_<date>.csv`:
  `publisher_id, publisher_name, feed_id, symbol, asset_class, session, sampled_update_count`
  Sorted by `(publisher_id, asset_class, feed_id, session)`.
- **Summary** `publisher_asset_map_summary_<date>.csv`: per
  `(publisher, asset_class, session)`:
  `publisher_id, publisher_name, asset_class, session, feed_count, sampled_total_updates`
  Sorted by `(publisher_id, asset_class, session)`.
- **Matrix** `publisher_asset_map_matrix_<date>.csv`: unchanged — publisher ×
  asset_class **distinct feed counts**, session-agnostic.

A US-equity feed seen in 3 sessions' probes → 3 detail rows; a feed absent from
a session's probes simply has no row for that session (gaps are visible in the
data — that is the implicit "silent" signal).

## Console summary

Print: date, publishers seen, unique feeds, per-asset-class distinct-feed counts,
the per-session US-equity distinct-feed counts, the **probe windows used** (per
session, the UTC ranges, so the sampled numbers are interpretable), and the
elapsed query time.

## CLI

| Argument               | Description                              | Default      |
| ---------------------- | ---------------------------------------- | ------------ |
| `--date`               | ET trading date (`YYYY-MM-DD`), required | -            |
| `--output-dir`         | Output directory                         | `output_csv` |
| `--asset-class`        | Optional asset-class filter              | All          |
| `--probe-interval-min` | Spacing between probe windows (minutes)  | 30           |
| `--probe-width-min`    | Probe window width in minutes            | 2            |

## Code structure

In `lib/publisher_asset_map_core.py`:

- **Remove** `_et_session_bounds` and `session_case_sql` (exhaustive-only).
- **Add** `ProbeWindow` (dataclass: `session: str`, `start_utc: str`, `end_utc: str`).
- **Add** `session_probe_windows(date_str, interval_min=30, width_min=2) -> list[ProbeWindow]`
  (pure; uniform 24h grid from premarket open, each probe labeled by the ET
  session containing it; ET ranges from `sql_filters`, DST offset from `zoneinfo`).
- **Rename** `PublisherFeedRow.update_count` → `sampled_update_count`.
- **Replace** `fetch_publisher_feeds` with `fetch_publisher_feeds(client, date_str,
interval_min=30, width_min=2, asset_class_filter=None)` running the per-session
  probe queries (sequential) and merging.
- Update `build_summary` (emit `sampled_total_updates`), `write_outputs`
  (renamed columns), and `feeds_by_session`/`feeds_by_asset_class` references to
  the renamed field. `build_matrix` stays distinct-feed counts.

In `publisher_asset_map.py`: add the two flags, pass them through, and print the
probe windows + elapsed time.

Docs: update `docs/publisher_asset_map.md` to describe sampling semantics, the
`sampled_*` columns, the probe defaults, and that counts are sampled (not
full-day).

## Testing

- `session_probe_windows`: unit-test the uniform grid (probe count =
  `1440 / interval`, width, even `interval` spacing from premarket open, correct
  session label per probe), DST-correct UTC conversion for a known date, and the
  overnight probes crossing into the next UTC day.
- `fetch_publisher_feeds` (fake client returning per-window rows): session
  attribution by window label, `all` for non-US symbols, summing across probes,
  international-equity categorization, `--asset-class` filter.
- `build_summary`/`write_outputs`: renamed columns; per-session split; matrix
  still distinct-feed and session-agnostic.
- Live smoke test: confirm the default run completes in roughly ~2–3 min (vs
  ~13 min exhaustive), with real session values for US equities, country
  segregation for international equities, and `all` for crypto/fx/intl.

## Non-goals (YAGNI)

- **Explicit gap flagging against an expected baseline** (e.g. config
  `allowedPublisherIds`). The coverage data exposes gaps implicitly; an explicit
  expected-vs-actual flag is a separate future feature.
- No full-day exact totals (that was the exhaustive approach being replaced).
- No per-session split for non-US equities (they remain `session = all`).
- No random probe placement (deterministic even spacing is reproducible and
  spreads coverage better).
