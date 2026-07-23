# active_min_pub

Aggregate publisher-count headroom sweep. For every STABLE `(feed, session)` in a
new-format Lazer config, reads the aggregate's own `publisher_count` per update
from the `price_feeds` table (highest-frequency channel = lowest-numbered channel
with data), session-masks to open hours, and reports the contributor-count
distribution vs the session's `minPublishers`.

## Distinct from `audit_min_pub`

|             | `active_min_pub`                     | `audit_min_pub`                         |
| ----------- | ------------------------------------ | --------------------------------------- |
| Question    | Aggregate contributor-count headroom | Per-minute publisher availability       |
| Source      | `price_feeds.publisher_count`        | `publisher_updates` (distinct ACCEPTED) |
| Granularity | per aggregate update                 | per minute                              |

Use `active_min_pub` to answer "how close does each feed run to its min-pub floor,
at the aggregate level?" — the input to feed-by-feed remediation.

## Usage

    python3 -m lazer_dq.active_min_pub \
        --config lazer_newest.json \
        --start-date 2026-07-14 --end-date 2026-07-22 \
        [--critical-pct 1.0] [--warn-pct 5.0] [--min-updates 100] [--workers 8]

`--start-date`/`--end-date` are UTC (`end` exclusive). Omit both for the last 7
full UTC days. `--feed-id N ...` restricts the sweep. `--exclude-internal` drops
internal feed families (`Pyth.*`, `Custom.*`, `Internal.*`, `FeedComponent.*`)
from the sweep entirely — use it for a purely consumer-facing report.

## Output

Two CSVs are written per run.

### Summary — `output_csv/active_min_pub_<start>_<end>.csv`

One row per feed-session (sorted CRITICAL first, then `pct_at_floor` descending):

`feed_id, symbol, asset_type, session, effective_min_pub, n_updates, min, p1, p5,
median, pct_at_floor, pct_at_floor_1, verdict`

- `pct_at_floor` — % of in-session updates with `publisher_count <= min_pub` (primary trigger).
- `pct_at_floor_1` — % with `publisher_count <= min_pub + 1` (context).

### Histogram — `output_csv/active_min_pub_histogram_<start>_<end>.csv`

The raw distribution: one row per distinct `publisher_count` value per feed-session
(the count of in-session aggregate updates at each observed contributor count):

`feed_id, symbol, asset_type, session, effective_min_pub, publisher_count, n_updates`

The per-session `n_updates` sum equals the summary row's `n_updates`. This is the
"count the number of updates per each distinct number" table — pivot or plot it
(x = `publisher_count`, y = `n_updates`, reference line at `effective_min_pub`) to
see exactly where each feed-session's distribution sits relative to its floor.

### Verdicts

The **floor** is each feed's `minPublishers`. Two metrics drive the verdict:
`pct_at_floor` (% of in-session aggregates with `publisher_count <= minPublishers`)
and `pct_at_floor_1` (% with `publisher_count <= minPublishers + 1`).

Precedence: NO_DATA > LOW_SAMPLE > CRITICAL > WARN > OK.

- **CRITICAL** — `pct_at_floor >= --critical-pct` (default **1.0%**): at least 1%
  of aggregates ran **at or below** the floor (`publisher_count <= minPublishers`).
  Hits its minimum regularly.
- **WARN** — `pct_at_floor == 0` **and** `pct_at_floor_1 >= --warn-pct`
  (default **5.0%**): never at the floor, but ≥5% ran exactly **one above** it
  (`= minPublishers + 1`). One dropout from CRITICAL.
- **OK** — everything else: **< 1%** at the floor, and — if never at it — **< 5%**
  one above. Rarely at or near the floor. (Gap by construction: a feed at the floor
  only _rarely_, `0 < pct_at_floor < 1%`, is neither CRITICAL nor WARN — it lands here.)
- **LOW_SAMPLE** — fewer than `--min-updates` (default 100) in-session updates.
- **NO_DATA** — no aggregate updates in the window (non-trading / not ingested).
- **NO_SCHEDULE** — session has no resolvable/parsable market schedule.
- **NO_MIN_PUB** — session has no `minPublishers` floor defined (cannot compare).

The console prints the verdict tally, the CRITICAL list (sorted by `pct_at_floor`),
and the NO_DATA / LOW_SAMPLE lists.

## Asset type refinement

The raw config `asset_type` is refined in this script's output only
(`derive_asset_type`); the shared config metadata and `audit_min_pub` are
untouched. Two adjustments keep the per-class distributions honest:

- **Internal feeds → `internal`.** `Pyth.*`, `Custom.*`, `Internal.*`, and
  `FeedComponent.*` are non-consumer-facing but carry real asset_types in the
  config (e.g. `Pyth.BN.AAPL` is tagged `equity`), so they would otherwise
  pollute the true classes. They collapse to a single `internal` bucket.
  `FundingRate.*` is a real product and is left as-is. Use `--exclude-internal`
  to drop them from the sweep entirely.
- **Index feeds → `<class>-index`.** `.Index.` feeds (symbol has `Index` as its
  second dotted segment — `Equity.Index.NVDA/USD`, `Commodities.Index.COPPER/USD`)
  are re-tagged `equity-index`, `commodity-index`, `fx-index`, `metal-index`,
  `crypto-index` so they don't dilute the underlying class. This also normalizes
  a config inconsistency (`Crypto.Index.*` was already `crypto-index`, but
  `Equity.Index.*` was plain `equity`).

## Sessions

US-equities feeds carry REGULAR / PRE_MARKET / POST_MARKET / OVER_NIGHT as distinct
`marketSchedules` entries, each with its own `minPublishers` and hours, so each gets
a standalone row masked to its own window. OVER_NIGHT (midnight-crossing) needs no
special-casing here because this analysis never touches a Datascope benchmark.
