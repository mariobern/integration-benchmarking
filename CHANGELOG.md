# Changelog

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
