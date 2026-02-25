# Benchmark Refactoring Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Extract shared logic from 18 Python files into a `lib/` package, merge `_95` variants via `--hit-rate-threshold`, and add per-session pass/fail thresholds for US Equities extended hours.

**Architecture:** Four-phase extract-and-slim. Each phase extracts one layer of shared logic into `lib/`, updates imports in consuming scripts, and verifies identical output via golden files. Phase 3 introduces session-aware thresholds as part of the core benchmark extraction.

**Tech Stack:** Python 3, pytest, clickhouse_connect, dataclasses, argparse

---

## Phase 1: Extract Shared Foundations

### Task 1.1: Create `lib/` Package

**Files:**

- Create: `lib/__init__.py`

**Step 1: Create the package**

```python
# lib/__init__.py
"""Shared library for Pyth Lazer benchmark scripts."""
```

**Step 2: Verify import works**

Run: `source venv/bin/activate && python3 -c "import lib; print('ok')"`
Expected: `ok`

**Step 3: Commit**

```bash
git add lib/__init__.py
git commit -m "chore: create lib/ package"
```

---

### Task 1.2: Extract `lib/config.py`

**Files:**

- Create: `lib/config.py`
- Create: `tests/lib/__init__.py`
- Create: `tests/lib/test_config.py`
- Reference: `quick_benchmark_95.py:56-80` (ASSET_CLASS_ALIASES, BENCHMARKABLE_ASSET_CLASSES)
- Reference: `quick_benchmark_95.py:230-232` (normalize_asset_class)
- Reference: `quick_benchmark_95.py:112-150` (load_config, get_clients)

**Step 1: Write the failing test**

```python
# tests/lib/test_config.py
"""Tests for lib.config — config loading, client creation, asset class normalization."""

import pytest
from unittest.mock import patch, mock_open

from lib.config import (
    ASSET_CLASS_ALIASES,
    BENCHMARKABLE_ASSET_CLASSES,
    normalize_asset_class,
    load_config,
)


class TestNormalizeAssetClass:
    def test_canonical_names_unchanged(self):
        assert normalize_asset_class("fx") == "fx"
        assert normalize_asset_class("metals") == "metals"
        assert normalize_asset_class("us-equities") == "us-equities"
        assert normalize_asset_class("commodity") == "commodity"
        assert normalize_asset_class("us-treasuries") == "us-treasuries"

    def test_aliases_resolve(self):
        assert normalize_asset_class("metal") == "metals"
        assert normalize_asset_class("equity-us") == "us-equities"
        assert normalize_asset_class("rates") == "us-treasuries"
        assert normalize_asset_class("treasuries") == "us-treasuries"

    def test_case_insensitive(self):
        assert normalize_asset_class("FX") == "fx"
        assert normalize_asset_class("Metals") == "metals"
        assert normalize_asset_class("US-Equities") == "us-equities"

    def test_unknown_asset_class_passthrough(self):
        assert normalize_asset_class("unknown") == "unknown"
        assert normalize_asset_class("CRYPTO") == "crypto"


class TestAssetClassConstants:
    def test_benchmarkable_is_subset_of_aliases(self):
        for ac in BENCHMARKABLE_ASSET_CLASSES:
            assert ac in ASSET_CLASS_ALIASES.values()

    def test_non_benchmarkable_excluded(self):
        assert "crypto" not in BENCHMARKABLE_ASSET_CLASSES
        assert "nav" not in BENCHMARKABLE_ASSET_CLASSES
        assert "funding-rate" not in BENCHMARKABLE_ASSET_CLASSES


class TestLoadConfig:
    def test_missing_config_raises(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(FileNotFoundError):
            load_config()

    def test_valid_config_loads(self, tmp_path, monkeypatch):
        config_content = "lazer_clickhouse_prod:\n  host: localhost\n"
        config_file = tmp_path / "config.yaml"
        config_file.write_text(config_content)
        monkeypatch.chdir(tmp_path)
        config = load_config()
        assert config["lazer_clickhouse_prod"]["host"] == "localhost"
```

**Step 2: Run test to verify it fails**

Run: `source venv/bin/activate && pytest tests/lib/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.config'`

**Step 3: Implement `lib/config.py`**

Extract from `quick_benchmark_95.py` lines 56-80 (constants), 230-232 (normalize), 112-150 (load_config, get_clients). The implementation must be a direct copy of the existing logic — no behavioral changes.

