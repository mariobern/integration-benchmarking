# Feed Provisioning Guide — Design Document

**Date:** 2026-03-06
**Status:** Approved

## Goal

Create a visual and written guide that explains the end-to-end feed provisioning workflow — from bringing a new price feed symbol into the system through to promoting it to STABLE in production. The guide serves engineers building automation tools for the integration team.

## Audience

Engineers who:

- Are building automation on top of the benchmarking toolset
- Have ClickHouse access
- Need to understand the full feed provisioning lifecycle
- Need to know the contracts between tools (what feeds into what)

## Deliverables

### 1. Visual HTML Diagram (`docs/feed-provisioning-pipeline.html`)

A phased journey map with:

- 5 phase columns (left-to-right), each with a distinct color
- Tool boxes within each phase showing script name + one-line purpose
- Arrows showing data flow between tools (labeled with file type: CSV, JSON)
- Decision diamonds at branch points:
  - "Symbol in Datascope?" (Phase 1 skip)
  - "US Equities?" (Phase 3 volume profile)
  - "Feed READY?" (Phase 3 → Phase 5 or Phase 4)
- Phase 4 shown as a side branch looping back to Phase 3
- Legend with pass/fail criteria and session thresholds

### 2. Markdown Guide (`docs/feed-provisioning-guide.md`)

Sections:

1. **Overview** — what this guide covers, who it's for, 5 phases at a glance
2. **Prerequisites** — ClickHouse access, config.yaml, venv setup, lazer_symbols.json
3. **Phase 1: Onboarding** — getting symbols into Datascope
4. **Phase 2: Preparation** — building the test input CSV
5. **Phase 3: Evaluation** — volume profile + feed readiness
6. **Phase 4: Investigation** — diagnosing failures (conditional)
7. **Phase 5: Promotion** — config update + state promotion
8. **Asset Class Reference** — benchmarkable vs non-benchmarkable, links to docs/asset-classes.md
9. **Quick Reference** — full happy-path command sequence

Each phase section follows: Purpose → Tools → Example Commands → What Happens Next.

## The Five Phases

### Phase 1: Onboarding

**Purpose:** Get symbols into Datascope so benchmark data exists.

**Tools:**

- `generate_source_upload.py` — Datascope instrument onboarding CSV (US equities only)
- `isin_resolver_v2.py` — ISIN resolution for onboarding validation
- `generate_ric_mapping.py` — RIC mapping for all asset classes

**Asset class distinction:**

- **US equities:** Require `generate_source_upload.py` to create onboarding CSV → submit to Datascope team
- **FX, metals, commodities, treasuries:** Instruments are generally already in Datascope's universe; `generate_ric_mapping.py` confirms the identifier

**Skip condition:** If symbol already has benchmark data in Datascope, skip to Phase 2.

### Phase 2: Preparation

**Purpose:** Build the standard test input CSV from feed IDs.

**Tools:**

- `generate_price_list.py` — feed IDs + dates → `feed_id,date,mode` CSV

**Details:**

- Auto-detects asset class from `lazer_symbols.json`
- Skips non-benchmarkable feeds (crypto, nav, etc.)
- Supports single date or date ranges

**Output:** `price_id_list.csv` — universal input for all evaluation tools.

### Phase 3: Evaluation

**Purpose:** Assess feed quality, uptime, and session viability.

**Flow:**

1. **`volume_profile.py`** (always run first for US equities) — determines session viability
2. Use volume profile's session recommendation to decide `--extended-hours` / `--overnight` flags
3. **`feed_readiness.py --csv price_id_list.csv`** — combined benchmark + uptime evaluation
4. **`feed_readiness.py --summary`** — generates READY-only summary CSV for Phase 5

**Branch:**

- Feed READY → Phase 5
- Feed FAILS → Phase 4

### Phase 4: Investigation (conditional)

**Purpose:** Diagnose why feeds failed readiness.

**Tools:**

- `publisher_report.py` — per-feed health classification (HEALTHY/DEGRADED/FAILING). Quick triage.
- `publisher_benchmark.py` — deep per-publisher metrics. Identifies quality vs coverage issues.
- `quick_benchmark.py --detailed` — feed-level with per-publisher rows for comparison.
- `verify_uptime.py` — uptime gap analysis for uptime-related failures.

**Outcome:** Fix underlying issue → re-evaluate (loop back to Phase 3).

### Phase 5: Promotion

**Purpose:** Update config and go live.

**Flow (two distinct steps):**

1. **`update_config_from_summary.py`** — sets `allowedPublisherIds` per session in `after.json`
   - Always `--dry-run` first
   - Creates `.bak` backup
2. **`update_lazer_symbols.py`** — flips feed state from `COMING_SOON → STABLE`
   - Always `--dry-run` first
   - Creates `.bak` backup

## Key Design Decisions

- **Conceptual data flow:** Show file types (CSV, JSON) at handoff points, not column schemas. Engineers reference individual script docs for column details.
- **Phased structure:** Maps to how operators think about the work and provides natural demo flow.
- **Full branching:** Includes onboarding skip, investigation loop, and session decision — engineers need all paths for automation.
- **volume_profile.py is mandatory** before deciding session flags, not optional.

## Pass/Fail Criteria Reference

| Session                          | nrmse_auto_pass | nrmse_conditional | hit_rate_threshold |
| -------------------------------- | --------------- | ----------------- | ------------------ |
| Regular (fx, equities, rates)    | 0.01            | 0.05              | 95%                |
| Relaxed (commodity, metals)      | 0.05            | 0.15              | 85%                |
| Extended (pre/after/overnight)   | 0.05            | 0.15              | 85%                |

Feed is READY when: `fully_passing_count >= target_pub_count` (default: 4).
