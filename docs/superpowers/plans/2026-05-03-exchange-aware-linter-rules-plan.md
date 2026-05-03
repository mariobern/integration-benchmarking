# Exchange-Aware Linter Rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add 9 lint rules (E019–E025, W010, W011) to `config_linter.py` covering the new exchange-inheritance feature in `after.json`, in two new modules to keep file sizes within the project's 800-line guideline.

**Architecture:** Pure-stdlib Python. New `lib/schedule_format.py` exposes a single `validate_holiday_token` function. New `lib/exchange_lint.py` exposes `check_exchanges(feeds, exchanges)` returning a `list[LintFinding]`. Orchestrator in `lib/config_lint.py` adds one `findings.extend(...)` call. All new code is dict-literal-driven, no JSON fixtures.

**Tech Stack:** Python 3.10+, pytest, existing `LintFinding` dataclass from `lib/config_lint.py`.

**Spec reference:** `docs/superpowers/specs/2026-05-03-exchange-aware-linter-rules-design.md` (commit `fe4514c`).

**Branch:** `feat/exchange-aware-linter-rules`.

---

## Task 1: `validate_holiday_token` — basic kinds (C, O) + structural checks

**Files:**

- Create: `lib/schedule_format.py`
- Test: `tests/test_schedule_format.py`

- [ ] **Step 1: Write the failing tests for valid C/O tokens, invalid kinds, invalid month/day, malformed shape**

Create `tests/test_schedule_format.py`:

```python
"""Tests for lib/schedule_format.py."""

import pytest

from lib.schedule_format import validate_holiday_token


class TestBasicKinds:
    @pytest.mark.parametrize("token", ["0101/C", "0619/O", "1225/C", "0229/C"])
    def test_valid_kind(self, token):
        assert validate_holiday_token(token) is None


class TestInvalidKind:
    @pytest.mark.parametrize("token", ["0101/X", "0101/Z", "0101/"])
    def test_unknown_kind(self, token):
        result = validate_holiday_token(token)
        assert result is not None
        assert "unknown kind" in result or "expected MMDD/" in result


class TestInvalidMonth:
    @pytest.mark.parametrize("token", ["1340/C", "0001/C", "1301/C"])
    def test_invalid_month(self, token):
        result = validate_holiday_token(token)
        assert result is not None
        assert "invalid month" in result


class TestInvalidDay:
    @pytest.mark.parametrize(
        "token",
        ["0230/C", "0431/C", "0532/C", "0100/C"],
    )
    def test_invalid_day(self, token):
        result = validate_holiday_token(token)
        assert result is not None
        assert "invalid day" in result


class TestMalformedShape:
    @pytest.mark.parametrize(
        "token",
        ["315/C", "01015/C", "0101", "0101C", ""],
    )
    def test_malformed(self, token):
        result = validate_holiday_token(token)
        assert result is not None
        assert "expected MMDD/" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_schedule_format.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lib.schedule_format'`.

- [ ] **Step 3: Implement minimal `validate_holiday_token` (kinds C/O only, plus structural validation)**

Create `lib/schedule_format.py`:

```python
"""Validation helpers for marketSchedule / holidayOverrides token formats.

Pure functions, no I/O, no exceptions raised. Designed for the linter
to embed reason strings into LintFinding messages.
"""

from __future__ import annotations

import re
from typing import Optional

# Days per month (non-leap-year). 0229 is treated as valid since it is a
# legitimate holiday-override format that may apply on leap years.
_DAYS_PER_MONTH = {
    1: 31, 2: 29, 3: 31, 4: 30, 5: 31, 6: 30,
    7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31,
}

_TOKEN_SHAPE = re.compile(r"^(\d{2})(\d{2})/(.+)$")
_EXPECTED = "expected MMDD/{C|O|HHMM-HHMM}"


def validate_holiday_token(token: str) -> Optional[str]:
    """Return None if `token` is valid, else a short reason string.

    Accepted shapes:
        MMDD/C            (closed)
        MMDD/O            (open)
        MMDD/HHMM-HHMM    (early close / partial open)

    MM in 01..12. DD must be a real day for the month (0229 always valid).
    For the time-range form: start has HH in 00..23, end has HH in 00..24
    (HH=24 requires MM=00); end > start as a 4-digit integer.
    """
    if not isinstance(token, str):
        return _EXPECTED
    m = _TOKEN_SHAPE.match(token)
    if not m:
        return _EXPECTED
    mm_str, dd_str, kind = m.group(1), m.group(2), m.group(3)
    mm, dd = int(mm_str), int(dd_str)

    if not (1 <= mm <= 12):
        return f"invalid month {mm_str}"
    if not (1 <= dd <= _DAYS_PER_MONTH[mm]):
        return f"invalid day {dd_str} for month {mm_str}"

    if kind in ("C", "O"):
        return None

    # Time-range kind handled in Task 2; for now reject anything else.
    return f"unknown kind {kind!r}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_schedule_format.py -v`
Expected: all tests in `TestBasicKinds`, `TestInvalidKind`, `TestInvalidMonth`, `TestInvalidDay`, `TestMalformedShape` PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/schedule_format.py tests/test_schedule_format.py
git commit -m "feat(linter): add validate_holiday_token for C/O kinds"
```

---

## Task 2: `validate_holiday_token` — time-range kind

**Files:**

- Modify: `lib/schedule_format.py`
- Modify: `tests/test_schedule_format.py`

- [ ] **Step 1: Add failing tests for time-range tokens**

Append to `tests/test_schedule_format.py`:

```python
class TestTimeRange:
    @pytest.mark.parametrize(
        "token",
        [
            "0703/0930-1300",
            "0703/0000-2400",
            "0703/0930-2400",
        ],
    )
    def test_valid_time_range(self, token):
        assert validate_holiday_token(token) is None

    @pytest.mark.parametrize(
        "token",
        ["0703/0930-1", "0703/0930-25"],
    )
    def test_malformed_time_range(self, token):
        result = validate_holiday_token(token)
        assert result is not None
        assert "malformed time range" in result

    def test_invalid_hour(self):
        # Hour 25 is invalid even with full MMHH form
        result = validate_holiday_token("0703/0930-2500")
        assert result is not None
        assert "malformed time range" in result

    @pytest.mark.parametrize(
        "token",
        [
            "0703/0930-0930",   # zero-length
            "0703/2400-0000",   # reversed (start would be 24:00 anyway)
            "0703/1300-0930",   # end < start
        ],
    )
    def test_reversed_time_range(self, token):
        result = validate_holiday_token(token)
        assert result is not None
        # Either malformed (24:00 in start position) or reversed
        assert "reversed time range" in result or "malformed time range" in result

    def test_24_00_only_at_end(self):
        # 24:30 is invalid — when HH=24, MM must be 00
        result = validate_holiday_token("0703/0930-2430")
        assert result is not None
        assert "malformed time range" in result
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_schedule_format.py::TestTimeRange -v`
Expected: failures — current impl returns `unknown kind '0930-1300'` for valid time ranges.

- [ ] **Step 3: Extend implementation**

Replace the `if kind in ("C", "O"): return None` / `return f"unknown kind ..."` block at the bottom of `validate_holiday_token` with:

```python
    if kind in ("C", "O"):
        return None

    return _validate_time_range(kind)


_TIME_RANGE = re.compile(r"^(\d{2})(\d{2})-(\d{2})(\d{2})$")


def _validate_time_range(kind: str) -> Optional[str]:
    m = _TIME_RANGE.match(kind)
    if not m:
        return f"malformed time range {kind!r}"
    s_h, s_m, e_h, e_m = (int(m.group(i)) for i in range(1, 5))

    # Start: HH 00..23, MM 00..59
    if not (0 <= s_h <= 23 and 0 <= s_m <= 59):
        return f"malformed time range {kind!r}"
    # End: HH 00..24, MM 00..59; if HH=24 then MM must be 0
    if not (0 <= e_h <= 24 and 0 <= e_m <= 59):
        return f"malformed time range {kind!r}"
    if e_h == 24 and e_m != 0:
        return f"malformed time range {kind!r}"

    start = s_h * 100 + s_m
    end = e_h * 100 + e_m
    if end <= start:
        return f"reversed time range {kind!r}"
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_schedule_format.py -v`
Expected: all tests including the new `TestTimeRange` PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/schedule_format.py tests/test_schedule_format.py
git commit -m "feat(linter): support HHMM-HHMM time range in validate_holiday_token"
```

