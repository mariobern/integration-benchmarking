# min_pub Situation Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce `docs/min_pub_report_2026-07-15.md` — a self-contained situation report on min_pub health for the feeds in `lazer_new.json`, synthesized from the Jul 13–14 `audit_min_pub` / `qualify_candidates` outputs.

**Architecture:** A throwaway generator script computes verified numbers and emits every markdown table into a fragments file; the report is then hand-assembled from written prose plus those fragments. No pipeline re-runs, no ClickHouse access.

**Tech Stack:** Python 3 stdlib (`csv`, `json`) + `yaml`; markdown; pre-commit (black/prettier).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-15-min-pub-situation-report-design.md` — the report must follow its 8-section structure exactly.
- The report must be self-contained: no links into `output_csv/` (untracked) — all per-feed detail inlined.
- Use `python3`, never `python` (not on PATH).
- Run `pre-commit run --files <changed files>` before every commit.
- Work on branch `docs/min-pub-situation-report`.
- Scratchpad dir for the generator script and fragments: `/private/tmp/claude-501/-Users-mariobernardi-Documents-GitHub-integration-benchmarking/4ae83b26-7e5c-42a0-b3a9-4df5f72bb25b/scratchpad` (referred to as `$SCRATCH` below; substitute the literal path).
- Verified headline numbers (any mismatch during generation is a stop-and-investigate, not a typo to paper over): 2,505 audit rows / 1,645 feeds; OK 1,888, WARN 369, CRITICAL 248; 617 qualification rows; met_target 245 (203 via additions + 42 already at target); 256 selected additions = spec additions, 31 publishers, 191 feeds; 393 still flagged (372 unmet + 21 already-at-target with failing candidates); 75 drifted feeds (16 also flagged).

---

### Task 1: Fragment generator script

**Files:**

- Create: `$SCRATCH/build_report_tables.py` (throwaway — NOT committed)
- Output: `$SCRATCH/fragments.md`

**Interfaces:**

- Consumes: `output_csv/min_pub_audit_2026-07-06_2026-07-13.csv`, `output_csv/flagged_feeds.csv`, `output_csv/qualification_summary.csv`, `output_csv/min_pub_remediation_spec.yaml`, `lazer_new.json`, `lazer_to_modify.json` (all at repo root `/Users/mariobernardi/Documents/GitHub/integration-benchmarking`).
- Produces: `$SCRATCH/fragments.md` containing delimited sections `<!-- FRAGMENT: name -->` for: `audit-by-asset`, `audit-by-session`, `worst-offenders`, `funnel`, `spec-by-session`, `spec-by-publisher`, `unresolvable-by-reason`, `drift-table`, `appendix-flagged`. Tasks 2–3 paste these verbatim.

- [ ] **Step 1: Write the generator script**

```python
#!/usr/bin/env python3
"""Verified numbers + markdown fragments for the min_pub situation report."""
import csv
import json
import sys
from collections import Counter

import yaml

REPO = "/Users/mariobernardi/Documents/GitHub/integration-benchmarking"
OUT = sys.argv[1]

au = list(csv.DictReader(open(f"{REPO}/output_csv/min_pub_audit_2026-07-06_2026-07-13.csv")))
fl = list(csv.DictReader(open(f"{REPO}/output_csv/flagged_feeds.csv")))
qs = list(csv.DictReader(open(f"{REPO}/output_csv/qualification_summary.csv")))
spec = yaml.safe_load(open(f"{REPO}/output_csv/min_pub_remediation_spec.yaml"))
new = {f["feedId"]: f for f in json.load(open(f"{REPO}/lazer_new.json"))["feeds"]}
old = {f["feedId"]: f for f in json.load(open(f"{REPO}/lazer_to_modify.json"))["feeds"]}

failures = []

def check(name, actual, expected):
    ok = actual == expected
    print(f"{'OK  ' if ok else 'FAIL'} {name}: {actual} (expected {expected})")
    if not ok:
        failures.append(name)

