# dq_summary POST_MARKET Exclusion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce `dq_summary_lazer-prod_2026-07-28_post-excluded.xlsx`, a copy of the source workbook where the `allowed` sheet's `POST_MARKET` row is blanked to `(excluded)` for the 29 feed IDs in `missing_us_equities_post_2026-07-27.csv`, with every other row byte-for-byte unchanged.

**Architecture:** A single pure function reads the `allowed` sheet, tracks the "current feed_id" across the sheet's blank-row-separated blocks, and overwrites `allowedPublisherIds`/`Notes` only on rows matching (target feed_id, session == `POST_MARKET`). A thin driver loads the real CSV + xlsx and calls it. No ClickHouse, no repo module — this is a one-off scratch script per the design spec.

**Tech Stack:** Python 3.12 (repo venv), `openpyxl` (already a repo dependency), `csv` stdlib.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-30-post-market-exclusion-dq-summary-design.md`
- Only `allowed`-sheet rows where `Feed ID` is in the 29-ID set **and** `Session == "POST_MARKET"` may change. Every other cell in the workbook (other sessions, other feed IDs, the `rankings` sheet) must be byte-identical to the source file.
- Changed cells: `allowedPublisherIds` → literal string `(excluded)`; `Notes` → literal string `excluded — see missing_us_equities_post_2026-07-27.csv` (overwrites whatever was there, including existing top-up/`(no data)` notes).
- Load the workbook without `data_only=True` (preserves formatting/formulas elsewhere in the workbook on save).
- Script and its test live in the scratchpad directory (`/private/tmp/claude-501/-Users-mariobernardi-Documents-GitHub-integration-benchmarking/0a51616a-5baf-44ff-b36b-c60f2e65dd7c/scratchpad`) — this is a one-time correction, not a repo module. No git commit for the script itself; the output `.xlsx` is gitignored (`*.xlsx` in `.gitignore`) so it doesn't need one either.
- Source files (read-only, never modified): `/Users/mariobernardi/Documents/GitHub/integration-benchmarking/dq_summary_lazer-prod_2026-07-28.xlsx`, `/Users/mariobernardi/Documents/GitHub/integration-benchmarking/missing_us_equities_post_2026-07-27.csv`.
- Output file: `/Users/mariobernardi/Documents/GitHub/integration-benchmarking/dq_summary_lazer-prod_2026-07-28_post-excluded.xlsx`.
- Run everything with the repo venv active (`source venv/bin/activate`) — bare `python3` at the system level may not have `openpyxl`, and per CLAUDE.md `python` is not on PATH at all.

---

### Task 1: Write and test the exclusion function

**Files:**
- Create: `<scratchpad>/exclude_post_market.py`
- Test: `<scratchpad>/test_exclude_post_market.py`

(`<scratchpad>` = `/private/tmp/claude-501/-Users-mariobernardi-Documents-GitHub-integration-benchmarking/0a51616a-5baf-44ff-b36b-c60f2e65dd7c/scratchpad`)

**Interfaces:**
- Produces: `load_feed_ids(csv_path: str) -> set[int]` — reads a CSV with header row `feed_id` and one integer per subsequent row, returns the set of ints.
- Produces: `exclude_post_market(input_path: str, feed_ids: set[int], output_path: str) -> int` — loads `input_path`, rewrites the `allowed` sheet's `POST_MARKET` rows for `feed_ids`, saves to `output_path`, returns the count of rows modified. Task 2 calls both of these directly.

- [ ] **Step 1: Write the failing test**

Create `<scratchpad>/test_exclude_post_market.py`:

```python
import os
import sys

sys.path.insert(0, os.path.dirname(__file__))

import openpyxl
from exclude_post_market import exclude_post_market, load_feed_ids


