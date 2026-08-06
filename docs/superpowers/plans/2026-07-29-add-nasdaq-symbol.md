# add_nasdaq_symbol Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Backfill `metadata.nasdaq_symbol = metadata.name` (verbatim) for every HK/CN/JP/KR/IN equity feed in `lazer_jpkr.json`, before `rename_numeric_feed_names.py` ever overwrites `metadata.name` with a display name.

**Architecture:** One standalone script, `add_nasdaq_symbol.py`, mirroring the existing `rename_numeric_feed_names.py` conventions: dry-run by default, `--apply` to write, `.bak` backup, JSON-aware before/after verification. Reuses `in_scope`, `dump_config`, and `write_config` from `rename_numeric_feed_names.py` rather than re-implementing them.

**Tech Stack:** Python 3 standard library only (`argparse`, `json`, `dataclasses`, `pathlib`) — no new dependencies.

## Global Constraints

- Target config: `lazer_jpkr.json` only (per spec scope — not `lazer-state.json`, `lazer_new.json`, `lazer_newest.json`, `lazer_to_modify.json`, or `state.json`).
- Default symbol prefixes: `Equity.HK.`, `Equity.CN.`, `Equity.JP.`, `Equity.KR.`, `Equity.IN.` (a new tuple, distinct from `rename_numeric_feed_names.MARKET_PREFIXES`, which excludes IN).
- Copy is verbatim — no transformation of the value.
- Skip (never overwrite) a feed that already has `metadata.nasdaq_symbol` set — idempotent re-run.
- Skip (don't guess) a feed whose `metadata.name` does not match the exchange code embedded in `symbol` — that code segment is never touched by `rename_numeric_feed_names.py`, so a mismatch means the feed has already been renamed; report it, don't touch it.
- `metadata` dict keys are rebuilt in alphabetical order whenever `nasdaq_symbol` is added, matching the existing convention observed on US-equity feeds and every other metadata dict in the config.
- Dry run is the default for `--apply`-gated scripts in this repo; never write without `--apply`.
- Per CLAUDE.md, the repo-root `pytest -q` fails on a pre-existing conftest clash — this suite is always run standalone: `pytest tests/test_add_nasdaq_symbol.py -v`.
- Run `pre-commit run --files <changed files>` before every commit.

---

## File Structure

- **Create:** `add_nasdaq_symbol.py` (repo root) — the whole implementation: dataclasses, scope/decision logic, apply, verification, CLI. Small and single-purpose, like its siblings; no reason to split further.
- **Create:** `tests/test_add_nasdaq_symbol.py` — fixture-based unit tests, plus a `lazer_jpkr.json`-gated live smoke test (skipped when that gitignored file is absent), mirroring `tests/test_rename_numeric_feed_names.py`'s `TestLiveConfigSmoke` pattern.
- **Create:** `docs/add_nasdaq_symbol.md` — usage doc, same shape as `docs/generate_short_name_candidates.md`.
- **Modify:** `CLAUDE.md` — add a row to the Scripts table.

---

### Task 1: Scope and per-feed decision logic

**Files:**

- Create: `add_nasdaq_symbol.py`
- Test: `tests/test_add_nasdaq_symbol.py`

**Interfaces:**

- Consumes: `in_scope(feed, prefixes)` from `rename_numeric_feed_names` (existing, unchanged signature: `(feed: dict, prefixes: tuple[str, ...]) -> bool`).
- Produces: `ASIAN_MARKET_PREFIXES: tuple[str, ...]`, `Change` (fields: `feed_id: int`, `symbol: str`, `name: str` — `name` is the value being copied into `nasdaq_symbol`), `Skip` (fields: `feed_id: int`, `symbol: str`, `reason: str`), `plan_change(feed: dict) -> tuple[Change | None, Skip | None]`, `build_changes(feeds: list[dict], prefixes: tuple[str, ...] = ASIAN_MARKET_PREFIXES) -> tuple[list[Change], list[Skip]]`. Later tasks call `build_changes` and consume `Change.feed_id` / `Change.name`.

- [ ] **Step 1: Write the failing tests for `plan_change`**

Create `tests/test_add_nasdaq_symbol.py` with this content:

```python
"""Tests for add_nasdaq_symbol.py."""

from add_nasdaq_symbol import (
    ASIAN_MARKET_PREFIXES,
    Change,
    Skip,
    build_changes,
    plan_change,
)


def _feed(
    feed_id=100,
    symbol="Equity.CN.688825/CNY",
    name="688825",
    nasdaq_symbol=None,
):
    """Build a minimal feed dict shaped like a lazer_jpkr.json entry."""
    metadata = {
        "asset_type": "equity",
        "description": "CHANGXIN MEMORY TECHNOLOGIES / CHINESE YUAN",
        "name": name,
        "quote_currency": "CNY",
    }
    if nasdaq_symbol is not None:
        metadata["nasdaq_symbol"] = nasdaq_symbol
    return {"feedId": feed_id, "symbol": symbol, "state": "STABLE", "metadata": metadata}


class TestAsianMarketPrefixes:
    def test_includes_all_five_markets(self):
        assert ASIAN_MARKET_PREFIXES == (
            "Equity.HK.",
            "Equity.CN.",
            "Equity.JP.",
            "Equity.KR.",
            "Equity.IN.",
        )


class TestPlanChange:
    def test_numeric_name_becomes_change(self):
        change, skip = plan_change(_feed())
        assert skip is None
        assert change == Change(feed_id=100, symbol="Equity.CN.688825/CNY", name="688825")

    def test_alphanumeric_code_becomes_change(self):
        change, skip = plan_change(
            _feed(symbol="Equity.IN.NIFTYBEES/INR", name="NIFTYBEES")
        )
        assert skip is None
        assert change.name == "NIFTYBEES"

    def test_hyphenated_code_becomes_change(self):
        change, skip = plan_change(
            _feed(symbol="Equity.JP.1321-JP/JPY", name="1321-JP")
        )
        assert skip is None
        assert change.name == "1321-JP"

    def test_already_set_is_skipped(self):
        change, skip = plan_change(_feed(nasdaq_symbol="688825"))
        assert change is None
        assert skip == Skip(
            feed_id=100,
            symbol="Equity.CN.688825/CNY",
            reason="nasdaq_symbol already set",
        )

    def test_already_set_is_skipped_even_if_stale(self):
        # Even a mismatched existing value is left alone -- idempotent, not "fix on rerun".
        change, skip = plan_change(_feed(nasdaq_symbol="WRONG"))
        assert change is None
        assert skip.reason == "nasdaq_symbol already set"

    def test_empty_name_is_skipped(self):
        change, skip = plan_change(_feed(name=""))
        assert change is None
        assert "metadata.name is empty" in skip.reason

    def test_name_with_space_is_skipped(self):
        change, skip = plan_change(_feed(name="CHANGXIN MEMORY TECHNOLOGIES"))
        assert change is None
        assert "does not match symbol code" in skip.reason

    def test_name_with_internal_space_is_skipped(self):
        change, skip = plan_change(_feed(name="GIGADEVICE SEMICONDUCTOR INC (CN)"))
        assert change is None
        assert "does not match symbol code" in skip.reason

    def test_single_word_display_name_is_still_skipped(self):
        # Regression: a whitespace-only check would wrongly accept this.
        change, skip = plan_change(
            _feed(symbol="Equity.JP.6501/JPY", name="HITACHI")
        )
        assert change is None
        assert "does not match symbol code" in skip.reason


class TestBuildChanges:
    def test_in_scope_cn_feed_produces_change(self):
        changes, skips = build_changes([_feed(feed_id=3520)])
        assert skips == []
        assert changes == [
            Change(feed_id=3520, symbol="Equity.CN.688825/CNY", name="688825")
        ]

    def test_default_scope_includes_india(self):
        feed = _feed(feed_id=3363, symbol="Equity.IN.NIFTYBEES/INR", name="NIFTYBEES")
        changes, skips = build_changes([feed])
        assert skips == []
        assert changes == [
            Change(feed_id=3363, symbol="Equity.IN.NIFTYBEES/INR", name="NIFTYBEES")
        ]

    def test_out_of_scope_feed_untouched(self):
        feeds = [_feed(feed_id=922, symbol="Equity.US.AAPL/USD", name="AAPL")]
        changes, skips = build_changes(feeds)
        assert changes == []
        assert skips == []

    def test_custom_prefixes_narrow_scope(self):
        feeds = [
            _feed(feed_id=3520),
            _feed(feed_id=884, symbol="Equity.HK.0002/HKD", name="0002"),
        ]
        changes, _ = build_changes(feeds, prefixes=("Equity.HK.",))
        assert [c.feed_id for c in changes] == [884]

    def test_mixed_changes_and_skips(self):
        feeds = [
            _feed(feed_id=3520),
            _feed(feed_id=3521, name="ALREADY MULTI WORD"),
        ]
        changes, skips = build_changes(feeds)
        assert [c.feed_id for c in changes] == [3520]
        assert [s.feed_id for s in skips] == [3521]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_add_nasdaq_symbol.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'add_nasdaq_symbol'`

- [ ] **Step 3: Write the implementation**

Create `add_nasdaq_symbol.py`:

```python
#!/usr/bin/env python3
"""Backfill metadata.nasdaq_symbol for HK/CN/JP/KR/IN equity feeds.

These markets carry the exchange-facing identifier downstream users read
prices by in `metadata.name` -- a numeric code for HK/CN/JP/KR, or the raw
ticker for the few already-alphabetic names. `rename_numeric_feed_names.py`
later overwrites `metadata.name` with a human-readable company name, so this
script copies the original identifier into `metadata.nasdaq_symbol` first,
verbatim, while it still holds the original code.

See docs/superpowers/specs/2026-07-29-add-nasdaq-symbol-design.md.
"""

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from rename_numeric_feed_names import dump_config, in_scope, write_config

ASIAN_MARKET_PREFIXES = (
    "Equity.HK.",
    "Equity.CN.",
    "Equity.JP.",
    "Equity.KR.",
    "Equity.IN.",
)


def _symbol_code(symbol: str) -> str:
    """Extract the exchange code/ticker segment from `symbol`.

    E.g. 'Equity.HK.0002/HKD' -> '0002', 'Equity.JP.1321-JP/JPY' -> '1321-JP'.
    This segment is never touched by rename_numeric_feed_names.py, unlike
    metadata.name, so comparing against it is an exact check for whether a
    feed has already been renamed -- not a heuristic.
    """
    root = symbol.split("/", 1)[0]
    return root.rsplit(".", 1)[-1]


@dataclass(frozen=True)
class Change:
    """One planned `metadata.nasdaq_symbol` addition."""

    feed_id: int
    symbol: str
    name: str  # value to copy into nasdaq_symbol


@dataclass(frozen=True)
class Skip:
    """A feed that was not touched, with the reason why."""

    feed_id: int
    symbol: str
    reason: str


def plan_change(feed: dict) -> tuple[Change | None, Skip | None]:
    """Decide what to do with one in-scope feed.

    Skips (never overwrites) a feed that already has `nasdaq_symbol` set, so
    a second run is a no-op. Compares metadata.name against the code embedded
    in symbol, which rename_numeric_feed_names.py never touches -- an exact
    check for whether this feed has already been renamed, rather than a
    heuristic. A mismatch (not just a name containing whitespace) triggers
    the skip, since some already-renamed display names are a single word
    (e.g. `HITACHI`, `CNOOC`) and would slip past a whitespace-only check.
    """
    feed_id = feed["feedId"]
    symbol = feed.get("symbol", "")
    metadata = feed.get("metadata", {})

    if "nasdaq_symbol" in metadata:
        return None, Skip(feed_id, symbol, "nasdaq_symbol already set")

    name = str(metadata.get("name") or "")
    if not name:
        return None, Skip(feed_id, symbol, "metadata.name is empty")

    code = _symbol_code(symbol)
    if name != code:
        return None, Skip(
            feed_id,
            symbol,
            f"metadata.name {name!r} does not match symbol code {code!r} (already renamed?)",
        )

    return Change(feed_id, symbol, name), None


def build_changes(
    feeds: list[dict], prefixes: tuple[str, ...] = ASIAN_MARKET_PREFIXES
) -> tuple[list[Change], list[Skip]]:
    """Plan the nasdaq_symbol backfill over every in-scope feed."""
    changes: list[Change] = []
    skips: list[Skip] = []
    for feed in feeds:
        if not in_scope(feed, prefixes):
            continue
        change, skip = plan_change(feed)
        if change is not None:
            changes.append(change)
        if skip is not None:
            skips.append(skip)
    return changes, skips
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_add_nasdaq_symbol.py -v`
Expected: PASS (all tests in `TestAsianMarketPrefixes`, `TestPlanChange`, `TestBuildChanges`)

- [ ] **Step 5: Commit**

```bash
git add add_nasdaq_symbol.py tests/test_add_nasdaq_symbol.py
git commit -m "feat: add scope and decision logic for add_nasdaq_symbol"
```

---

### Task 2: Apply changes with alphabetical key ordering

**Files:**

- Modify: `add_nasdaq_symbol.py`
- Modify: `tests/test_add_nasdaq_symbol.py`

**Interfaces:**

- Consumes: `Change` from Task 1 (`feed_id`, `symbol`, `name`).
- Produces: `apply_changes(data: dict, changes: list[Change]) -> None` (mutates `data["feeds"]` in place). Later tasks call this before dumping/writing the config.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_add_nasdaq_symbol.py`:

```python
from add_nasdaq_symbol import apply_changes


def _config(*feeds):
    return {"feeds": list(feeds)}


class TestApplyChanges:
    def test_sets_nasdaq_symbol(self):
        data = _config(_feed(feed_id=3520))
        changes, _ = build_changes(data["feeds"])
        apply_changes(data, changes)
        assert data["feeds"][0]["metadata"]["nasdaq_symbol"] == "688825"

    def test_other_fields_untouched(self):
        data = _config(_feed(feed_id=3520))
        changes, _ = build_changes(data["feeds"])
        apply_changes(data, changes)
        metadata = data["feeds"][0]["metadata"]
        assert metadata["name"] == "688825"
        assert metadata["description"] == "CHANGXIN MEMORY TECHNOLOGIES / CHINESE YUAN"
        assert metadata["quote_currency"] == "CNY"

    def test_symbol_untouched(self):
        data = _config(_feed(feed_id=3520))
        changes, _ = build_changes(data["feeds"])
        apply_changes(data, changes)
        assert data["feeds"][0]["symbol"] == "Equity.CN.688825/CNY"

    def test_metadata_keys_are_alphabetically_sorted(self):
        data = _config(_feed(feed_id=3520))
        changes, _ = build_changes(data["feeds"])
        apply_changes(data, changes)
        keys = list(data["feeds"][0]["metadata"].keys())
        assert keys == sorted(keys)
        assert keys == [
            "asset_type",
            "description",
            "name",
            "nasdaq_symbol",
            "quote_currency",
        ]

    def test_untouched_feed_not_mutated(self):
        data = _config(
            _feed(feed_id=3520),
            _feed(feed_id=922, symbol="Equity.US.AAPL/USD", name="AAPL"),
        )
        changes, _ = build_changes(data["feeds"])
        apply_changes(data, changes)
        assert "nasdaq_symbol" not in data["feeds"][1]["metadata"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_add_nasdaq_symbol.py -v`
Expected: FAIL with `ImportError: cannot import name 'apply_changes'`

- [ ] **Step 3: Write the implementation**

Add to `add_nasdaq_symbol.py` (after `build_changes`):

```python
def _with_sorted_keys(metadata: dict, key: str, value: str) -> dict:
    """Return a new dict with `key` set to `value`, all keys alphabetically sorted.

    Every metadata dict in this config is already alphabetically sorted (verified
    against both HK and US-equity feeds), and on US feeds `nasdaq_symbol` already
    sits between `name` and `quote_currency`. This keeps newly-touched feeds
    consistent with that existing convention instead of appending the new key
    at the end via plain dict assignment.
    """
    merged = {**metadata, key: value}
    return dict(sorted(merged.items()))


def apply_changes(data: dict, changes: list[Change]) -> None:
    """Write the planned nasdaq_symbol values into the in-memory document."""
    by_id = {f["feedId"]: f for f in data["feeds"]}
    for change in changes:
        feed = by_id[change.feed_id]
        feed["metadata"] = _with_sorted_keys(
            feed["metadata"], "nasdaq_symbol", change.name
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_add_nasdaq_symbol.py -v`
Expected: PASS (all tests in `TestApplyChanges`, plus everything from Task 1 still passing)

- [ ] **Step 5: Commit**

```bash
git add add_nasdaq_symbol.py tests/test_add_nasdaq_symbol.py
git commit -m "feat: apply nasdaq_symbol changes with sorted metadata keys"
```

---

### Task 3: JSON-aware verification

**Files:**

- Modify: `add_nasdaq_symbol.py`
- Modify: `tests/test_add_nasdaq_symbol.py`

**Interfaces:**

- Consumes: `Change` from Task 1, `apply_changes` from Task 2, `dump_config`/`write_config` from `rename_numeric_feed_names` (existing: `dump_config(data: dict) -> str`, `write_config(path: Path, text: str, backup: bool = True) -> None`).
- Produces: `VerificationError(Exception)`, `verify_feed_metadata(before_data: dict, after_data: dict, changes: list[Change]) -> None` (raises on mismatch), `verify_on_disk(path: Path, before_text: str, changes: list[Change]) -> None`. Task 4's `main()` calls both.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_add_nasdaq_symbol.py`:

```python
import json

import pytest

from add_nasdaq_symbol import VerificationError, verify_feed_metadata, verify_on_disk
from rename_numeric_feed_names import dump_config, write_config


class TestVerifyFeedMetadata:
    def test_passes_on_planned_change(self):
        before_data = _config(_feed(feed_id=3520))
        after_data = _config(_feed(feed_id=3520))
        changes, _ = build_changes(before_data["feeds"])
        apply_changes(after_data, changes)
        verify_feed_metadata(before_data, after_data, changes)

    def test_rejects_feed_id_set_change(self):
        before_data = _config(
            _feed(feed_id=3520),
            _feed(feed_id=884, symbol="Equity.HK.0002/HKD", name="0002"),
        )
        after_data = _config(_feed(feed_id=3520))
        with pytest.raises(VerificationError, match="feed id set changed"):
            verify_feed_metadata(before_data, after_data, changes=[])

    def test_rejects_unplanned_metadata_change(self):
        before_data = _config(_feed(feed_id=3520))
        after_data = _config(_feed(feed_id=3520))
        after_data["feeds"][0]["metadata"]["name"] = "TAMPERED"
        with pytest.raises(VerificationError, match="had no planned change"):
            verify_feed_metadata(before_data, after_data, changes=[])

    def test_rejects_wrong_nasdaq_symbol_value(self):
        before_data = _config(_feed(feed_id=3520))
        after_data = _config(_feed(feed_id=3520, nasdaq_symbol="WRONG"))
        changes, _ = build_changes(before_data["feeds"])
        with pytest.raises(VerificationError, match="does not match the plan"):
            verify_feed_metadata(before_data, after_data, changes)

    def test_rejects_change_leaking_to_unplanned_feed(self):
        before_data = _config(
            _feed(feed_id=3520),
            _feed(feed_id=884, symbol="Equity.HK.0002/HKD", name="0002"),
        )
        after_data = _config(
            # feed 3520 correctly matches the plan, so it isn't what trips the check.
            _feed(feed_id=3520, nasdaq_symbol="688825"),
            _feed(
                feed_id=884,
                symbol="Equity.HK.0002/HKD",
                name="0002",
                nasdaq_symbol="0002",
            ),
        )
        # Plan only covers CN, so the HK feed gaining nasdaq_symbol is unplanned.
        changes, _ = build_changes(before_data["feeds"], prefixes=("Equity.CN.",))
        with pytest.raises(VerificationError, match="had no planned change"):
            verify_feed_metadata(before_data, after_data, changes)


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
        before_text = dump_config(_config(_feed(feed_id=3520)))
        with pytest.raises(VerificationError, match="does not parse"):
            verify_on_disk(path, before_text, [])

    def test_rejects_feed_count_change(self, tmp_path):
        before_data = _config(
            _feed(feed_id=3520),
            _feed(feed_id=884, symbol="Equity.HK.0002/HKD", name="0002"),
        )
        before_text = dump_config(before_data)
        path = tmp_path / "cfg.json"
        path.write_text(dump_config(_config(_feed(feed_id=3520))), encoding="utf-8")
        with pytest.raises(VerificationError, match="feed count changed"):
            verify_on_disk(path, before_text, [])
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_add_nasdaq_symbol.py -v`
Expected: FAIL with `ImportError: cannot import name 'VerificationError'`

- [ ] **Step 3: Write the implementation**

Add to `add_nasdaq_symbol.py` (after `apply_changes`):

```python
class VerificationError(Exception):
    """Raised when the rewritten config differs in unexpected ways."""


def verify_feed_metadata(
    before_data: dict, after_data: dict, changes: list[Change]
) -> None:
    """Raise VerificationError unless exactly the planned nasdaq_symbol values changed.

    Confirms every feed outside the change set has a byte-identical `metadata`
    dict to before (no leak beyond the plan), and every feed in the change set
    gained exactly the planned `nasdaq_symbol` value with every other field
    unchanged.
    """
    before_by_id = {f["feedId"]: f for f in before_data["feeds"]}
    after_by_id = {f["feedId"]: f for f in after_data["feeds"]}
    if before_by_id.keys() != after_by_id.keys():
        raise VerificationError("feed id set changed")

    planned = {c.feed_id: c.name for c in changes}
    for feed_id, before_feed in before_by_id.items():
        before_metadata = before_feed.get("metadata", {})
        after_metadata = after_by_id[feed_id].get("metadata", {})

        if feed_id not in planned:
            if before_metadata != after_metadata:
                raise VerificationError(
                    f"feed {feed_id} metadata changed but had no planned change: "
                    f"before={before_metadata}, after={after_metadata}"
                )
            continue

        expected = dict(sorted({**before_metadata, "nasdaq_symbol": planned[feed_id]}.items()))
        if after_metadata != expected:
            raise VerificationError(
                f"feed {feed_id} metadata does not match the plan: "
                f"expected={expected}, actual={after_metadata}"
            )


def verify_on_disk(path: Path, before_text: str, changes: list[Change]) -> None:
    """Re-read the written config and confirm it parses and changed only as planned."""
    after_text = path.read_text(encoding="utf-8")
    try:
        after_data = json.loads(after_text)
    except json.JSONDecodeError as exc:
        raise VerificationError(f"written config does not parse: {exc}") from exc
    before_data = json.loads(before_text)
    if len(after_data["feeds"]) != len(before_data["feeds"]):
        raise VerificationError(
            f"feed count changed: {len(before_data['feeds'])} -> {len(after_data['feeds'])}"
        )
    verify_feed_metadata(before_data, after_data, changes)
```

Add `import json` to the top of `add_nasdaq_symbol.py` if not already present from a later task (it is added here for the first time).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_add_nasdaq_symbol.py -v`
Expected: PASS (all tests in `TestVerifyFeedMetadata`, `TestVerifyOnDisk`, plus everything from Tasks 1-2 still passing)

- [ ] **Step 5: Commit**

```bash
git add add_nasdaq_symbol.py tests/test_add_nasdaq_symbol.py
git commit -m "feat: add JSON-aware verification for nasdaq_symbol changes"
```

---

### Task 4: CLI wiring (main, report, dry-run/--apply)

**Files:**

- Modify: `add_nasdaq_symbol.py`
- Modify: `tests/test_add_nasdaq_symbol.py`

**Interfaces:**

- Consumes: `build_changes`, `apply_changes`, `verify_feed_metadata`, `verify_on_disk`, `VerificationError`, `ASIAN_MARKET_PREFIXES` (all from Tasks 1-3), `dump_config`/`write_config` (from `rename_numeric_feed_names`).
- Produces: `print_report(changes: list[Change], skips: list[Skip]) -> None`, `main(argv: list[str] | None = None) -> int`. This is the last task — nothing downstream consumes these except the CLI entry point (`if __name__ == "__main__": sys.exit(main())`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_add_nasdaq_symbol.py`:

```python
from add_nasdaq_symbol import main


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
        assert written["feeds"][0]["metadata"]["nasdaq_symbol"] == "688825"
        assert (tmp_path / "cfg.json.bak").exists()

    def test_second_run_is_a_noop(self, tmp_path, capsys):
        path = _write_config(tmp_path, _feed(feed_id=3520))
        main(["--config", str(path), "--apply"])
        capsys.readouterr()
        assert main(["--config", str(path), "--apply"]) == 0
        assert "No changes" in capsys.readouterr().out

    def test_symbol_prefix_narrows_scope(self, tmp_path):
        path = _write_config(
            tmp_path,
            _feed(feed_id=3520),
            _feed(feed_id=884, symbol="Equity.HK.0002/HKD", name="0002"),
        )
        assert (
            main(["--config", str(path), "--symbol-prefix", "Equity.HK.", "--apply"])
            == 0
        )
        written = json.loads(path.read_text(encoding="utf-8"))
        assert "nasdaq_symbol" not in written["feeds"][0]["metadata"]
        assert written["feeds"][1]["metadata"]["nasdaq_symbol"] == "0002"

    def test_missing_config_file_errors_cleanly(self, tmp_path, capsys):
        missing = tmp_path / "nope.json"
        assert main(["--config", str(missing)]) == 1
        err = capsys.readouterr().err
        assert "ERROR: Config file not found" in err
        assert str(missing) in err

    def test_no_backup_flag(self, tmp_path):
        path = _write_config(tmp_path, _feed(feed_id=3520))
        assert main(["--config", str(path), "--apply", "--no-backup"]) == 0
        assert not (tmp_path / "cfg.json.bak").exists()

    def test_skip_reasons_are_reported(self, tmp_path, capsys):
        path = _write_config(
            tmp_path,
            _feed(feed_id=3520, name="ALREADY MULTI WORD"),
        )
        assert main(["--config", str(path)]) == 0
        out = capsys.readouterr().out
        assert "Skipped (1)" in out
        assert "does not match symbol code" in out

    def test_pre_write_verification_failure_writes_nothing(self, tmp_path, monkeypatch):
        path = _write_config(tmp_path, _feed(feed_id=3520))
        original = path.read_text(encoding="utf-8")

        def _boom(*args, **kwargs):
            raise VerificationError("boom")

        monkeypatch.setattr("add_nasdaq_symbol.verify_feed_metadata", _boom)
        assert main(["--config", str(path), "--apply"]) == 1
        assert path.read_text(encoding="utf-8") == original
        assert not (tmp_path / "cfg.json.bak").exists()

    def test_post_write_verification_failure_leaves_backup(self, tmp_path, monkeypatch):
        path = _write_config(tmp_path, _feed(feed_id=3520))
        original = path.read_text(encoding="utf-8")

        def _boom(*args, **kwargs):
            raise VerificationError("boom")

        monkeypatch.setattr("add_nasdaq_symbol.verify_on_disk", _boom)
        assert main(["--config", str(path), "--apply"]) == 1
        assert (tmp_path / "cfg.json.bak").exists()
        assert (tmp_path / "cfg.json.bak").read_text(encoding="utf-8") == original
```

Note: `VerificationError` is already imported in the test file from Task 3.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest tests/test_add_nasdaq_symbol.py -v`
Expected: FAIL with `ImportError: cannot import name 'main'`

- [ ] **Step 3: Write the implementation**

Add to `add_nasdaq_symbol.py` (after `verify_on_disk`), and add `import argparse` and `import sys` to the top of the file if not already present (they are added here for the first time):

```python
def print_report(changes: list[Change], skips: list[Skip]) -> None:
    """Print the change table, skip list, and summary."""
    if changes:
        width = max(len(c.symbol) for c in changes)
        print(f"\nChanges ({len(changes)}):")
        for change in changes:
            print(
                f"  {change.feed_id:5d}  {change.symbol:<{width}}  "
                f"nasdaq_symbol -> {change.name!r}"
            )
    if skips:
        print(f"\nSkipped ({len(skips)}):")
        for skip in skips:
            print(f"  {skip.feed_id:5d}  {skip.symbol}  {skip.reason}")
    print(f"\nSummary: {len(changes)} change(s), {len(skips)} skip(s).")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="Path to the config")
    parser.add_argument(
        "--symbol-prefix",
        action="append",
        dest="symbol_prefixes",
        help=(
            "Symbol namespace to process; repeatable. Defaults to "
            f"{', '.join(ASIAN_MARKET_PREFIXES)}"
        ),
    )
    parser.add_argument("--apply", action="store_true", help="Write changes")
    parser.add_argument("--no-backup", action="store_true", help="Skip the .bak copy")
    args = parser.parse_args(argv)

    prefixes = (
        tuple(args.symbol_prefixes) if args.symbol_prefixes else ASIAN_MARKET_PREFIXES
    )

    if not args.config.exists():
        print(f"ERROR: Config file not found: {args.config}", file=sys.stderr)
        return 1

    before_text = args.config.read_text(encoding="utf-8")
    data = json.loads(before_text)
    feeds = data["feeds"]
    print(f"Reading {args.config} ({len(feeds)} feeds)...")

    changes, skips = build_changes(feeds, prefixes)
    print_report(changes, skips)

    if not changes:
        print("\nNo changes. Nothing to do.")
        return 0

    apply_changes(data, changes)
    trailing = before_text[len(before_text.rstrip("\n")) :]
    after_text = dump_config(data) + trailing

    try:
        verify_feed_metadata(json.loads(before_text), data, changes)
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

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest tests/test_add_nasdaq_symbol.py -v`
Expected: PASS (all tests in `TestMain`, plus everything from Tasks 1-3 still passing — full suite green)

- [ ] **Step 5: Run pre-commit and commit**

```bash
pre-commit run --files add_nasdaq_symbol.py tests/test_add_nasdaq_symbol.py
git add add_nasdaq_symbol.py tests/test_add_nasdaq_symbol.py
git commit -m "feat: add CLI entry point for add_nasdaq_symbol"
```

---

### Task 5: Live-config smoke test, docs, and CLAUDE.md entry

**Files:**

- Modify: `tests/test_add_nasdaq_symbol.py`
- Create: `docs/add_nasdaq_symbol.md`
- Modify: `CLAUDE.md`

**Interfaces:**

- Consumes: `build_changes` (from Task 1), `Path` (stdlib), `json` (stdlib).
- Produces: nothing consumed by other tasks — this is the last task in the plan.

- [ ] **Step 1: Add the live-config smoke test**

Append to `tests/test_add_nasdaq_symbol.py`:

```python
from pathlib import Path

LIVE_CONFIG = Path("lazer_jpkr.json")


@pytest.mark.skipif(
    not LIVE_CONFIG.exists(),
    reason="lazer_jpkr.json is gitignored and not present in this checkout",
)
class TestLiveConfigSmoke:
    """Guards the measured expectations from the design doc.

    The config is gitignored, so these are skipped wherever it is absent.
    """

    def _feeds(self):
        return json.loads(LIVE_CONFIG.read_text(encoding="utf-8"))["feeds"]

    def test_465_changes_no_skips(self):
        changes, skips = build_changes(self._feeds())
        assert len(changes) == 465
        assert skips == []
```

Note: if this checkout's `lazer_jpkr.json` has drifted since the design doc's measurement (465 changes, 0 skips), this test will fail with a different count. That's expected signal, not flakiness — re-measure with a dry run (`python3 add_nasdaq_symbol.py --config lazer_jpkr.json`) and update the asserted number to match, since the file is a live, gitignored working copy that can change between sessions.

- [ ] **Step 2: Run the full test suite**

Run: `pytest tests/test_add_nasdaq_symbol.py -v`
Expected: PASS (including `TestLiveConfigSmoke` if `lazer_jpkr.json` is present in this checkout, otherwise skipped)

- [ ] **Step 3: Write the usage doc**

Create `docs/add_nasdaq_symbol.md`:

````markdown
# nasdaq_symbol Backfill (add_nasdaq_symbol.py)

Backfills `metadata.nasdaq_symbol = metadata.name` (verbatim) across Hong Kong,
mainland China, Japan, South Korea, and India equity feeds. These markets carry the
exchange-facing identifier downstream users read prices by in `metadata.name` -- a
numeric code for HK/CN/JP/KR, or the raw ticker for the handful of already-alphabetic
names (e.g. `NIFTYBEES`). `rename_numeric_feed_names.py` later overwrites
`metadata.name` with a human-readable company name for display, so this script must
run first, while `metadata.name` still holds the original identifier.

See `docs/superpowers/specs/2026-07-29-add-nasdaq-symbol-design.md` for the full design.

## Usage

```bash
# Dry run (default) -- prints the plan, writes nothing
python3 add_nasdaq_symbol.py --config lazer_jpkr.json

# Apply -- writes lazer_jpkr.json, keeps a .bak backup
python3 add_nasdaq_symbol.py --config lazer_jpkr.json --apply

# Narrow to one market
python3 add_nasdaq_symbol.py --config lazer_jpkr.json --symbol-prefix Equity.HK. --apply
```
````

## Arguments

| Argument          | Description                             | Required | Default                                                              |
| ----------------- | --------------------------------------- | -------- | -------------------------------------------------------------------- |
| `--config`        | Path to the Lazer config JSON           | Yes      | --                                                                   |
| `--symbol-prefix` | Symbol namespace to process; repeatable | No       | `Equity.HK.`, `Equity.CN.`, `Equity.JP.`, `Equity.KR.`, `Equity.IN.` |
| `--apply`         | Write changes (default is dry run)      | No       | off                                                                  |
| `--no-backup`     | Skip the `.bak` copy `--apply` makes    | No       | off                                                                  |

## Behavior

For every in-scope feed:

- **Already has `nasdaq_symbol`:** skipped, reported -- makes a second run a no-op.
- **`metadata.name` is empty:** skipped, reported -- nothing to copy.
- **`metadata.name` does not match the code embedded in `symbol`:** skipped, reported.
  `rename_numeric_feed_names.py` never touches `symbol`, so the code segment embedded
  in it (e.g. `0002` in `Equity.HK.0002/HKD`) is an exact fingerprint of the
  not-yet-renamed state. A mismatch means the feed has already been through
  `rename_numeric_feed_names.py` and copying `metadata.name` into `nasdaq_symbol` would
  put a display name where the exchange code belongs -- this is an exact check, not a
  whitespace heuristic, since some renamed display names are a single word (e.g.
  `HITACHI`, `CNOOC`) and would slip past a whitespace-only check.
- **Otherwise:** `metadata.nasdaq_symbol` is set to `metadata.name`, verbatim.

`metadata` dict keys are rebuilt in alphabetical order whenever `nasdaq_symbol` is
added, matching the existing convention on every metadata dict in the config
(`nasdaq_symbol` already sorts between `name` and `quote_currency`, as seen on US
equity feeds).

## Verification

Before writing, and again after writing to disk, the script re-parses the config and
confirms: the feed-id set is unchanged, every feed outside the planned change set has
a byte-identical `metadata` dict to before, and every feed in the change set gained
exactly the planned `nasdaq_symbol` value with nothing else altered. A `.bak` copy of
the original file is kept unless `--no-backup` is passed.

## Tests

```bash
pytest tests/test_add_nasdaq_symbol.py -v
```

Per CLAUDE.md, the repo-root `pytest -q` fails on a pre-existing conftest name clash,
so this suite is always run on its own.

````

- [ ] **Step 4: Add a row to the CLAUDE.md Scripts table**

Modify `CLAUDE.md`: in the Scripts table, add a row directly after the
`rename_numeric_feed_names.py` row:

```markdown
| `add_nasdaq_symbol.py`                  | Backfill metadata.nasdaq_symbol = metadata.name for HK/CN/JP/KR/IN equity feeds (run before rename_numeric_feed_names.py)                                                                          | `python3 add_nasdaq_symbol.py --config lazer_jpkr.json`                                               | [docs/add_nasdaq_symbol.md](docs/add_nasdaq_symbol.md)                          |
````

Match the existing table's column widths/padding style as closely as practical --
exact alignment will be re-flowed by prettier in the next step regardless.

Known hazard: a new row wider than the table's current column max makes prettier
reflow _every_ row in the table, producing a large diff unrelated to this feature and
a likely merge conflict with any other branch touching this table concurrently. This
is expected, not a mistake -- let prettier do it and commit the reflow along with the
new row as a single docs commit (Step 6), rather than fighting the formatter.

- [ ] **Step 5: Run pre-commit on all changed/created files**

Run: `pre-commit run --files add_nasdaq_symbol.py tests/test_add_nasdaq_symbol.py docs/add_nasdaq_symbol.md CLAUDE.md`
Expected: all hooks pass (prettier will reflow the CLAUDE.md table and the new doc; re-stage if it rewrites anything)

- [ ] **Step 6: Commit**

```bash
git add tests/test_add_nasdaq_symbol.py docs/add_nasdaq_symbol.md CLAUDE.md
git commit -m "docs: add add_nasdaq_symbol usage doc and CLAUDE.md entry"
```

---

## Definition of Done

- [ ] `add_nasdaq_symbol.py` implemented: dry-run by default, `--apply` to write, `.bak` backup unless `--no-backup`.
- [ ] All automated unit tests pass: `pytest tests/test_add_nasdaq_symbol.py -v`.
- [ ] `docs/add_nasdaq_symbol.md` written; CLAUDE.md Scripts table updated.
- [ ] `pre-commit run --files <changed files>` passes on every commit.
- [ ] Dry run against `lazer_jpkr.json` reviewed by hand (`python3 add_nasdaq_symbol.py --config lazer_jpkr.json`) before `--apply` is used for real.
