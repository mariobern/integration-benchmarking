# Bulk Feeds DQ Runner Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `evaluate_feeds_bulk.py` — a sequential, subprocess-based bulk DQ runner that calls `evaluate_feed_standalone.py` once per CSV row, replacing the papermill-on-notebook flow without touching any existing files.

**Architecture:** New module + tests, no edits to existing code. `main()` parses CLI args → `process_csv()` iterates rows → `compute_times_from_mode()` resolves NY→UTC times → `run_standalone()` invokes the engine via `subprocess.run([sys.executable, "-m", "...evaluate_feed_standalone", ...])`. Per-row failures are tracked but never abort the batch. Exit code is 0 iff every row succeeded.

**Tech Stack:** Python 3 (stdlib only — `argparse`, `csv`, `subprocess`, `sys`, `datetime`, `pathlib`, `zoneinfo`), pytest 7.4.4, `unittest.mock` (stdlib).

**Spec:** [`docs/superpowers/specs/2026-05-07-bulk-feeds-dq-runner-design.md`](../specs/2026-05-07-bulk-feeds-dq-runner-design.md)

---

## File Structure

```
pythresearch/data_quality/lazer/
├── evaluate_feeds_bulk.py            (NEW — bulk runner module)
├── evaluate_feeds.py                 (UNTOUCHED — papermill loop, original)
├── evaluate_feed_standalone.py       (UNTOUCHED — engine)
├── publisher_benchmark_eval.ipynb    (UNTOUCHED — interactive)
├── evaluate_feeds_against_benchmark.sh (UNTOUCHED — legacy bash)
└── tests/
    ├── __init__.py                   (NEW — empty, makes tests a package)
    └── test_evaluate_feeds_bulk.py   (NEW — 13 pytest tests)
```

**Module responsibilities:**

- `evaluate_feeds_bulk.py`: 4 functions — `compute_times_from_mode` (pure helper), `run_standalone` (single subprocess invocation), `process_csv` (row loop + result tracking), `main` (argparse + glue + exit code).
- `tests/test_evaluate_feeds_bulk.py`: unit tests for all 4 functions, mocking `subprocess.run` so no engine is actually executed.

---

## Test Run Commands (used throughout the plan)

From repo root `/home/mariobern/research`:

```bash
# Run all tests in this module
pytest pythresearch/data_quality/lazer/tests/test_evaluate_feeds_bulk.py -v

# Run a single test
pytest pythresearch/data_quality/lazer/tests/test_evaluate_feeds_bulk.py::test_NAME -v
```

---

## Task 1: Bootstrap test package

**Files:**
- Create: `pythresearch/data_quality/lazer/tests/__init__.py`

- [ ] **Step 1: Create the empty test package init**

```bash
mkdir -p pythresearch/data_quality/lazer/tests
```

Create `pythresearch/data_quality/lazer/tests/__init__.py` as an empty file (zero bytes).

- [ ] **Step 2: Verify pytest can discover the new tests directory**

Run: `pytest pythresearch/data_quality/lazer/tests --collect-only`
Expected: exits 5 (no tests collected) OR exits 0 with empty collection — both acceptable. The directory must not error.

- [ ] **Step 3: Commit**

```bash
git add pythresearch/data_quality/lazer/tests/__init__.py
git commit -m "test: bootstrap tests package for lazer DQ"
```

---

## Task 2: Implement `compute_times_from_mode`

**Files:**
- Create: `pythresearch/data_quality/lazer/evaluate_feeds_bulk.py`
- Modify: `pythresearch/data_quality/lazer/tests/test_evaluate_feeds_bulk.py`

This task uses TDD: write 4 tests for the 4 mode branches, watch them fail, implement the function, watch them pass.

**Why these specific test dates:** The first three tests use `2026-05-04` (in EDT, UTC-4) so we exercise daylight-saving handling. The default-mode test uses `2026-12-15` (in EST, UTC-5) so we cover non-DST too. The function must produce correct UTC strings for both regimes — `zoneinfo` does this automatically as long as we go through `astimezone(UTC)`, but the tests pin it down.

- [ ] **Step 1: Write the four failing tests**

Create `pythresearch/data_quality/lazer/tests/test_evaluate_feeds_bulk.py` with this content:

