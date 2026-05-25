# Apply dq_summary "allowed" sheet → after.json — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `lazer_dq/apply_allowed_to_config.py`, a tool that reads a `dq_summary_*.xlsx` "allowed" sheet and applies its per-session `allowedPublisherIds` into `after.json`/`after_1.json`, promoting `COMING_SOON` feeds to `STABLE` and additively adding missing sessions to live feeds.

**Architecture:** A new script in the `lazer_dq` package parses the workbook with `openpyxl`, then edits the config as raw text using surgical regex/brace-scanning helpers (to preserve formatting and produce clean diffs). The low-level block-finding helpers are extracted from the existing `update_config_from_summary.py` into a shared `lib/json_surgery.py` so both tools use one implementation. The new tool's apply logic implements a per-(feed, session) decision matrix.

**Tech Stack:** Python 3.12, `openpyxl` (already a dependency — used by `summarize_feeds.py`), `pytest`. No `python` binary on this system — always use `python3`.

**Spec:** `docs/superpowers/specs/2026-05-26-apply-dq-summary-to-config-design.md`

---

## File Structure

| File | Responsibility |
|---|---|
| `lib/json_surgery.py` (create) | Reusable raw-text block finders: `find_feed_block`, `find_session_block`. |
| `tests/lib/test_json_surgery.py` (create) | Direct unit tests for the extracted helpers. |
| `update_config_from_summary.py` (modify) | Replace the two private block-finders with imports from `lib.json_surgery`, re-exported under their old private names so existing tests keep passing. |
| `lazer_dq/apply_allowed_to_config.py` (create) | The new tool: workbook reader, publisher filter, minPublishers policy, session-entry builder, decision-matrix apply, CLI. |
| `lazer_dq/tests/test_apply_allowed_to_config.py` (create) | Unit + integration tests for the new tool. |
| `docs/apply_allowed_to_config.md` (create) | User-facing docs. |
| `CLAUDE.md` (modify) | Add a Scripts-table row and a Key-Gotcha note. |

**Baseline note:** `python3 -m pytest tests/test_update_config_from_summary.py -q` currently shows **37 passed, 4 failed**. The 4 failures (`test_cli_*`) are pre-existing and environment-specific — they hardcode `cwd="/home/mariobern/integration-benchmarking"`, a path that does not exist on this machine. Treat **37 passed** as the green baseline; do not attempt to fix the 4 CLI tests as part of this work.

---

### Task 1: Extract surgical helpers into `lib/json_surgery.py`

**Files:**
- Create: `lib/json_surgery.py`
- Create: `tests/lib/test_json_surgery.py`
- Modify: `update_config_from_summary.py` (replace defs at the `_find_feed_block` and `_find_session_block` locations)

- [ ] **Step 1: Write the failing test**

Create `tests/lib/test_json_surgery.py`:

```python
"""Unit tests for lib.json_surgery raw-text block finders."""
from lib.json_surgery import find_feed_block, find_session_block


def test_find_feed_block_locates_feed():
    raw = '{"feeds": [ {"feedId": 100, "state": "COMING_SOON"} ]}'
    bounds = find_feed_block(raw, 100)
    assert bounds is not None
    start, end = bounds
    assert raw[start] == "{"
    assert raw[end - 1] == "}"
    assert '"feedId": 100' in raw[start:end]


def test_find_feed_block_returns_none_for_missing():
    raw = '{"feeds": [ {"feedId": 100} ]}'
    assert find_feed_block(raw, 999) is None


def test_find_feed_block_with_nested_braces():
    raw = (
        '[ {"feedId": 60, "metadata": {"a": {"b": 1}}, '
        '"marketSchedules": [ {"session": "REGULAR"} ]} ]'
    )
    bounds = find_feed_block(raw, 60)
    assert bounds is not None
    start, end = bounds
    block = raw[start:end]
    assert block.count("{") == block.count("}")
    assert '"feedId": 60' in block


def test_find_session_block_locates_session():
    block = (
        '{"marketSchedules": [ '
        '{"allowedPublisherIds": [1,2], "session": "REGULAR"}, '
        '{"allowedPublisherIds": [3], "session": "PRE_MARKET"} ]}'
    )
    bounds = find_session_block(block, "PRE_MARKET")
    assert bounds is not None
    s, e = bounds
    assert '"session": "PRE_MARKET"' in block[s:e]
    assert '"session": "REGULAR"' not in block[s:e]


def test_find_session_block_returns_none_for_missing():
    block = '{"marketSchedules": [ {"session": "REGULAR"} ]}'
    assert find_session_block(block, "OVER_NIGHT") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/lib/test_json_surgery.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lib.json_surgery'`

- [ ] **Step 3: Create the module**

Create `lib/json_surgery.py`:

```python
"""Raw-text surgical helpers for editing protobuf-style JSON configs in place.

These locate the byte span of a feed entry (by feedId) or a session entry
(by session name) within the raw JSON text, so callers can do regex-scoped
field replacements that preserve the file's original formatting. Shared by
update_config_from_summary.py and lazer_dq/apply_allowed_to_config.py.
"""
import re


def find_feed_block(raw: str, feed_id: int) -> tuple[int, int] | None:
    """Return (start, end) byte offsets of a feed entry by feedId, or None.

    start indexes the opening '{', end is one past the matching '}'.
    String-aware backward scan for the opening brace; brace-depth forward
    scan for the close.
    """
    pattern = rf'"feedId":\s*{feed_id}\s*[,\n}}]'
    match = re.search(pattern, raw)
    if not match:
        return None

    pos = match.start()

    # Scan backward for opening { (string-aware)
    depth = 0
    start = pos - 1
    while start >= 0:
        c = raw[start]
        if c == '"':
            start -= 1
            while start >= 0 and raw[start] != '"':
                if raw[start] == "\\" and start > 0:
                    start -= 1
                start -= 1
        elif c == "}":
            depth += 1
        elif c == "{":
            if depth == 0:
                break
            depth -= 1
        start -= 1

    # Scan forward from opening { for matching }
    depth = 1
    end = start + 1
    in_string = False
    while end < len(raw) and depth > 0:
        c = raw[end]
        if c == '"' and (end == 0 or raw[end - 1] != "\\"):
            in_string = not in_string
        elif not in_string:
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
        end += 1

    return (start, end)


def find_session_block(block: str, session_name: str) -> tuple[int, int] | None:
    """Return (start, end) byte offsets of a session entry within a feed block.

    Matches on `"session": "<session_name>"` and brackets the enclosing { }.
    """
    pattern = rf'"session":\s*"{session_name}"'
    match = re.search(pattern, block)
    if not match:
        return None

    pos = match.start()

    # Scan backward for opening {
    depth = 0
    start = pos - 1
    while start >= 0:
        c = block[start]
        if c == "}":
            depth += 1
        elif c == "{":
            if depth == 0:
                break
            depth -= 1
        start -= 1

    # Scan forward for matching }
    depth = 1
    end = start + 1
    in_string = False
    while end < len(block) and depth > 0:
        c = block[end]
        if c == '"' and (end == 0 or block[end - 1] != "\\"):
            in_string = not in_string
        elif not in_string:
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
        end += 1

    return (start, end)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/lib/test_json_surgery.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Re-point `update_config_from_summary.py` at the shared module**

In `update_config_from_summary.py`, **delete** the entire `def _find_feed_block(...)` function body and the entire `def _find_session_block(...)` function body. Replace each deleted function with nothing (remove it), and add this import directly below the existing `from pathlib import Path` line near the top of the file:

```python
from lib.json_surgery import (
    find_feed_block as _find_feed_block,
    find_session_block as _find_session_block,
)
```

The re-export aliases keep `_find_feed_block` / `_find_session_block` importable from `update_config_from_summary`, so its existing tests are unaffected. All internal call sites (`_find_feed_block(raw, feed_id)`, `_find_session_block(block, json_session)`) keep working unchanged.

- [ ] **Step 6: Run the existing suite to verify the refactor is behavior-preserving**

Run: `python3 -m pytest tests/test_update_config_from_summary.py tests/lib/test_json_surgery.py -q`
Expected: **42 passed, 4 failed** — the 4 failures are the pre-existing `test_cli_*` environment failures only (same 4 as baseline). All `test_find_feed_block_*` and `test_find_session_block*` tests pass.

- [ ] **Step 7: Commit**

```bash
git add lib/json_surgery.py tests/lib/test_json_surgery.py update_config_from_summary.py
git commit -m "refactor(lib): extract json_surgery block finders shared by config tools

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Workbook reader — `parse_allowed_sheet`

