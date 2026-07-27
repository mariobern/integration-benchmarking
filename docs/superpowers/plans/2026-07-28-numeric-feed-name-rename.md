# Numeric Feed Name Rename Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the purely numeric `metadata.name` on 452 HK/JP/KR/CN equity feeds with the company name derived from `metadata.description` minus its currency suffix, with a version-controlled override file for hand-curated exceptions.

**Architecture:** One standalone script at repo root holding pure, individually testable functions plus an `argparse` CLI at the bottom — matching `extract_overnight_candidates.py`. The config is read as text, parsed, mutated in memory, and re-serialized with `json.dumps(data, indent=2, ensure_ascii=False)`, which has been verified byte-identical to the on-disk file. A line-level verification pass asserts that the only lines differing between input and output are `"name":` lines.

**Tech Stack:** Python 3.12, stdlib only (`argparse`, `csv`, `json`, `re`, `shutil`, `dataclasses`, `pathlib`), pytest.

**Spec:** `docs/superpowers/specs/2026-07-28-numeric-feed-name-rename-design.md`

## Global Constraints

- Serialization is exactly `json.dumps(data, indent=2, ensure_ascii=False)` written as UTF-8 with **no trailing newline**. `ensure_ascii=False` is load-bearing — the config holds 9 non-ASCII characters that would otherwise be escaped across untouched lines.
- Default symbol prefixes: `Equity.HK.`, `Equity.JP.`, `Equity.KR.`, `Equity.CN.`
- Currency map: `CNY` → `CHINESE YUAN`, `HKD` → `HONG KONG DOLLAR`, `JPY` → `JAPANESE YEN`, `KRW` → `SOUTH KOREAN WON`
- Separator is `" / "` (space-slash-space).
- Numeric-name pattern is `^[0-9]+[A-Za-z]?$`.
- `symbol` and `metadata.description` are **never** modified. Only `metadata.name`.
- Dry-run is the default; `--apply` writes. Backup to `<config>.bak` unless `--no-backup`.
- Duplicate resulting names are a **warning**, never an error.
- Run tests with `pytest tests/test_rename_numeric_feed_names.py -v`. Never run the repo-root `pytest -q` — it fails on a pre-existing conftest name clash unrelated to this work.
- Run `pre-commit run --files <changed files>` before every commit (black, prettier, trailing whitespace, end-of-file).

## File Structure

| File                                               | Responsibility                                                                                                                                                      |
| -------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `rename_numeric_feed_names.py` (create)            | Everything: scope/candidacy predicates, derivation, override loading, change planning, serialization, verification, CLI. ~230 lines, matching sibling root scripts. |
| `feed_name_overrides.csv` (create)                 | Committed override rows for the 4 dual-listing disambiguations.                                                                                                     |
| `tests/test_rename_numeric_feed_names.py` (create) | Unit tests on synthetic fixtures plus a skippable real-data smoke test.                                                                                             |
| `docs/rename_numeric_feed_names.md` (create)       | Per-script doc following `docs/update_min_publishers.md` structure.                                                                                                 |
| `CLAUDE.md` (modify)                               | One row in the Scripts table.                                                                                                                                       |

A single script file is correct here: the sibling root scripts (`extract_overnight_candidates.py`, 126 lines; `update_min_publishers.py`) are single-file, and splitting ~230 lines across modules would break the established pattern for no benefit.

---

### Task 1: Scope, candidacy, and name derivation

**Files:**

- Create: `rename_numeric_feed_names.py`
- Test: `tests/test_rename_numeric_feed_names.py`

**Interfaces:**

- Consumes: nothing (first task)
- Produces:

  - `MARKET_PREFIXES: tuple[str, ...]`
  - `CURRENCY_NAMES: dict[str, str]`
  - `SEPARATOR: str`
  - `NUMERIC_NAME_RE: re.Pattern`
  - `in_scope(feed: dict, prefixes: tuple[str, ...] = MARKET_PREFIXES) -> bool`
  - `is_candidate(feed: dict, prefixes: tuple[str, ...] = MARKET_PREFIXES) -> bool`
  - `derive_name(feed: dict) -> tuple[str | None, str | None]` returning `(name, None)` on success or `(None, reason)` on skip

- [ ] **Step 1: Write the failing tests**

Create `tests/test_rename_numeric_feed_names.py`:

```python
"""Tests for rename_numeric_feed_names.py."""

from rename_numeric_feed_names import (
    derive_name,
    in_scope,
    is_candidate,
)


def _feed(feed_id=100, symbol="Equity.CN.688825/CNY", name="688825",
          description="CHANGXIN MEMORY TECHNOLOGIES / CHINESE YUAN",
          quote_currency="CNY"):
    """Build a minimal feed dict shaped like a lazer-state.json entry."""
    return {
        "feedId": feed_id,
        "symbol": symbol,
        "state": "STABLE",
        "metadata": {
            "asset_type": "equity",
            "description": description,
            "name": name,
            "quote_currency": quote_currency,
        },
    }


class TestInScope:
    def test_cn_prefix_in_scope(self):
        assert in_scope(_feed()) is True

    def test_us_prefix_out_of_scope(self):
        assert in_scope(_feed(symbol="Equity.US.AAPL/USD")) is False

    def test_custom_prefixes_respected(self):
        assert in_scope(_feed(), prefixes=("Equity.JP.",)) is False


class TestIsCandidate:
    def test_numeric_name_is_candidate(self):
        assert is_candidate(_feed()) is True

    def test_numeric_with_trailing_letter_is_candidate(self):
        assert is_candidate(_feed(name="0700A")) is True

    def test_already_renamed_is_not_candidate(self):
        assert is_candidate(_feed(name="CHANGXIN MEMORY TECHNOLOGIES")) is False

    def test_alphanumeric_futures_code_is_not_candidate(self):
        assert is_candidate(_feed(symbol="Equity.KR.KSM6/KRW", name="KSM6")) is False

    def test_out_of_scope_never_candidate(self):
        assert is_candidate(_feed(symbol="Equity.US.AAPL/USD", name="123")) is False


class TestDeriveName:
    def test_happy_path(self):
        name, reason = derive_name(_feed())
        assert name == "CHANGXIN MEMORY TECHNOLOGIES"
        assert reason is None

    def test_strips_trailing_whitespace(self):
        feed = _feed(
            symbol="Equity.KR.001040/KRW",
            description="CJ CORP  / SOUTH KOREAN WON",
            quote_currency="KRW",
        )
        name, reason = derive_name(feed)
        assert name == "CJ CORP"
        assert reason is None

    def test_splits_on_last_separator(self):
        feed = _feed(description="FOO / BAR CORP / CHINESE YUAN")
        name, reason = derive_name(feed)
        assert name == "FOO / BAR CORP"
        assert reason is None

    def test_currency_mismatch_is_skipped(self):
        feed = _feed(description="SOME CORP / US DOLLAR")
        name, reason = derive_name(feed)
        assert name is None
        assert "does not match expected" in reason

    def test_unmapped_currency_is_skipped(self):
        feed = _feed(
            symbol="Equity.TW.2330/TWD",
            description="TSMC / TAIWAN DOLLAR",
            quote_currency="TWD",
        )
        name, reason = derive_name(feed)
        assert name is None
        assert "no currency name mapped" in reason

    def test_missing_separator_is_skipped(self):
        feed = _feed(description="CHANGXIN MEMORY TECHNOLOGIES")
        name, reason = derive_name(feed)
        assert name is None
        assert "separator" in reason

    def test_empty_derived_name_is_skipped(self):
        feed = _feed(description=" / CHINESE YUAN")
        name, reason = derive_name(feed)
        assert name is None
        assert "empty" in reason
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_rename_numeric_feed_names.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'rename_numeric_feed_names'`

