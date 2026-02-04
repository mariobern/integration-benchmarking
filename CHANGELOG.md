# Changelog

## 2026-02-04

### Reverted

- **Revert date-based publisher and feed discovery** — The date-based approach introduced in `301c129` queried `publisher_updates` (a massive time-series table with billions of rows) using `toDate(publish_time)`, which caused full table scans and made the batch runner hang indefinitely. Reverted publisher and feed discovery back to using `feed_publisher_junction` (a small pre-aggregated metadata table) with time-window filtering. The default time window for the batch runner is now 60 minutes (up from 5) for better coverage.

### Removed

- **`--date` flag from `publisher_feeds.py`** — Removed the date-based discovery mode that queried `publisher_updates`. The `--time-window` approach via `feed_publisher_junction` is used exclusively.

### Changed

- `get_active_publishers()` reverted to query `feed_publisher_junction FINAL` instead of `publisher_updates`.
- `run_publisher_feeds()` passes `--date-offset` and `--time-window` instead of `--date`.
- Default `--time-window` for `daily_benchmark_runner.py` increased from 5 to 60 minutes for broader publisher coverage.
