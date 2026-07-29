# active_min_pub_to_audit — CRITICAL Feed-Session Handoff to Stage 2/3

**Date:** 2026-07-29
**Status:** Design approved, pending implementation plan
**Module:** `lazer_dq/active_min_pub_to_audit.py`

## Background & Motivation

`lazer_dq/active_min_pub.py` (shipped 2026-07-23) measures how often each STABLE
feed-session's *aggregate* `publisher_count` scrapes or breaches its `minPublishers`
floor. Its design spec explicitly left one question open:

> Whether to later feed CRITICAL feed-sessions into the existing Stage 2/3
> remediation pipeline (out of scope now).

This design answers that question. A recent snapshot
(`output_csv/active_min_pub_CRITICAL_2026-07-22.csv`, 87 rows) already carries
hand-added `category`/`actionable` columns from manual triage. Reverse-engineering
that triage against the raw data showed it reduces to a single exact rule with zero
exceptions across all 87 rows:

```
actionable == "yes"  iff  effective_min_pub >= 2
```

Every `actionable == "no"` row (internal `Pyth.*`/`Custom.*` feeds, interest-rates,
a handful of thin futures) has `effective_min_pub == 1`. These are structurally
single-source feed-sessions: there is no second publisher to qualify against, so
Stage 2 (candidate qualification) has nothing to act on. Every `actionable == "yes"`
row has `effective_min_pub >= 2` — real equities/crypto/nav feed-sessions where a
plausible second or third publisher candidate exists.

This was cross-checked against the existing Stage-1 audit
(`output_csv/audit_current/min_pub_audit_2026-07-15_2026-07-22.csv`): **all 34**
`effective_min_pub >= 2` CRITICAL feed-sessions are also flagged CRITICAL or WARN by
`audit_min_pub`'s allowed-publisher-availability signal. This confirms the root
cause is genuinely "too few allowed candidates," not an aggregation/filtering
artifact — so routing these into the existing Stage 2/3 mechanism (which adds
rebenchmarked publishers) is the correct remediation, not a different one.

Note for whoever runs this: cross-referencing ad-hoc Stage 2/3 batch directories
under `output_csv/` (`bucketA`, `pub20_severe`, `pub41_severe`, `pub19_severe`,
`pub71_7day`) — leftovers from the 2026-07-22 dominance de-risk work — shows about
12 of the 34 feed-sessions already have a Stage-2 "no qualifying candidate found"
result in `bucketA/flagged_feeds.csv`, and 2 (`Equity.US.CELH/USD` OVER_NIGHT,
`Equity.US.QUBT/USD` OVER_NIGHT) already had a candidate *selected* there. Whether
that selection was ever applied to a live config was not confirmed. This isn't a
blocker — Stage 2/3 is idempotent and config-driven, so a fresh run naturally
reflects whatever the current config already has — but it's worth a quick check
before assuming all 34 are still fully open.

## Relationship to the existing min_pub pipeline

This is a **new standalone adapter script**, not a modification to any shipped
pipeline stage. `lazer_dq/qualify_candidates.py` was inspected and confirmed to
read only `feed_id`, `session`, and `classification` from its `--audit-csv` input
(the full row is stashed in a dict but never indexed beyond membership checks) —
so any CSV carrying those three columns, with `classification` values in
`{"CRITICAL", "WARN"}`, is a valid drop-in input. `apply_min_pub_remediation.py`
downstream is untouched entirely; it consumes Stage 2's own output, not the audit
CSV.

```
                                    active_min_pub.py
                                            │  publisher_count per aggregate
                                            ▼
                            active_min_pub_<start>_<end>.csv  (verdict per feed-session)
                                            │
                                            ▼
                       [NEW] active_min_pub_to_audit.py
                            filter: verdict == CRITICAL
                                    AND effective_min_pub >= min_pub_floor (2)
                                            │
                    ┌───────────────────────┴───────────────────────┐
                    ▼                                                 ▼
   active_min_pub_flagged_<start>_<end>.csv          active_min_pub_excluded_<start>_<end>.csv
   (feed_id, symbol, session, classification,        (same rows, reason=min_pub_floor_1 —
    + passthrough metrics)                             surfaced, never silently dropped)
                    │
                    ▼
        qualify_candidates.py --audit-csv <flagged csv>   (UNCHANGED)
                    │
                    ▼
        apply_min_pub_remediation.py                       (UNCHANGED)
```