```python
"""Unit tests for evaluate_feeds_bulk.

All tests mock subprocess.run so no real engine ever executes.
"""
import sys
from unittest.mock import MagicMock

import pytest

from pythresearch.data_quality.lazer.evaluate_feeds_bulk import (
    compute_times_from_mode,
    run_standalone,
    process_csv,
    main,
)


# ---------- compute_times_from_mode ----------

def test_time_computation_us_equities_pre():
    # 2026-05-04 is EDT (UTC-4): 08:30 NY -> 12:30 UTC, 09:30 NY -> 13:30 UTC.
    assert compute_times_from_mode("2026-05-04", "us-equities-pre") == ("12:30:00", "13:30:00")


def test_time_computation_us_equities_post():
    # EDT: 16:30 NY -> 20:30 UTC, 17:30 NY -> 21:30 UTC.
    assert compute_times_from_mode("2026-05-04", "us-equities-post") == ("20:30:00", "21:30:00")


def test_time_computation_us_equities_overnight():
    # EDT: 20:00 NY -> 00:00 UTC (next day), 21:00 NY -> 01:00 UTC.
    # The function returns HH:MM:SS only; the date-rollover is handled downstream
    # by the engine when it builds full timestamps from --date + --start-time.
    assert compute_times_from_mode("2026-05-04", "us-equities-overnight") == ("00:00:00", "01:00:00")


def test_time_computation_default_mode():
    # 2026-12-15 is EST (UTC-5): 09:30 NY -> 14:30 UTC, 10:30 NY -> 15:30 UTC.
    # "us-equities" (and any unknown mode) hits the default branch.
    assert compute_times_from_mode("2026-12-15", "us-equities") == ("14:30:00", "15:30:00")
```

- [ ] **Step 2: Run tests — expect failure (ImportError)**

Run: `pytest pythresearch/data_quality/lazer/tests/test_evaluate_feeds_bulk.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'pythresearch.data_quality.lazer.evaluate_feeds_bulk'`. That's the right kind of failure: tests can't even import yet.

- [ ] **Step 3: Implement minimal module skeleton + the function**

Create `pythresearch/data_quality/lazer/evaluate_feeds_bulk.py` with this content:

```python
#!/usr/bin/env python3
"""Bulk DQ runner — calls evaluate_feed_standalone.py once per CSV row.

Replaces the papermill-on-notebook flow in evaluate_feeds.py with subprocess
calls to the standalone engine. Same CSV format (feed_id, date, mode), same
outputs, no notebook artifacts.

Run:
    python3 -m pythresearch.data_quality.lazer.evaluate_feeds_bulk \\
        --csv MV_Mario_1.csv --cluster lazer-prod
"""
import argparse
import csv as csv_mod
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ENGINE_MODULE = "pythresearch.data_quality.lazer.evaluate_feed_standalone"


def compute_times_from_mode(date: str, mode: str) -> tuple[str, str]:
    """Resolve (start_utc, end_utc) HH:MM:SS strings from CSV mode + date.

    NY-time market windows are converted to UTC using zoneinfo, which handles
    EDT/EST automatically based on the date.
    """
    mode_lower = mode.lower()
    if mode_lower == "us-equities-pre":
        start_ny, end_ny = "08:30:00", "09:30:00"
    elif mode_lower == "us-equities-post":
        start_ny, end_ny = "16:30:00", "17:30:00"
    elif mode_lower == "us-equities-overnight":
        start_ny, end_ny = "20:00:00", "21:00:00"
    else:
        start_ny, end_ny = "09:30:00", "10:30:00"

    def _ny_to_utc(t: str) -> str:
        dt = datetime.strptime(f"{date} {t}", "%Y-%m-%d %H:%M:%S")
        dt_ny = dt.replace(tzinfo=ZoneInfo("America/New_York"))
        dt_utc = dt_ny.astimezone(ZoneInfo("UTC"))
        return dt_utc.strftime("%H:%M:%S")

    return _ny_to_utc(start_ny), _ny_to_utc(end_ny)


def run_standalone(*args, **kwargs) -> bool:
    """Stub — implemented in Task 3."""
    raise NotImplementedError


def process_csv(*args, **kwargs):
    """Stub — implemented in Task 4."""
    raise NotImplementedError


def main():
    """Stub — implemented in Task 6."""
    raise NotImplementedError


if __name__ == "__main__":
    main()
```

The stubs let the test file import all four names without errors. We fill them in across Tasks 3-6.

- [ ] **Step 4: Run tests — expect pass on the four time tests**

