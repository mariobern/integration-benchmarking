# Feed Provisioning Guide Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a visual HTML pipeline diagram and a markdown guide documenting the end-to-end feed provisioning workflow (5 phases: Onboarding → Preparation → Evaluation → Investigation → Promotion).

**Architecture:** Two standalone deliverables: (1) a self-contained HTML page with CSS/SVG showing the phased journey map, (2) a markdown guide with phase-by-phase walkthrough. The HTML is for demo/presentation; the markdown is the reference doc for automation engineers.

**Tech Stack:** HTML/CSS/inline SVG for the diagram; Markdown for the guide. No JavaScript frameworks needed.

---

### Task 1: Create the HTML Visual Pipeline Diagram

**Files:**

- Create: `docs/feed-provisioning-pipeline.html`

**Step 1: Write the HTML diagram**

Create a self-contained HTML page with the phased journey map. Requirements:

- **Layout:** 5 phase columns arranged left-to-right, scrollable on small screens
- **Phase colors:** Each phase gets a distinct color palette:
  - Phase 1 (Onboarding): Blue tones
  - Phase 2 (Preparation): Teal/cyan tones
  - Phase 3 (Evaluation): Green tones
  - Phase 4 (Investigation): Amber/orange tones
  - Phase 5 (Promotion): Purple tones
- **Tool boxes:** Rounded rectangles within each phase showing:
  - Script name (bold, monospace)
  - One-line purpose (smaller text)
- **Decision diamonds** at branch points:
  - Between Phase 1 and Phase 2: "Symbol in Datascope?" → Yes skips to Phase 2, No enters Phase 1
  - Within Phase 3: "US Equities?" → Yes requires volume_profile.py
  - After Phase 3: "Feed READY?" → Yes goes to Phase 5, No goes to Phase 4
- **Arrows:** Connecting tools/phases with labeled data flow (CSV, JSON, summary CSV)
- **Phase 4 loop:** Arrow from Phase 4 back to Phase 3 labeled "Fix & re-evaluate"
- **Legend section** at the bottom with:
  - Pass/fail criteria table (3 threshold tiers)
  - Feed readiness formula: `fully_passing_count >= target_pub_count (default: 4)`
  - Asset class note: benchmarkable vs non-benchmarkable

**Phase 1 tools (Onboarding):**

| Tool                        | Purpose                                     |
| --------------------------- | ------------------------------------------- |
| `generate_source_upload.py` | Datascope onboarding CSV (US equities only) |
| `isin_resolver_v2.py`       | ISIN resolution for validation              |
| `generate_ric_mapping.py`   | RIC mapping (all asset classes)             |

Note in diagram: "US equities require `generate_source_upload.py`. FX, metals, commodities, treasuries are typically already in Datascope — use `generate_ric_mapping.py` to confirm."

**Phase 2 tools (Preparation):**

| Tool                     | Purpose                            |
| ------------------------ | ---------------------------------- |
| `generate_price_list.py` | Build test input CSV from feed IDs |

Arrow from Phase 2 output labeled "price_id_list.csv"

**Phase 3 tools (Evaluation):**

| Tool                | Purpose                                        |
| ------------------- | ---------------------------------------------- |
| `volume_profile.py` | Session viability (always run for US equities) |
| `feed_readiness.py` | Combined benchmark + uptime check              |

Show volume_profile.py feeding a "session recommendation" into feed_readiness.py flags.
Arrow from feed_readiness.py `--summary` output labeled "summary CSV"

**Phase 4 tools (Investigation):**

| Tool                            | Purpose                                          |
| ------------------------------- | ------------------------------------------------ |
| `publisher_report.py`           | Health classification (HEALTHY/DEGRADED/FAILING) |
| `publisher_benchmark.py`        | Deep per-publisher metrics                       |
| `quick_benchmark.py --detailed` | Feed-level with per-publisher comparison         |
| `verify_uptime.py`              | Uptime gap analysis                              |

