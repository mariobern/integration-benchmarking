# Changelog

## 2026-02-04

### Fixed

- **Date-based publisher and feed discovery** — The daily batch runner (`daily_benchmark_runner.py`) now discovers publishers and feeds based on the target date instead of looking at the last N minutes of real-time activity. Previously, running `--date 2026-01-28` would find publishers active *right now* rather than those that were active on Jan 28. This caused missed publishers (offline at batch time) and incorrect feed lists (feeds added/removed after the target date).

### Added

- **`--date` flag for `publisher_feeds.py`** — New argument to query all feeds a publisher published on a specific date (`--date 2026-01-28`). Uses `publisher_updates` table for accurate historical discovery. The existing `--time-window` real-time mode is preserved as the default for standalone usage.

### Removed

- **`--time-window` flag from `daily_benchmark_runner.py`** — No longer needed since publisher discovery is now date-based. The `publisher_feeds.py` script still supports `--time-window` for standalone real-time usage.

### Changed

- `get_active_publishers()` queries `publisher_updates WHERE toDate(publish_time) = target_date` instead of `feed_publisher_junction WHERE last_updated_at >= now() - INTERVAL N MINUTE`.
- `run_publisher_feeds()` passes `--date` to `publisher_feeds.py` instead of `--time-window` and `--date-offset`.