Run: `pytest pythresearch/data_quality/lazer/tests/test_evaluate_feeds_bulk.py -v -k "time_computation"`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add pythresearch/data_quality/lazer/evaluate_feeds_bulk.py pythresearch/data_quality/lazer/tests/test_evaluate_feeds_bulk.py
git commit -m "feat: add compute_times_from_mode for bulk DQ runner"
```

---

## Task 3: Implement `run_standalone`

**Files:**
- Modify: `pythresearch/data_quality/lazer/evaluate_feeds_bulk.py` (replace `run_standalone` stub)
- Modify: `pythresearch/data_quality/lazer/tests/test_evaluate_feeds_bulk.py` (append test)

- [ ] **Step 1: Write the failing argv-construction test**

Append to `pythresearch/data_quality/lazer/tests/test_evaluate_feeds_bulk.py`:

```python
# ---------- run_standalone ----------

def test_argv_construction(monkeypatch):
    """run_standalone builds the exact argv expected by evaluate_feed_standalone."""
    captured = []

    def fake_run(argv, check=False):
        captured.append(argv)
        return MagicMock(returncode=0)

    monkeypatch.setattr("pythresearch.data_quality.lazer.evaluate_feeds_bulk.subprocess.run", fake_run)

    ok = run_standalone(
        feed_id="1021",
        date="2026-05-04",
        mode="us-equities",
        cluster="lazer-prod",
        start_time="13:30:00",
        end_time="14:30:00",
        output_path="dq_reports",
        target_pub_count=4,
    )

    assert ok is True
    assert len(captured) == 1
    assert captured[0] == [
        sys.executable, "-m", "pythresearch.data_quality.lazer.evaluate_feed_standalone",
        "--feed-id", "1021",
        "--date", "2026-05-04",
        "--mode", "us-equities",
        "--cluster", "lazer-prod",
        "--start-time", "13:30:00",
        "--end-time", "14:30:00",
        "--output-path", "dq_reports",
        "--target-pub-count", "4",
    ]
```

- [ ] **Step 2: Run test — expect failure (NotImplementedError)**

Run: `pytest pythresearch/data_quality/lazer/tests/test_evaluate_feeds_bulk.py::test_argv_construction -v`
Expected: FAIL with `NotImplementedError`.

- [ ] **Step 3: Implement `run_standalone`**

In `evaluate_feeds_bulk.py`, replace the `run_standalone` stub with:

```python
def run_standalone(
    feed_id: str,
    date: str,
    mode: str,
    cluster: str,
    start_time: str,
    end_time: str,
    output_path: str,
    target_pub_count: int,
) -> bool:
    """Subprocess-call the engine for a single feed-day. True iff returncode == 0.

    Stdio is inherited from the parent so the engine's progress logs stream live.
    Any non-zero exit is treated as a soft failure: the caller continues to the
    next CSV row.
    """
    argv = [
        sys.executable, "-m", ENGINE_MODULE,
        "--feed-id", str(feed_id),
        "--date", date,
        "--mode", mode,
        "--cluster", cluster,
        "--start-time", start_time,
        "--end-time", end_time,
        "--output-path", output_path,
        "--target-pub-count", str(target_pub_count),
    ]
    print(f"  Executing engine for {feed_id} (mode: {mode}, cluster: {cluster})...")
    try:
        result = subprocess.run(argv, check=False)
    except Exception as e:
        print(f"  Error: Engine invocation raised for {feed_id}: {e}")
        return False
    if result.returncode == 0:
        print(f"  Engine execution successful for {feed_id}.")
        return True
    print(f"  Error: Engine execution failed for {feed_id} (exit {result.returncode}).")
    return False
```

- [ ] **Step 4: Run all tests written so far — expect all to pass**

Run: `pytest pythresearch/data_quality/lazer/tests/test_evaluate_feeds_bulk.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add pythresearch/data_quality/lazer/evaluate_feeds_bulk.py pythresearch/data_quality/lazer/tests/test_evaluate_feeds_bulk.py
git commit -m "feat: add run_standalone subprocess wrapper for bulk DQ runner"
```

---

## Task 4: Implement `process_csv` — iteration + parsing tolerance

**Files:**
- Modify: `pythresearch/data_quality/lazer/evaluate_feeds_bulk.py` (replace `process_csv` stub)
- Modify: `pythresearch/data_quality/lazer/tests/test_evaluate_feeds_bulk.py` (append 4 tests)

This task covers test 5 (CLI override) and tests 7–9 (CSV parsing tolerance). Result-tracking tests (11–13) come in Task 5 once we know the function returns counts.

- [ ] **Step 1: Write four failing tests**

Append to `tests/test_evaluate_feeds_bulk.py`:

```python
# ---------- process_csv: parsing & override behavior ----------