def _build_fixture(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "allowed"
    ws.append(["Allowed Publishers — fixture", None, None, None])
    ws.append(["Feed ID", "Session", "allowedPublisherIds", "Notes"])
    # Feed 100: target feed_id, all 5 session rows
    ws.append([100, "(aggregate)", '"allowedPublisherIds": [ 1, 2 ],', None])
    ws.append([100, "REGULAR", '"allowedPublisherIds": [ 1, 2 ],', None])
    ws.append([100, "PRE_MARKET", '"allowedPublisherIds": [ 1 ],', "1 passed + 1 top-up (≤2×)"])
    ws.append([100, "POST_MARKET", '"allowedPublisherIds": [ 1 ],', "0 passed + 1 top-up (≤2×)"])
    ws.append([100, "OVER_NIGHT", "(no data)", "mode missing for 2026-07-28"])
    ws.append([None, None, None, None])
    # Feed 200: not in target set, all 5 session rows
    ws.append([200, "(aggregate)", '"allowedPublisherIds": [ 3, 4 ],', None])
    ws.append([200, "REGULAR", '"allowedPublisherIds": [ 3, 4 ],', None])
    ws.append([200, "PRE_MARKET", '"allowedPublisherIds": [ 3 ],', None])
    ws.append([200, "POST_MARKET", '"allowedPublisherIds": [ 3, 4 ],', None])
    ws.append([200, "OVER_NIGHT", "(no data)", "mode missing for 2026-07-28"])
    ws.append([None, None, None, None])
    # Feed 300: target feed_id, POST_MARKET already "(no data)"
    ws.append([300, "(aggregate)", '"allowedPublisherIds": [ 5 ],', None])
    ws.append([300, "REGULAR", '"allowedPublisherIds": [ 5 ],', None])
    ws.append([300, "PRE_MARKET", "(no data)", "mode missing for 2026-07-28"])
    ws.append([300, "POST_MARKET", "(no data)", "mode missing for 2026-07-28"])
    ws.append([300, "OVER_NIGHT", "(no data)", "mode missing for 2026-07-28"])
    wb.save(path)


def _read_all(path):
    wb = openpyxl.load_workbook(path)
    ws = wb["allowed"]
    return [tuple(c.value for c in row) for row in ws.iter_rows()]


def test_load_feed_ids(tmp_path):
    csv_path = tmp_path / "ids.csv"
    csv_path.write_text("feed_id\n100\n300\n")
    assert load_feed_ids(str(csv_path)) == {100, 300}


def test_target_post_market_row_is_excluded(tmp_path):
    src = tmp_path / "src.xlsx"
    out = tmp_path / "out.xlsx"
    _build_fixture(str(src))

    modified = exclude_post_market(str(src), {100, 300}, str(out))

    assert modified == 2
    rows = {(r[0], r[1]): (r[2], r[3]) for r in _read_all(str(out)) if r[0] is not None}
    assert rows[(100, "POST_MARKET")] == (
        "(excluded)",
        "excluded — see missing_us_equities_post_2026-07-27.csv",
    )
    assert rows[(300, "POST_MARKET")] == (
        "(excluded)",
        "excluded — see missing_us_equities_post_2026-07-27.csv",
    )


def test_non_target_feed_untouched(tmp_path):
    src = tmp_path / "src.xlsx"
    out = tmp_path / "out.xlsx"
    _build_fixture(str(src))

    exclude_post_market(str(src), {100, 300}, str(out))

    rows = {(r[0], r[1]): (r[2], r[3]) for r in _read_all(str(out)) if r[0] is not None}
    assert rows[(200, "POST_MARKET")] == ('"allowedPublisherIds": [ 3, 4 ],', None)


def test_target_feed_other_sessions_untouched(tmp_path):
    src = tmp_path / "src.xlsx"
    out = tmp_path / "out.xlsx"
    _build_fixture(str(src))

    exclude_post_market(str(src), {100, 300}, str(out))

    rows = {(r[0], r[1]): (r[2], r[3]) for r in _read_all(str(out)) if r[0] is not None}
    assert rows[(100, "(aggregate)")] == ('"allowedPublisherIds": [ 1, 2 ],', None)
    assert rows[(100, "REGULAR")] == ('"allowedPublisherIds": [ 1, 2 ],', None)
    assert rows[(100, "PRE_MARKET")] == (
        '"allowedPublisherIds": [ 1 ],',
        "1 passed + 1 top-up (≤2×)",
    )
    assert rows[(100, "OVER_NIGHT")] == ("(no data)", "mode missing for 2026-07-28")


def test_row_count_unchanged(tmp_path):
    src = tmp_path / "src.xlsx"
    out = tmp_path / "out.xlsx"
    _build_fixture(str(src))

    exclude_post_market(str(src), {100, 300}, str(out))

    assert len(_read_all(str(src))) == len(_read_all(str(out)))
```

- [ ] **Step 2: Run test to verify it fails (module doesn't exist yet)**

Run: `source /Users/mariobernardi/Documents/GitHub/integration-benchmarking/venv/bin/activate && cd <scratchpad> && python3 -m pytest test_exclude_post_market.py -v`
Expected: FAIL/ERROR — `ModuleNotFoundError: No module named 'exclude_post_market'` (or `ImportError`).

- [ ] **Step 3: Write the implementation**

Create `<scratchpad>/exclude_post_market.py`:

```python
import csv

import openpyxl

EXCLUDE_NOTE = "excluded — see missing_us_equities_post_2026-07-27.csv"


def load_feed_ids(csv_path: str) -> set[int]:
    with open(csv_path, newline="") as f:
        reader = csv.reader(f)
        next(reader)  # header row
        return {int(row[0]) for row in reader if row}


def exclude_post_market(input_path: str, feed_ids: set[int], output_path: str) -> int:
    wb = openpyxl.load_workbook(input_path)
    ws = wb["allowed"]

    current_feed_id = None
    modified = 0
    for row in ws.iter_rows(min_row=3):
        feed_cell, session_cell, allowed_cell, notes_cell = row[0], row[1], row[2], row[3]
        if feed_cell.value is not None:
            current_feed_id = feed_cell.value
        if session_cell.value == "POST_MARKET" and current_feed_id in feed_ids:
            allowed_cell.value = "(excluded)"
            notes_cell.value = EXCLUDE_NOTE
            modified += 1

    wb.save(output_path)
    return modified
```

- [ ] **Step 4: Run test to verify it passes**

Run: `source /Users/mariobernardi/Documents/GitHub/integration-benchmarking/venv/bin/activate && cd <scratchpad> && python3 -m pytest test_exclude_post_market.py -v`
Expected: PASS — all 5 tests green (`test_load_feed_ids`, `test_target_post_market_row_is_excluded`, `test_non_target_feed_untouched`, `test_target_feed_other_sessions_untouched`, `test_row_count_unchanged`).

No commit for this step — scratch script only, per Global Constraints.

---

### Task 2: Run against the real files and verify the deliverable

**Files:**
- Modify: `<scratchpad>/exclude_post_market.py` (add a `if __name__ == "__main__":` driver block)
- Read: `/Users/mariobernardi/Documents/GitHub/integration-benchmarking/dq_summary_lazer-prod_2026-07-28.xlsx`
- Read: `/Users/mariobernardi/Documents/GitHub/integration-benchmarking/missing_us_equities_post_2026-07-27.csv`
- Create: `/Users/mariobernardi/Documents/GitHub/integration-benchmarking/dq_summary_lazer-prod_2026-07-28_post-excluded.xlsx`

**Interfaces:**
- Consumes: `load_feed_ids` and `exclude_post_market` from Task 1, unchanged signatures.

- [ ] **Step 1: Add the driver block**

Append to `<scratchpad>/exclude_post_market.py`:

```python
if __name__ == "__main__":
    REPO = "/Users/mariobernardi/Documents/GitHub/integration-benchmarking"
    feed_ids = load_feed_ids(f"{REPO}/missing_us_equities_post_2026-07-27.csv")
    modified = exclude_post_market(
        f"{REPO}/dq_summary_lazer-prod_2026-07-28.xlsx",
        feed_ids,
        f"{REPO}/dq_summary_lazer-prod_2026-07-28_post-excluded.xlsx",
    )
    print(f"feed_ids loaded: {len(feed_ids)}")
    print(f"POST_MARKET rows excluded: {modified}")
```

- [ ] **Step 2: Run it**

Run: `source /Users/mariobernardi/Documents/GitHub/integration-benchmarking/venv/bin/activate && cd <scratchpad> && python3 exclude_post_market.py`
Expected output: `feed_ids loaded: 29` and `POST_MARKET rows excluded: 29` (all 29 target feed IDs have a `POST_MARKET` row in the source sheet — confirmed present for every one of them during design research, so 29 is the exact expected count, not a lower bound).

- [ ] **Step 3: Verify row count is unchanged**

Run:
```bash
source /Users/mariobernardi/Documents/GitHub/integration-benchmarking/venv/bin/activate
python3 -c "
import openpyxl
REPO = '/Users/mariobernardi/Documents/GitHub/integration-benchmarking'
wb_a = openpyxl.load_workbook(f'{REPO}/dq_summary_lazer-prod_2026-07-28.xlsx')
wb_b = openpyxl.load_workbook(f'{REPO}/dq_summary_lazer-prod_2026-07-28_post-excluded.xlsx')
rows_a = list(wb_a['allowed'].iter_rows(values_only=True))
rows_b = list(wb_b['allowed'].iter_rows(values_only=True))
assert len(rows_a) == len(rows_b), (len(rows_a), len(rows_b))
print('row count OK:', len(rows_a))
"
```
Expected: `row count OK: <same number as original, no exception>`

- [ ] **Step 4: Verify only the 29 target POST_MARKET rows changed, everything else identical**

Run:
```bash
source /Users/mariobernardi/Documents/GitHub/integration-benchmarking/venv/bin/activate
python3 -c "
import csv
import openpyxl

REPO = '/Users/mariobernardi/Documents/GitHub/integration-benchmarking'
with open(f'{REPO}/missing_us_equities_post_2026-07-27.csv', newline='') as f:
    reader = csv.reader(f)
    next(reader)
    feed_ids = {int(row[0]) for row in reader if row}

wb_a = openpyxl.load_workbook(f'{REPO}/dq_summary_lazer-prod_2026-07-28.xlsx')
wb_b = openpyxl.load_workbook(f'{REPO}/dq_summary_lazer-prod_2026-07-28_post-excluded.xlsx')
rows_a = list(wb_a['allowed'].iter_rows(values_only=True))
rows_b = list(wb_b['allowed'].iter_rows(values_only=True))

current_feed_id = None
diffs = []
for a, b in zip(rows_a, rows_b):
    if a[0] is not None:
        current_feed_id = a[0]
    if a != b:
        diffs.append((current_feed_id, a, b))

unexpected = [d for d in diffs if not (d[0] in feed_ids and d[1][1] == 'POST_MARKET')]
print(f'total diffs: {len(diffs)}')
print(f'unexpected diffs: {len(unexpected)}')
assert len(unexpected) == 0, unexpected
assert len(diffs) == len(feed_ids), (len(diffs), len(feed_ids))

diffed_feed_ids = {d[0] for d in diffs}
assert diffed_feed_ids == feed_ids, diffed_feed_ids ^ feed_ids

for feed_id, a, b in diffs:
    assert b[2] == '(excluded)', (feed_id, b)
    assert b[3] == 'excluded — see missing_us_equities_post_2026-07-27.csv', (feed_id, b)

print('all diffs are exactly the 29 target POST_MARKET rows, correctly rewritten')
"
```
Expected: `total diffs: 29`, `unexpected diffs: 0`, no `AssertionError`, final line prints.

- [ ] **Step 5: Verify the rankings sheet is untouched**

Run:
```bash
source /Users/mariobernardi/Documents/GitHub/integration-benchmarking/venv/bin/activate
python3 -c "
import openpyxl
REPO = '/Users/mariobernardi/Documents/GitHub/integration-benchmarking'
wb_a = openpyxl.load_workbook(f'{REPO}/dq_summary_lazer-prod_2026-07-28.xlsx')
wb_b = openpyxl.load_workbook(f'{REPO}/dq_summary_lazer-prod_2026-07-28_post-excluded.xlsx')
rows_a = list(wb_a['rankings'].iter_rows(values_only=True))
rows_b = list(wb_b['rankings'].iter_rows(values_only=True))
assert rows_a == rows_b
print('rankings sheet identical:', len(rows_a), 'rows')
"
```
Expected: `rankings sheet identical: 705 rows` (no exception).

- [ ] **Step 6: Report the deliverable to the user**

No commit — the output `.xlsx` is gitignored per Global Constraints. Report the final path
(`/Users/mariobernardi/Documents/GitHub/integration-benchmarking/dq_summary_lazer-prod_2026-07-28_post-excluded.xlsx`)
and the verification results from Steps 3–5 back to the user.

---

## Self-Review Notes

- **Spec coverage:** Background/Goal → Task 1 (core logic) + Task 2 (real run). In-scope bullets (CSV read, target-match logic, cell overwrite, new output file, original untouched) → Task 1 steps 1–4 + Task 2 steps 1–2. Out-of-scope bullets (rankings sheet, other sessions/feeds, no ClickHouse rerun, no config edits, no permanent CLI) → enforced by Global Constraints and verified in Task 2 steps 4–5. Implementation notes (openpyxl without `data_only=True`, feed_id-carry-forward across blank rows, scratchpad location) → Global Constraints + Task 1 fixture/implementation. Verification checklist in the spec → Task 2 steps 3–5 map 1:1 to its four bullets.
- **Placeholder scan:** No TBD/TODO; every step has runnable code or an exact command with a stated expected result.
- **Type consistency:** `load_feed_ids(csv_path: str) -> set[int]` and `exclude_post_market(input_path: str, feed_ids: set[int], output_path: str) -> int` are defined once in Task 1 and consumed with the same names/signatures in Task 1's tests and Task 2's driver block.