# --- reconciliation checks (values pre-verified during brainstorming) ---
check("audit rows", len(au), 2505)
check("audit unique feeds", len({r["feed_id"] for r in au}), 1645)
cls = Counter(r["classification"] for r in au)
check("audit OK", cls["OK"], 1888)
check("audit WARN", cls["WARN"], 369)
check("audit CRITICAL", cls["CRITICAL"], 248)
check("qual rows == audit non-OK", len(qs), sum(v for k, v in cls.items() if k != "OK"))
check("qual rows", len(qs), 617)
check("flagged rows", len(fl), 393)
met = [r for r in qs if r["met_target"] == "True"]
check("met_target True", len(met), 245)
check("met via additions", sum(1 for r in met if int(r["n_selected"]) > 0), 203)
check("met already-at-target", sum(1 for r in met if int(r["n_selected"]) == 0), 42)
sel_sum = sum(int(r["n_selected"]) for r in qs)
check("selected sum", sel_sum, 256)
spec_feed_lists = [str(o["feed_id"]).split(",") for o in spec["operations"]]
check("spec additions == selected sum", sum(len(x) for x in spec_feed_lists), sel_sum)
check("spec unique publishers", len({o["publisher_id"] for o in spec["operations"]}), 31)
check("spec unique feeds", len({f for lst in spec_feed_lists for f in lst}), 191)
qkey = {(r["feed_id"], r["session"]): r for r in qs}
anom = [r for r in fl if qkey[(r["feed_id"], r["session"])]["met_target"] == "True"]
check("flagged with met_target=True", len(anom), 21)
check("flagged = 372 unmet + 21 anomaly", len(fl), 372 + 21)
changed = [k for k in new if json.dumps(new[k], sort_keys=True) != json.dumps(old[k], sort_keys=True)]
check("drifted feeds", len(changed), 75)
flids = {int(r["feed_id"]) for r in fl}
check("drifted & flagged", len(set(changed) & flids), 16)
check("CRITICAL zero-pub worst minute", sum(1 for r in au if r["classification"] == "CRITICAL" and int(r["worst_minute_active"]) == 0), 95)
check("rows with minutes_below_min>0", sum(1 for r in au if int(r["minutes_below_min"]) > 0), 121)
check("prolonged rows", sum(1 for r in au if r["prolonged"] == "True"), 390)

# --- fragment helpers ---
frags = []