**Files:**
- Create: `lazer_dq/apply_allowed_to_config.py`
- Create: `lazer_dq/tests/test_apply_allowed_to_config.py`

- [ ] **Step 1: Write the failing test**

Create `lazer_dq/tests/test_apply_allowed_to_config.py`:

```python
"""Unit + integration tests for apply_allowed_to_config."""
import json
from pathlib import Path

import openpyxl
import pytest

from lazer_dq.apply_allowed_to_config import parse_allowed_sheet


def _write_allowed_workbook(path: Path, rows: list[tuple]) -> None:
    """rows: list of (feed_id, session, allowed_cell, note). Builds a 2-sheet
    workbook matching summarize_feeds output (rankings sheet present but empty)."""
    wb = openpyxl.Workbook()
    wb.active.title = "rankings"  # present but unused by the reader
    ws = wb.create_sheet("allowed")
    ws.cell(row=1, column=1, value="Allowed Publishers — test — 2026-05-20")
    for i, h in enumerate(["Feed ID", "Session", "allowedPublisherIds", "Notes"], 1):
        ws.cell(row=2, column=i, value=h)
    r = 3
    for feed_id, session, allowed_cell, note in rows:
        ws.cell(row=r, column=1, value=feed_id)
        ws.cell(row=r, column=2, value=session)
        ws.cell(row=r, column=3, value=allowed_cell)
        ws.cell(row=r, column=4, value=note)
        r += 1
    wb.save(path)


def _agg(ids):
    return '"allowedPublisherIds": [ ' + ", ".join(str(i) for i in ids) + " ],"


def test_parse_allowed_sheet_reads_lists_and_no_data(tmp_path):
    xlsx = tmp_path / "dq.xlsx"
    _write_allowed_workbook(
        xlsx,
        [
            (100, "(aggregate)", _agg([24, 35, 42]), None),
            (100, "REGULAR", _agg([24, 35, 42]), "0 passed + 3 top-up (≤2×)"),
            (100, "PRE_MARKET", "(no data)", "mode missing for 2026-05-20"),
            (100, "POST_MARKET", "(no data)", "mode missing for 2026-05-20"),
            (100, "OVER_NIGHT", "(no data)", "mode missing for 2026-05-20"),
            (None, None, None, None),  # divider
            (200, "(aggregate)", "(no data)", "all sessions empty"),
            (200, "REGULAR", "(no data)", "mode missing for 2026-05-20"),
        ],
    )

    result = parse_allowed_sheet(xlsx)

    assert set(result.keys()) == {100, 200}
    assert result[100]["aggregate"] == [24, 35, 42]
    assert result[100]["sessions"]["REGULAR"] == [24, 35, 42]
    assert result[100]["sessions"]["PRE_MARKET"] is None
    assert result[200]["aggregate"] is None
    assert result[200]["sessions"]["REGULAR"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest lazer_dq/tests/test_apply_allowed_to_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lazer_dq.apply_allowed_to_config'`

- [ ] **Step 3: Create the module with the reader**

Create `lazer_dq/apply_allowed_to_config.py`:

```python
#!/usr/bin/env python3
"""Apply a dq_summary '_allowed_' sheet to after.json.

Reads the 'allowed' sheet of a dq_summary_<cluster>_<date>.xlsx (produced by
lazer_dq/summarize_feeds.py) and edits a Lazer config (after.json / after_1.json)
in place: per-(feed, session) it promotes COMING_SOON feeds to STABLE on their
DQ-vetted publisher lists, and additively adds missing sessions to already-live
(STABLE) feeds without disturbing their live sessions.

Run:
    python3 -m lazer_dq.apply_allowed_to_config \
        --xlsx dq_summary_lazer-prod_2026-05-20.xlsx \
        --config after_1.json --dry-run

See docs/apply_allowed_to_config.md and
docs/superpowers/specs/2026-05-26-apply-dq-summary-to-config-design.md.
"""
import argparse
import json
import re
import shutil
import sys
from pathlib import Path

from lib.json_surgery import find_feed_block, find_session_block

# Session names, in after.json order.
SESSION_ORDER = ["REGULAR", "PRE_MARKET", "POST_MARKET", "OVER_NIGHT"]

# Publisher 0 (aggregate sentinel) + Lazer publishers. summarize_feeds excludes
# {0} ∪ .Test but NOT Lazer ids, so we strip them defensively here.
EXCLUDED_PUBLISHERS = {0, 1, 9, 13, 15}


def _parse_ids_cell(cell) -> list[int] | None:
    """Extract publisher ids from an 'allowedPublisherIds' cell.

    The cell is either '(no data)'/None or the paste-ready fragment
    '"allowedPublisherIds": [ 41, 69 ],'. Returns a list of ints, or None
    when there is no list.
    """
    if cell is None:
        return None
    text = str(cell)
    if not text.startswith('"allowedPublisherIds"'):
        return None
    m = re.search(r"\[(.*?)\]", text)
    if not m:
        return None
    inner = m.group(1).strip()
    if not inner:
        return []
    return [int(x) for x in inner.split(",") if x.strip()]


def parse_allowed_sheet(path) -> dict[int, dict]:
    """Parse the 'allowed' sheet, grouped by feed_id.

    Returns {feed_id: {"aggregate": list[int]|None,
                       "sessions": {SESSION: list[int]|None}}}.
    Rows whose Feed ID column is not an int (title, header, dividers, footer)
    are skipped.
    """
    import openpyxl

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    if "allowed" not in wb.sheetnames:
        raise ValueError(f"workbook {path} has no 'allowed' sheet")
    ws = wb["allowed"]

    feeds: dict[int, dict] = {}
    for row in ws.iter_rows(values_only=True):
        if not row or not isinstance(row[0], int):
            continue
        feed_id = row[0]
        session = row[1]
        ids = _parse_ids_cell(row[2])
        entry = feeds.setdefault(
            feed_id,
            {"aggregate": None, "sessions": {s: None for s in SESSION_ORDER}},
        )
        if session == "(aggregate)":
            entry["aggregate"] = ids
        elif session in entry["sessions"]:
            entry["sessions"][session] = ids
    return feeds
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest lazer_dq/tests/test_apply_allowed_to_config.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add lazer_dq/apply_allowed_to_config.py lazer_dq/tests/test_apply_allowed_to_config.py
git commit -m "feat(lazer_dq): read dq_summary allowed sheet in apply_allowed_to_config

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Publisher filter + minPublishers policy

**Files:**
- Modify: `lazer_dq/apply_allowed_to_config.py`
- Test: `lazer_dq/tests/test_apply_allowed_to_config.py`

- [ ] **Step 1: Write the failing test**

Append to `lazer_dq/tests/test_apply_allowed_to_config.py`:

```python
from lazer_dq.apply_allowed_to_config import filter_publishers, get_min_publishers


def test_filter_publishers_strips_zero_and_lazer():
    kept, removed = filter_publishers([0, 1, 9, 13, 15, 24, 35, 42])
    assert kept == [24, 35, 42]
    assert removed == [0, 1, 9, 13, 15]


def test_filter_publishers_keeps_sorted_unique():
    kept, removed = filter_publishers([42, 24, 24, 35])
    assert kept == [24, 35, 42]
    assert removed == []


def test_get_min_publishers_defaults():
    assert get_min_publishers("REGULAR", 10) == 3
    assert get_min_publishers("PRE_MARKET", 10) == 2
    assert get_min_publishers("POST_MARKET", 10) == 2
    assert get_min_publishers("OVER_NIGHT", 10) == 1


def test_get_min_publishers_regular_low_count_rule():
    assert get_min_publishers("REGULAR", 5) == 2
    assert get_min_publishers("REGULAR", 1) == 2
    assert get_min_publishers("REGULAR", 6) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest lazer_dq/tests/test_apply_allowed_to_config.py -k "filter_publishers or min_publishers" -v`
Expected: FAIL — `ImportError: cannot import name 'filter_publishers'`

- [ ] **Step 3: Implement the helpers**

Add to `lazer_dq/apply_allowed_to_config.py` (below `EXCLUDED_PUBLISHERS`):

```python
# minPublishers defaults per session.
SESSION_MIN_PUBLISHERS = {
    "REGULAR": 3,
    "PRE_MARKET": 2,
    "POST_MARKET": 2,
    "OVER_NIGHT": 1,
}
# REGULAR sessions with this many or fewer publishers use a reduced floor.
REGULAR_LOW_PUB_THRESHOLD = 5
REGULAR_LOW_PUB_MIN = 2


def filter_publishers(ids: list[int]) -> tuple[list[int], list[int]]:
    """Drop EXCLUDED_PUBLISHERS. Return (kept_sorted_unique, removed_sorted)."""
    id_set = set(ids)
    kept = sorted(id_set - EXCLUDED_PUBLISHERS)
    removed = sorted(id_set & EXCLUDED_PUBLISHERS)
    return kept, removed


def get_min_publishers(session: str, pub_count: int) -> int:
    """minPublishers for a session, applying the REGULAR low-count reduction."""
    if session == "REGULAR" and pub_count <= REGULAR_LOW_PUB_THRESHOLD:
        return REGULAR_LOW_PUB_MIN
    return SESSION_MIN_PUBLISHERS[session]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest lazer_dq/tests/test_apply_allowed_to_config.py -k "filter_publishers or min_publishers" -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add lazer_dq/apply_allowed_to_config.py lazer_dq/tests/test_apply_allowed_to_config.py
git commit -m "feat(lazer_dq): publisher filter + minPublishers policy

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Block-edit primitives — set top-level, overwrite session, add session

**Files:**
- Modify: `lazer_dq/apply_allowed_to_config.py`
- Test: `lazer_dq/tests/test_apply_allowed_to_config.py`

- [ ] **Step 1: Write the failing test**

Append to `lazer_dq/tests/test_apply_allowed_to_config.py`:

```python
from lazer_dq.apply_allowed_to_config import (
    set_top_level_allowed,
    set_top_level_min_publishers,
    overwrite_session,
    add_session,
    SCHEDULE_TEMPLATES,
)


def test_set_top_level_allowed_replaces_array_before_marketschedules():
    block = (
        '{\n      "allowedPublisherIds": [\n        1,\n        2\n      ],\n'
        '      "marketSchedules": [ {"allowedPublisherIds": [9], '
        '"session": "REGULAR"} ]\n}'
    )
    out = set_top_level_allowed(block, [24, 35])
    # Top-level array (before marketSchedules) replaced; session array untouched.
    assert '"allowedPublisherIds": [ 24, 35 ]' in out
    assert '"allowedPublisherIds": [9]' in out
    assert out.index("[ 24, 35 ]") < out.index("[9]")


def test_set_top_level_min_publishers_targets_field_after_marketschedules():
    # Mirrors after.json: a session minPublishers appears BEFORE the top-level one.
    block = (
        '{\n      "allowedPublisherIds": [ 1 ],\n'
        '      "marketSchedules": [ {\n'
        '          "minPublishers": 3,\n'
        '          "session": "REGULAR"\n'
        '        } ],\n'
        '      "minPublishers": 3,\n'
        '      "state": "STABLE"\n}'
    )
    out = set_top_level_min_publishers(block, 1)
    data = json.loads(out)
    assert data["minPublishers"] == 1  # top-level changed
    assert data["marketSchedules"][0]["minPublishers"] == 3  # session untouched


def test_overwrite_session_replaces_ids_and_minpub():
    block = (
        '{ "marketSchedules": [ {\n'
        '          "allowedPublisherIds": [ 1, 2, 3 ],\n'
        '          "minPublishers": 3,\n'
        '          "session": "REGULAR"\n'
        '        } ] }'
    )
    out = overwrite_session(block, "REGULAR", [24, 35, 42])
    assert '"allowedPublisherIds": [ 24, 35, 42 ]' in out
    assert '"minPublishers": 2' in out  # 3 publishers => REGULAR low-count => 2
    assert '"session": "REGULAR"' in out


def test_overwrite_session_handles_null_array():
    block = (
        '{ "marketSchedules": [ {\n'
        '          "allowedPublisherIds": null,\n'
        '          "minPublishers": 3,\n'
        '          "session": "PRE_MARKET"\n'
        '        } ] }'
    )
    out = overwrite_session(block, "PRE_MARKET", [24, 35])
    assert '"allowedPublisherIds": [ 24, 35 ]' in out
    assert "null" not in out
    assert '"minPublishers": 2' in out


def test_add_session_inserts_entry_with_benchmark_mapping():
    block = (
        '{ "marketSchedules": [\n'
        '        {\n'
        '          "allowedPublisherIds": [ 11 ],\n'
        '          "marketSchedule": "X",\n'
        '          "minPublishers": 3,\n'
        '          "session": "REGULAR"\n'
        '        }\n'
        '      ]\n}'
    )
    bench = {"datascope_ric": {"identifiers": [{"identifier": "AAPL.O"}]}}
    out = add_session(block, "PRE_MARKET", [24, 35], bench)
    # Still valid JSON after the insert.
    data = json.loads(out)
    sessions = {s["session"]: s for s in data["marketSchedules"]}
    assert set(sessions) == {"REGULAR", "PRE_MARKET"}
    pre = sessions["PRE_MARKET"]
    assert pre["allowedPublisherIds"] == [24, 35]
    assert pre["minPublishers"] == 2  # PRE_MARKET default
    assert pre["benchmarkMapping"] == bench
    assert pre["marketSchedule"] == SCHEDULE_TEMPLATES["PRE_MARKET"]
    # REGULAR untouched.
    assert sessions["REGULAR"]["allowedPublisherIds"] == [11]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest lazer_dq/tests/test_apply_allowed_to_config.py -k "set_top_level or overwrite_session or add_session" -v`
Expected: FAIL — `ImportError: cannot import name 'set_top_level_allowed'`

- [ ] **Step 3: Implement the primitives**

Add to `lazer_dq/apply_allowed_to_config.py`:

```python
# marketSchedule templates (America/New_York; session windows; US-equity holidays),
# used only when ADDING a missing extended-hours session. Sourced from feed 922 (AAPL).
SCHEDULE_TEMPLATES = {
    "REGULAR": (
        "America/New_York;0930-1600,0930-1600,0930-1600,0930-1600,0930-1600,C,C;"
        "0101/C,0119/C,0216/C,0403/C,0525/C,0619/C,0703/C,0907/C,1126/C,"
        "1127/0930-1300,1224/0930-1300,1225/C"
    ),
    "PRE_MARKET": (
        "America/New_York;0400-0930,0400-0930,0400-0930,0400-0930,0400-0930,C,C;"
        "0101/C,0119/C,0216/C,0403/C,0525/C,0619/C,0703/C,0907/C,1126/C,1225/C"
    ),
    "POST_MARKET": (
        "America/New_York;1600-2000,1600-2000,1600-2000,1600-2000,1600-2000,C,C;"
        "0101/C,0119/C,0216/C,0403/C,0525/C,0619/C,0703/C,0907/C,1126/C,1225/C"
    ),
    "OVER_NIGHT": (
        "America/New_York;0000-0400&2000-2400,0000-0400&2000-2400,"
        "0000-0400&2000-2400,0000-0400&2000-2400,0000-0400,C,2000-2400;"
        "0118/C,0119/2000-2400,0215/C,0216/2000-2400,0402/0000-0400,0403/C,"
        "0524/C,0525/2000-2400,0618/0000-0400,0619/C,0702/0000-0400,0703/C,"
        "0906/C,0907/2000-2400,1125/0000-0400,1126/2000-2400,1224/0000-0400,"
        "1225/C,1231/0000-0400,0101/C"
    ),
}


def _ids_inline(ids: list[int]) -> str:
    """Render an id list as an inline JSON array: '[ 1, 2, 3 ]' or '[ ]'."""
    return "[ " + ", ".join(str(i) for i in ids) + " ]" if ids else "[ ]"


def set_top_level_allowed(block: str, ids: list[int]) -> str:
    """Set the feed's top-level allowedPublisherIds.

    The top-level array is the only allowedPublisherIds that precedes
    marketSchedules, so we restrict the search to the head of the block (before
    "marketSchedules") to avoid matching a session array. The pattern spans
    multi-line arrays because [^\\]] also matches newlines. If the feed has no
    top-level allowedPublisherIds, insert one after the opening '{'.
    """
    ms = re.search(r'"marketSchedules"', block)
    head_end = ms.start() if ms else len(block)
    head = block[:head_end]
    pattern = r'"allowedPublisherIds":\s*(\[[^\]]*\]|null)'
    repl = f'"allowedPublisherIds": {_ids_inline(ids)}'
    if re.search(pattern, head):
        new_head = re.sub(pattern, repl, head, count=1)
        return new_head + block[head_end:]
    nl = block.index("\n")
    return block[:nl] + f'\n      {repl},' + block[nl:]


def _marketschedules_end(block: str) -> int:
    """Return the offset just past the marketSchedules array's closing ']', or 0."""
    ms = re.search(r'"marketSchedules":\s*\[', block)
    if not ms:
        return 0
    pos = ms.end()
    depth = 1
    in_str = False
    while pos < len(block) and depth > 0:
        c = block[pos]
        if c == '"' and (pos == 0 or block[pos - 1] != "\\"):
            in_str = not in_str
        elif not in_str:
            if c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
        pos += 1
    return pos


def set_top_level_min_publishers(block: str, n: int) -> str:
    """Set the feed's top-level minPublishers.

    after.json lists marketSchedules (with their own minPublishers) BEFORE the
    top-level minPublishers, so we search only the region after the
    marketSchedules array closes. Falls back to the first match when the feed
    has no marketSchedules.
    """
    search_from = _marketschedules_end(block)
    pat = r'"minPublishers":\s*\d+'
    m = re.search(pat, block[search_from:])
    if not m:
        return re.sub(pat, f'"minPublishers": {n}', block, count=1)
    s = search_from + m.start()
    e = search_from + m.end()
    return block[:s] + f'"minPublishers": {n}' + block[e:]


def overwrite_session(block: str, session: str, ids: list[int]) -> str:
    """Within a feed block, set a session's allowedPublisherIds + minPublishers."""
    bounds = find_session_block(block, session)
    if bounds is None:
        return block
    s, e = bounds
    sblock = block[s:e]
    min_pub = get_min_publishers(session, len(ids))

    pub_pat = r'"allowedPublisherIds":\s*(\[[^\]]*\]|null)'
    if re.search(pub_pat, sblock):
        sblock = re.sub(
            pub_pat, f'"allowedPublisherIds": {_ids_inline(ids)}', sblock, count=1
        )
    min_pat = r'"minPublishers":\s*\d+'
    if re.search(min_pat, sblock):
        sblock = re.sub(min_pat, f'"minPublishers": {min_pub}', sblock, count=1)
    return block[:s] + sblock + block[e:]


def _detect_session_indent(block: str) -> str:
    """Return the leading whitespace of the first session entry's '{', or 8 spaces."""
    m = re.search(r'\n(\s*)\{', block[block.find('"marketSchedules"'):])
    return m.group(1) if m else "        "


def add_session(block: str, session: str, ids: list[int], benchmark_mapping) -> str:
    """Insert a new session entry before the closing ']' of marketSchedules.

    benchmark_mapping is the dict copied from the feed's REGULAR session (or None).
    """
    base_indent = _detect_session_indent(block)
    entry: dict = {"allowedPublisherIds": ids}
    if benchmark_mapping is not None:
        entry["benchmarkMapping"] = benchmark_mapping
    entry["marketSchedule"] = SCHEDULE_TEMPLATES[session]
    entry["minPublishers"] = get_min_publishers(session, len(ids))
    entry["session"] = session

    text = json.dumps(entry, indent=2)
    entry_text = "\n".join(base_indent + ln for ln in text.split("\n"))

    ms_end = _marketschedules_end(block)
    if ms_end == 0:
        return block
    closing_bracket = ms_end - 1  # position of the array's ']'

    # Walk back to the last non-whitespace char before ']' (last entry's '}').
    p = closing_bracket - 1
    while p >= 0 and block[p] in (" ", "\n", "\t", "\r"):
        p -= 1
    return block[: p + 1] + ",\n" + entry_text + block[p + 1 :]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest lazer_dq/tests/test_apply_allowed_to_config.py -k "set_top_level or overwrite_session or add_session" -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add lazer_dq/apply_allowed_to_config.py lazer_dq/tests/test_apply_allowed_to_config.py
git commit -m "feat(lazer_dq): block-edit primitives for top-level/session edits

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Decision-matrix apply — `apply_summary_to_config`

**Files:**
- Modify: `lazer_dq/apply_allowed_to_config.py`
- Test: `lazer_dq/tests/test_apply_allowed_to_config.py`

This is the core. It walks each feed in the parsed summary and edits the raw config text per the spec's decision matrix.

- [ ] **Step 1: Write the failing test**

Append to `lazer_dq/tests/test_apply_allowed_to_config.py`:

```python
from lazer_dq.apply_allowed_to_config import apply_summary_to_config

