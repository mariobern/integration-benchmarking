# min_pub audit & remediation pipeline — design

## Problem

`lazer_to_modify.json` (new-format, session-only publishers; 3,543 feeds — 1,645
STABLE) contains feeds whose **active** publisher count sits at or barely above
their effective `minPublishers` floor. Two failure classes:

1. **active == min_pub** at any time (worst when prolonged) — zero redundancy;
   one publisher dropping stalls aggregation.
2. **active == min_pub + 1** — one-publisher redundancy; the next wobble puts
   the feed in class 1.

Static config margins understate the problem: a feed can list 10 allowed
publishers of which only 3 actively publish. Conversely, `publisher_updates`
contains submissions from publishers **not** in the allowed set (verified:
feed 1 has 36 submitting / 19 allowed; feed 1830 has 8 / 2; feed 1554 has
6 / 1), so qualified candidates exist in the data and can be benchmarked.

## Decisions (user-confirmed)

- **Audit metric:** per-minute distinct active-publisher count, 7-day lookback,
  session-aware (open hours only).
- **Scope:** STABLE feeds only (1,645). DEPRECATED-symbol feeds excluded and
  reported separately.
- **Remediation levers:** add publishers (rebenchmarked) only; flag-only
  fallback when nothing qualifies. `minPublishers` is never lowered.
- **Non-Datascope feeds** (crypto, funding-rate, NAV, redemption-rate, custom,
  crypto-index): qualify candidates by **peer comparison vs the feed's own
  aggregate** (`price_feeds`), same NRMSE/hit-rate math; circularity risk
  accepted.
- **Apply mode:** auto-apply to `lazer_to_modify.json` via
  `tools/edit-config/edit_config.py`, review artifacts saved; user reviews the
  git diff before committing. Nothing is committed automatically.

## Architecture

Three-stage pipeline under `lazer_dq/`, CSV artifacts between stages; each
stage independently re-runnable.

```
lazer_to_modify.json
        │
        ▼
[1] audit_min_pub.py ──────────────► min_pub_audit_<start>_<end>.csv
        │  (CRITICAL / WARN rows)          + hygiene_report.csv
        ▼
[2] qualify_candidates.py ─────────► candidates_report.csv
        │  (selected rows)                 + flagged_feeds.csv
        ▼
[3] apply_min_pub_remediation.py ──► lazer_to_modify.json (edited in place)
           (edit_config.py subprocess)     + applied_changes.csv
```

New shared module: `lazer_dq/peer_benchmark.py` (aggregate-reference NRMSE /
hit-rate for non-Datascope feeds).

## Stage 1 — Audit (`lazer_dq/audit_min_pub.py`)

**CLI:** `--config lazer_to_modify.json`, `--start-date` / `--end-date`
(default last 7 full UTC days), `--workers` (default 8), `--feed-id` filter,
`--resume`, `--prolonged-threshold` (default 30 minutes).

**Unit of audit: the (feed, session) pair.** For each STABLE feed, each
`marketSchedules` entry is audited against its own `allowedPublisherIds` with
**effective min_pub** = session-level `minPublishers` if present (2,347
sessions, mostly `Equity.US`), else feed-level (present on all feeds).

**Query:** one ClickHouse query per feed, parallel via ThreadPoolExecutor
(pattern: `portal/batch/daily_benchmark_runner.py`):
per-minute `uniqExactIf(publisher_id, publisher_id IN {allowed})` over
`publisher_updates` for the window, grouped by minute (~10k rows/feed). Only
allowed publishers count as "active" — non-allowed submissions do not feed
aggregation. Session open-hours filtering happens in pandas using the session
windows from `lib/sql_filters.py` (equities sessions, fx/metals maintenance
windows, 24/7 crypto). Open minutes with no rows count as active = 0.

**Per (feed, session) metrics:** `effective_min_pub`, `allowed_count`,
`open_minutes`, `minutes_below_min` (active < min_pub — included because
strictly-below is already failing aggregation), `minutes_at_min`,
`minutes_at_min_plus_1`, longest consecutive run at ≤ min_pub and at
min_pub + 1, `median_active`, `prolonged` boolean (any run ≥ threshold).

**Classification:** `CRITICAL` = any open minute with active ≤ min_pub;
`WARN` = never ≤ min_pub but some minute at min_pub + 1; `OK` otherwise.

**Output:** `output_csv/min_pub_audit_<start>_<end>.csv`, written incrementally
(resumable). Expected runtime: hours at 8–16 workers (a 4-feed 2-day sample
query took ~4 minutes); the CSV is the interface to Stage 2 so the heavy scan
runs once.

**Hygiene report (report-only, no changes):** feeds where
`minPublishers > allowed_count` — the `minPublishers: 100` kill-switch
inventory (~100 feeds, mostly INACTIVE) and the 8 COMING_SOON `InterestRate.*`
feeds with min_pub 3 / 0 allowed — written to `hygiene_report.csv`. These are
scanned from the full config (all states) since it is a static check.

