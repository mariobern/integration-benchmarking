# Per-Session Publisher Consistency & Classifications — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add premarket, afterhours, and overnight publisher consistency + classification sections to `feed_readiness.py --detailed` output, gated by `--extended-hours` / `--overnight` flags.

**Architecture:** Generalize the existing `compute_publisher_consistency` function with a status-extractor parameter. Create session-specific extractors. Parameterize `write_publisher_consistency_csv` and `print_publisher_consistency` with a session prefix. Call once per active session after regular-hours output.

**Tech Stack:** Python 3, pytest, csv module

---

### Task 1: Test helper factory for `PublisherReadinessDetail` and `FeedReadinessResult`

**Files:**
- Create: `tests/test_feed_readiness.py`

**Step 1: Write helper factories**

```python
"""Tests for feed_readiness.py — publisher consistency & classifications."""
import csv
import io
from typing import Optional

import pytest

from feed_readiness import (
    FeedReadinessResult,
    PublisherReadinessDetail,
    compute_publisher_consistency,
    write_publisher_consistency_csv,
    print_publisher_consistency,
)


def make_detail(
    publisher_id: int,
    fully_passes: bool = False,
    benchmark_passes: bool = False,
    uptime_passes: bool = False,
    benchmark_error: Optional[str] = None,
    uptime_error: Optional[str] = None,
    # premarket
    premarket_benchmark_passes: Optional[bool] = None,
    premarket_uptime_passes: Optional[bool] = None,
    premarket_uptime_pct: Optional[float] = None,
    # afterhours
    afterhours_benchmark_passes: Optional[bool] = None,
    afterhours_uptime_passes: Optional[bool] = None,
    afterhours_uptime_pct: Optional[float] = None,
    # overnight
    overnight_benchmark_passes: Optional[bool] = None,
    overnight_uptime_passes: Optional[bool] = None,
    overnight_uptime_pct: Optional[float] = None,
) -> PublisherReadinessDetail:
    return PublisherReadinessDetail(
        publisher_id=publisher_id,
        benchmark_passes=benchmark_passes,
        benchmark_nrmse=0.01 if benchmark_passes else None,
        benchmark_hit_rate=98.0 if benchmark_passes else None,
        benchmark_n_observations=100,
        benchmark_error=benchmark_error,
        uptime_passes=uptime_passes,
        uptime_pct=99.0 if uptime_passes else 50.0,
        uptime_error=uptime_error,
        fully_passes=fully_passes,
        premarket_benchmark_passes=premarket_benchmark_passes,
        premarket_uptime_passes=premarket_uptime_passes,
        premarket_uptime_pct=premarket_uptime_pct,
        afterhours_benchmark_passes=afterhours_benchmark_passes,
        afterhours_uptime_passes=afterhours_uptime_passes,
        afterhours_uptime_pct=afterhours_uptime_pct,
        overnight_benchmark_passes=overnight_benchmark_passes,
        overnight_uptime_passes=overnight_uptime_passes,
        overnight_uptime_pct=overnight_uptime_pct,
    )


def make_result(
    feed_id: int,
    date: str,
    details: list[PublisherReadinessDetail],
) -> FeedReadinessResult:
    passing = [d for d in details if d.fully_passes]
    return FeedReadinessResult(
        feed_id=feed_id,
        date=date,
        mode="us-equities",
        symbol=f"Equity.US.TEST/USD",
        ready=len(passing) >= 4,
        benchmark_ready=len(passing) >= 4,
        uptime_ready=len(passing) >= 4,
        target_pub_count=4,
        fully_passing_count=len(passing),
        benchmark_only_passing_count=0,
        uptime_only_passing_count=0,
        both_failing_count=len(details) - len(passing),
        total_publisher_count=len(details),
        benchmark_passing_count=len(passing),
        benchmark_failing_count=len(details) - len(passing),
        median_nrmse=0.01,
        median_hit_rate=98.0,
        uptime_passing_count=len(passing),
        uptime_failing_count=len(details) - len(passing),
        median_uptime_pct=99.0,
        fully_passing_publishers=[d.publisher_id for d in passing],
        benchmark_only_publishers=[],
        uptime_only_publishers=[],
        both_failing_publishers=[d.publisher_id for d in details if not d.fully_passes],
        publisher_details=details,
    )
```

**Step 2: Run to verify imports work**

