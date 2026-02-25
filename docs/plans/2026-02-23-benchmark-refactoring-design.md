# Benchmark Scripts Refactoring — Design Document

**Date:** 2026-02-23 (updated 2026-02-25)
**Goal:** Improve auditability by reducing file sizes to <400 lines, eliminating code duplication, extracting shared logic into a `lib/` package, and adding per-session pass/fail thresholds for US Equities extended hours.

## Problem

- 22,678 total lines across 18 Python files
- Largest files: 2,683–2,985 lines (impossible to audit in one sitting)
- 4 near-identical `_95` variant files (11,336 duplicated lines)
- ~840 lines of copy-pasted shared logic (config, SQL filters, statistics, data classes)
- Only 1 shared module exists (`date_utils.py`, 70 lines)

## Approach: Extract-and-Slim

Extract shared code into a `lib/` package. Scripts become thin CLI wrappers. Merge `_95` variants via a `--hit-rate-threshold` parameter.

## Package Structure

### `lib/` modules

| Module                  | Est. Lines | Responsibility                                                                                                                                             |
| ----------------------- | ---------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `lib/config.py`         | ~80        | `load_config()`, `get_clients()`, `normalize_asset_class()`, asset class constants/aliases                                                                 |
| `lib/models.py`         | ~120       | Shared dataclasses: `TradingSession`, `ExtendedHoursMetrics`, `OvernightMetrics`, `PublisherFeedMetrics`, `BenchmarkResult`, `SessionReadinessStats`, etc. |
| `lib/sql_filters.py`    | ~250       | SQL time-window builders: market hours, extended hours, overnight filters; `get_benchmark_table()`, `get_benchmark_columns()`                              |
| `lib/statistics.py`     | ~200       | `compute_statistical_metrics()`, `_distribution_stats()`, NRMSE/hit rate/t-test/Wilcoxon/normality                                                         |
| `lib/benchmark_core.py` | ~400       | Core benchmark evaluation: `evaluate_feed_two_queries()`, session evaluation, overnight evaluation. Accepts `hit_rate_threshold` as parameter.             |
| `lib/uptime_core.py`    | ~300       | Core uptime computation: `evaluate_feed_uptime()`, session uptime, gap detection                                                                           |
| `lib/csv_output.py`     | ~200       | CSV/console output helpers: `write_results_csv()`, summary formatting, console tables                                                                      |

### CLI scripts (root, thin wrappers)

| Script                   | Est. Lines | Change                                            |
| ------------------------ | ---------- | ------------------------------------------------- |
| `quick_benchmark.py`     | ~200       | Argparse + calls `lib/benchmark_core`             |
| `publisher_benchmark.py` | ~250       | Argparse + per-publisher orchestration via `lib/` |
| `feed_readiness.py`      | ~300       | Argparse + merge benchmark + uptime via `lib/`    |
| `publisher_report.py`    | ~200       | Argparse + health classification                  |
| `verify_uptime.py`       | ~150       | Argparse + comparison logic                       |

### Deleted files

- `quick_benchmark_95.py` — replaced by `--hit-rate-threshold 95`
- `publisher_benchmark_95.py` — replaced by `--hit-rate-threshold 95`

## Per-Session Thresholds (US Equities)

Currently all sessions use identical pass/fail thresholds. Extended hours (pre-market, after-hours, overnight) have less liquidity, wider spreads, and fewer participants — publisher data is naturally noisier. Relaxed thresholds for these sessions prevent false failures.

### Threshold Table

| Session                             | Auto-Pass (NRMSE) | Conditional NRMSE | Hit Rate |
| ----------------------------------- | ----------------- | ----------------- | -------- |
| **Regular** (9:30 AM – 4:00 PM)     | < 0.01            | < 0.05            | >= 95%   |
| **Pre-Market** (4:00 AM – 9:30 AM)  | < 0.05            | < 0.15            | >= 85%   |
| **After-Hours** (4:00 PM – 8:00 PM) | < 0.05            | < 0.15            | >= 85%   |
| **Overnight** (8:00 PM – 4:00 AM)   | < 0.05            | < 0.15            | >= 85%   |

### Scope

- **US Equities only** — FX, metals, commodities, treasuries keep existing thresholds (24-hour markets, no session concept)
- Applies across all scripts: quick_benchmark, publisher_benchmark, feed_readiness, publisher_report
- No new CLI flags needed — the system picks thresholds automatically based on which session is being evaluated

### Implementation in `lib/`

Thresholds are defined as a data structure in `lib/benchmark_core.py` (or `lib/thresholds.py` if it improves clarity). The pass/fail function accepts a session type and looks up the correct thresholds. Non-US-equity asset classes always use regular thresholds.

## \_95 Variant Consolidation

The only difference between `quick_benchmark.py` and `quick_benchmark_95.py` (and similarly for `publisher_benchmark`) is the hit rate pass threshold (98% vs 95%). These are consolidated:

- Add `--hit-rate-threshold` CLI argument (default: 98, valid values: any float 0-100)
- Pass threshold through to `lib/benchmark_core.py` evaluation functions
- `feed_readiness.py` and `publisher_report.py` pass the threshold when calling benchmark functions
- Delete the `_95` files entirely

## Phased Rollout

### Phase 1: Extract shared foundations

**Scope:** `lib/config.py`, `lib/models.py`, `lib/sql_filters.py`

- Create `lib/` package with `__init__.py`
- Extract config loading, client creation, asset class constants
- Extract all shared dataclasses
- Extract SQL time-filter builders
- Update imports in all consuming scripts
- Add tests: `tests/lib/test_config.py`, `tests/lib/test_models.py`, `tests/lib/test_sql_filters.py`
- **Verification:** All scripts produce identical output before/after

### Phase 2: Extract statistics and merge \_95 variants

**Scope:** `lib/statistics.py`, delete `*_95.py` files

- Extract statistical computation logic
- Add `--hit-rate-threshold` parameter to `quick_benchmark.py` and `publisher_benchmark.py`
- Delete `quick_benchmark_95.py` and `publisher_benchmark_95.py`
- Update `feed_readiness.py` and `publisher_report.py` imports
- Add tests: `tests/lib/test_statistics.py`
- **Verification:** Run both threshold values, compare output to original \_95 scripts

### Phase 3: Extract core logic

**Scope:** `lib/benchmark_core.py`, `lib/uptime_core.py`

- Extract benchmark evaluation logic from `quick_benchmark.py`
- Extract uptime evaluation logic from `feed_uptime.py`
- Scripts become thin CLI wrappers
- Add tests: `tests/lib/test_benchmark_core.py`, `tests/lib/test_uptime_core.py`
- **Verification:** Output comparison against golden files

### Phase 4: Extract output helpers and final cleanup

**Scope:** `lib/csv_output.py`, dead code removal, docs update

- Extract CSV/console output logic
- Remove remaining dead code
- Final audit: every file < 400 lines
- Add tests: `tests/lib/test_csv_output.py`
- Update CLAUDE.md and script docs
- **Verification:** Full regression across all scripts

## Expected Outcome

| Metric           | Before         | After                                                       |
| ---------------- | -------------- | ----------------------------------------------------------- |
| Total lines      | 22,678         | ~12,000                                                     |
| File count       | 18             | 14 (−4 \_95 files, +7 lib modules, −1 feed_uptime absorbed) |
| Largest file     | 2,985 lines    | ~400 lines                                                  |
| Duplicated lines | ~840           | ~0                                                          |
| Shared modules   | 1 (date_utils) | 8 (date_utils + 7 lib modules)                              |

## Testing Strategy

### Output comparison (golden files)

For each phase:

1. Run affected scripts against known feeds, capture CSV as golden files
2. Make changes
3. Run same commands, diff against golden files
4. Pass: byte-identical output (or explainable differences)

Test feeds: 1 FX, 1 US equity (regular + extended + overnight), 1 metals, 1 futures.

### Unit tests

Each `lib/` module gets a corresponding test file in `tests/lib/`:

| Test file                          | Coverage target                                            |
| ---------------------------------- | ---------------------------------------------------------- |
| `tests/lib/test_config.py`         | Config loading, client creation, asset class normalization |
| `tests/lib/test_models.py`         | Dataclass construction, defaults, edge cases               |
| `tests/lib/test_sql_filters.py`    | SQL output for each asset class and session type           |
| `tests/lib/test_statistics.py`     | RMSE, hit rate, distribution stats with known inputs       |
| `tests/lib/test_benchmark_core.py` | Integration tests with mocked ClickHouse                   |
| `tests/lib/test_uptime_core.py`    | Integration tests with mocked ClickHouse                   |
| `tests/lib/test_csv_output.py`     | CSV format correctness                                     |

Tests are written in the same phase as module extraction.

### Per-session threshold tests

- Unit tests for threshold lookup: regular vs extended sessions, US equities vs other asset classes
- Edge cases: NRMSE exactly at boundary (0.05, 0.15), hit rate exactly at boundary (85%, 95%)
- Integration: US equity feed with `--extended-hours` produces different pass/fail than regular-only run

### Additional checks

- `pre-commit run --all-files` passes
- Import smoke test: `python3 -c "from lib import config, models, sql_filters, statistics, benchmark_core, uptime_core, csv_output"`
- Each script's `--help` works

## CLI Changes

- `--hit-rate-threshold <float>` added to `quick_benchmark.py` and `publisher_benchmark.py` (default: 98)
- No backward compatibility constraints (free to change)
- All existing flags remain functional

## Risks

| Risk                                              | Mitigation                                        |
| ------------------------------------------------- | ------------------------------------------------- |
| Subtle behavior change during extraction          | Golden-file output comparison per phase           |
| Broken imports after restructuring                | Import smoke test in CI                           |
| Merge conflicts if scripts change during refactor | Incremental phases reduce conflict window         |
| `lib/benchmark_core.py` too large                 | Split further if >400 lines during implementation |
