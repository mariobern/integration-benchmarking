# Min Publisher Audit & Remediation Pipeline

Three-stage pipeline that finds STABLE (feed, session) pairs whose **active**
publisher count sits at or barely above their effective `minPublishers`
floor, qualifies new publishers to fix them, and applies the fix through
`edit_config.py` with a built-in verification pass. Operates on new-format
(session-only publishers) Lazer configs such as `lazer_to_modify.json`.

## 1. Purpose

Static config margins understate redundancy risk: a feed can list ten
allowed publishers of which only three actually publish. Two failure
classes matter, both measured on **active** (currently-submitting) publisher
count, not the static `allowedPublisherIds` length:

1. **`active == min_pub`** at any open minute (worse when prolonged) — zero
   redundancy; one publisher dropping out stalls aggregation entirely.
2. **`active == min_pub + 1`** — one-publisher redundancy; the next wobble
   puts the feed into failure class 1.

The pipeline has three independently re-runnable stages, connected by CSV
artifacts:

```
lazer_to_modify.json
        │
        ▼
[1] audit_min_pub.py ──────────────► min_pub_audit_<start>_<end>.csv
        │  (CRITICAL / WARN rows)          + hygiene_report.csv
        ▼
[2] qualify_candidates.py ─────────► candidates_report.csv
        │  (selected rows)                 + qualification_summary.csv
        │                                   + flagged_feeds.csv
        │                                   + min_pub_activity/feed_<id>.csv.gz
        ▼
[3] apply_min_pub_remediation.py ──► lazer_to_modify.json (edited in place)
           (edit_config.py subprocess)     + applied_changes.csv
                                            + verification_report.csv
```

`minPublishers` is never lowered anywhere in this pipeline — the only lever
is adding rebenchmarked publishers, with flag-only fallback when nothing
qualifies.

## 2. Stage 1 — Audit (`lazer_dq/audit_min_pub.py`)

Counts distinct `ACCEPTED` allowed publishers per minute over a UTC date
window, restricted to each session's open hours, and classifies every
STABLE (feed, session) pair.

```bash
python3 -m lazer_dq.audit_min_pub --config lazer_to_modify.json \
    --start-date 2026-07-06 --end-date 2026-07-13 --workers 16
```

### CLI

| Flag                    | Default      | Notes                                                                                          |
| ----------------------- | ------------ | ---------------------------------------------------------------------------------------------- |
| `--config`              | required     | new-format (session-only publishers) Lazer config                                              |
| `--start-date`          | —            | UTC start date `YYYY-MM-DD`, inclusive. Must be passed with `--end-date` or not at all         |
| `--end-date`            | —            | UTC end date `YYYY-MM-DD`, exclusive                                                           |
| `--workers`             | `8`          | ThreadPoolExecutor size — one ClickHouse query per feed                                        |
| `--feed-id`             | —            | `nargs="*"`; restrict the audit to these feed IDs                                              |
| `--resume`              | off          | skip feeds already present in the output CSV and append to it                                  |
| `--prolonged-threshold` | `30`         | minutes; a run of open minutes `<= min_pub + 1` of this length or longer sets `prolonged=True` |
| `--output-dir`          | `output_csv` | where both output CSVs are written                                                             |

If neither `--start-date` nor `--end-date` is given, the window defaults to
the last 7 full UTC days (`[today-7 00:00, today 00:00)`). Passing only one
of the two is an error.

### Unit of audit

