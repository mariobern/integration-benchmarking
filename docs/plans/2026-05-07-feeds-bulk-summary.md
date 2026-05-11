# Feeds Bulk Summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `summarize_feeds.py` — a single Excel workbook generator that reads `evaluate_feeds_bulk.py`'s `dq_reports` tree and emits two sheets per run: ranked top-10 publishers per (feed, mode) and paste-ready `allowedPublisherIds` JSON arrays per feed/session.

**Architecture:** New module + tests, no edits to existing scripts. `main()` parses CLI args → `discover_feeds()` reads CSV → for each feed×mode: `load_stats()` reads `dq_reports/.../stats.csv`, `rank_top_n()` produces the rankings list, `apply_filter()` produces the allowed list with fallback. `compute_aggregate()` merges per-session arrays. `write_rankings_sheet()` and `write_allowed_sheet()` populate the workbook via openpyxl. Per-feed/per-mode failures (missing files, malformed rows) never abort the run.

**Tech Stack:** Python 3 (stdlib `argparse`, `csv`, `json`, `pathlib`, `re`, `sys`), `openpyxl` (NEW dep), pytest 7.4.4, `unittest.mock` (stdlib).

**Spec:** [`docs/superpowers/specs/2026-05-07-feeds-bulk-summary-design.md`](../specs/2026-05-07-feeds-bulk-summary-design.md)

---

## File Structure

```
pythresearch/data_quality/lazer/
├── summarize_feeds.py                (NEW — summary generator)
├── evaluate_feeds_bulk.py            (UNTOUCHED — bulk runner)
├── evaluate_feeds.py                 (UNTOUCHED — papermill loop)
├── evaluate_feed_standalone.py       (UNTOUCHED — engine)
└── tests/
    ├── __init__.py                   (EXISTING — already a package)
    ├── test_evaluate_feeds_bulk.py   (UNTOUCHED — bulk runner tests)
    └── test_summarize_feeds.py       (NEW — pytest suite)
requirements.in                       (MODIFY — add openpyxl)
requirements.txt                      (REGENERATE via pip-compile)
```

**Module responsibilities (summarize_feeds.py):**

| Function                                                                                | Purpose                                                           |
| --------------------------------------------------------------------------------------- | ----------------------------------------------------------------- |
| `load_excluded_publishers(path) -> set[int]`                                            | Parse markdown table, extract IDs ending in `.Test` + always 0.   |
| `discover_feeds(csv_path) -> list[int]`                                                 | Distinct numeric feed_ids from CSV column 1, in first-seen order. |
| `load_stats(reports_dir, cluster, mode, feed_id, date) -> list[dict] \| None`           | Read stats.csv, return None if missing.                           |
| `rank_top_n(stats, n, excluded) -> list[dict]`                                          | Drop excluded, sort by rmse_over_spread, take top n.              |
| `apply_filter(stats, max_ros, min_hit, min_obs, fallback_n) -> tuple[list[dict], bool]` | Threshold filter with fallback flag.                              |
| `compute_aggregate(per_session_arrays) -> list[int]`                                    | Sorted union of session arrays.                                   |
| `write_rankings_sheet(ws, per_feed_data, date, cluster)`                                | Populate sheet 1.                                                 |
| `write_allowed_sheet(ws, per_feed_data, skipped_feeds, date, cluster)`                  | Populate sheet 2.                                                 |
| `main()`                                                                                | argparse → glue → workbook write → stdout summary.                |

---

## Test Run Commands

From repo root `/home/mariobern/research`:

```bash
# Run all tests in this module
pytest pythresearch/data_quality/lazer/tests/test_summarize_feeds.py -v

# Run a single test
pytest pythresearch/data_quality/lazer/tests/test_summarize_feeds.py::test_NAME -v

# Coverage report
pytest pythresearch/data_quality/lazer/tests/test_summarize_feeds.py \
    --cov=pythresearch.data_quality.lazer.summarize_feeds \
    --cov-report=term-missing
```

---

## Task 1: Add openpyxl dependency

**Files:**

- Modify: `requirements.in`
- Regenerate: `requirements.txt`

- [ ] **Step 1: Add openpyxl to requirements.in**

Open `requirements.in` and append `openpyxl` on its own line (alphabetically near other top-level deps if the file is sorted, otherwise at the end).

- [ ] **Step 2: Recompile requirements.txt**

Run: `pip-compile requirements.in`
Expected: `requirements.txt` updated; new line for `openpyxl==X.Y.Z` and possibly `et-xmlfile` (its only dep).

If `pip-compile` is not installed, run: `pip install pip-tools` first.

- [ ] **Step 3: Install the new dependency locally**

Run: `pip install openpyxl`
Expected: success, no version conflict warnings.

- [ ] **Step 4: Verify importable**

Run: `python3 -c "import openpyxl; print(openpyxl.__version__)"`
Expected: prints version (e.g., `3.1.5`).

- [ ] **Step 5: Commit**

```bash
git add requirements.in requirements.txt
git commit -m "chore: add openpyxl for DQ summary workbook generation"
```

---

## Task 2: Module skeleton with constants

**Files:**

- Create: `pythresearch/data_quality/lazer/summarize_feeds.py`

- [ ] **Step 1: Create the skeleton with module-level constants**

Create `pythresearch/data_quality/lazer/summarize_feeds.py`:

```python
#!/usr/bin/env python3
"""DQ summary workbook generator — reads dq_reports/, emits one .xlsx.

Two sheets per run:
  rankings — top-N publishers per (feed, mode) by rmse_over_spread, modes side-by-side
  allowed  — paste-ready allowedPublisherIds JSON arrays per feed/session

Run:
    python3 -m pythresearch.data_quality.lazer.summarize_feeds \\
        --csv MV_Mario_3_pre.csv --cluster lazer-prod --date 2026-05-06
"""
import argparse
import csv as csv_mod
import json
import re
import sys
from pathlib import Path

# Mode → after.json session-label mapping.
MODE_TO_SESSION = {
    "us-equities": "REGULAR",
    "us-equities-pre": "PRE_MARKET",
    "us-equities-post": "POST_MARKET",
    "us-equities-overnight": "OVER_NIGHT",
}

# Stable mode order for both sheets.
MODE_ORDER = [
    "us-equities",
    "us-equities-pre",
    "us-equities-post",
    "us-equities-overnight",
]

# Default per-mode thresholds (CLI flags override).
DEFAULT_MAX_ROS = {
    "us-equities": 1.0,
    "us-equities-pre": 2.0,
    "us-equities-post": 2.0,
    "us-equities-overnight": 3.0,
}
DEFAULT_MIN_HIT = {
    "us-equities": 80.0,
    "us-equities-pre": 50.0,
    "us-equities-post": 50.0,
    "us-equities-overnight": 25.0,
}
DEFAULT_MIN_N_OBS = 1000
DEFAULT_TOP_N = 10
DEFAULT_FALLBACK_TOP = 3
```

- [ ] **Step 2: Verify the module imports cleanly**

Run: `python3 -c "from pythresearch.data_quality.lazer import summarize_feeds; print(summarize_feeds.MODE_ORDER)"`
Expected: prints `['us-equities', 'us-equities-pre', 'us-equities-post', 'us-equities-overnight']`.

- [ ] **Step 3: Commit**

```bash
git add pythresearch/data_quality/lazer/summarize_feeds.py
git commit -m "feat: scaffold summarize_feeds module with mode constants"
```

---

## Task 3: TDD `load_excluded_publishers`

**Files:**

- Create: `pythresearch/data_quality/lazer/tests/test_summarize_feeds.py`
- Modify: `pythresearch/data_quality/lazer/summarize_feeds.py`

- [ ] **Step 1: Write failing tests**

Create `pythresearch/data_quality/lazer/tests/test_summarize_feeds.py`:

```python
"""Unit + integration tests for summarize_feeds."""
from pathlib import Path

import pytest

from pythresearch.data_quality.lazer.summarize_feeds import (
    load_excluded_publishers,
)


# ---------- load_excluded_publishers ----------

def _write_publishers_md(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "publishers.md"
    p.write_text(body)
    return p


def test_load_excluded_publishers_extracts_dot_test_and_zero(tmp_path):
    md = _write_publishers_md(tmp_path, """\
# Publisher IDs and Names
| ID  | Name                  | Active |
| --- | --------------------- | ------ |
| 1   | Lazer.Binance         | Yes    |
| 23  | LoTech.Test           | Yes    |
| 25  | CharlesworthResearch.Test | Yes |
| 26  | CharlesworthResearch.Production | Yes |
""")
    assert load_excluded_publishers(md) == {0, 23, 25}


def test_load_excluded_publishers_always_includes_zero_even_if_empty_md(tmp_path):
    md = _write_publishers_md(tmp_path, "# empty\n")
    assert load_excluded_publishers(md) == {0}


def test_load_excluded_publishers_handles_malformed_row(tmp_path):
    md = _write_publishers_md(tmp_path, """\
| ID  | Name        | Active |
| --- | ----------- | ------ |
| abc | Bad.Test    | Yes    |
| 27  | MEMX.Test   | Yes    |
""")
    # Malformed ID row skipped, valid one parsed.
    assert load_excluded_publishers(md) == {0, 27}


def test_load_excluded_publishers_ignores_production_publishers(tmp_path):
    md = _write_publishers_md(tmp_path, """\
| ID  | Name              | Active |
| --- | ----------------- | ------ |
| 1   | Lazer.Binance     | Yes    |
| 2   | Jump.Production   | Yes    |
""")
    assert load_excluded_publishers(md) == {0}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest pythresearch/data_quality/lazer/tests/test_summarize_feeds.py -v`
Expected: ImportError on `load_excluded_publishers` or 4 failures.

- [ ] **Step 3: Implement `load_excluded_publishers`**

Append to `pythresearch/data_quality/lazer/summarize_feeds.py`:

```python
def load_excluded_publishers(publishers_md_path) -> set[int]:
    """Parse publishers.md markdown table, return IDs to exclude.

    Excluded = {0} ∪ {ids whose Name ends with ".Test"}.
    Malformed rows are skipped silently. Always includes 0 even if file is empty.
    """
    excluded: set[int] = {0}
    with open(publishers_md_path, "r") as f:
        for line in f:
            line = line.strip()
            if not line.startswith("|"):
                continue
            # Strip leading/trailing pipes, split on | and trim each cell.
            parts = [p.strip() for p in line.strip("|").split("|")]
            if len(parts) < 2:
                continue
            try:
                pub_id = int(parts[0])
            except ValueError:
                # Header row ("ID"), separator row ("---"), or malformed; skip.
                continue
            name = parts[1]
            if name.endswith(".Test"):
                excluded.add(pub_id)
    return excluded
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest pythresearch/data_quality/lazer/tests/test_summarize_feeds.py -v -k load_excluded`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add pythresearch/data_quality/lazer/summarize_feeds.py pythresearch/data_quality/lazer/tests/test_summarize_feeds.py
git commit -m "feat: add load_excluded_publishers parser for .Test exclusion"
```

---

## Task 4: TDD `discover_feeds`

**Files:**

- Modify: `pythresearch/data_quality/lazer/tests/test_summarize_feeds.py`
- Modify: `pythresearch/data_quality/lazer/summarize_feeds.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_summarize_feeds.py`:

```python
from pythresearch.data_quality.lazer.summarize_feeds import discover_feeds


# ---------- discover_feeds ----------

def test_discover_feeds_returns_distinct_feed_ids_from_csv(tmp_path):
    csv = tmp_path / "input.csv"
    csv.write_text(
        "1021, 2026-05-06, us-equities-pre\n"
        "1060, 2026-05-06, us-equities-pre\n"
        "1021, 2026-05-06, us-equities-post\n"  # duplicate feed_id
        "922, 2026-05-06, us-equities\n"
    )
    assert discover_feeds(csv) == [1021, 1060, 922]


def test_discover_feeds_skips_malformed_rows(tmp_path, capsys):
    csv = tmp_path / "input.csv"
    csv.write_text(
        "1021, 2026-05-06, us-equities-pre\n"
        "\n"                                 # blank line
        ", , \n"                             # empty fields
        "abc, 2026-05-06, us-equities\n"     # non-numeric feed_id
        "1060, 2026-05-06, us-equities\n"
    )
    assert discover_feeds(csv) == [1021, 1060]
    out = capsys.readouterr().out
    assert "abc" in out  # warning emitted


def test_discover_feeds_preserves_first_seen_order(tmp_path):
    csv = tmp_path / "input.csv"
    csv.write_text("3, x, y\n1, x, y\n2, x, y\n3, x, y\n1, x, y\n")
    assert discover_feeds(csv) == [3, 1, 2]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest pythresearch/data_quality/lazer/tests/test_summarize_feeds.py -v -k discover_feeds`
Expected: ImportError or 3 failures.

- [ ] **Step 3: Implement `discover_feeds`**

Append to `summarize_feeds.py`:

```python
def discover_feeds(csv_path) -> list[int]:
    """Distinct numeric feed_ids from CSV column 1, in first-seen order.

    Empty rows, rows with empty first column, and rows with non-numeric
    feed_ids are skipped with a stdout warning.
    """
    seen: list[int] = []
    seen_set: set[int] = set()
    with open(csv_path, "r") as f:
        reader = csv_mod.reader(f)
        for row in reader:
            if not row or not row[0].strip():
                continue
            raw = row[0].strip()
            try:
                feed_id = int(raw)
            except ValueError:
                print(f"  Warning: skipping malformed CSV row (non-numeric feed_id): {raw!r}")
                continue
            if feed_id not in seen_set:
                seen.append(feed_id)
                seen_set.add(feed_id)
    return seen
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest pythresearch/data_quality/lazer/tests/test_summarize_feeds.py -v -k discover_feeds`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add pythresearch/data_quality/lazer/summarize_feeds.py pythresearch/data_quality/lazer/tests/test_summarize_feeds.py
git commit -m "feat: add discover_feeds CSV parser with malformed-row tolerance"
```

---

## Task 5: TDD `load_stats`

**Files:**

- Modify: `tests/test_summarize_feeds.py`
- Modify: `summarize_feeds.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_summarize_feeds.py`:

```python
from pythresearch.data_quality.lazer.summarize_feeds import load_stats


# ---------- load_stats ----------

STATS_HEADER = (
    "feed_id,publisher_id,n_observations,mean_diff,std_diff,mean_pct_diff,"
    "std_pct_diff,rmse,nrmse,rmse_over_spread,mae,t_statistic,t_pvalue,"
    "wilcoxon_statistic,wilcoxon_pvalue,normality_pvalue,hit_rate_0.1pct,"
    "mean_abs_z_score,pass_fail\n"
)


def _write_stats_csv(reports_dir: Path, cluster, mode, feed_id, date, body_rows):
    """Build dq_reports/<cluster>/<mode>/<feed_id>/<date>/stats.csv."""
    p = reports_dir / cluster / mode / str(feed_id) / date / "stats.csv"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(STATS_HEADER + "".join(body_rows))
    return p


def test_load_stats_returns_none_for_missing_file(tmp_path):
    assert load_stats(tmp_path, "lazer-prod", "us-equities", 1021, "2026-05-06") is None


def test_load_stats_parses_real_csv_format(tmp_path):
    _write_stats_csv(
        tmp_path, "lazer-prod", "us-equities-post", 1021, "2026-05-06",
        ["1021,11,22218,-0.05,0.08,-0.01,0.02,0.0932,0.51,0.0185,0.07,-84,0,75,0,0,100.0,0.96,fail\n"]
    )
    rows = load_stats(tmp_path, "lazer-prod", "us-equities-post", 1021, "2026-05-06")
    assert rows is not None
    assert len(rows) == 1
    assert rows[0]["publisher_id"] == "11"
    assert rows[0]["rmse_over_spread"] == "0.0185"
    assert rows[0]["hit_rate_0.1pct"] == "100.0"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest pythresearch/data_quality/lazer/tests/test_summarize_feeds.py -v -k load_stats`