```python
# lib/config.py
"""Configuration loading, client creation, and asset class constants."""

from pathlib import Path

import clickhouse_connect
import yaml

# --- Asset class aliases and constants ---

ASSET_CLASS_ALIASES = {
    "metal": "metals",
    "metals": "metals",
    "equity-us": "us-equities",
    "us-equities": "us-equities",
    "fx": "fx",
    "commodity": "commodity",
    "crypto": "crypto",
    "crypto-redemption-rate": "crypto-redemption-rate",
    "funding-rate": "funding-rate",
    "rates": "us-treasuries",
    "nav": "nav",
    "us-treasuries": "us-treasuries",
    "treasuries": "us-treasuries",
}

BENCHMARKABLE_ASSET_CLASSES = {
    "fx",
    "metals",
    "us-equities",
    "commodity",
    "us-treasuries",
}


def normalize_asset_class(asset_class: str) -> str:
    """Normalize asset class name to canonical form."""
    return ASSET_CLASS_ALIASES.get(asset_class.lower(), asset_class.lower())


def load_config() -> dict:
    """Load database configuration from config.yaml."""
    config_path = Path("config.yaml")
    if not config_path.exists():
        raise FileNotFoundError(
            "config.yaml not found. Copy config.yaml.sample and fill in credentials."
        )
    with open(config_path) as f:
        return yaml.safe_load(f)


def get_clients(config: dict) -> tuple:
    """Create ClickHouse clients for Lazer and Analytics databases.

    Returns:
        (lazer_client, analytics_client) tuple.
    """
    lazer_cfg = config["lazer_clickhouse_prod"]
    analytics_cfg = config["analytics_clickhouse"]
    connect_timeout = 60
    send_receive_timeout = 300

    lazer_client = clickhouse_connect.get_client(
        host=lazer_cfg["host"],
        username=lazer_cfg["user"],
        password=lazer_cfg["password"],
        secure=True,
        connect_timeout=connect_timeout,
        send_receive_timeout=send_receive_timeout,
    )
    analytics_client = clickhouse_connect.get_client(
        host=analytics_cfg["host"],
        username=analytics_cfg["user"],
        password=analytics_cfg["password"],
        secure=True,
        connect_timeout=connect_timeout,
        send_receive_timeout=send_receive_timeout,
    )
    return lazer_client, analytics_client


def get_lazer_client(config: dict):
    """Create ClickHouse client for Lazer database only."""
    lazer_cfg = config["lazer_clickhouse_prod"]
    return clickhouse_connect.get_client(
        host=lazer_cfg["host"],
        username=lazer_cfg["user"],
        password=lazer_cfg["password"],
        secure=True,
        connect_timeout=60,
        send_receive_timeout=300,
    )


def get_analytics_client(config: dict):
    """Create ClickHouse client for Analytics database only."""
    analytics_cfg = config["analytics_clickhouse"]
    return clickhouse_connect.get_client(
        host=analytics_cfg["host"],
        username=analytics_cfg["user"],
        password=analytics_cfg["password"],
        secure=True,
        connect_timeout=60,
        send_receive_timeout=300,
    )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/lib/test_config.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add lib/config.py tests/lib/__init__.py tests/lib/test_config.py
git commit -m "feat(lib): extract config loading and asset class constants"
```

---

### Task 1.3: Extract `lib/models.py`

**Files:**

- Create: `lib/models.py`
- Create: `tests/lib/test_models.py`
- Reference: `quick_benchmark_95.py:111-200` (ExtendedHoursMetrics, OvernightMetrics, PublisherFeedMetrics, BenchmarkResult)
- Reference: `publisher_benchmark_95.py:443-523` (ExtendedHoursMetrics, OvernightMetrics, PublisherBenchmarkResult)
- Reference: `feed_readiness.py:50-150` (SessionReadinessStats, PublisherReadinessDetail, FeedReadinessResult)
- Reference: `feed_uptime.py:50-76` (PublisherSessionUptime, FeedUptimeResult)

**Step 1: Write the failing test**

Test file should verify:

- All dataclass fields have expected defaults
- Frozen dataclasses are immutable
- Edge cases: None fields, empty lists

```python
# tests/lib/test_models.py
"""Tests for lib.models — shared dataclasses."""

import pytest
from lib.models import (
    ExtendedHoursMetrics,
    OvernightMetrics,
    PublisherFeedMetrics,
    BenchmarkResult,
    PublisherBenchmarkResult,
    PublisherSessionUptime,
    FeedUptimeResult,
)


class TestExtendedHoursMetrics:
    def test_default_construction(self):
        m = ExtendedHoursMetrics(session="premarket")
        assert m.session == "premarket"
        assert m.n_observations == 0
        assert m.passes is False
        assert m.error is None

    def test_passes_field(self):
        m = ExtendedHoursMetrics(session="afterhours", passes=True, hit_rate=96.5)
        assert m.passes is True
        assert m.hit_rate == 96.5


class TestOvernightMetrics:
    def test_default_construction(self):
        m = OvernightMetrics()
        assert m.n_observations == 0
        assert m.reference_publisher_id is None
        assert m.passes is False


class TestPublisherFeedMetrics:
    def test_required_fields(self):
        m = PublisherFeedMetrics(publisher_id=55)
        assert m.publisher_id == 55
        assert m.passes is False
        assert m.premarket_metrics is None


class TestBenchmarkResult:
    def test_required_fields(self):
        r = BenchmarkResult(feed_id=327, date="2026-01-01", mode="fx", symbol="EURUSD")
        assert r.feed_id == 327
        assert r.ready is False
        assert r.passing_publishers == []


class TestPublisherBenchmarkResult:
    def test_required_fields(self):
        r = PublisherBenchmarkResult(
            publisher_id=55, feed_id=327, date="2026-01-01", mode="fx", symbol="EURUSD"
        )
        assert r.publisher_id == 55
        assert r.passes is False


class TestPublisherSessionUptime:
    def test_frozen(self):
        u = PublisherSessionUptime(
            publisher_id=55, session="regular", uptime_pct=99.5, passes=True,
            seconds_with_data=28800, total_seconds=28800, updates_total=100000,
            updates_per_second=3.47, downtime_ms=0, period_length_ms=28800000,
            max_gap_ms=0, gaps_over_threshold=0,
        )
        with pytest.raises(AttributeError):
            u.uptime_pct = 50.0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/lib/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement `lib/models.py`**

Extract all shared dataclasses. Copy field definitions exactly from the source scripts. Use `from __future__ import annotations` for forward references.

Key dataclasses to extract:

- `ExtendedHoursMetrics` (from quick_benchmark_95.py:111-125)
- `OvernightMetrics` (from quick_benchmark_95.py:127-142)
- `PublisherFeedMetrics` (from quick_benchmark_95.py:144-172)
- `BenchmarkResult` (from quick_benchmark_95.py:174-200)
- `PublisherBenchmarkResult` (from publisher_benchmark_95.py:482-523)
- `PublisherSessionUptime` (from feed_uptime.py:50-64, frozen=True)
- `FeedUptimeResult` (from feed_uptime.py:66-76, frozen=True)

Do NOT extract script-specific dataclasses (FeedHealthResult, PublisherReadinessDetail, etc.) — those stay in their scripts.

**Step 4: Run test to verify it passes**

Run: `pytest tests/lib/test_models.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add lib/models.py tests/lib/test_models.py
git commit -m "feat(lib): extract shared dataclasses into models module"
```

---

### Task 1.4: Extract `lib/sql_filters.py`

**Files:**

- Create: `lib/sql_filters.py`
- Create: `tests/lib/test_sql_filters.py`
- Reference: `quick_benchmark_95.py:85-108` (time constants)
- Reference: `quick_benchmark_95.py:308-411` (SQL filter functions)
- Reference: `quick_benchmark_95.py:234-305` (get_benchmark_table, get_benchmark_columns, futures detection)

**Step 1: Write the failing test**

```python
# tests/lib/test_sql_filters.py
"""Tests for lib.sql_filters — SQL time-window builders."""

