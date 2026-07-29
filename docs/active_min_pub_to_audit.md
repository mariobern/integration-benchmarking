# active_min_pub_to_audit

Adapter that filters an `active_min_pub.py` summary CSV down to the feed-sessions
worth routing into the existing min_pub Stage 2/3 remediation pipeline
(`qualify_candidates.py` → `apply_min_pub_remediation.py`), and produces a
drop-in `--audit-csv` for Stage 2 without any change to Stage 2 or Stage 3
themselves.

## Why `effective_min_pub >= 2`

A feed-session's `active_min_pub` verdict (`BREACH` or `CRITICAL`) says the
aggregate is running at or below its `minPublishers` floor. Whether that's
_fixable_ by qualifying a new publisher depends on whether a second publisher
could plausibly exist: feed-sessions with `effective_min_pub == 1` (internal
`Pyth.*`/`Custom.*` feeds, interest-rates, some thin futures) are structurally
single-source — there is no second candidate for Stage 2 to find. This rule was
derived empirically from a hand-curated triage of the 2026-07-22 CRITICAL
snapshot: every `actionable == "yes"` row had `effective_min_pub >= 2` and every
`actionable == "no"` row had `effective_min_pub == 1`, with zero exceptions
across 87 rows, and cross-checked against `audit_min_pub`'s independent
allowed-publisher-availability signal (see
`docs/superpowers/specs/2026-07-29-active-min-pub-to-audit-design.md` for the
full analysis).

## Usage

    python3 -m lazer_dq.active_min_pub_to_audit \
        --active-min-pub-csv output_csv/active_min_pub_2026-07-14_2026-07-22.csv \
        [--min-pub-floor 2] [--include-warn] [--output-dir output_csv]

The input must be a **standard** `active_min_pub.py` summary CSV
(`active_min_pub_<start>_<end>.csv`) — not the hand-curated
`active_min_pub_CRITICAL_<date>.csv` snapshot, which has no `verdict` column.
The `<start>_<end>` window is parsed from the input filename; there are no
separate date flags.

- `--min-pub-floor` (default `2`) — the `effective_min_pub` threshold below
  which a `BREACH`/`CRITICAL` row is excluded rather than flagged.
- `--include-warn` (default off) — also route `WARN`-verdict rows through the
  same split. Off by default: WARN ("living one publisher above the floor") is
  a lower-urgency signal than BREACH/CRITICAL and isn't part of this pass.

## Output

Two CSVs per run, named from the input file's own `<start>_<end>` window:

### Flagged — `output_csv/active_min_pub_flagged_<start>_<end>.csv`

A drop-in `--audit-csv` for `qualify_candidates.py`:

`feed_id, symbol, session, classification, source_verdict, asset_type,
effective_min_pub, pct_below_par, pct_at_par, pct_at_floor, pct_at_floor_1,
min, median, n_updates`

`classification` is always `"CRITICAL"` (both `BREACH`- and `CRITICAL`-sourced
rows) or `"WARN"` (with `--include-warn`) — the literal values Stage 2 expects.
`source_verdict` keeps the original `active_min_pub` verdict for traceability.
Sorted by `pct_at_floor` descending.

### Excluded — `output_csv/active_min_pub_excluded_<start>_<end>.csv`

`feed_id, symbol, session, source_verdict, effective_min_pub, pct_at_floor,
reason`

Rows that were `BREACH`/`CRITICAL` (or `WARN` with `--include-warn`) but fell
below `--min-pub-floor` — surfaced here rather than silently dropped.
`reason` is `"below_min_pub_floor_<N>"` where `<N>` is the `--min-pub-floor`
value used (the only exclusion rule that exists in v1).

## Running the full pipeline

    python3 -m lazer_dq.active_min_pub --config X --start-date A --end-date B
    python3 -m lazer_dq.active_min_pub_to_audit \
        --active-min-pub-csv output_csv/active_min_pub_A_B.csv
    python3 -m lazer_dq.qualify_candidates --config X \
        --audit-csv output_csv/active_min_pub_flagged_A_B.csv \
        --start-date A --end-date B
    python3 -m lazer_dq.apply_min_pub_remediation --config X \
        --start-date A --end-date B   # dry-run by default; add --apply to write
