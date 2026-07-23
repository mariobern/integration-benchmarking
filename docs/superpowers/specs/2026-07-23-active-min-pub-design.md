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
   channel = lowest-numbered channel with data, probing 1 → 2 → 3).
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
   (channel = lowest with data, 1→2→3)           (open hrs only)
```

### Universe & floors

Source of truth: `lazer_newest.json` (new-format, session-only publisher lists).
`min_pub_common.iter_stable_sessions(config)` yields one `FeedSession` per
`marketSchedules` entry of each STABLE feed, already resolving:

- `effective_min_pub` — session-level `minPublishers` if present, else feed-level.
- `schedule_str` — resolved market-schedule string (for session masking).
- `symbol`, `asset_type`, `session`, `feed_id`.

DEPRECATED-symbol feeds are skipped by the loader. ~2,554 STABLE feed-sessions.

### Session coverage (US equities)

US-equities feeds carry each trading session as a **distinct `marketSchedules`
entry** — REGULAR, PRE_MARKET, POST_MARKET, OVER_NIGHT — each with its own
`allowedPublisherIds`, its own `minPublishers`, and its own resolved schedule
string. This means every session gets a **standalone analysis row automatically**,
with no special-casing:

- **One row per session** — `iter_stable_sessions()` yields one `FeedSession` per
  entry, so PRE_MARKET / POST_MARKET / OVER_NIGHT each get their own verdict.
- **Per-session floor** — e.g. AAPL is REGULAR `minPublishers=3` vs 2 for the others;
  each session is judged against its own floor.
- **Per-session mask** — the resolved schedule strings are genuinely distinct per
  session (REGULAR `0930-1600`, PRE_MARKET `0400-0930`, POST_MARKET `1600-2000`,
  OVER_NIGHT `0000-0400 & 2000-2400`), so updates are masked to the correct window
  with no cross-contamination.

Because this analysis only reads `price_feeds.publisher_count` and never touches a
Datascope benchmark, **OVER_NIGHT needs no special-casing** (unlike `quick_benchmark`,
which requires `--overnight` + publisher-32 peer logic) — it is just another masked
window. The only masking subtlety is that OVER_NIGHT crosses midnight and has two
disjoint intervals per day; this is covered by an explicit test case.

### Query & channel selection

The config's `minChannel` is **symbolic** (`{'realTime': {}}` or `{'rate': {}}`),
not the numeric `channel` the `price_feeds` table keys on — so it can't be used
directly. The transcript's intent is "the highest-frequency channel = the lowest
number (~50ms)". We implement that with the proven pattern from
`lib/benchmark_core.py`: **probe channels 1 → 2 → 3 and use the lowest-numbered
channel that returns rows** (channel 1 = real-time/fastest).

Per feed, over `[start, end)`:

```sql
SELECT publish_time, publisher_count
FROM price_feeds
WHERE price_feed_id = {feed_id:UInt64}
  AND channel = {channel:UInt8}
  AND publish_time >= {start:String}
  AND publish_time < {end:String}
```

Client: `lazer_clickhouse_prod` (via `lib.config`). Parameterized-query syntax
(`{name:Type}` + `parameters=dict`). One query per feed covers all its sessions
(sessions are separated afterward by masking, not by re-querying).

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
n_updates, min, p1, p5, median, pct_at_floor, pct_at_floor_1, verdict
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
- `--start-date` is inclusive and `--end-date` is **exclusive** UTC dates; the
  query window is `[start 00:00:00, end 00:00:00)` — consistent with the sibling
  `audit_min_pub` tool. (E.g. `--start-date 2026-07-14 --end-date 2026-07-22`
  covers 07-14 through 07-21.)

## Testing

`lazer_dq/tests/test_active_min_pub.py`, mocking ClickHouse rows:

- Stat correctness on a known `counts[]` array (min, p1, p5, median, pct_at_floor,
  pct_at_floor_1).
- Verdict boundaries: exactly-at `critical_pct`, `pct_at_floor==0` with/without
  `warn_pct`, LOW_SAMPLE at `n_updates == min_updates - 1` vs `== min_updates`,
  NO_DATA at `n_updates == 0`.
- Session masking: updates outside open hours are excluded from `counts[]`.
- OVER_NIGHT midnight-crossing, multi-interval mask (`0000-0400 & 2000-2400`)
  keeps only updates inside either interval.
- Channel probing: when channel 1 has no rows, falls through to 2 then 3, and
  uses the first channel that returns data.

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