## Goal

Given an `active_min_pub.py` output CSV, produce an `--audit-csv`-compatible file
containing exactly the feed-sessions that are (a) CRITICAL by the aggregate-
contributor-count signal and (b) structurally capable of benefiting from a new
publisher (`effective_min_pub >= 2`), so they can be run through the existing,
unmodified Stage 2/3 tooling.

## Scope

**In scope:**

- New module `lazer_dq/active_min_pub_to_audit.py` (thin CLI, no ClickHouse access
  — pure CSV transform).
- Flagged-CSV + excluded-CSV output, console summary.
- Unit tests (`lazer_dq/tests/test_active_min_pub_to_audit.py`).
- Docs: `docs/active_min_pub_to_audit.md`, Scripts-table row, one CLAUDE.md gotcha
  line documenting the `min_pub >= 2` actionability rule.

**Out of scope:**

- Any change to `active_min_pub.py`, `qualify_candidates.py`,
  `apply_min_pub_remediation.py`, `audit_min_pub.py`.
- Actually qualifying or applying publishers — this script only reshapes/filters;
  Stage 2/3 does the real work, unchanged.
- WARN-verdict feed-sessions. `active_min_pub`'s WARN rows ("living one publisher
  above the floor") are excluded from this pass by default; only CRITICAL is
  routed forward, matching the immediate ask. An `--include-warn` flag is included
  for future use but defaults off.
- Investigating or resolving the `bucketA` overlap noted above — left as an
  operational check for whoever runs the pipeline, not something this script
  needs to detect or special-case.

## Filter logic

Expected input is the **standard** `active_min_pub.py` per-feed-session output
(`active_min_pub_<start>_<end>.csv`, columns `feed_id, symbol, asset_type, session,
effective_min_pub, n_updates, min, p1, p5, median, pct_at_floor, pct_at_floor_1,
verdict` per its own spec) — not the hand-curated
`active_min_pub_CRITICAL_<date>.csv` snapshot, whose `category`/`actionable`
columns were this design's input for reverse-engineering the rule but which has no
`verdict` column and isn't itself meant to be re-consumed. If the input filename
doesn't match the `active_min_pub_<start>_<end>.csv` pattern (so the date suffix
can't be parsed), the script errors out with a clear message rather than guessing
a fallback name.

Given one row of `active_min_pub`'s per-feed-session CSV:

```
include (→ flagged) if:
    verdict == "CRITICAL"                          (or also "WARN" if --include-warn)
    and effective_min_pub >= args.min_pub_floor     (default 2)

else if verdict == "CRITICAL" and effective_min_pub < args.min_pub_floor:
    include (→ excluded, reason="min_pub_floor_1")

else:
    drop silently (WARN/OK/LOW_SAMPLE/NO_DATA rows when --include-warn is off,
    or below the floor filter but not CRITICAL/WARN — these were never part of
    the actionable universe and don't need surfacing)
```

`min_pub_floor` is CLI-tunable rather than hardcoded to `2`, consistent with
`active_min_pub`'s own `--critical-pct`/`--warn-pct` pattern, in case future data
shows the boundary isn't always exactly 2 (e.g., a feed-session with `min_pub == 2`
that's also structurally single-source).

## Output

### Flagged CSV (Stage-2 input)

`output_csv/active_min_pub_flagged_<start>_<end>.csv`:

```
feed_id, symbol, session, classification, asset_type, effective_min_pub,
pct_at_floor, pct_at_floor_1, min, median, n_updates
```

`classification` is always `"CRITICAL"` (or `"WARN"`, passthrough from `verdict`
when `--include-warn` is set) — never re-derived, just copied from `verdict`. Sorted
by `pct_at_floor` descending, matching `active_min_pub`'s own severity ordering.

