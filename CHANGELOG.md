# Changelog

## 2026-02-14

### Added

- **`feed_readiness.py`** — new combined readiness script that orchestrates benchmark quality (`quick_benchmark_95.py`) and uptime (`feed_uptime.py`) into a single per-feed verdict, with publisher-level bucket classification (`fully_passing`, `benchmark_only`, `uptime_only`, `both_failing`) and optional detailed consistency reporting.
- **`docs/feed_readiness.md`** — dedicated usage guide for `feed_readiness.py` covering CLI modes, readiness logic, benchmarkable asset-class behavior, CSV output schema, and multi-date detailed consistency sections.

## 2026-02-13

### Added

- **`feed_uptime.py`** — new feed-centric uptime script that discovers publishers per feed and computes per-publisher/session uptime with default 1-second window mode plus optional precise gap mode.
- **`docs/feed_uptime.md`** — dedicated usage guide for `feed_uptime.py` with CLI modes, session behavior, threshold controls, and output schema.

### Changed

- **`feed_uptime.py` modes and thresholds**:
  - Default uptime method is now `1s window`.
  - Added `--precise` to use gap-based uptime.
  - Added `--uptime-threshold` (default `95.0`) for pass/fail classification.
  - `--gap-threshold` is used with `--precise` (default `200ms`).
  - Added publisher consistency matrix output (`PUBLISHER SUMMARY`) for multi-date runs.
- **`quick_benchmark.py` detailed multi-date publisher consistency reporting**:
  - Added CSV `PUBLISHER SUMMARY` section (after `PUBLISHER DETAIL`) for cross-date PASS/FAIL/ERROR matrix by publisher.
  - Added console `PUBLISHER CONSISTENCY` section with per-session pass/fail rates and date timelines.
  - Gated to runs using `--detailed` with more than one unique evaluated date.
- **README documentation** — added `feed_uptime.py` to the tools overview and a dedicated usage section with examples.

## 2026-02-12

### Added

- **Multi-feed-id support in `quick_benchmark.py`** — `--feed-id` now accepts one or more IDs (e.g., `--feed-id 327 328 329`). Creates a cartesian product of feed IDs × dates for parallel evaluation.
- **Multi-date support across benchmark scripts**:
  - New shared helper module: `date_utils.py` (`expand_date_args`, `validate_date_args`).
  - `publisher_feeds.py`: supports `--date` (list) and `--start-date/--end-date` (range) for output row dates.
  - `quick_benchmark.py`: single-feed mode supports multi-date list/range and evaluates one run per resolved date.
  - `publisher_benchmark.py`: date override flags (`--date`, `--start-date`, `--end-date`) ignore CSV date column and evaluate each unique `(feed_id, mode)` across selected dates.
- **Per-date reporting for multi-date runs**:
  - `quick_benchmark.py`: console `Per-date breakdown` section when multiple dates are evaluated.
  - `publisher_benchmark.py`: console `PER-DATE BREAKDOWN` and CSV `PER_DATE_BREAKDOWN` summary section.
- **Full feed-level benchmark flow in `quick_benchmark.py`** — expanded from lightweight output to full feed readiness workflow with feed-level metrics, detailed publisher output, and session-aware evaluation paths.

### Changed

- **LRU cache sizing for timezone SQL helpers** — increased from `maxsize=32` to `maxsize=128` in `quick_benchmark.py` and `publisher_benchmark.py` to reduce cache churn during multi-date runs.
- **Documentation refresh** — updated benchmark tool docs to reflect full quick-benchmark behavior and new date semantics.

### Fixed

- **Trade-only benchmark handling in `publisher_benchmark.py`** — query logic now accepts rows where benchmark `price` exists but `bid/ask` is missing (common in extended sessions), reducing false "no benchmark data" outcomes.

### Data

- Refreshed `benchmark_availability/SUMMARY.md`, `benchmark_availability/history.csv`, and `price_id_list.csv`.

## 2026-02-09

### Added

