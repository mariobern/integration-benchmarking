# Config Linter (Super-Linter) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a config linter for `after.json` that catches duplicate IDs, invalid publisher references, unsafe minPublishers values, and schedule inconsistencies — runnable as CLI and Docker image for governance CI.

**Architecture:** Thin CLI wrapper (`config_linter.py`) delegates to `lib/config_lint.py` for all lint rules. Shared futures/equity helpers extracted to `lib/symbol_utils.py`. Zero external dependencies at runtime.

**Tech Stack:** Python 3.11+ stdlib only (json, re, dataclasses, argparse, collections). pytest for tests. Docker for CI image.

**Spec:** `docs/superpowers/specs/2026-03-24-config-linter-design.md`

---

## File Structure

| File                              | Responsibility                                                                                                                                           |
| --------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `lib/symbol_utils.py`             | Shared helpers: `is_futures_symbol()`, `is_us_equity()` — extracted from `sql_filters.py` to avoid ClickHouse deps                                       |
| `lib/config_lint.py`              | All lint rules: `LintFinding` dataclass, `lint_config()` orchestrator, `check_duplicates()`, `check_schema()`, `check_publishers()`, `check_schedules()` |
| `config_linter.py`                | Thin CLI: argparse, JSON loading, text/JSON output formatting, exit codes                                                                                |
| `tests/test_symbol_utils.py`      | Unit tests for symbol_utils                                                                                                                              |
| `tests/test_config_lint.py`       | Unit tests for all 15 lint rules + edge cases                                                                                                            |
| `tests/test_config_linter_cli.py` | CLI integration tests (subprocess invocation)                                                                                                            |
| `Dockerfile.linter`               | Minimal Docker image for governance CI                                                                                                                   |

---

### Task 1: Extract `lib/symbol_utils.py` from `lib/sql_filters.py`

**Files:**

- Create: `lib/symbol_utils.py`
- Modify: `lib/sql_filters.py` (import from symbol_utils instead of defining locally)
- Create: `tests/test_symbol_utils.py`

- [ ] **Step 1: Write failing tests for symbol_utils**

Create `tests/test_symbol_utils.py`:

```python
from lib.symbol_utils import is_futures_symbol, is_us_equity


class TestIsFuturesSymbol:
    def test_commodity_future(self):
        assert is_futures_symbol("Commodities.CCH6/USD") is True

    def test_equity_future(self):
        assert is_futures_symbol("Equity.US.EMH6/USD") is True

    def test_all_month_codes(self):
        for code in "FGHJKMNQUVXZ":
            assert is_futures_symbol(f"Commodities.CC{code}6/USD") is True

    def test_regular_equity(self):
        assert is_futures_symbol("Equity.US.AAPL/USD") is False

    def test_crypto(self):
        assert is_futures_symbol("Crypto.BTC/USD") is False

    def test_fx(self):
        assert is_futures_symbol("FX.EUR/USD") is False

    def test_empty_string(self):
        assert is_futures_symbol("") is False

    def test_short_ticker(self):
        assert is_futures_symbol("X.A/USD") is False


class TestIsUsEquity:
    def test_us_equity(self):
        assert is_us_equity({"symbol": "Equity.US.AAPL/USD"}) is True

    def test_non_us_equity(self):
        assert is_us_equity({"symbol": "Equity.GB.VOD/GBP"}) is False

    def test_crypto(self):
        assert is_us_equity({"symbol": "Crypto.BTC/USD"}) is False

    def test_missing_symbol(self):
        assert is_us_equity({}) is False

    def test_us_equity_future(self):
        assert is_us_equity({"symbol": "Equity.US.EMH6/USD"}) is True
```

- [ ] **Step 2: Run tests — expect FAIL (module not found)**

Run: `python3 -m pytest tests/test_symbol_utils.py -v`
Expected: `ModuleNotFoundError` or `ImportError`

- [ ] **Step 3: Create `lib/symbol_utils.py`**

```python
"""Shared symbol utilities for Pyth Lazer feed analysis.

Extracted from sql_filters.py to allow use without ClickHouse dependencies.
"""

from __future__ import annotations

# Futures contract month codes: F=Jan, G=Feb, H=Mar, J=Apr, K=May, M=Jun,
# N=Jul, Q=Aug, U=Sep, V=Oct, X=Nov, Z=Dec
FUTURES_MONTH_CODES = "FGHJKMNQUVXZ"


def is_futures_symbol(symbol: str) -> bool:
    """Detect if a symbol represents a futures contract.

    Pattern: [ROOT][MONTH_CODE][YEAR_DIGIT] where month code is one of
    FGHJKMNQUVXZ and year digit is 0-9.
    """
    if not symbol:
        return False

    base = symbol.split("/")[0] if "/" in symbol else symbol
    parts = base.split(".")
    if len(parts) < 2:
        return False

    ticker = parts[-1]
    if len(ticker) < 2:
        return False

    month_code = ticker[-2].upper()
    year_digit = ticker[-1]

    return month_code in FUTURES_MONTH_CODES and year_digit.isdigit()


def is_us_equity(feed: dict) -> bool:
    """Check if a feed is a US equity by symbol prefix."""
    return feed.get("symbol", "").startswith("Equity.US.")
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `python3 -m pytest tests/test_symbol_utils.py -v`
Expected: All tests PASS

- [ ] **Step 5: Update `lib/sql_filters.py` to import from symbol_utils**

Replace in `lib/sql_filters.py`:

- Remove the `FUTURES_MONTH_CODES` constant definition (line 20)
- Remove the `is_futures_symbol` function (lines 45-63)
- Add **module-level** import: `from lib.symbol_utils import FUTURES_MONTH_CODES, is_futures_symbol`

**IMPORTANT:** The import MUST be at module level (not inside a function) so that
`FUTURES_MONTH_CODES` and `is_futures_symbol` are re-exported as attributes of
`lib.sql_filters`. Existing code (`tests/lib/test_sql_filters.py`) imports these
names from `lib.sql_filters` — a module-level re-export preserves backward compatibility.

- [ ] **Step 6: Verify existing tests still pass**

Run: `python3 -m pytest tests/ -v --tb=short`
Expected: All existing tests PASS (no regressions)

- [ ] **Step 7: Run pre-commit and commit**

```bash
pre-commit run --files lib/symbol_utils.py lib/sql_filters.py tests/test_symbol_utils.py
git add lib/symbol_utils.py lib/sql_filters.py tests/test_symbol_utils.py
git commit -m "refactor: extract symbol_utils from sql_filters for shared use"
```

---

### Task 2: `lib/config_lint.py` — Data Model + Orchestrator + Duplicate Checks (E001, E002)

**Files:**

- Create: `lib/config_lint.py`
- Create: `tests/test_config_lint.py`

- [ ] **Step 1: Write failing tests for LintFinding, lint_config, and duplicate checks**

Create `tests/test_config_lint.py`:

```python
from lib.config_lint import LintFinding, lint_config, check_duplicates


