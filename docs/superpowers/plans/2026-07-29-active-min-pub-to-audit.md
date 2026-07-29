# active_min_pub_to_audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `lazer_dq/active_min_pub_to_audit.py`, a thin CSV-only adapter that filters `active_min_pub.py` output down to `BREACH`/`CRITICAL` feed-sessions with `effective_min_pub >= 2`, producing a drop-in `--audit-csv` for the existing, unmodified Stage 2 (`qualify_candidates.py`) / Stage 3 (`apply_min_pub_remediation.py`) pipeline.

**Architecture:** Pure-function core (verdict/floor filtering, row reshaping, filename parsing) covered by unit tests, wrapped by a thin `argparse` CLI that reads one CSV and writes two (`..._flagged_...csv` for Stage 2, `..._excluded_...csv` for visibility). No ClickHouse client, no config file, no network calls — a pandas-free, dependency-free CSV transform using only the standard library `csv` module, matching the "no silent truncation" convention used elsewhere in this pipeline.

**Tech Stack:** Python 3, standard library only (`argparse`, `csv`, `re`, `collections.Counter`, `pathlib`), `pytest` for tests.

## Global Constraints

- Do not modify `lazer_dq/active_min_pub.py`, `lazer_dq/qualify_candidates.py`, `lazer_dq/apply_min_pub_remediation.py`, or `lazer_dq/audit_min_pub.py` — this is a new, additive, standalone script only.
- The flagged CSV's `classification` column must only ever contain the literal strings `"CRITICAL"` or `"WARN"` — `qualify_candidates.py` does `audit[audit["classification"].isin(["CRITICAL", "WARN"])]` and anything else silently vanishes from Stage 2.
- `min_pub_floor` defaults to `2` and must be CLI-tunable (`--min-pub-floor`), not hardcoded — matches the repo's existing tunable-threshold convention (`active_min_pub`'s `--critical-pct`/`--warn-pct`).
- No row may be silently dropped without being accounted for in either the flagged CSV, the excluded CSV, or the console summary's tallies (WARN-skip count when `--include-warn` is off).
- Run `pre-commit run --files <changed files>` before every commit (black, prettier, trailing whitespace, end-of-file fixer) per this repo's `CLAUDE.md`.
- New code follows this repo's existing style in `lazer_dq/active_min_pub.py`: `from __future__ import annotations`, module docstring with a `Run:` usage example, plain top-level functions (no classes), `argparse.ArgumentParser(description=__doc__)`.

---

## File Structure

- `lazer_dq/active_min_pub_to_audit.py` — new module. Pure functions (`target_verdicts`, `bucket_for_row`, `to_flagged_row`, `to_excluded_row`, `parse_window_from_filename`) plus `parse_args`/`main`.
- `lazer_dq/tests/test_active_min_pub_to_audit.py` — new test module, plain `pytest` functions, no ClickHouse mocking needed (this script never touches ClickHouse).
- `docs/active_min_pub_to_audit.md` — new usage doc.
- `CLAUDE.md` — one new Scripts-table row, one new Key Gotchas bullet.

---

### Task 1: Core filter/reshape functions

**Files:**
- Create: `lazer_dq/active_min_pub_to_audit.py`
- Test: `lazer_dq/tests/test_active_min_pub_to_audit.py`

**Interfaces:**
- Consumes: nothing (first task).
- Produces (used by Task 2):
  - `FLAGGED_COLUMNS: list[str]` — `["feed_id", "symbol", "session", "classification", "source_verdict", "asset_type", "effective_min_pub", "pct_below_par", "pct_at_par", "pct_at_floor", "pct_at_floor_1", "min", "median", "n_updates"]`
  - `EXCLUDED_COLUMNS: list[str]` — `["feed_id", "symbol", "session", "source_verdict", "effective_min_pub", "pct_at_floor", "reason"]`
  - `target_verdicts(include_warn: bool) -> frozenset[str]`
  - `bucket_for_row(row: dict, min_pub_floor: int, include_warn: bool) -> str` — returns `"flagged"`, `"excluded"`, or `"drop"`
  - `to_flagged_row(row: dict) -> dict` — keys match `FLAGGED_COLUMNS`
  - `to_excluded_row(row: dict, reason: str) -> dict` — keys match `EXCLUDED_COLUMNS`
  - `parse_window_from_filename(path: Path) -> str` — raises `ValueError` on an unparseable name
  - `parse_args(argv=None)` — `argparse` namespace with `.active_min_pub_csv`, `.min_pub_floor`, `.include_warn`, `.output_dir`

- [ ] **Step 1: Write the failing tests**

Create `lazer_dq/tests/test_active_min_pub_to_audit.py`:

```python
from pathlib import Path

import pytest

from lazer_dq.active_min_pub_to_audit import (
    EXCLUDED_COLUMNS,
    FLAGGED_COLUMNS,
    bucket_for_row,
    parse_window_from_filename,
    target_verdicts,
    to_excluded_row,
    to_flagged_row,
)


def _row(**overrides):
    base = {
        "feed_id": "100",
        "symbol": "Equity.US.FOO/USD",
        "asset_type": "equity",
        "session": "REGULAR",
        "effective_min_pub": "2",
        "n_updates": "1000",
        "min": "1",
        "p1": "1",
        "p5": "2",
        "median": "2",
        "pct_below_par": "2.0",
        "pct_at_par": "10.0",
        "pct_at_floor": "12.0",
        "pct_at_floor_1": "20.0",
        "verdict": "BREACH",
    }
    base.update(overrides)
    return base


def test_target_verdicts_excludes_warn_by_default():
    assert target_verdicts(include_warn=False) == {"BREACH", "CRITICAL"}


def test_target_verdicts_includes_warn_when_requested():
    assert target_verdicts(include_warn=True) == {"BREACH", "CRITICAL", "WARN"}


def test_bucket_breach_at_or_above_floor_is_flagged():
    assert bucket_for_row(_row(verdict="BREACH", effective_min_pub="2"), 2, False) == "flagged"


def test_bucket_critical_above_floor_is_flagged():
    assert bucket_for_row(_row(verdict="CRITICAL", effective_min_pub="3"), 2, False) == "flagged"


def test_bucket_critical_below_floor_is_excluded():
    assert bucket_for_row(_row(verdict="CRITICAL", effective_min_pub="1"), 2, False) == "excluded"


def test_bucket_breach_below_floor_is_excluded():
    assert bucket_for_row(_row(verdict="BREACH", effective_min_pub="1"), 2, False) == "excluded"


def test_bucket_warn_dropped_when_include_warn_off():
    assert bucket_for_row(_row(verdict="WARN", effective_min_pub="2"), 2, False) == "drop"


def test_bucket_warn_flagged_when_include_warn_on():
    assert bucket_for_row(_row(verdict="WARN", effective_min_pub="2"), 2, True) == "flagged"


def test_bucket_warn_excluded_when_include_warn_on_and_below_floor():
    assert bucket_for_row(_row(verdict="WARN", effective_min_pub="1"), 2, True) == "excluded"


def test_bucket_ok_is_always_dropped():
    assert bucket_for_row(_row(verdict="OK", effective_min_pub="5"), 2, True) == "drop"


def test_bucket_respects_custom_floor():
    # min_pub_floor=3: a CRITICAL row at effective_min_pub=2 no longer clears the bar.
    assert bucket_for_row(_row(verdict="CRITICAL", effective_min_pub="2"), 3, False) == "excluded"


def test_to_flagged_row_breach_maps_to_critical_classification():
    row = to_flagged_row(_row(verdict="BREACH"))
    assert row["classification"] == "CRITICAL"
    assert row["source_verdict"] == "BREACH"
    assert set(row.keys()) == set(FLAGGED_COLUMNS)


def test_to_flagged_row_critical_maps_to_critical_classification():
    row = to_flagged_row(_row(verdict="CRITICAL"))
    assert row["classification"] == "CRITICAL"
    assert row["source_verdict"] == "CRITICAL"


def test_to_flagged_row_warn_maps_to_warn_classification():
    row = to_flagged_row(_row(verdict="WARN"))
    assert row["classification"] == "WARN"
    assert row["source_verdict"] == "WARN"


def test_to_flagged_row_preserves_metrics():
    row = to_flagged_row(_row(pct_at_floor="12.0", n_updates="1000"))
    assert row["pct_at_floor"] == "12.0"
    assert row["n_updates"] == "1000"
    assert row["feed_id"] == "100"
    assert row["symbol"] == "Equity.US.FOO/USD"
    assert row["session"] == "REGULAR"


def test_to_excluded_row_shape_and_reason():
    row = to_excluded_row(_row(verdict="CRITICAL", effective_min_pub="1"), "min_pub_floor_1")
    assert set(row.keys()) == set(EXCLUDED_COLUMNS)
    assert row["reason"] == "min_pub_floor_1"
    assert row["source_verdict"] == "CRITICAL"
    assert row["effective_min_pub"] == "1"


def test_parse_window_from_filename_valid():
    stamp = parse_window_from_filename(Path("active_min_pub_2026-07-14_2026-07-22.csv"))
    assert stamp == "2026-07-14_2026-07-22"


def test_parse_window_from_filename_valid_with_directory_prefix():
    stamp = parse_window_from_filename(
        Path("output_csv/active_min_pub_2026-07-14_2026-07-22.csv")
    )
    assert stamp == "2026-07-14_2026-07-22"


def test_parse_window_from_filename_rejects_curated_snapshot():
    with pytest.raises(ValueError, match="active_min_pub_CRITICAL_2026-07-22.csv"):
        parse_window_from_filename(Path("active_min_pub_CRITICAL_2026-07-22.csv"))


def test_parse_window_from_filename_rejects_unrelated_name():
    with pytest.raises(ValueError):
        parse_window_from_filename(Path("min_pub_audit_2026-07-14_2026-07-22.csv"))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest lazer_dq/tests/test_active_min_pub_to_audit.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lazer_dq.active_min_pub_to_audit'`