- [ ] **Step 3: Write the minimal implementation**

Create `rename_numeric_feed_names.py`:

```python
#!/usr/bin/env python3
"""Replace numeric metadata.name values with human-readable company names.

Equities listed in Hong Kong, Japan, South Korea and mainland China carry a
purely numeric `metadata.name` (e.g. `688825`) because those exchanges issue
numeric instrument codes rather than alphabetic tickers. The company name is
already present in `metadata.description`, suffixed with the spelled-out quote
currency, so the name is derived by stripping that suffix.

The exchange code is never lost: it stays in `symbol` (`Equity.CN.688825/CNY`),
and `metadata.description` is never modified.

See docs/superpowers/specs/2026-07-28-numeric-feed-name-rename-design.md.
"""

import re

MARKET_PREFIXES = ("Equity.HK.", "Equity.JP.", "Equity.KR.", "Equity.CN.")

CURRENCY_NAMES = {
    "CNY": "CHINESE YUAN",
    "HKD": "HONG KONG DOLLAR",
    "JPY": "JAPANESE YEN",
    "KRW": "SOUTH KOREAN WON",
}

SEPARATOR = " / "

NUMERIC_NAME_RE = re.compile(r"^[0-9]+[A-Za-z]?$")


def in_scope(feed: dict, prefixes: tuple[str, ...] = MARKET_PREFIXES) -> bool:
    """True iff the feed's symbol sits in one of the configured namespaces."""
    return feed.get("symbol", "").startswith(prefixes)


def is_candidate(feed: dict, prefixes: tuple[str, ...] = MARKET_PREFIXES) -> bool:
    """True iff the feed is in scope and still carries a numeric name.

    The numeric test is what makes the script idempotent: once renamed, a feed
    stops matching, so a second run is a no-op.
    """
    if not in_scope(feed, prefixes):
        return False
    name = str(feed.get("metadata", {}).get("name", ""))
    return bool(NUMERIC_NAME_RE.match(name))


def derive_name(feed: dict) -> tuple[str | None, str | None]:
    """Derive the company name from `metadata.description`.

    Returns `(name, None)` on success, or `(None, reason)` when the feed must be
    skipped. The description tail is validated against the feed's
    `quote_currency` so a malformed or unmapped description is reported rather
    than written into `name` as a mangled value.
    """
    metadata = feed.get("metadata", {})
    description = metadata.get("description") or ""
    head, separator, tail = description.rpartition(SEPARATOR)
    if not separator:
        return None, f"description has no {SEPARATOR!r} separator: {description!r}"

    currency = metadata.get("quote_currency")
    expected = CURRENCY_NAMES.get(currency)
    if expected is None:
        return None, f"no currency name mapped for quote_currency {currency!r}"
    if tail.strip() != expected:
        return None, (
            f"description tail {tail.strip()!r} does not match expected "
            f"{expected!r} for {currency}"
        )

    name = head.strip()
    if not name:
        return None, f"derived name is empty from description {description!r}"
    return name, None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_rename_numeric_feed_names.py -v`
Expected: PASS — 15 passed

- [ ] **Step 5: Commit**

```bash
pre-commit run --files rename_numeric_feed_names.py tests/test_rename_numeric_feed_names.py
git add rename_numeric_feed_names.py tests/test_rename_numeric_feed_names.py
git commit -m "feat(rename-names): scope, candidacy and name derivation"
```

---

### Task 2: Override file loading and validation

**Files:**

- Modify: `rename_numeric_feed_names.py` (append after `derive_name`)
- Test: `tests/test_rename_numeric_feed_names.py` (append)

**Interfaces:**

- Consumes: `in_scope`, `MARKET_PREFIXES` from Task 1
- Produces:

  - `OverrideError(Exception)`
  - `OVERRIDE_COLUMNS: tuple[str, ...]`
  - `load_overrides(path: Path) -> dict[int, str]`
  - `validate_overrides(overrides: dict[int, str], feeds: list[dict], prefixes: tuple[str, ...] = MARKET_PREFIXES) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_rename_numeric_feed_names.py` (and extend the import at the top to include `OverrideError`, `load_overrides`, `validate_overrides`):