def _make_feed(
    feed_id,
    symbol="Crypto.BTC/USD",
    state="STABLE",
    kind="PRICE",
    asset_type="crypto",
    min_publishers=3,
    publisher_ids=None,
    schedules=None,
):
    """Build a minimal feed dict matching after.json structure."""
    feed = {
        "feedId": feed_id,
        "symbol": symbol,
        "state": state,
        "kind": kind,
        "minPublishers": min_publishers,
        "metadata": {"asset_type": asset_type},
        "marketSchedules": schedules
        or [
            {
                "marketSchedule": "America/New_York;O,O,O,O,O,O,O;",
                "session": "REGULAR",
            }
        ],
    }
    if publisher_ids is not None:
        feed["allowedPublisherIds"] = publisher_ids
    return feed


def _make_config(feeds, publishers=None):
    """Build a minimal config dict matching after.json structure."""
    return {
        "feeds": feeds,
        "publishers": publishers
        or [
            {"publisherId": 1, "name": "pub1", "keyType": "PRODUCTION", "isActive": True},
            {"publisherId": 2, "name": "pub2", "keyType": "PRODUCTION", "isActive": True},
            {"publisherId": 3, "name": "pub3", "keyType": "PRODUCTION", "isActive": True},
        ],
    }


class TestLintFinding:
    def test_dataclass_fields(self):
        f = LintFinding(
            rule_id="E001",
            severity="ERROR",
            message="test",
            feed_id=1,
            symbol="Crypto.BTC/USD",
        )
        assert f.rule_id == "E001"
        assert f.severity == "ERROR"
        assert f.feed_id == 1

    def test_optional_fields(self):
        f = LintFinding(
            rule_id="E001", severity="ERROR", message="test", feed_id=None, symbol=None
        )
        assert f.feed_id is None
        assert f.symbol is None


class TestCheckDuplicates:
    def test_e001_duplicate_feed_id(self):
        feeds = [
            _make_feed(1, symbol="Crypto.BTC/USD"),
            _make_feed(1, symbol="Crypto.ETH/USD"),
        ]
        findings = check_duplicates(feeds)
        errors = [f for f in findings if f.rule_id == "E001"]
        assert len(errors) == 1
        assert "1" in errors[0].message

    def test_e001_no_duplicate(self):
        feeds = [
            _make_feed(1, symbol="Crypto.BTC/USD"),
            _make_feed(2, symbol="Crypto.ETH/USD"),
        ]
        findings = check_duplicates(feeds)
        errors = [f for f in findings if f.rule_id == "E001"]
        assert len(errors) == 0

    def test_e002_duplicate_symbol_stable(self):
        feeds = [
            _make_feed(1, symbol="Crypto.BTC/USD", state="STABLE"),
            _make_feed(2, symbol="Crypto.BTC/USD", state="STABLE"),
        ]
        findings = check_duplicates(feeds)
        errors = [f for f in findings if f.rule_id == "E002"]
        assert len(errors) == 1

    def test_e002_duplicate_symbol_coming_soon(self):
        feeds = [
            _make_feed(1, symbol="Crypto.BTC/USD", state="COMING_SOON"),
            _make_feed(2, symbol="Crypto.BTC/USD", state="COMING_SOON"),
        ]
        findings = check_duplicates(feeds)
        errors = [f for f in findings if f.rule_id == "E002"]
        assert len(errors) == 1

    def test_e002_inactive_duplicate_not_flagged(self):
        feeds = [
            _make_feed(1, symbol="Crypto.BTC/USD", state="INACTIVE"),
            _make_feed(2, symbol="Crypto.BTC/USD", state="INACTIVE"),
        ]
        findings = check_duplicates(feeds)
        errors = [f for f in findings if f.rule_id == "E002"]
        assert len(errors) == 0

    def test_e002_stable_and_inactive_not_flagged(self):
        """STABLE + INACTIVE with same symbol is OK (different state groups)."""
        feeds = [
            _make_feed(1, symbol="Crypto.BTC/USD", state="STABLE"),
            _make_feed(2, symbol="Crypto.BTC/USD", state="INACTIVE"),
        ]
        findings = check_duplicates(feeds)
        errors = [f for f in findings if f.rule_id == "E002"]
        assert len(errors) == 0

    def test_e002_stable_and_coming_soon_flagged(self):
        """STABLE + COMING_SOON with same symbol IS a duplicate (both active pipeline)."""
        feeds = [
            _make_feed(1, symbol="Crypto.BTC/USD", state="STABLE"),
            _make_feed(2, symbol="Crypto.BTC/USD", state="COMING_SOON"),
        ]
        findings = check_duplicates(feeds)
        errors = [f for f in findings if f.rule_id == "E002"]
        assert len(errors) == 1

    def test_empty_feeds(self):
        findings = check_duplicates([])
        assert findings == []


class TestLintConfigOrchestrator:
    def test_clean_config(self):
        config = _make_config(
            [
                _make_feed(1, symbol="Crypto.BTC/USD", publisher_ids=[1, 2, 3]),
                _make_feed(2, symbol="Crypto.ETH/USD", publisher_ids=[1, 2, 3]),
            ]
        )
        findings = lint_config(config)
        errors = [f for f in findings if f.severity == "ERROR"]
        assert len(errors) == 0

    def test_empty_feeds(self):
        config = _make_config([])
        findings = lint_config(config)
        assert findings == []