Show as a side branch below or to the right of Phase 3, with a loop-back arrow to Phase 3.

**Phase 5 tools (Promotion):**

| Tool                            | Purpose                                |
| ------------------------------- | -------------------------------------- |
| `update_config_from_summary.py` | Set publisher allowlists in after.json |
| `update_lazer_symbols.py`       | Flip COMING_SOON → STABLE              |

Show these as sequential (step 1 then step 2), both with a "dry-run first" annotation.

**Style guidelines:**

- Clean, professional design suitable for screen-sharing in a demo
- Use a sans-serif font (system fonts)
- Subtle shadows and borders, not flat boxes
- Phase headers prominent with phase number
- Responsive: works on 1920px screens, scrollable on smaller
- Title at top: "Feed Provisioning Pipeline"
- Subtitle: "End-to-end workflow: from new symbol to production-ready feed"

**Step 2: Verify the HTML renders correctly**

Run: Open `docs/feed-provisioning-pipeline.html` in a browser and verify:

- All 5 phases visible
- Decision diamonds readable
- Arrows connect correctly
- Legend present and accurate
- No layout issues

**Step 3: Commit**

```bash
pre-commit run --files docs/feed-provisioning-pipeline.html
git add docs/feed-provisioning-pipeline.html
git commit -m "docs: add feed provisioning pipeline HTML diagram"
```

---

### Task 2: Create the Markdown Guide

**Files:**

- Create: `docs/feed-provisioning-guide.md`

**Step 1: Write the markdown guide**

Structure with these exact sections:

#### Section 1: Overview

```markdown
# Feed Provisioning Guide

End-to-end guide for bringing a price feed from initial symbol to production-ready
(`COMING_SOON` → `STABLE`). For engineers building automation on the benchmarking toolset.

See the [visual pipeline overview](feed-provisioning-pipeline.html) for a diagram of this workflow.

## The Five Phases

| Phase | Name          | Purpose                                                |
| ----- | ------------- | ------------------------------------------------------ |
| 1     | Onboarding    | Get symbols into Datascope for benchmark data          |
| 2     | Preparation   | Build the test input CSV from feed IDs                 |
| 3     | Evaluation    | Assess feed quality, uptime, and session viability     |
| 4     | Investigation | Diagnose failures (conditional — only when feeds fail) |
| 5     | Promotion     | Update config and go live                              |
```

#### Section 2: Prerequisites

```markdown
## Prerequisites

- **Python environment:** `source venv/bin/activate` (or use `python3`)
- **ClickHouse access:** Configure `config.yaml` with credentials for `lazer_clickhouse_prod` and `analytics_clickhouse`
- **lazer_symbols.json:** Current feed metadata (used by generate_price_list.py and generate_ric_mapping.py)
- **after.json:** Production config file (used in Phase 5 for promotion)
```

#### Section 3: Phase 1 — Onboarding

Cover:

- Purpose: get symbols into Datascope so benchmark data can be collected
- The asset class distinction:
  - **US equities:** Run `generate_source_upload.py` to create Datascope onboarding CSV → submit to Datascope team to start benchmark collection
  - **FX, metals, commodities, treasuries:** These instruments are generally already in Datascope's universe. Use `generate_ric_mapping.py` to confirm the RIC identifier is correct.
- Skip condition: if the symbol already has benchmark data in Datascope, skip to Phase 2
- Example commands:

  ```bash
  # US equities: generate Datascope onboarding CSV
  python3 generate_source_upload.py --tickers AAPL,MSFT,NVDA

  # Resolve ISINs for validation
  python3 isin_resolver_v2.py --tickers AAPL,MSFT,NVDA --output isins.csv

  # Generate RIC mappings (all asset classes)
  python3 generate_ric_mapping.py --ticker AAPL EURUSD XAUUSD CCH6 US10Y
  ```

- Link to: [generate_source_upload.md](generate_source_upload.md), [generate_ric_mapping.md](generate_ric_mapping.md), [isin_resolver_v2.md](isin_resolver_v2.md)