---

## Task 3: `lib/exchange_lint.py` skeleton + index helpers

**Files:**

- Create: `lib/exchange_lint.py`
- Test: `tests/test_exchange_lint.py`

- [ ] **Step 1: Write a smoke test that imports the module and calls the entry point on empty input**

Create `tests/test_exchange_lint.py`:

```python
"""Tests for lib/exchange_lint.py."""

import pytest

from lib.exchange_lint import check_exchanges


class TestEntryPoint:
    def test_empty_inputs(self):
        assert check_exchanges([], []) == []

    def test_no_exchanges_no_exchange_id(self):
        feeds = [{"feedId": 1, "symbol": "X", "marketSchedules": []}]
        assert check_exchanges(feeds, []) == []

    def test_non_list_exchanges_coerced(self):
        # Defensive coercion per spec
        feeds = [{"feedId": 1, "symbol": "X", "marketSchedules": []}]
        # Pass a dict instead of a list — should be treated as []
        assert check_exchanges(feeds, {"oops": "wrong type"}) == []
```

- [ ] **Step 2: Run smoke test to verify it fails**

Run: `pytest tests/test_exchange_lint.py::TestEntryPoint -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lib.exchange_lint'`.

- [ ] **Step 3: Implement the module skeleton with private index helpers and public entry point**

Create `lib/exchange_lint.py`:

```python
"""Exchange-aware lint rules: E019, E020, E021, E022, E023, E024, E025,
W010, W011.

Public entry point: check_exchanges(feeds, exchanges) -> list[LintFinding].
"""

from __future__ import annotations

from typing import Any, Optional

from lib.config_lint import LintFinding
from lib.schedule_format import validate_holiday_token


# Enum allowlists (per Exchange_Configuration_Guide.md).
_ASSET_CLASS = frozenset({
    "EXCHANGE_ASSET_CLASS_UNSPECIFIED",
    "EXCHANGE_ASSET_CLASS_EQUITY",
    "EXCHANGE_ASSET_CLASS_FUTURE",
})
_ASSET_SUBCLASS = frozenset({
    "EXCHANGE_ASSET_SUBCLASS_UNSPECIFIED",
    "EXCHANGE_ASSET_SUBCLASS_COMMON_STOCK",
    "EXCHANGE_ASSET_SUBCLASS_ETF",
    "EXCHANGE_ASSET_SUBCLASS_ENERGY",
    "EXCHANGE_ASSET_SUBCLASS_METALS",
    "EXCHANGE_ASSET_SUBCLASS_EQUITY",
    "EXCHANGE_ASSET_SUBCLASS_FIXED_INCOME",
    "EXCHANGE_ASSET_SUBCLASS_FX",
    "EXCHANGE_ASSET_SUBCLASS_AGRICULTURAL",
})
_ASSET_SECTOR = frozenset({
    "EXCHANGE_ASSET_SECTOR_UNSPECIFIED",
    "EXCHANGE_ASSET_SECTOR_TECHNOLOGY",
    "EXCHANGE_ASSET_SECTOR_FINANCIALS",
    "EXCHANGE_ASSET_SECTOR_BROAD_MARKET",
    "EXCHANGE_ASSET_SECTOR_OIL",
    "EXCHANGE_ASSET_SECTOR_METALS",
    "EXCHANGE_ASSET_SECTOR_INDEX",
    "EXCHANGE_ASSET_SECTOR_RATES",
    "EXCHANGE_ASSET_SECTOR_FX",
    "EXCHANGE_ASSET_SECTOR_AGRICULTURAL",
})

_DEFAULT_CLASS = "EXCHANGE_ASSET_CLASS_UNSPECIFIED"
_DEFAULT_SUBCLASS = "EXCHANGE_ASSET_SUBCLASS_UNSPECIFIED"
_DEFAULT_SECTOR = "EXCHANGE_ASSET_SECTOR_UNSPECIFIED"


def _is_well_formed(entry: dict) -> bool:
    """An entry is well-formed iff exchangeId is non-null AND name is a
    non-empty string. E021/E023/E025 only consider well-formed entries.
    Entries with empty/missing sessions are still well-formed for those
    rules (E020 handles the inheritance consequence per affected feed)."""
    if not isinstance(entry, dict):
        return False
    if entry.get("exchangeId") is None:
        return False
    name = entry.get("name")
    if not isinstance(name, str) or not name:
        return False
    return True


def _build_index(
    exchanges: list[dict],
) -> tuple[dict[Any, dict], dict[Any, set[str]]]:
    """Build (exchange_by_id, session_set_by_id) from well-formed entries.

    On duplicate id, last-write-wins (deterministic by iteration order).
    E023 reports the duplicate group; downstream rules use the surviving
    entry as canonical.
    """
    by_id: dict[Any, dict] = {}
    sessions_by_id: dict[Any, set[str]] = {}
    for e in exchanges:
        if not _is_well_formed(e):
            continue
        eid = e["exchangeId"]
        try:
            by_id[eid] = e
        except TypeError:
            # Unhashable id — skip; E024 should have caught this if it
            # was in the value, but well-formed already requires non-null.
            continue
        sessions_by_id[eid] = {
            s.get("session")
            for s in (e.get("sessions") or [])
            if isinstance(s, dict) and s.get("session")
        }
    return by_id, sessions_by_id


def check_exchanges(
    feeds: list[dict],
    exchanges: Any,
) -> list[LintFinding]:
    """Run E019, E020, E021, E022, E023, E024, E025, W010, W011.

    `exchanges` is defensively coerced to [] if not a list.
    """
    if not isinstance(exchanges, list):
        exchanges = []

    findings: list[LintFinding] = []
    # Subsequent tasks add: check_e024, check_e023, check_e021, check_e025,
    # check_e019_e020_w010_w011, check_e022.
    return findings
```

- [ ] **Step 4: Run smoke test to verify it passes**

Run: `pytest tests/test_exchange_lint.py::TestEntryPoint -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/exchange_lint.py tests/test_exchange_lint.py
git commit -m "feat(linter): scaffold exchange_lint module with entry point and index helpers"
```

---

## Task 4: E024 — missing required exchange fields

**Files:**

- Modify: `lib/exchange_lint.py`
- Modify: `tests/test_exchange_lint.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_exchange_lint.py`:

```python
class TestE024:
    _SESSIONS_OK = [{"session": "REGULAR", "marketSchedule": "UTC;O,O,O,O,O,O,O;"}]

    def test_well_formed_no_finding(self):
        ex = [{"exchangeId": 1, "name": "X", "sessions": self._SESSIONS_OK}]
        findings = check_exchanges([], ex)
        assert [f for f in findings if f.rule_id == "E024"] == []

    def test_missing_exchange_id(self):
        ex = [{"name": "X", "sessions": self._SESSIONS_OK}]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E024"]
        assert len(findings) == 1
        assert "missing required field 'exchangeId'" in findings[0].message
        assert findings[0].feed_id is None
        assert findings[0].symbol is None

    def test_missing_name(self):
        ex = [{"exchangeId": 1, "sessions": self._SESSIONS_OK}]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E024"]
        assert len(findings) == 1
        assert "missing required field 'name'" in findings[0].message

    def test_empty_name_string(self):
        ex = [{"exchangeId": 1, "name": "", "sessions": self._SESSIONS_OK}]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E024"]
        assert len(findings) == 1
        assert "missing required field 'name'" in findings[0].message

    def test_missing_sessions(self):
        ex = [{"exchangeId": 1, "name": "X"}]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E024"]
        assert len(findings) == 1
        assert "empty sessions list" in findings[0].message

    @pytest.mark.parametrize("sessions", [[], None, "not a list"])
    def test_empty_or_invalid_sessions(self, sessions):
        ex = [{"exchangeId": 1, "name": "X", "sessions": sessions}]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E024"]
        assert len(findings) == 1
        assert "empty sessions list" in findings[0].message

    def test_missing_two_fields_emits_two_findings(self):
        ex = [{"sessions": self._SESSIONS_OK}]  # missing exchangeId AND name
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E024"]
        assert len(findings) == 2
        msgs = sorted(f.message for f in findings)
        assert "exchangeId" in msgs[0]
        assert "name" in msgs[1]

    def test_index_is_zero_based(self):
        ex = [
            {"exchangeId": 1, "name": "OK", "sessions": self._SESSIONS_OK},
            {"name": "BROKEN", "sessions": self._SESSIONS_OK},  # index 1
        ]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E024"]
        assert len(findings) == 1
        assert "at index 1" in findings[0].message
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_exchange_lint.py::TestE024 -v`
Expected: all 9 tests FAIL (no findings emitted).