import pytest
from lib.sql_filters import (
    get_market_hours_filter_sql,
    get_extended_hours_filter_sql,
    get_overnight_hours_filter_sql,
    get_benchmark_table,
    get_benchmark_columns,
    is_futures_symbol,
    REGULAR_MIN_OBSERVATIONS,
    SESSION_MIN_OBSERVATIONS,
)


class TestMarketHoursFilter:
    def test_us_equities_regular_hours(self):
        sql = get_market_hours_filter_sql("us-equities", "2026-01-15", "publish_time")
        assert "14:30:00" in sql  # 9:30 AM ET = 14:30 UTC
        assert "21:00:00" in sql  # 4:00 PM ET = 21:00 UTC
        assert "publish_time" in sql

    def test_fx_returns_empty(self):
        sql = get_market_hours_filter_sql("fx", "2026-01-15", "publish_time")
        # FX is 24-hour, no market hours filter
        assert sql == "" or "00:00:00" in sql

    def test_metals_returns_empty(self):
        sql = get_market_hours_filter_sql("metals", "2026-01-15", "publish_time")
        assert sql == "" or "00:00:00" in sql


class TestExtendedHoursFilter:
    def test_premarket(self):
        sql = get_extended_hours_filter_sql("premarket", "2026-01-15", "publish_time")
        assert "publish_time" in sql
        # Pre-market: 4:00 AM - 9:30 AM ET = 09:00 - 14:30 UTC
        assert "09:00:00" in sql
        assert "14:30:00" in sql

    def test_afterhours(self):
        sql = get_extended_hours_filter_sql("afterhours", "2026-01-15", "publish_time")
        assert "publish_time" in sql
        # After-hours: 4:00 PM - 8:00 PM ET = 21:00 - 01:00 UTC
        assert "21:00:00" in sql


class TestOvernightHoursFilter:
    def test_overnight_spans_midnight(self):
        sql = get_overnight_hours_filter_sql("2026-01-15", "publish_time")
        assert "publish_time" in sql
        # Overnight: 8:00 PM - 4:00 AM ET = 01:00 - 09:00 UTC (next day)


class TestBenchmarkTable:
    def test_regular_symbol(self):
        table = get_benchmark_table("EURUSD", "fx")
        assert "datascope" in table.lower()

    def test_futures_symbol(self):
        table = get_benchmark_table("Commodities.CCH6/USD", "commodity")
        assert "futures" in table.lower()


class TestFuturesDetection:
    def test_futures_pattern(self):
        assert is_futures_symbol("Commodities.CCH6/USD") is True
        assert is_futures_symbol("Equity.US.EMH6/USD") is True

    def test_non_futures(self):
        assert is_futures_symbol("EURUSD") is False
        assert is_futures_symbol("AAPL") is False