Expected: ImportError or failures.

- [ ] **Step 3: Implement `load_stats`**

Append to `summarize_feeds.py`:

```python
def load_stats(reports_dir, cluster: str, mode: str, feed_id: int, date: str):
    """Read dq_reports/<cluster>/<mode>/<feed_id>/<date>/stats.csv.

    Returns a list of dicts (csv.DictReader output), or None if the file is missing.
    """
    path = Path(reports_dir) / cluster / mode / str(feed_id) / date / "stats.csv"
    if not path.exists():
        return None
    with open(path, "r") as f:
        return list(csv_mod.DictReader(f))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest pythresearch/data_quality/lazer/tests/test_summarize_feeds.py -v -k load_stats`
Expected: 2 PASS.

- [ ] **Step 5: Commit**

```bash
git add pythresearch/data_quality/lazer/summarize_feeds.py pythresearch/data_quality/lazer/tests/test_summarize_feeds.py
git commit -m "feat: add load_stats reader with missing-file None semantics"
```

---

## Task 6: TDD `rank_top_n`

**Files:**

- Modify: `tests/test_summarize_feeds.py`
- Modify: `summarize_feeds.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_summarize_feeds.py`:

```python
from pythresearch.data_quality.lazer.summarize_feeds import rank_top_n


# ---------- rank_top_n ----------

def _stat(publisher_id, ros, hit=80.0, n_obs=10000):
    """Helper: minimal stats.csv-style dict."""
    return {
        "publisher_id": str(publisher_id),
        "rmse_over_spread": str(ros),
        "hit_rate_0.1pct": str(hit),
        "n_observations": str(n_obs),
    }


def test_rank_top_n_sorts_ascending_by_rmse_over_spread():
    stats = [_stat(11, 0.5), _stat(20, 0.1), _stat(35, 0.3)]
    ranked = rank_top_n(stats, n=10, excluded=set())
    assert [r["publisher_id"] for r in ranked] == ["20", "35", "11"]


def test_rank_top_n_takes_top_n_only():
    stats = [_stat(i, i * 0.01) for i in range(20)]
    ranked = rank_top_n(stats, n=5, excluded=set())
    assert len(ranked) == 5
    assert [r["publisher_id"] for r in ranked] == ["0", "1", "2", "3", "4"]


def test_rank_top_n_excludes_excluded_publishers():
    stats = [_stat(11, 0.1), _stat(23, 0.05), _stat(20, 0.2)]
    ranked = rank_top_n(stats, n=10, excluded={23})
    assert [r["publisher_id"] for r in ranked] == ["11", "20"]


def test_rank_top_n_skips_rows_with_bad_rmse_over_spread(capsys):
    stats = [
        _stat(11, 0.1),
        {"publisher_id": "20", "rmse_over_spread": "NaN", "hit_rate_0.1pct": "0", "n_observations": "0"},
        _stat(35, 0.2),
    ]
    ranked = rank_top_n(stats, n=10, excluded=set())
    assert [r["publisher_id"] for r in ranked] == ["11", "35"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest pythresearch/data_quality/lazer/tests/test_summarize_feeds.py -v -k rank_top_n`
Expected: ImportError or failures.

- [ ] **Step 3: Implement `rank_top_n`**

Append to `summarize_feeds.py`:

```python
def rank_top_n(stats, n: int, excluded: set[int]) -> list[dict]:
    """Drop excluded publisher_ids, sort ascending by rmse_over_spread, take top n.

    Rows with non-numeric publisher_id or rmse_over_spread are skipped with a warning.
    """
    keyed: list[tuple[float, dict]] = []
    for r in stats:
        try:
            pid = int(r["publisher_id"])
        except (ValueError, KeyError):
            continue
        if pid in excluded:
            continue
        try:
            ros = float(r["rmse_over_spread"])
        except (ValueError, KeyError):
            print(f"  Warning: skipping row with bad rmse_over_spread: publisher_id={r.get('publisher_id')}")
            continue
        keyed.append((ros, r))
    keyed.sort(key=lambda x: x[0])
    return [r for _, r in keyed[:n]]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest pythresearch/data_quality/lazer/tests/test_summarize_feeds.py -v -k rank_top_n`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add pythresearch/data_quality/lazer/summarize_feeds.py pythresearch/data_quality/lazer/tests/test_summarize_feeds.py
git commit -m "feat: add rank_top_n with exclusion + malformed-row tolerance"
```

---

## Task 7: TDD `apply_filter`

**Files:**

- Modify: `tests/test_summarize_feeds.py`
- Modify: `summarize_feeds.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_summarize_feeds.py`:

```python
from pythresearch.data_quality.lazer.summarize_feeds import apply_filter


# ---------- apply_filter ----------

def test_apply_filter_returns_passers_when_present():
    stats = [
        _stat(11, 0.5, hit=90, n_obs=10000),   # passes
        _stat(20, 1.5, hit=90, n_obs=10000),   # fails ros
        _stat(35, 0.3, hit=85, n_obs=10000),   # passes
    ]
    passers, is_fallback = apply_filter(stats, max_ros=1.0, min_hit=80, min_obs=1000, fallback_n=3)
    assert is_fallback is False
    assert {r["publisher_id"] for r in passers} == {"11", "35"}
    # Sorted ascending by rmse_over_spread.
    assert [r["publisher_id"] for r in passers] == ["35", "11"]


def test_apply_filter_returns_fallback_when_zero_pass():
    stats = [
        _stat(11, 5.0, hit=10, n_obs=10000),
        _stat(20, 4.0, hit=10, n_obs=10000),
        _stat(35, 6.0, hit=10, n_obs=10000),
        _stat(42, 7.0, hit=10, n_obs=10000),
    ]
    passers, is_fallback = apply_filter(stats, max_ros=1.0, min_hit=80, min_obs=1000, fallback_n=3)
    assert is_fallback is True
    # Top-3 by rmse_over_spread: 20 (4.0), 11 (5.0), 35 (6.0).
    assert [r["publisher_id"] for r in passers] == ["20", "11", "35"]


def test_apply_filter_returns_partial_when_under_fallback_size():
    stats = [_stat(11, 5.0, hit=10), _stat(20, 4.0, hit=10)]
    passers, is_fallback = apply_filter(stats, max_ros=1.0, min_hit=80, min_obs=1000, fallback_n=3)
    assert is_fallback is True
    assert [r["publisher_id"] for r in passers] == ["20", "11"]


def test_apply_filter_returns_empty_when_input_empty():
    passers, is_fallback = apply_filter([], max_ros=1.0, min_hit=80, min_obs=1000, fallback_n=3)
    assert passers == []
    assert is_fallback is False


def test_apply_filter_excludes_low_n_observations():
    stats = [
        _stat(11, 0.1, hit=90, n_obs=500),      # fails n_obs
        _stat(20, 0.2, hit=90, n_obs=10000),    # passes
    ]
    passers, is_fallback = apply_filter(stats, max_ros=1.0, min_hit=80, min_obs=1000, fallback_n=3)
    assert is_fallback is False
    assert [r["publisher_id"] for r in passers] == ["20"]