Run: `pytest tests/test_feed_readiness.py --collect-only`
Expected: Collects 0 tests (no test functions yet), no import errors.

**Step 3: Commit**

```bash
git add tests/test_feed_readiness.py
git commit -m "test: add test scaffold with factories for feed_readiness"
```

---

### Task 2: Test & implement session status extractors

**Files:**
- Modify: `feed_readiness.py:790` (add extractors before `compute_publisher_consistency`)
- Modify: `tests/test_feed_readiness.py` (add tests)

**Step 1: Write failing tests for session extractors**

Append to `tests/test_feed_readiness.py`:

```python
from feed_readiness import (
    _regular_status,
    _premarket_status,
    _afterhours_status,
    _overnight_status,
)


class TestRegularStatus:
    def test_pass(self):
        detail = make_detail(publisher_id=1, fully_passes=True, benchmark_passes=True, uptime_passes=True)
        assert _regular_status(detail) == "PASS"

    def test_fail(self):
        detail = make_detail(publisher_id=1, fully_passes=False)
        assert _regular_status(detail) == "FAIL"

    def test_error_benchmark(self):
        detail = make_detail(publisher_id=1, benchmark_error="No data")
        assert _regular_status(detail) == "ERROR"

    def test_error_uptime(self):
        detail = make_detail(publisher_id=1, uptime_error="Timeout")
        assert _regular_status(detail) == "ERROR"


class TestPremarketStatus:
    def test_pass(self):
        detail = make_detail(
            publisher_id=1,
            premarket_benchmark_passes=True,
            premarket_uptime_passes=True,
            premarket_uptime_pct=99.0,
        )
        assert _premarket_status(detail) == "PASS"

    def test_fail_benchmark(self):
        detail = make_detail(
            publisher_id=1,
            premarket_benchmark_passes=False,
            premarket_uptime_passes=True,
            premarket_uptime_pct=99.0,
        )
        assert _premarket_status(detail) == "FAIL"

    def test_fail_uptime(self):
        detail = make_detail(
            publisher_id=1,
            premarket_benchmark_passes=True,
            premarket_uptime_passes=False,
            premarket_uptime_pct=80.0,
        )
        assert _premarket_status(detail) == "FAIL"

    def test_no_data_none_uptime(self):
        detail = make_detail(publisher_id=1, premarket_uptime_pct=None)
        assert _premarket_status(detail) is None

    def test_no_data_zero_uptime(self):
        detail = make_detail(publisher_id=1, premarket_uptime_pct=0.0)
        assert _premarket_status(detail) is None

    def test_error_benchmark_none(self):
        detail = make_detail(
            publisher_id=1,
            premarket_benchmark_passes=None,
            premarket_uptime_passes=True,
            premarket_uptime_pct=99.0,
        )
        assert _premarket_status(detail) == "ERROR"


class TestAfterhours Status:
    def test_pass(self):
        detail = make_detail(
            publisher_id=1,
            afterhours_benchmark_passes=True,
            afterhours_uptime_passes=True,
            afterhours_uptime_pct=99.0,
        )
        assert _afterhours_status(detail) == "PASS"

    def test_no_data(self):
        detail = make_detail(publisher_id=1, afterhours_uptime_pct=None)
        assert _afterhours_status(detail) is None

    def test_fail(self):
        detail = make_detail(
            publisher_id=1,
            afterhours_benchmark_passes=False,
            afterhours_uptime_passes=True,
            afterhours_uptime_pct=99.0,
        )
        assert _afterhours_status(detail) == "FAIL"


class TestOvernightStatus:
    def test_pass(self):
        detail = make_detail(
            publisher_id=1,
            overnight_benchmark_passes=True,
            overnight_uptime_passes=True,
            overnight_uptime_pct=99.0,
        )
        assert _overnight_status(detail) == "PASS"

    def test_no_data(self):
        detail = make_detail(publisher_id=1, overnight_uptime_pct=None)
        assert _overnight_status(detail) is None

    def test_error(self):
        detail = make_detail(
            publisher_id=1,
            overnight_benchmark_passes=None,
            overnight_uptime_passes=True,
            overnight_uptime_pct=99.0,
        )
        assert _overnight_status(detail) == "ERROR"
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_feed_readiness.py -v -k "Status"`
Expected: ImportError — `_regular_status` not found.