- **`isin_resolver_v2.py`** — new resolver with manual overrides, ADR-aware matching, and broader ticker normalization support.
- **ISIN research and usage docs** — added `docs/isin_research.md` and `docs/isin_resolver_v2.md`.

### Changed

- **README expansion** — added fuller tool documentation, argument references, and end-to-end workflow guidance.

## 2026-02-08

### Changed

- **ISIN/RIC reliability improvements** in `generate_source_upload.py` and `isin_resolver.py`, with substantial test coverage additions in:
  - `tests/test_generate_source_upload.py`
  - `tests/test_isin_resolver.py`

## 2026-02-06

### Added

- **`isin_resolver.py`** — New standalone utility that resolves ticker symbols to International Securities Identification Numbers (ISINs) using a tiered strategy: FinanceDatabase (158K+ equities, instant local lookup), yfinance (per-ticker Yahoo Finance fallback), and CUSIP→ISIN computation via python-stdnum. Achieves 86.4% coverage against ric.csv (612/708 tickers). Includes JSON file caching with 7-day TTL, CLI with `--tickers`/`--ticker-file`/`--ric-csv` inputs, and CSV output. Handles dotted tickers (BRK.B→BRK-B), BOM-encoded CSVs, ADRs with non-US ISINs, and ETFs. Tests at `tests/test_isin_resolver.py` (49 tests).

- **`generate_source_upload.py`** — New script to automate creation of `source_upload` CSV files for Datascope US equity onboarding. Given a list of tickers, resolves each to its Reuters Instrument Code (RIC), company name, and Pyth identifiers using a 3-tier strategy: Datascope ClickHouse (most accurate), NASDAQ Trader listings (offline fallback), and default `.N` suffix (flagged for review). Handles dotted tickers (BRK.B → BRKb.N), ADR classification, NASDAQ Trader caching (24h TTL), and parameterized ClickHouse queries. Supports `--no-clickhouse` for offline mode and `--force-refresh` to bypass cache.

- **`--skip-scipy-tests` flag for `publisher_benchmark.py`** — Skips scipy statistical tests (t-test, Wilcoxon, normality) for faster execution. Useful for batch processing where statistical metrics aren't needed. Reduces per-feed benchmark time by ~30-50%.

- **`--skip-scipy-tests` flag for `daily_benchmark_runner.py`** — Passes the flag through to `publisher_benchmark.py` during batch processing.

- **`--discovery-workers` flag for `daily_benchmark_runner.py`** — Controls the number of parallel workers for feed discovery phase. Default is 8. Parallelizes `publisher_feeds.py` calls across publishers.

- **Parallel feed discovery via `discover_feeds_parallel()`** — New function that runs feed discovery for multiple publishers concurrently using ThreadPoolExecutor. Creates a shared temporary directory for all discovered feed CSV files.

### Changed

- **LRU cache on timezone filter functions** — Added `@lru_cache(maxsize=32)` decorator to `get_market_hours_filter_sql()`, `get_extended_hours_filter_sql()`, and `get_overnight_hours_filter_sql()` functions. These functions are called repeatedly with the same parameters across feeds, so caching eliminates redundant SQL generation.

## 2026-02-04

### Reverted

- **Revert date-based publisher and feed discovery** — The date-based approach introduced in `301c129` queried `publisher_updates` (a massive time-series table with billions of rows) using `toDate(publish_time)`, which caused full table scans and made the batch runner hang indefinitely. Reverted publisher and feed discovery back to using `feed_publisher_junction` (a small pre-aggregated metadata table) with time-window filtering. The default time window for the batch runner is now 60 minutes (up from 5) for better coverage.

### Removed

- **`--date` flag from `publisher_feeds.py`** — Removed the date-based discovery mode that queried `publisher_updates`. The `--time-window` approach via `feed_publisher_junction` is used exclusively.

### Changed

- `get_active_publishers()` reverted to query `feed_publisher_junction FINAL` instead of `publisher_updates`.
- `run_publisher_feeds()` passes `--date-offset` and `--time-window` instead of `--date`.
- Default `--time-window` for `daily_benchmark_runner.py` increased from 5 to 60 minutes for broader publisher coverage.