- [ ] **Step 3: Implement E024**

In `lib/exchange_lint.py`, add this function above `check_exchanges`:

```python
def _check_e024(exchanges: list) -> list[LintFinding]:
    """E024: missing required exchange fields (exchangeId, name, sessions)."""
    findings: list[LintFinding] = []
    for i, e in enumerate(exchanges):
        if not isinstance(e, dict):
            continue
        if e.get("exchangeId") is None:
            findings.append(LintFinding(
                rule_id="E024", severity="ERROR",
                message=f"exchange entry at index {i} is missing required field 'exchangeId'",
                feed_id=None, symbol=None,
            ))
        name = e.get("name")
        if not isinstance(name, str) or not name:
            findings.append(LintFinding(
                rule_id="E024", severity="ERROR",
                message=f"exchange entry at index {i} is missing required field 'name'",
                feed_id=None, symbol=None,
            ))
        sessions = e.get("sessions")
        if not isinstance(sessions, list) or len(sessions) == 0:
            findings.append(LintFinding(
                rule_id="E024", severity="ERROR",
                message=f"exchange entry at index {i} has empty sessions list",
                feed_id=None, symbol=None,
            ))
    return findings
```

In `check_exchanges`, after the defensive coercion, add:

```python
    findings.extend(_check_e024(exchanges))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_exchange_lint.py::TestE024 -v`
Expected: 9 PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/exchange_lint.py tests/test_exchange_lint.py
git commit -m "feat(linter): E024 — missing required exchange fields"
```

---

## Task 5: E023 — duplicate `exchangeId`

**Files:**

- Modify: `lib/exchange_lint.py`
- Modify: `tests/test_exchange_lint.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_exchange_lint.py`:

```python
class TestE023:
    _OK = {"sessions": [{"session": "REGULAR", "marketSchedule": "UTC;O,O,O,O,O,O,O;"}]}

    def test_distinct_ids_no_finding(self):
        ex = [
            {"exchangeId": 1, "name": "A", **self._OK},
            {"exchangeId": 2, "name": "B", **self._OK},
        ]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E023"]
        assert findings == []

    def test_duplicate_id_pair(self):
        ex = [
            {"exchangeId": 1, "name": "A", **self._OK},
            {"exchangeId": 1, "name": "B", **self._OK},
        ]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E023"]
        assert len(findings) == 1
        assert "duplicate exchangeId 1" in findings[0].message
        assert "appears on 2 entries" in findings[0].message

    def test_duplicate_id_three_way_emits_one_finding(self):
        ex = [
            {"exchangeId": 7, "name": "A", **self._OK},
            {"exchangeId": 7, "name": "B", **self._OK},
            {"exchangeId": 7, "name": "C", **self._OK},
        ]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E023"]
        assert len(findings) == 1
        assert "appears on 3 entries" in findings[0].message

    def test_malformed_entries_excluded(self):
        # Both entries missing 'name' — they're not well-formed,
        # E024 reports them, E023 ignores them.
        ex = [
            {"exchangeId": 1, **self._OK},
            {"exchangeId": 1, **self._OK},
        ]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E023"]
        assert findings == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_exchange_lint.py::TestE023 -v`
Expected: 3 of 4 FAIL (`test_malformed_entries_excluded` happens to pass since current impl emits no E023).

- [ ] **Step 3: Implement E023**

In `lib/exchange_lint.py`, add above `check_exchanges`:

```python
def _check_e023(exchanges: list) -> list[LintFinding]:
    """E023: duplicate exchangeId across well-formed entries."""
    from collections import Counter
    ids = [e["exchangeId"] for e in exchanges if _is_well_formed(e)]
    counts = Counter(ids)
    findings: list[LintFinding] = []
    for eid, n in counts.items():
        if n >= 2:
            findings.append(LintFinding(
                rule_id="E023", severity="ERROR",
                message=f"duplicate exchangeId {eid!r} appears on {n} entries in exchanges[]",
                feed_id=None, symbol=None,
            ))
    return findings
```

In `check_exchanges`, after `_check_e024`, add:

```python
    findings.extend(_check_e023(exchanges))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_exchange_lint.py::TestE023 -v`
Expected: 4 PASS.

Run all module tests so far: `pytest tests/test_exchange_lint.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/exchange_lint.py tests/test_exchange_lint.py
git commit -m "feat(linter): E023 — duplicate exchangeId in exchanges[]"
```

---

## Task 6: E021 — duplicate exchange tuple (with E024 gate + distinct-id qualifier)

**Files:**

- Modify: `lib/exchange_lint.py`
- Modify: `tests/test_exchange_lint.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_exchange_lint.py`:

```python
class TestE021:
    _SESS = [{"session": "REGULAR", "marketSchedule": "UTC;O,O,O,O,O,O,O;"}]

    def test_distinct_tuples_no_finding(self):
        ex = [
            {"exchangeId": 1, "name": "NASDAQ",
             "assetClass": "EXCHANGE_ASSET_CLASS_EQUITY",
             "assetSubclass": "EXCHANGE_ASSET_SUBCLASS_COMMON_STOCK",
             "assetSector": "EXCHANGE_ASSET_SECTOR_TECHNOLOGY",
             "sessions": self._SESS},
            {"exchangeId": 2, "name": "NASDAQ",
             "assetClass": "EXCHANGE_ASSET_CLASS_EQUITY",
             "assetSubclass": "EXCHANGE_ASSET_SUBCLASS_ETF",
             "assetSector": "EXCHANGE_ASSET_SECTOR_BROAD_MARKET",
             "sessions": self._SESS},
        ]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E021"]
        assert findings == []

    def test_duplicate_tuple_distinct_ids(self):
        ex = [
            {"exchangeId": 1, "name": "NASDAQ",
             "assetClass": "EXCHANGE_ASSET_CLASS_EQUITY",
             "assetSubclass": "EXCHANGE_ASSET_SUBCLASS_COMMON_STOCK",
             "assetSector": "EXCHANGE_ASSET_SECTOR_TECHNOLOGY",
             "sessions": self._SESS},
            {"exchangeId": 2, "name": "NASDAQ",
             "assetClass": "EXCHANGE_ASSET_CLASS_EQUITY",
             "assetSubclass": "EXCHANGE_ASSET_SUBCLASS_COMMON_STOCK",
             "assetSector": "EXCHANGE_ASSET_SECTOR_TECHNOLOGY",
             "sessions": self._SESS},
        ]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E021"]
        assert len(findings) == 1
        assert "NASDAQ" in findings[0].message
        assert "[1, 2]" in findings[0].message

    def test_three_way_duplicate_one_finding(self):
        common = {
            "name": "X",
            "assetClass": "EXCHANGE_ASSET_CLASS_UNSPECIFIED",
            "assetSubclass": "EXCHANGE_ASSET_SUBCLASS_UNSPECIFIED",
            "assetSector": "EXCHANGE_ASSET_SECTOR_UNSPECIFIED",
            "sessions": self._SESS,
        }
        ex = [
            {"exchangeId": 1, **common},
            {"exchangeId": 2, **common},
            {"exchangeId": 3, **common},
        ]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E021"]
        assert len(findings) == 1
        assert "[1, 2, 3]" in findings[0].message

    def test_missing_classification_treated_as_unspecified(self):
        ex = [
            {"exchangeId": 1, "name": "X", "sessions": self._SESS},
            {"exchangeId": 2, "name": "X",
             "assetClass": "EXCHANGE_ASSET_CLASS_UNSPECIFIED",
             "assetSubclass": "EXCHANGE_ASSET_SUBCLASS_UNSPECIFIED",
             "assetSector": "EXCHANGE_ASSET_SECTOR_UNSPECIFIED",
             "sessions": self._SESS},
        ]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E021"]
        assert len(findings) == 1

    def test_same_id_same_tuple_only_e023_not_e021(self):
        common = {
            "name": "X",
            "sessions": self._SESS,
        }
        ex = [
            {"exchangeId": 1, **common},
            {"exchangeId": 1, **common},
        ]
        all_findings = check_exchanges([], ex)
        assert any(f.rule_id == "E023" for f in all_findings)
        assert not any(f.rule_id == "E021" for f in all_findings)

    def test_malformed_entries_excluded(self):
        ex = [
            {"name": "X", "sessions": self._SESS},  # missing exchangeId
            {"name": "X", "sessions": self._SESS},
        ]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E021"]
        assert findings == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_exchange_lint.py::TestE021 -v`
Expected: tests with expected E021 findings FAIL.

- [ ] **Step 3: Implement E021**

In `lib/exchange_lint.py`, add above `check_exchanges`:

```python
def _check_e021(exchanges: list) -> list[LintFinding]:
    """E021: duplicate (name, class, subclass, sector) tuple across
    well-formed entries with distinct exchangeIds."""
    # Group by tuple, tracking exchangeIds.
    groups: dict[tuple, list] = {}
    for e in exchanges:
        if not _is_well_formed(e):
            continue
        tup = (
            e["name"],
            e.get("assetClass") or _DEFAULT_CLASS,
            e.get("assetSubclass") or _DEFAULT_SUBCLASS,
            e.get("assetSector") or _DEFAULT_SECTOR,
        )
        groups.setdefault(tup, []).append(e["exchangeId"])

    findings: list[LintFinding] = []
    for tup, ids in groups.items():
        # Only report duplicates across DISTINCT ids
        # (same-id duplicates are E023's domain).
        unique_ids = sorted(set(ids), key=lambda x: (str(type(x)), x))
        if len(unique_ids) >= 2:
            name, cls, sub, sec = tup
            findings.append(LintFinding(
                rule_id="E021", severity="ERROR",
                message=(
                    f"duplicate exchange tuple "
                    f"(name={name}, class={cls}, subclass={sub}, sector={sec}) "
                    f"on exchangeIds {unique_ids}"
                ),
                feed_id=None, symbol=None,
            ))
    return findings