#### Section 4: Phase 2 — Preparation

Cover:

- Purpose: build the standard `feed_id,date,mode` CSV from feed IDs
- `generate_price_list.py` auto-detects asset class from `lazer_symbols.json`
- Non-benchmarkable feeds (crypto, nav, etc.) are automatically skipped
- Supports single date or date ranges
- Example commands:

  ```bash
  # Single date, specific feed IDs
  python3 generate_price_list.py --feed-id 327 340 922 --date 2026-03-05

  # Date range
  python3 generate_price_list.py --feed-id 327 340 --start-date 2026-03-03 --end-date 2026-03-05

  # From a file of feed IDs
  python3 generate_price_list.py --feed-ids-file my_feed_ids.txt --date 2026-03-05
  ```

- Output: `price_id_list.csv` — the universal input for all evaluation tools
- What happens next: proceed to Phase 3

#### Section 5: Phase 3 — Evaluation

Cover:

- Purpose: assess feed quality, uptime, and determine which trading sessions are viable
- **Step 1: Volume Profile (mandatory for US equities)**
  - Always run `volume_profile.py` before deciding session flags
  - The `session_recommendation` column tells you whether the ticker supports regular-only or 24/5
  - Example:
    ```bash
    python3 volume_profile.py --tickers AAPL,MSFT,NVDA --date 2026-03-05
    ```
  - Only applies to US equities — FX, metals, commodities, treasuries use their own session rules
- **Step 2: Feed Readiness**

  - Use `feed_readiness.py` with the CSV from Phase 2
  - Choose session flags based on volume_profile output:

    ```bash
    # Regular session only
    python3 feed_readiness.py --csv price_id_list.csv --workers 8

    # With extended hours (if volume_profile shows sufficient liquidity)
    python3 feed_readiness.py --csv price_id_list.csv --extended-hours --overnight --workers 8

    # Generate READY-only summary for Phase 5
    python3 feed_readiness.py --csv price_id_list.csv --extended-hours --overnight --summary --workers 8
    ```

- **Interpreting results:**
  - Feed READY → proceed to Phase 5
  - Feed FAILS → enter Phase 4 to investigate why
- Link to: [feed_readiness.md](feed_readiness.md), [volume_profile.md](volume_profile.md), [benchmark_results_guide.md](benchmark_results_guide.md)

#### Section 6: Phase 4 — Investigation (conditional)

Cover:

- Purpose: diagnose why feeds failed readiness — entered only when Phase 3 reports failures
- **Triage tools (use in this order):**
  1. `publisher_report.py` — quick health classification across all publishers for a feed (HEALTHY/DEGRADED/FAILING)
  2. `publisher_benchmark.py` — deep dive into specific publisher metrics (NRMSE, hit rate, statistical tests)
  3. `quick_benchmark.py --detailed` — feed-level benchmark with per-publisher rows for side-by-side comparison
  4. `verify_uptime.py` — if failure is uptime-related, analyzes gap patterns
- Example commands:

  ```bash
  # Quick triage: which publishers are healthy vs failing?
  python3 publisher_report.py --csv price_id_list.csv

  # Deep dive into a specific publisher
  python3 publisher_benchmark.py --csv price_id_list.csv --publisher-id 55

  # Feed-level with per-publisher detail
  python3 quick_benchmark.py --csv price_id_list.csv --detailed

  # Uptime gap analysis for a specific publisher
  python3 verify_uptime.py --publisher-id 55 --date 2026-03-05
  ```

- Outcome: fix the underlying issue (publisher-side) and loop back to Phase 3 to re-evaluate
- Link to: [publisher_benchmark.md](publisher_benchmark.md)

#### Section 7: Phase 5 — Promotion

Cover:

- Purpose: update config and promote feed to production
- **Two distinct steps (always in this order):**
  1. `update_config_from_summary.py` — sets `allowedPublisherIds` per session in `after.json`
  2. `update_lazer_symbols.py` — flips feed state from `COMING_SOON` → `STABLE`
- Both tools support `--dry-run` and create `.bak` backups
- Example commands:

  ```bash
  # Step 1: Update publisher allowlists (dry-run first)
  python3 update_config_from_summary.py --summary feed_readiness_summary.csv --config after.json --dry-run
  python3 update_config_from_summary.py --summary feed_readiness_summary.csv --config after.json

  # Step 2: Promote COMING_SOON → STABLE (dry-run first)
  python3 update_lazer_symbols.py --summary readiness_summary.md --config after.json --dry-run
  python3 update_lazer_symbols.py --summary readiness_summary.md --config after.json
  ```

- Link to: [update_config_from_summary.md](update_config_from_summary.md), [update_lazer_symbols.md](update_lazer_symbols.md)

#### Section 8: Asset Class Reference

```markdown
## Asset Class Reference

### Benchmarkable (have Datascope data)

| Asset Class     | Aliases               | Notes                            |
| --------------- | --------------------- | -------------------------------- |
| `fx`            | -                     | Foreign exchange, 24h session    |
| `metals`        | `metal`               | Precious metals, 24h session     |
| `us-equities`   | `equity-us`           | Includes equity index futures    |
| `commodity`     | -                     | Includes commodity futures       |
| `us-treasuries` | `treasuries`, `rates` | US Treasury bonds (yield values) |

### Not Benchmarkable

`crypto`, `crypto-redemption-rate`, `funding-rate`, `nav` — these asset classes have no Datascope benchmark data and will error if passed to evaluation tools.

See [asset-classes.md](asset-classes.md) for the full reference.
```

#### Section 9: Quick Reference

```markdown
## Quick Reference — Happy Path

Full command sequence for the common case (US equity, new symbol, regular + extended sessions):

### 1. Onboard

python3 generate_source_upload.py --tickers AAPL,MSFT
python3 generate_ric_mapping.py --ticker AAPL MSFT

### 2. Prepare

python3 generate_price_list.py --feed-id 922 1163 --date 2026-03-05

### 3. Evaluate

python3 volume_profile.py --tickers AAPL,MSFT --date 2026-03-05
python3 feed_readiness.py --csv price_id_list.csv --extended-hours --overnight --summary --workers 8

### 4. Promote

python3 update_config_from_summary.py --summary feed_readiness_summary.csv --config after.json --dry-run
python3 update_config_from_summary.py --summary feed_readiness_summary.csv --config after.json
python3 update_lazer_symbols.py --summary readiness_summary.md --config after.json --dry-run
python3 update_lazer_symbols.py --summary readiness_summary.md --config after.json
```

**Step 2: Verify the markdown renders correctly**

Check all internal links point to existing docs. Run:

```bash
ls docs/generate_source_upload.md docs/generate_ric_mapping.md docs/isin_resolver_v2.md docs/feed_readiness.md docs/volume_profile.md docs/benchmark_results_guide.md docs/publisher_benchmark.md docs/update_config_from_summary.md docs/update_lazer_symbols.md docs/asset-classes.md
```

All should exist.

**Step 3: Commit**

```bash
pre-commit run --files docs/feed-provisioning-guide.md
git add docs/feed-provisioning-guide.md
git commit -m "docs: add feed provisioning guide (markdown walkthrough)"
```

---

### Task 3: Final Commit (both deliverables together)

If not already committed individually:

```bash
pre-commit run --files docs/feed-provisioning-pipeline.html docs/feed-provisioning-guide.md
git add docs/feed-provisioning-pipeline.html docs/feed-provisioning-guide.md
git commit -m "docs: add feed provisioning pipeline diagram and guide

Visual HTML diagram + markdown walkthrough covering the 5-phase
feed provisioning workflow (Onboarding → Preparation → Evaluation →
Investigation → Promotion) for automation engineers."
```