- [ ] **Step 3: Write the implementation**

Create `lazer_dq/active_min_pub_to_audit.py`:

```python
"""Adapter: active_min_pub BREACH/CRITICAL feed-sessions -> Stage 2/3 audit CSV.

Filters an active_min_pub.py summary CSV down to feed-sessions whose verdict is
BREACH or CRITICAL (WARN too, with --include-warn) and whose effective_min_pub
is >= --min-pub-floor (default 2) -- min_pub == 1 feed-sessions are structurally
single-source (no second publisher to qualify against) and are written to a
separate excluded CSV instead of being silently dropped.

The flagged output is a drop-in --audit-csv for the existing, unmodified
qualify_candidates.py (Stage 2): that script only ever reads feed_id, session,
and classification from its --audit-csv, so any CSV carrying those three
columns with classification in {"CRITICAL", "WARN"} works unchanged.

Run:
    python3 -m lazer_dq.active_min_pub_to_audit \\
        --active-min-pub-csv output_csv/active_min_pub_2026-07-14_2026-07-22.csv \\
        [--min-pub-floor 2] [--include-warn] [--output-dir output_csv]
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path

FLAGGED_COLUMNS = [
    "feed_id",
    "symbol",
    "session",
    "classification",
    "source_verdict",
    "asset_type",
    "effective_min_pub",
    "pct_below_par",
    "pct_at_par",
    "pct_at_floor",
    "pct_at_floor_1",
    "min",
    "median",
    "n_updates",
]

EXCLUDED_COLUMNS = [
    "feed_id",
    "symbol",
    "session",
    "source_verdict",
    "effective_min_pub",
    "pct_at_floor",
    "reason",
]

_BASE_TARGET_VERDICTS = frozenset({"BREACH", "CRITICAL"})

_FILENAME_RE = re.compile(r"active_min_pub_(\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2})\.csv")


def target_verdicts(include_warn: bool) -> frozenset:
    """Verdicts this adapter routes forward, before the min_pub_floor split."""
    return _BASE_TARGET_VERDICTS | ({"WARN"} if include_warn else frozenset())


def bucket_for_row(row: dict, min_pub_floor: int, include_warn: bool) -> str:
    """'flagged' (-> Stage 2), 'excluded' (surfaced, not routed), or 'drop'."""
    if row["verdict"] not in target_verdicts(include_warn):
        return "drop"
    if int(row["effective_min_pub"]) >= min_pub_floor:
        return "flagged"
    return "excluded"


def to_flagged_row(row: dict) -> dict:
    """Shape a source active_min_pub row into a Stage-2-compatible flagged row.

    classification collapses BREACH and CRITICAL to the literal "CRITICAL" that
    qualify_candidates.py expects; the original verdict survives in
    source_verdict for human traceability.
    """
    classification = "WARN" if row["verdict"] == "WARN" else "CRITICAL"
    return {
        "feed_id": row["feed_id"],
        "symbol": row["symbol"],
        "session": row["session"],
        "classification": classification,
        "source_verdict": row["verdict"],
        "asset_type": row["asset_type"],
        "effective_min_pub": row["effective_min_pub"],
        "pct_below_par": row["pct_below_par"],
        "pct_at_par": row["pct_at_par"],
        "pct_at_floor": row["pct_at_floor"],
        "pct_at_floor_1": row["pct_at_floor_1"],
        "min": row["min"],
        "median": row["median"],
        "n_updates": row["n_updates"],
    }


def to_excluded_row(row: dict, reason: str) -> dict:
    return {
        "feed_id": row["feed_id"],
        "symbol": row["symbol"],
        "session": row["session"],
        "source_verdict": row["verdict"],
        "effective_min_pub": row["effective_min_pub"],
        "pct_at_floor": row["pct_at_floor"],
        "reason": reason,
    }


def parse_window_from_filename(path: Path) -> str:
    """Extract '<start>_<end>' from an active_min_pub_<start>_<end>.csv name.

    Raises ValueError (with the offending filename in the message) for any
    other name, including the hand-curated active_min_pub_CRITICAL_<date>.csv
    snapshot format, which this script does not consume.
    """
    m = _FILENAME_RE.fullmatch(path.name)
    if not m:
        raise ValueError(
            f"{path.name} doesn't match active_min_pub_<start>_<end>.csv -- pass "
            "a standard active_min_pub.py summary CSV, not a hand-curated snapshot"
        )
    return m.group(1)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--active-min-pub-csv", required=True)
    p.add_argument("--min-pub-floor", type=int, default=2)
    p.add_argument("--include-warn", action="store_true")
    p.add_argument("--output-dir", default="output_csv")
    return p.parse_args(argv)


if __name__ == "__main__":
    sys.exit(0)
```