```

In `check_exchanges`, after `_check_e023`, add:

```python
    findings.extend(_check_e021(exchanges))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_exchange_lint.py::TestE021 -v`
Expected: 6 PASS.

Run all module tests: `pytest tests/test_exchange_lint.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/exchange_lint.py tests/test_exchange_lint.py
git commit -m "feat(linter): E021 — duplicate exchange tuple across distinct exchangeIds"
```

---

## Task 7: E025 — unknown enum value

**Files:**

- Modify: `lib/exchange_lint.py`
- Modify: `tests/test_exchange_lint.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_exchange_lint.py`:

```python
class TestE025:
    _SESS = [{"session": "REGULAR", "marketSchedule": "UTC;O,O,O,O,O,O,O;"}]

    def test_known_values_no_finding(self):
        ex = [{
            "exchangeId": 1, "name": "X",
            "assetClass": "EXCHANGE_ASSET_CLASS_EQUITY",
            "assetSubclass": "EXCHANGE_ASSET_SUBCLASS_COMMON_STOCK",
            "assetSector": "EXCHANGE_ASSET_SECTOR_TECHNOLOGY",
            "sessions": self._SESS,
        }]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E025"]
        assert findings == []

    def test_unspecified_no_finding(self):
        ex = [{
            "exchangeId": 1, "name": "X",
            "assetClass": "EXCHANGE_ASSET_CLASS_UNSPECIFIED",
            "assetSubclass": "EXCHANGE_ASSET_SUBCLASS_UNSPECIFIED",
            "assetSector": "EXCHANGE_ASSET_SECTOR_UNSPECIFIED",
            "sessions": self._SESS,
        }]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E025"]
        assert findings == []

    def test_missing_classification_no_finding(self):
        # Missing -> default UNSPECIFIED; not flagged
        ex = [{"exchangeId": 1, "name": "X", "sessions": self._SESS}]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E025"]
        assert findings == []

    def test_unknown_class(self):
        ex = [{
            "exchangeId": 1, "name": "X",
            "assetClass": "EXCHANGE_ASSET_CLASS_EQUTIY",  # typo
            "sessions": self._SESS,
        }]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E025"]
        assert len(findings) == 1
        assert "assetClass" in findings[0].message
        assert "EQUTIY" in findings[0].message

    def test_unknown_subclass(self):
        ex = [{
            "exchangeId": 1, "name": "X",
            "assetSubclass": "EXCHANGE_ASSET_SUBCLASS_BANANA",
            "sessions": self._SESS,
        }]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E025"]
        assert len(findings) == 1
        assert "assetSubclass" in findings[0].message

    def test_unknown_sector(self):
        ex = [{
            "exchangeId": 1, "name": "X",
            "assetSector": "EXCHANGE_ASSET_SECTOR_NONSENSE",
            "sessions": self._SESS,
        }]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E025"]
        assert len(findings) == 1
        assert "assetSector" in findings[0].message

    def test_three_unknown_fields_emits_three(self):
        ex = [{
            "exchangeId": 1, "name": "X",
            "assetClass": "WRONG1",
            "assetSubclass": "WRONG2",
            "assetSector": "WRONG3",
            "sessions": self._SESS,
        }]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E025"]
        assert len(findings) == 3

    def test_malformed_entries_excluded(self):
        ex = [{"name": "X", "assetClass": "WRONG", "sessions": self._SESS}]  # no id
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E025"]
        assert findings == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_exchange_lint.py::TestE025 -v`
Expected: failures on the unknown-value tests.

- [ ] **Step 3: Implement E025**

In `lib/exchange_lint.py`, add above `check_exchanges`:

```python
def _check_e025(exchanges: list) -> list[LintFinding]:
    """E025: unknown enum for assetClass / assetSubclass / assetSector
    on well-formed entries. Missing keys (treated as UNSPECIFIED) are
    not flagged."""
    findings: list[LintFinding] = []
    fields = (
        ("assetClass", _ASSET_CLASS),
        ("assetSubclass", _ASSET_SUBCLASS),
        ("assetSector", _ASSET_SECTOR),
    )
    for e in exchanges:
        if not _is_well_formed(e):
            continue
        eid = e["exchangeId"]
        for fname, allowed in fields:
            if fname not in e:
                continue  # default UNSPECIFIED applies
            val = e[fname]
            if val not in allowed:
                findings.append(LintFinding(
                    rule_id="E025", severity="ERROR",
                    message=f"exchange {eid} field {fname}={val!r} is not a known enum value",
                    feed_id=None, symbol=None,
                ))
    return findings
```

In `check_exchanges`, after `_check_e021`, add:

```python
    findings.extend(_check_e025(exchanges))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_exchange_lint.py::TestE025 -v`
Expected: 8 PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/exchange_lint.py tests/test_exchange_lint.py
git commit -m "feat(linter): E025 — unknown enum value for asset classification fields"
```

---

## Task 8: E019 — dangling `exchangeId` reference

**Files:**

- Modify: `lib/exchange_lint.py`
- Modify: `tests/test_exchange_lint.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_exchange_lint.py`:

```python
class TestE019:
    _OK = {"sessions": [{"session": "REGULAR", "marketSchedule": "UTC;O,O,O,O,O,O,O;"}]}

    def test_resolvable_no_finding(self):
        ex = [{"exchangeId": 1, "name": "X", **self._OK}]
        feeds = [{"feedId": 100, "symbol": "S", "exchangeId": 1, "marketSchedules": []}]
        findings = [f for f in check_exchanges(feeds, ex) if f.rule_id == "E019"]
        assert findings == []

    def test_no_exchange_id_no_finding(self):
        ex = []
        feeds = [{"feedId": 100, "symbol": "S", "marketSchedules": []}]
        findings = [f for f in check_exchanges(feeds, ex) if f.rule_id == "E019"]
        assert findings == []

    def test_dangling_int_id(self):
        ex = [{"exchangeId": 1, "name": "X", **self._OK}]
        feeds = [{"feedId": 100, "symbol": "S", "exchangeId": 99999, "marketSchedules": []}]
        findings = [f for f in check_exchanges(feeds, ex) if f.rule_id == "E019"]
        assert len(findings) == 1
        assert findings[0].feed_id == 100
        assert findings[0].symbol == "S"
        assert "99999" in findings[0].message

    def test_dangling_string_id_distinct_from_int(self):
        ex = [{"exchangeId": 1, "name": "X", **self._OK}]
        feeds = [{"feedId": 100, "symbol": "S", "exchangeId": "1", "marketSchedules": []}]
        findings = [f for f in check_exchanges(feeds, ex) if f.rule_id == "E019"]
        assert len(findings) == 1
        assert "'1'" in findings[0].message  # repr() of string

    def test_unhashable_id_does_not_raise(self):
        ex = [{"exchangeId": 1, "name": "X", **self._OK}]
        feeds = [{"feedId": 100, "symbol": "S", "exchangeId": [1, 2], "marketSchedules": []}]
        findings = [f for f in check_exchanges(feeds, ex) if f.rule_id == "E019"]
        assert len(findings) == 1
        assert "[1, 2]" in findings[0].message

    def test_no_exchanges_array_with_exchange_id_set(self):
        feeds = [{"feedId": 100, "symbol": "S", "exchangeId": 1, "marketSchedules": []}]
        findings = [f for f in check_exchanges(feeds, []) if f.rule_id == "E019"]
        assert len(findings) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_exchange_lint.py::TestE019 -v`
Expected: 4 of 6 FAIL (no E019 emitted yet).

- [ ] **Step 3: Implement E019**

In `lib/exchange_lint.py`, add above `check_exchanges`:

```python
def _is_resolvable(eid: Any, by_id: dict[Any, dict]) -> bool:
    """Return True iff eid is hashable and present in by_id."""
    try:
        return eid in by_id
    except TypeError:
        return False


def _check_e019(
    feeds: list[dict],
    by_id: dict[Any, dict],
) -> tuple[list[LintFinding], set[Optional[int]]]:
    """E019: dangling exchangeId. Returns (findings, set of feed_ids that
    fired E019) — used downstream to suppress E020 + W010 on those feeds."""
    findings: list[LintFinding] = []
    suppressed_feeds: set[Optional[int]] = set()
    for feed in feeds:
        if not isinstance(feed, dict):
            continue
        eid = feed.get("exchangeId")
        if eid is None:
            continue
        if _is_resolvable(eid, by_id):
            continue
        findings.append(LintFinding(
            rule_id="E019", severity="ERROR",
            message=f"feed references exchangeId {eid!r} which is not defined in exchanges[]",
            feed_id=feed.get("feedId"), symbol=feed.get("symbol"),
        ))
        suppressed_feeds.add(feed.get("feedId"))
    return findings, suppressed_feeds
```

In `check_exchanges`, after `_check_e025`, add:

```python
    by_id, sessions_by_id = _build_index(exchanges)
    e019_findings, e019_suppressed = _check_e019(feeds, by_id)
    findings.extend(e019_findings)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_exchange_lint.py::TestE019 -v`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/exchange_lint.py tests/test_exchange_lint.py
git commit -m "feat(linter): E019 — dangling exchangeId reference"
```

---

## Task 9: E020 — session has no schedule source

**Files:**

- Modify: `lib/exchange_lint.py`
- Modify: `tests/test_exchange_lint.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_exchange_lint.py`:

```python
class TestE020:
    _EX = [{
        "exchangeId": 1, "name": "X",
        "sessions": [{"session": "REGULAR", "marketSchedule": "UTC;O,O,O,O,O,O,O;"}],
    }]

    def test_inline_schedule_no_finding(self):
        feeds = [{"feedId": 100, "symbol": "S", "marketSchedules": [
            {"session": "REGULAR", "marketSchedule": "UTC;O,O,O,O,O,O,O;"},
        ]}]
        findings = [f for f in check_exchanges(feeds, []) if f.rule_id == "E020"]
        assert findings == []

    def test_inheritance_no_finding(self):
        feeds = [{"feedId": 100, "symbol": "S", "exchangeId": 1, "marketSchedules": [
            {"session": "REGULAR"},  # no marketSchedule, inherits
        ]}]
        findings = [f for f in check_exchanges(feeds, self._EX) if f.rule_id == "E020"]
        assert findings == []

    def test_case_1_no_exchange_id(self):
        feeds = [{"feedId": 100, "symbol": "S", "marketSchedules": [
            {"session": "REGULAR"},  # no marketSchedule, no exchangeId
        ]}]
        findings = [f for f in check_exchanges(feeds, []) if f.rule_id == "E020"]
        assert len(findings) == 1
        assert "feed has no exchangeId" in findings[0].message
        assert findings[0].feed_id == 100

    def test_case_1_empty_string_market_schedule(self):
        feeds = [{"feedId": 100, "symbol": "S", "marketSchedules": [
            {"session": "REGULAR", "marketSchedule": ""},
        ]}]
        findings = [f for f in check_exchanges(feeds, []) if f.rule_id == "E020"]
        assert len(findings) == 1

    def test_case_2_exchange_missing_session(self):
        # Exchange defines REGULAR; feed wants PRE_MARKET
        feeds = [{"feedId": 100, "symbol": "S", "exchangeId": 1, "marketSchedules": [
            {"session": "PRE_MARKET"},
        ]}]
        findings = [f for f in check_exchanges(feeds, self._EX) if f.rule_id == "E020"]
        assert len(findings) == 1
        assert "PRE_MARKET" in findings[0].message
        assert "exchange 1" in findings[0].message

    def test_e019_suppresses_e020(self):
        feeds = [{"feedId": 100, "symbol": "S", "exchangeId": 99999, "marketSchedules": [
            {"session": "REGULAR"},  # would fire E020 case 2 if E019 didn't suppress
        ]}]
        all_findings = check_exchanges(feeds, self._EX)
        assert any(f.rule_id == "E019" for f in all_findings)
        assert not any(f.rule_id == "E020" for f in all_findings)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_exchange_lint.py::TestE020 -v`
Expected: case_1, case_2, empty-string FAIL.

- [ ] **Step 3: Implement E020**

In `lib/exchange_lint.py`, add above `check_exchanges`:

```python
def _check_e020(
    feeds: list[dict],
    by_id: dict[Any, dict],
    sessions_by_id: dict[Any, set[str]],
    e019_suppressed: set[Optional[int]],
) -> list[LintFinding]:
    """E020: per-session schedule source missing.
    Skipped on feeds where E019 fired."""
    findings: list[LintFinding] = []
    for feed in feeds:
        if not isinstance(feed, dict):
            continue
        fid = feed.get("feedId")
        if fid in e019_suppressed:
            continue
        eid = feed.get("exchangeId")
        sessions = feed.get("marketSchedules") or []
        for ms in sessions:
            if not isinstance(ms, dict):
                continue
            if ms.get("marketSchedule"):  # falsy = missing OR empty string
                continue
            session_name = ms.get("session")
            if eid is None:
                findings.append(LintFinding(
                    rule_id="E020", severity="ERROR",
                    message=f"feed session {session_name} has no marketSchedule and feed has no exchangeId — no schedule source",
                    feed_id=fid, symbol=feed.get("symbol"),
                ))
            else:
                # Resolvable (else E019 would have suppressed): check the
                # exchange defines this session.
                if session_name not in sessions_by_id.get(eid, set()):
                    findings.append(LintFinding(
                        rule_id="E020", severity="ERROR",
                        message=f"feed session {session_name} has no marketSchedule and exchange {eid} does not define a {session_name} session",
                        feed_id=fid, symbol=feed.get("symbol"),
                    ))
    return findings
```

In `check_exchanges`, after the `_check_e019` block, add:

```python
    findings.extend(_check_e020(feeds, by_id, sessions_by_id, e019_suppressed))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_exchange_lint.py::TestE020 -v`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/exchange_lint.py tests/test_exchange_lint.py
git commit -m "feat(linter): E020 — session has no schedule source"
```

---

## Task 10: W010 — inline `marketSchedule` shadows exchange

**Files:**

- Modify: `lib/exchange_lint.py`
- Modify: `tests/test_exchange_lint.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_exchange_lint.py`:

```python
class TestW010:
    _EX = [{
        "exchangeId": 1, "name": "X",
        "sessions": [{"session": "REGULAR", "marketSchedule": "UTC;O,O,O,O,O,O,O;"}],
    }]

    def test_no_exchange_id_no_finding(self):
        feeds = [{"feedId": 100, "symbol": "S", "marketSchedules": [
            {"session": "REGULAR", "marketSchedule": "UTC;C,C,C,C,C,C,C;"},
        ]}]
        findings = [f for f in check_exchanges(feeds, []) if f.rule_id == "W010"]
        assert findings == []

    def test_inline_no_inherit_no_finding(self):
        # exchange has no PRE_MARKET, feed has inline PRE_MARKET — nothing to shadow
        feeds = [{"feedId": 100, "symbol": "S", "exchangeId": 1, "marketSchedules": [
            {"session": "PRE_MARKET", "marketSchedule": "UTC;O,O,O,O,O,O,O;"},
        ]}]
        findings = [f for f in check_exchanges(feeds, self._EX) if f.rule_id == "W010"]
        assert findings == []

    def test_shadow_fires(self):
        feeds = [{"feedId": 100, "symbol": "S", "exchangeId": 1, "marketSchedules": [
            {"session": "REGULAR", "marketSchedule": "UTC;C,C,C,C,C,C,C;"},
        ]}]
        findings = [f for f in check_exchanges(feeds, self._EX) if f.rule_id == "W010"]
        assert len(findings) == 1
        assert findings[0].severity == "WARNING"
        assert "REGULAR" in findings[0].message
        assert "exchangeId 1" in findings[0].message

    def test_e019_suppresses_w010(self):
        feeds = [{"feedId": 100, "symbol": "S", "exchangeId": 99999, "marketSchedules": [
            {"session": "REGULAR", "marketSchedule": "UTC;C,C,C,C,C,C,C;"},
        ]}]
        findings = [f for f in check_exchanges(feeds, self._EX) if f.rule_id == "W010"]
        assert findings == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_exchange_lint.py::TestW010 -v`
Expected: `test_shadow_fires` FAIL.

- [ ] **Step 3: Implement W010**

In `lib/exchange_lint.py`, add above `check_exchanges`:

```python
def _check_w010(
    feeds: list[dict],
    sessions_by_id: dict[Any, set[str]],
    e019_suppressed: set[Optional[int]],
    w011_suppressed: set[Optional[int]],
) -> list[LintFinding]:
    """W010: inline marketSchedule shadows exchange-provided schedule.
    Skipped on feeds where E019 or W011 fired."""
    findings: list[LintFinding] = []
    for feed in feeds:
        if not isinstance(feed, dict):
            continue
        fid = feed.get("feedId")
        if fid in e019_suppressed or fid in w011_suppressed:
            continue
        eid = feed.get("exchangeId")
        if eid is None:
            continue
        for ms in feed.get("marketSchedules") or []:
            if not isinstance(ms, dict):
                continue
            if not ms.get("marketSchedule"):
                continue
            session_name = ms.get("session")
            if session_name in sessions_by_id.get(eid, set()):
                findings.append(LintFinding(
                    rule_id="W010", severity="WARNING",
                    message=f"feed session {session_name} has both inline marketSchedule and exchangeId {eid}; inline takes priority — exchange schedule unused for this session",
                    feed_id=fid, symbol=feed.get("symbol"),
                ))
    return findings
```

In `check_exchanges`, AFTER E020, append (W011 not yet implemented; pass empty set for now):

```python
    w011_suppressed: set[Optional[int]] = set()  # populated by _check_w011 in Task 11
    findings.extend(_check_w010(feeds, sessions_by_id, e019_suppressed, w011_suppressed))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_exchange_lint.py::TestW010 -v`
Expected: 4 PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/exchange_lint.py tests/test_exchange_lint.py
git commit -m "feat(linter): W010 — inline marketSchedule shadows exchange"
```

---

## Task 11: W011 — `exchangeId` is dead code (and connect W010 suppression)

**Files:**

- Modify: `lib/exchange_lint.py`
- Modify: `tests/test_exchange_lint.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_exchange_lint.py`:

```python
class TestW011:
    _EX = [{
        "exchangeId": 1, "name": "X",
        "sessions": [
            {"session": "REGULAR", "marketSchedule": "UTC;O,O,O,O,O,O,O;"},
            {"session": "PRE_MARKET", "marketSchedule": "UTC;O,O,O,O,O,O,O;"},
        ],
    }]

    def test_partial_inherit_no_finding(self):
        feeds = [{"feedId": 100, "symbol": "S", "exchangeId": 1, "marketSchedules": [
            {"session": "REGULAR", "marketSchedule": "UTC;C,C,C,C,C,C,C;"},
            {"session": "PRE_MARKET"},  # this one inherits
        ]}]
        findings = [f for f in check_exchanges(feeds, self._EX) if f.rule_id == "W011"]
        assert findings == []

    def test_all_inline_fires(self):
        feeds = [{"feedId": 100, "symbol": "S", "exchangeId": 1, "marketSchedules": [
            {"session": "REGULAR", "marketSchedule": "UTC;C,C,C,C,C,C,C;"},
            {"session": "PRE_MARKET", "marketSchedule": "UTC;O,O,O,O,O,O,O;"},
        ]}]
        findings = [f for f in check_exchanges(feeds, self._EX) if f.rule_id == "W011"]
        assert len(findings) == 1
        assert findings[0].feed_id == 100
        assert "exchangeId 1" in findings[0].message

    def test_zero_sessions_no_finding(self):
        feeds = [{"feedId": 100, "symbol": "S", "exchangeId": 1, "marketSchedules": []}]
        findings = [f for f in check_exchanges(feeds, self._EX) if f.rule_id == "W011"]
        assert findings == []

    def test_w011_suppresses_w010(self):
        feeds = [{"feedId": 100, "symbol": "S", "exchangeId": 1, "marketSchedules": [
            {"session": "REGULAR", "marketSchedule": "UTC;C,C,C,C,C,C,C;"},
            {"session": "PRE_MARKET", "marketSchedule": "UTC;O,O,O,O,O,O,O;"},
        ]}]
        all_findings = check_exchanges(feeds, self._EX)
        assert any(f.rule_id == "W011" for f in all_findings)
        assert not any(f.rule_id == "W010" for f in all_findings)

    def test_e019_suppresses_w011(self):
        feeds = [{"feedId": 100, "symbol": "S", "exchangeId": 99999, "marketSchedules": [
            {"session": "REGULAR", "marketSchedule": "UTC;C,C,C,C,C,C,C;"},
        ]}]
        findings = [f for f in check_exchanges(feeds, self._EX) if f.rule_id == "W011"]
        assert findings == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_exchange_lint.py::TestW011 -v`
Expected: `test_all_inline_fires` and `test_w011_suppresses_w010` FAIL.

- [ ] **Step 3: Implement W011 and wire its output into W010 suppression**

In `lib/exchange_lint.py`, add above `check_exchanges`:

```python
def _check_w011(
    feeds: list[dict],
    e019_suppressed: set[Optional[int]],
) -> tuple[list[LintFinding], set[Optional[int]]]:
    """W011: feed has exchangeId but every session uses inline marketSchedule.
    Returns (findings, set of feed_ids that fired W011) for downstream W010
    suppression."""
    findings: list[LintFinding] = []
    suppressed: set[Optional[int]] = set()
    for feed in feeds:
        if not isinstance(feed, dict):
            continue
        fid = feed.get("feedId")
        if fid in e019_suppressed:
            continue
        eid = feed.get("exchangeId")
        if eid is None:
            continue
        sessions = feed.get("marketSchedules") or []
        if not sessions:  # zero sessions: vacuous, do not fire
            continue
        all_inline = all(
            isinstance(ms, dict) and ms.get("marketSchedule")
            for ms in sessions
        )
        if all_inline:
            findings.append(LintFinding(
                rule_id="W011", severity="WARNING",
                message=f"feed has exchangeId {eid} but every session has an inline marketSchedule — exchangeId is unused",
                feed_id=fid, symbol=feed.get("symbol"),
            ))
            suppressed.add(fid)
    return findings, suppressed