The **(feed, session) pair**. For every STABLE feed (DEPRECATED-symbol
feeds are excluded — see `deprecated_stable_feeds` below), each
`marketSchedules` entry is audited against its own `allowedPublisherIds`,
with **effective min_pub** = the session-level `minPublishers` if present,
else the feed-level `minPublishers` (`lazer_dq/min_pub_common.py:FeedSession`).
Only allowed publishers count as "active" — submissions from publishers not
in the session's allowed list do not feed aggregation and are not counted
here (that's what Stage 2 mines for candidates).

One ClickHouse query per feed (covers every session of that feed in one
pass) runs in parallel across `--workers` threads: per-minute
`groupUniqArrayIf(publisher_id, status = 'ACCEPTED')` over `publisher_updates`
for the date window. Session open-hours filtering then happens in pandas
using the schedule mask (`lazer_dq/market_schedule.py`); open minutes with no
rows in ClickHouse count as `active = 0`.

### Audit CSV columns

`min_pub_audit_<start>_<end>.csv` (17 columns):

| Column                      | Meaning                                                              |
| --------------------------- | -------------------------------------------------------------------- |
| `feed_id`                   | Lazer feed ID                                                        |
| `symbol`                    | feed symbol                                                          |
| `asset_type`                | `feed.metadata.asset_type`                                           |
| `session`                   | `REGULAR`, `PRE_MARKET`, `POST_MARKET`, `OVER_NIGHT`, …              |
| `classification`            | `CRITICAL` / `WARN` / `OK` / `NO_SCHEDULE` / `SKIPPED_DEPRECATED`    |
| `effective_min_pub`         | session-level `minPublishers` if present, else feed-level            |
| `allowed_count`             | `len(allowedPublisherIds)` for this session                          |
| `static_margin`             | `allowed_count - effective_min_pub`                                  |
| `open_minutes`              | number of open minutes in the window per the session's schedule mask |
| `minutes_below_min`         | open minutes with `active < min_pub` (already failing aggregation)   |
| `minutes_at_min`            | open minutes with `active == min_pub`                                |
| `minutes_at_min_plus_1`     | open minutes with `active == min_pub + 1`                            |
| `longest_run_le_min`        | longest consecutive run of open minutes with `active <= min_pub`     |
| `longest_run_le_min_plus_1` | longest consecutive run of open minutes with `active <= min_pub + 1` |
| `median_active`             | median active-publisher count over open minutes                      |
| `worst_minute_active`       | minimum active-publisher count over open minutes                     |
| `prolonged`                 | `True` if `longest_run_le_min_plus_1 >= --prolonged-threshold`       |

`SKIPPED_DEPRECATED` and `NO_SCHEDULE` rows only populate `feed_id`,
`symbol`, `session` (where applicable) and `classification` — no metrics
columns.

### Classification semantics

- **`CRITICAL`** — any open minute with `active <= min_pub`
  (`minutes_below_min + minutes_at_min > 0`).
- **`WARN`** — never `<= min_pub`, but at least one minute at
  `min_pub + 1`.
- **`OK`** — otherwise.
- **`NO_SCHEDULE`** — the session has no resolvable `marketSchedule` string
  (no inline string on the session entry and no matching session on the
  feed's `exchanges[]` entry), **or** the schedule string exists but fails
  to parse (`parse_market_schedule` raises `ValueError` — e.g. a malformed
  `HHMM` token, wrong day-entry count, or a bad override date). Either case
  produces no per-minute metrics; the feed is not scored.
- **`SKIPPED_DEPRECATED`** — the feed is `STABLE` but its symbol starts with
  `DEPRECATED` (a config hygiene issue, not an audit finding). Reported once
  per feed with no metrics; excluded from every other stage.

### `--resume`

If `--resume` is passed and the target audit CSV already exists, the script
reads its `feed_id` column, skips those feeds, and appends new rows to the
same file rather than starting over. Useful for restarting a multi-hour run
after an interruption — it does not detect a changed date window, so resume
only makes sense against the same `--start-date`/`--end-date` pair (the
output filename already encodes the window).

### Runtime

Expect a **multi-hour run** across the full STABLE population (1,645 feeds
in the reference config) even at 16 workers — this is a per-minute scan over
a 7-day window per feed. The audit CSV is written incrementally (flushed
after each feed) so the heavy scan only has to run once; Stage 2 and Stage 3
both consume the CSV rather than re-querying ClickHouse for activity.

### Hygiene report

`hygiene_report.csv` is a **static, report-only** scan across feeds of
**every** state (not just STABLE) — no ClickHouse query is needed. It flags
feeds where the feed-level `minPublishers` exceeds the union of
`allowedPublisherIds` across all `marketSchedules` entries: the
`minPublishers: 100` kill-switch pattern, and feeds that can never aggregate
because `minPublishers` exceeds the publisher list they actually have (e.g.
`min_pub 3` with 0 allowed publishers). Columns: `feed_id`, `symbol`,
`state`, `feed_min_publishers`, `allowed_union_count`, `issue`
(`no_allowed_publishers` or `min_pub_exceeds_allowed`). It is written on
every run, independent of `--resume` and `--feed-id`.

## 3. Stage 2 — Qualify candidates (`lazer_dq/qualify_candidates.py`)

Reads the Stage-1 audit CSV and, for every `CRITICAL`/`WARN` (feed,
session), discovers candidate publishers, runs them through two gates, and
greedily selects enough passers to close the margin.

```bash
python3 -m lazer_dq.qualify_candidates --config lazer_to_modify.json \
    --audit-csv output_csv/min_pub_audit_2026-07-06_2026-07-13.csv \
    --start-date 2026-07-06 --end-date 2026-07-13 --cluster lazer-prod
```

### CLI

| Flag                  | Default         | Notes                                                                       |
| --------------------- | --------------- | --------------------------------------------------------------------------- |
| `--config`            | required        | must match the config the audit CSV was generated from                      |
| `--audit-csv`         | required        | Stage-1 output                                                              |
| `--start-date`        | required        | UTC, inclusive                                                              |
| `--end-date`          | required        | UTC, exclusive — should match the audit window                              |
| `--cluster`           | `lazer-prod`    | passed through to `evaluate_feed_standalone` for engine-path feeds          |
| `--exclude-publisher` | `[]`            | repeatable; extra publisher IDs to never consider as candidates             |
| `--min-activity`      | `0.90`          | Gate 1 threshold: share of open minutes a candidate must have submitted in  |
| `--target-margin`     | `2`             | selection target is `min_pub + target_margin`                               |
| `--peer-nrmse-auto`   | `0.05`          | peer-path auto-pass NRMSE threshold                                         |
| `--peer-nrmse-cond`   | `0.15`          | peer-path conditional NRMSE threshold (needs hit-rate too)                  |
| `--peer-hit-rate`     | `85.0`          | peer-path minimum hit rate (%) for the conditional pass                     |
| `--min-obs`           | `1000`          | minimum aligned observations for both the engine and peer quality gates     |
| `--peer-days`         | `2`             | lookback window (days) for the peer-path benchmark, bounded within the mask |
| `--reports-dir`       | `dq_reports`    | where `evaluate_feed_standalone` writes/reads `stats.csv`                   |
| `--output-dir`        | `output_csv`    | where the four output artifacts land                                        |
| `--publishers-md`     | `publishers.md` | source of `.Test`-suffix publisher exclusions                               |

### Candidate discovery

For each flagged (feed, session), candidates are the distinct publishers
seen in `publisher_updates` for that feed over the window that are:

- submitting with `status = 'ACCEPTED'` **or** `status = 'REJECTED'` with
  `status_reason = 'UNAUTHORIZED'` — i.e. publishers Lazer is currently
  rejecting _only_ because they are not on the allow-list, not for any other
  reason;
- from a **production** key (`publishers_metadata_latest.key_type IN
('production', 'Production')`) — test keys are never candidates;
- **not** already in the session's `allowedPublisherIds`;
- **not** excluded: publisher `0` is always excluded (via
  `load_excluded_publishers`, which also drops any publisher whose name in
  `publishers.md` ends in `.Test`), plus anything passed via
  `--exclude-publisher`.

A (feed, session) with no candidates after this filter is flagged
`no_candidates` and skipped.

### Gate 1 — activity

A candidate must have submitted at least one update in `>= --min-activity`
(default 90%) of the session's open minutes over the window. A publisher
that doesn't actually publish can't raise the active-minute count no matter
how good its price is. Candidates that fail this gate never reach Gate 2; if
**all** candidates fail it, the (feed, session) is flagged
`candidates_fail_activity`.

### Gate 2 — quality

Two paths, chosen per (feed, session) by `engine_mode_for`:

| `asset_type`  | `symbol` / `session` condition                            | Engine mode             |
| ------------- | --------------------------------------------------------- | ----------------------- |
| `fx`          | —                                                         | `fx`                    |
| `metal`       | —                                                         | `metals`                |
| `commodity`   | —                                                         | `commodity`             |
| `rates`       | —                                                         | `us-treasuries-yield`   |
| `equity`      | `Equity.US.*`, session `REGULAR`                          | `us-equities`           |
| `equity`      | `Equity.US.*`, session `PRE_MARKET`                       | `us-equities-pre`       |
| `equity`      | `Equity.US.*`, session `POST_MARKET`                      | `us-equities-post`      |
| `equity`      | `Equity.US.*`, session `OVER_NIGHT`                       | `us-equities-overnight` |
| `equity`      | `Equity.HK.*`, session `REGULAR`                          | `hk-equities`           |
| anything else | (crypto, funding-rate, nav, redemption-rate, custom,      | **peer path** (`None`)  |
|               | crypto-index, `Equity.HK.*` non-REGULAR, and — on this    |                         |
|               | branch — `Equity.JP.*`/`Equity.KR.*`/`Equity.IN.*`, since |                         |
|               | the DQ engine has no modes for them here)                 |                         |

- **Engine path** (`mode` resolved): runs
  `evaluate_feed_standalone` as a subprocess for up to 3 most recent
  weekdays in the window (newest first; a date is skipped if `stats.csv`
  already exists under `--reports-dir`, so re-runs are cheap), stopping at
  the first date that exits `0` and yields non-empty stats. If all three
  dates exit `2` (no benchmark data) or error, the (feed, session) is
  flagged `no_benchmark_data`. Pass criteria (`engine_gate`): `n_observations
  > = --min-obs`, and then either the mode's own default thresholds from
`lazer_dq/summarize_feeds.ASSET_CLASS_CONFIG` (`rmse_over_spread`/`hit_rate_0.1pct`— currently defined for the four`us-equities\*`modes and`hk-equities`), or, for modes with no entry there (fx, metals, commodity,
`us-treasuries-yield`), the engine's own `pass_fail` column.
- **Peer path** (`mode is None`): uses `lazer_dq/peer_benchmark.py`. Window
  is the last `--peer-days` (default 2) days of the session's open-minute
  mask (never extending past its start). Reference is the feed's own
  aggregate from `price_feeds` (tries `channel` 1, 2, then 3 — first
  non-empty wins), candidate series is their raw per-second
  `publisher_updates` (same ACCEPTED/UNAUTHORIZED-rejected + production-key
  filter as candidate discovery), both restricted to open minutes and
  aligned last-observation-per-second. `evaluate_peer` computes NRMSE
  (`rmse / (max(agg) - min(agg))`) and hit rate (`|diff| / |agg_price| <=
0.1%`); requires `n_observations >= --min-obs`; passes if `nrmse <
--peer-nrmse-auto` or (`nrmse < --peer-nrmse-cond` and `hit_rate >=
--peer-hit-rate`) — the same relaxed-tier shape as
  `lib/thresholds.py`.

If **no** candidate passes Gate 2, the (feed, session) is flagged
`candidates_fail_quality`.

### Selection

Gate-2 passers are ranked ascending by their quality metric
(`rmse_over_spread` on the engine path, `nrmse` on the peer path — lower is
better) and added one at a time, recomputing the **worst-minute** projected
active count (`projected_worst_minute`, joining each candidate's own
per-minute activity onto the Stage-1 window) after each addition, until it
reaches `min_pub + --target-margin` (default `min_pub + 2`) or passers run
out. If the target is never reached, every passer is still added and the
(feed, session) is additionally flagged `still_below_target` — a feed at
static margin 0 or 1 can never clear the target through activity alone; its
`flagged_feeds.csv` row records that its fix needs new publishers by
construction.

### Output files (four)

| File                                     | Contents                                                                                                                 |
| ---------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| `candidates_report.csv`                  | one row per candidate per (feed, session): activity, both gates' metrics, `selected`, `selection_rank`                   |
| `qualification_summary.csv`              | one row per flagged (feed, session): before/after projections and counts at each stage                                   |
| `flagged_feeds.csv`                      | one row per (feed, session) that Stage 2 could not fully remediate, with a reason                                        |
| `min_pub_activity/feed_<feed_id>.csv.gz` | the per-minute per-publisher activity matrix queried for that feed (gitignored; reused by Stage 3's projection re-check) |

`candidates_report.csv` columns (17): `feed_id`, `symbol`, `session`,
`classification`, `candidate_publisher_id`, `activity_pct`, `gate1_pass`,
`quality_path` (`engine` or `peer`), `engine_mode`, `benchmark_date`,
`rmse_over_spread`, `hit_rate`, `n_obs`, `nrmse`, `gate2_pass`, `selected`,
`selection_rank`.

`qualification_summary.csv` columns (13): `feed_id`, `symbol`, `session`,
`classification`, `effective_min_pub`, `target` (`effective_min_pub +
target_margin`), `worst_minute_before`, `n_candidates`, `n_gate1`,
`n_gate2`, `n_selected`, `projected_worst_after`, `met_target`.

`flagged_feeds.csv` columns (6): `feed_id`, `symbol`, `session`,
`classification`, `reason`, `detail`. `reason` is one of `no_candidates`,
`candidates_fail_activity`, `candidates_fail_quality`,
`still_below_target`, `no_benchmark_data`.

## 4. Stage 3 — Apply + verify (`lazer_dq/apply_min_pub_remediation.py`)

Turns Stage 2's `selected` rows into a batched `edit_config.py` spec, runs
it, and verifies the result. **Dry-run by default** — nothing is written to
the config unless `--apply` is passed.

```bash
# Dry run — preview the spec and the edit_config diff, write nothing
python3 -m lazer_dq.apply_min_pub_remediation --config lazer_to_modify.json \
    --start-date 2026-07-06 --end-date 2026-07-13

# Apply — write the config and run all verification checks
python3 -m lazer_dq.apply_min_pub_remediation --config lazer_to_modify.json \
    --start-date 2026-07-06 --end-date 2026-07-13 --apply
```

### CLI

| Flag               | Default                                | Notes                                                        |
| ------------------ | -------------------------------------- | ------------------------------------------------------------ |
| `--config`         | required                               | edited in place when `--apply` is passed                     |
| `--candidates-csv` | `output_csv/candidates_report.csv`     | Stage-2 output                                               |
| `--summary-csv`    | `output_csv/qualification_summary.csv` | Stage-2 output, used by the verification checks              |
| `--activity-dir`   | `output_csv/min_pub_activity`          | per-feed activity matrices from Stage 2                      |
| `--start-date`     | required                               | should match the Stage 1/2 window                            |
| `--end-date`       | required                               | should match the Stage 1/2 window                            |
| `--apply`          | off (dry-run)                          | actually write the config via `edit_config.py --apply`       |
| `--skip-linter`    | off                                    | skip check 2 (records it as `SKIPPED` in the report instead) |
| `--output-dir`     | `output_csv`                           | where the spec YAML and report CSVs are written              |

### The spec

`build_spec` groups every `selected == True` row from `candidates_report.csv`
by `(candidate_publisher_id, session)` and emits one `add_publisher`
operation per group, covering all its feed IDs as a comma-joined list (the
`edit_config.py` batching syntax). `session` is omitted from the op when it
is `REGULAR` (the tool's default). The resulting YAML
(`{"version": 1, "operations": [...]}`) is written to
`output_csv/min_pub_remediation_spec.yaml` and passed to `edit_config.py
--from-spec <path>`, which does the actual JSON surgery (schedule
inheritance, formatting-preserving edits — see
[docs/edit_config.md](docs/edit_config.md)). If nothing was selected in
Stage 2, the script prints a message and exits `0` without invoking
`edit_config.py`.

If `edit_config.py` itself exits non-zero, the stage aborts (return `1`)
without running verification; the config may or may not have been partially
modified depending on how far `edit_config.py` got — check `git diff`.

### Verification (only runs after `--apply`)

Four checks, written to `verification_report.csv`
(`check`, `feed_id`, `session`, `status`, `detail`; `status` is `PASS`,
`FAIL`, or `SKIPPED`):

1. **`selected_applied` / `static_margin`** (`verify_static`) — reloads the
   just-written config and, per remediated (feed, session): fails if the raw
   `allowedPublisherIds` list has duplicate entries; fails
   `selected_applied` if any selected candidate ID is missing from the
   session's allowed list after the edit; and, where Stage 2 recorded
   `met_target == True`, checks `static_margin` — `len(allowed) >= target`.
2. **`linter`** — runs `tools/config-linter/config_linter.py --config
<config> --format json` **before** the edit (baseline) and **after**
   (post-apply), and compares the real `ERROR`-severity finding counts.
   `PASS` if the after-count did not increase; `FAIL` if it did. This is a
   **before/after delta**, not a zero-errors requirement — on the current
   repo config the linter reports roughly 5,070 pre-existing errors (the
   linter still assumes the old feed-level-`allowedPublisherIds` config
   format, per the `New config format` gotcha below, and misreads the
   new-format session-only config), so comparing to zero would be
   meaningless. If the linter subprocess itself fails, times out, or its
   output can't be parsed into a count (`_parse_linter_error_count` returns
   `None`) either before or after, the check is recorded as `SKIPPED`
   instead of `FAIL`. Skip this whole check with `--skip-linter`.
3. **`projected_margin`** (`verify_projection`) — recomputes the
   worst-minute active count from Stage 2's saved activity matrices, using
   the **post-apply** allowed set for each remediated (feed, session).
   `PASS` if the projected worst-minute count now meets the Stage-2 target,
   **or** if Stage 2 had already recorded `met_target == False` for that
   row (i.e. it was already flagged as unfixable — not a regression to
   still miss it). `SKIPPED` if the session, its schedule, its activity
   matrix file, or its summary row is missing.
4. **Human review** — not an automated check; the script always prints
   `Review 'git diff' on the config plus the CSVs before committing.` after
   the verification summary. Nothing in this pipeline commits on your
   behalf.

`applied_changes.csv` (`feed_id`, `symbol`, `session`, `publisher_id`,
`quality_path`, `selection_rank`) is written right after the config edit
succeeds, independent of verification outcome.

### Exit codes

- `0` — dry-run completed (no write attempted), or nothing was selected, or
  `--apply` succeeded with zero `FAIL` rows in the verification report
  (`SKIPPED` rows do not count as failures).
- `1` — the `edit_config.py` subprocess exited non-zero, **or** at least one
  verification check `FAIL`ed after `--apply`.

## 5. Worked example

A full 7-day cycle against `lazer_to_modify.json`:

```bash
# Stage 1 — audit the last 7 full UTC days (16 workers for the multi-hour scan)
python3 -m lazer_dq.audit_min_pub --config lazer_to_modify.json \
    --start-date 2026-07-06 --end-date 2026-07-13 --workers 16

# Review output_csv/min_pub_audit_2026-07-06_2026-07-13.csv and
# output_csv/hygiene_report.csv before continuing.

# Stage 2 — qualify candidates for every CRITICAL/WARN row from Stage 1
python3 -m lazer_dq.qualify_candidates --config lazer_to_modify.json \
    --audit-csv output_csv/min_pub_audit_2026-07-06_2026-07-13.csv \
    --start-date 2026-07-06 --end-date 2026-07-13 --cluster lazer-prod

# Review candidates_report.csv, qualification_summary.csv, flagged_feeds.csv.

# Stage 3 — dry run first
python3 -m lazer_dq.apply_min_pub_remediation --config lazer_to_modify.json \
    --start-date 2026-07-06 --end-date 2026-07-13

# Looks right — apply for real
python3 -m lazer_dq.apply_min_pub_remediation --config lazer_to_modify.json \
    --start-date 2026-07-06 --end-date 2026-07-13 --apply

# Review git diff lazer_to_modify.json, verification_report.csv,
# applied_changes.csv, and flagged_feeds.csv, then commit the config
# change manually.
```

`--start-date`/`--end-date` must be identical across all three commands (the
Stage-1 CSV filename and Stage-2's activity matrices are keyed to that
window).

## 6. Caveats

- **Peer-benchmark circularity.** For feeds with no Datascope coverage (and,
  on this branch, `Equity.JP.*`/`Equity.KR.*`/`Equity.IN.*`), Gate 2 checks a
  candidate against the feed's own `price_feeds` aggregate — which is itself
  built from the currently allowed publishers, potentially including
  publishers close to the same margin problem being fixed. This is a design
  trade-off accepted deliberately (see the 2026-07-13 spec), not an
  oversight: there is no independent benchmark for these asset classes.
  Treat peer-path passes as weaker evidence than engine-path (Datascope)
  passes when reviewing `candidates_report.csv`.
- **Flat-reference feeds never pass the peer gate.** If a feed's own
  aggregate has zero price variance over the peer window (observed in live
  smoke testing on NAV feeds, whose reference price barely moves), `agg_range
<= 0` and `evaluate_peer` returns `reason: "zero_range"` with `passed:
False` unconditionally — no candidate can ever clear Gate 2 for that
  feed, regardless of how closely it tracks the reference. These feeds land
  on `flagged_feeds.csv` with `candidates_fail_quality` and require manual
  remediation (or a widened peer methodology) rather than another pipeline
  run.
- **`NO_SCHEDULE` rows never reach Stage 2.** Any session whose
  `marketSchedule` string is missing or fails to parse is classified
  `NO_SCHEDULE` in Stage 1 and is silently excluded from Stage 2's flagged
  set (`iter_stable_sessions` only yields sessions where `schedule_str is
not None`, and Stage 2 additionally requires it to be a resolvable
  schedule when building its worklist). A `NO_SCHEDULE` feed needs its
  config schedule fixed by hand before this pipeline can help it.
- **The linter check can be `SKIPPED`, not just pass/fail.** `config_linter.py`
  was built for the old (feed-level `allowedPublisherIds`) config format —
  see the `New config format` gotcha below. Against a new-format config it
  still runs and returns a JSON error count (currently ~5,070 pre-existing
  findings, mostly artifacts of the format mismatch rather than real
  issues), which is why Stage 3 compares before/after counts instead of
  requiring zero. If the linter subprocess fails outright, times out, or
  its output is unparseable, the check degrades to `SKIPPED` rather than
  blocking the apply.
- **Equity coverage gap.** `engine_mode_for` only routes `Equity.US.*` and
  `Equity.HK.*` (`REGULAR` session) to the DQ engine. JP/KR/IN equities have
  no engine mode on this branch, so they always take the peer path — even
  though Datascope coverage for those markets may exist elsewhere in the
  codebase (a separate, not-yet-merged branch adds `jp-equities` /
  `kr-equities` / `in-equities` modes to `evaluate_feed_standalone`). Once
  those modes land here, `engine_mode_for` should be extended to route them
  to the engine path for a stronger quality signal.