**Step 3: Implement the four extractors**

Add before `compute_publisher_consistency` (before line 790 in `feed_readiness.py`):

```python
from typing import Callable


def _regular_status(detail: PublisherReadinessDetail) -> str | None:
    """Status extractor for regular-hours consistency."""
    if detail.benchmark_error or detail.uptime_error:
        return "ERROR"
    return "PASS" if detail.fully_passes else "FAIL"


def _session_status(
    benchmark_passes: bool | None,
    uptime_passes: bool | None,
    uptime_pct: float | None,
) -> str | None:
    """Generic session status extractor. Returns None if no data for this session."""
    if uptime_pct is None or uptime_pct == 0.0:
        return None
    if benchmark_passes is None:
        return "ERROR"
    return "PASS" if (benchmark_passes and uptime_passes) else "FAIL"


def _premarket_status(detail: PublisherReadinessDetail) -> str | None:
    return _session_status(
        detail.premarket_benchmark_passes,
        detail.premarket_uptime_passes,
        detail.premarket_uptime_pct,
    )


def _afterhours_status(detail: PublisherReadinessDetail) -> str | None:
    return _session_status(
        detail.afterhours_benchmark_passes,
        detail.afterhours_uptime_passes,
        detail.afterhours_uptime_pct,
    )


def _overnight_status(detail: PublisherReadinessDetail) -> str | None:
    return _session_status(
        detail.overnight_benchmark_passes,
        detail.overnight_uptime_passes,
        detail.overnight_uptime_pct,
    )
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_feed_readiness.py -v -k "Status"`
Expected: All 16 tests PASS.

**Step 5: Commit**

```bash
git add feed_readiness.py tests/test_feed_readiness.py
git commit -m "feat: add session status extractors for consistency computation"
```

---

### Task 3: Test & generalize `compute_publisher_consistency`

**Files:**
- Modify: `feed_readiness.py:790-846` (refactor function signature)
- Modify: `tests/test_feed_readiness.py` (add tests)

**Step 1: Write failing tests for parameterized consistency**

Append to `tests/test_feed_readiness.py`:

```python
class TestComputePublisherConsistency:
    """Tests for compute_publisher_consistency with status_extractor."""

    def _make_two_date_results(self):
        """Two dates, publisher 19 passes regular+premarket, publisher 20 fails both."""
        details_d1 = [
            make_detail(
                publisher_id=19, fully_passes=True, benchmark_passes=True, uptime_passes=True,
                premarket_benchmark_passes=True, premarket_uptime_passes=True, premarket_uptime_pct=99.0,
            ),
            make_detail(
                publisher_id=20, fully_passes=False,
                premarket_benchmark_passes=False, premarket_uptime_passes=True, premarket_uptime_pct=80.0,
            ),
        ]
        details_d2 = [
            make_detail(
                publisher_id=19, fully_passes=True, benchmark_passes=True, uptime_passes=True,
                premarket_benchmark_passes=True, premarket_uptime_passes=True, premarket_uptime_pct=99.0,
            ),
            make_detail(
                publisher_id=20, fully_passes=False,
                premarket_benchmark_passes=True, premarket_uptime_passes=True, premarket_uptime_pct=95.0,
            ),
        ]
        return [
            make_result(feed_id=100, date="2026-02-17", details=details_d1),
            make_result(feed_id=100, date="2026-02-18", details=details_d2),
        ]

    def test_regular_default_extractor(self):
        results = self._make_two_date_results()
        consistency = compute_publisher_consistency(results)
        # Publisher 19: PASS on both dates
        row_19 = next(r for r in consistency["rows"] if r["publisher_id"] == 19)
        assert row_19["pass_count"] == 2
        assert 19 in consistency["classifications"]["always_passing"]
        # Publisher 20: FAIL on both dates
        row_20 = next(r for r in consistency["rows"] if r["publisher_id"] == 20)
        assert row_20["fail_count"] == 2
        assert 20 in consistency["classifications"]["always_failing"]

    def test_premarket_extractor(self):
        results = self._make_two_date_results()
        consistency = compute_publisher_consistency(results, status_extractor=_premarket_status)
        # Publisher 19: PASS on both dates (premarket benchmark+uptime pass)
        row_19 = next(r for r in consistency["rows"] if r["publisher_id"] == 19)
        assert row_19["pass_count"] == 2
        # Publisher 20: FAIL d1, PASS d2 → intermittent
        row_20 = next(r for r in consistency["rows"] if r["publisher_id"] == 20)
        assert row_20["pass_count"] == 1
        assert row_20["fail_count"] == 1
        assert 20 in consistency["classifications"]["intermittent"]

    def test_extractor_none_excludes_publisher(self):
        """Publisher with no session data (None uptime) excluded from rows."""
        details = [
            make_detail(
                publisher_id=19, fully_passes=True,
                premarket_uptime_pct=99.0, premarket_benchmark_passes=True, premarket_uptime_passes=True,
            ),
            make_detail(
                publisher_id=20, fully_passes=False,
                premarket_uptime_pct=None,  # no premarket data
            ),
        ]
        results = [
            make_result(feed_id=100, date="2026-02-17", details=details),
            make_result(feed_id=100, date="2026-02-18", details=details),
        ]
        consistency = compute_publisher_consistency(results, status_extractor=_premarket_status)
        publisher_ids = {r["publisher_id"] for r in consistency["rows"]}
        assert 19 in publisher_ids
        assert 20 not in publisher_ids  # excluded — no premarket data

    def test_backward_compatible_no_extractor(self):
        """Without extractor arg, behavior is identical to original (regular hours)."""
        details = [make_detail(publisher_id=19, fully_passes=True, benchmark_passes=True, uptime_passes=True)]
        results = [
            make_result(feed_id=100, date="2026-02-17", details=details),
            make_result(feed_id=100, date="2026-02-18", details=details),
        ]
        consistency = compute_publisher_consistency(results)
        assert consistency["classifications"]["always_passing"] == [19]
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_feed_readiness.py::TestComputePublisherConsistency -v`
Expected: FAIL — `compute_publisher_consistency` doesn't accept `status_extractor` kwarg.

