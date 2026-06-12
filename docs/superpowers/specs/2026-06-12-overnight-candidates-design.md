# Overnight Candidate Identification for US Equities

**Date:** 2026-06-12
**Status:** Design approved, pending implementation plan

## Problem

We need to give BlueOcean a prioritized list of US equity tickers worth adding
overnight (8 PM–4 AM ET) trading support. BlueOcean is the overnight venue; Pyth
wants to inform them which tickers, from the feeds Pyth already runs, have enough
liquidity and extended-hours activity to justify an overnight session.

The candidate pool is US equity feeds that are live (or about to be) but do **not**
yet carry an `OVER_NIGHT` session in `lazer_test.json`. We rank these by their
volume profile and hand the sorted metrics to a human, who draws the cutoff.

## Candidate Universe

From `lazer_test.json` (`Equity.US.*` feeds):

| State       | Has overnight | No overnight |
| ----------- | ------------- | ------------ |
| STABLE      | 168           | 665          |
| COMING_SOON | 197           | 10           |
| INACTIVE    | 4             | 80           |

**Universe = the 675 feeds where `state ∈ {STABLE, COMING_SOON}` and no
`OVER_NIGHT` session exists.** INACTIVE feeds are excluded. Feeds that already
have an overnight session (~365) are excluded — they are already covered.

A feed "has an overnight session" iff any entry in its `marketSchedules` array has
`session == "OVER_NIGHT"`.

## Methodology Note (why not use `overnight_benchmark_obs`)

`volume_profile.py`'s built-in "24/5 viable" recommendation depends on
`overnight_benchmark_obs` (publisher updates 8 PM–4 AM ET). Our candidates have **no
overnight publishers yet**, so that column reads ~0 for exactly the tickers we are
trying to qualify — it is circular. The robust signal for a net-new overnight
candidate is **liquidity tier + after-hours activity** (after-hours dollar volume /
AH %), since after-hours interest is the best available proxy for overnight demand.
We rank on that and ignore `overnight_benchmark_obs`.

## Design

Three small steps. The volume engine (`volume_profile.py`) is reused unchanged; new
logic is isolated in two thin scripts.

### Step 1 — Candidate extraction

`extract_overnight_candidates.py`:

- Reads `lazer_test.json`.
- Selects `Equity.US.*` feeds where `state ∈ {STABLE, COMING_SOON}` and no
  `marketSchedule` entry has `session == "OVER_NIGHT"`.
- Maps symbol `Equity.US.XXX/USD → XXX`.
- Writes `overnight_candidates_tickers.txt` (one ticker per line, ~675 lines).
- Retains a `ticker → {feedId, state}` map for the final join. This can be written
  to a side file (e.g. `overnight_candidates_meta.csv`) so step 3 does not need to
  re-parse the JSON.

Input path (`lazer_test.json`) and output paths are CLI arguments with these
defaults.

### Step 2 — Volume measurement (existing tool, unchanged)

```bash
python3 volume_profile.py --ticker-file overnight_candidates_tickers.txt --date 2026-06-11
```

- `2026-06-11` is the last completed trading day relative to today (2026-06-12,
  Friday); 06-11 is a Thursday. Single day, per the chosen window.
- These are onboarded feeds, so they resolve to the **Datascope** path → real
  per-session share and dollar volume, including measured after-hours volume.
- Produces `output_csv/volume_profile_2026-06-11.csv` (and an `.html`).

### Step 3 — Rank and assemble

`rank_overnight_candidates.py`:

- Reads the `volume_profile` output CSV and the `ticker → {feedId, state}` map from
  step 1.
- Joins on ticker; sorts **descending by `after_hours_dollar_vol`** (primary
  overnight signal).
- Emits `overnight_candidates_for_blueocean.csv` with raw metrics — **no tiering,
  no cutoffs**:

  ```
  ticker, feedId, state, liquidity_tier, total_dollar_vol,
  regular_dollar_vol, after_hours_dollar_vol, after_hours_pct,
  pre_market_dollar_vol
  ```

- Prints a short summary (counts; top tickers by after-hours dollar volume).

The human draws the cutoff by eyeballing the sorted CSV.

### Error handling

- Tickers present in the candidate list but **absent from the volume CSV** (no
  Datascope data for 2026-06-11 — non-trading edge cases, unresolved symbols) go
  into a separate `unresolved` list reported in the step-3 summary. They are **not**
  silently dropped.
- If `volume_profile.py` itself errors or returns zero rows, step 3 surfaces that
  rather than emitting an empty BlueOcean list.

## Out of Scope

- Price-quality / benchmark evaluation of the candidates (that is
  `feed_readiness.py` / `publisher_benchmark.py`).
- Editing `lazer_test.json` to add overnight sessions. This task only produces the
  candidate list to inform BlueOcean.
- Automated thresholds / pass-fail tiers — explicitly deferred to the human.

## Files

| File                                     | Role                                 |
| ---------------------------------------- | ------------------------------------ |
| `extract_overnight_candidates.py`        | New — step 1 extraction              |
| `rank_overnight_candidates.py`           | New — step 3 ranking/assembly        |
| `volume_profile.py`                      | Existing — reused unchanged          |
| `overnight_candidates_tickers.txt`       | Generated — ticker file for the tool |
| `overnight_candidates_meta.csv`          | Generated — ticker→feedId/state map  |
| `overnight_candidates_for_blueocean.csv` | Generated — final ranked deliverable |
