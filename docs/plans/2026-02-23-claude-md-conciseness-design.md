# Design: CLAUDE.md Conciseness Restructure

**Date:** 2026-02-23
**Goal:** Reduce CLAUDE.md from 1,011 lines to ~200 lines
**Audience:** Claude Code only (humans use docs/ files)
**Approach:** "Index + Essentials" — keep cross-cutting knowledge, replace per-script sections with an index table linking to existing docs/

## Problem

CLAUDE.md duplicates content that already exists in `docs/` files. Every script has detailed argument tables, usage examples, output formats, and edge cases documented in both places. This wastes context window and makes maintenance harder (two places to update).

## Design

### What stays in CLAUDE.md (cross-cutting knowledge)

1. **Overview** (~3 lines) — what the repo does
2. **Setup** (~4 lines) — pip install + config.yaml
3. **Pass/fail criteria** (~3 lines) — rmse_over_spread threshold, readiness formula
4. **Database configuration** (~6 lines) — two ClickHouse clusters, EOF troubleshooting tip
5. **Input CSV format** (~6 lines) — format example + "no header required"
6. **Asset classes** (~15 lines) — benchmarkable vs non-benchmarkable, with aliases
7. **Futures naming convention** (~8 lines) — month codes, year digits, symbol pattern
8. **Trading sessions** (~12 lines) — single consolidated table (regular, premarket, afterhours, overnight) with times, benchmark sources, and CLI flags
9. **Script index** (~50 lines) — table mapping each script to purpose, one example command, and docs/ link
10. **Key gotchas** (~8 lines) — dotted tickers, NASDAQ Trader caching, publisher 32 caveats

### What moves to docs/ (per-script detail)

All of the following are already documented in `docs/*.md` files:

- Argument tables for every script
- Extended usage examples (multi-feed, date ranges, CSV mode, single-feed mode)
- Output CSV column descriptions
- Statistical metrics tables and interpretation guides
- Performance optimization flags and when-to-use guidance
- Extended hours / overnight output columns
- Programmatic usage examples
- Portal API endpoints, dashboard features, uptime methodology
- ISIN resolver tiers, coverage stats, caching details
- Trading halt "how it works", LUDP reason codes, typical results
- Feed readiness logic (per-publisher, per-feed, per-session)

### Script index table structure

| Script | Purpose | Quick Example | Docs |
|--------|---------|---------------|------|
| `quick_benchmark.py` | Evaluate feed quality vs Datascope | `python quick_benchmark.py --csv feeds.csv` | [docs/quick_benchmark.md] |
| `feed_readiness.py` | Combined benchmark + uptime readiness | `python feed_readiness.py --csv feeds.csv` | [docs/feed_readiness.md] |
| `publisher_benchmark.py` | Per-publisher benchmark with stats | `python publisher_benchmark.py --csv feeds.csv` | [docs/publisher_benchmark.md] |
| `publisher_report.py` | Per-feed health classification | `python publisher_report.py --csv feeds.csv` | [docs/publisher_report.md] |
| `generate_source_upload.py` | Datascope onboarding CSV (US equities) | `python generate_source_upload.py --tickers AAPL,NVDA` | [docs/generate_source_upload.md] |
| `generate_ric_mapping.py` | Universal RIC mapping (all asset classes) | `python generate_ric_mapping.py --ticker AAPL EURUSD` | (inline, has tests) |
| `isin_resolver.py` | Ticker to ISIN resolution | `python isin_resolver.py --tickers AAPL,MSFT` | [docs/isin_resolver_v2.md] |
| `update_lazer_symbols.py` | Promote feeds to STABLE in after.json | `python3 update_lazer_symbols.py --summary X --config after.json --dry-run` | [docs/update_lazer_symbols.md] |
| `trading_halt_history.py` | Download NASDAQ LUDP halt data | `python trading_halt_history.py` | [docs/trading_halt_history.md] |
| `verify_uptime.py` | Compare uptime calculation methods | `python verify_uptime.py --publisher-id 55 --date 2026-01-28` | (inline) |
| Portal (`portal/`) | Self-service publisher API + dashboard | `python portal/test_api.py` | [docs/portal_usage.md] |
| Daily batch | Production batch runner | `python -m portal.batch.daily_benchmark_runner --date 2026-01-30` | [docs/portal_usage.md] |

### Consolidated trading sessions table

| Session | Time (ET) | Benchmark Source | Flag | Asset Classes |
|---------|-----------|------------------|------|---------------|
| Regular | 9:30 AM - 4:00 PM | Datascope | (always) | US Equities |
| Pre-market | 4:00 AM - 9:30 AM | Datascope | `--extended-hours` | US Equities |
| After-hours | 4:00 PM - 8:00 PM | Datascope | `--extended-hours` | US Equities |
| Overnight | 8:00 PM - 4:00 AM | Publisher 32 | `--overnight` | US Equities |
| Regular | 24h (with maint.) | Datascope | (always) | FX, Metals |

## Validation

- Every `docs/` link in the index table must resolve to an existing file
- The new CLAUDE.md must be <= 200 lines
- `generate_ric_mapping.py` docs link needs verification (may need a docs/ file created)
- No information loss: every removed section must be findable in the corresponding docs/ file

## Risk

**Low.** Claude Code can always read `docs/` files on demand. The index table tells it where to look. The only risk is Claude not knowing to check docs/ for a specific detail — mitigated by the explicit table.