```

- [ ] **Step 2: Run tests — expect FAIL**

Run: `python3 -m pytest tests/test_config_lint.py -v`
Expected: `ImportError`

- [ ] **Step 3: Create `lib/config_lint.py` with data model, orchestrator, and check_duplicates**

```python
"""Config linter rules for after.json validation.

Validates feed definitions, publisher references, schedule consistency,
and business rules. Pure stdlib — no external dependencies.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Optional


@dataclass
class LintFinding:
    """A single lint finding."""

    rule_id: str
    severity: str  # "ERROR" or "WARNING"
    message: str
    feed_id: Optional[int]
    symbol: Optional[str]


def check_duplicates(feeds: list[dict]) -> list[LintFinding]:
    """E001: duplicate feedId, E002: duplicate symbol (STABLE/COMING_SOON)."""
    findings: list[LintFinding] = []

    # E001: duplicate feedId (all feeds)
    id_counts: dict[int, list[int]] = {}
    for idx, feed in enumerate(feeds):
        fid = feed.get("feedId")
        if fid is not None:
            id_counts.setdefault(fid, []).append(idx)

    for fid, indices in id_counts.items():
        if len(indices) > 1:
            locs = ", ".join(f"feeds[{i}]" for i in indices)
            findings.append(
                LintFinding(
                    rule_id="E001",
                    severity="ERROR",
                    message=f"feedId {fid} is duplicated ({locs})",
                    feed_id=fid,
                    symbol=None,
                )
            )

    # E002: duplicate symbol within STABLE/COMING_SOON
    active_symbols: dict[str, list[dict]] = {}
    for feed in feeds:
        state = feed.get("state", "")
        if state in ("STABLE", "COMING_SOON"):
            sym = feed.get("symbol", "")
            active_symbols.setdefault(sym, []).append(feed)

    for sym, dupes in active_symbols.items():
        if len(dupes) > 1:
            ids = [str(f.get("feedId", "?")) for f in dupes]
            findings.append(
                LintFinding(
                    rule_id="E002",
                    severity="ERROR",
                    message=f"symbol '{sym}' duplicated in STABLE/COMING_SOON feeds (feedIds: {', '.join(ids)})",
                    feed_id=dupes[0].get("feedId"),
                    symbol=sym,
                )
            )

    return findings


def check_schema(feeds: list[dict]) -> list[LintFinding]:
    """E007: missing required fields."""
    # Placeholder — implemented in Task 3
    return []


def check_publishers(feeds: list[dict], publishers: list[dict]) -> list[LintFinding]:
    """Publisher validation rules."""
    # Placeholder — implemented in Task 4
    return []


def check_schedules(feeds: list[dict]) -> list[LintFinding]:
    """Schedule validation rules."""
    # Placeholder — implemented in Task 5
    return []


def lint_config(config: dict) -> list[LintFinding]:
    """Orchestrator. Takes the full parsed after.json root object."""
    feeds = config.get("feeds", [])
    publishers = config.get("publishers", [])

    findings: list[LintFinding] = []
    findings.extend(check_duplicates(feeds))
    findings.extend(check_schema(feeds))
    findings.extend(check_publishers(feeds, publishers))
    findings.extend(check_schedules(feeds))

    return findings
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `python3 -m pytest tests/test_config_lint.py -v`
Expected: All tests PASS

- [ ] **Step 5: Run pre-commit and commit**

```bash
pre-commit run --files lib/config_lint.py tests/test_config_lint.py
git add lib/config_lint.py tests/test_config_lint.py
git commit -m "feat: add config_lint data model, orchestrator, and duplicate checks (E001, E002)"
```

---

### Task 3: Schema Check (E007)

**Files:**

- Modify: `lib/config_lint.py`
- Modify: `tests/test_config_lint.py`

- [ ] **Step 1: Write failing tests for E007**

Add to `tests/test_config_lint.py`:

```python
from lib.config_lint import check_schema


class TestCheckSchema:
    def test_e007_missing_kind(self):
        feed = _make_feed(1)
        del feed["kind"]
        findings = check_schema([feed])
        assert len(findings) == 1
        assert findings[0].rule_id == "E007"
        assert "kind" in findings[0].message

    def test_e007_missing_metadata_asset_type(self):
        feed = _make_feed(1)
        del feed["metadata"]["asset_type"]
        findings = check_schema([feed])
        assert len(findings) == 1
        assert findings[0].rule_id == "E007"

    def test_e007_missing_metadata_entirely(self):
        feed = _make_feed(1)
        del feed["metadata"]
        findings = check_schema([feed])
        assert len(findings) == 1
        assert findings[0].rule_id == "E007"

    def test_e007_all_fields_present(self):
        feed = _make_feed(1)
        findings = check_schema([feed])
        assert len(findings) == 0

    def test_e007_multiple_missing(self):
        feed = {"feedId": 1}
        findings = check_schema([feed])
        assert len(findings) == 1
        assert "symbol" in findings[0].message or "state" in findings[0].message
```

- [ ] **Step 2: Run tests — expect FAIL (check_schema returns empty)**

Run: `python3 -m pytest tests/test_config_lint.py::TestCheckSchema -v`
Expected: FAIL

- [ ] **Step 3: Implement check_schema**

Replace the `check_schema` placeholder in `lib/config_lint.py`:

```python
# Required top-level fields on every feed
_REQUIRED_FIELDS = ("feedId", "symbol", "state", "kind")


def check_schema(feeds: list[dict]) -> list[LintFinding]:
    """E007: missing required fields."""
    findings: list[LintFinding] = []

    for feed in feeds:
        fid = feed.get("feedId")
        sym = feed.get("symbol")
        missing = [f for f in _REQUIRED_FIELDS if f not in feed]

        # Check metadata.asset_type separately
        metadata = feed.get("metadata")
        if metadata is None or "asset_type" not in metadata:
            missing.append("metadata.asset_type")

        if missing:
            findings.append(
                LintFinding(
                    rule_id="E007",
                    severity="ERROR",
                    message=f"missing required fields: {', '.join(missing)}",
                    feed_id=fid,
                    symbol=sym,
                )
            )

    return findings
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `python3 -m pytest tests/test_config_lint.py::TestCheckSchema -v`
Expected: All PASS

- [ ] **Step 5: Run pre-commit and commit**

```bash
pre-commit run --files lib/config_lint.py tests/test_config_lint.py
git add lib/config_lint.py tests/test_config_lint.py
git commit -m "feat: add schema validation rule E007"
```

---

### Task 4: Publisher Checks (E003, E004, E005, E008, W004, W005, W006, W007)

**Files:**

- Modify: `lib/config_lint.py`
- Modify: `tests/test_config_lint.py`

This is the largest task — 8 rules. It handles top-level and session-level publisher validation.

- [ ] **Step 1: Write failing tests for all publisher rules**

Add to `tests/test_config_lint.py`:

```python
from lib.config_lint import check_publishers


def _make_publisher(pub_id, key_type="PRODUCTION"):
    return {"publisherId": pub_id, "name": f"pub{pub_id}", "keyType": key_type, "isActive": True}


class TestCheckPublishers:
    def test_e003_invalid_publisher_ref_toplevel(self):
        feeds = [_make_feed(1, publisher_ids=[1, 2, 999])]
        publishers = [_make_publisher(1), _make_publisher(2)]
        findings = check_publishers(feeds, publishers)
        errors = [f for f in findings if f.rule_id == "E003"]
        assert len(errors) == 1
        assert "999" in errors[0].message

    def test_e003_invalid_publisher_ref_session_level(self):
        feeds = [
            _make_feed(
                1,
                symbol="Equity.US.AAPL/USD",
                asset_type="equity",
                publisher_ids=[1, 2],
                schedules=[
                    {"marketSchedule": "America/New_York;O;", "session": "REGULAR"},
                    {
                        "marketSchedule": "America/New_York;0400-0930;",
                        "session": "PRE_MARKET",
                        "allowedPublisherIds": [1, 888],
                        "minPublishers": 1,
                    },
                ],
            )
        ]
        publishers = [_make_publisher(1), _make_publisher(2)]
        findings = check_publishers(feeds, publishers)
        errors = [f for f in findings if f.rule_id == "E003"]
        assert len(errors) == 1
        assert "888" in errors[0].message

    def test_e003_valid_refs(self):
        feeds = [_make_feed(1, publisher_ids=[1, 2])]
        publishers = [_make_publisher(1), _make_publisher(2), _make_publisher(3)]
        findings = check_publishers(feeds, publishers)
        errors = [f for f in findings if f.rule_id == "E003"]
        assert len(errors) == 0

    def test_e004_min_publishers_equals_count(self):
        feeds = [_make_feed(1, min_publishers=3, publisher_ids=[1, 2, 3])]
        publishers = [_make_publisher(1), _make_publisher(2), _make_publisher(3)]
        findings = check_publishers(feeds, publishers)
        errors = [f for f in findings if f.rule_id == "E004"]
        assert len(errors) == 1

    def test_e004_min_publishers_exceeds_count(self):
        feeds = [_make_feed(1, min_publishers=5, publisher_ids=[1, 2, 3])]
        publishers = [_make_publisher(1), _make_publisher(2), _make_publisher(3)]
        findings = check_publishers(feeds, publishers)
        errors = [f for f in findings if f.rule_id == "E004"]
        assert len(errors) == 1

    def test_e004_exempt_asset_type(self):
        feeds = [
            _make_feed(
                1,
                asset_type="funding-rate",
                min_publishers=1,
                publisher_ids=[1],
            )
        ]
        publishers = [_make_publisher(1)]
        findings = check_publishers(feeds, publishers)
        errors = [f for f in findings if f.rule_id == "E004"]
        assert len(errors) == 0

    def test_e004_session_level(self):
        feeds = [
            _make_feed(
                1,
                symbol="Equity.US.AAPL/USD",
                asset_type="equity",
                min_publishers=3,
                publisher_ids=[1, 2, 3, 4, 5],
                schedules=[
                    {"marketSchedule": "America/New_York;O;", "session": "REGULAR"},
                    {
                        "marketSchedule": "America/New_York;0400-0930;",
                        "session": "PRE_MARKET",
                        "allowedPublisherIds": [1, 2],
                        "minPublishers": 2,
                    },
                ],
            )
        ]
        publishers = [_make_publisher(i) for i in range(1, 6)]
        findings = check_publishers(feeds, publishers)
        errors = [f for f in findings if f.rule_id == "E004"]
        assert len(errors) == 1
        assert "PRE_MARKET" in errors[0].message

    def test_e004_min_publishers_zero_not_flagged(self):
        """minPublishers=0 with publishers should not trigger E004."""
        feeds = [_make_feed(1, min_publishers=0, publisher_ids=[1, 2, 3, 4, 5])]
        publishers = [_make_publisher(i) for i in range(1, 6)]
        findings = check_publishers(feeds, publishers)
        errors = [f for f in findings if f.rule_id == "E004"]
        assert len(errors) == 0

    def test_e004_coming_soon_not_checked(self):
        feeds = [
            _make_feed(1, state="COMING_SOON", min_publishers=5, publisher_ids=[1])
        ]
        publishers = [_make_publisher(1)]
        findings = check_publishers(feeds, publishers)
        errors = [f for f in findings if f.rule_id == "E004"]
        assert len(errors) == 0

    def test_e005_stable_no_publishers(self):
        feeds = [_make_feed(1, state="STABLE", publisher_ids=[])]
        publishers = [_make_publisher(1)]
        findings = check_publishers(feeds, publishers)
        errors = [f for f in findings if f.rule_id == "E005"]
        assert len(errors) == 1

    def test_e005_stable_missing_field(self):
        feeds = [_make_feed(1, state="STABLE")]  # no publisher_ids kwarg -> field absent
        publishers = [_make_publisher(1)]
        findings = check_publishers(feeds, publishers)
        errors = [f for f in findings if f.rule_id == "E005"]
        assert len(errors) == 1

    def test_e008_session_publisher_not_in_toplevel(self):
        feeds = [
            _make_feed(
                1,
                symbol="Equity.US.AAPL/USD",
                asset_type="equity",
                publisher_ids=[1, 2, 3],
                schedules=[
                    {"marketSchedule": "America/New_York;O;", "session": "REGULAR"},
                    {
                        "marketSchedule": "America/New_York;0400-0930;",
                        "session": "PRE_MARKET",
                        "allowedPublisherIds": [1, 2, 4],
                        "minPublishers": 1,
                    },
                ],
            )
        ]
        publishers = [_make_publisher(i) for i in range(1, 5)]
        findings = check_publishers(feeds, publishers)
        errors = [f for f in findings if f.rule_id == "E008"]
        assert len(errors) == 1
        assert "4" in errors[0].message

    def test_w004_coming_soon_no_publishers(self):
        feeds = [_make_feed(1, state="COMING_SOON")]  # no publisher_ids
        publishers = [_make_publisher(1)]
        findings = check_publishers(feeds, publishers)
        warnings = [f for f in findings if f.rule_id == "W004"]
        assert len(warnings) == 1

    def test_w005_one_headroom(self):
        feeds = [_make_feed(1, min_publishers=4, publisher_ids=[1, 2, 3, 4, 5])]
        publishers = [_make_publisher(i) for i in range(1, 6)]
        findings = check_publishers(feeds, publishers)
        warnings = [f for f in findings if f.rule_id == "W005"]
        assert len(warnings) == 1

    def test_w005_session_level_one_headroom(self):
        feeds = [
            _make_feed(
                1,
                symbol="Equity.US.AAPL/USD",
                asset_type="equity",
                min_publishers=3,
                publisher_ids=[1, 2, 3, 4, 5, 6],
                schedules=[
                    {"marketSchedule": "America/New_York;O;", "session": "REGULAR"},
                    {
                        "marketSchedule": "America/New_York;0400-0930;",
                        "session": "PRE_MARKET",
                        "allowedPublisherIds": [1, 2, 3],
                        "minPublishers": 2,
                    },
                ],
            )
        ]
        publishers = [_make_publisher(i) for i in range(1, 7)]
        findings = check_publishers(feeds, publishers)
        warnings = [f for f in findings if f.rule_id == "W005"]
        assert len(warnings) == 1
        assert "PRE_MARKET" in warnings[0].message

    def test_w005_sufficient_headroom(self):
        feeds = [_make_feed(1, min_publishers=3, publisher_ids=[1, 2, 3, 4, 5])]
        publishers = [_make_publisher(i) for i in range(1, 6)]
        findings = check_publishers(feeds, publishers)
        warnings = [f for f in findings if f.rule_id == "W005"]
        assert len(warnings) == 0

    def test_w006_duplicate_publisher_in_feed(self):
        feeds = [_make_feed(1, publisher_ids=[1, 2, 2, 3])]
        publishers = [_make_publisher(i) for i in range(1, 4)]
        findings = check_publishers(feeds, publishers)
        warnings = [f for f in findings if f.rule_id == "W006"]
        assert len(warnings) == 1
        assert "2" in warnings[0].message

    def test_w007_stable_test_publisher(self):
        feeds = [_make_feed(1, state="STABLE", publisher_ids=[1, 2])]
        publishers = [_make_publisher(1, key_type="TEST"), _make_publisher(2)]
        findings = check_publishers(feeds, publishers)
        warnings = [f for f in findings if f.rule_id == "W007"]
        assert len(warnings) == 1
        assert "1" in warnings[0].message

    def test_w007_coming_soon_test_publisher_not_flagged(self):
        feeds = [_make_feed(1, state="COMING_SOON", publisher_ids=[1])]
        publishers = [_make_publisher(1, key_type="TEST")]
        findings = check_publishers(feeds, publishers)
        warnings = [f for f in findings if f.rule_id == "W007"]
        assert len(warnings) == 0

    def test_missing_allowedPublisherIds_field(self):
        """Feed without allowedPublisherIds field — null-safe handling."""
        feed = _make_feed(1, state="COMING_SOON")
        assert "allowedPublisherIds" not in feed
        findings = check_publishers([feed], [_make_publisher(1)])
        # Should not crash; W004 should fire
        w004 = [f for f in findings if f.rule_id == "W004"]
        assert len(w004) == 1
```

- [ ] **Step 2: Run tests — expect FAIL (check_publishers returns empty)**

Run: `python3 -m pytest tests/test_config_lint.py::TestCheckPublishers -v`
Expected: FAIL

- [ ] **Step 3: Implement check_publishers**

Replace the `check_publishers` placeholder in `lib/config_lint.py`:

```python
# Asset types exempt from E004/W005 (single-source feeds)
_EXEMPT_ASSET_TYPES = frozenset(
    {"funding-rate", "custom", "crypto-redemption-rate", "nav", "crypto-index", "kalshi"}
)

_EXTENDED_SESSIONS = frozenset({"PRE_MARKET", "POST_MARKET", "OVER_NIGHT"})


def check_publishers(feeds: list[dict], publishers: list[dict]) -> list[LintFinding]:
    """Publisher validation: E003, E004, E005, E008, W004, W005, W006, W007."""
    findings: list[LintFinding] = []
    valid_pub_ids = {p["publisherId"] for p in publishers}
    test_pub_ids = {p["publisherId"] for p in publishers if p.get("keyType") == "TEST"}

    for feed in feeds:
        fid = feed.get("feedId")
        sym = feed.get("symbol", "")
        state = feed.get("state", "")
        asset_type = feed.get("metadata", {}).get("asset_type", "")
        is_exempt = asset_type in _EXEMPT_ASSET_TYPES
        pub_ids = feed.get("allowedPublisherIds", [])
        min_pub = feed.get("minPublishers", 0)

        # Skip most rules for INACTIVE
        if state == "INACTIVE":
            continue

        # E003: invalid publisher ref (top-level)
        invalid_top = set(pub_ids) - valid_pub_ids
        if invalid_top:
            findings.append(
                LintFinding(
                    rule_id="E003",
                    severity="ERROR",
                    message=f"references unknown publisherIds: {sorted(invalid_top)}",
                    feed_id=fid,
                    symbol=sym,
                )
            )

        # W006: duplicate publisher in feed (top-level)
        seen = set()
        dupes = set()
        for pid in pub_ids:
            if pid in seen:
                dupes.add(pid)
            seen.add(pid)
        if dupes:
            findings.append(
                LintFinding(
                    rule_id="W006",
                    severity="WARNING",
                    message=f"duplicate publisherIds in feed: {sorted(dupes)}",
                    feed_id=fid,
                    symbol=sym,
                )
            )

        # STABLE-only rules
        if state == "STABLE":
            # E005: no publishers
            if len(pub_ids) == 0:
                findings.append(
                    LintFinding(
                        rule_id="E005",
                        severity="ERROR",
                        message="STABLE feed with no publishers",
                        feed_id=fid,
                        symbol=sym,
                    )
                )

            # E004: minPublishers >= count (top-level, non-exempt)
            if not is_exempt and len(pub_ids) > 0 and min_pub >= len(pub_ids):
                findings.append(
                    LintFinding(
                        rule_id="E004",
                        severity="ERROR",
                        message=(
                            f"minPublishers ({min_pub}) >= publisher count"
                            f" ({len(pub_ids)}), no fault tolerance"
                        ),
                        feed_id=fid,
                        symbol=sym,
                    )
                )

            # W005: only 1 headroom (top-level, non-exempt)
            if (
                not is_exempt
                and len(pub_ids) > 0
                and min_pub == len(pub_ids) - 1
                and min_pub > 0
            ):
                findings.append(
                    LintFinding(
                        rule_id="W005",
                        severity="WARNING",
                        message=(
                            f"minPublishers ({min_pub}) leaves only 1 headroom"
                            f" ({len(pub_ids)} publishers)"
                        ),
                        feed_id=fid,
                        symbol=sym,
                    )
                )

            # W007: STABLE referencing TEST publisher
            test_refs = set(pub_ids) & test_pub_ids
            if test_refs:
                findings.append(
                    LintFinding(
                        rule_id="W007",
                        severity="WARNING",
                        message=f"STABLE feed references TEST publishers: {sorted(test_refs)}",
                        feed_id=fid,
                        symbol=sym,
                    )
                )

        # COMING_SOON-only rules
        if state == "COMING_SOON":
            # W004: no publishers
            if len(pub_ids) == 0:
                findings.append(
                    LintFinding(
                        rule_id="W004",
                        severity="WARNING",
                        message="COMING_SOON feed with no publishers",
                        feed_id=fid,
                        symbol=sym,
                    )
                )

        # Session-level checks (all non-INACTIVE states)
        top_level_set = set(pub_ids)
        for schedule in feed.get("marketSchedules", []):
            session_name = schedule.get("session", "")
            session_pubs = schedule.get("allowedPublisherIds")
            session_min = schedule.get("minPublishers")

            if session_pubs is None:
                continue  # no session-level publishers

            # E003: invalid publisher ref (session-level)
            invalid_session = set(session_pubs) - valid_pub_ids
            if invalid_session:
                findings.append(
                    LintFinding(
                        rule_id="E003",
                        severity="ERROR",
                        message=(
                            f"session {session_name}: references unknown"
                            f" publisherIds: {sorted(invalid_session)}"
                        ),
                        feed_id=fid,
                        symbol=sym,
                    )
                )

            # E008: session publisher not in top-level list
            not_in_top = set(session_pubs) - top_level_set
            if not_in_top:
                findings.append(
                    LintFinding(
                        rule_id="E008",
                        severity="ERROR",
                        message=(
                            f"session {session_name}: publisherIds"
                            f" {sorted(not_in_top)} not in top-level list"
                        ),
                        feed_id=fid,
                        symbol=sym,
                    )
                )

            # E004/W005 at session level (STABLE non-exempt only)
            if state == "STABLE" and not is_exempt and session_min is not None:
                session_count = len(session_pubs)
                if session_count > 0 and session_min >= session_count:
                    findings.append(
                        LintFinding(
                            rule_id="E004",
                            severity="ERROR",
                            message=(
                                f"session {session_name}: minPublishers ({session_min})"
                                f" >= publisher count ({session_count})"
                            ),
                            feed_id=fid,
                            symbol=sym,
                        )
                    )
                elif (
                    session_count > 0
                    and session_min == session_count - 1
                    and session_min > 0
                ):
                    findings.append(
                        LintFinding(
                            rule_id="W005",
                            severity="WARNING",
                            message=(
                                f"session {session_name}: minPublishers ({session_min})"
                                f" leaves only 1 headroom ({session_count} publishers)"
                            ),
                            feed_id=fid,
                            symbol=sym,
                        )
                    )

    return findings
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `python3 -m pytest tests/test_config_lint.py::TestCheckPublishers -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `python3 -m pytest tests/test_config_lint.py -v`
Expected: All PASS

- [ ] **Step 6: Run pre-commit and commit**

```bash
pre-commit run --files lib/config_lint.py tests/test_config_lint.py
git add lib/config_lint.py tests/test_config_lint.py
git commit -m "feat: add publisher validation rules (E003-E005, E008, W004-W007)"
```

---

### Task 5: Schedule Checks (E006, W001, W002, W003)

**Files:**

- Modify: `lib/config_lint.py`
- Modify: `tests/test_config_lint.py`

- [ ] **Step 1: Write failing tests for schedule rules**

Add to `tests/test_config_lint.py`:

```python
from lib.config_lint import check_schedules


def _us_equity_all_sessions():
    """Return the 4-session schedule set for a properly configured US equity."""
    return [
        {"marketSchedule": "America/New_York;0930-1600;", "session": "REGULAR"},
        {"marketSchedule": "America/New_York;0400-0930;", "session": "PRE_MARKET",
         "allowedPublisherIds": [1, 2], "minPublishers": 1},
        {"marketSchedule": "America/New_York;1600-2000;", "session": "POST_MARKET",
         "allowedPublisherIds": [1, 2], "minPublishers": 1},
        {"marketSchedule": "America/New_York;2000-0400;", "session": "OVER_NIGHT",
         "allowedPublisherIds": [1, 2], "minPublishers": 1},
    ]


class TestCheckSchedules:
    def test_e006_non_equity_with_extended_session(self):
        feeds = [
            _make_feed(
                1,
                symbol="FX.EUR/USD",
                asset_type="fx",
                schedules=[
                    {"marketSchedule": "America/New_York;O;", "session": "REGULAR"},
                    {"marketSchedule": "America/New_York;0400-0930;", "session": "PRE_MARKET"},
                ],
            )
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E006"]
        assert len(errors) == 1

    def test_e006_equity_with_extended_ok(self):
        feeds = [
            _make_feed(
                1,
                symbol="Equity.US.AAPL/USD",
                asset_type="equity",
                schedules=_us_equity_all_sessions(),
            )
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E006"]
        assert len(errors) == 0

    def test_w001_equity_missing_extended(self):
        feeds = [
            _make_feed(
                1,
                symbol="Equity.US.AAPL/USD",
                asset_type="equity",
                state="STABLE",
                schedules=[
                    {"marketSchedule": "America/New_York;0930-1600;", "session": "REGULAR"},
                ],
            )
        ]
        findings = check_schedules(feeds)
        warnings = [f for f in findings if f.rule_id == "W001"]
        assert len(warnings) == 1
        # Missing all 3 extended sessions
        assert "PRE_MARKET" in warnings[0].message
        assert "POST_MARKET" in warnings[0].message
        assert "OVER_NIGHT" in warnings[0].message

    def test_w001_non_us_equity_not_flagged(self):
        feeds = [
            _make_feed(
                1,
                symbol="Equity.GB.VOD/GBP",
                asset_type="equity",
                state="STABLE",
                schedules=[
                    {"marketSchedule": "Europe/London;0800-1630;", "session": "REGULAR"},
                ],
            )
        ]
        findings = check_schedules(feeds)
        warnings = [f for f in findings if f.rule_id == "W001"]
        assert len(warnings) == 0

    def test_w002_us_equity_wrong_timezone(self):
        feeds = [
            _make_feed(
                1,
                symbol="Equity.US.AAPL/USD",
                asset_type="equity",
                state="STABLE",
                schedules=[
                    {"marketSchedule": "UTC;0930-1600;", "session": "REGULAR"},
                ],
            )
        ]
        findings = check_schedules(feeds)
        warnings = [f for f in findings if f.rule_id == "W002"]
        assert len(warnings) == 1

    def test_w002_non_us_equity_different_tz_ok(self):
        feeds = [
            _make_feed(
                1,
                symbol="Equity.GB.VOD/GBP",
                asset_type="equity",
                state="STABLE",
                schedules=[
                    {"marketSchedule": "Europe/London;0800-1630;", "session": "REGULAR"},
                ],
            )
        ]
        findings = check_schedules(feeds)
        warnings = [f for f in findings if f.rule_id == "W002"]
        assert len(warnings) == 0

    def test_w003_schedule_deviation(self):
        """One commodity has a different schedule from the majority."""
        majority_schedule = [
            {"marketSchedule": "America/New_York;O,O,O,O,O,O,O;", "session": "REGULAR"}
        ]
        deviant_schedule = [
            {"marketSchedule": "America/New_York;0800-1400,0800-1400,0800-1400,0800-1400,0800-1400,C,C;", "session": "REGULAR"}
        ]
        feeds = [
            _make_feed(i, symbol=f"Commodities.GOLD{i}/USD", asset_type="commodity",
                       state="STABLE", schedules=majority_schedule)
            for i in range(1, 6)
        ] + [
            _make_feed(6, symbol="Commodities.ODD/USD", asset_type="commodity",
                       state="STABLE", schedules=deviant_schedule)
        ]
        findings = check_schedules(feeds)
        warnings = [f for f in findings if f.rule_id == "W003"]
        assert len(warnings) == 1
        assert warnings[0].feed_id == 6

    def test_w003_futures_exempt(self):
        """Futures contracts are exempt from schedule deviation warnings."""
        majority_schedule = [
            {"marketSchedule": "America/New_York;O,O,O,O,O,O,O;", "session": "REGULAR"}
        ]
        deviant_schedule = [
            {"marketSchedule": "America/New_York;0800-1400;", "session": "REGULAR"}
        ]
        feeds = [
            _make_feed(i, symbol=f"Commodities.GOLD{i}/USD", asset_type="commodity",
                       state="STABLE", schedules=majority_schedule)
            for i in range(1, 4)
        ] + [
            _make_feed(4, symbol="Commodities.CCH6/USD", asset_type="commodity",
                       state="STABLE", schedules=deviant_schedule)
        ]
        findings = check_schedules(feeds)
        warnings = [f for f in findings if f.rule_id == "W003"]
        assert len(warnings) == 0

    def test_w003_single_feed_in_class(self):
        feeds = [
            _make_feed(1, symbol="Rates.US10Y/USD", asset_type="rates", state="STABLE")
        ]
        findings = check_schedules(feeds)
        warnings = [f for f in findings if f.rule_id == "W003"]
        assert len(warnings) == 0

    def test_inactive_feeds_skipped(self):
        feeds = [
            _make_feed(
                1,
                symbol="FX.EUR/USD",
                asset_type="fx",
                state="INACTIVE",
                schedules=[
                    {"marketSchedule": "America/New_York;O;", "session": "REGULAR"},
                    {"marketSchedule": "America/New_York;0400-0930;", "session": "PRE_MARKET"},
                ],
            )
        ]
        findings = check_schedules(feeds)
        assert len(findings) == 0
```

- [ ] **Step 2: Run tests — expect FAIL (check_schedules returns empty)**

Run: `python3 -m pytest tests/test_config_lint.py::TestCheckSchedules -v`
Expected: FAIL

- [ ] **Step 3: Implement check_schedules**

Replace the `check_schedules` placeholder in `lib/config_lint.py`. Add this import at the top:

```python
from lib.symbol_utils import is_futures_symbol, is_us_equity
```

Then the implementation:

```python
_US_EQUITY_EXPECTED_SESSIONS = frozenset({"REGULAR", "PRE_MARKET", "POST_MARKET", "OVER_NIGHT"})


def _get_schedule_signature(schedules: list[dict]) -> tuple:
    """Create a hashable signature from a feed's marketSchedules for comparison."""
    return tuple(
        sorted(
            (s.get("session", ""), s.get("marketSchedule", ""))
            for s in schedules
        )
    )