def frag(name, header, rows):
    lines = [f"<!-- FRAGMENT: {name} -->", "| " + " | ".join(header) + " |",
             "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(str(c) for c in r) + " |" for r in rows]
    frags.append("\n".join(lines) + "\n")

def breakdown(key):
    agg = {}
    for r in au:
        agg.setdefault(r[key], Counter())[r["classification"]] += 1
    rows = []
    for k, c in sorted(agg.items(), key=lambda kv: -(kv[1]["WARN"] + kv[1]["CRITICAL"])):
        rows.append([k, c["OK"], c["WARN"], c["CRITICAL"], sum(c.values())])
    rows.append(["**total**", cls["OK"], cls["WARN"], cls["CRITICAL"], len(au)])
    return rows

frag("audit-by-asset", ["Asset type", "OK", "WARN", "CRITICAL", "Total"], breakdown("asset_type"))
frag("audit-by-session", ["Session", "OK", "WARN", "CRITICAL", "Total"], breakdown("session"))

worst = sorted(au, key=lambda r: (-int(r["minutes_below_min"]), -int(r["longest_run_le_min"])))[:15]
frag("worst-offenders",
     ["Feed", "Symbol", "Session", "Class", "minPub", "Allowed", "Min below min", "Longest run ≤ min", "Worst minute"],
     [[r["feed_id"], r["symbol"], r["session"], r["classification"], r["effective_min_pub"],
       r["allowed_count"], r["minutes_below_min"], r["longest_run_le_min"], r["worst_minute_active"]] for r in worst])

tot = lambda col: sum(int(r[col]) for r in qs)
frag("funnel", ["Stage", "Count"],
     [["Flagged feed-sessions entering qualification", len(qs)],
      ["Candidate (publisher, feed-session) pairs discovered", tot("n_candidates")],
      ["Passed gate 1 (activity ≥ 90% of open minutes)", tot("n_gate1")],
      ["Passed gate 2 (quality: Datascope or peer)", tot("n_gate2")],
      ["Selected for remediation", tot("n_selected")]])

sess_add = Counter()
pub_add = Counter()
for o in spec["operations"]:
    n = len(str(o["feed_id"]).split(","))
    sess_add[o.get("session", "REGULAR (default)")] += n
    pub_add[o["publisher_id"]] += n
frag("spec-by-session", ["Session", "Publisher additions"],
     sorted(sess_add.items(), key=lambda kv: -kv[1]))
frag("spec-by-publisher", ["Publisher", "Additions"],
     sorted(pub_add.items(), key=lambda kv: -kv[1]))

reasons = Counter(r["reason"] for r in fl)
rfeeds = {}
for r in fl:
    rfeeds.setdefault(r["reason"], set()).add(r["feed_id"])
frag("unresolvable-by-reason", ["Reason", "Feed-sessions", "Unique feeds"],
     [[k, v, len(rfeeds[k])] for k, v in reasons.most_common()])

audit_key = {(r["feed_id"], r["session"]): r for r in au}
drift_rows = []
for k in sorted(changed):
    so, sn = old[k].get("state"), new[k].get("state")
    kind = f"state {so} → {sn}" if so != sn else "publishers/minPublishers"
    drift_rows.append([k, new[k].get("symbol", "?"), kind,
                       "yes" if k in flids else "", ])
frag("drift-table", ["Feed", "Symbol", "Change (lazer_to_modify → lazer_new)", "Flagged?"], drift_rows)

app_rows = []
for r in sorted(fl, key=lambda r: (r["classification"] != "CRITICAL", int(r["feed_id"]))):
    q = qkey[(r["feed_id"], r["session"])]
    app_rows.append([r["feed_id"], r["symbol"], r["session"], r["classification"], r["reason"],
                     q["n_candidates"], q["n_gate1"], q["n_gate2"], q["n_selected"],
                     q["worst_minute_before"], q["target"], r["detail"].replace("|", "\\|")])
frag("appendix-flagged",
     ["Feed", "Symbol", "Session", "Class", "Reason", "Cand", "G1", "G2", "Sel", "Worst min", "Target", "Detail"],
     app_rows)

with open(OUT, "w") as f:
    f.write("\n".join(frags))
print(f"\nwrote {OUT}; fragments: {len(frags)}; check failures: {len(failures)}")
sys.exit(1 if failures else 0)
```

- [ ] **Step 2: Run it and verify every check prints OK**

Run: `python3 $SCRATCH/build_report_tables.py $SCRATCH/fragments.md`
Expected: every line starts with `OK`, final line `... check failures: 0`, exit code 0. If any line prints `FAIL`, stop and investigate the discrepancy before proceeding — do not adjust expected values to match.

- [ ] **Step 3: Eyeball the fragments**

Run: `grep -c 'FRAGMENT:' $SCRATCH/fragments.md`
Expected: `9`. Open `$SCRATCH/fragments.md` and confirm `appendix-flagged` has 393 data rows (`grep -c '^| ' $SCRATCH/fragments.md` is ~490 total table rows across fragments; precise appendix row count: 393 + 2 header lines).

No commit for this task (script and fragments are scratchpad-only).

### Task 2: Report body (sections 1–6)

**Files:**

- Create: `docs/min_pub_report_2026-07-15.md`

**Interfaces:**

- Consumes: `$SCRATCH/fragments.md` fragments `audit-by-asset`, `audit-by-session`, `worst-offenders`, `funnel`, `spec-by-session`, `spec-by-publisher`, `unresolvable-by-reason` (paste tables verbatim, without the `<!-- FRAGMENT -->` comment lines).
- Produces: report sections 1–6; Task 3 appends sections 7–8 to the same file.

- [ ] **Step 1: Write sections 1–6**

Use this skeleton verbatim, inserting the named fragment tables where marked:

```markdown
# min_pub Situation Report — 2026-07-15

Status report on minimum-publisher health for the STABLE feeds in
`lazer_new.json`, based on the min_pub audit & remediation pipeline run of
2026-07-13/14 (`lazer_dq/audit_min_pub.py` → `lazer_dq/qualify_candidates.py`).

## 1. Executive summary

- **1,645 STABLE feeds (2,505 feed-sessions) audited** over 2026-07-06 → 2026-07-13:
  **1,888 OK, 369 WARN, 248 CRITICAL** feed-sessions.
- **95 CRITICAL feed-sessions hit a minute with zero active publishers**; 121
  feed-sessions spent time below their effective minPublishers.
- Qualification examined all 617 non-OK feed-sessions: **245 can meet their
  publisher target** — 203 via new publisher additions, 42 already at target
  on their worst minute (flagged for margin/persistence, not shortfall).
- A remediation spec with **256 publisher additions (31 publishers, 191
  feeds)** was generated on Jul 14 but has **NOT been applied** — the
  additions are absent from `lazer_new.json`.
- **393 feed-sessions (370 feeds) remain flagged with no automatic fix**,
  mostly because every discovered candidate fails the activity or quality
  gates. These need publisher outreach, minPublishers review, or
  deactivation decisions.
- Caveat: the pipeline ran against `lazer_to_modify.json`; `lazer_new.json`
  (pulled 2026-07-15) has since drifted on 75 feeds, 16 of them flagged —
  see §7.

## 2. Methodology & data provenance

| Stage              | Tool                                              | Ran    | Config                 | Output                                                                                        |
| ------------------ | ------------------------------------------------- | ------ | ---------------------- | --------------------------------------------------------------------------------------------- |
| 1. Audit           | `lazer_dq/audit_min_pub.py`                       | Jul 13 | `lazer_to_modify.json` | `min_pub_audit_2026-07-06_2026-07-13.csv` (2,505 rows)                                        |
| 2. Qualification   | `lazer_dq/qualify_candidates.py`                  | Jul 14 | `lazer_to_modify.json` | `qualification_summary.csv` (617), `candidates_report.csv` (6,607), `flagged_feeds.csv` (393) |
| 3. Spec generation | `lazer_dq/apply_min_pub_remediation.py` (dry-run) | Jul 14 | `lazer_to_modify.json` | `min_pub_remediation_spec.yaml` (55 ops) — pending                                            |

The audit counts only `status='ACCEPTED'` updates from currently-allowed
publishers, per minute, session-aware. Qualification discovers candidates
from `REJECTED`/`UNAUTHORIZED` submissions (production keys only); gate 1 is
activity (≥ 90% of open minutes), gate 2 is quality — Datascope benchmark
where available, otherwise peer comparison against the feed's own
`price_feeds` aggregate.

Known caveats:

- **Peer-gate circularity**: non-Datascope feeds are qualified against their
  own aggregate — accepted by design, but it cannot detect a candidate that
  is wrong in the same way the aggregate is.
- **Flat-reference feeds** (zero price variance, e.g. NAV) can never pass
  the peer quality gate (`zero_range`) and are always flag-listed.
- **Window matching**: Stage 2 and Stage 3 must use identical
  `--start`/`--end` dates; a partial-overlap window produces spurious
  projected-margin failures.
- The audit classifies on time spent at/near minPublishers, not only on
  outright shortfall — a feed can be WARN/CRITICAL while its worst minute
  still meets the target (42 such feed-sessions; 21 of them remain flagged
  because their candidates also fail the gates).

## 3. Audit results (Stage 1)

Classification by asset type (feed-sessions, sorted by non-OK count):

[PASTE FRAGMENT audit-by-asset]

Equities dominate the non-OK population (380 of 617 feed-sessions), driven
by extended sessions with thin publisher coverage. By session:

[PASTE FRAGMENT audit-by-session]

Severity highlights:

- 95 CRITICAL feed-sessions recorded at least one minute with **zero active
  publishers**.
- 121 feed-sessions spent minutes **below** effective minPublishers.
- 390 of the 617 non-OK feed-sessions are **prolonged** (long consecutive
  runs at or below minPublishers + 1), i.e. structural coverage gaps rather
  than transient dips.

Worst offenders by minutes below minimum:

[PASTE FRAGMENT worst-offenders]

## 4. Qualification outcomes (Stage 2)

Candidate funnel across all 617 flagged feed-sessions:

[PASTE FRAGMENT funnel]

Outcome per feed-session: 245 met target (203 via additions, 42 already at
target), 372 unmet (16 of which received partial additions that narrow but
do not close the gap).

Selected additions by session:

[PASTE FRAGMENT spec-by-session]

## 5. Remediation plan status — PENDING

`output_csv/min_pub_remediation_spec.yaml` (generated Jul 14) contains 55
operations adding 256 (publisher, feed, session) entries across 191 feeds
and 31 publishers. **It has not been applied**: spot-checks confirm the
additions are absent from both `lazer_to_modify.json` and `lazer_new.json`.

Additions per publisher:

[PASTE FRAGMENT spec-by-publisher]

To apply (dry-run first, then with `--apply`):

    python3 -m lazer_dq.apply_min_pub_remediation \
      --config lazer_new.json \
      --start-date 2026-07-06 --end-date 2026-07-13

Note: Stage 3 must reuse the Stage 2 window (2026-07-06 → 2026-07-13)
exactly, and the spec was computed against `lazer_to_modify.json` — re-verify
against `lazer_new.json` given the drift in §7 (16 flagged feeds changed).

## 6. Unresolvable feeds — 393 feed-sessions (370 feeds)

[PASTE FRAGMENT unresolvable-by-reason]

Recommended disposition per bucket:

- **candidates_fail_quality (210)** — candidates are active but publish
  prices failing the benchmark/peer gate. Publisher outreach with per-feed
  quality evidence (`candidates_report.csv` has per-candidate metrics).
- **no_candidates (77)** — nobody else is even attempting to publish.
  Requires recruiting publishers, lowering minPublishers, or accepting the
  risk; feeds here with a zero-publisher worst minute are the deactivation
  discussion list.
- **no_benchmark_data (63)** — quality gate could not run (no Datascope RIC
  and no usable aggregate; includes the flat-NAV `zero_range` class).
  Needs an alternative quality metric (max-abs-pct-diff was floated) before
  these can ever auto-qualify.
- **candidates_fail_activity (27)** — candidates exist but publish < 90% of
  open minutes. Outreach: ask for sustained coverage, then re-run.
- **still_below_target (16)** — additions were found but not enough.
  Combine with outreach from the first two buckets.
```

- [ ] **Step 2: Verify body numbers against fragments**

Every count in the pasted prose must match the fragment tables (e.g. asset-type totals sum to 2,505; unresolvable reasons sum to 393). Run: `grep -c '^| ' docs/min_pub_report_2026-07-15.md` and confirm the tables landed.

- [ ] **Step 3: Commit**

```bash
pre-commit run --files docs/min_pub_report_2026-07-15.md
git add docs/min_pub_report_2026-07-15.md
git commit -m "docs: min_pub situation report 2026-07-15 — body (sections 1-6)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

### Task 3: Appendices (sections 7–8)

**Files:**

- Modify: `docs/min_pub_report_2026-07-15.md` (append)

**Interfaces:**

- Consumes: fragments `drift-table` (75 rows) and `appendix-flagged` (393 rows).
- Produces: final report file.

- [ ] **Step 1: Append sections 7–8**

```markdown
## 7. Appendix A — config drift since the audit

`lazer_new.json` (2026-07-15) differs from `lazer_to_modify.json` (the
config the pipeline ran against) on 75 feeds: 16 state changes (11
COMING_SOON→STABLE among them) and 59 publisher/minPublishers edits. Audit
rows for these feeds — especially the 16 that are also flagged — may be
stale and should be re-audited after the remediation spec is applied.

[PASTE FRAGMENT drift-table]

## 8. Appendix B — all flagged feed-sessions with qualification outcome

CRITICAL first, then WARN; `Cand/G1/G2/Sel` = candidates discovered / passed
activity gate / passed quality gate / selected. `Worst min` is the lowest
per-minute active-publisher count observed in the audit window.

[PASTE FRAGMENT appendix-flagged]
```

- [ ] **Step 2: Verify appendix row counts**

Run: `python3 -c "
import re
t=open('docs/min_pub_report_2026-07-15.md').read()
sec7=t.split('## 7.')[1].split('## 8.')[0]
sec8=t.split('## 8.')[1]
print('drift rows:', len(re.findall(r'^\| \d', sec7, re.M)))
print('appendix rows:', len(re.findall(r'^\| \d', sec8, re.M)))
"`
Expected: `drift rows: 75`, `appendix rows: 393`.

- [ ] **Step 3: Commit**

```bash
pre-commit run --files docs/min_pub_report_2026-07-15.md
git add docs/min_pub_report_2026-07-15.md
git commit -m "docs: min_pub situation report 2026-07-15 — appendices (drift + flagged detail)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

### Task 4: Final verification & spot-checks

**Files:**

- Modify: `docs/min_pub_report_2026-07-15.md` (only if a check fails)

**Interfaces:**

- Consumes: the finished report, `lazer_new.json`, `output_csv/min_pub_remediation_spec.yaml`.
- Produces: verified report; fixes committed if needed.

- [ ] **Step 1: Spot-check three concrete claims against lazer_new.json**

```python
import json, yaml
new = {f["feedId"]: f for f in json.load(open("lazer_new.json"))["feeds"]}

# (a) spec NOT applied: first op adds publisher 2 to feeds 3050, 3095
spec = yaml.safe_load(open("output_csv/min_pub_remediation_spec.yaml"))
op = spec["operations"][0]
assert op["publisher_id"] == 2
for fid in (3050, 3095):
    ms = new[fid]["metadata"]["marketSchedules"] if "metadata" in new[fid] else new[fid]["marketSchedules"]
    regular = next(e for e in ms if e["session"] == "REGULAR")
    assert 2 not in regular["allowedPublisherIds"], f"spec WAS applied to {fid}"

# (b) drift example: feed 579 is STABLE in lazer_new
assert new[579]["state"] == "STABLE", new[579]["state"]

# (c) a flagged feed exists and is STABLE (audit only covers STABLE feeds)
assert new[209]["state"] == "STABLE", new[209]["state"]
print("all spot-checks passed")
```

Note: the marketSchedules location may be `feed["metadata"]["marketSchedules"]`
or top-level depending on format — the Task 1 script already resolved this;
mirror whichever path it used. Expected: `all spot-checks passed`.

- [ ] **Step 2: Fresh-eyes read of the full report**

Read the whole report top to bottom. Check: every section from the spec is
present (8 sections), no `[PASTE FRAGMENT ...]` markers remain, no broken
tables (prettier reflows them; verify pipes aligned after pre-commit), all
cross-references (§7 from §1 and §5) point at the right sections.

- [ ] **Step 3: Commit any fixes**

Only if Steps 1–2 found problems:

```bash
pre-commit run --files docs/min_pub_report_2026-07-15.md
git add docs/min_pub_report_2026-07-15.md
git commit -m "docs: min_pub report fixes from final verification

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