Note: `main()` is intentionally not yet defined — `parse_args` exists now because
Task 1's tests only need the pure functions above it, but `parse_args` is included
here since it has no dependency on `main` and keeps Task 2's diff focused on
`main` itself. The `if __name__ == "__main__":` guard is replaced in Task 2.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest lazer_dq/tests/test_active_min_pub_to_audit.py -v`
Expected: PASS (all tests from Step 1)

- [ ] **Step 5: Run pre-commit and fix any formatting issues**

Run: `pre-commit run --files lazer_dq/active_min_pub_to_audit.py lazer_dq/tests/test_active_min_pub_to_audit.py`
Expected: PASS (black/prettier/whitespace/EOF hooks all clean, or auto-fixed — re-run once if a hook modifies files)

- [ ] **Step 6: Commit**

```bash
git add lazer_dq/active_min_pub_to_audit.py lazer_dq/tests/test_active_min_pub_to_audit.py
git commit -m "$(cat <<'EOF'
feat(active_min_pub_to_audit): core filter/reshape functions

Pure functions that decide whether an active_min_pub row is flagged for
Stage 2, excluded (min_pub == 1, structurally single-source), or dropped
(verdict not BREACH/CRITICAL[/WARN]), plus the row-shaping and filename
parsing used by the CLI in the next commit.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: CLI wiring (`main`) + integration tests

**Files:**
- Modify: `lazer_dq/active_min_pub_to_audit.py`
- Test: `lazer_dq/tests/test_active_min_pub_to_audit.py`

**Interfaces:**
- Consumes: everything produced in Task 1 (`FLAGGED_COLUMNS`, `EXCLUDED_COLUMNS`, `target_verdicts`, `bucket_for_row`, `to_flagged_row`, `to_excluded_row`, `parse_window_from_filename`, `parse_args`).
- Produces: `main(argv=None) -> int` — reads `args.active_min_pub_csv`, writes `<output_dir>/active_min_pub_flagged_<stamp>.csv` and `<output_dir>/active_min_pub_excluded_<stamp>.csv`, prints the console summary, returns `0` on success or `1` if the input filename can't be parsed.

- [ ] **Step 1: Write the failing tests**

Append to `lazer_dq/tests/test_active_min_pub_to_audit.py`:

```python
import csv as csv_module

from lazer_dq.active_min_pub_to_audit import main

_HEADER = [
    "feed_id",
    "symbol",
    "asset_type",
    "session",
    "effective_min_pub",
    "n_updates",
    "min",
    "p1",
    "p5",
    "median",
    "pct_below_par",
    "pct_at_par",
    "pct_at_floor",
    "pct_at_floor_1",
    "verdict",
]

_FIXTURE_ROWS = [
    # feed 100: BREACH, min_pub=2 -> flagged, pct_at_floor=12.0
    ["100", "Equity.US.AAA/USD", "equity", "REGULAR", "2", "1000", "1", "1", "2", "2",
     "2.0", "10.0", "12.0", "20.0", "BREACH"],
    # feed 101: CRITICAL, min_pub=3 -> flagged, pct_at_floor=5.0
    ["101", "Equity.US.BBB/USD", "equity", "REGULAR", "3", "1000", "3", "3", "3", "4",
     "0.0", "5.0", "5.0", "15.0", "CRITICAL"],
    # feed 102: CRITICAL, min_pub=1 -> excluded (structurally single-source)
    ["102", "InterestRate.US10Y/USD", "interest-rate", "REGULAR", "1", "1000", "1", "1", "1", "1",
     "0.0", "100.0", "100.0", "100.0", "CRITICAL"],
    # feed 103: WARN, min_pub=2 -> dropped by default, flagged when --include-warn
    ["103", "Equity.US.CCC/USD", "equity", "OVER_NIGHT", "2", "1000", "2", "2", "2", "3",
     "0.0", "0.0", "0.0", "8.0", "WARN"],
    # feed 104: OK -> always dropped
    ["104", "Equity.US.DDD/USD", "equity", "REGULAR", "5", "1000", "5", "5", "6", "8",
     "0.0", "0.0", "0.0", "0.5", "OK"],
]


def _write_fixture(path):
    with open(path, "w", newline="") as f:
        writer = csv_module.writer(f)
        writer.writerow(_HEADER)
        writer.writerows(_FIXTURE_ROWS)


def test_main_default_flags_breach_and_critical_only(tmp_path, capsys):
    in_path = tmp_path / "active_min_pub_2026-07-14_2026-07-22.csv"
    _write_fixture(in_path)
    out_dir = tmp_path / "out"

    rc = main(
        [
            "--active-min-pub-csv",
            str(in_path),
            "--output-dir",
            str(out_dir),
        ]
    )
    assert rc == 0

    flagged_path = out_dir / "active_min_pub_flagged_2026-07-14_2026-07-22.csv"
    excluded_path = out_dir / "active_min_pub_excluded_2026-07-14_2026-07-22.csv"
    assert flagged_path.exists()
    assert excluded_path.exists()

    with open(flagged_path, newline="") as f:
        flagged = list(csv_module.DictReader(f))
    assert [r["feed_id"] for r in flagged] == ["100", "101"]  # sorted pct_at_floor desc
    assert flagged[0]["classification"] == "CRITICAL"
    assert flagged[0]["source_verdict"] == "BREACH"
    assert flagged[1]["classification"] == "CRITICAL"
    assert flagged[1]["source_verdict"] == "CRITICAL"

    with open(excluded_path, newline="") as f:
        excluded = list(csv_module.DictReader(f))
    assert [r["feed_id"] for r in excluded] == ["102"]
    assert excluded[0]["reason"] == "min_pub_floor_1"

    out = capsys.readouterr().out
    assert "Flagged 2 feed-sessions" in out
    assert "Excluded 1 feed-sessions" in out
    assert "Skipped 1 WARN rows" in out


def test_main_include_warn_adds_warn_rows(tmp_path):
    in_path = tmp_path / "active_min_pub_2026-07-14_2026-07-22.csv"
    _write_fixture(in_path)
    out_dir = tmp_path / "out"

    rc = main(
        [
            "--active-min-pub-csv",
            str(in_path),
            "--output-dir",
            str(out_dir),
            "--include-warn",
        ]
    )
    assert rc == 0

    flagged_path = out_dir / "active_min_pub_flagged_2026-07-14_2026-07-22.csv"
    with open(flagged_path, newline="") as f:
        flagged = list(csv_module.DictReader(f))
    feed_ids = {r["feed_id"] for r in flagged}
    assert feed_ids == {"100", "101", "103"}
    warn_row = next(r for r in flagged if r["feed_id"] == "103")
    assert warn_row["classification"] == "WARN"
    assert warn_row["source_verdict"] == "WARN"


def test_main_custom_min_pub_floor(tmp_path):
    in_path = tmp_path / "active_min_pub_2026-07-14_2026-07-22.csv"
    _write_fixture(in_path)
    out_dir = tmp_path / "out"

    rc = main(
        [
            "--active-min-pub-csv",
            str(in_path),
            "--output-dir",
            str(out_dir),
            "--min-pub-floor",
            "3",
        ]
    )
    assert rc == 0

    flagged_path = out_dir / "active_min_pub_flagged_2026-07-14_2026-07-22.csv"
    excluded_path = out_dir / "active_min_pub_excluded_2026-07-14_2026-07-22.csv"
    with open(flagged_path, newline="") as f:
        flagged = list(csv_module.DictReader(f))
    assert [r["feed_id"] for r in flagged] == ["101"]  # only min_pub=3 clears floor=3

    with open(excluded_path, newline="") as f:
        excluded = list(csv_module.DictReader(f))
    assert {r["feed_id"] for r in excluded} == {"100", "102"}  # both min_pub < 3 now


def test_main_bad_filename_errors_without_writing_output(tmp_path, capsys):
    in_path = tmp_path / "active_min_pub_CRITICAL_2026-07-22.csv"
    _write_fixture(in_path)
    out_dir = tmp_path / "out"

    rc = main(
        [
            "--active-min-pub-csv",
            str(in_path),
            "--output-dir",
            str(out_dir),
        ]
    )
    assert rc == 1
    assert "ERROR" in capsys.readouterr().out
    assert not out_dir.exists()


def test_main_empty_input_produces_empty_outputs_with_headers(tmp_path):
    in_path = tmp_path / "active_min_pub_2026-07-14_2026-07-22.csv"
    with open(in_path, "w", newline="") as f:
        writer = csv_module.writer(f)
        writer.writerow(_HEADER)
    out_dir = tmp_path / "out"

    rc = main(
        [
            "--active-min-pub-csv",
            str(in_path),
            "--output-dir",
            str(out_dir),
        ]
    )
    assert rc == 0

    flagged_path = out_dir / "active_min_pub_flagged_2026-07-14_2026-07-22.csv"
    with open(flagged_path, newline="") as f:
        reader = csv_module.reader(f)
        header = next(reader)
        rows = list(reader)
    assert header == FLAGGED_COLUMNS
    assert rows == []
```