**Step 3: Refactor `compute_publisher_consistency` (line 790)**

Replace the function signature and the inner status-determination logic:

```python
def compute_publisher_consistency(
    results: list[FeedReadinessResult],
    status_extractor: Callable[[PublisherReadinessDetail], str | None] | None = None,
) -> dict:
    if status_extractor is None:
        status_extractor = _regular_status

    dates = sorted({result.date for result in results})

    publisher_statuses: dict[int, dict[str, str]] = {}
    for result in sorted(results, key=lambda r: (r.date, r.feed_id)):
        for detail in result.publisher_details or []:
            status = status_extractor(detail)
            if status is None:
                continue  # no data for this session → skip
            publisher_statuses.setdefault(detail.publisher_id, {})[result.date] = status

    # ... rest of function unchanged (rows aggregation + classifications)
```

Only two changes:
1. Add `status_extractor` parameter with default `None` → `_regular_status`
2. Replace the inline `if detail.benchmark_error...` block with `status = status_extractor(detail)` + `if status is None: continue`

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_feed_readiness.py -v`
Expected: All tests PASS (extractors + consistency).

**Step 5: Commit**

```bash
git add feed_readiness.py tests/test_feed_readiness.py
git commit -m "feat: generalize compute_publisher_consistency with status_extractor param"
```

---

### Task 4: Test & parameterize `write_publisher_consistency_csv`

**Files:**
- Modify: `feed_readiness.py:849-881` (add `session_prefix` parameter)
- Modify: `tests/test_feed_readiness.py` (add tests)

**Step 1: Write failing tests for session-prefixed CSV output**

Append to `tests/test_feed_readiness.py`:

```python
class TestWritePublisherConsistencyCsv:
    def _write_and_read(self, consistency, session_prefix=""):
        buf = io.StringIO()
        writer = csv.writer(buf)
        write_publisher_consistency_csv(writer, consistency, session_prefix=session_prefix)
        buf.seek(0)
        return buf.getvalue()

    def _make_consistency(self):
        return {
            "dates": ["2026-02-17", "2026-02-18"],
            "rows": [
                {
                    "publisher_id": 19,
                    "dates_seen": 2,
                    "pass_count": 2,
                    "fail_count": 0,
                    "error_count": 0,
                    "pass_rate": 100.0,
                    "results": {"2026-02-17": "PASS", "2026-02-18": "PASS"},
                },
            ],
            "classifications": {
                "always_passing": [19],
                "always_failing": [],
                "intermittent": [],
            },
        }

    def test_regular_default_prefix(self):
        output = self._write_and_read(self._make_consistency())
        assert "PUBLISHER CONSISTENCY" in output
        assert "PUBLISHER CLASSIFICATIONS" in output
        assert "regular_always_passing" in output

    def test_premarket_prefix(self):
        output = self._write_and_read(self._make_consistency(), session_prefix="PREMARKET ")
        assert "PREMARKET PUBLISHER CONSISTENCY" in output
        assert "PREMARKET PUBLISHER CLASSIFICATIONS" in output
        assert "premarket_always_passing" in output
        # Should NOT contain regular_ prefix
        assert "regular_always_passing" not in output

    def test_overnight_prefix(self):
        output = self._write_and_read(self._make_consistency(), session_prefix="OVERNIGHT ")
        assert "OVERNIGHT PUBLISHER CONSISTENCY" in output
        assert "overnight_always_passing" in output
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_feed_readiness.py::TestWritePublisherConsistencyCsv -v`
Expected: FAIL — `write_publisher_consistency_csv` doesn't accept `session_prefix`.

**Step 3: Add `session_prefix` parameter to `write_publisher_consistency_csv` (line 849)**

```python
def write_publisher_consistency_csv(
    writer: csv.writer,
    consistency: dict,
    session_prefix: str = "",
) -> None:
    label_prefix = session_prefix.lower().replace(" ", "") + "_" if session_prefix else "regular_"

    writer.writerow([])
    writer.writerow([f"{session_prefix}PUBLISHER CONSISTENCY"])
    writer.writerow(
        [
            "publisher_id",
            "dates_seen",
            "pass_dates",
            "fail_dates",
            "pass_rate",
            "results",
        ]
    )

    for row in consistency["rows"]:
        results_str = ";".join(f"{date_value}:{status}" for date_value, status in row["results"].items())
        writer.writerow(
            [
                row["publisher_id"],
                row["dates_seen"],
                row["pass_count"],
                row["fail_count"],
                f"{row['pass_rate']:.2f}%" if row["pass_rate"] is not None else "",
                results_str,
            ]
        )

    writer.writerow([])
    writer.writerow([f"{session_prefix}PUBLISHER CLASSIFICATIONS"])
    _fmt = lambda ids: ";".join(str(x) for x in ids) if ids else ""
    writer.writerow([f"{label_prefix}always_passing", _fmt(consistency["classifications"]["always_passing"])])
    writer.writerow([f"{label_prefix}always_failing", _fmt(consistency["classifications"]["always_failing"])])
    writer.writerow([f"{label_prefix}intermittent",   _fmt(consistency["classifications"]["intermittent"])])
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_feed_readiness.py -v`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add feed_readiness.py tests/test_feed_readiness.py
git commit -m "feat: parameterize write_publisher_consistency_csv with session_prefix"
```