_BENCH = {"datascope_ric": {"identifiers": [{"identifier": "AAPL.O"}]}}


def _config_with(feeds: list[dict]) -> str:
    """Serialize a minimal config the way after.json is laid out (indent=2)."""
    return json.dumps({"feeds": feeds}, indent=2)


def _feed(feed_id, state, sessions, top=None):
    """sessions: list of (name, allowed_or_None). REGULAR carries benchmarkMapping."""
    ms = []
    for name, allowed in sessions:
        entry = {
            "allowedPublisherIds": allowed,
            "benchmarkMapping": _BENCH,
            "marketSchedule": "TPL",
            "minPublishers": 3,
            "session": name,
        }
        ms.append(entry)
    feed = {
        "allowedPublisherIds": top if top is not None else [],
        "feedId": feed_id,
        "marketSchedules": ms,
        "minPublishers": 3,
        "state": state,
        "symbol": f"S{feed_id}",
    }
    return feed


def test_apply_promotes_coming_soon_regular_only():
    raw = _config_with(
        [_feed(100, "COMING_SOON", [("REGULAR", [1, 2, 3])], top=[1, 2, 3])]
    )
    summary = {100: {"aggregate": [24, 35, 42], "sessions": {
        "REGULAR": [24, 35, 42], "PRE_MARKET": None,
        "POST_MARKET": None, "OVER_NIGHT": None}}}

    out, stats = apply_summary_to_config(raw, summary)
    data = json.loads(out)
    feed = {f["feedId"]: f for f in data["feeds"]}[100]

    assert feed["state"] == "STABLE"
    assert feed["minPublishers"] == 1  # top-level set to 1
    assert feed["allowedPublisherIds"] == [24, 35, 42]
    reg = feed["marketSchedules"][0]
    assert reg["allowedPublisherIds"] == [24, 35, 42]
    assert reg["minPublishers"] == 2  # 3 pubs => REGULAR low-count
    assert stats["promoted"] == 1


def test_apply_adds_missing_session_to_stable_feed():
    raw = _config_with(
        [_feed(200, "STABLE", [("REGULAR", [11, 12])], top=[11, 12])]
    )
    summary = {200: {"aggregate": [24, 35], "sessions": {
        "REGULAR": [11, 12], "PRE_MARKET": [24, 35],
        "POST_MARKET": None, "OVER_NIGHT": None}}}

    out, stats = apply_summary_to_config(raw, summary)
    data = json.loads(out)
    feed = {f["feedId"]: f for f in data["feeds"]}[200]
    sess = {s["session"]: s for s in feed["marketSchedules"]}

    assert feed["state"] == "STABLE"  # unchanged
    assert sess["REGULAR"]["allowedPublisherIds"] == [11, 12]  # live, untouched
    assert sess["PRE_MARKET"]["allowedPublisherIds"] == [24, 35]  # added
    assert sess["PRE_MARKET"]["benchmarkMapping"] == _BENCH  # copied from REGULAR
    assert feed["allowedPublisherIds"] == [11, 12, 24, 35]  # folded union
    assert feed["minPublishers"] == 3  # top-level untouched on STABLE
    assert stats["sessions_added"] == 1


def test_apply_leaves_existing_stable_session_untouched():
    raw = _config_with([_feed(300, "STABLE",
        [("REGULAR", [11]), ("PRE_MARKET", [99])], top=[11, 99])])
    summary = {300: {"aggregate": [24], "sessions": {
        "REGULAR": [11], "PRE_MARKET": [24],
        "POST_MARKET": None, "OVER_NIGHT": None}}}

    out, stats = apply_summary_to_config(raw, summary)
    data = json.loads(out)
    feed = {f["feedId"]: f for f in data["feeds"]}[300]
    sess = {s["session"]: s for s in feed["marketSchedules"]}

    assert sess["PRE_MARKET"]["allowedPublisherIds"] == [99]  # NOT overwritten
    assert stats["sessions_added"] == 0