def _patch_subprocess(monkeypatch, returncodes=None):
    """Helper: patch subprocess.run, return list that captures argvs.

    `returncodes` is a list of return codes to yield in order; if None, all 0.
    """
    captured = []
    rc_iter = iter(returncodes or [])

    def fake_run(argv, check=False):
        captured.append(argv)
        try:
            rc = next(rc_iter)
        except StopIteration:
            rc = 0
        return MagicMock(returncode=rc)

    monkeypatch.setattr(
        "pythresearch.data_quality.lazer.evaluate_feeds_bulk.subprocess.run",
        fake_run,
    )
    return captured


def test_cli_time_override_bypasses_mode_computation(tmp_path, monkeypatch):
    """When start_time_override and end_time_override are given, mode-derived times are ignored."""
    csv = tmp_path / "input.csv"
    # us-equities-pre would normally compute 12:30/13:30 UTC; override must win.
    csv.write_text("1021, 2026-05-04, us-equities-pre\n")
    captured = _patch_subprocess(monkeypatch)

    process_csv(
        csv_file=csv,
        cluster="lazer-prod",
        start_time_override="18:00:00",
        end_time_override="19:00:00",
        output_path="dq_reports",
        target_pub_count=4,
    )

    assert len(captured) == 1
    argv = captured[0]
    assert argv[argv.index("--start-time") + 1] == "18:00:00"
    assert argv[argv.index("--end-time") + 1] == "19:00:00"


def test_csv_skips_blank_lines(tmp_path, monkeypatch):
    csv = tmp_path / "input.csv"
    csv.write_text(
        "1021, 2026-05-04, us-equities\n"
        "\n"
        "   \n"
        "3226, 2026-05-04, us-equities\n"
    )
    captured = _patch_subprocess(monkeypatch)

    process_csv(
        csv_file=csv,
        cluster="lazer-prod",
        start_time_override=None,
        end_time_override=None,
        output_path="dq_reports",
        target_pub_count=4,
    )

    assert len(captured) == 2  # only the two non-blank rows


def test_csv_skips_short_rows(tmp_path, monkeypatch):
    csv = tmp_path / "input.csv"
    csv.write_text(
        "1021, 2026-05-04, us-equities\n"
        "foobar\n"            # 1 column — skip
        "3226, 2026-05-04\n"  # 2 columns — skip
        "3227, 2026-05-04, us-equities\n"
    )
    captured = _patch_subprocess(monkeypatch)

    process_csv(
        csv_file=csv,
        cluster="lazer-prod",
        start_time_override=None,
        end_time_override=None,
        output_path="dq_reports",
        target_pub_count=4,
    )

    assert len(captured) == 2  # only the two complete rows


def test_csv_tolerates_whitespace(tmp_path, monkeypatch):
    """MV_Mario_1.csv-style leading spaces in cells are stripped."""
    csv = tmp_path / "input.csv"
    csv.write_text("  1021 ,  2026-05-04  ,  us-equities  \n")
    captured = _patch_subprocess(monkeypatch)

    process_csv(
        csv_file=csv,
        cluster="lazer-prod",
        start_time_override=None,
        end_time_override=None,
        output_path="dq_reports",
        target_pub_count=4,
    )

    assert len(captured) == 1
    argv = captured[0]
    assert argv[argv.index("--feed-id") + 1] == "1021"
    assert argv[argv.index("--date") + 1] == "2026-05-04"
    assert argv[argv.index("--mode") + 1] == "us-equities"