```python
import pytest

from rename_numeric_feed_names import (
    OverrideError,
    load_overrides,
    validate_overrides,
)


def _write_csv(tmp_path, text):
    path = tmp_path / "overrides.csv"
    path.write_text(text, encoding="utf-8")
    return path


class TestLoadOverrides:
    def test_parses_rows(self, tmp_path):
        path = _write_csv(tmp_path, "feed_id,name\n3520,CXMT\n3360,GIGA (HK)\n")
        assert load_overrides(path) == {3520: "CXMT", 3360: "GIGA (HK)"}

    def test_strips_whitespace(self, tmp_path):
        path = _write_csv(tmp_path, "feed_id,name\n 3520 , CXMT \n")
        assert load_overrides(path) == {3520: "CXMT"}

    def test_skips_fully_blank_rows(self, tmp_path):
        path = _write_csv(tmp_path, "feed_id,name\n3520,CXMT\n,\n")
        assert load_overrides(path) == {3520: "CXMT"}

    def test_missing_file_is_error(self, tmp_path):
        with pytest.raises(OverrideError, match="not found"):
            load_overrides(tmp_path / "nope.csv")

    def test_missing_column_is_error(self, tmp_path):
        path = _write_csv(tmp_path, "feed_id\n3520\n")
        with pytest.raises(OverrideError, match="missing required column"):
            load_overrides(path)

    def test_non_integer_feed_id_is_error(self, tmp_path):
        path = _write_csv(tmp_path, "feed_id,name\nabc,CXMT\n")
        with pytest.raises(OverrideError, match="not an integer"):
            load_overrides(path)

    def test_empty_name_is_error(self, tmp_path):
        path = _write_csv(tmp_path, "feed_id,name\n3520,\n")
        with pytest.raises(OverrideError, match="name is empty"):
            load_overrides(path)

    def test_duplicate_feed_id_is_error(self, tmp_path):
        path = _write_csv(tmp_path, "feed_id,name\n3520,CXMT\n3520,OTHER\n")
        with pytest.raises(OverrideError, match="duplicate feed_id"):
            load_overrides(path)


class TestValidateOverrides:
    def test_in_scope_feed_accepted(self):
        feeds = [_feed(feed_id=3520)]
        validate_overrides({3520: "CXMT"}, feeds)

    def test_already_renamed_feed_accepted(self):
        feeds = [_feed(feed_id=3520, name="CHANGXIN MEMORY TECHNOLOGIES")]
        validate_overrides({3520: "CXMT"}, feeds)

    def test_unknown_feed_id_is_error(self):
        with pytest.raises(OverrideError, match="not found in config"):
            validate_overrides({999: "X"}, [_feed(feed_id=3520)])

    def test_out_of_prefix_feed_is_error(self):
        feeds = [_feed(feed_id=922, symbol="Equity.US.AAPL/USD")]
        with pytest.raises(OverrideError, match="outside the configured"):
            validate_overrides({922: "APPLE"}, feeds)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_rename_numeric_feed_names.py -v -k "Override"`
Expected: FAIL — `ImportError: cannot import name 'OverrideError'`

- [ ] **Step 3: Write the minimal implementation**

Add `import csv` and `from pathlib import Path` to the imports in `rename_numeric_feed_names.py`, then append:

```python
class OverrideError(Exception):
    """Raised on a malformed or invalid override CSV."""


OVERRIDE_COLUMNS = ("feed_id", "name")


def load_overrides(path: Path) -> dict[int, str]:
    """Parse the override CSV into `{feed_id: name}`.

    Raises OverrideError on any structural problem. Rows that are entirely
    blank are skipped so a trailing newline is not an error.
    """
    if not path.exists():
        raise OverrideError(f"override CSV not found: {path}")
    overrides: dict[int, str] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise OverrideError(f"{path}: no header row")
        missing = [c for c in OVERRIDE_COLUMNS if c not in reader.fieldnames]
        if missing:
            raise OverrideError(
                f"{path}: missing required column(s): {', '.join(missing)}"
            )
        for lineno, row in enumerate(reader, start=2):  # line 2 = first data row
            raw_id = (row.get("feed_id") or "").strip()
            name = (row.get("name") or "").strip()
            if not raw_id and not name:
                continue
            try:
                feed_id = int(raw_id)
            except ValueError:
                raise OverrideError(
                    f"{path} line {lineno}: feed_id {raw_id!r} is not an integer"
                ) from None
            if not name:
                raise OverrideError(f"{path} line {lineno}: name is empty")
            if feed_id in overrides:
                raise OverrideError(f"{path} line {lineno}: duplicate feed_id {feed_id}")
            overrides[feed_id] = name
    return overrides


def validate_overrides(
    overrides: dict[int, str],
    feeds: list[dict],
    prefixes: tuple[str, ...] = MARKET_PREFIXES,
) -> None:
    """Raise OverrideError unless every override targets an in-scope feed.

    An override may target a feed that is no longer a candidate (already
    renamed), so a short code can be pinned after the bulk rename has run.
    """
    by_id = {f["feedId"]: f for f in feeds}
    for feed_id in sorted(overrides):
        feed = by_id.get(feed_id)
        if feed is None:
            raise OverrideError(f"override feed_id {feed_id} not found in config")
        if not in_scope(feed, prefixes):
            raise OverrideError(
                f"override feed_id {feed_id} ({feed.get('symbol')}) is outside "
                f"the configured symbol prefixes: {', '.join(prefixes)}"
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_rename_numeric_feed_names.py -v`
Expected: PASS — 27 passed

- [ ] **Step 5: Commit**

```bash
pre-commit run --files rename_numeric_feed_names.py tests/test_rename_numeric_feed_names.py
git add rename_numeric_feed_names.py tests/test_rename_numeric_feed_names.py
git commit -m "feat(rename-names): override CSV loading and validation"
```

---

### Task 3: Change planning and duplicate detection

**Files:**

- Modify: `rename_numeric_feed_names.py` (append)
- Test: `tests/test_rename_numeric_feed_names.py` (append)

**Interfaces:**

- Consumes: `in_scope`, `is_candidate`, `derive_name`, `MARKET_PREFIXES` from Task 1
- Produces:

  - `Change` frozen dataclass with fields `feed_id: int`, `symbol: str`, `before: str`, `after: str`, `source: str` (`"rule"` or `"override"`)
  - `Skip` frozen dataclass with fields `feed_id: int`, `symbol: str`, `reason: str`
  - `build_changes(feeds: list[dict], prefixes: tuple[str, ...] = MARKET_PREFIXES, overrides: dict[int, str] | None = None) -> tuple[list[Change], list[Skip]]`
  - `find_duplicate_names(feeds: list[dict], changes: list[Change]) -> list[tuple[str, list[tuple[int, str]]]]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_rename_numeric_feed_names.py` (extend imports with `Change`, `build_changes`, `find_duplicate_names`):