def test_apply_filter_uses_per_mode_thresholds():
    """Same publisher set, regular thresholds vs overnight thresholds → different counts."""
    stats = [
        _stat(11, 0.8, hit=60, n_obs=10000),
        _stat(20, 1.5, hit=30, n_obs=10000),
        _stat(35, 2.5, hit=20, n_obs=10000),
    ]
    # Regular: max_ros=1.0, min_hit=80 → nobody passes → fallback top-3.
    passers, fb = apply_filter(stats, max_ros=1.0, min_hit=80, min_obs=1000, fallback_n=3)
    assert fb is True and len(passers) == 3
    # Overnight: max_ros=3.0, min_hit=25 → 11 and 20 pass.
    passers, fb = apply_filter(stats, max_ros=3.0, min_hit=25, min_obs=1000, fallback_n=3)
    assert fb is False
    assert {r["publisher_id"] for r in passers} == {"11", "20"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest pythresearch/data_quality/lazer/tests/test_summarize_feeds.py -v -k apply_filter`
Expected: ImportError or failures.

- [ ] **Step 3: Implement `apply_filter`**

Append to `summarize_feeds.py`:

```python
def apply_filter(stats, max_ros: float, min_hit: float, min_obs: int, fallback_n: int):
    """Apply per-mode thresholds. Return (passers, is_fallback).

    passers: list of stat dicts that pass all three thresholds, sorted ascending
             by rmse_over_spread.
    is_fallback: True iff zero rows passed AND input was non-empty (we then
                 return the top-fallback_n by rmse_over_spread instead).

    Empty input → ([], False). Rows with non-numeric metric fields are skipped silently.
    """
    if not stats:
        return [], False

    passers: list[tuple[float, dict]] = []
    parseable: list[tuple[float, dict]] = []
    for r in stats:
        try:
            ros = float(r["rmse_over_spread"])
            hit = float(r["hit_rate_0.1pct"])
            n_obs = int(r["n_observations"])
        except (ValueError, KeyError):
            continue
        parseable.append((ros, r))
        if ros <= max_ros and hit >= min_hit and n_obs >= min_obs:
            passers.append((ros, r))

    if passers:
        passers.sort(key=lambda x: x[0])
        return [r for _, r in passers], False

    # Fallback: top-fallback_n by rmse_over_spread from parseable rows.
    parseable.sort(key=lambda x: x[0])
    return [r for _, r in parseable[:fallback_n]], True
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest pythresearch/data_quality/lazer/tests/test_summarize_feeds.py -v -k apply_filter`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add pythresearch/data_quality/lazer/summarize_feeds.py pythresearch/data_quality/lazer/tests/test_summarize_feeds.py
git commit -m "feat: add apply_filter with per-mode thresholds + fallback"
```

---

## Task 8: TDD `compute_aggregate`

**Files:**

- Modify: `tests/test_summarize_feeds.py`
- Modify: `summarize_feeds.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_summarize_feeds.py`:

```python
from pythresearch.data_quality.lazer.summarize_feeds import compute_aggregate


# ---------- compute_aggregate ----------

def test_compute_aggregate_is_sorted_union_of_per_session_arrays():
    arrays = [[11, 20, 35], [20, 22, 41], [11, 42]]
    assert compute_aggregate(arrays) == [11, 20, 22, 35, 41, 42]


def test_compute_aggregate_skips_none_sessions():
    arrays = [[11, 20], None, [22, 11]]
    assert compute_aggregate(arrays) == [11, 20, 22]


def test_compute_aggregate_empty_when_all_sessions_empty():
    assert compute_aggregate([None, None, None, None]) == []
    assert compute_aggregate([[], [], []]) == []


def test_compute_aggregate_deduplicates():
    arrays = [[11, 11, 20], [20, 20]]
    assert compute_aggregate(arrays) == [11, 20]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest pythresearch/data_quality/lazer/tests/test_summarize_feeds.py -v -k compute_aggregate`
Expected: ImportError or failures.

- [ ] **Step 3: Implement `compute_aggregate`**

Append to `summarize_feeds.py`:

```python
def compute_aggregate(per_session_arrays) -> list[int]:
    """Sorted union of per-session publisher_id arrays.

    None entries (mode missing) are skipped. Empty list if every session is empty/None.
    """
    union: set[int] = set()
    for arr in per_session_arrays:
        if arr is None:
            continue
        union.update(arr)
    return sorted(union)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest pythresearch/data_quality/lazer/tests/test_summarize_feeds.py -v -k compute_aggregate`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add pythresearch/data_quality/lazer/summarize_feeds.py pythresearch/data_quality/lazer/tests/test_summarize_feeds.py
git commit -m "feat: add compute_aggregate sorted-union helper"
```

---

## Task 9: Implement `write_rankings_sheet`

**Files:**

- Modify: `summarize_feeds.py`

This sheet has no unit tests — its contract is exercised by the integration test in Task 11. Cell-level format details (colors, fonts) are explicitly out of scope for testing per the spec.

- [ ] **Step 1: Implement `write_rankings_sheet`**

Append to `summarize_feeds.py`:

```python
def write_rankings_sheet(ws, per_feed_data: dict, date: str, cluster: str) -> None:
    """Populate the 'rankings' worksheet.

    Layout (24 cols A:X):
      Row 1: workbook title (merged A:X), bold, font 14
      Row 2: blank
      Row 3: mode-block headers — "us-equities" merged B:F, "us-equities-pre" H:L,
             "us-equities-post" N:R, "us-equities-overnight" T:X, bold + light-gray fill
      Row 4: per-column sub-headers — "rank" in A, then "pub | n_obs | rmse | r/s | hit%" × 4
      Row 5+: per-feed sections (banner + 10 data rows + blank divider)

    Column allocation:
      A=rank | B-F=us-equities | G=spacer | H-L=us-equities-pre | M=spacer
      N-R=us-equities-post | S=spacer | T-X=us-equities-overnight
    """
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    bold = Font(bold=True)
    bold_lg = Font(bold=True, size=12)
    bold_xl = Font(bold=True, size=14)
    gray = PatternFill(start_color="DDDDDD", end_color="DDDDDD", fill_type="solid")
    center = Alignment(horizontal="center")

    mode_starts = {  # 1-indexed start columns of each 5-col mode block
        "us-equities": 2,            # B
        "us-equities-pre": 8,        # H
        "us-equities-post": 14,      # N
        "us-equities-overnight": 20, # T
    }
    sub_headers = ["pub", "n_obs", "rmse", "r/s", "hit%"]

    # Row 1: title.
    ws.cell(row=1, column=1, value=f"DQ Summary — {cluster} — {date}").font = bold_xl
    ws.merge_cells(start_row=1, start_column=1, end_row=1, end_column=24)
    ws.cell(row=1, column=1).alignment = center

    # Row 3: mode-block headers.
    for mode in MODE_ORDER:
        col = mode_starts[mode]
        c = ws.cell(row=3, column=col, value=mode)
        c.font = bold
        c.fill = gray
        c.alignment = center
        ws.merge_cells(start_row=3, start_column=col, end_row=3, end_column=col + 4)

    # Row 4: sub-headers.
    a4 = ws.cell(row=4, column=1, value="rank")
    a4.font = bold
    a4.fill = gray
    for mode in MODE_ORDER:
        start = mode_starts[mode]
        for i, label in enumerate(sub_headers):
            c = ws.cell(row=4, column=start + i, value=label)
            c.font = bold
            c.fill = gray

    # Freeze header rows.
    ws.freeze_panes = "A5"

    # Per-feed sections.
    row = 6
    for feed_id, mode_data in per_feed_data.items():
        # Banner.
        banner = ws.cell(row=row, column=1, value=f"=== Feed {feed_id} ===")
        banner.font = bold_lg
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=24)
        row += 1

        # Top-N data rows.
        ranked_per_mode = {
            m: (mode_data[m]["ranked"] if mode_data.get(m) else None) for m in MODE_ORDER
        }
        # Determine row count = max ranked length, capped at top_n (already capped upstream).
        n_rows = max(
            (len(r) for r in ranked_per_mode.values() if r), default=0
        )
        if n_rows == 0:
            # Every mode is None → still emit a single "(no data)" row for visibility.
            ws.cell(row=row, column=2, value="(no data)")
            row += 2  # blank divider after
            continue

        for i in range(n_rows):
            ws.cell(row=row + i, column=1, value=i + 1)  # rank
        for mode in MODE_ORDER:
            start = mode_starts[mode]
            ranked = ranked_per_mode[mode]
            if ranked is None:
                ws.cell(row=row, column=start, value="(no data)")
                continue
            for i, r in enumerate(ranked):
                ws.cell(row=row + i, column=start + 0, value=int(r["publisher_id"]))
                ws.cell(row=row + i, column=start + 1, value=int(r["n_observations"]))
                ws.cell(row=row + i, column=start + 2, value=round(float(r["rmse"]), 4))
                ws.cell(row=row + i, column=start + 3, value=round(float(r["rmse_over_spread"]), 4))
                ws.cell(row=row + i, column=start + 4, value=round(float(r["hit_rate_0.1pct"]), 2))
        row += n_rows + 1  # data rows + blank divider

    # Reasonable column widths.
    for col_idx in range(1, 25):
        letter = get_column_letter(col_idx)
        ws.column_dimensions[letter].width = 9
    ws.column_dimensions["A"].width = 6  # rank
