# Revert RIC Corrections in `lazer_new.json`

**Date:** 2026-06-19
**Status:** Approved (design)

## Problem

A prior operation rewrote the `datascope_ric` benchmark identifiers for a set of
`Equity.US.*` feeds in `lazer_new.json`, stripping or changing the exchange
suffix (e.g. `JPM.N` → `JPM`, `ABBV.N` → `ABBV.K`). We want to **revert** these
feeds so the original RIC is restored (e.g. `JPM` → `JPM.N`).

The change set is described by `ric_corrections.csv` (328 rows):

```
feedId,symbol,state,confidence,current_day_ric,expected_day_ric
1223,Equity.US.JPM/USD,STABLE,medium,JPM.N,JPM
```

- `current_day_ric` — the **original** RIC we want to restore.
- `expected_day_ric` — the value the operation applied; this is what the config
  currently holds.

Verified: for all 328 rows, the config's day-session `datascope_ric` identifiers
currently equal `expected_day_ric` exactly.

## Goal

Restore `current_day_ric` for the affected feeds' **day sessions** (REGULAR,
PRE_MARKET, POST_MARKET), leaving overnight RICs untouched.

## Scope

### Feeds reverted: 325 of 328

Three rows have a genuinely broken original RIC and are **skipped** (left at their
current corrected value, per user decision):

| feedId | symbol | original (skipped) | kept value | reason                          |
| ------ | ------ | ------------------ | ---------- | ------------------------------- |
| 3227   | ALNY   | `LIN.O`            | `ALNY.O`   | `LIN.O` is Linde, wrong company |
| 1080   | DIA    | `BAC\|DIA.N`       | `DIA`      | malformed `BAC\|` prefix        |
| 1143   | FSLR   | `FLSR.O`           | `FSLR.O`   | `FLSR` is a typo of `FSLR`      |

`BRK-A` / `BRK-B` keep their dotted-ticker originals (`BRKa.N` / `BRKb.N`), which
are correct, and revert normally.

### Sessions touched

Within each reverted feed, update `datascope_ric` identifiers in **non-overnight**
sessions only:

- REGULAR, PRE_MARKET, POST_MARKET → reverted.
- OVER_NIGHT → **untouched** (uses a separate `.BLUE` RIC, e.g. `JPM.BLUE`).

The `identifier` string changes from `expected_day_ric` → `current_day_ric`; the
`validFrom` timestamp is preserved.

## RIC location in the config

```
feed.marketSchedules[i].benchmarkMapping.datascope_ric.identifiers[j].identifier
```

## Safety / preconditions

Before writing, the script asserts per targeted session:

1. The session's current `datascope_ric` identifier equals `expected_day_ric`.
   If not (already changed elsewhere), **skip that session** and report it —
   never blind-overwrite.
2. Single-identifier history per session is expected. A session with multiple
   `datascope_ric` identifiers is flagged for manual review rather than edited.
3. Skip the 3 broken feedIds listed above.

## Implementation

A one-off Python script:

1. Load `ric_corrections.csv` and `lazer_new.json`.
2. Build a `feedId → row` map; exclude the 3 skipped feedIds.
3. For each remaining feed, walk `marketSchedules`; for each non-overnight
   session whose `datascope_ric` identifier == `expected_day_ric`, set it to
   `current_day_ric`.
4. Write back with `json.dump(..., indent=2, ensure_ascii=False)` plus a trailing
   newline.

Formatting fidelity: a `json.load`/`json.dump(indent=2, ensure_ascii=False)`
round-trip on `lazer_new.json` is byte-identical except for adding a trailing
newline (verified), so the git diff contains only the changed RIC lines.

### Modes

- `--dry-run` — report planned changes (feed count, session count, skips,
  mismatches) without writing. Run first.
- Default — apply and write.

## Verification

- Dry-run summary: feeds reverted, sessions changed, 3 skipped, any unexpected
  mismatches (expected: 0).
- After apply: confirm JPM day sessions → `JPM.N`, ABBV → `ABBV.N`; confirm the
  3 skipped feeds (ALNY, DIA, FSLR) are unchanged; confirm overnight `.BLUE`
  RICs unchanged.
- `git diff --stat lazer_new.json` shows only RIC-line changes.