```python
from rename_numeric_feed_names import Change, build_changes, find_duplicate_names


class TestBuildChanges:
    def test_derives_name_for_candidate(self):
        changes, skips = build_changes([_feed(feed_id=3520)])
        assert skips == []
        assert changes == [
            Change(
                feed_id=3520,
                symbol="Equity.CN.688825/CNY",
                before="688825",
                after="CHANGXIN MEMORY TECHNOLOGIES",
                source="rule",
            )
        ]

    def test_out_of_scope_feed_untouched(self):
        feeds = [_feed(feed_id=922, symbol="Equity.US.AAPL/USD", name="AAPL")]
        changes, skips = build_changes(feeds)
        assert changes == []
        assert skips == []

    def test_already_renamed_feed_is_noop(self):
        feeds = [_feed(feed_id=3520, name="CHANGXIN MEMORY TECHNOLOGIES")]
        changes, skips = build_changes(feeds)
        assert changes == []
        assert skips == []

    def test_idempotent_second_pass(self):
        feeds = [_feed(feed_id=3520)]
        changes, _ = build_changes(feeds)
        feeds[0]["metadata"]["name"] = changes[0].after
        changes_again, skips_again = build_changes(feeds)
        assert changes_again == []
        assert skips_again == []

    def test_undeliverable_description_is_skipped(self):
        feeds = [_feed(feed_id=3520, description="SOME CORP / US DOLLAR")]
        changes, skips = build_changes(feeds)
        assert changes == []
        assert len(skips) == 1
        assert skips[0].feed_id == 3520

    def test_override_beats_derived_name(self):
        changes, skips = build_changes([_feed(feed_id=3520)], overrides={3520: "CXMT"})
        assert skips == []
        assert changes[0].after == "CXMT"
        assert changes[0].source == "override"

    def test_override_applies_to_already_renamed_feed(self):
        feeds = [_feed(feed_id=3520, name="CHANGXIN MEMORY TECHNOLOGIES")]
        changes, _ = build_changes(feeds, overrides={3520: "CXMT"})
        assert changes[0].before == "CHANGXIN MEMORY TECHNOLOGIES"
        assert changes[0].after == "CXMT"

    def test_override_matching_current_name_is_noop(self):
        changes, _ = build_changes([_feed(feed_id=3520)], overrides={3520: "688825"})
        assert changes == []

    def test_override_skips_currency_validation(self):
        feeds = [_feed(feed_id=3520, description="BROKEN DESCRIPTION")]
        changes, skips = build_changes(feeds, overrides={3520: "CXMT"})
        assert skips == []
        assert changes[0].after == "CXMT"


class TestFindDuplicateNames:
    def test_reports_dual_listing(self):
        feeds = [
            _feed(
                feed_id=3339,
                symbol="Equity.CN.603986/CNY",
                name="603986",
                description="GIGADEVICE SEMICONDUCTOR INC / CHINESE YUAN",
            ),
            _feed(
                feed_id=3360,
                symbol="Equity.HK.3986/HKD",
                name="3986",
                description="GIGADEVICE SEMICONDUCTOR INC / HONG KONG DOLLAR",
                quote_currency="HKD",
            ),
        ]
        changes, _ = build_changes(feeds)
        duplicates = find_duplicate_names(feeds, changes)
        assert duplicates == [
            (
                "GIGADEVICE SEMICONDUCTOR INC",
                [(3339, "Equity.CN.603986/CNY"), (3360, "Equity.HK.3986/HKD")],
            )
        ]

    def test_overrides_clear_the_duplicate(self):
        feeds = [
            _feed(
                feed_id=3339,
                symbol="Equity.CN.603986/CNY",
                name="603986",
                description="GIGADEVICE SEMICONDUCTOR INC / CHINESE YUAN",
            ),
            _feed(
                feed_id=3360,
                symbol="Equity.HK.3986/HKD",
                name="3986",
                description="GIGADEVICE SEMICONDUCTOR INC / HONG KONG DOLLAR",
                quote_currency="HKD",
            ),
        ]
        overrides = {
            3339: "GIGADEVICE SEMICONDUCTOR INC (CN)",
            3360: "GIGADEVICE SEMICONDUCTOR INC (HK)",
        }
        changes, _ = build_changes(feeds, overrides=overrides)
        assert find_duplicate_names(feeds, changes) == []

    def test_preexisting_duplicate_not_reported_when_untouched(self):
        feeds = [
            _feed(feed_id=979, symbol="Equity.US.BA/USD", name="BA"),
            _feed(feed_id=790, symbol="Equity.GB.BA/GBP", name="BA"),
        ]
        assert find_duplicate_names(feeds, changes=[]) == []

    def test_collision_with_untouched_feed_is_reported(self):
        feeds = [
            _feed(feed_id=3520),
            _feed(
                feed_id=3293,
                symbol="Equity.US.CXMT/USD",
                name="CHANGXIN MEMORY TECHNOLOGIES",
            ),
        ]
        changes, _ = build_changes(feeds)
        duplicates = find_duplicate_names(feeds, changes)
        assert len(duplicates) == 1
        assert duplicates[0][0] == "CHANGXIN MEMORY TECHNOLOGIES"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_rename_numeric_feed_names.py -v -k "BuildChanges or FindDuplicate"`
Expected: FAIL — `ImportError: cannot import name 'Change'`

- [ ] **Step 3: Write the minimal implementation**

Add `from dataclasses import dataclass` to the imports, then append:

```python
@dataclass(frozen=True)
class Change:
    """One planned `metadata.name` rewrite."""

    feed_id: int
    symbol: str
    before: str
    after: str
    source: str  # "rule" or "override"


@dataclass(frozen=True)
class Skip:
    """A candidate that could not be derived, with the reason why."""

    feed_id: int
    symbol: str
    reason: str


def build_changes(
    feeds: list[dict],
    prefixes: tuple[str, ...] = MARKET_PREFIXES,
    overrides: dict[int, str] | None = None,
) -> tuple[list[Change], list[Skip]]:
    """Plan the rename over every in-scope feed.

    Overrides take precedence over rule derivation and bypass the currency
    check, since the value is supplied by hand. A feed whose name already
    equals the target produces no change, which is what makes repeat runs
    no-ops.
    """
    overrides = overrides or {}
    changes: list[Change] = []
    skips: list[Skip] = []
    for feed in feeds:
        if not in_scope(feed, prefixes):
            continue
        feed_id = feed["feedId"]
        symbol = feed.get("symbol", "")
        before = str(feed.get("metadata", {}).get("name", ""))

        if feed_id in overrides:
            after, source = overrides[feed_id], "override"
        elif is_candidate(feed, prefixes):
            after, reason = derive_name(feed)
            if after is None:
                skips.append(Skip(feed_id, symbol, reason))
                continue
            source = "rule"
        else:
            continue

        if after != before:
            changes.append(Change(feed_id, symbol, before, after, source))
    return changes, skips


def find_duplicate_names(
    feeds: list[dict], changes: list[Change]
) -> list[tuple[str, list[tuple[int, str]]]]:
    """Names shared by two or more feeds after the rename.

    Only groups containing at least one changed feed are reported, which keeps
    pre-existing duplicates elsewhere in the config (`BA`, `AAL`) out of the
    output while still catching a derived name colliding with an untouched one.
    """
    new_names = {c.feed_id: c.after for c in changes}
    groups: dict[str, list[tuple[int, str]]] = {}
    for feed in feeds:
        feed_id = feed["feedId"]
        current = str(feed.get("metadata", {}).get("name", ""))
        name = new_names.get(feed_id, current)
        groups.setdefault(name, []).append((feed_id, feed.get("symbol", "")))
    return sorted(
        (name, members)
        for name, members in groups.items()
        if len(members) > 1 and any(fid in new_names for fid, _ in members)
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_rename_numeric_feed_names.py -v`
Expected: PASS — 40 passed