### Excluded CSV (visibility, not consumed downstream)

`output_csv/active_min_pub_excluded_<start>_<end>.csv`:

```
feed_id, symbol, session, effective_min_pub, pct_at_floor, reason
```

`reason` is `"min_pub_floor_1"` for every row in v1 (the only exclusion rule that
exists). Structured as a column rather than a fixed filename purpose so a future
second exclusion rule can reuse the same file/shape.

### Console summary

- Input row count, verdict tally of the input file.
- Flagged count / excluded count.
- If `--include-warn` is off, note how many WARN rows were present but skipped
  (visibility without changing default behavior).

## CLI & Structure

```bash
python3 -m lazer_dq.active_min_pub_to_audit \
    --active-min-pub-csv output_csv/active_min_pub_2026-07-14_2026-07-18.csv \
    [--min-pub-floor 2] [--include-warn] [--output-dir output_csv]
```

- `--active-min-pub-csv` — required; an `active_min_pub.py` output CSV.
- `--min-pub-floor` — default `2`.
- `--include-warn` — default off; when set, WARN-verdict rows are treated the same
  as CRITICAL for the flagged/excluded split.
- `--output-dir` — default `output_csv`, matching sibling scripts.
- Output filenames derive the `<start>_<end>` suffix from the input CSV's own
  filename (parsed, not re-specified via separate date flags) — the input file's
  name already encodes the window, so there is no independent date range for this
  script to accept.

No ClickHouse client, no config file — this is a pure pandas CSV transform, so no
`lib.config` dependency and no network calls.

## Testing

`lazer_dq/tests/test_active_min_pub_to_audit.py`, using small in-memory/fixture
CSVs (no ClickHouse mocking needed, unlike `active_min_pub`'s own tests):

- `effective_min_pub == 2` (boundary, included) vs `== 1` (excluded) vs `== 3`
  (included) — exact-boundary correctness.
- CRITICAL row with `--include-warn` off is included; WARN row with it off is
  dropped entirely (appears in neither output).
- CRITICAL row with `--include-warn` on and `min_pub == 1` lands in excluded with
  `reason=min_pub_floor_1`; WARN row with it on and `min_pub >= 2` lands in
  flagged with `classification=WARN`.
- OK/LOW_SAMPLE/NO_DATA verdict rows are dropped regardless of `min_pub_floor` or
  `--include-warn`.
- Empty input (zero CRITICAL rows) produces empty flagged/excluded CSVs with
  correct headers, not a crash.
- Output filename date-suffix parsing from an arbitrary input filename.

## Documentation

- `docs/active_min_pub_to_audit.md` — usage, filter rule and its empirical basis,
  output schema, and the explicit "flagged CSV is a drop-in `--audit-csv` for
  `qualify_candidates.py`" contract.
- Scripts table row in `CLAUDE.md`.
- One "Key Gotchas" line in `CLAUDE.md`: `active_min_pub_to_audit` routes CRITICAL
  feed-sessions into the existing Stage 2/3 pipeline only when
  `effective_min_pub >= 2` — `min_pub == 1` feed-sessions (internal `Pyth.*`/
  `Custom.*`, interest-rates, some thin futures) are structurally single-source
  and have no qualifiable second publisher, so they're excluded rather than fed
  into a mechanism that can't help them.

## Open Questions / Future Work

- Whether to fold WARN-verdict feed-sessions in by default once the CRITICAL-only
  pass has been run and validated end-to-end.
- Whether the `min_pub_floor >= 2` rule should eventually be pulled into
  `active_min_pub.py` itself as a verdict sub-classification (e.g.
  `CRITICAL_ACTIONABLE` vs `CRITICAL_SINGLE_SOURCE`) rather than living in this
  downstream adapter — deferred until the adapter has proven itself in practice.
- Confirming (outside this script) whether the `bucketA` selections for feed 2731
  (`Equity.US.CELH/USD` OVER_NIGHT) and 3356 (`Equity.US.QUBT/USD` OVER_NIGHT) were
  ever applied, so a fresh Stage 2/3 run doesn't redundantly re-surface them.
