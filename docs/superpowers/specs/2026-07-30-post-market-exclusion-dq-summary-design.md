# dq_summary POST_MARKET Exclusion — Flagged Feed IDs

**Date:** 2026-07-30
**Status:** Design approved, pending implementation plan
**Scope:** One-off scratch script, not a repo module

## Background & Motivation

`dq_summary_lazer-prod_2026-07-28.xlsx` (produced by `lazer_dq/summarize_feeds.py`)
has an `allowed` sheet listing, per feed_id/session, the `allowedPublisherIds` to
apply to the live Lazer config. For the 29 feed IDs in
`missing_us_equities_post_2026-07-27.csv`, the `POST_MARKET` row is largely built
from top-up fills rather than genuine passers — several are `"0 passed + N
top-up (≤2×)"`, meaning no publisher actually met the benchmark threshold for
that session on 2026-07-28. These POST_MARKET entries should not be trusted or
carried forward into `apply_allowed_to_config.py`, so they need to be stripped
from the sheet before that step runs.

## Goal

Produce a corrected copy of the workbook where the `allowed` sheet's
`POST_MARKET` row is blanked out for exactly these 29 feed IDs, leaving every
other row (other sessions, other feed IDs, the `rankings` sheet) byte-for-byte
unchanged in content.

## In scope

- Read `missing_us_equities_post_2026-07-27.csv` (single `feed_id` column, 29
  rows) to get the target feed ID set.
- Read `dq_summary_lazer-prod_2026-07-28.xlsx`, `allowed` sheet.
- For each row where `Feed ID` (col A) is in the target set **and** `Session`
  (col B) is exactly `POST_MARKET`:
  - Set `allowedPublisherIds` (col C) to the literal string `(excluded)`.
  - Set `Notes` (col D) to
    `excluded — see missing_us_equities_post_2026-07-27.csv`, overwriting
    whatever was there before (including existing top-up notes and `mode
    missing for 2026-07-28` notes — both get the same treatment so the sheet
    reads uniformly across all 29 feeds).
- Write the result to a new file,
  `dq_summary_lazer-prod_2026-07-28_post-excluded.xlsx`, in the repo root.
- Leave the original `.xlsx` untouched.

## Out of scope

- The `rankings` sheet — not read or modified.
- Any other session (`(aggregate)`, `REGULAR`, `PRE_MARKET`, `OVER_NIGHT`) for
  any feed ID, including the 29 flagged ones.
- Any feed ID not in the CSV, including its own `POST_MARKET` row.
- Re-running `summarize_feeds.py` or touching ClickHouse in any way — this is a
  pure post-processing pass over an already-generated workbook.
- Editing any Lazer config JSON or running `apply_allowed_to_config.py` — this
  script only prepares a cleaned-up input for that step; applying it is a
  separate, later action.
- Adding this as a permanent CLI tool under `lazer_dq/` — this is a one-time
  correction for this specific date's workbook, not a recurring pipeline stage.
  (`summarize_feeds.py`'s existing `--exclude-publisher` flag is global across
  all feeds/sessions and can't target "this session, these feed IDs only,"
  which is why a post-processing script is used instead of a rerun.)

## Implementation notes

- Use `openpyxl`, loaded **without** `data_only=True` (that flag is for reading
  cached formula values; loading that way and re-saving can silently drop
  formatting/formulas elsewhere in the workbook). Since we only need to read
  and write plain string cells on the `allowed` sheet, a normal load-and-save
  round-trip preserves everything else in the workbook (styles, the `rankings`
  sheet, column widths) as-is.
- Match feed_id by exact integer equality; the sheet uses `None` for the blank
  separator rows between feeds (see row 6 in the existing dump — a fully blank
  row after each feed's 5 session rows), so iterate by tracking the
  "current feed_id" (carried forward from the last non-`None` col-A cell,
  since only the first row of each feed's block repeats the ID) rather than
  requiring col A to be non-null on every row.
- Script lives in the scratchpad directory (not committed to the repo), since
  it's a one-time correction, not a reusable tool.

## Verification

- Row count in the `allowed` sheet is unchanged (no rows added or removed).
- For all 29 feed IDs: `POST_MARKET` row now reads `(excluded)` /
  `excluded — see missing_us_equities_post_2026-07-27.csv`.
- For all 29 feed IDs: `(aggregate)`, `REGULAR`, `PRE_MARKET`, `OVER_NIGHT` rows
  are byte-identical to the original.
- For every other feed ID (not in the CSV): all 5 rows are byte-identical to
  the original.
- `rankings` sheet is byte-identical to the original.

## Open Questions

None — this is a self-contained, single-run correction.