- [ ] **Step 5: Commit**

```bash
pre-commit run --files rename_numeric_feed_names.py tests/test_rename_numeric_feed_names.py
git add rename_numeric_feed_names.py tests/test_rename_numeric_feed_names.py
git commit -m "feat(rename-names): change planning and duplicate detection"
```

---

### Task 4: Serialization, verification, and writing

**Files:**

- Modify: `rename_numeric_feed_names.py` (append)
- Test: `tests/test_rename_numeric_feed_names.py` (append)

**Interfaces:**

- Consumes: `Change` from Task 3
- Produces:

  - `VerificationError(Exception)`
  - `dump_config(data: dict) -> str`
  - `apply_changes(data: dict, changes: list[Change]) -> None` (mutates in place)
  - `verify_text(before_text: str, after_text: str, changes: list[Change]) -> None` (raises `VerificationError`)
  - `verify_on_disk(path: Path, before_text: str, changes: list[Change]) -> None`
  - `write_config(path: Path, text: str, backup: bool = True) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_rename_numeric_feed_names.py` (extend imports with `VerificationError`, `apply_changes`, `dump_config`, `verify_on_disk`, `verify_text`, `write_config`; add `import json` at the top):

```python
import json

from rename_numeric_feed_names import (
    VerificationError,
    apply_changes,
    dump_config,
    verify_on_disk,
    verify_text,
    write_config,
)


def _config(*feeds):
    return {"feeds": list(feeds)}


class TestDumpConfig:
    def test_round_trip_is_byte_identical(self, tmp_path):
        data = _config(_feed(feed_id=3520))
        text = dump_config(data)
        assert dump_config(json.loads(text)) == text

    def test_no_trailing_newline(self):
        assert not dump_config(_config(_feed())).endswith("\n")

    def test_non_ascii_is_not_escaped(self):
        data = _config(_feed(description="COSTA RICAN COLÓN / CHINESE YUAN"))
        assert "COLÓN" in dump_config(data)
        assert "\\u00d3" not in dump_config(data).lower()


class TestApplyChanges:
    def test_sets_name_and_leaves_description(self):
        data = _config(_feed(feed_id=3520))
        changes, _ = build_changes(data["feeds"])
        apply_changes(data, changes)
        metadata = data["feeds"][0]["metadata"]
        assert metadata["name"] == "CHANGXIN MEMORY TECHNOLOGIES"
        assert metadata["description"] == "CHANGXIN MEMORY TECHNOLOGIES / CHINESE YUAN"

    def test_symbol_untouched(self):
        data = _config(_feed(feed_id=3520))
        changes, _ = build_changes(data["feeds"])
        apply_changes(data, changes)
        assert data["feeds"][0]["symbol"] == "Equity.CN.688825/CNY"


class TestVerifyText:
    def _before_after(self):
        data = _config(_feed(feed_id=3520), _feed(feed_id=3521, symbol="Equity.US.X/USD"))
        before_text = dump_config(data)
        changes, _ = build_changes(data["feeds"])
        apply_changes(data, changes)
        return before_text, dump_config(data), changes

    def test_passes_on_name_only_diff(self):
        before_text, after_text, changes = self._before_after()
        verify_text(before_text, after_text, changes)

    def test_untouched_feed_lines_are_identical(self):
        before_text, after_text, changes = self._before_after()
        differing = [
            b
            for b, a in zip(before_text.split("\n"), after_text.split("\n"))
            if b != a
        ]
        assert len(differing) == 1
        assert differing[0].strip().startswith('"name":')

    def test_rejects_unexpected_field_change(self):
        before_text, after_text, changes = self._before_after()
        tampered = after_text.replace("Equity.CN.688825/CNY", "Equity.CN.999999/CNY")
        with pytest.raises(VerificationError):
            verify_text(before_text, tampered, changes)

    def test_rejects_line_count_change(self):
        before_text, after_text, changes = self._before_after()
        with pytest.raises(VerificationError, match="line count changed"):
            verify_text(before_text, after_text + "\n", changes)

    def test_rejects_wrong_change_count(self):
        before_text, after_text, changes = self._before_after()
        with pytest.raises(VerificationError, match="changed line"):
            verify_text(before_text, after_text, [])


class TestWriteConfig:
    def test_writes_and_backs_up(self, tmp_path):
        path = tmp_path / "cfg.json"
        path.write_text("original", encoding="utf-8")
        write_config(path, "updated")
        assert path.read_text(encoding="utf-8") == "updated"
        assert (tmp_path / "cfg.json.bak").read_text(encoding="utf-8") == "original"

    def test_no_backup_flag(self, tmp_path):
        path = tmp_path / "cfg.json"
        path.write_text("original", encoding="utf-8")
        write_config(path, "updated", backup=False)
        assert not (tmp_path / "cfg.json.bak").exists()


class TestVerifyOnDisk:
    def test_passes_after_real_write(self, tmp_path):
        data = _config(_feed(feed_id=3520))
        before_text = dump_config(data)
        path = tmp_path / "cfg.json"
        path.write_text(before_text, encoding="utf-8")
        changes, _ = build_changes(data["feeds"])
        apply_changes(data, changes)
        write_config(path, dump_config(data), backup=False)
        verify_on_disk(path, before_text, changes)

    def test_rejects_unparseable_file(self, tmp_path):
        path = tmp_path / "cfg.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(VerificationError, match="does not parse"):
            verify_on_disk(path, dump_config(_config(_feed())), [])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_rename_numeric_feed_names.py -v -k "Dump or Apply or Verify or Write"`
Expected: FAIL — `ImportError: cannot import name 'VerificationError'`

- [ ] **Step 3: Write the minimal implementation**

Add `import json` and `import shutil` to the imports, then append:

```python
class VerificationError(Exception):
    """Raised when the rewritten config differs in unexpected ways."""


def dump_config(data: dict) -> str:
    """Serialize exactly as the config is stored on disk.

    2-space indent, raw UTF-8, no trailing newline. Verified byte-identical
    against an unmodified `lazer-state.json`, so the only difference between
    input and output is the lines this script deliberately changes.
    """
    return json.dumps(data, indent=2, ensure_ascii=False)


def apply_changes(data: dict, changes: list[Change]) -> None:
    """Write the planned names into the in-memory document."""
    by_id = {f["feedId"]: f for f in data["feeds"]}
    for change in changes:
        by_id[change.feed_id]["metadata"]["name"] = change.after


def _parse_name_line(line: str) -> str:
    """Extract the value from a `"name": "..."` line, comma or not."""
    return json.loads("{" + line.strip().rstrip(",") + "}")["name"]


def verify_text(before_text: str, after_text: str, changes: list[Change]) -> None:
    """Raise VerificationError unless every differing line is an expected name.

    This is what makes a whole-document rewrite trustworthy: it proves no other
    field, feed, or formatting detail moved.
    """
    before_lines = before_text.split("\n")
    after_lines = after_text.split("\n")
    if len(before_lines) != len(after_lines):
        raise VerificationError(
            f"line count changed: {len(before_lines)} -> {len(after_lines)}"
        )
    differing = [
        (lineno, before, after)
        for lineno, (before, after) in enumerate(
            zip(before_lines, after_lines), start=1
        )
        if before != after
    ]
    if len(differing) != len(changes):
        raise VerificationError(
            f"expected {len(changes)} changed line(s), found {len(differing)}"
        )
    for lineno, before_line, _after_line in differing:
        if not before_line.strip().startswith('"name":'):
            raise VerificationError(
                f"line {lineno} is not a name field: {before_line.strip()!r}"
            )
    expected = sorted(c.after for c in changes)
    found = sorted(_parse_name_line(after) for _, _, after in differing)
    if expected != found:
        raise VerificationError("changed name values do not match the plan")


def verify_on_disk(path: Path, before_text: str, changes: list[Change]) -> None:
    """Re-read the written config and confirm it parses and changed only names."""
    after_text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(after_text)
    except json.JSONDecodeError as exc:
        raise VerificationError(f"written config does not parse: {exc}") from exc
    expected_feeds = len(json.loads(before_text)["feeds"])
    if len(data["feeds"]) != expected_feeds:
        raise VerificationError(
            f"feed count changed: {expected_feeds} -> {len(data['feeds'])}"
        )
    verify_text(before_text, after_text, changes)


def write_config(path: Path, text: str, backup: bool = True) -> None:
    """Back up (unless suppressed) then overwrite the config."""
    if backup:
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    path.write_text(text, encoding="utf-8")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_rename_numeric_feed_names.py -v`
Expected: PASS — 54 passed

- [ ] **Step 5: Commit**

```bash
pre-commit run --files rename_numeric_feed_names.py tests/test_rename_numeric_feed_names.py
git add rename_numeric_feed_names.py tests/test_rename_numeric_feed_names.py
git commit -m "feat(rename-names): serialization, verification and writing"
```

---

### Task 5: CLI, reporting, and the committed override file

**Files:**

- Modify: `rename_numeric_feed_names.py` (append)
- Create: `feed_name_overrides.csv`
- Test: `tests/test_rename_numeric_feed_names.py` (append)

**Interfaces:**

- Consumes: everything from Tasks 1–4
- Produces:

  - `print_report(changes: list[Change], skips: list[Skip], duplicates: list[tuple[str, list[tuple[int, str]]]]) -> None`
  - `main(argv: list[str] | None = None) -> int` returning a process exit code

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_rename_numeric_feed_names.py` (extend imports with `main`):

```python
from rename_numeric_feed_names import main


def _write_config(tmp_path, *feeds):
    path = tmp_path / "cfg.json"
    path.write_text(dump_config(_config(*feeds)), encoding="utf-8")
    return path