```

- [ ] **Step 2: Verify the function compiles (syntax-only check)**

Run: `python3 -c "from pythresearch.data_quality.lazer import summarize_feeds; print(summarize_feeds.write_rankings_sheet.__doc__[:60])"`
Expected: prints a snippet of the docstring (no syntax error).

- [ ] **Step 3: Commit**

```bash
git add pythresearch/data_quality/lazer/summarize_feeds.py
git commit -m "feat: add write_rankings_sheet for per-feed mode-side-by-side layout"
```

---

## Task 10: Implement `write_allowed_sheet`

**Files:**

- Modify: `summarize_feeds.py`

- [ ] **Step 1: Implement `write_allowed_sheet`**

Append to `summarize_feeds.py`:

```python
def write_allowed_sheet(ws, per_feed_data: dict, skipped_feeds: list[int], date: str, cluster: str) -> None:
    """Populate the 'allowed' worksheet.

    Layout (4 cols, NO merges):
      A1: title (cell A1 only, bold size 14)
      A2: column headers — Feed ID | Session | allowedPublisherIds | Notes (bold + light gray)
      A3+: per-feed groups:
           row: <feed_id> | (aggregate)  | sorted-union JSON or "(no data)" |
           row: <feed_id> | REGULAR      | JSON or "(no data)"              | optional FALLBACK note
           row: <feed_id> | PRE_MARKET   | …
           row: <feed_id> | POST_MARKET  | …
           row: <feed_id> | OVER_NIGHT   | …
           row: blank divider
      Footer: "Feeds skipped (no data for any mode):" then one feed_id per row in column A.
    """
    from openpyxl.styles import Font, PatternFill

    bold = Font(bold=True)
    bold_xl = Font(bold=True, size=14)
    gray = PatternFill(start_color="DDDDDD", end_color="DDDDDD", fill_type="solid")
    yellow = PatternFill(start_color="FFF4B5", end_color="FFF4B5", fill_type="solid")
    light_gray = PatternFill(start_color="EEEEEE", end_color="EEEEEE", fill_type="solid")

    # Row 1: title (single cell, no merge).
    ws.cell(row=1, column=1, value=f"Allowed Publishers — {cluster} — {date}").font = bold_xl

    # Row 2: column headers.
    headers = ["Feed ID", "Session", "allowedPublisherIds", "Notes"]
    for i, h in enumerate(headers, 1):
        c = ws.cell(row=2, column=i, value=h)
        c.font = bold
        c.fill = gray

    ws.freeze_panes = "A3"
    ws.auto_filter.ref = "A2:D2"  # extended to last data row at the end

    row = 3
    for feed_id, mode_data in per_feed_data.items():
        # Build per-session arrays (None if mode missing or no data after filter).
        per_session_arrays: list[list[int] | None] = []
        for mode in MODE_ORDER:
            md = mode_data.get(mode) if mode_data else None
            if md is None:
                per_session_arrays.append(None)
            else:
                # filtered is the threshold-passing list (or fallback set).
                ids = sorted({int(r["publisher_id"]) for r in md["filtered"]})
                per_session_arrays.append(ids if ids else None)

        # Aggregate row.
        agg = compute_aggregate(per_session_arrays)
        ws.cell(row=row, column=1, value=feed_id)
        ws.cell(row=row, column=2, value="(aggregate)")
        ws.cell(row=row, column=3, value=json.dumps(agg) if agg else "(no data)")
        if not agg:
            ws.cell(row=row, column=4, value="all sessions empty").fill = light_gray
        row += 1

        # Per-session rows.
        for mode, ids in zip(MODE_ORDER, per_session_arrays):
            session_label = MODE_TO_SESSION[mode]
            md = mode_data.get(mode) if mode_data else None
            ws.cell(row=row, column=1, value=feed_id)
            ws.cell(row=row, column=2, value=session_label)
            if md is None:
                ws.cell(row=row, column=3, value="(no data)")
                ws.cell(row=row, column=4, value=f"mode missing for {date}").fill = light_gray
            elif ids is None:
                # Filter returned empty *after* parsing rows — rare, treat as no data.
                ws.cell(row=row, column=3, value="(no data)")
                ws.cell(row=row, column=4, value="filter empty after parse").fill = light_gray
            else:
                ws.cell(row=row, column=3, value=json.dumps(ids))
                if md["is_fallback"]:
                    ws.cell(row=row, column=4, value="FALLBACK: 0 passed filter").fill = yellow
            row += 1

        row += 1  # blank divider between feeds

    # Skipped-feeds footer.
    if skipped_feeds:
        row += 1
        ws.cell(row=row, column=1, value="Feeds skipped (no data for any mode):").font = bold
        for fid in skipped_feeds:
            row += 1
            ws.cell(row=row, column=1, value=fid)

    # Update auto-filter range to include all data rows.
    last_data_row = max(row, 2)
    ws.auto_filter.ref = f"A2:D{last_data_row}"

    # Column widths.
    ws.column_dimensions["A"].width = 10  # Feed ID
    ws.column_dimensions["B"].width = 14  # Session
    ws.column_dimensions["C"].width = 50  # JSON
    ws.column_dimensions["D"].width = 32  # Notes
