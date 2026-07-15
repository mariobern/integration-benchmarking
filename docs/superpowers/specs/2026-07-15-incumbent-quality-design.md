# Design: Incumbent Publisher Quality Sweep

## Goal

Measure the price quality of every incumbent (currently-allowed) publisher on
every session of every STABLE feed in a Lazer config — the population the
min_pub pipeline never benchmarks (its quality gate only scores _candidate_
publishers on WARN/CRITICAL feed-sessions).

## Deliverables

1. New pipeline stage `lazer_dq/incumbent_quality.py`, runnable as
   `python3 -m lazer_dq.incumbent_quality`, with pytest unit tests.
2. Documentation: usage section (new `docs/incumbent_quality.md`, linked from
   the CLAUDE.md scripts table).
3. First production run over a recent 7-day window.
4. Summary report `docs/incumbent_quality_report_<run-date>.md`.

Branch: `feat/incumbent-quality` (off `main`).

## Decisions made during brainstorming

- **Reusable tool + first run**, not a one-off orchestration.
- **Population: all STABLE feed-sessions** (OK ones included, WARN/CRITICAL
  too — their incumbents were never re-benchmarked either).
- **Non-Datascope feeds use aggregate comparison** (peer path vs the feed's
  own `price_feeds` aggregate), accepting the incumbent-circularity the same
  way `qualify_candidates.py` accepted it for candidates. Leave-one-out peer
  median was considered and rejected for scope.
- **Architecture: new stage reusing `qualify_candidates` machinery** by
  import (option A), not an `--incumbents` flag on the existing script and
  not the older `lib/publisher_eval` stack (whose metrics would not be
  comparable with candidate-qualification results).

## Data flow

For each `FeedSession` from `iter_stable_sessions(config)` (new-format,
session-only configs — same contract as the rest of `lazer_dq`):

1. **Incumbents** = the session entry's `allowedPublisherIds`.
2. **Quality path** picks itself per feed-session, identical to
   qualification:
   - **Datascope path** — when `engine_mode_for(fs)` resolves a mode: run the
     DQ engine (`run_engine`, i.e. `evaluate_feed_standalone`) once per
     feed/date over `candidate_dates(start, end)`; the engine emits
     per-publisher stats; gate each incumbent with `engine_gate(stats_row,
mode, min_obs)`.
   - **Peer path** — everything else (crypto, redemption rates, NAV, funding
     rates, …): fetch the incumbent's per-second ACCEPTED prices and the
     `price_feeds` aggregate (`fetch_aggregate`), restrict to the session's
     open-minutes mask, score with `peer_benchmark.evaluate_peer` using the
     same `PeerThresholds` as qualification.
3. **Activity** — each incumbent also gets `activity_pct` over the session's
   open minutes (context only, NOT a gate; publisher presence is the min_pub
   audit's job).
4. **Verdict per incumbent**: `PASS` / `FAIL` / `NO_DATA` (no ACCEPTED
   submissions in the window) / `NO_BENCHMARK` (engine soft-skip — exit 2 —
   or empty/zero-range aggregate).

Shared helpers are imported from `lazer_dq.qualify_candidates`,
`lazer_dq.peer_benchmark`, `lazer_dq.min_pub_common`, and
`lazer_dq.market_schedule`. Where a needed helper is private or coupled to
candidate-only assumptions, extract it to `min_pub_common` (or a small new
shared module) rather than copy-pasting; `qualify_candidates` keeps working
unchanged (its tests must still pass).

## Outputs (written to `--output-dir`, default `output_csv/`)

| File                            | Grain                            | Contents                                                                                                                                                                 |
| ------------------------------- | -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `incumbent_report.csv`          | publisher × feed-session         | feed_id, symbol, session, publisher_id, quality_path (engine/peer), engine_mode, activity_pct, rmse_over_spread, hit_rate, nrmse, n_obs, verdict                         |
| `incumbent_quality_summary.csv` | feed-session                     | feed_id, symbol, session, asset_type, quality_path, n_incumbents, n_pass, n_fail, n_no_data, n_no_benchmark, all_pass, audit_classification (blank unless `--audit-csv`) |
| `flagged_incumbents.csv`        | failing publisher × feed-session | feed_id, symbol, session, publisher_id, verdict, reason, detail                                                                                                          |

`--audit-csv <min_pub_audit CSV>` joins the Stage-1 min_pub classification
onto summary rows by (feed_id, session), so "OK feeds with failing
incumbents" — the headline question — falls straight out of the summary.

## CLI

```
python3 -m lazer_dq.incumbent_quality \
    --config lazer_new.json \
    --start-date 2026-07-08 --end-date 2026-07-15 \
    [--workers 8] [--feed-id ...] [--resume] \
    [--peer-days N] [--audit-csv output_csv/min_pub_audit_X.csv] \
    [--output-dir output_csv]
```

- Dates are UTC, end exclusive (same convention as `audit_min_pub`).
- `--resume` appends to existing outputs and skips already-written
  (feed_id, session) keys.
- Per-feed errors are soft failures (log + continue), matching the rest of
  the pipeline. Exit 0 if the sweep ran; non-zero only on setup errors
  (bad config, no ClickHouse).
- New-format configs only; error out on old-format files (same guard as
  `edit_config.py` / `apply_allowed_to_config.py`).

## Error handling

- Publisher with zero ACCEPTED rows in the window → verdict `NO_DATA`
  (not FAIL — could be schedule/maintenance; flagged separately).
- Engine exit 2 (no benchmark data for that feed/date/mode) → try the next
  candidate date; if all dates skip → `NO_BENCHMARK`.
- Zero-range aggregate on the peer path (flat NAV class) → `NO_BENCHMARK`
  with reason `zero_range` (known limitation, documented in the report).
- Feeds whose session has no parsable market schedule → soft-skip row with
  reason `no_schedule`.

## Testing

- Pytest units (no ClickHouse), matching existing `tests/` style for
  lazer_dq: incumbent enumeration from config fixtures, verdict mapping
  (PASS/FAIL/NO_DATA/NO_BENCHMARK), summary rollup arithmetic, resume-key
  filtering, audit-CSV join, old-format config rejection.
- Existing suite must stay green (especially `qualify_candidates` tests,
  since shared helpers may move).
- Live smoke before the production run: ~3 hand-picked feeds — one Datascope
  equity (engine path), one crypto (peer path), one thin/flat feed
  (NO_DATA / zero_range handling).

## First run & report

- Full sweep of `lazer_new.json` over a recent 7-day window (multi-hour,
  `--workers 8+`, resumable).
- `docs/incumbent_quality_report_<run-date>.md`: pass rates by asset type
  and quality path; the OK-feeds-with-failing-incumbents table (via
  `--audit-csv` join); NO_DATA / NO_BENCHMARK inventory; caveats
  (peer-path circularity, engine soft-skips, flat-reference feeds).

## Out of scope

- Leave-one-out / peer-median methodology (rejected during brainstorming).
- Changing minPublishers, publisher lists, or any config mutation — this
  stage only measures.
- Uptime / presence auditing (min_pub audit owns that).
- Old-format config support.
- Portal integration.
