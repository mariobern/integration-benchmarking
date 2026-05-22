# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

This repository contains standalone benchmark scripts for Pyth Network Lazer feeds. It evaluates publisher data quality against external benchmarks (Datascope) to assess feed readiness.

## Setup

```bash
pip install -r requirements.txt
cp config.yaml.sample config.yaml  # then fill in ClickHouse credentials
```

## Pass/Fail Criteria

- **Publisher PASSES** if: `nrmse < nrmse_auto_pass` OR (`nrmse < nrmse_conditional` AND `hit_rate >= hit_rate_threshold`)
- **Feed is READY** if: `passing_publisher_count >= target_publisher_count`

### Per-Session Thresholds

| Session / Asset Class                      | nrmse_auto_pass | nrmse_conditional | hit_rate_threshold |
| ------------------------------------------ | --------------- | ----------------- | ------------------ |
| Regular (fx, us-equities, us-treasuries)   | 0.01            | 0.05              | 95%                |
| Relaxed (commodity, metals)                | 0.05            | 0.15              | 85%                |
| Extended (US equities pre/after/overnight) | 0.05            | 0.15              | 85%                |

Thresholds are defined in `lib/thresholds.py`. The `--hit-rate-threshold` CLI flag overrides the hit rate for regular and relaxed tiers; extended session thresholds are fixed.

## Database Configuration

Requires ClickHouse access configured in `config.yaml`:

- `lazer_clickhouse_prod`: Lazer production cluster (publisher data, feed metadata)
- `analytics_clickhouse`: Analytics cluster (Datascope benchmark data)

If connection fails with "EOF occurred in violation of protocol", the hostname is wrong.

## Input CSV Format

CSV files for batch processing (no header required):

```
feed_id,date,mode
327,2025-10-06,fx
1163,2025-10-02,us-equities
346,2025-10-02,metals
```

## Asset Classes

Benchmarkable (have Datascope data):

- `fx` - Foreign exchange
- `metals` / `metal` - Precious metals
- `us-equities` / `equity-us` - US equities (includes equity index futures)
- `commodity` - Commodities (includes commodity futures)
- `us-treasuries` / `treasuries` / `rates` - US Treasury bonds (uses yield values)

Not benchmarkable (will error): `crypto`, `crypto-redemption-rate`, `funding-rate`, `nav`

Use `--list-asset-classes` to discover asset classes in a CSV file.

## Futures Naming Convention

Futures contracts are auto-detected by symbol pattern: `[ROOT][MONTH_CODE][YEAR_DIGIT]`

- Month codes: F=Jan, G=Feb, H=Mar, J=Apr, K=May, M=Jun, N=Jul, Q=Aug, U=Sep, V=Oct, X=Nov, Z=Dec
- Year digit: 5=2025, 6=2026, 7=2027, etc.
- Examples: `Commodities.CCH6/USD` (Copper Mar 2026), `Equity.US.EMH6/USD` (E-Mini S&P Mar 2026)

Uses `datascope_futures_benchmark_data` table instead of the standard benchmark table.

## Trading Sessions (US Equities)

| Session     | Time (ET)         | Benchmark Source | Flag               |
| ----------- | ----------------- | ---------------- | ------------------ |
| Regular     | 9:30 AM - 4:00 PM | Datascope        | (always)           |
| Pre-market  | 4:00 AM - 9:30 AM | Datascope        | `--extended-hours` |
| After-hours | 4:00 PM - 8:00 PM | Datascope        | `--extended-hours` |
| Overnight   | 8:00 PM - 4:00 AM | Publisher 32     | `--overnight`      |

FX and Metals use 24-hour regular session (with maintenance windows). See individual script docs for session-specific output columns.

## Scripts

