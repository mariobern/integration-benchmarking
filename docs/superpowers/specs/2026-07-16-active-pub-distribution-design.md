# Active Publisher Distribution — Design

**Date:** 2026-07-16
**Status:** Approved design, pending implementation
**Owner:** Mario

## Purpose

For every STABLE (feed, session) in a new-format Lazer config, describe the
_shape_ of publisher activity over a date window, answering two questions the
min_pub audit's CRITICAL/WARN/OK classification collapses away:

1. **How close does the feed run to minPublishers, and how often?** — the
   histogram of per-minute active publisher counts. Left-skew (mass near
   `min_pub`) means the feed needs attention; right-skew (mass near
   `allowed_count`) means healthy margin.
2. **Is update volume concentrated in a few publishers?** — a feed with 10
   allowed publishers where 3 produce 80% of updates must be distinguishable
   from one with uniform contribution.

Pure diagnostic. No config edits, no coupling to the Stage 1–3 min_pub
remediation pipeline (`audit_min_pub` → `qualify_candidates` →
`apply_min_pub_remediation`).

## New files

| File                                    | Role                                         |
| --------------------------------------- | -------------------------------------------- |
| `lazer_dq/active_pub_distribution.py`   | Main script: query, metrics, two CSVs        |
| `lazer_dq/render_active_pub_html.py`    | Renderer: CSVs → self-contained HTML report  |
| `tests/test_active_pub_distribution.py` | Unit tests for pure metric functions         |
| `docs/active_pub_distribution.md`       | Usage doc (+ row in CLAUDE.md scripts table) |

## Methodology

Reuses the `audit_min_pub` foundations so numbers line up with existing
CRITICAL/WARN/OK results:

- Feed-session enumeration via `min_pub_common.iter_stable_sessions`
  (STABLE feeds, new-format configs only; per-session allowed sets and
  `effective_min_pub`).
- Session open-minute masking via `market_schedule.parse_market_schedule` /
  `open_minutes_mask` (UTC minutes, Monday-first schedule strings,
  `exchangeId` inheritance already resolved by `min_pub_common`).
- A publisher is "active in minute m" iff it has ≥ 1 ACCEPTED update in m.
  Open minutes with no rows count as 0 active. Only publishers in the
  session's allowed list count toward metrics.

### Query (one per feed, shared by all its sessions)

Variant of the audit query that keeps per-publisher counts instead of
distinct sets:

```sql
SELECT toStartOfMinute(publish_time) AS minute,
       publisher_id,
       countIf(status = 'ACCEPTED') AS accepted
FROM publisher_updates
PREWHERE price_feed_id = {feed_id:UInt64}
WHERE publish_time >= {start:String}
  AND publish_time < {end:String}
GROUP BY minute, publisher_id
HAVING accepted > 0
ORDER BY minute
```

This single result yields both the per-minute active sets (histogram) and
per-publisher ACCEPTED-update totals over open minutes (concentration).

## Metric definitions

Let the session's open minutes be `M`, allowed set `A`, per-minute active
count `c(m) = |{p ∈ A : accepted(p, m) > 0}|`, and per-publisher totals
`u(p) = Σ_{m ∈ M} accepted(p, m)` for `p ∈ A`, with `U = Σ u(p)`.