def _extract_timezone(schedule_str: str) -> str:
    """Extract timezone from a marketSchedule string (first segment before ';')."""
    return schedule_str.split(";")[0] if ";" in schedule_str else ""


def check_schedules(feeds: list[dict]) -> list[LintFinding]:
    """E006, W001, W002, W003: schedule validation rules."""
    findings: list[LintFinding] = []

    # Collect schedule signatures per asset_type for W003 majority detection
    asset_type_schedules: dict[str, list[tuple[int, str, tuple, bool]]] = {}

    for feed in feeds:
        fid = feed.get("feedId")
        sym = feed.get("symbol", "")
        state = feed.get("state", "")
        asset_type = feed.get("metadata", {}).get("asset_type", "")
        schedules = feed.get("marketSchedules", [])

        if state == "INACTIVE":
            continue

        sessions = {s.get("session", "") for s in schedules}

        # E006: non-equity with extended sessions
        if asset_type != "equity":
            extended = sessions & _EXTENDED_SESSIONS
            if extended:
                findings.append(
                    LintFinding(
                        rule_id="E006",
                        severity="ERROR",
                        message=f"non-equity ({asset_type}) has extended sessions: {sorted(extended)}",
                        feed_id=fid,
                        symbol=sym,
                    )
                )

        # STABLE-only schedule rules
        if state == "STABLE":
            # W001: US equity missing extended sessions
            if is_us_equity(feed):
                missing = _US_EQUITY_EXPECTED_SESSIONS - sessions
                if missing:
                    findings.append(
                        LintFinding(
                            rule_id="W001",
                            severity="WARNING",
                            message=f"STABLE US equity missing sessions: {sorted(missing)}",
                            feed_id=fid,
                            symbol=sym,
                        )
                    )

                # W002: US equity wrong timezone
                for sched in schedules:
                    tz = _extract_timezone(sched.get("marketSchedule", ""))
                    if tz and tz != "America/New_York":
                        findings.append(
                            LintFinding(
                                rule_id="W002",
                                severity="WARNING",
                                message=f"US equity using timezone '{tz}' instead of 'America/New_York'",
                                feed_id=fid,
                                symbol=sym,
                            )
                        )
                        break  # one finding per feed is enough

            # Collect for W003
            sig = _get_schedule_signature(schedules)
            is_future = is_futures_symbol(sym)
            asset_type_schedules.setdefault(asset_type, []).append(
                (fid, sym, sig, is_future)
            )

    # W003: schedule deviation from asset-class majority
    for asset_type, feed_sigs in asset_type_schedules.items():
        if len(feed_sigs) <= 1:
            continue

        # Find majority schedule (exclude futures from count — they legitimately differ)
        sig_counts: Counter[tuple] = Counter()
        for _, _, sig, is_future in feed_sigs:
            if not is_future:
                sig_counts[sig] += 1

        majority_sig = sig_counts.most_common(1)[0][0]

        for fid, sym, sig, is_future in feed_sigs:
            if sig != majority_sig and not is_future:
                findings.append(
                    LintFinding(
                        rule_id="W003",
                        severity="WARNING",
                        message=f"schedule deviates from {asset_type} majority",
                        feed_id=fid,
                        symbol=sym,
                    )
                )

    return findings
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `python3 -m pytest tests/test_config_lint.py::TestCheckSchedules -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `python3 -m pytest tests/test_config_lint.py -v`
Expected: All PASS

- [ ] **Step 6: Run pre-commit and commit**

```bash
pre-commit run --files lib/config_lint.py tests/test_config_lint.py
git add lib/config_lint.py tests/test_config_lint.py
git commit -m "feat: add schedule validation rules (E006, W001-W003)"
```

---

### Task 6: CLI Wrapper (`config_linter.py`)

**Files:**

- Create: `config_linter.py`
- Create: `tests/test_config_linter_cli.py`

- [ ] **Step 1: Write failing CLI integration tests**

Create `tests/test_config_linter_cli.py`:

```python
import json
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = str(Path(__file__).resolve().parent.parent)