---

### Task 5: Test & parameterize `print_publisher_consistency`

**Files:**
- Modify: `feed_readiness.py:1297-1318` (add `session_prefix` parameter)
- Modify: `tests/test_feed_readiness.py` (add tests)

**Step 1: Write failing tests**

Append to `tests/test_feed_readiness.py`:

```python
class TestPrintPublisherConsistency:
    def _make_consistency(self):
        return {
            "dates": ["2026-02-17", "2026-02-18"],
            "rows": [
                {
                    "publisher_id": 19,
                    "dates_seen": 2,
                    "pass_count": 2,
                    "fail_count": 0,
                    "error_count": 0,
                    "pass_rate": 100.0,
                    "results": {"2026-02-17": "PASS", "2026-02-18": "PASS"},
                },
            ],
            "classifications": {
                "always_passing": [19],
                "always_failing": [],
                "intermittent": [],
            },
        }

    def test_regular_default(self, capsys):
        print_publisher_consistency(self._make_consistency())
        out = capsys.readouterr().out
        assert "REGULAR SESSION:" in out
        assert "Always passing:" in out

    def test_premarket_session(self, capsys):
        print_publisher_consistency(self._make_consistency(), session_prefix="PREMARKET ")
        out = capsys.readouterr().out
        assert "PREMARKET SESSION:" in out

    def test_overnight_session(self, capsys):
        print_publisher_consistency(self._make_consistency(), session_prefix="OVERNIGHT ")
        out = capsys.readouterr().out
        assert "OVERNIGHT SESSION:" in out
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_feed_readiness.py::TestPrintPublisherConsistency -v`
Expected: FAIL — `print_publisher_consistency` doesn't accept `session_prefix`.

