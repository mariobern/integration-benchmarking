# Feed Provisioning Guide

End-to-end guide for bringing a price feed from initial symbol to production-ready (`COMING_SOON` → `STABLE`). For engineers building automation on the benchmarking toolset.

See the [visual pipeline overview](feed-provisioning-pipeline.html) for a diagram of this workflow.

## The Five Phases

| Phase | Name          | Purpose                                                |
| ----- | ------------- | ------------------------------------------------------ |
| 1     | Onboarding    | Get symbols into Datascope for benchmark data          |
| 2     | Preparation   | Build the test input CSV from feed IDs                 |
| 3     | Evaluation    | Assess feed quality, uptime, and session viability     |
| 4     | Investigation | Diagnose failures (conditional — only when feeds fail) |
| 5     | Promotion     | Update config and go live                              |

## Prerequisites

- **Python environment:** `source venv/bin/activate` (or use `python3`)
- **ClickHouse access:** Configure `config.yaml` with credentials for `lazer_clickhouse_prod` and `analytics_clickhouse`
- **lazer_symbols.json:** Current feed metadata (used by generate_price_list.py and generate_ric_mapping.py)
- **after.json:** Production config file (used in Phase 5 for promotion)

## Phase 1 — Onboarding

**Purpose:** Get symbols into Datascope so benchmark data can be collected.

The onboarding path depends on the asset class:

- **US equities:** Run `generate_source_upload.py` to create a Datascope onboarding CSV, then submit it to the Datascope team to start benchmark data collection.
- **FX, metals, commodities, treasuries:** These instruments are generally already in Datascope's universe. Use `generate_ric_mapping.py` to confirm the RIC identifier is correct.

**Skip condition:** If the symbol already has benchmark data in Datascope, skip to Phase 2.

```bash
# US equities: generate Datascope onboarding CSV
python3 generate_source_upload.py --tickers AAPL,MSFT,NVDA

# Resolve ISINs for validation
python3 isin_resolver_v2.py --tickers AAPL,MSFT,NVDA --output isins.csv

# Generate RIC mappings (all asset classes)
python3 generate_ric_mapping.py --ticker AAPL EURUSD XAUUSD CCH6 US10Y
```

See: [generate_source_upload.md](generate_source_upload.md), [generate_ric_mapping.md](generate_ric_mapping.md), [isin_resolver_v2.md](isin_resolver_v2.md)

## Phase 2 — Preparation

**Purpose:** Build the standard `feed_id,date,mode` CSV from feed IDs.

`generate_price_list.py` auto-detects asset class from `lazer_symbols.json`. Non-benchmarkable feeds (crypto, nav, etc.) are automatically skipped. Supports single date or date ranges.

```bash
# Single date, specific feed IDs
python3 generate_price_list.py --feed-id 327 340 922 --date 2026-03-05

# Date range
python3 generate_price_list.py --feed-id 327 340 --start-date 2026-03-03 --end-date 2026-03-05

# From a file of feed IDs
python3 generate_price_list.py --feed-ids-file my_feed_ids.txt --date 2026-03-05
```

**Output:** `price_id_list.csv` — the universal input for all evaluation tools. Proceed to Phase 3.

## Phase 3 — Evaluation

**Purpose:** Assess feed quality, uptime, and determine which trading sessions are viable.

### Step 1: Volume Profile (mandatory for US equities)

Always run `volume_profile.py` before deciding session flags. The `session_recommendation` column tells you whether the ticker supports regular-only or 24/5. Only applies to US equities — FX, metals, commodities, and treasuries use their own session rules.

```bash
python3 volume_profile.py --tickers AAPL,MSFT,NVDA --date 2026-03-05
```

### Step 2: Feed Readiness

Use `feed_readiness.py` with the CSV from Phase 2. Choose session flags based on volume_profile output:

```bash
# Regular session only
python3 feed_readiness.py --csv price_id_list.csv --workers 8

# With extended hours (if volume_profile shows sufficient liquidity)
python3 feed_readiness.py --csv price_id_list.csv --extended-hours --overnight --workers 8

# Generate READY-only summary for Phase 5
python3 feed_readiness.py --csv price_id_list.csv --extended-hours --overnight --summary --workers 8
```

**Interpreting results:** Feed READY → proceed to Phase 5. Feed FAILS → proceed to Phase 4.

See: [feed_readiness.md](feed_readiness.md), [volume_profile.md](volume_profile.md), [benchmark_results_guide.md](benchmark_results_guide.md)

## Phase 4 — Investigation (conditional)

**Purpose:** Diagnose why feeds failed readiness. Entered only when Phase 3 reports failures.

### Triage tools (recommended order)

1. **`publisher_report.py`** — Quick health classification across all publishers (HEALTHY/DEGRADED/FAILING)
2. **`publisher_benchmark.py`** — Deep per-publisher metrics (NRMSE, hit rate, statistical tests)
3. **`quick_benchmark.py --detailed`** — Feed-level with per-publisher rows for side-by-side comparison
4. **`verify_uptime.py`** — Uptime gap analysis for uptime-related failures

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

**Outcome:** Fix the underlying issue (publisher-side) and loop back to Phase 3 to re-evaluate.

See: [publisher_benchmark.md](publisher_benchmark.md)

## Phase 5 — Promotion

**Purpose:** Update config and promote feed to production.

Two distinct steps, always in this order:

1. **`update_config_from_summary.py`** — Sets `allowedPublisherIds` per session in `after.json`
2. **`update_lazer_symbols.py`** — Flips feed state from `COMING_SOON` → `STABLE`

Both tools support `--dry-run` and create `.bak` backups.

```bash
# Step 1: Update publisher allowlists (dry-run first)
python3 update_config_from_summary.py --summary feed_readiness_summary.csv --config after.json --dry-run
python3 update_config_from_summary.py --summary feed_readiness_summary.csv --config after.json

# Step 2: Promote COMING_SOON → STABLE (dry-run first)
python3 update_lazer_symbols.py --summary readiness_summary.md --config after.json --dry-run
python3 update_lazer_symbols.py --summary readiness_summary.md --config after.json
```

See: [update_config_from_summary.md](update_config_from_summary.md), [update_lazer_symbols.md](update_lazer_symbols.md)

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

## Quick Reference — Happy Path

Full command sequence for the common case: US equity, new symbol, regular + extended sessions.

### 1. Onboard

```bash
python3 generate_source_upload.py --tickers AAPL,MSFT
python3 generate_ric_mapping.py --ticker AAPL MSFT
```

### 2. Prepare

```bash
python3 generate_price_list.py --feed-id 922 1163 --date 2026-03-05
```

### 3. Evaluate

```bash
python3 volume_profile.py --tickers AAPL,MSFT --date 2026-03-05
python3 feed_readiness.py --csv price_id_list.csv --extended-hours --overnight --summary --workers 8
```

### 4. Promote

```bash
python3 update_config_from_summary.py --summary feed_readiness_summary.csv --config after.json --dry-run
python3 update_config_from_summary.py --summary feed_readiness_summary.csv --config after.json
python3 update_lazer_symbols.py --summary readiness_summary.md --config after.json --dry-run
python3 update_lazer_symbols.py --summary readiness_summary.md --config after.json
```