def _write_config(tmp_dir, config):
    path = Path(tmp_dir) / "after.json"
    path.write_text(json.dumps(config))
    return str(path)


def _run_linter(*args):
    result = subprocess.run(
        [sys.executable, "config_linter.py", *args],
        capture_output=True,
        text=True,
        cwd=PROJECT_DIR,
    )
    return result


def _make_clean_config():
    return {
        "feeds": [
            {
                "feedId": 1,
                "symbol": "Crypto.BTC/USD",
                "state": "STABLE",
                "kind": "PRICE",
                "minPublishers": 3,
                "allowedPublisherIds": [1, 2, 3, 4, 5],
                "metadata": {"asset_type": "crypto"},
                "marketSchedules": [
                    {"marketSchedule": "America/New_York;O,O,O,O,O,O,O;", "session": "REGULAR"}
                ],
            }
        ],
        "publishers": [
            {"publisherId": i, "name": f"pub{i}", "keyType": "PRODUCTION", "isActive": True}
            for i in range(1, 6)
        ],
    }


class TestCLIExitCodes:
    def test_clean_config_exits_0(self, tmp_path):
        path = _write_config(tmp_path, _make_clean_config())
        result = _run_linter("--config", path)
        assert result.returncode == 0

    def test_errors_exit_1(self, tmp_path):
        config = _make_clean_config()
        config["feeds"].append(config["feeds"][0].copy())  # duplicate feedId
        path = _write_config(tmp_path, config)
        result = _run_linter("--config", path)
        assert result.returncode == 1

    def test_warnings_only_exit_0(self, tmp_path):
        config = _make_clean_config()
        config["feeds"][0]["minPublishers"] = 4  # W005: only 1 headroom
        path = _write_config(tmp_path, config)
        result = _run_linter("--config", path)
        assert result.returncode == 0
        assert "W005" in result.stdout

    def test_warnings_as_errors_exit_1(self, tmp_path):
        config = _make_clean_config()
        config["feeds"][0]["minPublishers"] = 4  # W005
        path = _write_config(tmp_path, config)
        result = _run_linter("--config", path, "--warnings-as-errors")
        assert result.returncode == 1