| Script                                 | Purpose                                                                                                | Quick Example                                                                                         | Docs                                                                     |
| -------------------------------------- | ------------------------------------------------------------------------------------------------------ | ----------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------ |
| `quick_benchmark.py`                   | Evaluate feed quality vs Datascope                                                                     | `python quick_benchmark.py --csv feeds.csv`                                                           | [docs/quick_benchmark.md](docs/quick_benchmark.md)                       |
| `feed_readiness.py`                    | Combined benchmark + uptime readiness check                                                            | `python feed_readiness.py --csv feeds.csv`                                                            | [docs/feed_readiness.md](docs/feed_readiness.md)                         |
| `publisher_benchmark.py`               | Per-publisher benchmark with statistical metrics                                                       | `python publisher_benchmark.py --csv feeds.csv`                                                       | [docs/publisher_benchmark.md](docs/publisher_benchmark.md)               |
| `publisher_report.py`                  | Per-feed health classification (HEALTHY/DEGRADED/FAILING)                                              | `python publisher_report.py --csv feeds.csv`                                                          | [docs/publisher_report.md](docs/publisher_report.md)                     |
| `generate_source_upload.py`            | Datascope onboarding CSV for US equities                                                               | `python generate_source_upload.py --tickers AAPL,NVDA`                                                | [docs/generate_source_upload.md](docs/generate_source_upload.md)         |
| `generate_ric_mapping.py`              | Universal RIC mapping (all asset classes); resolves by ticker or feedId, reads `after.json` by default | `python generate_ric_mapping.py --ticker AAPL EURUSD` or `--feed-id 922 327`                          | [docs/generate_ric_mapping.md](docs/generate_ric_mapping.md)             |
| `isin_resolver.py`                     | Ticker to ISIN resolution (multi-tier)                                                                 | `python isin_resolver.py --tickers AAPL,MSFT`                                                         | [docs/isin_resolver_v2.md](docs/isin_resolver_v2.md)                     |
| `update_lazer_symbols.py`              | Promote feeds COMING_SOON to STABLE in after.json                                                      | `python3 update_lazer_symbols.py --summary X --config after.json --dry-run`                           | [docs/update_lazer_symbols.md](docs/update_lazer_symbols.md)             |
| `update_config_from_summary.py`        | Update after.json publisher lists from readiness CSV                                                   | `python3 update_config_from_summary.py --summary X.csv --config after.json`                           | [docs/update_config_from_summary.md](docs/update_config_from_summary.md) |
| `trading_halt_history.py`              | Download NASDAQ LUDP halt data                                                                         | `python trading_halt_history.py`                                                                      | [docs/trading_halt_history.md](docs/trading_halt_history.md)             |
| `generate_price_list.py`               | Generate price_id_list.csv from feed IDs + lazer_symbols.json                                          | `python3 generate_price_list.py --feed-id 327 340 --date 2026-02-27`                                  | -                                                                        |
| `verify_uptime.py`                     | Compare uptime calculation methods (1s window vs 200ms gap)                                            | `python verify_uptime.py --publisher-id 55 --date 2026-01-28`                                         | -                                                                        |
| `update_min_publishers.py`             | Enforce minimum minPublishers based on publisher count                                                 | `python3 update_min_publishers.py --config after.json --dry-run`                                      | [docs/update_min_publishers.md](docs/update_min_publishers.md)           |
| `volume_profile.py`                    | Volume profile analysis for US equities (per-session)                                                  | `python3 volume_profile.py --tickers AAPL,MSFT --date 2026-03-03`                                     | [docs/volume_profile.md](docs/volume_profile.md)                         |
| `tools/config-linter/config_linter.py` | Lint after.json for config errors (duplicates, publishers, schedules)                                  | `python3 tools/config-linter/config_linter.py --config after.json`                                    | [docs/config_linter.md](docs/config_linter.md)                           |
| `tools/edit-config/edit_config.py`     | Surgical editor: add/remove publishers, set minPublishers, set state                                   | `python3 tools/edit-config/edit_config.py --config after.json --add-publisher 80 --feed-id 1000-1050` | [docs/edit_config.md](docs/edit_config.md)                               |

### Publisher Performance Portal

Located in `portal/`. FastAPI-based REST API + web dashboard for publishers to view benchmark performance. See [docs/portal_usage.md](docs/portal_usage.md) for endpoints, uptime methodology, and dashboard features.

```bash
# Test server with mock data
python portal/test_api.py

# Production server
uvicorn portal.api.main:app --reload

# Daily batch (production)
python -m portal.batch.daily_benchmark_runner --date 2026-01-30 --overnight --workers 16

# Tests
pytest portal/tests/ -v
```

### Feed Readiness (Primary Readiness Tool)

`feed_readiness.py` is the primary tool for assessing production readiness. A feed is **READY** only if enough publishers pass **both** benchmark quality and uptime checks. Per-publisher: `fully_passes = benchmark_passes AND uptime_passes`. Publisher buckets: `fully_passing`, `benchmark_only`, `uptime_only`, `both_failing`. See [docs/feed_readiness.md](docs/feed_readiness.md) for full output schema and per-session readiness details.

## lib/ Package Structure