```

- [ ] **Step 2: Verify the function compiles**

Run: `python3 -c "from pythresearch.data_quality.lazer import summarize_feeds; print(summarize_feeds.write_allowed_sheet.__doc__[:60])"`
Expected: prints a snippet (no syntax error).

- [ ] **Step 3: Commit**

```bash
git add pythresearch/data_quality/lazer/summarize_feeds.py
git commit -m "feat: add write_allowed_sheet with paste-ready JSON arrays"
```

---

## Task 11: Implement `main` + happy-path integration test

**Files:**

- Modify: `summarize_feeds.py`
- Modify: `tests/test_summarize_feeds.py`

- [ ] **Step 1: Implement `main`**

Append to `summarize_feeds.py`:

```python
def _build_per_feed_data(
    feed_ids, reports_dir, cluster, date, excluded, top_n,
    max_ros_map, min_hit_map, min_obs, fallback_top,
):
    """Returns (per_feed_data, skipped_feeds, fallback_count, modes_with_data_count)."""
    per_feed_data: dict = {}
    skipped: list[int] = []
    fallback_count = 0
    modes_with_data = 0

    for feed_id in feed_ids:
        mode_data: dict = {}
        any_data = False
        for mode in MODE_ORDER:
            raw = load_stats(reports_dir, cluster, mode, feed_id, date)
            if raw is None:
                mode_data[mode] = None
                continue
            # Apply exclusion at the row level.
            kept = []
            for r in raw:
                try:
                    pid = int(r["publisher_id"])
                except (ValueError, KeyError):
                    continue
                if pid in excluded:
                    continue
                kept.append(r)
            if not kept:
                mode_data[mode] = None  # all rows excluded
                continue
            ranked = rank_top_n(kept, n=top_n, excluded=set())  # already excluded
            filtered, is_fallback = apply_filter(
                kept, max_ros_map[mode], min_hit_map[mode], min_obs, fallback_top
            )
            mode_data[mode] = {"ranked": ranked, "filtered": filtered, "is_fallback": is_fallback}
            any_data = True
            modes_with_data += 1
            if is_fallback:
                fallback_count += 1
        if not any_data:
            skipped.append(feed_id)
        per_feed_data[feed_id] = mode_data
    return per_feed_data, skipped, fallback_count, modes_with_data