class TestMain:
    def test_dry_run_writes_nothing(self, tmp_path, capsys):
        path = _write_config(tmp_path, _feed(feed_id=3520))
        original = path.read_text(encoding="utf-8")
        assert main(["--config", str(path)]) == 0
        assert path.read_text(encoding="utf-8") == original
        assert not (tmp_path / "cfg.json.bak").exists()
        assert "DRY RUN" in capsys.readouterr().out

    def test_apply_writes_and_backs_up(self, tmp_path):
        path = _write_config(tmp_path, _feed(feed_id=3520))
        assert main(["--config", str(path), "--apply"]) == 0
        written = json.loads(path.read_text(encoding="utf-8"))
        assert written["feeds"][0]["metadata"]["name"] == "CHANGXIN MEMORY TECHNOLOGIES"
        assert (tmp_path / "cfg.json.bak").exists()

    def test_second_run_is_a_noop(self, tmp_path, capsys):
        path = _write_config(tmp_path, _feed(feed_id=3520))
        main(["--config", str(path), "--apply"])
        capsys.readouterr()
        assert main(["--config", str(path), "--apply"]) == 0
        assert "No changes" in capsys.readouterr().out

    def test_override_applied(self, tmp_path):
        path = _write_config(tmp_path, _feed(feed_id=3520))
        overrides = tmp_path / "ov.csv"
        overrides.write_text("feed_id,name\n3520,CXMT\n", encoding="utf-8")
        args = ["--config", str(path), "--name-overrides", str(overrides), "--apply"]
        assert main(args) == 0
        written = json.loads(path.read_text(encoding="utf-8"))
        assert written["feeds"][0]["metadata"]["name"] == "CXMT"

    def test_bad_override_exits_one_without_writing(self, tmp_path):
        path = _write_config(tmp_path, _feed(feed_id=3520))
        original = path.read_text(encoding="utf-8")
        overrides = tmp_path / "ov.csv"
        overrides.write_text("feed_id,name\n999,NOPE\n", encoding="utf-8")
        args = ["--config", str(path), "--name-overrides", str(overrides), "--apply"]
        assert main(args) == 1
        assert path.read_text(encoding="utf-8") == original

    def test_symbol_prefix_narrows_scope(self, tmp_path):
        path = _write_config(
            tmp_path,
            _feed(feed_id=3520),
            _feed(
                feed_id=884,
                symbol="Equity.HK.0002/HKD",
                name="0002",
                description="CLP HOLDINGS / HONG KONG DOLLAR",
                quote_currency="HKD",
            ),
        )
        assert main(["--config", str(path), "--symbol-prefix", "Equity.HK.", "--apply"]) == 0
        written = json.loads(path.read_text(encoding="utf-8"))
        assert written["feeds"][0]["metadata"]["name"] == "688825"
        assert written["feeds"][1]["metadata"]["name"] == "CLP HOLDINGS"

    def test_duplicate_warning_printed(self, tmp_path, capsys):
        path = _write_config(
            tmp_path,
            _feed(
                feed_id=3339,
                symbol="Equity.CN.603986/CNY",
                name="603986",
                description="GIGADEVICE SEMICONDUCTOR INC / CHINESE YUAN",
            ),
            _feed(
                feed_id=3360,
                symbol="Equity.HK.3986/HKD",
                name="3986",
                description="GIGADEVICE SEMICONDUCTOR INC / HONG KONG DOLLAR",
                quote_currency="HKD",
            ),
        )
        assert main(["--config", str(path), "--apply"]) == 0
        out = capsys.readouterr().out
        assert "WARNING" in out
        assert "GIGADEVICE SEMICONDUCTOR INC" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_rename_numeric_feed_names.py -v -k "TestMain"`
Expected: FAIL — `ImportError: cannot import name 'main'`

- [ ] **Step 3: Write the minimal implementation**

Add `import argparse` and `import sys` to the imports, then append:

```python
def print_report(
    changes: list[Change],
    skips: list[Skip],
    duplicates: list[tuple[str, list[tuple[int, str]]]],
) -> None:
    """Print the change table, skip list, and duplicate-name warnings."""
    if changes:
        width = max(len(c.symbol) for c in changes)
        print(f"\nChanges ({len(changes)}):")
        for change in changes:
            print(
                f"  {change.feed_id:5d}  {change.symbol:<{width}}  "
                f"{change.before!r} -> {change.after!r}  [{change.source}]"
            )
    if skips:
        print(f"\nSkipped ({len(skips)}):")
        for skip in skips:
            print(f"  {skip.feed_id:5d}  {skip.symbol}  {skip.reason}")
    for name, members in duplicates:
        print(f"\nWARNING  duplicate name {name!r}")
        for feed_id, symbol in members:
            print(f"           {feed_id:5d}  {symbol}")
    print(
        f"\nSummary: {len(changes)} change(s), {len(skips)} skip(s), "
        f"{len(duplicates)} duplicate-name warning(s)."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="Path to the config")
    parser.add_argument(
        "--symbol-prefix",
        action="append",
        dest="symbol_prefixes",
        help=(
            "Symbol namespace to process; repeatable. Defaults to "
            f"{', '.join(MARKET_PREFIXES)}"
        ),
    )
    parser.add_argument(
        "--name-overrides",
        type=Path,
        help="CSV of hand-curated names (columns: feed_id,name)",
    )
    parser.add_argument("--apply", action="store_true", help="Write changes")
    parser.add_argument("--no-backup", action="store_true", help="Skip the .bak copy")
    args = parser.parse_args(argv)

    prefixes = tuple(args.symbol_prefixes) if args.symbol_prefixes else MARKET_PREFIXES

    before_text = args.config.read_text(encoding="utf-8")
    data = json.loads(before_text)
    feeds = data["feeds"]
    print(f"Reading {args.config} ({len(feeds)} feeds)...")

    overrides: dict[int, str] = {}
    if args.name_overrides:
        try:
            overrides = load_overrides(args.name_overrides)
            validate_overrides(overrides, feeds, prefixes)
        except OverrideError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print(f"Loaded {len(overrides)} override(s) from {args.name_overrides}")

    changes, skips = build_changes(feeds, prefixes, overrides)
    duplicates = find_duplicate_names(feeds, changes)
    print_report(changes, skips, duplicates)

    if not changes:
        print("\nNo changes. Nothing to do.")
        return 0

    apply_changes(data, changes)
    after_text = dump_config(data)
    # Verification runs before the write, so a dry run catches problems too.
    try:
        verify_text(before_text, after_text, changes)
    except VerificationError as exc:
        print(f"\nERROR: verification failed: {exc}", file=sys.stderr)
        return 1

    if not args.apply:
        print("\n[DRY RUN] No changes written. Re-run with --apply to write.")
        return 0

    write_config(args.config, after_text, backup=not args.no_backup)
    try:
        verify_on_disk(args.config, before_text, changes)
    except VerificationError as exc:
        print(f"\nERROR: post-write verification failed: {exc}", file=sys.stderr)
        return 1
    print(f"\nWrote {len(changes)} change(s) to {args.config}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Create the committed override file**

Create `feed_name_overrides.csv`:

```csv
feed_id,name
3339,GIGADEVICE SEMICONDUCTOR INC (CN)
3341,MONTAGE TECHNOLOGY CO LTD (CN)
3358,MONTAGE TECHNOLOGY CO LTD (HK)
3360,GIGADEVICE SEMICONDUCTOR INC (HK)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_rename_numeric_feed_names.py -v`
Expected: PASS — 61 passed

- [ ] **Step 6: Commit**

```bash
pre-commit run --files rename_numeric_feed_names.py tests/test_rename_numeric_feed_names.py feed_name_overrides.csv
git add rename_numeric_feed_names.py tests/test_rename_numeric_feed_names.py feed_name_overrides.csv
git commit -m "feat(rename-names): CLI, reporting and committed override file"
```

---

### Task 6: Real-data smoke test and documentation

**Files:**

- Test: `tests/test_rename_numeric_feed_names.py` (append)
- Create: `docs/rename_numeric_feed_names.md`
- Modify: `CLAUDE.md` (Scripts table)

**Interfaces:**

- Consumes: `build_changes`, `find_duplicate_names`, `load_overrides` from Tasks 2–3
- Produces: nothing consumed by later tasks

- [ ] **Step 1: Write the smoke test**

Append to `tests/test_rename_numeric_feed_names.py` (add `from pathlib import Path` at the top):

```python
from pathlib import Path

LIVE_CONFIG = Path("lazer-state.json")


@pytest.mark.skipif(
    not LIVE_CONFIG.exists(),
    reason="lazer-state.json is gitignored and not present in this checkout",
)
class TestLiveConfigSmoke:
    """Guards the measured expectations from the design doc.

    The config is gitignored, so these are skipped wherever it is absent.
    """

    def _feeds(self):
        return json.loads(LIVE_CONFIG.read_text(encoding="utf-8"))["feeds"]

    def test_452_changes_no_skips(self):
        changes, skips = build_changes(self._feeds())
        assert len(changes) == 452
        assert skips == []

    def test_two_duplicate_warnings_without_overrides(self):
        feeds = self._feeds()
        changes, _ = build_changes(feeds)
        duplicates = find_duplicate_names(feeds, changes)
        assert [name for name, _ in duplicates] == [
            "GIGADEVICE SEMICONDUCTOR INC",
            "MONTAGE TECHNOLOGY CO LTD",
        ]

    def test_no_duplicates_with_committed_overrides(self):
        feeds = self._feeds()
        overrides = load_overrides(Path("feed_name_overrides.csv"))
        changes, _ = build_changes(feeds, overrides=overrides)
        assert find_duplicate_names(feeds, changes) == []

    def test_feed_3520_gets_company_name(self):
        changes, _ = build_changes(self._feeds())
        by_id = {c.feed_id: c for c in changes}
        assert by_id[3520].before == "688825"
        assert by_id[3520].after == "CHANGXIN MEMORY TECHNOLOGIES"
```

- [ ] **Step 2: Run the full suite**

Run: `pytest tests/test_rename_numeric_feed_names.py -v`
Expected: PASS — 65 passed (or 61 passed, 4 skipped if `lazer-state.json` is absent)

- [ ] **Step 3: Run the real dry run and confirm the numbers**

Run:

```bash
python3 rename_numeric_feed_names.py --config lazer-state.json --name-overrides feed_name_overrides.csv
```

Expected: `Summary: 452 change(s), 0 skip(s), 0 duplicate-name warning(s).` followed by `[DRY RUN] No changes written.` Confirm the file is unmodified with `git status` (it is gitignored, so check the mtime or re-run and compare output).

- [ ] **Step 4: Write the per-script doc**

Create `docs/rename_numeric_feed_names.md`:

````markdown
# Numeric Feed Name Rename (rename_numeric_feed_names.py)

Replaces the purely numeric `metadata.name` on Hong Kong, Japan, South Korea and mainland China equity feeds with the company name, derived from `metadata.description` minus its spelled-out currency suffix.

Those exchanges issue numeric instrument codes rather than alphabetic tickers, so `metadata.name` reads as `688825` instead of `CHANGXIN MEMORY TECHNOLOGIES`. The exchange code is never lost — it stays in `symbol` (`Equity.CN.688825/CNY`) — and `metadata.description` is never modified.

## Usage

```bash
# Dry run (default) — preview every change
python3 rename_numeric_feed_names.py --config lazer-state.json

# Apply, with the committed disambiguation overrides
python3 rename_numeric_feed_names.py --config lazer-state.json \
    --name-overrides feed_name_overrides.csv --apply

# Narrow to one market
python3 rename_numeric_feed_names.py --config lazer-state.json \
    --symbol-prefix Equity.JP.
```
````

## Arguments

| Argument           | Description                                | Required | Default                                                |
| ------------------ | ------------------------------------------ | -------- | ------------------------------------------------------ |
| `--config`         | Path to the Lazer config JSON              | Yes      | —                                                      |
| `--symbol-prefix`  | Symbol namespace to process; repeatable    | No       | `Equity.HK.`, `Equity.JP.`, `Equity.KR.`, `Equity.CN.` |
| `--name-overrides` | CSV of hand-curated names (`feed_id,name`) | No       | —                                                      |
| `--apply`          | Write changes (otherwise dry run)          | No       | False                                                  |
| `--no-backup`      | Skip the `<config>.bak` copy               | No       | False                                                  |

## Selection Rule

A feed is renamed when all three hold:

1. Its `symbol` starts with a configured prefix.
2. Its `metadata.name` matches `^[0-9]+[A-Za-z]?$`.
3. Its `metadata.description` splits on `" / "` with a tail matching the feed's `quote_currency`.

Condition 2 makes the script idempotent — once renamed, a feed stops matching, so re-running is a no-op. This matters because most affected feeds are `COMING_SOON` and go live over time.

| quote_currency | Expected description tail |
| -------------- | ------------------------- |
| CNY            | `CHINESE YUAN`            |
| HKD            | `HONG KONG DOLLAR`        |
| JPY            | `JAPANESE YEN`            |
| KRW            | `SOUTH KOREAN WON`        |

A feed whose tail does not match, whose currency is unmapped, or whose derived name is empty is **skipped and reported** — never written with a mangled value.

## Override File

`feed_name_overrides.csv` pins names by hand. It takes precedence over the rule and bypasses the currency check.

```csv
feed_id,name
3339,GIGADEVICE SEMICONDUCTOR INC (CN)
3360,GIGADEVICE SEMICONDUCTOR INC (HK)
```

Use it for short codes where one genuinely exists (`3520,CXMT`) and to disambiguate dual listings. An override may target any in-scope feed, including one already renamed, so a code can be pinned after the bulk run.

The file must be passed explicitly with `--name-overrides`; there is no implicit default path.

## Duplicate Names

Two same-issuer dual listings derive identical names (GigaDevice and Montage, each listed in both Shanghai and Hong Kong). The script prints a warning naming every feed involved and still writes — `metadata.name` is already non-unique across the config. Adding override rows clears the warning.

## Safety

- Dry run is the default; `--apply` writes.
- The config is backed up to `<config>.bak` first, unless `--no-backup`.
- Serialization is byte-identical to the stored format, so only the changed `"name":` lines differ.
- Before writing (and again after), the script asserts that every differing line is an expected `"name":` line, that the file parses, and that the feed count is unchanged. Anything else aborts with exit code 1.

## Tests

```bash
pytest tests/test_rename_numeric_feed_names.py -v
```

The real-data smoke tests skip automatically when `lazer-state.json` is absent, since config files are gitignored.

See `docs/superpowers/specs/2026-07-28-numeric-feed-name-rename-design.md` for the full design and the measurements behind it.

````

- [ ] **Step 5: Add the CLAUDE.md Scripts table row**

In `CLAUDE.md`, insert this row into the Scripts table immediately after the `update_min_publishers.py` row:

```markdown
| `rename_numeric_feed_names.py`          | Replace numeric `metadata.name` with company names for HK/JP/KR/CN equity feeds (override CSV for short codes)                                                                     | `python3 rename_numeric_feed_names.py --config lazer-state.json --name-overrides feed_name_overrides.csv` | [docs/rename_numeric_feed_names.md](docs/rename_numeric_feed_names.md)   |
````

- [ ] **Step 6: Commit**

```bash
pre-commit run --files tests/test_rename_numeric_feed_names.py docs/rename_numeric_feed_names.md CLAUDE.md
git add tests/test_rename_numeric_feed_names.py docs/rename_numeric_feed_names.md CLAUDE.md
git commit -m "docs(rename-names): per-script doc, smoke tests and Scripts table row"
```

---

## Definition of Done

- [ ] `pytest tests/test_rename_numeric_feed_names.py -v` passes (65 tests with the config present).
- [ ] Dry run against `lazer-state.json` reports 452 changes, 0 skips.
- [ ] With `--name-overrides feed_name_overrides.csv`, 0 duplicate-name warnings.
- [ ] Feed 3520 becomes `CHANGXIN MEMORY TECHNOLOGIES`.
- [ ] `feed_name_overrides.csv` committed with the 4 disambiguation rows.
- [ ] `docs/rename_numeric_feed_names.md` written; CLAUDE.md Scripts table updated.
- [ ] `pre-commit run --files <changed files>` passes on every commit.