Shared logic extracted from scripts into `lib/`:

| Module                      | Purpose                                                       |
| --------------------------- | ------------------------------------------------------------- |
| `config.py`                 | Config loading, ClickHouse clients, asset class normalization |
| `models.py`                 | Shared dataclasses (BenchmarkResult, FeedUptimeResult, etc.)  |
| `sql_filters.py`            | SQL WHERE clause builders for trading sessions                |
| `statistics.py`             | Statistical computations (t-test, Wilcoxon, normality)        |
| `thresholds.py`             | Per-session pass/fail thresholds (SessionThresholds)          |
| `benchmark_core.py`         | Core feed-level benchmark evaluation engine                   |
| `uptime_core.py`            | Uptime calculation (1s window and gap-based)                  |
| `publisher_eval.py`         | Single-publisher benchmark evaluation                         |
| `publisher_health.py`       | Publisher health classification (HEALTHY/DEGRADED/FAILING)    |
| `publisher_output.py`       | Console and CSV output for publisher_benchmark                |
| `quick_benchmark_output.py` | Console and CSV output for quick_benchmark                    |
| `readiness_core.py`         | Feed readiness evaluation (benchmark + uptime)                |
| `readiness_output.py`       | Console and CSV output for feed_readiness                     |
| `report_output.py`          | Console and CSV output for publisher_report                   |
| `uptime_output.py`          | Console and CSV output for feed_uptime                        |

Scripts are thin CLI wrappers that parse arguments and delegate to `lib/`.

## Benchmark Results Interpretation

`docs/benchmark_results_guide.md` is a standalone guide for publishers explaining how to read benchmark CSV output. Covers pass/fail criteria, core quality metrics, session breakdowns, and advanced statistical tests.

## Pre-commit

Always run `pre-commit run --files <changed files>` before committing. Hooks: black (Python), prettier (Markdown/YAML), trailing whitespace, end-of-file fixer.

## Key Gotchas

- **Dotted tickers** (BRK.B) use `BRKb.N` RIC format (lowercase class, no dot)
- **NASDAQ Trader caching** in `.nasdaq_cache/` with 24h TTL; use `--force-refresh` to bypass
- **Publisher 32 overnight** is peer comparison, not official benchmark (circular validation risk)
- **`python` not found** on this system — use `python3` or activate venv (`source venv/bin/activate`)
- **Publisher 71** may fail due to infinite t_statistic values (numeric precision edge case)
- **ClickHouse parameterized queries** use `{param_name:String}` syntax with `parameters=dict`
- **`docs/asset-classes.md`** — update the `Last updated:` date at the top every time this file is modified
- **Equities qualifier filter** — benchmark queries for `us-equities*` and `hk-equities` modes (in `lazer_dq/evaluate_feed_standalone.py`) filter out irregular trade conditions: IRGCOND qualifiers, plus `102[ODDSALCOND]` (odd-lot sales) and `101[IRGSALCOND]` (irregular sales)
- **`hk-equities` mode (lazer_dq)** — uses `09:30:00–10:30:00 Asia/Hong_Kong` (HKT = UTC+8, no DST) for the per-row window in `evaluate_feeds_bulk`; benchmark query reuses the global-equities table (`datascope_global_equities_benchmark_data`)
- **Metals benchmark smoothing** — `lazer_dq/evaluate_feed_standalone.py` applies EMA (`span=10`) to `benchmark_price` when `mode == "metals"` because the metals benchmark is noisy
- **`evaluate_feed_standalone` exit codes** — `0` = analysis ran; `2` = no benchmark data for that feed/date/mode (non-trading day, holiday, or feed not yet ingested in Datascope); other non-zero = unexpected error. `evaluate_feeds_bulk` treats every non-zero engine exit as a soft failure and continues to the next row
- **Aggregate feed (publisher 0)** — `feed_readiness.py` and `quick_benchmark.py` evaluate the aggregated price feed as publisher 0 by default; disable with `--no-agg`. Publisher 0 is excluded from passing/failing counts and readiness determination.
- **`summarize_feeds` asset class** — `lazer_dq/summarize_feeds.py` defaults to `--asset-class us-equities` (4 modes). For HK equities use `--asset-class hk-equities` (1 mode). Mode set + session labels + default thresholds live in `ASSET_CLASS_CONFIG` at the top of the file; adding a new asset class is a one-entry edit. The CSV's column-3 mode must match the selected asset class or the script exits with a clear error.