def main():
    parser = argparse.ArgumentParser(
        description="Generate one Excel summary workbook from evaluate_feeds_bulk DQ outputs.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Example:
  python3 -m pythresearch.data_quality.lazer.summarize_feeds \\
      --csv MV_Mario_3_pre.csv --cluster lazer-prod --date 2026-05-06
""",
    )
    parser.add_argument("--csv", required=True, help="CSV: feed_id,date,mode per row (column 1 used)")
    parser.add_argument("--cluster", required=True, help="Cluster name (e.g. lazer-prod)")
    parser.add_argument("--date", required=True, help="Date YYYY-MM-DD")
    parser.add_argument("--reports-dir", default="dq_reports",
                        help="Base reports directory (default: dq_reports)")
    parser.add_argument("--publishers-md", default="publishers.md",
                        help="Path to publishers.md (default: publishers.md)")
    parser.add_argument("--output", default=None,
                        help="Output .xlsx path (default: dq_summary_<cluster>_<date>.xlsx)")
    parser.add_argument("--max-rmse-over-spread-regular", type=float,
                        default=DEFAULT_MAX_ROS["us-equities"])
    parser.add_argument("--min-hit-rate-regular", type=float,
                        default=DEFAULT_MIN_HIT["us-equities"])
    parser.add_argument("--max-rmse-over-spread-pre", type=float,
                        default=DEFAULT_MAX_ROS["us-equities-pre"])
    parser.add_argument("--min-hit-rate-pre", type=float,
                        default=DEFAULT_MIN_HIT["us-equities-pre"])
    parser.add_argument("--max-rmse-over-spread-post", type=float,
                        default=DEFAULT_MAX_ROS["us-equities-post"])
    parser.add_argument("--min-hit-rate-post", type=float,
                        default=DEFAULT_MIN_HIT["us-equities-post"])
    parser.add_argument("--max-rmse-over-spread-overnight", type=float,
                        default=DEFAULT_MAX_ROS["us-equities-overnight"])
    parser.add_argument("--min-hit-rate-overnight", type=float,
                        default=DEFAULT_MIN_HIT["us-equities-overnight"])
    parser.add_argument("--min-n-observations", type=int, default=DEFAULT_MIN_N_OBS)
    parser.add_argument("--top-n", type=int, default=DEFAULT_TOP_N)
    parser.add_argument("--fallback-top", type=int, default=DEFAULT_FALLBACK_TOP)
    args = parser.parse_args()

    csv_path = Path(args.csv)
    md_path = Path(args.publishers_md)
    reports_dir = Path(args.reports_dir)

    if not csv_path.exists():
        print(f"Error: CSV file '{csv_path}' not found.")
        sys.exit(1)
    if not md_path.exists():
        print(f"Error: publishers.md '{md_path}' not found (needed for .Test exclusion).")
        sys.exit(1)
    if not (reports_dir / args.cluster).exists():
        print(f"Error: reports dir '{reports_dir / args.cluster}' not found.")
        sys.exit(1)

    excluded = load_excluded_publishers(md_path)
    feed_ids = discover_feeds(csv_path)
    if not feed_ids:
        print(f"Error: no feed_ids parsed from '{csv_path}'.")
        sys.exit(1)

    max_ros_map = {
        "us-equities": args.max_rmse_over_spread_regular,
        "us-equities-pre": args.max_rmse_over_spread_pre,
        "us-equities-post": args.max_rmse_over_spread_post,
        "us-equities-overnight": args.max_rmse_over_spread_overnight,
    }
    min_hit_map = {
        "us-equities": args.min_hit_rate_regular,
        "us-equities-pre": args.min_hit_rate_pre,
        "us-equities-post": args.min_hit_rate_post,
        "us-equities-overnight": args.min_hit_rate_overnight,
    }

    per_feed_data, skipped, fb_count, modes_with_data = _build_per_feed_data(
        feed_ids, reports_dir, args.cluster, args.date, excluded,
        args.top_n, max_ros_map, min_hit_map, args.min_n_observations, args.fallback_top,
    )

    feeds_with_data = len(feed_ids) - len(skipped)
    if feeds_with_data == 0:
        print("Error: no feed produced any data (wrong --date or --cluster?).")
        sys.exit(1)

    # Build workbook.
    from openpyxl import Workbook
    wb = Workbook()
    ws_rank = wb.active
    ws_rank.title = "rankings"
    ws_allow = wb.create_sheet("allowed")
    write_rankings_sheet(ws_rank, per_feed_data, args.date, args.cluster)
    write_allowed_sheet(ws_allow, per_feed_data, skipped, args.date, args.cluster)

    out_path = Path(args.output) if args.output else Path(
        f"dq_summary_{args.cluster}_{args.date}.xlsx"
    )
    wb.save(out_path)

    test_count = sum(1 for _ in excluded if _ != 0)
    sample_excluded = sorted(p for p in excluded if p != 0)[:3]
    print(f"Summary written to {out_path}")
    print(f"Feeds in CSV: {len(feed_ids)}")
    print(f"Feeds with at least one mode: {feeds_with_data}")
    if skipped:
        print(f"Feeds skipped (no data anywhere): {len(skipped)} → {skipped}")
    else:
        print("Feeds skipped (no data anywhere): 0")
    print(f"Modes with data: {modes_with_data}/{len(feed_ids) * 4} cells")
    print(f"Excluded publishers: 0 + {test_count} .Test (sample: {sample_excluded})")
    print(f"Fallbacks triggered: {fb_count} cells")
    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Write failing happy-path integration test**

Append to `tests/test_summarize_feeds.py`:

```python
import sys

from openpyxl import load_workbook

from pythresearch.data_quality.lazer.summarize_feeds import main


def test_main_writes_workbook_for_one_feed_one_mode(tmp_path, monkeypatch, capsys):
    """End-to-end happy path: 1 feed, 1 mode populated, 3 missing modes."""
    # publishers.md
    pubs_md = tmp_path / "publishers.md"
    pubs_md.write_text("""\
| ID  | Name              | Active |
| --- | ----------------- | ------ |
| 11  | Amber.Production  | Yes    |
| 23  | LoTech.Test       | Yes    |
""")

    # CSV with one feed.
    csv = tmp_path / "input.csv"
    csv.write_text("1021, 2026-05-06, us-equities-post\n")

    # dq_reports tree — only us-equities-post for feed 1021 has data.
    reports = tmp_path / "dq_reports"
    _write_stats_csv(
        reports, "lazer-prod", "us-equities-post", 1021, "2026-05-06",
        [
            "1021,11,22218,-0.05,0.08,-0.01,0.02,0.0932,0.51,0.0185,0.07,-84,0,75,0,0,100.0,0.96,fail\n",
            # excluded .Test publisher 23 — must not appear anywhere.
            "1021,23,5000,-0.05,0.08,-0.01,0.02,0.05,0.5,0.01,0.05,0,0,0,0,0,100.0,0.5,fail\n",
        ]
    )

    out_path = tmp_path / "out.xlsx"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "summarize_feeds",
        "--csv", str(csv),
        "--cluster", "lazer-prod",
        "--date", "2026-05-06",
        "--reports-dir", str(reports),
        "--publishers-md", str(pubs_md),
        "--output", str(out_path),
    ])

    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0

    # Workbook exists with both sheets.
    wb = load_workbook(out_path, data_only=True)
    assert "rankings" in wb.sheetnames
    assert "allowed" in wb.sheetnames

    # Allowed sheet: 1 aggregate row + 4 session rows = 5 data rows starting at row 3.
    allow = wb["allowed"]
    assert allow.cell(3, 1).value == 1021
    assert allow.cell(3, 2).value == "(aggregate)"
    # Aggregate JSON contains publisher 11 only (23 excluded as .Test).
    assert allow.cell(3, 3).value == "[11]"
    # Session rows in MODE_ORDER: us-equities (no data), pre (no data), post (data), overnight (no data).
    assert allow.cell(4, 2).value == "REGULAR"
    assert allow.cell(4, 3).value == "(no data)"
    assert allow.cell(5, 2).value == "PRE_MARKET"
    assert allow.cell(6, 2).value == "POST_MARKET"
    assert allow.cell(6, 3).value == "[11]"
    assert allow.cell(7, 2).value == "OVER_NIGHT"
    assert allow.cell(7, 3).value == "(no data)"

    # Rankings sheet: feed banner + at least 1 data row.
    rank = wb["rankings"]
    found_banner = any(
        rank.cell(r, 1).value == "=== Feed 1021 ==="
        for r in range(1, 30)
    )
    assert found_banner
```

- [ ] **Step 3: Run the integration test, verify it passes**

Run: `pytest pythresearch/data_quality/lazer/tests/test_summarize_feeds.py -v -k test_main_writes_workbook_for_one_feed_one_mode`
Expected: PASS.

- [ ] **Step 4: Commit**

```bash
git add pythresearch/data_quality/lazer/summarize_feeds.py pythresearch/data_quality/lazer/tests/test_summarize_feeds.py
git commit -m "feat: add main + happy-path integration test for summarize_feeds"
```

---

## Task 12: Edge-case integration tests

**Files:**

- Modify: `tests/test_summarize_feeds.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_summarize_feeds.py`:

```python
def test_main_skipped_feeds_section_lists_zero_data_feeds(tmp_path, monkeypatch, capsys):
    """Feed in CSV with no data anywhere → listed in skipped footer + stdout summary."""
    pubs_md = tmp_path / "publishers.md"
    pubs_md.write_text("| ID | Name | Active |\n| --- | --- | --- |\n| 11 | Amber.Production | Yes |\n")

    csv = tmp_path / "input.csv"
    csv.write_text("1021, 2026-05-06, us-equities\n9999, 2026-05-06, us-equities\n")

    reports = tmp_path / "dq_reports"
    _write_stats_csv(
        reports, "lazer-prod", "us-equities", 1021, "2026-05-06",
        ["1021,11,22218,-0.05,0.08,-0.01,0.02,0.0932,0.51,0.0185,0.07,-84,0,75,0,0,100.0,0.96,fail\n"]
    )
    # Feed 9999 has no stats anywhere.

    out_path = tmp_path / "out.xlsx"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "summarize_feeds",
        "--csv", str(csv), "--cluster", "lazer-prod", "--date", "2026-05-06",
        "--reports-dir", str(reports), "--publishers-md", str(pubs_md),
        "--output", str(out_path),
    ])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0

    out = capsys.readouterr().out
    assert "9999" in out
    assert "Feeds skipped" in out

    wb = load_workbook(out_path, data_only=True)
    allow = wb["allowed"]
    # Find footer header.
    found_footer_label = False
    found_9999 = False
    for r in range(1, 60):
        v = allow.cell(r, 1).value
        if v == "Feeds skipped (no data for any mode):":
            found_footer_label = True
        if v == 9999:
            found_9999 = True
    assert found_footer_label
    assert found_9999


def test_main_no_data_anywhere_exits_nonzero(tmp_path, monkeypatch):
    pubs_md = tmp_path / "publishers.md"
    pubs_md.write_text("| ID | Name | Active |\n| --- | --- | --- |\n")

    csv = tmp_path / "input.csv"
    csv.write_text("1021, 2026-05-06, us-equities\n")

    reports = tmp_path / "dq_reports"
    (reports / "lazer-prod").mkdir(parents=True)  # cluster dir exists but empty

    out_path = tmp_path / "out.xlsx"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "summarize_feeds",
        "--csv", str(csv), "--cluster", "lazer-prod", "--date", "2026-05-06",
        "--reports-dir", str(reports), "--publishers-md", str(pubs_md),
        "--output", str(out_path),
    ])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1


def test_main_excluded_publishers_never_appear_in_either_sheet(tmp_path, monkeypatch):
    """A .Test publisher with stellar metrics must not appear in rankings or allowed."""
    pubs_md = tmp_path / "publishers.md"
    pubs_md.write_text("""\
| ID | Name             | Active |
| --- | --------------- | ------ |
| 11 | Amber.Production | Yes   |
| 23 | LoTech.Test      | Yes   |
""")

    csv = tmp_path / "input.csv"
    csv.write_text("1021, 2026-05-06, us-equities\n")

    reports = tmp_path / "dq_reports"
    _write_stats_csv(
        reports, "lazer-prod", "us-equities", 1021, "2026-05-06",
        [
            # publisher 23 has the BEST rmse_over_spread but is .Test → must be filtered out.
            "1021,23,99999,-0.001,0.001,-0.0001,0.0001,0.001,0.001,0.0001,0.001,0,0,0,0,0,100.0,0.01,fail\n",
            "1021,11,22218,-0.05,0.08,-0.01,0.02,0.0932,0.51,0.0185,0.07,-84,0,75,0,0,100.0,0.96,fail\n",
        ]
    )

    out_path = tmp_path / "out.xlsx"
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "summarize_feeds",
        "--csv", str(csv), "--cluster", "lazer-prod", "--date", "2026-05-06",
        "--reports-dir", str(reports), "--publishers-md", str(pubs_md),
        "--output", str(out_path),
    ])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0

    wb = load_workbook(out_path, data_only=True)

    # Rankings sheet: scan all cells for "23" — none should appear as a publisher_id.
    rank = wb["rankings"]
    for r in range(1, 30):
        for c in range(1, 25):
            assert rank.cell(r, c).value != 23, f"excluded publisher 23 leaked into rankings at ({r},{c})"

    # Allowed sheet: column C JSON arrays must not contain 23.
    allow = wb["allowed"]
    for r in range(1, 30):
        v = allow.cell(r, 3).value
        if isinstance(v, str) and v.startswith("["):
            assert "23" not in v, f"excluded publisher 23 leaked into allowed JSON: {v}"


def test_main_missing_csv_exits_nonzero(tmp_path, monkeypatch, capsys):
    pubs_md = tmp_path / "publishers.md"
    pubs_md.write_text("| ID | Name | Active |\n| --- | --- | --- |\n")

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(sys, "argv", [
        "summarize_feeds",
        "--csv", str(tmp_path / "missing.csv"),
        "--cluster", "lazer-prod", "--date", "2026-05-06",
        "--publishers-md", str(pubs_md),
    ])
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    assert "not found" in capsys.readouterr().out
```

- [ ] **Step 2: Run the new tests, verify they pass**

Run: `pytest pythresearch/data_quality/lazer/tests/test_summarize_feeds.py -v -k "test_main_"`
Expected: 5 PASS (4 new + 1 from Task 11).

- [ ] **Step 3: Commit**

```bash
git add pythresearch/data_quality/lazer/tests/test_summarize_feeds.py
git commit -m "test: add integration tests for skipped feeds, empty data, exclusions, missing inputs"
```

---

## Task 13: Verify full test suite + coverage

**Files:** none modified (verification only).

- [ ] **Step 1: Run the full new test file**

Run: `pytest pythresearch/data_quality/lazer/tests/test_summarize_feeds.py -v`
Expected: all tests pass. Count should be ≥ 24 (4 + 3 + 2 + 4 + 6 + 4 + 1 + 4 = 28 if every assertion in the plan is preserved).

- [ ] **Step 2: Run with coverage**

Run:

```bash
pytest pythresearch/data_quality/lazer/tests/test_summarize_feeds.py \
    --cov=pythresearch.data_quality.lazer.summarize_feeds \
    --cov-report=term-missing
```

Expected: coverage ≥ 80%. If under 80%, add small targeted tests for the missing lines reported in the term-missing output.

- [ ] **Step 3: Verify the existing suite still passes (no regression)**

Run: `pytest pythresearch/data_quality/lazer/tests/ -v`
Expected: all tests pass — both `test_evaluate_feeds_bulk.py` and `test_summarize_feeds.py`.

- [ ] **Step 4: No commit needed (verification only).**

---

## Task 14: Smoke test against real data

**Files:** none modified (smoke test only).

- [ ] **Step 1: Run the script against a real CSV that exists in repo**

Run from repo root:

```bash
ls *.csv | head -3
```

Pick any CSV at the repo root (e.g. `MV_Mario_3_pre.csv` if present). If none exists at root, look under `pythresearch/data_quality/lazer/`.

- [ ] **Step 2: Invoke the new script with that CSV against an existing date**

Existing data in `dq_reports/lazer-prod/` covers `2026-05-01`, `2026-05-04`, `2026-05-06`. Pick one:

```bash
python3 -m pythresearch.data_quality.lazer.summarize_feeds \
    --csv <chosen.csv> \
    --cluster lazer-prod \
    --date 2026-05-06 \
    --output /tmp/dq_summary_smoke.xlsx
```

Expected: stdout summary printed, exit code 0, file `/tmp/dq_summary_smoke.xlsx` exists.

- [ ] **Step 3: Open the file and eyeball the layout**

Open `/tmp/dq_summary_smoke.xlsx` in Excel/Numbers/LibreOffice. Verify:

- `rankings` sheet has 4 mode-block headers and at least one feed banner.
- `allowed` sheet has tabular rows. Column C contains JSON arrays like `[11, 35, 20]`.
- Selecting a single cell in column C and copying yields just the JSON text (no merged-cell oddness).
- Skipped-feeds footer present iff some feeds had no data.

- [ ] **Step 4: No commit (verification only).**

---

## Task 15: Final cleanup pass

**Files:** review only.

- [ ] **Step 1: Run flake8 / pyflakes against the new module**

Run: `python3 -m pyflakes pythresearch/data_quality/lazer/summarize_feeds.py`
Expected: no output (no warnings). If warnings exist, fix and amend the most recent commit OR create a small follow-up commit.

- [ ] **Step 2: Confirm git log is clean**

Run: `git log --oneline -15`
Expected: ~12 new commits with descriptive `feat:` / `test:` / `chore:` messages, in order. No "wip" or "fixup" messages.

- [ ] **Step 3: Stop here and request review.**

The branch is ready for the user to inspect or open a PR. Do not push or open a PR unless explicitly asked.

---

## Self-Review

**Spec coverage check** (every spec section → task that implements it):

| Spec section                                               | Implementing task                                                                                                                                                                              |
| ---------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Module file path & function decomposition                  | Task 2 (skeleton) + Tasks 3–11 (each function)                                                                                                                                                 |
| CLI flags                                                  | Task 11 (`main()` argparse)                                                                                                                                                                    |
| Mode → session mapping (`MODE_TO_SESSION`)                 | Task 2                                                                                                                                                                                         |
| Data flow (exclusion → rank → filter → aggregate)          | Task 11 (`_build_per_feed_data`)                                                                                                                                                               |
| Per-mode thresholds + global `min_n_observations`          | Tasks 7, 11                                                                                                                                                                                    |
| Excluded publishers (`{0} ∪ .Test`)                        | Task 3 (loader) + Task 11 (applied at row level)                                                                                                                                               |
| Fallback when filter empty                                 | Task 7 (function) + Task 11 (used)                                                                                                                                                             |
| `rmse_over_spread` definition (documentation only)         | Spec only — no code change needed                                                                                                                                                              |
| `rankings` sheet layout (24-col side-by-side)              | Task 9                                                                                                                                                                                         |
| `allowed` sheet layout (tabular, no merges)                | Task 10                                                                                                                                                                                        |
| Aggregate row                                              | Task 8 + Task 10                                                                                                                                                                               |
| Cell coloring (yellow / light-gray for fallback / no-data) | Task 10                                                                                                                                                                                        |
| Auto-filter + freeze panes                                 | Tasks 9, 10                                                                                                                                                                                    |
| Skipped-feeds footer in `allowed`                          | Task 10 + integration test in Task 12                                                                                                                                                          |
| Hard error: missing CSV / publishers.md / cluster dir      | Task 11 + integration test in Task 12                                                                                                                                                          |
| Soft error: missing per-feed-mode `stats.csv`              | Task 5 (returns None) + Task 11 (renders `(no data)`)                                                                                                                                          |
| Soft error: malformed CSV row                              | Task 4                                                                                                                                                                                         |
| Soft error: malformed `stats.csv` row                      | Tasks 6, 7                                                                                                                                                                                     |
| Stdout summary                                             | Task 11                                                                                                                                                                                        |
| openpyxl dependency                                        | Task 1                                                                                                                                                                                         |
| Tests 1-13 unit + 14-19 integration                        | Tasks 3–8 (units) + Tasks 11–12 (integration)                                                                                                                                                  |
| 24-column note                                             | Spec said "26 cols total" but 5×4 + 1 + 3 spacers = 24. Plan uses 24 (range A:X). Spec self-review of design doc already noted this discrepancy informally; correcting at implementation time. |

**Placeholder scan:** none. All test code, all implementation code, all commands shown in full. No "implement later", "TBD", or "similar to Task N" references.

**Type / signature consistency:**

- `load_excluded_publishers(path) -> set[int]` — same name in module, tests, and `main()`. ✓
- `discover_feeds(csv_path) -> list[int]` — consistent. ✓
- `load_stats(reports_dir, cluster, mode, feed_id, date)` — same arg order in module, tests, and `_build_per_feed_data`. ✓
- `rank_top_n(stats, n, excluded)` — `excluded` param present even though `_build_per_feed_data` passes `set()` (exclusion done one level up). API matches spec. ✓
- `apply_filter(stats, max_ros, min_hit, min_obs, fallback_n) -> tuple[list[dict], bool]` — return signature consistent across function, tests, and consumer. ✓
- `compute_aggregate(per_session_arrays) -> list[int]` — accepts iterable of `list[int] | None`. Test #2 covers None case. ✓
- `mode_data[mode]` shape: `{"ranked": [...], "filtered": [...], "is_fallback": bool}` or `None`. Used identically in `write_rankings_sheet`, `write_allowed_sheet`, integration tests. ✓

No drift detected.
