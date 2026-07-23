# active_min_pub — Aggregate Publisher-Count Headroom Sweep

**Date:** 2026-07-23
**Status:** Design approved, pending implementation plan
**Module:** `lazer_dq/active_min_pub.py`

## Background & Motivation

A report run on 2026-07-22 attempted to answer "how many feeds run close to their
`minPublishers` floor?" using the wrong methodology. It measured **per-minute distinct
ACCEPTED publishers from the `publisher_updates` table** (via `audit_min_pub`) — a
per-minute *union of individual submissions*. That count is inflated and does not
reflect what any single aggregate price update actually used.

The correct question, per the design walkthrough (transcript `active_min_pub_220726.txt`):

> "When we produce an aggregate, how many effective publishers have been at play for
> every single update? ... Each aggregate has a number of publishers that have
> contributed. The number of publishers over time creates that histogram/distribution
> that we want to compare to min pub. **Not like for a single update for one minute** —
> the update is actually at the aggregate level."

The authoritative signal is the **aggregate's own `publisher_count`** on the
`price_feeds` table: one value per aggregate update, equal to the actual number of
publishers that contributed to that aggregate. The distribution of that value over a
multi-day window, per feed-session, compared against `minPublishers`, is what
identifies feeds needing feed-by-feed remediation.

## Relationship to the existing min_pub pipeline

This is a **new standalone script**, not a replacement for `audit_min_pub`. The two
answer genuinely different questions and must not be confused:

| Script | Question | Source | Metric | Granularity |
|---|---|---|---|---|
| `audit_min_pub` (Stage 1) | Publisher *availability* | `publisher_updates` | distinct ACCEPTED publishers | per minute |
| `active_min_pub` (new) | Aggregate *contributor-count headroom* | `price_feeds` | `publisher_count` on the aggregate | per aggregate update |

Both scripts get a one-line docstring note stating this distinction. The existing
deployed pipeline (Stage 1/2/3) is left untouched. This script identifies the feeds;
the option to later wire its output into the existing Stage 2/3 remediation is left
open but is out of scope here.

## Goal

For every STABLE `(feed, session)` in `lazer_newest.json`, over a multi-day window:

1. Fetch the aggregate `publisher_count` per update from `price_feeds` (highest-freq
   channel = the feed's `minChannel`).
2. Session-mask to the session's open hours.
3. Compute the contributor-count distribution and a per-feed verdict driven by how
   often the aggregate scrapes/breaches the `minPublishers` floor.
4. Emit a per-feed-session CSV + console summary of feeds needing remediation.

## Scope

**In scope:**
- New module `lazer_dq/active_min_pub.py` (thin CLI + parallel fetch).
- Per-feed-session CSV + console summary.
- Unit tests (`lazer_dq/tests/test_active_min_pub.py`).
- Docs: `docs/active_min_pub.md`, Scripts-table row, one CLAUDE.md gotcha line.

**Out of scope:**
- Any change to `audit_min_pub`, `qualify_candidates`, `apply_min_pub_remediation`
  (beyond the one-line docstring distinction note).
- Actually remediating feeds (feed-by-feed edits) — this script only *identifies*.
- Wiring output into the existing Stage 2/3 pipeline.

## Data Flow

```
lazer_newest.json ──iter_stable_sessions()──▶ [(feed, session, min_pub, schedule_str)]
                                                        │  per feed-session
price_feeds  ──publisher_count per aggregate──▶  session-mask ──▶ counts[]  ──▶ stats + verdict
   (channel = feed.minChannel)                   (open hrs only)
```

### Universe & floors

Source of truth: `lazer_newest.json` (new-format, session-only publisher lists).
`min_pub_common.iter_stable_sessions(config)` yields one `FeedSession` per
`marketSchedules` entry of each STABLE feed, already resolving:

- `effective_min_pub` — session-level `minPublishers` if present, else feed-level.
- `schedule_str` — resolved market-schedule string (for session masking).
- `symbol`, `asset_type`, `session`, `feed_id`.

DEPRECATED-symbol feeds are skipped by the loader. ~2,554 STABLE feed-sessions.

### Query

Per feed, over `[start, end)`, using the feed's own `minChannel` as the
highest-frequency channel (no channel probing):

```sql
SELECT publish_time, publisher_count
FROM price_feeds
WHERE price_feed_id = {feed_id:UInt64}
  AND channel = {channel:UInt8}
  AND publish_time >= {start:String}
  AND publish_time < {end:String}
```

Client: `lazer_clickhouse_prod` (via `lib.config`). Parameterized-query syntax
(`{name:Type}` + `parameters=dict`).

### Session masking

Reuse `market_schedule.parse_market_schedule` + `open_minutes_mask` to keep only
`publish_time` values inside the session's open hours before computing statistics.
Closed-hours thin prints are excluded so they don't pollute the histogram.

## Statistics & Verdict

All statistics are computed from the single masked `counts[]` array (numpy):

| Field | Meaning |
|---|---|
| `min` | minimum contributor count observed in-session |
| `p1`, `p5` | 1st / 5th percentile of contributor count |
| `median` | median contributor count |
| `pct_at_floor` | fraction of in-session updates with `publisher_count <= min_pub` — **primary trigger** |
| `pct_at_floor_1` | fraction with `publisher_count <= min_pub + 1` (context) |
| `worst_day_min` | lowest single-day `min` across the window (catches one bad day) |
| `n_updates` | total in-session aggregate updates (conclusiveness guard) |

`pct_at_floor` / `pct_at_floor_1` are reported as percentages (0–100).

### Verdict logic

Thresholds are CLI-tunable; defaults in parentheses:

- **CRITICAL** — `pct_at_floor >= critical_pct` (default **1.0%**): regularly at/below floor.
- **WARN** — `pct_at_floor == 0` AND `pct_at_floor_1 >= warn_pct` (default **5.0%**):
  living one publisher above the floor.
- **OK** — otherwise.
- **LOW_SAMPLE** — `n_updates < min_updates` (default **100**): too few in-session
  updates for a confident verdict; reported separately, not counted as OK/WARN/CRITICAL.
- **NO_DATA** — `n_updates == 0`: feed didn't trade / not ingested in window; surfaced
  separately, never silently dropped.

Ordering precedence for a feed-session: NO_DATA > LOW_SAMPLE > CRITICAL > WARN > OK.

## Output

### Per-feed-session CSV

`output_csv/active_min_pub_<start>_<end>.csv`, one row per feed-session:

```
feed_id, symbol, asset_type, session, effective_min_pub,
n_updates, min, p1, p5, median, pct_at_floor, pct_at_floor_1,
worst_day_min, verdict
```

Sorted by verdict precedence (CRITICAL first), then `pct_at_floor` descending.

### Console summary

- Verdict tally (count of CRITICAL / WARN / OK / LOW_SAMPLE / NO_DATA).
- CRITICAL list: `feed_id, symbol, session, min_pub, pct_at_floor` — the immediate
  feed-by-feed action list.
- NO_DATA and LOW_SAMPLE feed lists surfaced separately (no silent truncation).

## CLI & Structure

```bash
python3 -m lazer_dq.active_min_pub \
    --config lazer_newest.json \
    --start-date 2026-07-14 --end-date 2026-07-22 \
    [--critical-pct 1.0] [--warn-pct 5.0] [--min-updates 100] [--workers 8]
```

- Thin CLI wrapper; parallel per-feed fetch via `ThreadPoolExecutor` (mirrors
  `audit_min_pub`'s concurrency shape).
- Reuse: `min_pub_common.iter_stable_sessions`, `market_schedule` helpers,
  `lib.config` ClickHouse client.
- `--start-date` / `--end-date` are inclusive UTC dates; the query window is
  `[start 00:00:00, (end+1) 00:00:00)`.

## Testing

`lazer_dq/tests/test_active_min_pub.py`, mocking ClickHouse rows:

- Stat correctness on a known `counts[]` array (min, p1, p5, median, pct_at_floor,
  pct_at_floor_1).
- Verdict boundaries: exactly-at `critical_pct`, `pct_at_floor==0` with/without
  `warn_pct`, LOW_SAMPLE at `n_updates == min_updates - 1` vs `== min_updates`,
  NO_DATA at `n_updates == 0`.
- Session masking: updates outside open hours are excluded from `counts[]`.
- `worst_day_min` picks the lowest single-day minimum across a multi-day window.
- `minChannel` is used for the query (no channel probing).

## Documentation

- `docs/active_min_pub.md` — usage, output schema, verdict semantics, and the
  explicit contrast with `audit_min_pub`.
- Scripts table row in `CLAUDE.md`.
- One "Key Gotchas" line in `CLAUDE.md`: `active_min_pub` uses `price_feeds.publisher_count`
  (aggregate contributors), NOT `publisher_updates` per-minute distinct — the two answer
  different questions.

## Open Questions / Future Work

- Whether to later feed CRITICAL feed-sessions into the existing Stage 2/3 remediation
  pipeline (out of scope now).
- Whether closed-session feeds (24h FX/metals maintenance windows) need special-casing
  beyond the standard session mask — assumed handled by `market_schedule` for v1.