**Step 3: Add `session_prefix` parameter (line 1297)**

```python
def print_publisher_consistency(consistency: dict, session_prefix: str = "") -> None:
    session_label = session_prefix.strip() if session_prefix else "REGULAR"

    print()
    print("=" * 70)
    print(f"PUBLISHER CONSISTENCY (across {len(consistency['dates'])} dates)")
    print("=" * 70)

    print(f"\n{session_label} SESSION:")
    print("  Publisher  Pass  Fail  Rate    Results")
    for row in consistency["rows"]:
        if row["dates_seen"] == 0:
            continue
        results_str = " ".join(f"{date_value}:{status}" for date_value, status in row["results"].items())
        rate_str = f"{row['pass_rate']:.1f}%" if row["pass_rate"] is not None else "N/A"
        print(
            f"  {row['publisher_id']:<9} {row['pass_count']:<5} "
            f"{row['fail_count']:<5} {rate_str:<7}  {results_str}"
        )

    print()
    print(f"  Always passing: {_format_id_list(consistency['classifications']['always_passing'])}")
    print(f"  Always failing: {_format_id_list(consistency['classifications']['always_failing'])}")
    print(f"  Intermittent: {_format_id_list(consistency['classifications']['intermittent'])}")
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_feed_readiness.py -v`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add feed_readiness.py tests/test_feed_readiness.py
git commit -m "feat: parameterize print_publisher_consistency with session_prefix"
```

---

### Task 6: Wire session consistency into `write_results_csv`

**Files:**
- Modify: `feed_readiness.py:1076-1078` (add session calls after regular-hours call)

**Step 1: Write failing test for CSV integration**

Append to `tests/test_feed_readiness.py`:

```python
import tempfile
from pathlib import Path
from feed_readiness import write_results_csv