class TestCLIOutputFormats:
    def test_text_format(self, tmp_path):
        config = _make_clean_config()
        config["feeds"].append(config["feeds"][0].copy())
        path = _write_config(tmp_path, config)
        result = _run_linter("--config", path, "--format", "text")
        assert "E001" in result.stdout
        assert "Summary:" in result.stdout

    def test_json_format(self, tmp_path):
        config = _make_clean_config()
        config["feeds"].append(config["feeds"][0].copy())
        path = _write_config(tmp_path, config)
        result = _run_linter("--config", path, "--format", "json")
        findings = json.loads(result.stdout)
        assert isinstance(findings, list)
        assert any(f["rule_id"] == "E001" for f in findings)

    def test_json_format_clean(self, tmp_path):
        path = _write_config(tmp_path, _make_clean_config())
        result = _run_linter("--config", path, "--format", "json")
        findings = json.loads(result.stdout)
        errors = [f for f in findings if f["severity"] == "ERROR"]
        assert len(errors) == 0


class TestCLIFileHandling:
    def test_missing_file(self):
        result = _run_linter("--config", "/nonexistent/after.json")
        assert result.returncode == 1
        assert "not found" in result.stderr.lower() or "not found" in result.stdout.lower()

    def test_invalid_json(self, tmp_path):
        path = Path(tmp_path) / "bad.json"
        path.write_text("{invalid json")
        result = _run_linter("--config", str(path))
        assert result.returncode == 1