```

- [ ] **Step 2: Run tests — expect 4 failures (NotImplementedError)**

Run: `pytest pythresearch/data_quality/lazer/tests/test_evaluate_feeds_bulk.py -v`
Expected: 5 passed (from Tasks 2-3), 4 failed (the new ones, all `NotImplementedError`).

- [ ] **Step 3: Implement `process_csv`**

In `evaluate_feeds_bulk.py`, replace the `process_csv` stub with:

```python
def process_csv(
    csv_file: Path,
    cluster: str,
    start_time_override: str | None,
    end_time_override: str | None,
    output_path: str,
    target_pub_count: int,
) -> tuple[int, int, list[str]]:
    """Iterate the CSV and run the engine per row. Returns (succeeded, failed, failed_descriptors).

    failed_descriptors is a list like ["1021@2026-05-04", ...] for the end-of-run summary.
    Per-row failures never abort the batch.
    """
    succeeded = 0
    failed = 0
    failed_list: list[str] = []

    print("Starting batch processing of price_ids...")
    try:
        with open(csv_file, "r") as f:
            reader = csv_mod.reader(f)
            for row in reader:
                if not row or not row[0].strip():
                    continue
                if len(row) < 3:
                    print(f"  Warning: Skipping incomplete row: {row}")
                    continue

                feed_id = row[0].strip()
                date = row[1].strip()
                mode = row[2].strip()
                if not feed_id:
                    continue

                print(
                    f"--- Processing feed_id: {feed_id}, date: {date}, "
                    f"mode: {mode}, cluster: {cluster} ---"
                )

                if start_time_override and end_time_override:
                    start_time = start_time_override
                    end_time = end_time_override
                else:
                    start_time, end_time = compute_times_from_mode(date, mode)

                ok = run_standalone(
                    feed_id=feed_id,
                    date=date,
                    mode=mode,
                    cluster=cluster,
                    start_time=start_time,
                    end_time=end_time,
                    output_path=output_path,
                    target_pub_count=target_pub_count,
                )
                if ok:
                    succeeded += 1
                else:
                    failed += 1
                    failed_list.append(f"{feed_id}@{date}")
    except FileNotFoundError:
        print(f"Error: CSV file '{csv_file}' not found.")
        sys.exit(1)

    print("Batch processing complete.")
    return succeeded, failed, failed_list
```

- [ ] **Step 4: Run all tests — expect all 9 to pass**

Run: `pytest pythresearch/data_quality/lazer/tests/test_evaluate_feeds_bulk.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add pythresearch/data_quality/lazer/evaluate_feeds_bulk.py pythresearch/data_quality/lazer/tests/test_evaluate_feeds_bulk.py
git commit -m "feat: add process_csv loop + override + parsing tolerance"
```

---

## Task 5: `process_csv` result tracking + summary line via `main`

**Files:**
- Modify: `pythresearch/data_quality/lazer/tests/test_evaluate_feeds_bulk.py` (append 3 tests)

`process_csv` already returns `(succeeded, failed, failed_list)` from Task 4. The summary line and exit code live in `main`, which we'll implement in Task 6. We're writing the tests now so they'll be in place when `main` lands.

- [ ] **Step 1: Write three failing tests**

Append to `tests/test_evaluate_feeds_bulk.py`:

```python
# ---------- main: exit codes and summary ----------

def test_exit_code_zero_on_all_success(tmp_path, monkeypatch):
    csv = tmp_path / "input.csv"
    csv.write_text(
        "1021, 2026-05-04, us-equities\n"
        "3226, 2026-05-04, us-equities\n"
    )
    _patch_subprocess(monkeypatch)  # all returncodes default to 0
    monkeypatch.setattr(sys, "argv", [
        "evaluate_feeds_bulk", "--csv", str(csv), "--cluster", "lazer-prod"
    ])

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 0


def test_exit_code_one_on_any_failure(tmp_path, monkeypatch):
    csv = tmp_path / "input.csv"
    csv.write_text(
        "1021, 2026-05-04, us-equities\n"
        "3226, 2026-05-04, us-equities\n"
        "3227, 2026-05-04, us-equities\n"
    )
    # second row fails, others succeed — confirms batch continues past failure
    captured = _patch_subprocess(monkeypatch, returncodes=[0, 1, 0])
    monkeypatch.setattr(sys, "argv", [
        "evaluate_feeds_bulk", "--csv", str(csv), "--cluster", "lazer-prod"
    ])

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1
    assert len(captured) == 3  # all rows attempted


def test_summary_line_counts(tmp_path, monkeypatch, capsys):
    csv = tmp_path / "input.csv"
    csv.write_text(
        "1021, 2026-05-04, us-equities\n"
        "3226, 2026-05-04, us-equities\n"
    )
    _patch_subprocess(monkeypatch, returncodes=[1, 0])  # first fails, second ok
    monkeypatch.setattr(sys, "argv", [
        "evaluate_feeds_bulk", "--csv", str(csv), "--cluster", "lazer-prod"
    ])

    with pytest.raises(SystemExit):
        main()

    captured = capsys.readouterr()
    assert "Processed 2 feeds: 1 succeeded, 1 failed." in captured.out
    assert "1021@2026-05-04" in captured.out