Update the existing import block at the top of the test file (added in Task 1)
to also import `main` — `FLAGGED_COLUMNS` is already imported from Task 1 and
is reused unchanged by the new tests above:

```python
from lazer_dq.active_min_pub_to_audit import (
    EXCLUDED_COLUMNS,
    FLAGGED_COLUMNS,
    bucket_for_row,
    main,
    parse_window_from_filename,
    target_verdicts,
    to_excluded_row,
    to_flagged_row,
)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest lazer_dq/tests/test_active_min_pub_to_audit.py -v`
Expected: FAIL — `ImportError: cannot import name 'main' from 'lazer_dq.active_min_pub_to_audit'`

- [ ] **Step 3: Write the implementation**

In `lazer_dq/active_min_pub_to_audit.py`, replace the trailing
`if __name__ == "__main__": sys.exit(0)` block with:

```python
def main(argv=None) -> int:
    args = parse_args(argv)
    in_path = Path(args.active_min_pub_csv)
    try:
        stamp = parse_window_from_filename(in_path)
    except ValueError as e:
        print(f"ERROR: {e}")
        return 1

    with open(in_path, newline="") as f:
        rows = list(csv.DictReader(f))

    verdict_tally = Counter(r["verdict"] for r in rows)
    warn_skipped = verdict_tally.get("WARN", 0) if not args.include_warn else 0

    flagged, excluded = [], []
    for row in rows:
        bucket = bucket_for_row(row, args.min_pub_floor, args.include_warn)
        if bucket == "flagged":
            flagged.append(to_flagged_row(row))
        elif bucket == "excluded":
            excluded.append(to_excluded_row(row, "min_pub_floor_1"))

    flagged.sort(key=lambda r: -float(r["pct_at_floor"]))

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    flagged_path = out_dir / f"active_min_pub_flagged_{stamp}.csv"
    excluded_path = out_dir / f"active_min_pub_excluded_{stamp}.csv"

    with open(flagged_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FLAGGED_COLUMNS)
        writer.writeheader()
        writer.writerows(flagged)

    with open(excluded_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=EXCLUDED_COLUMNS)
        writer.writeheader()
        writer.writerows(excluded)

    print(f"Read {len(rows)} rows from {in_path}")
    for verdict, n in sorted(verdict_tally.items(), key=lambda kv: -kv[1]):
        print(f"  {verdict:12} {n}")
    print(f"\nFlagged {len(flagged)} feed-sessions -> {flagged_path}")
    print(
        f"Excluded {len(excluded)} feed-sessions (min_pub_floor={args.min_pub_floor}) "
        f"-> {excluded_path}"
    )
    if not args.include_warn and warn_skipped:
        print(f"Skipped {warn_skipped} WARN rows (pass --include-warn to include them)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

(The test file's import block was already updated to include `main` in Step 1,
above — that's what made the Step 2 failure an `ImportError` rather than an
`AttributeError`.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest lazer_dq/tests/test_active_min_pub_to_audit.py -v`
Expected: PASS (all tests, Task 1 + Task 2)

- [ ] **Step 5: Run the full test file once more for a clean full-module pass, then pre-commit**

Run: `pytest lazer_dq/tests/test_active_min_pub_to_audit.py -v && pre-commit run --files lazer_dq/active_min_pub_to_audit.py lazer_dq/tests/test_active_min_pub_to_audit.py`
Expected: all tests PASS; pre-commit hooks clean (or auto-fixed — re-run once if modified)

- [ ] **Step 6: Manual smoke test against real data**