class TestWriteResultsCsvSessionConsistency:
    def _make_multi_date_results(self):
        """Two dates with session data for premarket and overnight."""
        details_d1 = [
            make_detail(
                publisher_id=19, fully_passes=True, benchmark_passes=True, uptime_passes=True,
                premarket_benchmark_passes=True, premarket_uptime_passes=True, premarket_uptime_pct=99.0,
                overnight_benchmark_passes=True, overnight_uptime_passes=True, overnight_uptime_pct=98.0,
            ),
            make_detail(
                publisher_id=20, fully_passes=False,
                premarket_benchmark_passes=False, premarket_uptime_passes=True, premarket_uptime_pct=80.0,
                overnight_uptime_pct=None,  # no overnight data
            ),
        ]
        details_d2 = [
            make_detail(
                publisher_id=19, fully_passes=True, benchmark_passes=True, uptime_passes=True,
                premarket_benchmark_passes=True, premarket_uptime_passes=True, premarket_uptime_pct=99.0,
                overnight_benchmark_passes=False, overnight_uptime_passes=True, overnight_uptime_pct=95.0,
            ),
            make_detail(
                publisher_id=20, fully_passes=False,
                premarket_benchmark_passes=True, premarket_uptime_passes=True, premarket_uptime_pct=95.0,
                overnight_uptime_pct=None,  # no overnight data
            ),
        ]
        return [
            make_result(feed_id=100, date="2026-02-17", details=details_d1),
            make_result(feed_id=100, date="2026-02-18", details=details_d2),
        ]

    def test_no_session_sections_without_flags(self):
        results = self._make_multi_date_results()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            path = Path(f.name)
        write_results_csv(results, path, include_extended_hours=False, include_overnight=False, include_detailed=True)
        content = path.read_text()
        assert "PUBLISHER CONSISTENCY" in content
        assert "PREMARKET PUBLISHER CONSISTENCY" not in content
        assert "OVERNIGHT PUBLISHER CONSISTENCY" not in content
        path.unlink()

    def test_extended_hours_adds_premarket_afterhours(self):
        results = self._make_multi_date_results()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            path = Path(f.name)
        write_results_csv(results, path, include_extended_hours=True, include_overnight=False, include_detailed=True)
        content = path.read_text()
        assert "PUBLISHER CONSISTENCY" in content
        assert "PREMARKET PUBLISHER CONSISTENCY" in content
        assert "PREMARKET PUBLISHER CLASSIFICATIONS" in content
        assert "premarket_always_passing" in content
        assert "AFTERHOURS PUBLISHER CONSISTENCY" in content
        assert "OVERNIGHT PUBLISHER CONSISTENCY" not in content
        path.unlink()

    def test_overnight_adds_overnight_section(self):
        results = self._make_multi_date_results()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            path = Path(f.name)
        write_results_csv(results, path, include_extended_hours=False, include_overnight=True, include_detailed=True)
        content = path.read_text()
        assert "OVERNIGHT PUBLISHER CONSISTENCY" in content
        assert "overnight_always_passing" in content
        assert "PREMARKET PUBLISHER CONSISTENCY" not in content
        path.unlink()

    def test_both_flags_all_sections(self):
        results = self._make_multi_date_results()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            path = Path(f.name)
        write_results_csv(results, path, include_extended_hours=True, include_overnight=True, include_detailed=True)
        content = path.read_text()
        assert "PUBLISHER CONSISTENCY" in content
        assert "PREMARKET PUBLISHER CONSISTENCY" in content
        assert "AFTERHOURS PUBLISHER CONSISTENCY" in content
        assert "OVERNIGHT PUBLISHER CONSISTENCY" in content
        path.unlink()

    def test_single_date_no_session_sections(self):
        """Session sections require multi-date, same as regular."""
        details = [
            make_detail(
                publisher_id=19, fully_passes=True, benchmark_passes=True, uptime_passes=True,
                premarket_benchmark_passes=True, premarket_uptime_passes=True, premarket_uptime_pct=99.0,
            ),
        ]
        results = [make_result(feed_id=100, date="2026-02-17", details=details)]
        with tempfile.NamedTemporaryFile(mode="w", suffix=".csv", delete=False) as f:
            path = Path(f.name)
        write_results_csv(results, path, include_extended_hours=True, include_overnight=True, include_detailed=True)
        content = path.read_text()
        assert "PREMARKET PUBLISHER CONSISTENCY" not in content
        path.unlink()
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_feed_readiness.py::TestWriteResultsCsvSessionConsistency -v`
Expected: FAIL — session sections not being written.

**Step 3: Add session consistency calls in `write_results_csv` (after line 1078)**

At line 1076-1078 (existing code):
```python
            consistency = compute_publisher_consistency(results)
            if len(consistency["dates"]) > 1 and consistency["rows"]:
                write_publisher_consistency_csv(writer, consistency)
```

Add after line 1078:

```python
            # Per-session consistency (only for multi-date with session flags)
            if include_extended_hours:
                for session_name, extractor in [("PREMARKET", _premarket_status), ("AFTERHOURS", _afterhours_status)]:
                    session_consistency = compute_publisher_consistency(results, status_extractor=extractor)
                    if len(session_consistency["dates"]) > 1 and session_consistency["rows"]:
                        write_publisher_consistency_csv(writer, session_consistency, session_prefix=f"{session_name} ")

            if include_overnight:
                session_consistency = compute_publisher_consistency(results, status_extractor=_overnight_status)
                if len(session_consistency["dates"]) > 1 and session_consistency["rows"]:
                    write_publisher_consistency_csv(writer, session_consistency, session_prefix="OVERNIGHT ")
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/test_feed_readiness.py -v`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add feed_readiness.py tests/test_feed_readiness.py
git commit -m "feat: wire session consistency sections into write_results_csv"
```

---

### Task 7: Wire session consistency into `main` console output

**Files:**
- Modify: `feed_readiness.py:1564-1567` (add session console prints after regular)

**Step 1: Add session console prints after regular-hours print (line 1567)**

At lines 1564-1567 (existing code):
```python
    if args.detailed and len({result.date for result in results}) > 1:
        consistency = compute_publisher_consistency(results)
        if consistency["rows"]:
            print_publisher_consistency(consistency)
```

Add after line 1567:

```python
        # Per-session consistency console output
        if args.extended_hours:
            for session_name, extractor in [("PREMARKET", _premarket_status), ("AFTERHOURS", _afterhours_status)]:
                session_consistency = compute_publisher_consistency(results, status_extractor=extractor)
                if session_consistency["rows"]:
                    print_publisher_consistency(session_consistency, session_prefix=f"{session_name} ")

        if args.overnight:
            session_consistency = compute_publisher_consistency(results, status_extractor=_overnight_status)
            if session_consistency["rows"]:
                print_publisher_consistency(session_consistency, session_prefix="OVERNIGHT ")
```