## Stage 2 — Qualify candidates (`lazer_dq/qualify_candidates.py`)

**Input:** Stage-1 CSV (CRITICAL + WARN rows) + config.

**Candidate discovery:** distinct publishers in `publisher_updates` for the
feed over the audit window, minus the session's `allowedPublisherIds`, minus
exclusions (`--exclude-publisher`, repeatable; publisher 0 always excluded).

**Gate 1 — activity (all feeds):** candidate must be active (≥1 update) in
≥ 90% of the session's open minutes over the window (`--min-activity`,
default 0.90). A publisher that doesn't publish can't raise the active count.

**Gate 2 — price quality:**

- _Datascope-benchmarkable modes_ (fx, metals, commodity, us/hk/jp/kr/in
  equities, treasuries): run the existing `evaluate_feed_standalone` engine on
  up to 3 most recent trading days in the window (first date that exits 0
  wins; exit 2 on all dates → flag `no_benchmark_data`). The engine already
  emits per-publisher stats including non-allowed publishers. Pass criteria:
  the existing `summarize_feeds` per-mode thresholds (`rmse_over_spread`,
  `hit_rate`, `n_obs`) — the same bar current allowed publishers were held to.
- _Non-Datascope feeds_: `lazer_dq/peer_benchmark.py`. Reference = the feed's
  aggregate from `price_feeds`; candidate = their `publisher_updates`; asof
  per-second alignment (resampling style of `lib/benchmark_core.py`); NRMSE
  and hit-rate computed identically. Default thresholds = relaxed tier
  (`nrmse < 0.05` auto-pass, or `< 0.15` with `hit_rate ≥ 85%`), overridable.

**Selection:** rank passers by quality metric ascending; add until **projected
active margin ≥ min_pub + 2**, where projection joins each candidate's
observed per-minute activity onto Stage-1 counts on a **worst-minute** basis
(not average). Target unreachable → add whoever qualifies and flag the feed
with a reason: `no_candidates`, `candidates_fail_activity`,
`candidates_fail_quality`, `still_below_target`, `no_benchmark_data`.

Static-margin note: STABLE feeds at static margin 0/1 (16 + 16 today) can
never clear the target through activity alone; the report marks that their fix
requires new publishers by construction.

**Output:** `candidates_report.csv` (every candidate, both gates' metrics,
pass/fail, selected flag) and `flagged_feeds.csv`.

## Stage 3 — Apply + verify (`lazer_dq/apply_min_pub_remediation.py`)

**Apply:** for each selected (feed, session, publisher), subprocess:
`python3 tools/edit-config/edit_config.py --config lazer_to_modify.json
--add-publisher <id> --feed-id <fid> --session <SESSION>` — inheriting
edit_config's new-format guardrails and formatting-preserving JSON surgery.
`--dry-run` prints the aggregate diff without touching the file. Writes
`applied_changes.csv`.

**Verification (built-in "check your work"):**

1. **Static re-check** — reload the modified config; every remediated
   (feed, session) has `allowed_count ≥ min_pub + 2` or appears in
   `flagged_feeds.csv`; no duplicate adds; no non-selected publisher added;
   untouched feeds byte-identical.
2. **Linter** — `tools/config-linter/config_linter.py` on the modified config;
   no new errors vs a pre-run baseline. If the linter rejects the new format
   outright, fall back to checks 1 + 3 and note it in the report.
3. **Projected-margin re-check** — recompute worst-minute active counts from
   Stage-1 per-minute data with the new allowed sets; every remediated feed
   clears min_pub + 1 (no longer CRITICAL/WARN) or is flagged.
4. **Human review** — user reviews `git diff lazer_to_modify.json` + the three
   CSVs before committing.

**Error handling:** per-feed ClickHouse failures soft-fail and continue (the
`evaluate_feeds_bulk` pattern); edit_config non-zero exit aborts the apply
stage and reports which changes already landed.

## Testing

Unit tests in `lazer_dq/tests/`:

- effective-min_pub resolution (session override vs feed-level) and margin math
- session open-minute filtering (equities sessions, fx maintenance, 24/7)
- classification (CRITICAL / WARN / OK, prolonged runs, zero-row minutes)
- candidate selection incl. worst-minute projection and flag reasons
- `peer_benchmark` NRMSE/hit-rate on synthetic aligned/misaligned series
- end-to-end dry-run over a small config fixture with mocked ClickHouse

## Out of scope

- Lowering `minPublishers` anywhere.
- Publisher outreach for lapsed-but-allowed publishers (visible in the audit
  CSV; no action taken).
- Recurring/cron monitoring (Stage 1 is designed to double as one later).
- COMING_SOON / INACTIVE remediation (hygiene report only).