```

- [ ] **Step 2: Run tests — expect FAIL (config_linter.py not found)**

Run: `python3 -m pytest tests/test_config_linter_cli.py -v`
Expected: FAIL

- [ ] **Step 3: Create `config_linter.py`**

```python
"""Config linter CLI for after.json validation.

Usage:
    python3 config_linter.py --config after.json
    python3 config_linter.py --config after.json --format json
    python3 config_linter.py --config after.json --warnings-as-errors
"""

import argparse
import json
import sys
from pathlib import Path

from lib.config_lint import LintFinding, lint_config

# ANSI color codes
_RED = "\033[91m"
_YELLOW = "\033[93m"
_RESET = "\033[0m"
_BOLD = "\033[1m"


def _supports_color() -> bool:
    """Check if stdout supports ANSI colors."""
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()


def _format_text(findings: list[LintFinding], use_color: bool) -> str:
    """Format findings as human-readable text."""
    errors = [f for f in findings if f.severity == "ERROR"]
    warnings = [f for f in findings if f.severity == "WARNING"]
    lines: list[str] = []

    if errors:
        header = f"ERRORS ({len(errors)} found):"
        if use_color:
            header = f"{_RED}{_BOLD}{header}{_RESET}"
        lines.append(header)
        for f in errors:
            loc = ""
            if f.feed_id is not None:
                loc = f"Feed {f.feed_id}"
                if f.symbol:
                    loc += f" ({f.symbol})"
                loc += ": "
            line = f"  {f.rule_id}  {loc}{f.message}"
            if use_color:
                line = f"  {_RED}{f.rule_id}{_RESET}  {loc}{f.message}"
            lines.append(line)
        lines.append("")

    if warnings:
        header = f"WARNINGS ({len(warnings)} found):"
        if use_color:
            header = f"{_YELLOW}{_BOLD}{header}{_RESET}"
        lines.append(header)
        for f in warnings:
            loc = ""
            if f.feed_id is not None:
                loc = f"Feed {f.feed_id}"
                if f.symbol:
                    loc += f" ({f.symbol})"
                loc += ": "
            line = f"  {f.rule_id}  {loc}{f.message}"
            if use_color:
                line = f"  {_YELLOW}{f.rule_id}{_RESET}  {loc}{f.message}"
            lines.append(line)
        lines.append("")

    if not errors and not warnings:
        lines.append("No issues found.")
    else:
        lines.append(f"Summary: {len(errors)} errors, {len(warnings)} warnings")

    return "\n".join(lines)