Run:
```bash
python3 -m lazer_dq.active_min_pub_to_audit \
    --active-min-pub-csv output_csv/active_min_pub_2026-07-14_2026-07-18.csv \
    --output-dir /tmp/active_min_pub_to_audit_smoke
```
Expected: console prints a verdict tally matching the earlier-observed `2360 OK, 144 CRITICAL, 32 WARN, 18 NO_DATA` (this file predates the BREACH split, so all 144 CRITICAL rows are evaluated as CRITICAL, none as BREACH — the summary won't show a `BREACH` line), followed by `Flagged 86 feed-sessions`, `Excluded 58 feed-sessions`, and `Skipped 32 WARN rows` — verified directly against this file by filtering it with pandas/csv by hand before writing this plan: of the 144 `CRITICAL` rows, 86 have `effective_min_pub >= 2` and 58 have `effective_min_pub == 1`.

Note this 86/58 split is **not** the same as the 34/52 split quoted earlier in
`docs/superpowers/specs/2026-07-29-active-min-pub-to-audit-design.md` — that
34/52 came from the hand-curated `active_min_pub_CRITICAL_2026-07-22.csv`
snapshot, a *different* underlying run/window than this 07-14→07-18 file (86
CRITICAL keys of overlap out of 144 vs. 87 total curated rows — confirmed not
identical). The 34/52 numbers validate the *rule*; this step validates the
*tool* against whichever file is actually fed to it, so the two won't match and
that's expected, not a bug.

Inspect `/tmp/active_min_pub_to_audit_smoke/active_min_pub_flagged_2026-07-14_2026-07-18.csv`
and spot-check that feed `1474` (`Equity.US.VRSN/USD`, both `POST_MARKET` and
`PRE_MARKET` sessions, `effective_min_pub=2`, verdict `CRITICAL`) appears — this
is a manual verification step, not an automated test (no assertion to write —
it's a sanity check against real historical output before this tool is trusted
with a fresh run).

- [ ] **Step 7: Commit**

```bash
git add lazer_dq/active_min_pub_to_audit.py lazer_dq/tests/test_active_min_pub_to_audit.py
git commit -m "$(cat <<'EOF'
feat(active_min_pub_to_audit): CLI entry point

Wires the Task-1 filter functions into a main() that reads an
active_min_pub.py summary CSV and writes the flagged (Stage-2-ready)
and excluded (min_pub==1, surfaced not routed) CSVs, with a console
verdict tally and skip-count summary.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Documentation

**Files:**
- Create: `docs/active_min_pub_to_audit.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: the finished CLI from Task 2 (`--active-min-pub-csv`, `--min-pub-floor`, `--include-warn`, `--output-dir`; output filenames `active_min_pub_flagged_<stamp>.csv` / `active_min_pub_excluded_<stamp>.csv`).
- Produces: nothing consumed by later tasks — this is the last task.

- [ ] **Step 1: Write `docs/active_min_pub_to_audit.md`**

```markdown
# active_min_pub_to_audit

Adapter that filters an `active_min_pub.py` summary CSV down to the feed-sessions
worth routing into the existing min_pub Stage 2/3 remediation pipeline
(`qualify_candidates.py` → `apply_min_pub_remediation.py`), and produces a
drop-in `--audit-csv` for Stage 2 without any change to Stage 2 or Stage 3
themselves.

## Why `effective_min_pub >= 2`

A feed-session's `active_min_pub` verdict (`BREACH` or `CRITICAL`) says the
aggregate is running at or below its `minPublishers` floor. Whether that's
*fixable* by qualifying a new publisher depends on whether a second publisher
could plausibly exist: feed-sessions with `effective_min_pub == 1` (internal
`Pyth.*`/`Custom.*` feeds, interest-rates, some thin futures) are structurally
single-source — there is no second candidate for Stage 2 to find. This rule was
derived empirically from a hand-curated triage of the 2026-07-22 CRITICAL
snapshot: every `actionable == "yes"` row had `effective_min_pub >= 2` and every
`actionable == "no"` row had `effective_min_pub == 1`, with zero exceptions
across 87 rows, and cross-checked against `audit_min_pub`'s independent
allowed-publisher-availability signal (see
`docs/superpowers/specs/2026-07-29-active-min-pub-to-audit-design.md` for the
full analysis).

## Usage

    python3 -m lazer_dq.active_min_pub_to_audit \
        --active-min-pub-csv output_csv/active_min_pub_2026-07-14_2026-07-22.csv \
        [--min-pub-floor 2] [--include-warn] [--output-dir output_csv]

The input must be a **standard** `active_min_pub.py` summary CSV
(`active_min_pub_<start>_<end>.csv`) — not the hand-curated
`active_min_pub_CRITICAL_<date>.csv` snapshot, which has no `verdict` column.
The `<start>_<end>` window is parsed from the input filename; there are no
separate date flags.

- `--min-pub-floor` (default `2`) — the `effective_min_pub` threshold below
  which a `BREACH`/`CRITICAL` row is excluded rather than flagged.
- `--include-warn` (default off) — also route `WARN`-verdict rows through the
  same split. Off by default: WARN ("living one publisher above the floor") is
  a lower-urgency signal than BREACH/CRITICAL and isn't part of this pass.

## Output

Two CSVs per run, named from the input file's own `<start>_<end>` window:

### Flagged — `output_csv/active_min_pub_flagged_<start>_<end>.csv`

A drop-in `--audit-csv` for `qualify_candidates.py`:

`feed_id, symbol, session, classification, source_verdict, asset_type,
effective_min_pub, pct_below_par, pct_at_par, pct_at_floor, pct_at_floor_1,
min, median, n_updates`

`classification` is always `"CRITICAL"` (both `BREACH`- and `CRITICAL`-sourced
rows) or `"WARN"` (with `--include-warn`) — the literal values Stage 2 expects.
`source_verdict` keeps the original `active_min_pub` verdict for traceability.
Sorted by `pct_at_floor` descending.

### Excluded — `output_csv/active_min_pub_excluded_<start>_<end>.csv`

`feed_id, symbol, session, source_verdict, effective_min_pub, pct_at_floor,
reason`

Rows that were `BREACH`/`CRITICAL` (or `WARN` with `--include-warn`) but fell
below `--min-pub-floor` — surfaced here rather than silently dropped.
`reason` is `"min_pub_floor_1"` in v1 (the only exclusion rule that exists).

## Running the full pipeline

    python3 -m lazer_dq.active_min_pub --config X --start-date A --end-date B
    python3 -m lazer_dq.active_min_pub_to_audit \
        --active-min-pub-csv output_csv/active_min_pub_A_B.csv
    python3 -m lazer_dq.qualify_candidates --config X \
        --audit-csv output_csv/active_min_pub_flagged_A_B.csv \
        --start-date A --end-date B
    python3 -m lazer_dq.apply_min_pub_remediation --config X \
        --start-date A --end-date B   # dry-run by default; add --apply to write
```

- [ ] **Step 2: Add the Scripts-table row to `CLAUDE.md`**

In `CLAUDE.md`, find this existing row (in the Scripts table):

```
| `lazer_dq/active_min_pub.py`            | Aggregate publisher-count headroom sweep: per STABLE feed-session, distribution of `price_feeds.publisher_count` per update vs `minPublishers`                                    | `python3 -m lazer_dq.active_min_pub --config lazer_newest.json --start-date A --end-date B`            | [docs/active_min_pub.md](docs/active_min_pub.md)                                 |
```

Add immediately after it:

```
| `lazer_dq/active_min_pub_to_audit.py`   | Filter active_min_pub BREACH/CRITICAL feed-sessions (min_pub>=2) into a Stage-2-ready audit CSV                                                                                   | `python3 -m lazer_dq.active_min_pub_to_audit --active-min-pub-csv output_csv/active_min_pub_A_B.csv`   | [docs/active_min_pub_to_audit.md](docs/active_min_pub_to_audit.md)               |
```

Match the existing column widths as closely as practical; `prettier` (run via
pre-commit in the next step) will reflow the whole table to consistent widths
automatically, so exact spacing here isn't load-bearing.

- [ ] **Step 3: Add a Key Gotchas bullet to `CLAUDE.md`**

Immediately after the existing bullet that starts `- **min_pub pipeline
(lazer_dq)** — ...`, add a new bullet:

```
- **`active_min_pub_to_audit`** — routes `active_min_pub` `BREACH`/`CRITICAL` feed-sessions into the existing Stage 2/3 pipeline only when `effective_min_pub >= 2` (both collapse to `classification="CRITICAL"` for Stage 2, with the original verdict kept in `source_verdict`) — `min_pub == 1` feed-sessions (internal `Pyth.*`/`Custom.*`, interest-rates, some thin futures) are structurally single-source and have no qualifiable second publisher, so they land in the excluded CSV instead of a mechanism that can't help them.
```

- [ ] **Step 4: Run pre-commit on the changed docs**

Run: `pre-commit run --files docs/active_min_pub_to_audit.md CLAUDE.md`
Expected: PASS (prettier will reflow the Scripts table and Markdown — re-run
once if it modifies files, then verify the new row and bullet still read
correctly after reflow)

- [ ] **Step 5: Commit**

```bash
git add docs/active_min_pub_to_audit.md CLAUDE.md
git commit -m "$(cat <<'EOF'
docs: add active_min_pub_to_audit usage guide and CLAUDE.md entries

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review Notes

- **Spec coverage:** Filter logic (Task 1), flagged/excluded CSV output + console summary (Task 2), CLI flags `--active-min-pub-csv`/`--min-pub-floor`/`--include-warn`/`--output-dir` (Task 2), filename-parsing error path (Task 1 + Task 2), testing list from the spec (boundary at `min_pub_floor`, CRITICAL/WARN-off/on combinations, OK/LOW_SAMPLE/NO_DATA always dropped, empty input, filename parsing) — all covered across Task 1/2's test steps. Documentation (Task 3) covers usage, output schema, the Stage-2 drop-in contract, and the `min_pub >= 2` rule's empirical basis, matching the spec's Documentation section.
- **Placeholder scan:** no TBD/TODO; every step has runnable code, not a description of code.
- **Type consistency:** `bucket_for_row` returns the string literals `"flagged"`/`"excluded"`/`"drop"` consistently in Task 1 and Task 2; `FLAGGED_COLUMNS`/`EXCLUDED_COLUMNS` are defined once in Task 1 and referenced (not redefined) in Task 2 and Task 3's doc; `main`'s signature (`argv=None) -> int`) matches every test call site.