class TestConstants:
    def test_observation_thresholds(self):
        assert REGULAR_MIN_OBSERVATIONS == 100
        assert SESSION_MIN_OBSERVATIONS == 50
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/lib/test_sql_filters.py -v`
Expected: FAIL — `ModuleNotFoundError`

**Step 3: Implement `lib/sql_filters.py`**

Extract from quick_benchmark_95.py:

- Lines 85-108: Time constants (market hours, extended hours, overnight)
- Lines 234-305: `get_benchmark_table()`, `get_benchmark_columns()`, `is_futures_symbol()`
- Lines 308-411: `get_market_hours_filter_sql()`, `get_extended_hours_filter_sql()`, `get_overnight_hours_filter_sql()`

Copy exactly — no behavioral changes. Keep `@lru_cache` decorators.

**Step 4: Run test to verify it passes**

Run: `pytest tests/lib/test_sql_filters.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add lib/sql_filters.py tests/lib/test_sql_filters.py
git commit -m "feat(lib): extract SQL filter builders and time constants"
```

---

### Task 1.5: Update Imports in All Scripts (Phase 1)

**Files:**

- Modify: `quick_benchmark.py` — replace local definitions with `from lib.config import ...`, `from lib.models import ...`, `from lib.sql_filters import ...`
- Modify: `quick_benchmark_95.py` — same
- Modify: `publisher_benchmark.py` — same
- Modify: `publisher_benchmark_95.py` — same
- Modify: `feed_readiness.py` — update imports (currently imports from quick_benchmark_95)
- Modify: `publisher_report.py` — update imports (currently imports from publisher_benchmark_95)
- Modify: `feed_uptime.py` — replace local config/model definitions
- Modify: `verify_uptime.py` — replace local config definitions
- Modify: `check_benchmark_availability.py` — replace local config definitions

**Step 1: For each script, replace local definitions with lib imports**

For each file:

1. Add imports from `lib.config`, `lib.models`, `lib.sql_filters`
2. Delete the local definitions of the extracted code (constants, dataclasses, functions)
3. Keep script-specific code (argparse, main logic, script-only dataclasses)

**Important:** `feed_readiness.py` currently imports from `quick_benchmark_95`. After this step, shared items come from `lib.*`, but script-specific items (like `evaluate_feed_two_queries`) still come from `quick_benchmark_95` until Phase 3.

**Step 2: Run smoke test**

Run: `source venv/bin/activate && python3 -c "from lib import config, models, sql_filters; print('lib imports ok')"`
Expected: `lib imports ok`

Run: `python3 quick_benchmark_95.py --help`
Expected: Help text prints without error

Run: `python3 feed_readiness.py --help`
Expected: Help text prints without error

**Step 3: Run existing tests**

Run: `pytest tests/ -v`
Expected: All existing tests still PASS

**Step 4: Commit**

```bash
git add quick_benchmark.py quick_benchmark_95.py publisher_benchmark.py publisher_benchmark_95.py feed_readiness.py publisher_report.py feed_uptime.py verify_uptime.py check_benchmark_availability.py
git commit -m "refactor: update all scripts to import from lib/ (Phase 1)"
```

---

### Task 1.6: Golden-File Verification (Phase 1)

**Purpose:** Confirm zero behavioral change. Pick one feed from each asset class, run before/after, diff.

**Step 1: Capture golden files**

Before making changes in Task 1.5, run these against the live database and save output. If Task 1.5 is already done, use `git stash` to temporarily revert, capture, then `git stash pop`.

Pick specific feeds from existing CSV files or known feed IDs. The exact feeds depend on what's available — the implementer should identify suitable test feeds.

**Step 2: Run same commands after changes**

Compare CSV output byte-for-byte with `diff`. Any difference must be explained (e.g., timestamp in header).

**Step 3: Commit verification notes**

Add a brief note to the PR description confirming golden-file comparison passed.

---

## Phase 2: Extract Statistics and Merge \_95 Variants

### Task 2.1: Extract `lib/statistics.py`

**Files:**

- Create: `lib/statistics.py`
- Create: `tests/lib/test_statistics.py`
- Reference: `quick_benchmark_95.py:435-500` (compute_statistical_metrics)
- Reference: `feed_readiness.py:152-184` (\_distribution_stats)

**Step 1: Write the failing test**

```python
# tests/lib/test_statistics.py
"""Tests for lib.statistics — statistical computations."""

import math
import pytest
from lib.statistics import compute_statistical_metrics, distribution_stats


class TestComputeStatisticalMetrics:
    def test_identical_values(self):
        """Zero differences should produce zero stats."""
        diffs = [0.0] * 100
        pct_diffs = [0.0] * 100
        result = compute_statistical_metrics(diffs, pct_diffs)
        assert result["mean_diff"] == 0.0
        assert result["mae"] == 0.0

    def test_known_values(self):
        """Verify with hand-calculated inputs."""
        diffs = [1.0, -1.0, 2.0, -2.0, 0.5]
        pct_diffs = [0.1, -0.1, 0.2, -0.2, 0.05]
        result = compute_statistical_metrics(diffs, pct_diffs)
        assert abs(result["mean_diff"] - 0.1) < 1e-9
        assert result["mae"] == pytest.approx(1.3, abs=0.01)

    def test_too_few_observations(self):
        """Below min_observations, t-test and Wilcoxon should be None."""
        diffs = [1.0, 2.0]
        pct_diffs = [0.01, 0.02]
        result = compute_statistical_metrics(diffs, pct_diffs, min_observations=20)
        assert result["t_statistic"] is None
        assert result["wilcoxon_statistic"] is None

    def test_infinite_values_handled(self):
        """Publisher 71 edge case: infinite t_statistic."""
        diffs = [0.0] * 50  # All identical → std=0 → t_stat=inf
        pct_diffs = [0.0] * 50
        result = compute_statistical_metrics(diffs, pct_diffs, min_observations=20)
        # Should not raise; inf is acceptable