def test_apply_skips_no_data_feed():
    raw = _config_with([_feed(400, "COMING_SOON", [("REGULAR", [1])], top=[1])])
    summary = {400: {"aggregate": None, "sessions": {
        s: None for s in ["REGULAR", "PRE_MARKET", "POST_MARKET", "OVER_NIGHT"]}}}

    out, stats = apply_summary_to_config(raw, summary)
    assert out == raw  # nothing changed
    assert stats["skipped_no_data"] == 1


def test_apply_warns_on_missing_feed():
    raw = _config_with([_feed(500, "COMING_SOON", [("REGULAR", [1])], top=[1])])
    summary = {999: {"aggregate": [24], "sessions": {
        "REGULAR": [24], "PRE_MARKET": None,
        "POST_MARKET": None, "OVER_NIGHT": None}}}

    out, stats = apply_summary_to_config(raw, summary)
    assert out == raw
    assert stats["not_found"] == [999]


def test_apply_filters_lazer_and_warns():
    raw = _config_with([_feed(600, "COMING_SOON", [("REGULAR", [1])], top=[1])])
    summary = {600: {"aggregate": [1, 9, 24, 35], "sessions": {
        "REGULAR": [1, 9, 24, 35], "PRE_MARKET": None,
        "POST_MARKET": None, "OVER_NIGHT": None}}}

    out, stats = apply_summary_to_config(raw, summary)
    data = json.loads(out)
    feed = {f["feedId"]: f for f in data["feeds"]}[600]
    assert feed["marketSchedules"][0]["allowedPublisherIds"] == [24, 35]
    assert feed["allowedPublisherIds"] == [24, 35]
    assert stats["filtered_any"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest lazer_dq/tests/test_apply_allowed_to_config.py -k apply_ -v`
Expected: FAIL — `ImportError: cannot import name 'apply_summary_to_config'`

- [ ] **Step 3: Implement the apply function**

Add to `lazer_dq/apply_allowed_to_config.py`:

```python
def _regular_benchmark_mapping(feed: dict):
    """Return the benchmarkMapping dict from the feed's REGULAR session, or None."""
    for s in feed.get("marketSchedules", []):
        if s.get("session") == "REGULAR":
            return s.get("benchmarkMapping")
    return None


def apply_summary_to_config(
    raw: str, summary: dict[int, dict], log=None
) -> tuple[str, dict]:
    """Apply the parsed summary to the raw config text.

    Returns (new_raw, stats). `log` is an optional callable(str) for per-feed
    lines; defaults to a no-op. Implements the spec decision matrix.
    """
    if log is None:
        log = lambda _msg: None  # noqa: E731

    data = json.loads(raw)
    feed_index = {f["feedId"]: f for f in data["feeds"]}

    stats = {
        "promoted": 0,
        "sessions_added": 0,
        "skipped_no_data": 0,
        "skipped_state": 0,
        "not_found": [],
        "filtered_any": False,
    }

    for feed_id, fa in summary.items():
        if not fa["aggregate"]:
            stats["skipped_no_data"] += 1
            log(f"  SKIP (no data): feedId={feed_id}")
            continue

        feed = feed_index.get(feed_id)
        if feed is None:
            stats["not_found"].append(feed_id)
            log(f"  WARNING (not found): feedId={feed_id}")
            continue

        state = feed.get("state")
        if state not in ("COMING_SOON", "STABLE"):
            stats["skipped_state"] += 1
            log(f"  SKIP (state={state}): feedId={feed_id}")
            continue

        bounds = find_feed_block(raw, feed_id)
        if bounds is None:
            stats["not_found"].append(feed_id)
            log(f"  WARNING (block not found): feedId={feed_id}")
            continue

        start, end = bounds
        block = raw[start:end]
        existing_sessions = {
            s.get("session") for s in feed.get("marketSchedules", [])
        }
        bench = _regular_benchmark_mapping(feed)

        if state == "COMING_SOON":
            block = re.sub(
                r'"state":\s*"COMING_SOON"', '"state": "STABLE"', block, count=1
            )
            top_union: set[int] = set()
            for session in SESSION_ORDER:
                raw_ids = fa["sessions"].get(session)
                if not raw_ids:
                    continue
                kept, removed = filter_publishers(raw_ids)
                if removed:
                    stats["filtered_any"] = True
                    log(f"    filtered {removed} from {feed_id}/{session}")
                if not kept:
                    continue
                top_union.update(kept)
                if session in existing_sessions:
                    block = overwrite_session(block, session, kept)
                else:
                    block = add_session(block, session, kept, bench)
                    stats["sessions_added"] += 1
            block = set_top_level_allowed(block, sorted(top_union))
            block = set_top_level_min_publishers(block, 1)
            stats["promoted"] += 1
            log(f"  PROMOTE: feedId={feed_id} -> STABLE, top={sorted(top_union)}")
        else:  # STABLE — additive only
            added: set[int] = set()
            for session in SESSION_ORDER:
                raw_ids = fa["sessions"].get(session)
                if not raw_ids:
                    continue
                if session in existing_sessions:
                    log(f"  SKIP (live): feedId={feed_id}/{session}")
                    continue
                kept, removed = filter_publishers(raw_ids)
                if removed:
                    stats["filtered_any"] = True
                    log(f"    filtered {removed} from {feed_id}/{session}")
                if not kept:
                    continue
                block = add_session(block, session, kept, bench)
                added.update(kept)
                stats["sessions_added"] += 1
                log(f"  ADD-SESSION: feedId={feed_id}/{session}={kept}")
            if added:
                existing_top = feed.get("allowedPublisherIds") or []
                new_top = sorted(set(existing_top) | added)
                block = set_top_level_allowed(block, new_top)

        raw = raw[:start] + block + raw[end:]

    return raw, stats
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest lazer_dq/tests/test_apply_allowed_to_config.py -k apply_ -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Run the whole new-tool suite**

Run: `python3 -m pytest lazer_dq/tests/test_apply_allowed_to_config.py -v`
Expected: PASS (all tests so far green)

- [ ] **Step 6: Commit**

```bash
git add lazer_dq/apply_allowed_to_config.py lazer_dq/tests/test_apply_allowed_to_config.py
git commit -m "feat(lazer_dq): decision-matrix apply_summary_to_config

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: CLI — `main`, dry-run, backup, reporting

**Files:**
- Modify: `lazer_dq/apply_allowed_to_config.py`
- Test: `lazer_dq/tests/test_apply_allowed_to_config.py`

- [ ] **Step 1: Write the failing test**

Append to `lazer_dq/tests/test_apply_allowed_to_config.py`:

```python
import subprocess
import sys


def _real_workbook(tmp_path):
    xlsx = tmp_path / "dq_summary_test_2026-05-20.xlsx"
    _write_allowed_workbook(
        xlsx,
        [
            (100, "(aggregate)", _agg([24, 35, 42]), None),
            (100, "REGULAR", _agg([24, 35, 42]), "0 passed + 3 top-up (≤2×)"),
            (100, "PRE_MARKET", "(no data)", "mode missing"),
            (100, "POST_MARKET", "(no data)", "mode missing"),
            (100, "OVER_NIGHT", "(no data)", "mode missing"),
        ],
    )
    return xlsx


def _real_config(tmp_path):
    cfg = tmp_path / "after_test.json"
    cfg.write_text(_config_with(
        [_feed(100, "COMING_SOON", [("REGULAR", [1, 2, 3])], top=[1, 2, 3])]
    ))
    return cfg


def test_cli_dry_run_writes_nothing(tmp_path):
    xlsx = _real_workbook(tmp_path)
    cfg = _real_config(tmp_path)
    before = cfg.read_text()

    result = subprocess.run(
        [sys.executable, "-m", "lazer_dq.apply_allowed_to_config",
         "--xlsx", str(xlsx), "--config", str(cfg), "--dry-run"],
        capture_output=True, text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    assert result.returncode == 0, result.stderr
    assert "DRY RUN" in result.stdout
    assert cfg.read_text() == before  # unchanged
    assert not (tmp_path / "after_test.json.bak").exists()


def test_cli_real_run_writes_and_backs_up(tmp_path):
    xlsx = _real_workbook(tmp_path)
    cfg = _real_config(tmp_path)

    result = subprocess.run(
        [sys.executable, "-m", "lazer_dq.apply_allowed_to_config",
         "--xlsx", str(xlsx), "--config", str(cfg)],
        capture_output=True, text=True,
        cwd=str(Path(__file__).resolve().parents[2]),
    )
    assert result.returncode == 0, result.stderr
    assert (cfg.parent / "after_test.json.bak").exists()
    data = json.loads(cfg.read_text())
    feed = {f["feedId"]: f for f in data["feeds"]}[100]
    assert feed["state"] == "STABLE"
    assert feed["allowedPublisherIds"] == [24, 35, 42]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest lazer_dq/tests/test_apply_allowed_to_config.py -k cli -v`
Expected: FAIL — module has no `main` / no `__main__` entry (non-zero return, or `SystemExit`/`AttributeError`).

- [ ] **Step 3: Implement `main` and the entry point**

Add to the end of `lazer_dq/apply_allowed_to_config.py`:

```python
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Apply a dq_summary 'allowed' sheet to after.json."
    )
    parser.add_argument(
        "--xlsx", required=True, help="dq_summary_<cluster>_<date>.xlsx"
    )
    parser.add_argument(
        "--config", required=True, help="after.json / after_1.json config file"
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Preview changes; write nothing."
    )
    args = parser.parse_args()

    xlsx_path = Path(args.xlsx)
    config_path = Path(args.config)
    if not xlsx_path.exists():
        print(f"ERROR: workbook not found: {xlsx_path}")
        sys.exit(1)
    if not config_path.exists():
        print(f"ERROR: config not found: {config_path}")
        sys.exit(1)

    print(f"Reading allowed sheet from {xlsx_path}")
    summary = parse_allowed_sheet(xlsx_path)
    print(f"Found {len(summary)} feeds in the allowed sheet")

    if args.dry_run:
        print("\n=== DRY RUN (no files will be modified) ===\n")

    raw = config_path.read_text()
    new_raw, stats = apply_summary_to_config(raw, summary, log=print)

    changed = stats["promoted"] + stats["sessions_added"]
    if not args.dry_run and changed > 0:
        backup = str(config_path) + ".bak"
        shutil.copy2(config_path, backup)
        config_path.write_text(new_raw)
        print(f"\nBackup saved to {backup}")

    print(f"\n{'=' * 50}\nSUMMARY\n{'=' * 50}")
    print(f"  Feeds promoted (COMING_SOON->STABLE): {stats['promoted']}")
    print(f"  Sessions added:                       {stats['sessions_added']}")
    print(f"  Skipped (no data):                    {stats['skipped_no_data']}")
    print(f"  Skipped (other state):                {stats['skipped_state']}")
    print(f"  Not found in config:                  {len(stats['not_found'])}")
    if stats["not_found"]:
        print(f"  Missing feed IDs: {stats['not_found']}")
    if stats["filtered_any"]:
        print("  NOTE: some Lazer/zero publishers were filtered (see lines above).")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest lazer_dq/tests/test_apply_allowed_to_config.py -k cli -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add lazer_dq/apply_allowed_to_config.py lazer_dq/tests/test_apply_allowed_to_config.py
git commit -m "feat(lazer_dq): CLI with dry-run, backup, and summary reporting

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: End-to-end smoke test against the real artifacts (dry-run)

This task verifies the tool runs against the actual `dq_summary_lazer-prod_2026-05-20.xlsx` + `after_1.json` and produces the expected tallies, then confirms the result is still valid JSON. It does not commit any config changes.

**Files:** none created; this is a verification task.

- [ ] **Step 1: Dry-run against the real files**

Run:
```bash
python3 -m lazer_dq.apply_allowed_to_config \
    --xlsx dq_summary_lazer-prod_2026-05-20.xlsx \
    --config after_1.json --dry-run
```
Expected (from the spec's "Expected result" section): SUMMARY shows
`Feeds promoted ... : 174`, `Sessions added: 0`, `Skipped (no data): 52`,
`Not found in config: 0`. `after_1.json` is unchanged and no `.bak` is created.

- [ ] **Step 2: Verify a real run produces valid JSON (against a copy)**

Run:
```bash
cp after_1.json /tmp/after_smoke.json
python3 -m lazer_dq.apply_allowed_to_config \
    --xlsx dq_summary_lazer-prod_2026-05-20.xlsx \
    --config /tmp/after_smoke.json
python3 -c "import json; d=json.load(open('/tmp/after_smoke.json')); \
fids={f['feedId']:f for f in d['feeds']}; \
print('feed 997 state:', fids[997]['state']); \
print('feed 997 REGULAR allowed:', \
[s for s in fids[997]['marketSchedules'] if s['session']=='REGULAR'][0]['allowedPublisherIds']); \
print('feed 997 top minPub:', fids[997]['minPublishers'])"
```
Expected: JSON parses without error; feed 997 state is `STABLE`; REGULAR
`allowedPublisherIds` is `[24, 35, 42, 45, 80]`; top-level `minPublishers` is `1`.

- [ ] **Step 3: Diff sanity check**

Run: `python3 -c "import json; a=json.load(open('after_1.json')); b=json.load(open('/tmp/after_smoke.json')); ca={f['feedId']:f['state'] for f in a['feeds']}; cb={f['feedId']:f['state'] for f in b['feeds']}; print('feeds flipped to STABLE:', sum(1 for k in ca if ca[k]=='COMING_SOON' and cb.get(k)=='STABLE'))"`
Expected: `feeds flipped to STABLE: 174`

- [ ] **Step 4: Clean up the scratch file**

Run: `rm -f /tmp/after_smoke.json /tmp/after_smoke.json.bak`
No commit for this task.

---

### Task 8: Documentation

**Files:**
- Create: `docs/apply_allowed_to_config.md`
- Modify: `CLAUDE.md` (Scripts table + Key Gotchas)

- [ ] **Step 1: Write the user docs**

Create `docs/apply_allowed_to_config.md`:

```markdown
# Apply Allowed Publishers to Config (apply_allowed_to_config.py)

Applies the **"allowed" sheet** of a `dq_summary_<cluster>_<date>.xlsx`
(produced by `lazer_dq/summarize_feeds.py`) directly into `after.json` /
`after_1.json`. It promotes `COMING_SOON` feeds to `STABLE` on their
DQ-vetted publisher lists and additively adds missing sessions to live feeds.

## Usage

```bash
# Preview (no writes)
python3 -m lazer_dq.apply_allowed_to_config \
    --xlsx dq_summary_lazer-prod_2026-05-20.xlsx \
    --config after_1.json --dry-run

# Apply (writes after_1.json, backup at after_1.json.bak)
python3 -m lazer_dq.apply_allowed_to_config \
    --xlsx dq_summary_lazer-prod_2026-05-20.xlsx \
    --config after_1.json
```

Run once per workbook (each file is one asset class / one date).

## Arguments

| Argument    | Description                                  | Required |
| ----------- | -------------------------------------------- | -------- |
| `--xlsx`    | dq_summary workbook (reads the `allowed` tab)| Yes      |
| `--config`  | after.json / after_1.json                    | Yes      |
| `--dry-run` | Preview changes without writing              | No       |

## Per-(feed, session) rules

| Feed state | Session in feed? | Summary has list? | Action |
|---|---|---|---|
| COMING_SOON | yes | yes | overwrite `allowedPublisherIds` + `minPublishers` |
| COMING_SOON | no  | yes | add the session entry |
| COMING_SOON | (any session has data) | — | flip → STABLE; top-level = union, `minPublishers` 1 |
| STABLE | yes | yes | leave untouched (live) |
| STABLE | no  | yes | add the session entry; fold publishers into top-level |
| any | — | `(no data)` | leave untouched |

- Only `COMING_SOON` and `STABLE` feeds are modified.
- Added sessions copy `benchmarkMapping` from the feed's REGULAR session and
  use the standard US-equity `marketSchedule` template for the session.
- `minPublishers`: REGULAR 3 (→2 when ≤5 publishers), PRE/POST 2, OVERNIGHT 1;
  top-level set to 1 only on COMING_SOON promotion.
- Publisher `{0, 1, 9, 13, 15}` (aggregate sentinel + Lazer) are stripped from
  every list defensively, with a warning.

## Safety

- `--dry-run` previews everything and writes nothing.
- A real run copies the config to `<config>.bak` before writing.
- Existing live (STABLE) sessions are never overwritten.

## Compared to update_config_from_summary.py

| Feature        | `update_config_from_summary.py` | `apply_allowed_to_config.py`        |
| -------------- | ------------------------------- | ----------------------------------- |
| Input          | `feed_readiness.py` CSV         | dq_summary `.xlsx` "allowed" sheet  |
| Multi-date     | Intersects across dates         | One vetted date per workbook        |
| STABLE feeds   | Refreshes existing sessions     | Never touches live sessions; adds new only |
| Added sessions | Omits `benchmarkMapping`        | Copies `benchmarkMapping` from REGULAR |

## Tests

```bash
python3 -m pytest lazer_dq/tests/test_apply_allowed_to_config.py -v
```
```

- [ ] **Step 2: Add the Scripts-table row in CLAUDE.md**

In `CLAUDE.md`, in the Scripts table (the big table under `## Scripts`), add a row after the `update_config_from_summary.py` row:

```markdown
| `lazer_dq/apply_allowed_to_config.py`  | Apply dq_summary "allowed" sheet to after.json (promote + add sessions)                                | `python3 -m lazer_dq.apply_allowed_to_config --xlsx dq_summary_X.xlsx --config after_1.json --dry-run` | [docs/apply_allowed_to_config.md](docs/apply_allowed_to_config.md)       |
```

- [ ] **Step 3: Add a Key Gotchas bullet in CLAUDE.md**

In `CLAUDE.md` under `## Key Gotchas`, add:

```markdown
- **`apply_allowed_to_config` vs `update_config_from_summary`** — `lazer_dq/apply_allowed_to_config.py` consumes the dq_summary `.xlsx` "allowed" sheet (from `summarize_feeds.py`); `update_config_from_summary.py` consumes the `feed_readiness.py` CSV. The former only ever changes state on `COMING_SOON` feeds and never overwrites a live (`STABLE`) session — it only *adds* missing sessions to STABLE feeds. Both share `lib/json_surgery.py` for raw-text block surgery.
```

- [ ] **Step 4: Run pre-commit on changed files**

Run: `pre-commit run --files docs/apply_allowed_to_config.md CLAUDE.md lazer_dq/apply_allowed_to_config.py lib/json_surgery.py`
Expected: hooks pass (black, prettier, trailing-whitespace, end-of-file-fixer). If a hook reformats a file, re-stage and re-run until clean.

- [ ] **Step 5: Commit**

```bash
git add docs/apply_allowed_to_config.md CLAUDE.md
git commit -m "docs(lazer_dq): document apply_allowed_to_config

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>"
```

---

## Final verification

- [ ] **Run the full relevant test suite**

Run: `python3 -m pytest lazer_dq/tests/test_apply_allowed_to_config.py tests/lib/test_json_surgery.py tests/test_update_config_from_summary.py -q`
Expected: all new tests pass; `test_update_config_from_summary.py` still shows the same **4 pre-existing CLI failures** and no others (i.e. the refactor introduced no regressions).

- [ ] **Confirm the design's expected outcome holds** (Task 7, Step 1 tally: 174 promoted / 0 added / 52 no-data).
