# min_pub July 27 Detection + Remediation Pass — Design

Last updated: 2026-07-29

## 1. Goal

Re-run the `active_min_pub` detection sweep against `lazer_to_modify.json` as
of 2026-07-27, route the flagged (BREACH/CRITICAL/WARN) feed-sessions through
the existing Stage 2/3 min_pub remediation pipeline (PR #65's
`active_min_pub_to_audit.py` → `qualify_candidates.py` →
`apply_min_pub_remediation.py`), apply the qualified publisher additions to
`lazer_to_modify.json`, and produce a situation-report doc plus an HTML
artifact summarizing the pass — mirroring the reporting style used for the
Jul 15 situation report and the Jul 22 dominance de-risk exercise.

This is a continuation of PR #65 (which wired `active_min_pub`
BREACH/CRITICAL verdicts into the existing Stage 2/3 pipeline via
`active_min_pub_to_audit.py`), not new tooling — no code changes are expected
in this pass, only pipeline runs, config edits, and documentation.

## 2. Scope

- **In scope**: running the four-stage pipeline below against
  `lazer_to_modify.json`, reviewing and applying the resulting remediation
  spec, and writing the two report deliverables.
- **Out of scope**: changes to any of the pipeline scripts themselves
  (`active_min_pub.py`, `active_min_pub_to_audit.py`, `qualify_candidates.py`,
  `apply_min_pub_remediation.py`, `edit_config.py`) — if a bug or gap is
  discovered while running the pipeline, it gets flagged and handled as a
  separate fix, not folded into this pass silently.

## 3. Pipeline

All four stages run against `lazer_to_modify.json`. Outputs are written to a
dedicated `output_csv/2026-07-27_pass/` directory so they don't overwrite the
July 21 run's un-suffixed `qualification_summary.csv` /
`candidates_report.csv` / `flagged_feeds.csv`.

### Stage 0 — Detect (`active_min_pub.py`)

```
python3 -m lazer_dq.active_min_pub \
    --config lazer_to_modify.json \
    --start-date 2026-07-27 --end-date 2026-07-28
```

1-day snapshot window. Produces
`output_csv/active_min_pub_2026-07-27_2026-07-28.csv` and its histogram CSV.

### Stage 0.5 — Route (`active_min_pub_to_audit.py`)

```
python3 -m lazer_dq.active_min_pub_to_audit \
    --active-min-pub-csv output_csv/active_min_pub_2026-07-27_2026-07-28.csv \
    --include-warn \
    --output-dir output_csv/2026-07-27_pass
```

`--include-warn` is on for this pass (vs. PR #65's off-by-default), so WARN
feed-sessions ("one publisher above the floor") are routed into remediation
alongside BREACH/CRITICAL, not just the higher-urgency rows. Produces a
flagged CSV (drop-in `--audit-csv` for Stage 2, `classification` = `CRITICAL`
for BREACH/CRITICAL-sourced rows, `WARN` for WARN-sourced rows) and an
excluded CSV (rows below `--min-pub-floor 2`, i.e. structurally single-source
feed-sessions with no second publisher to qualify).

### Stage 2 — Qualify (`qualify_candidates.py`)

```
python3 -m lazer_dq.qualify_candidates \
    --config lazer_to_modify.json \
    --audit-csv output_csv/2026-07-27_pass/active_min_pub_flagged_2026-07-27_2026-07-28.csv \
    --start-date 2026-07-27 --end-date 2026-07-29 \
    --output-dir output_csv/2026-07-27_pass
```

Uses a 2-day window (07-27 → 07-29, end exclusive) rather than the 7-day
window used in the original Jul 13/14 pass. **Caveat carried into the
report**: 2 days is thinner history for the activity gate (≥90% of open
minutes) than the 7-day precedent, so qualification results here have more
noise than the Jul 13/14 pass — flagged explicitly, not glossed over.

### Stage 3 — Apply (`apply_min_pub_remediation.py`)

Two-step, with a **manual review checkpoint** between them:

```
# 1. Dry-run — generates the spec, does NOT touch lazer_to_modify.json
python3 -m lazer_dq.apply_min_pub_remediation \
    --config lazer_to_modify.json \
    --start-date 2026-07-27 --end-date 2026-07-29 \
    --output-dir output_csv/2026-07-27_pass
```

**Stop here.** The generated `min_pub_remediation_spec.yaml` is presented to
the user for review before proceeding — no `--apply` run happens until the
user confirms the spec looks right.

```
# 2. Apply — only after user sign-off on the dry-run spec
python3 -m lazer_dq.apply_min_pub_remediation \
    --config lazer_to_modify.json \
    --start-date 2026-07-27 --end-date 2026-07-29 --apply \
    --output-dir output_csv/2026-07-27_pass
```

This writes the qualified publisher additions into `lazer_to_modify.json` via
`edit_config.py`, then runs the built-in post-apply verification:
`static_margin` (every remediated feed-session has exactly the selected
publishers, no dupes, reaches target), `linter` (error count vs. pre-apply
baseline — best-effort, SKIPPED if the linter rejects the config format), and
`projected_margin` (worst-minute recomputation from Stage-2 activity
matrices). Verification results are reported as-observed, not assumed.

## 4. Report deliverables

### 4a. Situation-report doc

`docs/min_pub_report_2026-07-27.md`, structured like
`docs/min_pub_report_2026-07-15.md`:

- Executive summary (counts at each stage, headline numbers)
- Methodology & data provenance table (stage → tool → date run → config →
  output), same shape as the Jul 15 report's §2
- Detection results by asset type / verdict (OK / WARN / CRITICAL /
  BREACH), and the WARN-inclusion + thin-window caveats called out
  explicitly
- Qualification results (how many feed-sessions fixed vs. still flagged,
  win/dilution breakdown if it naturally falls out of the data)
- Applied changes: publisher additions count, feeds touched, verification
  outcome (static_margin / linter / projected_margin results)
- Caveats section (2-day window signal quality, WARN inclusion, any
  excluded structurally-unfixable feed-sessions)
- Appendix: pointers to `output_csv/2026-07-27_pass/*` artifacts and the
  applied spec YAML

### 4b. HTML artifact

New Claude Artifact (not overwriting the existing "Active Min-Publisher
Analysis · 14–17 Jul 2026" one, since it's a different window/pass), styled
to match: eyebrow header + stat-tile row (feed-sessions, OK, WARN, flagged),
verdict-key legend card, an overall inline-SVG histogram, per-asset-class
breakdown cards (histogram + collapsible flagged table), an equities-by-
session breakout, and a "set aside" appendix for excluded/structurally
unfixable feed-sessions. Light/dark theme support, monospace numerics,
same semantic color scheme (green/amber/red) as the prior artifact.

## 5. Definition of done

- [ ] Stage 0 detection CSV produced for 2026-07-27→2026-07-28
- [ ] Stage 0.5 flagged/excluded CSVs produced (WARN included)
- [ ] Stage 2 qualification outputs produced under
      `output_csv/2026-07-27_pass/`
- [ ] Stage 3 dry-run spec generated and reviewed with the user
- [ ] Stage 3 applied (post user sign-off) and post-apply verification
      passes (or failures are surfaced, not hidden)
- [ ] `docs/min_pub_report_2026-07-27.md` written
- [ ] HTML artifact published
- [ ] `lazer_to_modify.json` reflects the applied additions