**Step 2: Verify no import issues**

Run: `python3 -c "from feed_readiness import main"`
Expected: No errors.

**Step 3: Commit**

```bash
git add feed_readiness.py
git commit -m "feat: add session consistency to console output in main"
```

---

### Task 8: Update documentation

**Files:**
- Modify: `docs/feed_readiness.md:148-157` (extend consistency section docs)
- Modify: `CLAUDE.md` (update feed readiness detailed output description)

**Step 1: Update `docs/feed_readiness.md`**

Replace the consistency section (lines 148-157) with:

```markdown
### Consistency section (multi-date + `--detailed`)

When multiple dates are evaluated, CSV appends:

- `PUBLISHER CONSISTENCY` (cross-date pass/fail matrix for regular hours)
- `PUBLISHER CLASSIFICATIONS`
  - `regular_always_passing`
  - `regular_always_failing`
  - `regular_intermittent`

With `--extended-hours`, additional sections are appended for each extended session:

- `PREMARKET PUBLISHER CONSISTENCY` + `PREMARKET PUBLISHER CLASSIFICATIONS`
  - `premarket_always_passing`, `premarket_always_failing`, `premarket_intermittent`
- `AFTERHOURS PUBLISHER CONSISTENCY` + `AFTERHOURS PUBLISHER CLASSIFICATIONS`
  - `afterhours_always_passing`, `afterhours_always_failing`, `afterhours_intermittent`

With `--overnight`, an additional section is appended:

- `OVERNIGHT PUBLISHER CONSISTENCY` + `OVERNIGHT PUBLISHER CLASSIFICATIONS`
  - `overnight_always_passing`, `overnight_always_failing`, `overnight_intermittent`

Session consistency uses the same pass logic as regular hours: a publisher PASSES a session if both session-specific benchmark AND session-specific uptime pass. Publishers with no data for a session (0% uptime or null) are excluded from that session's table.
```

**Step 2: Update `CLAUDE.md` feed readiness detailed output section**

In the `CLAUDE.md` section about `--detailed` output, add a note about session consistency sections appearing with `--extended-hours` / `--overnight`.

**Step 3: Commit**

```bash
git add docs/feed_readiness.md CLAUDE.md
git commit -m "docs: document per-session consistency and classification sections"
```

---

### Task 9: End-to-end validation with sample data

**Step 1: Run with sample 3025.csv-equivalent flags**

Run: `source venv/bin/activate && python3 feed_readiness.py --feed-id 3025 --start-date 2026-02-16 --end-date 2026-02-19 --mode us-equities --extended-hours --overnight --detailed --output /tmp/test_3025_sessions.csv --skip-scipy-tests`

Expected: Output includes all four consistency/classification section pairs (REGULAR, PREMARKET, AFTERHOURS, OVERNIGHT).

**Step 2: Verify CSV output**

Check the output CSV contains session sections:
```bash
grep "PUBLISHER CONSISTENCY" /tmp/test_3025_sessions.csv
grep "PUBLISHER CLASSIFICATIONS" /tmp/test_3025_sessions.csv
```

Expected output (4 consistency headers, 4 classification headers):
```
PUBLISHER CONSISTENCY
PREMARKET PUBLISHER CONSISTENCY
AFTERHOURS PUBLISHER CONSISTENCY
OVERNIGHT PUBLISHER CONSISTENCY
PUBLISHER CLASSIFICATIONS
PREMARKET PUBLISHER CLASSIFICATIONS
AFTERHOURS PUBLISHER CLASSIFICATIONS
OVERNIGHT PUBLISHER CLASSIFICATIONS
```

**Step 3: Run full test suite**

Run: `pytest tests/test_feed_readiness.py -v`
Expected: All tests PASS.

**Step 4: Commit (if any fixes needed)**

```bash
git add -A && git commit -m "fix: address issues found in e2e validation"
```

---

### Task 10: Final test suite run & cleanup

**Step 1: Run all tests**

Run: `pytest tests/ -v`
Expected: All existing + new tests PASS.

**Step 2: Final commit if needed**

No commit needed if all clean.