- **Histogram** — for each `k`, `pct(k) = 100 · |{m : c(m) = k}| / |M|`.
- **Skew** — `pct_minutes_le_min` = % of open minutes with
  `c(m) ≤ effective_min_pub` (matches the audit's CRITICAL condition);
  `pct_minutes_le_min_plus_1` likewise for `min_pub + 1`.
- **Shares** — `s(p) = u(p) / U`.
- **Effective publishers** — `1 / Σ s(p)²` (inverse HHI). `0.0` when `U = 0`.
  Reads as "this feed effectively has 3.2 publishers even though 10 are
  allowed"; directly comparable to `effective_min_pub`.
- **top1_share_pct / top3_share_pct** — `100 ·` (sum of the 1 / 3 largest
  `s(p)`). `0.0` when `U = 0`.

## Output 1 — summary CSV

`output_csv/active_pub_distribution_<start>_<end>.csv`, one row per
(feed, session):

| Column                                  | Meaning                                                                                                                                                                                                                                                                                                                                 |
| --------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `feed_id, symbol, asset_type, session`  | Identity                                                                                                                                                                                                                                                                                                                                |
| `note`                                  | blank \| `NO_SCHEDULE` \| `ZERO_OPEN_MINUTES` \| `SKIPPED_DEPRECATED`                                                                                                                                                                                                                                                                   |
| `effective_min_pub`                     | Session minPublishers (feed-level fallback per `min_pub_common`)                                                                                                                                                                                                                                                                        |
| `allowed_count`                         | Size of the session's allowed list                                                                                                                                                                                                                                                                                                      |
| `active_pub_count`                      | Allowed publishers with ≥ 1 ACCEPTED update in open minutes                                                                                                                                                                                                                                                                             |
| `never_published_count`                 | `allowed_count − active_pub_count` (allowed but zero updates)                                                                                                                                                                                                                                                                           |
| `unlisted_active_count`                 | Distinct publishers **not** in the allowed list with ≥ 1 ACCEPTED update in open minutes. Sanity flag only: non-zero means the analyzed config file differs from the config production enforced during the window (snapshot drift), so allowed-list-based metrics are computed against a stale roster. Excluded from all other metrics. |
| `open_minutes`                          | `\|M\|`                                                                                                                                                                                                                                                                                                                                 |
| `total_accepted_updates`                | `U`                                                                                                                                                                                                                                                                                                                                     |
| `pct_minutes_le_min`                    | Skew: % open minutes at or below min_pub                                                                                                                                                                                                                                                                                                |
| `pct_minutes_le_min_plus_1`             | % open minutes at or below min_pub + 1                                                                                                                                                                                                                                                                                                  |
| `p10_active, median_active, p90_active` | Percentiles of `c(m)`                                                                                                                                                                                                                                                                                                                   |
| `worst_minute_active`                   | `min c(m)`                                                                                                                                                                                                                                                                                                                              |
| `active_hist`                           | Full histogram, compact string: `"3:0.52;4:12.10;5:87.38"` — `k:pct` pairs for non-empty buckets, ascending `k`, pct rounded to 2 dp                                                                                                                                                                                                    |
| `effective_publishers`                  | Inverse HHI (2 dp)                                                                                                                                                                                                                                                                                                                      |
| `top1_share_pct, top3_share_pct`        | Concentration shares (2 dp)                                                                                                                                                                                                                                                                                                             |

Rows with a non-blank `note` carry identity, `effective_min_pub`, and
`allowed_count` only; every query-derived column (from `active_pub_count`
onward, including `unlisted_active_count`) is left empty.
`SKIPPED_DEPRECATED` rows, one per deprecated STABLE feed, carry identity
only — same convention as the audit.

## Output 2 — per-publisher detail CSV

`output_csv/active_pub_publishers_<start>_<end>.csv`, one row per
(feed, session, **allowed** publisher) — including zero-update publishers,
which is the "allowed vs actually publishing" list:

| Column                                   | Meaning                                                                         |
| ---------------------------------------- | ------------------------------------------------------------------------------- |
| `feed_id, symbol, session, publisher_id` | Identity                                                                        |
| `accepted_updates`                       | `u(p)` over open minutes                                                        |
| `update_share_pct`                       | `100 · s(p)` (2 dp; 0.0 when `U = 0`)                                           |
| `minutes_active`                         | Open minutes where `accepted(p, m) > 0`                                         |
| `pct_open_minutes_active`                | `100 · minutes_active / \|M\|` (2 dp)                                           |
| `rank`                                   | 1 = most updates; ties broken by publisher_id; zero-update publishers rank last |

Sessions with a non-blank `note` produce no detail rows.

## Output 3 — HTML report

`lazer_dq/render_active_pub_html.py --summary <csv> --publishers <csv>
[--output <html>] [--top 50]`

Reads the two CSVs (no ClickHouse) and writes one self-contained HTML file:

- **Worst-first histogram gallery**: top `--top` (default 50) feed-sessions
  ordered by `pct_minutes_le_min` desc, then `effective_publishers` asc.
  Each card renders the `active_hist` distribution as inline CSS bars with
  the `min_pub` position marked in red, annotated with
  `effective_publishers`, `top3_share_pct`, `active_pub_count`/`allowed_count`,
  and the dominant publisher IDs (top 3 by share from the detail CSV).
- **Full table**: every summary row, sortable client-side (vanilla JS,
  no external assets — the file must render offline and as a claude.ai
  Artifact under strict CSP).

The markdown findings doc (like `docs/min_pub_sweep_*`) is hand-written
after the first production run, not script-generated.

## CLI (main script)

Same shape as `audit_min_pub`:

```
python3 -m lazer_dq.active_pub_distribution --config lazer_new.json \
    [--start-date YYYY-MM-DD --end-date YYYY-MM-DD]   # default: last 7 full UTC days
    [--workers 8] [--feed-id ...] [--resume] [--output-dir output_csv]
```

`--start-date`/`--end-date` must be passed together (start inclusive, end
exclusive, UTC). Uses `ThreadLocalClients(load_config(), lazer_only=True)`;
per-feed failures are soft (logged, run continues, failure count in the
final summary line).

## Resume & write ordering

Lessons from `incumbent_quality` applied:

- Both CSV headers are written and flushed at file creation.
- Per feed, under one lock: detail rows written and flushed **first**, then
  summary rows flushed **last** — the summary row is the completion marker.
- `--resume` reads completed `feed_id`s from the summary CSV, prunes orphan
  detail rows (feeds present in detail but not summary — interrupted
  mid-flush), and skips completed feeds.

## Edge cases

- Unparseable or missing schedule → `note = NO_SCHEDULE`, no metrics.
- Session closed for the whole window (`|M| = 0`) → `note = ZERO_OPEN_MINUTES`.
- Zero updates (`U = 0`) → metrics computed, shares/effective_publishers 0.0,
  histogram `"0:100.00"`.
- Deprecated STABLE feeds → one `SKIPPED_DEPRECATED` summary row, no query.

## Testing

`tests/test_active_pub_distribution.py` — pure functions with synthetic
per-minute data, no ClickHouse:

- histogram + `active_hist` encoding (incl. all-zero and empty-mask cases)
- effective_publishers / top-N shares (uniform, fully concentrated, `U = 0`)
- skew percentages vs a hand-computed fixture
- summary/detail row builders (never_published, unlisted, ranks, note rows)
- renderer smoke test: given tiny CSVs, output contains expected cards/rows

## Out of scope

- No changes to `audit_min_pub` or any Stage 1–3 pipeline files.
- No aggregate-side analysis (`price_feeds` table) — per-minute publisher
  activity only.
- No thresholds/classification — this tool describes; humans (or a later
  tool) decide cutoffs.