```

In `check_exchanges`, replace the previous W010 wiring with:

```python
    w011_findings, w011_suppressed = _check_w011(feeds, e019_suppressed)
    findings.extend(w011_findings)
    findings.extend(_check_w010(feeds, sessions_by_id, e019_suppressed, w011_suppressed))
```

(i.e., compute W011 BEFORE calling W010 so the suppression set is populated.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_exchange_lint.py::TestW011 tests/test_exchange_lint.py::TestW010 -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/exchange_lint.py tests/test_exchange_lint.py
git commit -m "feat(linter): W011 — exchangeId is dead code (suppresses W010)"
```

---

## Task 12: Cross-rule suppression-matrix tests

**Files:**

- Modify: `tests/test_exchange_lint.py` (no implementation changes — verifying existing wiring)

- [ ] **Step 1: Add suppression interaction tests**

Append to `tests/test_exchange_lint.py`:

```python
class TestSuppressionMatrix:
    """Validates the interaction matrix from the spec:
        E019 → suppresses E020 + W010 on same feed
        W011 → suppresses W010 on same feed
        E024 → gates E021/E023/E025 (entries excluded)
    """

    _EX = [{
        "exchangeId": 1, "name": "X",
        "sessions": [{"session": "REGULAR", "marketSchedule": "UTC;O,O,O,O,O,O,O;"}],
    }]

    def test_e019_blocks_both_e020_and_w010(self):
        feeds = [{"feedId": 100, "symbol": "S", "exchangeId": 999, "marketSchedules": [
            {"session": "REGULAR", "marketSchedule": "UTC;C,C,C,C,C,C,C;"},
            {"session": "PRE_MARKET"},  # would fire E020 case 2
        ]}]
        findings = check_exchanges(feeds, self._EX)
        rule_ids = {f.rule_id for f in findings}
        assert "E019" in rule_ids
        assert "E020" not in rule_ids
        assert "W010" not in rule_ids

    def test_w011_blocks_w010_only(self):
        feeds = [{"feedId": 100, "symbol": "S", "exchangeId": 1, "marketSchedules": [
            {"session": "REGULAR", "marketSchedule": "UTC;C,C,C,C,C,C,C;"},
        ]}]
        findings = check_exchanges(feeds, self._EX)
        rule_ids = {f.rule_id for f in findings}
        assert "W011" in rule_ids
        assert "W010" not in rule_ids

    def test_e024_gates_e021_e023_e025(self):
        # Entries missing 'name' should not appear in tuple/duplicate-id/enum checks.
        ex = [
            {"exchangeId": 1, "assetClass": "WRONG_VALUE", "sessions": self._EX[0]["sessions"]},
            {"exchangeId": 1, "assetClass": "WRONG_VALUE", "sessions": self._EX[0]["sessions"]},
        ]
        findings = check_exchanges([], ex)
        rule_ids = [f.rule_id for f in findings]
        # Only E024 (twice — missing name on both entries) should appear.
        assert all(r == "E024" for r in rule_ids), rule_ids
        assert "E021" not in rule_ids
        assert "E023" not in rule_ids
        assert "E025" not in rule_ids
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `pytest tests/test_exchange_lint.py::TestSuppressionMatrix -v`
Expected: 3 PASS (no implementation change needed; existing wiring already enforces this).

- [ ] **Step 3: Run full module test suite**

Run: `pytest tests/test_exchange_lint.py tests/test_schedule_format.py -v`
Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/test_exchange_lint.py
git commit -m "test(linter): cross-rule suppression matrix coverage"
```

---

## Task 13: E022 — invalid `holidayOverrides` syntax

**Files:**

- Modify: `lib/exchange_lint.py`
- Modify: `tests/test_exchange_lint.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/test_exchange_lint.py`:

```python
class TestE022:
    def test_no_overrides_no_finding(self):
        feeds = [{"feedId": 100, "symbol": "S", "marketSchedules": [
            {"session": "REGULAR", "marketSchedule": "UTC;O,O,O,O,O,O,O;"},
        ]}]
        findings = [f for f in check_exchanges(feeds, []) if f.rule_id == "E022"]
        assert findings == []

    def test_valid_tokens_no_finding(self):
        feeds = [{"feedId": 100, "symbol": "S", "marketSchedules": [{
            "session": "REGULAR",
            "scheduleOverrides": {"holidayOverrides": ["0101/C", "0619/O", "0703/0930-1300"]},
        }]}]
        findings = [f for f in check_exchanges(feeds, []) if f.rule_id == "E022"]
        assert findings == []

    def test_one_bad_token(self):
        feeds = [{"feedId": 100, "symbol": "S", "marketSchedules": [{
            "session": "REGULAR",
            "scheduleOverrides": {"holidayOverrides": ["0315/X"]},
        }]}]
        findings = [f for f in check_exchanges(feeds, []) if f.rule_id == "E022"]
        assert len(findings) == 1
        assert "'0315/X'" in findings[0].message
        assert findings[0].feed_id == 100

    def test_three_bad_tokens_emit_three_findings(self):
        feeds = [{"feedId": 100, "symbol": "S", "marketSchedules": [{
            "session": "REGULAR",
            "scheduleOverrides": {"holidayOverrides": ["0315/X", "315/C", "1340/C"]},
        }]}]
        findings = [f for f in check_exchanges(feeds, []) if f.rule_id == "E022"]
        assert len(findings) == 3

    def test_holiday_overrides_not_a_list(self):
        feeds = [{"feedId": 100, "symbol": "S", "marketSchedules": [{
            "session": "REGULAR",
            "scheduleOverrides": {"holidayOverrides": "0315/C"},  # string, not list
        }]}]
        findings = [f for f in check_exchanges(feeds, []) if f.rule_id == "E022"]
        assert len(findings) == 1
        assert "must be a list of strings" in findings[0].message

    def test_empty_or_null_overrides_no_finding(self):
        for overrides in ([], None):
            feeds = [{"feedId": 100, "symbol": "S", "marketSchedules": [{
                "session": "REGULAR",
                "scheduleOverrides": {"holidayOverrides": overrides},
            }]}]
            findings = [f for f in check_exchanges(feeds, []) if f.rule_id == "E022"]
            assert findings == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_exchange_lint.py::TestE022 -v`
Expected: 4 of 6 FAIL (no E022 emitted yet).

- [ ] **Step 3: Implement E022**

In `lib/exchange_lint.py`, add above `check_exchanges`:

```python
def _check_e022(feeds: list[dict]) -> list[LintFinding]:
    """E022: invalid holidayOverrides syntax."""
    findings: list[LintFinding] = []
    for feed in feeds:
        if not isinstance(feed, dict):
            continue
        fid = feed.get("feedId")
        sym = feed.get("symbol")
        for ms in feed.get("marketSchedules") or []:
            if not isinstance(ms, dict):
                continue
            overrides_obj = ms.get("scheduleOverrides")
            if not isinstance(overrides_obj, dict):
                continue
            tokens = overrides_obj.get("holidayOverrides")
            if tokens is None or tokens == []:
                continue
            if not isinstance(tokens, list):
                findings.append(LintFinding(
                    rule_id="E022", severity="ERROR",
                    message=f"holidayOverrides must be a list of strings, got {type(tokens).__name__}",
                    feed_id=fid, symbol=sym,
                ))
                continue
            for token in tokens:
                if not isinstance(token, str):
                    findings.append(LintFinding(
                        rule_id="E022", severity="ERROR",
                        message=f"holidayOverrides entry {token!r} has invalid syntax: not a string",
                        feed_id=fid, symbol=sym,
                    ))
                    continue
                reason = validate_holiday_token(token)
                if reason is not None:
                    findings.append(LintFinding(
                        rule_id="E022", severity="ERROR",
                        message=f"holidayOverrides entry {token!r} has invalid syntax: {reason}",
                        feed_id=fid, symbol=sym,
                    ))
    return findings
```

In `check_exchanges`, AFTER the W010 call, add:

```python
    findings.extend(_check_e022(feeds))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_exchange_lint.py::TestE022 -v`
Expected: 6 PASS.

Run all module tests: `pytest tests/test_exchange_lint.py tests/test_schedule_format.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/exchange_lint.py tests/test_exchange_lint.py
git commit -m "feat(linter): E022 — invalid holidayOverrides syntax"
```

---

## Task 14: Orchestrator wiring + integration test

**Files:**