def _format_json(findings: list[LintFinding]) -> str:
    """Format findings as JSON array."""
    return json.dumps(
        [
            {
                "rule_id": f.rule_id,
                "severity": f.severity,
                "message": f.message,
                "feed_id": f.feed_id,
                "symbol": f.symbol,
            }
            for f in findings
        ],
        indent=2,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lint after.json config for common errors"
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to after.json config file",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--warnings-as-errors",
        action="store_true",
        help="Treat warnings as errors (exit 1)",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"ERROR: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(config_path) as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in {config_path}: {e}", file=sys.stderr)
        sys.exit(1)

    findings = lint_config(config)

    if args.format == "json":
        print(_format_json(findings))
    else:
        print(_format_text(findings, use_color=_supports_color()))

    errors = [f for f in findings if f.severity == "ERROR"]
    warnings = [f for f in findings if f.severity == "WARNING"]

    if errors:
        sys.exit(1)
    if args.warnings_as_errors and warnings:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests — expect PASS**

Run: `python3 -m pytest tests/test_config_linter_cli.py -v`
Expected: All PASS

- [ ] **Step 5: Smoke test against real after.json**

Run: `python3 config_linter.py --config after.json`
Check: output is reasonable, no crashes, exit code is 0 or 1

Run: `python3 config_linter.py --config after.json --format json | python3 -m json.tool | head -30`
Check: valid JSON output

- [ ] **Step 6: Run pre-commit and commit**

```bash
pre-commit run --files config_linter.py tests/test_config_linter_cli.py
git add config_linter.py tests/test_config_linter_cli.py
git commit -m "feat: add config_linter CLI with text and JSON output"
```

---

### Task 7: Dockerfile

**Files:**

- Create: `Dockerfile.linter`

- [ ] **Step 1: Create `Dockerfile.linter`**

```dockerfile
FROM python:3.11-slim

WORKDIR /app

COPY config_linter.py .
COPY lib/__init__.py lib/
COPY lib/config_lint.py lib/
COPY lib/symbol_utils.py lib/

ENTRYPOINT ["python3", "config_linter.py"]
```

- [ ] **Step 2: Build the image**

Run: `docker build -f Dockerfile.linter -t config-linter:test .`
Expected: Build succeeds

- [ ] **Step 3: Test the image against real after.json**

Run: `docker run --rm -v $(pwd):/repo config-linter:test --config /repo/after.json --format text`
Expected: Same output as running CLI directly

Run: `docker run --rm -v $(pwd):/repo config-linter:test --config /repo/after.json --format json | python3 -m json.tool | head -20`
Expected: Valid JSON

- [ ] **Step 4: Run pre-commit and commit**

```bash
pre-commit run --files Dockerfile.linter
git add Dockerfile.linter
git commit -m "feat: add Dockerfile.linter for governance CI"
```

---

### Task 8: Coverage Check and Final Verification

**Files:**

- All test files

- [ ] **Step 1: Run full test suite with coverage**

Run: `python3 -m pytest tests/test_config_lint.py tests/test_symbol_utils.py tests/test_config_linter_cli.py -v --cov=lib/config_lint --cov=lib/symbol_utils --cov-report=term-missing`
Expected: All PASS, 80%+ coverage on `lib/config_lint.py` and `lib/symbol_utils.py`

- [ ] **Step 2: Run against real after.json and review findings**

Run: `python3 config_linter.py --config after.json`
Review: findings should be sensible — no false positives on known-good feeds, real issues flagged

- [ ] **Step 3: Verify existing tests still pass (no regressions from sql_filters refactor)**

Run: `python3 -m pytest tests/ -v --tb=short`
Expected: All existing tests PASS

- [ ] **Step 4: Run pre-commit on all new/modified files**

```bash
pre-commit run --files lib/symbol_utils.py lib/config_lint.py lib/sql_filters.py config_linter.py tests/test_symbol_utils.py tests/test_config_lint.py tests/test_config_linter_cli.py Dockerfile.linter
```

Expected: All pass

---

### Task 9: Documentation Update

**Files:**

- Modify: `CLAUDE.md`

- [ ] **Step 1: Add config_linter.py to the Scripts table in CLAUDE.md**

Add row to the Scripts table:

```markdown
| `config_linter.py` | Lint after.json for config errors (duplicates, publishers, schedules) | `python3 config_linter.py --config after.json` | - |
```

- [ ] **Step 2: Run pre-commit and commit**

```bash
pre-commit run --files CLAUDE.md
git add CLAUDE.md
git commit -m "docs: add config_linter to scripts table in CLAUDE.md"
```
