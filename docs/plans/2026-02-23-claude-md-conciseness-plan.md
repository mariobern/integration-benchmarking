# CLAUDE.md Conciseness Restructure Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce CLAUDE.md from 1,011 lines to ~200 lines by keeping cross-cutting knowledge and replacing per-script detail with an index table linking to existing docs/.

**Architecture:** Single-file rewrite. No new code. All removed content already exists in `docs/*.md` files. One verification step to confirm no docs/ links are broken.

**Tech Stack:** Markdown only.

---

### Task 1: Verify docs/ coverage before removing content

**Files:**

- Read: `docs/quick_benchmark.md`, `docs/feed_readiness.md`, `docs/publisher_benchmark.md`, `docs/generate_source_upload.md`, `docs/trading_halt_history.md`, `docs/portal_usage.md`, `docs/isin_resolver_v2.md`, `docs/publisher_report.md`, `docs/update_lazer_symbols.md`

**Step 1: Confirm each docs/ file exists and covers the content being removed**

Check that argument tables, usage examples, and output formats are present in the corresponding docs/ file. If any docs/ file is missing critical content that only exists in CLAUDE.md today, note it for Task 2.

**Step 2: Check if `generate_ric_mapping.py` has a docs/ file**

It may not have one. If missing, create `docs/generate_ric_mapping.md` by extracting the relevant CLAUDE.md sections (RIC resolution rules, confidence levels, edge cases, programmatic usage).

---

### Task 2: Backfill any missing docs/ content

**Files:**

- Create (if needed): `docs/generate_ric_mapping.md`
- Modify (if needed): any docs/ file missing content from CLAUDE.md

**Step 1: Create or update docs/ files**

Only needed if Task 1 found gaps. Move content from CLAUDE.md into the appropriate docs/ file.

**Step 2: Commit**

```bash
git add docs/
git commit -m "docs: backfill docs/ files before CLAUDE.md restructure"
```

---

### Task 3: Rewrite CLAUDE.md

**Files:**

- Modify: `CLAUDE.md`

**Step 1: Write the new CLAUDE.md with these sections (in order):**

1. **Header + Overview** (~3 lines) — keep existing overview paragraph
2. **Setup** (~4 lines) — keep existing pip install + config.yaml
3. **Pass/Fail Criteria** (~3 lines) — keep existing
4. **Database Configuration** (~6 lines) — keep existing including EOF tip
5. **Input CSV Format** (~6 lines) — keep format example
6. **Asset Classes** (~15 lines) — compact list with benchmarkable/non-benchmarkable indicators and aliases
7. **Futures Naming Convention** (~8 lines) — month codes, year digits, symbol pattern (no enumerated futures list)
8. **Trading Sessions** (~12 lines) — single consolidated table:

| Session     | Time (ET)         | Benchmark Source | Flag               | Asset Classes |
| ----------- | ----------------- | ---------------- | ------------------ | ------------- |
| Regular     | 9:30 AM - 4:00 PM | Datascope        | (always)           | US Equities   |
| Pre-market  | 4:00 AM - 9:30 AM | Datascope        | `--extended-hours` | US Equities   |
| After-hours | 4:00 PM - 8:00 PM | Datascope        | `--extended-hours` | US Equities   |
| Overnight   | 8:00 PM - 4:00 AM | Publisher 32     | `--overnight`      | US Equities   |
| Regular     | 24h (with maint.) | Datascope        | (always)           | FX, Metals    |

9. **Scripts** (~50 lines) — index table:

| Script                                                                     | Purpose | Quick Example | Docs |
| -------------------------------------------------------------------------- | ------- | ------------- | ---- |
| One row per script with 1-line purpose, one example command, link to docs/ |

Include all 12 scripts/tools: quick_benchmark, feed_readiness, publisher_benchmark, publisher_report, generate_source_upload, generate_ric_mapping, isin_resolver, update_lazer_symbols, trading_halt_history, verify_uptime, portal (test_api + uvicorn), daily batch runner.

10. **Key Gotchas** (~8 lines) — consolidated:
    - Dotted tickers (BRK.B) use `BRKb.N` RIC format
    - NASDAQ Trader caching in `.nasdaq_cache/` with 24h TTL
    - Publisher 32 is peer comparison, not official benchmark
    - `python` not found — use `python3` or activate venv
    - Publisher 71 may fail (infinite t_statistic)

**Step 2: Verify line count**

```bash
wc -l CLAUDE.md
```

Target: <= 200 lines.

**Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: restructure CLAUDE.md from 1011 to ~200 lines

Replace per-script documentation with index table linking to docs/.
Keep cross-cutting knowledge: asset classes, trading sessions, pass/fail
criteria, DB config, futures naming, and key gotchas."
```

---

### Task 4: Verify no broken links

**Step 1: Check all docs/ links in CLAUDE.md resolve**

```bash
grep -oP '\(docs/[^)]+\)' CLAUDE.md | tr -d '()' | while read f; do [ -f "$f" ] || echo "BROKEN: $f"; done
```

**Step 2: Fix any broken links**

If any links are broken, either fix the path or create the missing doc.