```

- [ ] **Step 2: Run tests — expect 3 failures (`main` still raises NotImplementedError)**

Run: `pytest pythresearch/data_quality/lazer/tests/test_evaluate_feeds_bulk.py -v`
Expected: 9 passed, 3 failed (all in `main`-related tests).

These will go green in Task 6 when `main` lands. Don't commit yet — Task 6 packages the green together with the implementation.

---

## Task 6: Implement `main` (argparse + summary + exit code)

**Files:**
- Modify: `pythresearch/data_quality/lazer/evaluate_feeds_bulk.py` (replace `main` stub)
- Modify: `pythresearch/data_quality/lazer/tests/test_evaluate_feeds_bulk.py` (append 1 test)

- [ ] **Step 1: Write the missing-CSV failing test**

Append to `tests/test_evaluate_feeds_bulk.py`:

```python
def test_csv_missing_file_exits_1(tmp_path, monkeypatch):
    nonexistent = tmp_path / "nope.csv"
    monkeypatch.setattr(sys, "argv", [
        "evaluate_feeds_bulk", "--csv", str(nonexistent), "--cluster", "lazer-prod"
    ])

    with pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1
```

- [ ] **Step 2: Run tests — expect 4 still-failing main tests**

Run: `pytest pythresearch/data_quality/lazer/tests/test_evaluate_feeds_bulk.py -v`
Expected: 9 passed, 4 failed (3 from Task 5 + the new missing-file test).

- [ ] **Step 3: Implement `main`**

In `evaluate_feeds_bulk.py`, replace the `main` stub with:

```python
def main():
    parser = argparse.ArgumentParser(
        description="Bulk DQ evaluation: subprocess-call evaluate_feed_standalone.py for each CSV row.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  python3 -m pythresearch.data_quality.lazer.evaluate_feeds_bulk --cluster lazer-prod
  python3 -m pythresearch.data_quality.lazer.evaluate_feeds_bulk --csv MV_Mario_1.csv --cluster lazer-prod
""",
    )
    parser.add_argument("--csv", default="price_id_list.csv",
                        help="CSV: feed_id,date,mode per row (default: price_id_list.csv)")
    parser.add_argument("--cluster", required=True,
                        help="Cluster name (e.g. lazer-prod)")
    parser.add_argument("--start-time", default=None,
                        help="Override start time HH:MM:SS UTC (default: per-row from mode)")
    parser.add_argument("--end-time", default=None,
                        help="Override end time HH:MM:SS UTC (default: per-row from mode)")
    parser.add_argument("--output-path", default="dq_reports",
                        help="Base output dir (default: dq_reports)")
    parser.add_argument("--target-pub-count", type=int, default=4,
                        help="Target publisher count (default: 4)")

    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"Error: CSV file '{csv_path}' not found.")
        sys.exit(1)

    succeeded, failed, failed_list = process_csv(
        csv_file=csv_path,
        cluster=args.cluster,
        start_time_override=args.start_time,
        end_time_override=args.end_time,
        output_path=args.output_path,
        target_pub_count=args.target_pub_count,
    )

    total = succeeded + failed
    print(f"Processed {total} feeds: {succeeded} succeeded, {failed} failed.")
    if failed_list:
        print(f"Failed: {failed_list}")
    sys.exit(0 if failed == 0 else 1)
```

- [ ] **Step 4: Run all tests — expect 13 passed**

Run: `pytest pythresearch/data_quality/lazer/tests/test_evaluate_feeds_bulk.py -v`
Expected: **13 passed**, matching the spec's test count exactly.

- [ ] **Step 5: Spot-check the CLI manually**

Run: `python3 -m pythresearch.data_quality.lazer.evaluate_feeds_bulk --help`
Expected: argparse `--help` output showing all 6 flags. No traceback.

Run with a missing CSV to confirm exit code:

```bash
python3 -m pythresearch.data_quality.lazer.evaluate_feeds_bulk --csv /tmp/no-such.csv --cluster lazer-prod
echo "exit code: $?"
```

Expected: `Error: CSV file '/tmp/no-such.csv' not found.` and `exit code: 1`.

- [ ] **Step 6: Commit**

```bash
git add pythresearch/data_quality/lazer/evaluate_feeds_bulk.py pythresearch/data_quality/lazer/tests/test_evaluate_feeds_bulk.py
git commit -m "feat: add main() argparse + summary + exit code for bulk DQ runner"
```

---

## Task 7: Manual end-to-end smoke test

**Files:** none modified — this is a runtime validation.

**Prerequisite:** the engine module must be importable. Confirm `pythresearch/data_quality/lazer/evaluate_feed_standalone.py` exists. (At time of writing it's untracked on `time-filter-queries` — `git ls-files | grep evaluate_feed_standalone` may return nothing, but the file is on disk and that's what matters for runtime.)

- [ ] **Step 1: Build a 2-row test CSV**

```bash
cat > /tmp/bulk_smoke.csv <<'EOF'
1021, 2026-05-04, us-equities
1060, 2026-05-04, us-equities
EOF
```

(Adjust feed_ids/dates if these specific ones don't have data in your ClickHouse cluster — pick two known-good rows from `MV_Mario_1.csv` that you've validated in single-feed mode previously.)

- [ ] **Step 2: Run the bulk runner**

```bash
python3 -m pythresearch.data_quality.lazer.evaluate_feeds_bulk \
    --csv /tmp/bulk_smoke.csv \
    --cluster lazer-prod \
    --output-path /tmp/dq_smoke
echo "exit: $?"
```

Expected:
- For each row: `Executing engine for ...` then engine progress (ClickHouse queries, `Saved all plots for feed ... to ...`, `Updated feed ... readiness in ...`).
- After loop: `Processed 2 feeds: 2 succeeded, 0 failed.` and `exit: 0`.

- [ ] **Step 3: Verify outputs exist on disk**

```bash
find /tmp/dq_smoke -type f | sort
```

Expected — 2× `plots.html` + 2× `stats.csv` + 1× `feed_readiness.csv`:

```
/tmp/dq_smoke/lazer-prod/us-equities/1021/2026-05-04/plots.html
/tmp/dq_smoke/lazer-prod/us-equities/1021/2026-05-04/stats.csv
/tmp/dq_smoke/lazer-prod/us-equities/1060/2026-05-04/plots.html
/tmp/dq_smoke/lazer-prod/us-equities/1060/2026-05-04/stats.csv
/tmp/dq_smoke/lazer-prod/us-equities/feed_readiness.csv
```

- [ ] **Step 4: Parity check vs. single-feed engine run**

For one row, run the engine directly and confirm outputs match:

```bash
python3 -m pythresearch.data_quality.lazer.evaluate_feed_standalone \
    --feed-id 1021 --date 2026-05-04 --mode us-equities \
    --cluster lazer-prod --start-time 13:30:00 --end-time 14:30:00 \
    --output-path /tmp/dq_solo
diff /tmp/dq_smoke/lazer-prod/us-equities/1021/2026-05-04/stats.csv \
     /tmp/dq_solo/lazer-prod/us-equities/1021/2026-05-04/stats.csv
```

Expected: `stats.csv` files identical (no `diff` output). `plots.html` will likely diff on plot IDs / timestamps embedded by plotly even for the same input — that's not a parity bug, ignore.

- [ ] **Step 5: Failure-path smoke test**

```bash
cat > /tmp/bulk_smoke_bad.csv <<'EOF'
1021, 2026-05-04, us-equities
99999999, 2026-05-04, us-equities
1060, 2026-05-04, us-equities
EOF

python3 -m pythresearch.data_quality.lazer.evaluate_feeds_bulk \
    --csv /tmp/bulk_smoke_bad.csv \
    --cluster lazer-prod \
    --output-path /tmp/dq_smoke_bad
echo "exit: $?"
```

Expected: middle row fails (no data for bogus feed_id), but the third row still runs. Final summary: `Processed 3 feeds: 2 succeeded, 1 failed.`, `Failed: ['99999999@2026-05-04']`, `exit: 1`.

If the middle row succeeds (because the engine doesn't error on empty data), pick a more reliably-bad input — e.g., a clearly invalid date format, or run with `--cluster nope` to force a connection error.

---

## Task 8: Self-review checklist

- [ ] **Step 1: Re-run the full unit test suite**

Run: `pytest pythresearch/data_quality/lazer/tests/test_evaluate_feeds_bulk.py -v`
Expected: 13 passed.

- [ ] **Step 2: Confirm no edits leaked to the four "untouched" files**

Run:

```bash
git log --oneline main..HEAD -- \
    pythresearch/data_quality/lazer/evaluate_feeds.py \
    pythresearch/data_quality/lazer/evaluate_feed_standalone.py \
    pythresearch/data_quality/lazer/publisher_benchmark_eval.ipynb \
    pythresearch/data_quality/lazer/evaluate_feeds_against_benchmark.sh
```

Expected: empty output (no commits on this branch touched those files).

- [ ] **Step 3: Confirm the three new files were added**

Run: `git log --name-only main..HEAD --diff-filter=A -- pythresearch/data_quality/lazer/`
Expected output includes:
- `pythresearch/data_quality/lazer/evaluate_feeds_bulk.py`
- `pythresearch/data_quality/lazer/tests/__init__.py`
- `pythresearch/data_quality/lazer/tests/test_evaluate_feeds_bulk.py`

- [ ] **Step 4 (optional): Coverage measurement**

If you want explicit coverage numbers, install `pytest-cov` once per env:

```bash
pip install pytest-cov
pytest pythresearch/data_quality/lazer/tests/test_evaluate_feeds_bulk.py -v \
    --cov=pythresearch.data_quality.lazer.evaluate_feeds_bulk \
    --cov-report=term-missing
```

Expected: ≥80% line coverage on `evaluate_feeds_bulk.py`. The only intentionally-uncovered branch is the `except Exception` in `run_standalone` (defensive against `subprocess.run` raising — unreachable in normal flow). If coverage drops below 80%, look for branches added in implementation that aren't in the test list above and either add a test or remove the branch.

- [ ] **Step 5: Final task-list check**

Mentally check each spec requirement against this plan:

| Spec requirement | Task |
|---|---|
| New `evaluate_feeds_bulk.py` file, no edits to existing files | Tasks 2-6, verified in Task 8 step 2 |
| `compute_times_from_mode` for 4 modes | Task 2 |
| `run_standalone` shells out via `subprocess.run`, sys.executable, ENGINE_MODULE | Task 3 |
| `process_csv` iterates, tolerates whitespace/blanks/short rows, applies override | Task 4 |
| Per-row failure → continue, no retries | Task 4 (in `process_csv` impl, not aborting on `ok=False`) |
| End-of-run summary line + failed list | Task 6 (`main`) |
| Exit code 0 on full success, 1 on any failure | Task 6 (`main`) |
| Missing CSV → print + sys.exit(1) | Task 6 (`main`) — explicit `csv_path.exists()` check |
| 13 pytest tests covering specified cases | Tasks 2, 3, 4, 5, 6 (4+1+4+3+1 = 13) |
| Outputs identical to old papermill flow | Task 7 (parity check on `stats.csv`) |

---

## Self-Review (against the spec — done by author)

- **Coverage of spec sections:**
  - Problem / Goals / Non-Goals → reflected in Goal/Architecture/Scope of this plan.
  - Approach (subprocess loop) → Tasks 3, 4, 6.
  - Components (`compute_times_from_mode`, `run_standalone`, `process_csv`, `main`) → Tasks 2, 3, 4, 6.
  - Per-Row Execution Flow → Task 4 implementation matches the pseudocode in the spec.
  - CLI section → Task 6 implementation matches the flag table.
  - Outputs section → not implemented here (engine owns it); validated in Task 7.
  - Failure Handling → Task 4 (continue-on-failure) + Task 6 (summary, exit code, missing-CSV).
  - Validation Plan → Task 7 mirrors the spec's validation plan one-to-one.
  - Test list (13 named tests) → all present, count matches.

- **Placeholder scan:** no TBDs, no "implement later", no missing code blocks. All test code and implementation code is fully written in the steps.

- **Type/name consistency:**
  - `compute_times_from_mode(date: str, mode: str) -> tuple[str, str]` — same in stub (Task 2) and final impl.
  - `run_standalone(feed_id, date, mode, cluster, start_time, end_time, output_path, target_pub_count) -> bool` — same param order in test (Task 3), impl (Task 3), and call site (Task 4).
  - `process_csv(csv_file, cluster, start_time_override, end_time_override, output_path, target_pub_count) -> tuple[int, int, list[str]]` — same kwarg names in tests (Tasks 4, 5) and impl (Task 4).
  - `ENGINE_MODULE = "pythresearch.data_quality.lazer.evaluate_feed_standalone"` — referenced consistently by Task 3 impl + Task 3 test (which hardcodes the same string).
  - Failed-descriptor format `f"{feed_id}@{date}"` — same in impl (Task 4) and test assertion (Task 5).
  - Summary line `f"Processed {total} feeds: {succeeded} succeeded, {failed} failed."` — same in impl (Task 6) and test assertion (Task 5).

No issues found.