- Modify: `lib/config_lint.py:1067-1085`
- Modify: `tests/test_config_lint.py`

- [ ] **Step 1: Write the failing integration test**

Append to `tests/test_config_lint.py` (place at the end of the file, before any conflict markers):

```python
class TestExchangeOrchestratorIntegration:
    """Verifies that lint_config wires through to check_exchanges."""

    def test_e019_appears_in_lint_config_output(self):
        from lib.config_lint import lint_config
        config = {
            "feeds": [
                {
                    "feedId": 1,
                    "symbol": "X",
                    "state": "STABLE",
                    "kind": "PRICE",
                    "metadata": {"asset_type": "equity"},
                    "exchangeId": 99999,  # dangling
                    "allowedPublisherIds": [1],
                    "minPublishers": 1,
                    "marketSchedules": [
                        {"session": "REGULAR", "marketSchedule": "UTC;O,O,O,O,O,O,O;"},
                    ],
                }
            ],
            "publishers": [{"publisherId": 1, "name": "p1", "keyType": "PRODUCTION"}],
            "exchanges": [
                {"exchangeId": 1, "name": "X",
                 "sessions": [{"session": "REGULAR", "marketSchedule": "UTC;O,O,O,O,O,O,O;"}]},
            ],
        }
        findings = lint_config(config)
        assert any(f.rule_id == "E019" for f in findings)

    def test_no_exchanges_key_does_not_break(self):
        from lib.config_lint import lint_config
        config = {
            "feeds": [],
            "publishers": [],
            # no exchanges key
        }
        findings = lint_config(config)
        # Just confirm no crash; no E0xx exchange rule should fire on empty
        assert all(not f.rule_id.startswith("E019")
                   and not f.rule_id.startswith("E020")
                   and not f.rule_id.startswith("E021")
                   for f in findings)
```

- [ ] **Step 2: Run integration tests to verify they fail**

Run: `pytest tests/test_config_lint.py::TestExchangeOrchestratorIntegration -v`
Expected: `test_e019_appears_in_lint_config_output` FAILS (no E019 in `lint_config` output yet).

- [ ] **Step 3: Wire orchestrator**

Edit `lib/config_lint.py` to add the import and the call.

Add to the imports near the top (around line 13, with the other `from lib.symbol_utils` import):

```python
from lib.exchange_lint import check_exchanges
```

In `lint_config` (around line 1083, after `check_identifier_continuity`):

```python
    findings.extend(check_identifier_continuity(feeds))
    findings.extend(check_exchanges(feeds, config.get("exchanges", []) or []))

    return findings
```

- [ ] **Step 4: Run integration tests + full existing suite to verify nothing broke**

Run: `pytest tests/test_config_lint.py -v`
Expected: all PASS, including the new 2 integration tests.

Run: `pytest tests/test_exchange_lint.py tests/test_schedule_format.py tests/test_config_lint.py -v`
Expected: full suite PASS.

- [ ] **Step 5: Commit**

```bash
git add lib/config_lint.py tests/test_config_lint.py
git commit -m "feat(linter): wire check_exchanges into lint_config orchestrator"
```

---

## Task 15: Documentation updates

**Files:**

- Modify: `docs/config_linter.md`
- Modify: `Config_Linter_Guide.md`

- [ ] **Step 1: Read the existing rule tables to understand the column structure**

Run: `grep -nE "^\| [EW]0" docs/config_linter.md | head`

This reveals the existing format (typically `| ID | Rule | Scope |` for both Errors and Warnings sections).

- [ ] **Step 2: Add new rule rows to `docs/config_linter.md`**

Find the existing Errors table (usually under a `### Errors` heading) and append these rows in numerical order:

```markdown
| E019 | feed references `exchangeId` not in `exchanges[]` (dangling reference) | non-INACTIVE |
| E020 | session has no schedule source (no inline `marketSchedule`, no resolvable inheritance) | non-INACTIVE |
| E021 | duplicate exchange tuple `(name, assetClass, assetSubclass, assetSector)` across distinct exchangeIds | exchanges array |
| E022 | invalid syntax in `scheduleOverrides.holidayOverrides[]` token | non-INACTIVE |
| E023 | duplicate `exchangeId` value in `exchanges[]` | exchanges array |
| E024 | exchange entry missing required field (`exchangeId`/`name`/non-empty `sessions`) | exchanges array |
| E025 | unknown enum value for `assetClass`/`assetSubclass`/`assetSector` | exchanges array |
```

Find the existing Warnings table and append:

```markdown
| W010 | feed session has both inline `marketSchedule` and `exchangeId` (inline shadows exchange) | non-INACTIVE |
| W011 | feed has `exchangeId` but every session has an inline `marketSchedule` (`exchangeId` unused) | non-INACTIVE |
```

- [ ] **Step 3: Add the same rows to `Config_Linter_Guide.md`**

Locate the Errors and Warnings tables in `Config_Linter_Guide.md` and append the same rows (matching its column structure if different — typically same).

- [ ] **Step 4: Add a narrative paragraph in `Config_Linter_Guide.md` introducing the exchange-aware block**

Below the rule tables, add a new section:

```markdown
### Exchange-aware rules (E019–E025, W010–W011)

Rules covering the new `exchanges[]` top-level array and per-feed `exchangeId` /
per-session `scheduleOverrides` fields described in
[`Exchange_Configuration_Guide.md`](./Exchange_Configuration_Guide.md). They
validate referential integrity (E019), schedule-source completeness (E020),
exchange-array uniqueness (E021/E023), required-field schema (E024), enum
values (E025), holiday-override token syntax (E022), and migration-mistake
patterns (W010/W011).
```

- [ ] **Step 5: Run pre-commit on the docs**

Run: `pre-commit run --files docs/config_linter.md Config_Linter_Guide.md`
Expected: PASS (prettier may reformat table column widths; let it).

- [ ] **Step 6: Commit**

```bash
git add docs/config_linter.md Config_Linter_Guide.md
git commit -m "docs(linter): document exchange-aware rules E019-E025 and W010-W011"
```

---

## Final verification

- [ ] **Run the full test suite**

```bash
pytest tests/ -v
```

Expected: every test passes, including the 159+ pre-existing tests in `test_config_lint.py`.

- [ ] **Run the linter against `staging/after.json` to confirm no false positives on real pilot data**

```bash
python3 config_linter.py --config staging/after.json --no-baseline 2>&1 | grep -E "E019|E020|E021|E022|E023|E024|E025|W010|W011" || echo "No exchange-rule findings (expected on the pilot snapshot)"
```

Expected: no output (or only "No exchange-rule findings…"). Per the spec's verified analysis, the pilot snapshot has 6 well-formed feeds referencing 2 well-formed exchanges, no scheduleOverrides, no duplicates. If anything fires, debug before merging.

- [ ] **Run pre-commit on every modified file**

```bash
pre-commit run --files \
  lib/schedule_format.py lib/exchange_lint.py lib/config_lint.py \
  tests/test_schedule_format.py tests/test_exchange_lint.py tests/test_config_lint.py \
  docs/config_linter.md Config_Linter_Guide.md
```

Expected: all hooks PASS.

- [ ] **Push the branch and open a PR**

```bash
git push -u origin feat/exchange-aware-linter-rules
gh pr create --base main --title "feat(linter): exchange-aware lint rules (E019–E025, W010–W011)" --body "$(cat <<'EOF'
## Summary
- Adds 9 lint rules covering the new `exchanges[]` feature in `after.json`.
- Splits exchange logic into `lib/exchange_lint.py` (rules) and `lib/schedule_format.py` (token validator) to keep `lib/config_lint.py` within the 800-line guideline.
- Documents the rules in `docs/config_linter.md` and `Config_Linter_Guide.md`.

## Spec
See `docs/superpowers/specs/2026-05-03-exchange-aware-linter-rules-design.md`.

## Test plan
- [x] Unit tests for `validate_holiday_token` (table-driven)
- [x] Per-rule unit tests for E019, E020, E021, E022, E023, E024, E025, W010, W011
- [x] Cross-rule suppression-matrix tests
- [x] Orchestrator integration test in `tests/test_config_lint.py`
- [x] Linted `staging/after.json` — no false positives on the pilot data
EOF
)"
```

Expected: PR opens with mergeable status (CI may take a minute to settle).