class TestDistributionStats:
    def test_empty_list(self):
        result = distribution_stats([])
        assert result["median"] is None
        assert result["mean"] is None

    def test_single_value(self):
        result = distribution_stats([42.0])
        assert result["median"] == 42.0
        assert result["mean"] == 42.0
        assert result["min"] == 42.0
        assert result["max"] == 42.0

    def test_known_distribution(self):
        values = list(range(1, 101))  # 1 to 100
        result = distribution_stats(values)
        assert result["median"] == pytest.approx(50.5)
        assert result["mean"] == pytest.approx(50.5)
        assert result["min"] == 1
        assert result["max"] == 100
        assert result["p90"] is not None
        assert result["p95"] is not None
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/lib/test_statistics.py -v`
Expected: FAIL

**Step 3: Implement `lib/statistics.py`**

Extract from:

- `quick_benchmark_95.py:435-500` — `compute_statistical_metrics()`
- `feed_readiness.py:152-184` — `_distribution_stats()` (rename to `distribution_stats()`, drop leading underscore since it's now a public API)

**Step 4: Run test to verify it passes**

Run: `pytest tests/lib/test_statistics.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add lib/statistics.py tests/lib/test_statistics.py
git commit -m "feat(lib): extract statistical computation functions"
```

---

### Task 2.2: Add `--hit-rate-threshold` Parameter

**Files:**

- Modify: `quick_benchmark.py` — add `--hit-rate-threshold` argparse argument, pass to evaluation functions
- Modify: `publisher_benchmark.py` — same

**Step 1: Add the CLI argument to both scripts**

In the argparse section of each script, add:

```python
parser.add_argument(
    "--hit-rate-threshold",
    type=float,
    default=95,
    help="Hit rate pass threshold (default: 95). Use 98 for strict mode.",
)
```

**Step 2: Thread the threshold through evaluation functions**

Replace all hardcoded `hit_rate >= 98` and `hit_rate >= 95` with `hit_rate >= args.hit_rate_threshold`. This is a find-and-replace within each script.

Locations in quick_benchmark.py (approximate — verify exact lines):

- Line ~650: regular session pass logic
- Line ~869: extended hours pass logic
- Line ~1131: another regular session check
- Line ~1393, ~1638, ~1698, ~1748: per-session checks

Same pattern in publisher_benchmark.py.

**Step 3: Verify both threshold values work**

Run: `python3 quick_benchmark.py --help | grep hit-rate`
Expected: Shows the argument with default 95

**Step 4: Commit**

```bash
git add quick_benchmark.py publisher_benchmark.py
git commit -m "feat: add --hit-rate-threshold CLI parameter to benchmark scripts"
```

---

### Task 2.3: Delete \_95 Variant Files

**Files:**

- Delete: `quick_benchmark_95.py`
- Delete: `publisher_benchmark_95.py`
- Modify: `feed_readiness.py` — change imports from `quick_benchmark_95` to `quick_benchmark`
- Modify: `publisher_report.py` — change imports from `publisher_benchmark_95` to `publisher_benchmark`

**Step 1: Update feed_readiness.py imports**

Replace:

```python
from quick_benchmark_95 import (
```

With:

```python
from quick_benchmark import (
```

**Step 2: Update publisher_report.py imports**

Replace:

```python
from publisher_benchmark_95 import (
```

With:

```python
from publisher_benchmark import (
```

**Step 3: Delete the \_95 files**

```bash
git rm quick_benchmark_95.py publisher_benchmark_95.py
```

**Step 4: Verify**

Run: `python3 feed_readiness.py --help`
Expected: Works without error

Run: `python3 publisher_report.py --help`
Expected: Works without error

Run: `pytest tests/ -v`
Expected: All PASS (update any test imports if they reference \_95 files)

**Step 5: Commit**

```bash
git add feed_readiness.py publisher_report.py
git commit -m "refactor: merge _95 variants via --hit-rate-threshold, delete duplicates"
```

---

### Task 2.4: Golden-File Verification (Phase 2)

Run the same test feeds as Phase 1 with `--hit-rate-threshold 95` and `--hit-rate-threshold 98`. Compare to golden files from the original \_95 and non-\_95 scripts. Output must be byte-identical.

---

## Phase 3: Extract Core Logic + Per-Session Thresholds

### Task 3.1: Create `lib/thresholds.py`

**Files:**

- Create: `lib/thresholds.py`
- Create: `tests/lib/test_thresholds.py`

This is the **new per-session threshold feature**. It defines session-aware pass/fail thresholds for US Equities.

**Step 1: Write the failing test**

```python
# tests/lib/test_thresholds.py
"""Tests for lib.thresholds — per-session pass/fail thresholds."""

import pytest
from lib.thresholds import (
    SessionThresholds,
    get_session_thresholds,
    passes_benchmark,
    REGULAR_THRESHOLDS,
    EXTENDED_THRESHOLDS,
)


class TestSessionThresholds:
    def test_regular_thresholds(self):
        t = REGULAR_THRESHOLDS
        assert t.nrmse_auto_pass == 0.01
        assert t.nrmse_conditional == 0.05
        assert t.hit_rate_threshold == 95

    def test_extended_thresholds(self):
        t = EXTENDED_THRESHOLDS
        assert t.nrmse_auto_pass == 0.05
        assert t.nrmse_conditional == 0.15
        assert t.hit_rate_threshold == 85


class TestGetSessionThresholds:
    def test_regular_us_equities(self):
        t = get_session_thresholds("regular", "us-equities")
        assert t.hit_rate_threshold == 95

    def test_premarket_us_equities(self):
        t = get_session_thresholds("premarket", "us-equities")
        assert t.hit_rate_threshold == 85
        assert t.nrmse_auto_pass == 0.05
        assert t.nrmse_conditional == 0.15

    def test_afterhours_us_equities(self):
        t = get_session_thresholds("afterhours", "us-equities")
        assert t.hit_rate_threshold == 85

    def test_overnight_us_equities(self):
        t = get_session_thresholds("overnight", "us-equities")
        assert t.hit_rate_threshold == 85

    def test_fx_always_regular(self):
        """Non-US-equity asset classes always get regular thresholds."""
        t = get_session_thresholds("premarket", "fx")
        assert t.hit_rate_threshold == 95
        assert t.nrmse_auto_pass == 0.01

    def test_metals_always_regular(self):
        t = get_session_thresholds("afterhours", "metals")
        assert t.hit_rate_threshold == 95

    def test_custom_hit_rate_override(self):
        """CLI --hit-rate-threshold overrides regular session hit rate."""
        t = get_session_thresholds("regular", "us-equities", hit_rate_override=98)
        assert t.hit_rate_threshold == 98

    def test_custom_hit_rate_does_not_affect_extended(self):
        """Extended session thresholds are fixed, not overridden by CLI."""
        t = get_session_thresholds("premarket", "us-equities", hit_rate_override=98)
        assert t.hit_rate_threshold == 85


class TestPassesBenchmark:
    # --- Regular session (strict thresholds) ---
    def test_auto_pass_very_low_nrmse(self):
        assert passes_benchmark(nrmse=0.005, hit_rate=50.0, session="regular", mode="us-equities") is True

    def test_conditional_pass(self):
        assert passes_benchmark(nrmse=0.03, hit_rate=96.0, session="regular", mode="us-equities") is True

    def test_conditional_fail_low_hit_rate(self):
        assert passes_benchmark(nrmse=0.03, hit_rate=90.0, session="regular", mode="us-equities") is False

    def test_fail_high_nrmse(self):
        assert passes_benchmark(nrmse=0.06, hit_rate=99.0, session="regular", mode="us-equities") is False

    # --- Extended session (relaxed thresholds) ---
    def test_premarket_auto_pass(self):
        """NRMSE < 0.05 auto-passes in extended hours."""
        assert passes_benchmark(nrmse=0.04, hit_rate=50.0, session="premarket", mode="us-equities") is True

    def test_premarket_conditional_pass(self):
        """NRMSE < 0.15 + hit_rate >= 85 passes in extended hours."""
        assert passes_benchmark(nrmse=0.10, hit_rate=87.0, session="premarket", mode="us-equities") is True

    def test_premarket_conditional_fail(self):
        """NRMSE < 0.15 but hit_rate < 85 fails in extended hours."""
        assert passes_benchmark(nrmse=0.10, hit_rate=80.0, session="premarket", mode="us-equities") is False

    def test_premarket_fail_high_nrmse(self):
        """NRMSE >= 0.15 fails even with high hit rate."""
        assert passes_benchmark(nrmse=0.16, hit_rate=99.0, session="premarket", mode="us-equities") is False

    def test_overnight_uses_extended(self):
        assert passes_benchmark(nrmse=0.10, hit_rate=87.0, session="overnight", mode="us-equities") is True

    def test_afterhours_uses_extended(self):
        assert passes_benchmark(nrmse=0.10, hit_rate=87.0, session="afterhours", mode="us-equities") is True

    # --- Non-US-equity: always regular thresholds ---
    def test_fx_premarket_uses_regular(self):
        """FX doesn't get relaxed thresholds even if session is 'premarket'."""
        assert passes_benchmark(nrmse=0.04, hit_rate=50.0, session="premarket", mode="fx") is False

    # --- Edge cases ---
    def test_nrmse_none_fails(self):
        assert passes_benchmark(nrmse=None, hit_rate=99.0, session="regular", mode="us-equities") is False

    def test_boundary_nrmse_0_01_regular(self):
        """NRMSE exactly at 0.01 does NOT auto-pass (strict <)."""
        assert passes_benchmark(nrmse=0.01, hit_rate=50.0, session="regular", mode="us-equities") is False

    def test_boundary_nrmse_0_05_extended(self):
        """NRMSE exactly at 0.05 does NOT auto-pass in extended (strict <)."""
        assert passes_benchmark(nrmse=0.05, hit_rate=50.0, session="premarket", mode="us-equities") is False

    def test_boundary_hit_rate_85_extended(self):
        """Hit rate exactly 85 PASSES in extended (>=)."""
        assert passes_benchmark(nrmse=0.10, hit_rate=85.0, session="premarket", mode="us-equities") is True

    def test_boundary_hit_rate_95_regular(self):
        """Hit rate exactly 95 PASSES in regular (>=)."""
        assert passes_benchmark(nrmse=0.03, hit_rate=95.0, session="regular", mode="us-equities") is True
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/lib/test_thresholds.py -v`
Expected: FAIL

**Step 3: Implement `lib/thresholds.py`**

```python
# lib/thresholds.py
"""Per-session pass/fail thresholds for benchmark evaluation.

US Equities extended hours (pre-market, after-hours, overnight) use
relaxed thresholds due to lower liquidity and wider spreads.
All other asset classes use regular thresholds regardless of session.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SessionThresholds:
    """Pass/fail thresholds for a benchmark session."""

    nrmse_auto_pass: float  # NRMSE below this = automatic pass
    nrmse_conditional: float  # NRMSE below this + hit_rate >= threshold = pass
    hit_rate_threshold: float  # Hit rate must be >= this for conditional pass


# Default thresholds (regular session, all asset classes)
REGULAR_THRESHOLDS = SessionThresholds(
    nrmse_auto_pass=0.01,
    nrmse_conditional=0.05,
    hit_rate_threshold=95,
)

# Relaxed thresholds (extended hours, US equities only)
EXTENDED_THRESHOLDS = SessionThresholds(
    nrmse_auto_pass=0.05,
    nrmse_conditional=0.15,
    hit_rate_threshold=85,
)

# Sessions that use extended thresholds for US equities
_EXTENDED_SESSIONS = {"premarket", "afterhours", "overnight"}


def get_session_thresholds(
    session: str,
    mode: str,
    hit_rate_override: Optional[float] = None,
) -> SessionThresholds:
    """Look up the correct thresholds for a session + asset class.

    Args:
        session: "regular", "premarket", "afterhours", or "overnight"
        mode: Normalized asset class (e.g. "us-equities", "fx")
        hit_rate_override: CLI override for regular session hit rate threshold.
            Only applies to regular sessions. Extended sessions always use 85%.

    Returns:
        SessionThresholds with the correct pass/fail values.
    """
    is_us_equities = mode in ("us-equities", "equity-us")

    if is_us_equities and session in _EXTENDED_SESSIONS:
        return EXTENDED_THRESHOLDS

    if hit_rate_override is not None:
        return SessionThresholds(
            nrmse_auto_pass=REGULAR_THRESHOLDS.nrmse_auto_pass,
            nrmse_conditional=REGULAR_THRESHOLDS.nrmse_conditional,
            hit_rate_threshold=hit_rate_override,
        )

    return REGULAR_THRESHOLDS


def passes_benchmark(
    nrmse: Optional[float],
    hit_rate: float,
    session: str = "regular",
    mode: str = "us-equities",
    hit_rate_override: Optional[float] = None,
) -> bool:
    """Evaluate whether a publisher passes the benchmark for a given session.

    Args:
        nrmse: Normalized RMSE value (None = insufficient data = fail).
        hit_rate: Percentage of observations within 10 basis points.
        session: "regular", "premarket", "afterhours", or "overnight".
        mode: Normalized asset class.
        hit_rate_override: CLI override for regular session hit rate.

    Returns:
        True if the publisher passes.
    """
    if nrmse is None:
        return False

    t = get_session_thresholds(session, mode, hit_rate_override)
    return nrmse < t.nrmse_auto_pass or (
        nrmse < t.nrmse_conditional and hit_rate >= t.hit_rate_threshold
    )
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/lib/test_thresholds.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add lib/thresholds.py tests/lib/test_thresholds.py
git commit -m "feat(lib): add per-session pass/fail thresholds for US equities extended hours"
```

---

### Task 3.2: Extract `lib/benchmark_core.py`

**Files:**

- Create: `lib/benchmark_core.py`
- Create: `tests/lib/test_benchmark_core.py`
- Reference: `quick_benchmark_95.py:500-900` (evaluate_session_for_all_publishers, evaluate_feed_two_queries)
- Reference: `quick_benchmark_95.py:1100-1800` (extended hours and overnight evaluation)

**Step 1: Write the failing test**

Tests should use mocked ClickHouse clients. Focus on:

- `passes_benchmark` is called with correct session type
- Regular session uses strict thresholds
- Extended sessions use relaxed thresholds
- The function returns correct `PublisherFeedMetrics` and `BenchmarkResult`

```python
# tests/lib/test_benchmark_core.py
"""Tests for lib.benchmark_core — core benchmark evaluation."""

import pytest
from unittest.mock import MagicMock
from lib.thresholds import passes_benchmark


class TestPassesBenchmarkIntegration:
    """Verify passes_benchmark is used correctly in evaluation flow."""

    def test_regular_session_strict_threshold(self):
        # NRMSE 0.03 + hit_rate 94% should FAIL regular (needs 95%)
        assert passes_benchmark(0.03, 94.0, "regular", "us-equities") is False

    def test_premarket_relaxed_threshold(self):
        # Same values should PASS pre-market (needs 85%)
        assert passes_benchmark(0.03, 94.0, "premarket", "us-equities") is True

    def test_afterhours_high_nrmse_passes(self):
        # NRMSE 0.10 + hit_rate 90% should PASS after-hours (nrmse < 0.15, hr >= 85)
        assert passes_benchmark(0.10, 90.0, "afterhours", "us-equities") is True

    def test_regular_high_nrmse_fails(self):
        # NRMSE 0.10 should FAIL regular (nrmse >= 0.05)
        assert passes_benchmark(0.10, 90.0, "regular", "us-equities") is False
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/lib/test_benchmark_core.py -v`
Expected: FAIL (or PASS if only using passes_benchmark — adjust to test actual extraction)

**Step 3: Implement `lib/benchmark_core.py`**

Extract the core evaluation functions from `quick_benchmark.py`:

- `evaluate_session_for_all_publishers()` — the main benchmark evaluation function
- `evaluate_extended_session()` — pre-market / after-hours evaluation
- `evaluate_overnight_session()` — overnight evaluation
- Helper functions used by these

Replace all inline `passes = nrmse < 0.01 or (nrmse < 0.05 and hit_rate >= 95)` with calls to `passes_benchmark()` from `lib/thresholds.py`, passing the correct `session` and `mode` parameters.

This is the largest extraction. Target: ~400 lines. If it exceeds 400, split into `benchmark_regular.py` and `benchmark_extended.py`.

**Step 4: Run test to verify it passes**

Run: `pytest tests/lib/test_benchmark_core.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add lib/benchmark_core.py tests/lib/test_benchmark_core.py
git commit -m "feat(lib): extract core benchmark evaluation with session-aware thresholds"
```

---

### Task 3.3: Extract `lib/uptime_core.py`

**Files:**

- Create: `lib/uptime_core.py`
- Create: `tests/lib/test_uptime_core.py`
- Reference: `feed_uptime.py:100-400` (evaluate_feed_uptime, session uptime, gap detection)

**Step 1: Write the failing test**

Test with mocked ClickHouse client. Verify:

- Uptime calculation logic
- Gap detection
- Pass/fail based on uptime threshold

**Step 2: Run test to verify it fails**

Run: `pytest tests/lib/test_uptime_core.py -v`
Expected: FAIL

**Step 3: Implement `lib/uptime_core.py`**

Extract from `feed_uptime.py`:

- Core uptime evaluation functions
- Gap detection logic
- Session window computation

`feed_uptime.py` becomes a thin CLI wrapper.

**Step 4: Run test to verify it passes**

Run: `pytest tests/lib/test_uptime_core.py -v`
Expected: All PASS

**Step 5: Commit**

```bash
git add lib/uptime_core.py tests/lib/test_uptime_core.py
git commit -m "feat(lib): extract core uptime evaluation logic"
```

---

### Task 3.4: Slim Down Scripts to Thin Wrappers

**Files:**

- Modify: `quick_benchmark.py` — replace evaluation logic with calls to `lib/benchmark_core`
- Modify: `publisher_benchmark.py` — same
- Modify: `feed_readiness.py` — import from `lib/` instead of `quick_benchmark`
- Modify: `publisher_report.py` — import from `lib/` instead of `publisher_benchmark`
- Modify: `feed_uptime.py` — replace evaluation logic with calls to `lib/uptime_core`

Each script should become:

1. Argparse setup
2. CSV processing / input handling
3. Calls to `lib/` functions
4. Output formatting

Target: each script < 400 lines.

**Step 1: Refactor each script**

Work one script at a time. After each script:

- Run `python3 <script>.py --help` to verify it works
- Run `pytest tests/ -v` to verify existing tests pass

**Step 2: Verify all scripts under 400 lines**

Run: `wc -l quick_benchmark.py publisher_benchmark.py feed_readiness.py publisher_report.py feed_uptime.py verify_uptime.py`
Expected: All < 400

**Step 3: Commit**

```bash
git add quick_benchmark.py publisher_benchmark.py feed_readiness.py publisher_report.py feed_uptime.py
git commit -m "refactor: slim scripts to thin CLI wrappers over lib/"
```

---

### Task 3.5: Golden-File Verification (Phase 3)

Run all test feeds with both regular and extended hours. This is the critical verification because:

1. Extended hours output should now show different pass/fail results where the relaxed thresholds make a difference
2. Regular hours output must be identical to pre-refactoring

For US equity feeds with `--extended-hours`:

- Pre-market and after-hours columns should reflect the new 85%/0.15 thresholds
- A publisher with NRMSE=0.10 and hit_rate=87% should now PASS in pre-market (previously FAILED)

For non-US-equity feeds:

- Output must be byte-identical to pre-refactoring

---

## Phase 4: Extract Output Helpers and Final Cleanup

### Task 4.1: Extract `lib/csv_output.py`

**Files:**

- Create: `lib/csv_output.py`
- Create: `tests/lib/test_csv_output.py`
- Reference: CSV writing sections in each script (look for `csv.writer`, `csv.DictWriter`)

**Step 1: Write the failing test**

Test CSV output format correctness: headers, field order, quoting, special characters.

**Step 2: Implement `lib/csv_output.py`**

Extract shared CSV/console output helpers. Each script has similar output patterns — consolidate into reusable functions.

**Step 3: Run tests and commit**

```bash
git add lib/csv_output.py tests/lib/test_csv_output.py
git commit -m "feat(lib): extract CSV/console output helpers"
```

---

### Task 4.2: Dead Code Removal

**Files:**

- Audit all scripts for:
  - Unused imports
  - Unreachable code
  - Commented-out blocks
  - Functions that were extracted but not deleted

**Step 1: Run analysis**

```bash
# Check for unused imports
source venv/bin/activate && python3 -m py_compile quick_benchmark.py
# Repeat for each script
```

**Step 2: Remove dead code and commit**

```bash
git add -u
git commit -m "chore: remove dead code after lib/ extraction"
```

---

### Task 4.3: Final Audit and Documentation

**Files:**

- Modify: `CLAUDE.md` — update pass/fail criteria to mention per-session thresholds
- Modify: `docs/benchmark_results_guide.md` — add section on extended hours thresholds
- Modify: `docs/quick_benchmark.md`, `docs/feed_readiness.md` — document `--hit-rate-threshold` flag

**Step 1: Verify all files under 400 lines**

```bash
wc -l *.py lib/*.py
```

**Step 2: Import smoke test**

```bash
python3 -c "from lib import config, models, sql_filters, statistics, thresholds, benchmark_core, uptime_core, csv_output; print('all imports ok')"
```

**Step 3: Full test suite**

```bash
pytest tests/ -v
```

**Step 4: Pre-commit**

```bash
pre-commit run --all-files
```

**Step 5: Update CLAUDE.md pass/fail criteria**

Add to the Pass/Fail Criteria section:

```markdown
### Per-Session Thresholds (US Equities)

| Session                         | Auto-Pass (NRMSE) | Conditional NRMSE | Hit Rate |
| ------------------------------- | ----------------- | ----------------- | -------- |
| Regular (9:30 AM – 4:00 PM)     | < 0.01            | < 0.05            | >= 95%   |
| Pre-Market (4:00 AM – 9:30 AM)  | < 0.05            | < 0.15            | >= 85%   |
| After-Hours (4:00 PM – 8:00 PM) | < 0.05            | < 0.15            | >= 85%   |
| Overnight (8:00 PM – 4:00 AM)   | < 0.05            | < 0.15            | >= 85%   |

Non-US-equity asset classes (FX, metals, commodities, treasuries) always use regular thresholds.
```

**Step 6: Commit**

```bash
git add CLAUDE.md docs/
git commit -m "docs: update pass/fail criteria with per-session thresholds"
```

---

## Summary

| Phase | Tasks   | Key Deliverables                                                                            |
| ----- | ------- | ------------------------------------------------------------------------------------------- |
| 1     | 1.1–1.6 | `lib/config.py`, `lib/models.py`, `lib/sql_filters.py` + tests                              |
| 2     | 2.1–2.4 | `lib/statistics.py`, `--hit-rate-threshold` flag, delete `_95` files                        |
| 3     | 3.1–3.5 | `lib/thresholds.py`, `lib/benchmark_core.py`, `lib/uptime_core.py` + per-session thresholds |
| 4     | 4.1–4.3 | `lib/csv_output.py`, dead code removal, docs update                                         |

**Total new files:** 8 lib modules + 8 test files
**Total deleted files:** 2 (\_95 variants) + possible dead code
**New feature:** Per-session relaxed thresholds for US Equities extended hours
