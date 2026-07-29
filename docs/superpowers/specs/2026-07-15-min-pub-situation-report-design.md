# Design: min_pub Situation Report (2026-07-15)

## Goal

Produce a comprehensive, self-contained markdown report of the current min_pub
situation for the feeds in `lazer_new.json`, synthesized from the existing
`audit_min_pub.py` and `qualify_candidates.py` outputs (Jul 13–14 run), for the
internal Lazer team.

## Deliverable

`docs/min_pub_report_2026-07-15.md`, committed to git. No links into
`output_csv/` (untracked); all per-feed detail is inlined.

## Data sources

| Source                                               | Produced | Role                                                                                       |
| ---------------------------------------------------- | -------- | ------------------------------------------------------------------------------------------ |
| `output_csv/min_pub_audit_2026-07-06_2026-07-13.csv` | Jul 13   | Stage 1 audit: 2,505 feed-session rows, 1,645 unique feeds                                 |
| `output_csv/flagged_feeds.csv`                       | Jul 14   | Stage 2 output: 393 still-flagged feed-sessions (370 feeds)                                |
| `output_csv/qualification_summary.csv`               | Jul 14   | Stage 2 per-feed-session funnel: 617 rows                                                  |
| `output_csv/candidates_report.csv`                   | Jul 14   | Stage 2 per-candidate detail: 6,607 rows (used for drill-downs)                            |
| `output_csv/min_pub_remediation_spec.yaml`           | Jul 14   | Stage 3 spec: 55 ops, 256 publisher additions, 31 publishers, 191 feeds — NOT yet applied  |
| `lazer_to_modify.json`                               | Jul 14   | Config the pipeline ran against                                                            |
| `lazer_new.json`                                     | Jul 15   | Current config snapshot the report describes (75 feeds differ from `lazer_to_modify.json`) |

## Report structure

1. **Executive summary** — headline counts (OK 1,888 / WARN 369 / CRITICAL 248
   feed-sessions), remediation coverage (245 of 617 flagged feed-sessions met
   target), spec pending application, 393 feed-sessions with no automatic fix.
2. **Methodology & provenance** — audit window 2026-07-06 → 2026-07-13, config
   used per stage, caveats: peer-comparison circularity for non-Datascope
   feeds, flat-NAV peer-gate limitation, benchmark window matching.
3. **Audit results** — classification breakdown by asset type and session;
   severity highlights: 95 CRITICAL rows with a zero-active-publisher worst
   minute, 121 rows with minutes below minPublishers, 390 prolonged.
4. **Qualification outcomes** — gate funnel (candidates → activity gate →
   quality gate → selected), 256 selected additions split by session
   (OVER_NIGHT 103, REGULAR/default 77, POST_MARKET 49, PRE_MARKET 27).
5. **Remediation plan status** — spec summary, explicit "pending" call-out,
   exact `apply_min_pub_remediation` command to apply it.
6. **Unresolvable feeds** — 393 flagged rows by reason
   (candidates_fail_quality 210, no_candidates 77, no_benchmark_data 63,
   candidates_fail_activity 27, still_below_target 16) with recommended
   disposition per bucket.
7. **Config drift appendix** — the 75 feeds changed between
   `lazer_to_modify.json` and `lazer_new.json`; flag the 16 that are also in
   the flagged set (their audit rows may be stale).
8. **Full flagged-feed appendix** — all 393 flagged rows joined with their
   qualification outcome (candidates, gates passed, selected, projection).

## Verification before finalizing

- Trace the 21 flagged rows that show `met_target=True` in
  `qualification_summary.csv` and explain them in the report (or correct the
  counts if they indicate a join error).
- Cross-check totals across CSVs: audit non-OK (617) = qualification rows;
  flagged reasons sum to 393; spec additions (256) = qualification
  `n_selected` sum.
- Spot-check at least 3 feeds' current state/publishers in `lazer_new.json`
  against report claims.

## Out of scope

- Re-running the audit or qualification pipeline against `lazer_new.json`.
- Applying the remediation spec.
- Config hygiene findings (`hygiene_report.csv`) — excluded by user choice.
