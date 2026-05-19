# edit-config `--set-ric-mapping` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `--set-ric-mapping --from-csv <path>` operation to `tools/edit-config/edit_config.py` that surgically fills empty `datascope_ric.identifier` values in `after.json` from an LSEG-style CSV (HK rule v1).

**Architecture:** New `SetRicMapping` op class in `config_ops.py`, a new `find_ric_identifier_spans()` locator in `config_text_surgery.py`, a CSV loader in a new `ric_csv.py` module, and wiring through `config_editor.py` + CLI + YAML spec. Emits per-slot `Change` records carrying a slot `index`; the existing apply-changes path is extended to handle the new field.

**Tech Stack:** Python 3, stdlib only (`csv`, `re`, `dataclasses`), `pytest` for tests.

**Spec:** `docs/superpowers/specs/2026-05-18-edit-config-set-ric-mapping-design.md`

---

## File Structure

**Create:**

- `tools/edit-config/edit_config_lib/ric_csv.py` — CSV loading + HK prefix derivation.
- `tools/edit-config/tests/test_ric_csv.py` — unit tests for CSV loader.
- `tools/edit-config/tests/fixtures/hk_sample.json` — small fixture: empty / populated / unmatched / non-HK feeds.
- `tools/edit-config/tests/fixtures/hk-syms-sample.csv` — matching + unmatched CSV rows.

**Modify:**

- `tools/edit-config/edit_config_lib/config_ops.py` — add `index` to `Change`, add `SetRicMapping` op.
- `tools/edit-config/edit_config_lib/config_text_surgery.py` — add `find_ric_identifier_spans()`.
- `tools/edit-config/edit_config_lib/config_editor.py` — wire CLI + YAML + apply path.
- `tools/edit-config/edit_config.py` — CLI flags `--set-ric-mapping` and `--from-csv`.
- `tools/edit-config/tests/test_config_ops.py` — `SetRicMapping` unit tests.
- `tools/edit-config/tests/test_edit_config_cli.py` — end-to-end CLI test.
- `tools/edit-config/tests/test_config_text_surgery.py` — locator tests.
- `tools/edit-config/README.md` — usage example for the new op.
- `docs/edit_config.md` — usage doc.

---

## Task 1: CSV loader skeleton + tests (RED)

**Files:**

- Create: `tools/edit-config/tests/test_ric_csv.py`
- Create: `tools/edit-config/tests/fixtures/hk-syms-sample.csv`

- [ ] **Step 1: Write the fixture CSV**

Create `tools/edit-config/tests/fixtures/hk-syms-sample.csv` with the same header as the real file:

```csv
Exchange Code,Exchange Description,Ticker,RIC,Security Description,Security Long Description,Asset Category,Asset Category Description,Asset SubType,Asset SubType Description,GICS Sector Code,GICS Sector Code Description,GICS Industry Code,GICS Industry Code Description,GICS Industry Description Code,GICS Industry Description Code Description,GICS Industry Group Code,GICS Industry Group Code Description
HKG,The Stock Exchange of Hong Kong Ltd,700,0700.HK,TENCENT ORD,Tencent Holdings Ord Shs,ORD,Ordinary,ODSH,Ordinary shares,,,,,,,,
HKG,The Stock Exchange of Hong Kong Ltd,883,0883.HK,CNOOC ORD,CNOOC Ord Shs,ORD,Ordinary,ODSH,Ordinary shares,,,,,,,,
HKG,The Stock Exchange of Hong Kong Ltd,1211,1211.HK,BYD ORD,BYD Ord Shs,ORD,Ordinary,ODSH,Ordinary shares,,,,,,,,
```

- [ ] **Step 2: Write failing tests**

Create `tools/edit-config/tests/test_ric_csv.py`:

```python
"""Tests for ric_csv module."""

from pathlib import Path

import pytest

from edit_config_lib.ric_csv import (
    RicEntry,
    load_ric_csv,
    derive_symbol_prefix,
    LoadError,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_load_ric_csv_returns_entries():
    entries = load_ric_csv(str(FIXTURES / "hk-syms-sample.csv"))
    assert len(entries) == 3
    assert entries[0] == RicEntry(ticker="700", ric="0700.HK", exchange_code="HKG")
    assert entries[1].ric == "0883.HK"
    assert entries[2].ric == "1211.HK"


def test_load_ric_csv_raises_on_missing_file(tmp_path):
    with pytest.raises(LoadError, match="not found"):
        load_ric_csv(str(tmp_path / "nope.csv"))


def test_load_ric_csv_raises_on_empty(tmp_path):
    p = tmp_path / "empty.csv"
    p.write_text("Exchange Code,Ticker,RIC\n", encoding="utf-8")
    with pytest.raises(LoadError, match="no data rows"):
        load_ric_csv(str(p))


def test_load_ric_csv_raises_on_missing_columns(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("Ticker,Foo\n700,bar\n", encoding="utf-8")
    with pytest.raises(LoadError, match="missing required column"):
        load_ric_csv(str(p))


def test_load_ric_csv_raises_on_duplicate_ric(tmp_path):
    p = tmp_path / "dup.csv"
    p.write_text(
        "Exchange Code,Ticker,RIC\n"
        "HKG,700,0700.HK\n"
        "HKG,701,0700.HK\n",
        encoding="utf-8",
    )
    with pytest.raises(LoadError, match="duplicate RIC"):
        load_ric_csv(str(p))


def test_derive_symbol_prefix_hk():
    assert derive_symbol_prefix("0700.HK") == "Equity.HK.0700-HK/"
    assert derive_symbol_prefix("0002.HK") == "Equity.HK.0002-HK/"


def test_derive_symbol_prefix_unknown_suffix_returns_none():
    assert derive_symbol_prefix("AAPL.O") is None
    assert derive_symbol_prefix("EUR=") is None
```

- [ ] **Step 3: Run tests to verify they fail**

```
cd tools/edit-config && python3 -m pytest tests/test_ric_csv.py -v
```

Expected: ImportError / ModuleNotFoundError for `edit_config_lib.ric_csv`.

- [ ] **Step 4: Commit the failing test**

```bash
git add tools/edit-config/tests/test_ric_csv.py tools/edit-config/tests/fixtures/hk-syms-sample.csv
git commit -m "test: failing tests for ric_csv loader"
```

---

## Task 2: CSV loader implementation (GREEN)

**Files:**

- Create: `tools/edit-config/edit_config_lib/ric_csv.py`

- [ ] **Step 1: Implement the module**

Create `tools/edit-config/edit_config_lib/ric_csv.py`:

```python
"""Load LSEG-style RIC CSVs and derive feed symbol prefixes.

The CSV contains one row per security with columns including `Ticker`,
`RIC`, and `Exchange Code`. For v1 we only know how to derive a feed
symbol prefix for HK rows (RIC ending in `.HK`).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


class LoadError(Exception):
    """Raised on malformed or missing CSV input."""


@dataclass(frozen=True)
class RicEntry:
    ticker: str
    ric: str
    exchange_code: str


_REQUIRED_COLUMNS = ("Ticker", "RIC", "Exchange Code")


def load_ric_csv(path: str) -> list[RicEntry]:
    """Parse the CSV at `path`. Raises LoadError on any structural problem."""
    p = Path(path)
    if not p.exists():
        raise LoadError(f"CSV not found: {path}")
    with p.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise LoadError(f"{path}: no header row")
        missing = [c for c in _REQUIRED_COLUMNS if c not in reader.fieldnames]
        if missing:
            raise LoadError(
                f"{path}: missing required column(s): {', '.join(missing)}"
            )
        entries: list[RicEntry] = []
        seen_rics: set[str] = set()
        for i, row in enumerate(reader, start=2):  # line 2 = first data row
            ric = (row.get("RIC") or "").strip()
            ticker = (row.get("Ticker") or "").strip()
            exchange = (row.get("Exchange Code") or "").strip()
            if not ric:
                continue  # skip blank rows
            if ric in seen_rics:
                raise LoadError(f"{path}: duplicate RIC {ric!r} (line {i})")
            seen_rics.add(ric)
            entries.append(
                RicEntry(ticker=ticker, ric=ric, exchange_code=exchange)
            )
    if not entries:
        raise LoadError(f"{path}: no data rows")
    return entries


def derive_symbol_prefix(ric: str) -> str | None:
    """Map a RIC to the expected Lazer feed symbol prefix.

    v1 supports only HK equities: `NNNN.HK` -> `Equity.HK.NNNN-HK/`.
    Returns None for RICs we don't know how to map.
    """
    if ric.endswith(".HK"):
        head = ric[: -len(".HK")]
        if head.isdigit():
            return f"Equity.HK.{head}-HK/"
    return None


def build_prefix_index(entries: list[RicEntry]) -> dict[str, str]:
    """Build `{symbol_prefix: ric}` for entries with a derivable prefix.

    Entries with no derivable prefix are silently dropped — callers can
    diff against `entries` to report unmapped RICs.
    """
    out: dict[str, str] = {}
    for e in entries:
        prefix = derive_symbol_prefix(e.ric)
        if prefix is None:
            continue
        out[prefix] = e.ric
    return out
```

- [ ] **Step 2: Run tests to verify they pass**

```
cd tools/edit-config && python3 -m pytest tests/test_ric_csv.py -v
```

Expected: all 7 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tools/edit-config/edit_config_lib/ric_csv.py
git commit -m "feat: add ric_csv loader for LSEG-style HK CSVs"
```

---

## Task 3: text-surgery locator for `datascope_ric` identifier spans (RED → GREEN)

**Files:**

- Modify: `tools/edit-config/edit_config_lib/config_text_surgery.py`
- Modify: `tools/edit-config/tests/test_config_text_surgery.py`

- [ ] **Step 1: Write failing tests**

Append to `tools/edit-config/tests/test_config_text_surgery.py`:

```python
from edit_config_lib.config_text_surgery import find_ric_identifier_spans


def test_find_ric_identifier_spans_single_empty():
    block = '''{
  "feedId": 884,
  "marketSchedules": [
    {
      "benchmarkMapping": {
        "datascope_ric": {
          "identifiers": [
            {
              "identifier": "",
              "validFrom": "1970-01-01T00:00:00.000000000Z"
            }
          ]
        }
      }
    }
  ]
}'''
    spans = find_ric_identifier_spans(block)
    assert len(spans) == 1
    start, end, value = spans[0]
    assert block[start:end] == '""'
    assert value == ""


def test_find_ric_identifier_spans_populated_is_returned_too():
    block = '''{
  "marketSchedules": [
    {
      "benchmarkMapping": {
        "datascope_ric": {
          "identifiers": [
            {"identifier": "0700.HK", "validFrom": "1970-01-01T00:00:00.000000000Z"}
          ]
        }
      }
    }
  ]
}'''
    spans = find_ric_identifier_spans(block)
    assert len(spans) == 1
    start, end, value = spans[0]
    assert block[start:end] == '"0700.HK"'
    assert value == "0700.HK"


def test_find_ric_identifier_spans_multiple_schedules():
    block = '''{
  "marketSchedules": [
    {"benchmarkMapping": {"datascope_ric": {"identifiers": [{"identifier": ""}]}}},
    {"benchmarkMapping": {"datascope_ric": {"identifiers": [{"identifier": "X"}]}}}
  ]
}'''
    spans = find_ric_identifier_spans(block)
    assert [v for _, _, v in spans] == ["", "X"]
    # spans must be in document order
    assert spans[0][0] < spans[1][0]


def test_find_ric_identifier_spans_no_datascope_ric():
    block = '{"marketSchedules": [{"benchmarkMapping": {}}]}'
    assert find_ric_identifier_spans(block) == []


def test_find_ric_identifier_spans_no_marketSchedules():
    block = '{"feedId": 1}'
    assert find_ric_identifier_spans(block) == []
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd tools/edit-config && python3 -m pytest tests/test_config_text_surgery.py -v -k ric_identifier
```

Expected: ImportError for `find_ric_identifier_spans`.

- [ ] **Step 3: Implement the locator**

Append to `tools/edit-config/edit_config_lib/config_text_surgery.py`:

```python
def find_ric_identifier_spans(block: str) -> list[tuple[int, int, str]]:
    """Locate every `"identifier"` string value inside any
    `datascope_ric.identifiers[]` array within `block`.

    Returns a list of (start, end, current_value) tuples in document
    order, where `start..end` covers the value INCLUDING the surrounding
    double quotes. The list is empty if no such structure exists.
    """
    out: list[tuple[int, int, str]] = []
    # Find each `"datascope_ric":` and walk into its identifiers array.
    for dm in re.finditer(r'"datascope_ric"\s*:\s*\{', block):
        dr_open = dm.end() - 1  # '{' position
        dr_close = find_matching_close(block, dr_open)
        if dr_close is None:
            continue
        dr_block = block[dr_open : dr_close + 1]
        ids_match = re.search(r'"identifiers"\s*:\s*\[', dr_block)
        if ids_match is None:
            continue
        ids_open_rel = ids_match.end() - 1  # '[' inside dr_block
        ids_close_rel = find_matching_close(dr_block, ids_open_rel)
        if ids_close_rel is None:
            continue
        ids_block = dr_block[ids_open_rel : ids_close_rel + 1]
        # Find each "identifier": "..." inside the identifiers array.
        for m in re.finditer(
            r'"identifier"\s*:\s*("[^"\\]*(?:\\.[^"\\]*)*")', ids_block
        ):
            abs_start = dr_open + ids_open_rel + m.start(1)
            abs_end = dr_open + ids_open_rel + m.end(1)
            # Strip surrounding quotes for the value.
            value = block[abs_start + 1 : abs_end - 1]
            out.append((abs_start, abs_end, value))
    out.sort(key=lambda t: t[0])
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd tools/edit-config && python3 -m pytest tests/test_config_text_surgery.py -v
```

Expected: all tests PASS (including pre-existing ones).

- [ ] **Step 5: Commit**

```bash
git add tools/edit-config/edit_config_lib/config_text_surgery.py tools/edit-config/tests/test_config_text_surgery.py
git commit -m "feat: locator for datascope_ric identifier spans"
```

---

## Task 4: Extend `Change` with `index` field

**Files:**

- Modify: `tools/edit-config/edit_config_lib/config_ops.py`

- [ ] **Step 1: Add optional `index` to `Change`**

In `tools/edit-config/edit_config_lib/config_ops.py`, modify the `Change` dataclass:

```python
@dataclass(frozen=True)
class Change:
    """One atomic edit to a feed."""

    feed_id: int
    symbol: str
    location: str  # "top_level", a SESSION_NAME, or "datascope_ric_identifier"
    field: str  # "allowedPublisherIds", "minPublishers", "state", "identifier"
    before: Any
    after: Any
    index: int | None = None  # for list-positional fields (e.g. ric identifier slot)
```

- [ ] **Step 2: Run existing tests to verify nothing regressed**

```
cd tools/edit-config && python3 -m pytest -v
```

Expected: all existing tests PASS (the new field has a default).

- [ ] **Step 3: Commit**

```bash
git add tools/edit-config/edit_config_lib/config_ops.py
git commit -m "refactor: add optional index field to Change for positional edits"
```

---

## Task 5: `SetRicMapping` op (RED)

**Files:**

- Modify: `tools/edit-config/tests/test_config_ops.py`

- [ ] **Step 1: Add failing tests**

Append to `tools/edit-config/tests/test_config_ops.py`:

```python
from edit_config_lib.config_ops import SetRicMapping


def _hk_feed(feed_id: int, ticker: str, identifier: str = "") -> dict:
    return {
        "feedId": feed_id,
        "symbol": f"Equity.HK.{ticker}-HK/HKD",
        "state": "COMING_SOON",
        "marketSchedules": [
            {
                "benchmarkMapping": {
                    "datascope_ric": {
                        "identifiers": [
                            {"identifier": identifier, "validFrom": "1970-01-01T00:00:00.000000000Z"}
                        ]
                    }
                }
            }
        ],
    }


def test_set_ric_mapping_fills_empty_identifier():
    feed = _hk_feed(884, "0002")
    op = SetRicMapping(prefix_to_ric={"Equity.HK.0002-HK/": "0002.HK"})
    changes, warnings = op.apply(feed)
    assert len(changes) == 1
    c = changes[0]
    assert c.feed_id == 884
    assert c.location == "datascope_ric_identifier"
    assert c.field == "identifier"
    assert c.before == ""
    assert c.after == "0002.HK"
    assert c.index == 0
    assert warnings == []
    # in-memory feed is updated too
    assert (
        feed["marketSchedules"][0]["benchmarkMapping"]["datascope_ric"][
            "identifiers"
        ][0]["identifier"]
        == "0002.HK"
    )


def test_set_ric_mapping_skips_populated_identifier_with_warning():
    feed = _hk_feed(884, "0002", identifier="EXISTING.HK")
    op = SetRicMapping(prefix_to_ric={"Equity.HK.0002-HK/": "0002.HK"})
    changes, warnings = op.apply(feed)
    assert changes == []
    assert len(warnings) == 1
    assert "already populated" in warnings[0].message


def test_set_ric_mapping_skips_unmatched_symbol():
    feed = _hk_feed(884, "0002")
    op = SetRicMapping(prefix_to_ric={"Equity.HK.0700-HK/": "0700.HK"})
    changes, warnings = op.apply(feed)
    # No symbol-prefix match -> silent skip, no changes, no warnings.
    assert changes == []
    assert warnings == []


def test_set_ric_mapping_skips_feed_without_datascope_ric_structure():
    feed = {
        "feedId": 999,
        "symbol": "Equity.HK.0002-HK/HKD",
        "state": "COMING_SOON",
        "marketSchedules": [{"benchmarkMapping": {}}],
    }
    op = SetRicMapping(prefix_to_ric={"Equity.HK.0002-HK/": "0002.HK"})
    changes, warnings = op.apply(feed)
    assert changes == []
    assert len(warnings) == 1
    assert "no datascope_ric identifier slots" in warnings[0].message


def test_set_ric_mapping_handles_multi_slot_feed():
    feed = {
        "feedId": 884,
        "symbol": "Equity.HK.0002-HK/HKD",
        "state": "COMING_SOON",
        "marketSchedules": [
            {
                "benchmarkMapping": {
                    "datascope_ric": {
                        "identifiers": [
                            {"identifier": ""},
                            {"identifier": "ALREADY.HK"},
                        ]
                    }
                }
            }
        ],
    }
    op = SetRicMapping(prefix_to_ric={"Equity.HK.0002-HK/": "0002.HK"})
    changes, warnings = op.apply(feed)
    assert len(changes) == 1
    assert changes[0].index == 0
    assert changes[0].after == "0002.HK"
    assert len(warnings) == 1  # one skip warning for index 1
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd tools/edit-config && python3 -m pytest tests/test_config_ops.py -v -k set_ric_mapping
```

Expected: ImportError for `SetRicMapping`.

- [ ] **Step 3: Commit**

```bash
git add tools/edit-config/tests/test_config_ops.py
git commit -m "test: failing tests for SetRicMapping op"
```

---

## Task 6: `SetRicMapping` op (GREEN)

**Files:**

- Modify: `tools/edit-config/edit_config_lib/config_ops.py`

- [ ] **Step 1: Implement the op**

Append to `tools/edit-config/edit_config_lib/config_ops.py`:

```python
@dataclass
class SetRicMapping:
    """Fill empty `datascope_ric.identifiers[].identifier` slots from a CSV-derived mapping.

    `prefix_to_ric` maps a feed-symbol prefix (e.g. `"Equity.HK.0700-HK/"`)
    to the RIC string to write (e.g. `"0700.HK"`).

    Per-slot semantics:
      - empty string  -> Change (fill with the RIC).
      - any non-empty -> Warning (skipped, no overwrite).

    Per-feed semantics:
      - feed.symbol does not match any prefix -> silent skip (no warnings).
      - feed has no datascope_ric.identifiers[] slots -> Warning.
    """

    prefix_to_ric: dict[str, str]

    def apply(self, feed: dict) -> tuple[list[Change], list[Warning]]:
        feed_id = feed["feedId"]
        symbol = feed.get("symbol", "")

        ric = None
        for prefix, candidate in self.prefix_to_ric.items():
            if symbol.startswith(prefix):
                ric = candidate
                break
        if ric is None:
            return [], []

        slots: list[dict] = []  # references to {"identifier": ...} dicts
        for schedule in feed.get("marketSchedules", []):
            bm = schedule.get("benchmarkMapping", {})
            ds = bm.get("datascope_ric", {})
            for ident in ds.get("identifiers", []) or []:
                if isinstance(ident, dict) and "identifier" in ident:
                    slots.append(ident)

        if not slots:
            return [], [
                Warning(
                    feed_id=feed_id,
                    symbol=symbol,
                    message=(
                        f"feed {feed_id}: no datascope_ric identifier slots — skipped"
                    ),
                )
            ]

        changes: list[Change] = []
        warnings: list[Warning] = []
        for i, slot in enumerate(slots):
            current = slot["identifier"]
            if current == "":
                changes.append(
                    Change(
                        feed_id=feed_id,
                        symbol=symbol,
                        location="datascope_ric_identifier",
                        field="identifier",
                        before="",
                        after=ric,
                        index=i,
                    )
                )
                slot["identifier"] = ric  # keep working-copy consistent
            else:
                warnings.append(
                    Warning(
                        feed_id=feed_id,
                        symbol=symbol,
                        message=(
                            f"feed {feed_id}: identifier slot {i} already populated "
                            f"({current!r}) — skipped"
                        ),
                    )
                )
        return changes, warnings
```

- [ ] **Step 2: Run tests to verify they pass**

```
cd tools/edit-config && python3 -m pytest tests/test_config_ops.py -v
```

Expected: all tests PASS, including the 5 new `SetRicMapping` tests.

- [ ] **Step 3: Commit**

```bash
git add tools/edit-config/edit_config_lib/config_ops.py
git commit -m "feat: SetRicMapping op for filling datascope_ric identifiers"
```

---

## Task 7: Wire `SetRicMapping` into `apply_changes` text-surgery path (RED → GREEN)

**Files:**

- Modify: `tools/edit-config/edit_config_lib/config_editor.py`
- Modify: `tools/edit-config/tests/test_config_editor.py` (if exists; otherwise extend an existing test file — see step 1)

- [ ] **Step 1: Add a failing end-to-end text-apply test**

First check what test module covers `apply_changes`:

```
cd tools/edit-config && grep -l "apply_changes" tests/
```

Add a new test to the file that covers `apply_changes` (most likely `tests/test_config_editor.py`; create it if missing). The test:

```python
from edit_config_lib.config_editor import apply_changes
from edit_config_lib.config_ops import Change


def test_apply_changes_fills_ric_identifier():
    raw = '''{
  "feeds": [
    {
      "feedId": 884,
      "symbol": "Equity.HK.0002-HK/HKD",
      "marketSchedules": [
        {
          "benchmarkMapping": {
            "datascope_ric": {
              "identifiers": [
                {
                  "identifier": "",
                  "validFrom": "1970-01-01T00:00:00.000000000Z"
                }
              ]
            }
          }
        }
      ]
    }
  ]
}'''
    changes = [
        Change(
            feed_id=884,
            symbol="Equity.HK.0002-HK/HKD",
            location="datascope_ric_identifier",
            field="identifier",
            before="",
            after="0002.HK",
            index=0,
        )
    ]
    out = apply_changes(raw, changes)
    assert '"identifier": "0002.HK"' in out
    # everything else byte-identical
    assert out.replace('"identifier": "0002.HK"', '"identifier": ""') == raw


def test_apply_changes_fills_correct_slot_index():
    raw = '''{
  "feeds": [
    {
      "feedId": 1,
      "symbol": "S",
      "marketSchedules": [
        {
          "benchmarkMapping": {
            "datascope_ric": {
              "identifiers": [
                {"identifier": ""},
                {"identifier": ""}
              ]
            }
          }
        }
      ]
    }
  ]
}'''
    changes = [
        Change(feed_id=1, symbol="S", location="datascope_ric_identifier",
               field="identifier", before="", after="B", index=1),
        Change(feed_id=1, symbol="S", location="datascope_ric_identifier",
               field="identifier", before="", after="A", index=0),
    ]
    out = apply_changes(raw, changes)
    # First slot -> "A", second slot -> "B".
    a_pos = out.find('"identifier": "A"')
    b_pos = out.find('"identifier": "B"')
    assert 0 <= a_pos < b_pos
```

- [ ] **Step 2: Run tests to verify they fail**

```
cd tools/edit-config && python3 -m pytest tests/test_config_editor.py -v -k ric
```

Expected: failures — `apply_changes` does not yet know `field="identifier"`.

- [ ] **Step 3: Extend `_apply_changes_to_feed_block`**

In `tools/edit-config/edit_config_lib/config_editor.py`, modify the import line near the top of the text-surgery imports to include the new locator:

```python
from edit_config_lib.config_text_surgery import (
    find_feed_block,
    find_session_block,
    find_publisher_array_span,
    find_int_field_span,
    find_string_field_span,
    find_matching_close,
    find_ric_identifier_spans,
)
```

Then, inside `_apply_changes_to_feed_block`, BEFORE the per-change `for change in changes:` loop, split the changes by whether they target ric identifiers (which require an indexed batch lookup) vs. everything else. The simplest implementation:

Replace the existing `for change in changes:` body's location-branching with an early branch:

```python
    # Pre-compute ric identifier spans once if any change targets them.
    ric_spans: list[tuple[int, int, str]] | None = None
    if any(c.location == "datascope_ric_identifier" for c in changes):
        ric_spans = find_ric_identifier_spans(block)

    for change in changes:
        if change.location == "datascope_ric_identifier":
            assert ric_spans is not None
            if change.index is None:
                raise RuntimeError(
                    "datascope_ric_identifier change missing index"
                )
            if change.index >= len(ric_spans):
                raise RuntimeError(
                    f"identifier slot index {change.index} out of range "
                    f"({len(ric_spans)} slots)"
                )
            start_rel, end_rel, _current = ric_spans[change.index]
            replacement = f'"{change.after}"'
            edits.append((start_rel, end_rel, replacement))
            continue

        if change.location == "top_level":
            ...
```

Keep the rest of the function unchanged. The key invariants: spans are computed once per feed block (not per change) and indexes refer to document order.

- [ ] **Step 4: Run tests to verify they pass**

```
cd tools/edit-config && python3 -m pytest tests/test_config_editor.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Run the full test suite**

```
cd tools/edit-config && python3 -m pytest -v
```

Expected: every test PASSES — no regressions.

- [ ] **Step 6: Commit**

```bash
git add tools/edit-config/edit_config_lib/config_editor.py tools/edit-config/tests/test_config_editor.py
git commit -m "feat: apply_changes handles datascope_ric_identifier edits"
```

---

## Task 8: CLI flag `--set-ric-mapping --from-csv` (RED → GREEN)

**Files:**

- Modify: `tools/edit-config/edit_config.py`
- Modify: `tools/edit-config/edit_config_lib/config_editor.py`
- Create: `tools/edit-config/tests/fixtures/hk_sample.json`
- Modify: `tools/edit-config/tests/test_edit_config_cli.py`

- [ ] **Step 1: Create the JSON fixture**

Create `tools/edit-config/tests/fixtures/hk_sample.json`. Keep the schema close to the real file (top-level keys + a small feeds array):

```json
{
  "featureFlags": {},
  "feeds": [
    {
      "allowedPublisherIds": [1, 3, 4],
      "expiryTime": "5.000000000s",
      "exponent": -5,
      "feedId": 884,
      "isEnabledInShard": true,
      "kind": "PRICE",
      "marketSchedules": [
        {
          "benchmarkMapping": {
            "datascope_ric": {
              "identifiers": [
                {
                  "identifier": "",
                  "validFrom": "1970-01-01T00:00:00.000000000Z"
                }
              ]
            }
          },
          "marketSchedule": "Asia/Hong_Kong;C"
        }
      ],
      "metadata": { "asset_type": "Equity" },
      "minChannel": "REAL_TIME",
      "minPublishers": 1,
      "state": "COMING_SOON",
      "symbol": "Equity.HK.0700-HK/HKD"
    },
    {
      "allowedPublisherIds": [1, 3, 4],
      "expiryTime": "5.000000000s",
      "exponent": -5,
      "feedId": 885,
      "isEnabledInShard": true,
      "kind": "PRICE",
      "marketSchedules": [
        {
          "benchmarkMapping": {
            "datascope_ric": {
              "identifiers": [
                {
                  "identifier": "STALE.HK",
                  "validFrom": "1970-01-01T00:00:00.000000000Z"
                }
              ]
            }
          },
          "marketSchedule": "Asia/Hong_Kong;C"
        }
      ],
      "metadata": { "asset_type": "Equity" },
      "minChannel": "REAL_TIME",
      "minPublishers": 1,
      "state": "COMING_SOON",
      "symbol": "Equity.HK.0883-HK/HKD"
    },
    {
      "allowedPublisherIds": [1, 3, 4],
      "expiryTime": "5.000000000s",
      "exponent": -5,
      "feedId": 886,
      "isEnabledInShard": true,
      "kind": "PRICE",
      "marketSchedules": [
        {
          "benchmarkMapping": {
            "datascope_ric": {
              "identifiers": [
                {
                  "identifier": "",
                  "validFrom": "1970-01-01T00:00:00.000000000Z"
                }
              ]
            }
          },
          "marketSchedule": "Asia/Hong_Kong;C"
        }
      ],
      "metadata": { "asset_type": "Equity" },
      "minChannel": "REAL_TIME",
      "minPublishers": 1,
      "state": "COMING_SOON",
      "symbol": "Equity.HK.9999-HK/HKD"
    },
    {
      "allowedPublisherIds": [1, 3, 4],
      "expiryTime": "5.000000000s",
      "exponent": -8,
      "feedId": 1000,
      "isEnabledInShard": true,
      "kind": "PRICE",
      "marketSchedules": [],
      "metadata": { "asset_type": "Crypto" },
      "minChannel": "REAL_TIME",
      "minPublishers": 1,
      "state": "STABLE",
      "symbol": "Crypto.BTC/USD"
    }
  ]
}
```

Note: feed 884 expects RIC `0700.HK` (matches sample CSV), feed 885 has a stale RIC (must be skipped + warned), feed 886's ticker `9999` is NOT in the sample CSV (must be untouched), feed 1000 is a non-HK feed (must be untouched).

- [ ] **Step 2: Write the failing CLI test**

Append to `tools/edit-config/tests/test_edit_config_cli.py`:

```python
import json
import shutil
import subprocess
import sys
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures"
TOOL = Path(__file__).resolve().parents[1] / "edit_config.py"


def _run_cli(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_set_ric_mapping_dry_run(tmp_path):
    config = tmp_path / "after.json"
    shutil.copy(FIXTURES / "hk_sample.json", config)
    csv_path = FIXTURES / "hk-syms-sample.csv"

    result = _run_cli(
        [
            "--config", str(config),
            "--set-ric-mapping",
            "--from-csv", str(csv_path),
            "--dry-run",
        ]
    )
    assert result.returncode == 0, result.stderr
    # Dry-run must not modify the file.
    assert config.read_text() == (FIXTURES / "hk_sample.json").read_text()
    out = result.stdout + result.stderr
    # Reports the planned change for feed 884.
    assert "884" in out
    assert "0700.HK" in out


def test_cli_set_ric_mapping_apply(tmp_path):
    config = tmp_path / "after.json"
    shutil.copy(FIXTURES / "hk_sample.json", config)
    csv_path = FIXTURES / "hk-syms-sample.csv"

    result = _run_cli(
        [
            "--config", str(config),
            "--set-ric-mapping",
            "--from-csv", str(csv_path),
        ]
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(config.read_text())
    feeds_by_id = {f["feedId"]: f for f in data["feeds"]}
    # Feed 884: filled with 0700.HK.
    assert (
        feeds_by_id[884]["marketSchedules"][0]["benchmarkMapping"][
            "datascope_ric"
        ]["identifiers"][0]["identifier"]
        == "0700.HK"
    )
    # Feed 885: STALE.HK left untouched.
    assert (
        feeds_by_id[885]["marketSchedules"][0]["benchmarkMapping"][
            "datascope_ric"
        ]["identifiers"][0]["identifier"]
        == "STALE.HK"
    )
    # Feed 886: no CSV match, left empty.
    assert (
        feeds_by_id[886]["marketSchedules"][0]["benchmarkMapping"][
            "datascope_ric"
        ]["identifiers"][0]["identifier"]
        == ""
    )
    # Non-HK feed untouched.
    assert feeds_by_id[1000]["symbol"] == "Crypto.BTC/USD"

    out = result.stdout + result.stderr
    # Summary mentions the unmatched CSV row's ticker (1211) — it wasn't found.
    assert "1211" in out or "1211.HK" in out
    # Summary mentions the stale-skip warning for 885.
    assert "885" in out


def test_cli_set_ric_mapping_requires_from_csv(tmp_path):
    config = tmp_path / "after.json"
    shutil.copy(FIXTURES / "hk_sample.json", config)
    result = _run_cli(
        ["--config", str(config), "--set-ric-mapping"]
    )
    assert result.returncode != 0
    assert "--from-csv" in (result.stdout + result.stderr)
```

- [ ] **Step 3: Run tests to verify they fail**

```
cd tools/edit-config && python3 -m pytest tests/test_edit_config_cli.py -v -k ric_mapping
```

Expected: failures — flag not implemented yet.

- [ ] **Step 4: Add CLI flags**

In `tools/edit-config/edit_config.py`, inside `_build_parser`:

Add to the `op_group` (mutually exclusive):

```python
    op_group.add_argument(
        "--set-ric-mapping",
        action="store_true",
        help="Fill empty datascope_ric.identifier values from a CSV (use --from-csv).",
    )
```

Then add the supporting arg outside the mutex group (since `--from-csv` only pairs with `--set-ric-mapping`):

```python
    p.add_argument(
        "--from-csv",
        type=str,
        help="CSV path for --set-ric-mapping (LSEG-style: requires Ticker, RIC, Exchange Code columns).",
    )
```

- [ ] **Step 5: Wire op construction**

In `tools/edit-config/edit_config_lib/config_editor.py`:

Import the new pieces at the top of the file (with the other imports):

```python
from edit_config_lib.config_ops import (
    AddPublisher,
    RemovePublisher,
    SetMinPublishers,
    BumpMinPublishers,
    SetState,
    SetRicMapping,
)
from edit_config_lib.ric_csv import load_ric_csv, build_prefix_index, LoadError
```

Extend `_OP_FLAGS`:

```python
_OP_FLAGS = (
    "add_publisher",
    "remove_publisher",
    "set_min_publishers",
    "bump_min_publishers",
    "set_state",
    "set_ric_mapping",
)
```

In `build_op_from_args`, handle `set_ric_mapping`. Because this op derives its own targeting from the CSV, it must NOT call `_build_filters_from_args` (which requires a selector). Implement a no-op filter set just for this op, or — simpler — let the op match everything and let its own per-feed prefix check do the filtering.

Refactor `build_op_from_args`:

```python
def build_op_from_args(args) -> list[PlannedOp]:
    selected = [name for name in _OP_FLAGS if _flag_set(args, name)]
    if not selected:
        raise ValueError(
            "no operation specified (use one of --add-publisher, "
            "--remove-publisher, --set-min-publishers, "
            "--bump-min-publishers, --set-state, --set-ric-mapping)"
        )
    if len(selected) > 1:
        raise ValueError(f"exactly one operation flag allowed; got {selected}")

    name = selected[0]

    if name == "set_ric_mapping":
        if not args.from_csv:
            raise ValueError("--set-ric-mapping requires --from-csv PATH")
        try:
            entries = load_ric_csv(args.from_csv)
        except LoadError as e:
            raise ValueError(str(e))
        prefix_to_ric = build_prefix_index(entries)
        if not prefix_to_ric:
            raise ValueError(
                f"--from-csv {args.from_csv}: no rows produced a known feed prefix "
                f"(v1 supports HK rows only)"
            )
        op = SetRicMapping(prefix_to_ric=prefix_to_ric)
        # Empty/no-op filter: match every feed; the op decides per-feed.
        filters = FilterSet()
        filters.feed_ids = None
        # Bypass validate() — set_ric_mapping uses CSV for targeting.
        return [PlannedOp(op=op, filters=filters)]

    filters = _build_filters_from_args(args)

    if name == "add_publisher":
        op = AddPublisher(publisher_id=args.add_publisher, session=args.session)
    elif name == "remove_publisher":
        op = RemovePublisher(publisher_id=args.remove_publisher, session=args.session)
    elif name == "set_min_publishers":
        op = SetMinPublishers(value=args.set_min_publishers, session=args.session)
    elif name == "bump_min_publishers":
        delta = _parse_signed_int(args.bump_min_publishers)
        op = BumpMinPublishers(delta=delta, session=args.session)
    elif name == "set_state":
        op = SetState(value=args.set_state)
    else:
        raise AssertionError(f"unhandled op {name}")

    return [PlannedOp(op=op, filters=filters)]


def _flag_set(args, name: str) -> bool:
    """True iff the op flag was provided. set_ric_mapping is boolean; others are values."""
    val = getattr(args, name, None)
    if name == "set_ric_mapping":
        return bool(val)
    return val is not None
```

Replace the existing `selected = ...` line at the top of `build_op_from_args` with the new `_flag_set`-based version.

The `FilterSet` instance used for `set_ric_mapping` must match all feeds. Look at `resolve_targets` / `FilterSet.matches`: when all fields are None, `matches` returns True for everything. The `validate()` call is only made by `_build_filters_from_args` — we skip it intentionally for this op.

However, `simulate_plan` will then iterate every feed. That's fine — the op's own `apply` returns `[], []` for non-matching symbols, so the work is proportional to total feeds (~3.3k), which is negligible. But `simulate_plan` will emit an error if `matched_counts[idx] == 0`. For `set_ric_mapping`, all feeds match the filter, so that's not an issue. But it WILL flag "operation #N matched 3.3k feeds" — that's misleading. Acceptable for v1; address only if it causes confusion.

Also: `simulate_plan` skips INACTIVE feeds for non-SetState ops. For `set_ric_mapping`, that's fine — INACTIVE feeds shouldn't be touched.

- [ ] **Step 6: Run all tests**

```
cd tools/edit-config && python3 -m pytest -v
```

Expected: all tests PASS.

- [ ] **Step 7: Commit**

```bash
git add tools/edit-config/edit_config.py tools/edit-config/edit_config_lib/config_editor.py tools/edit-config/tests/fixtures/hk_sample.json tools/edit-config/tests/test_edit_config_cli.py
git commit -m "feat: --set-ric-mapping --from-csv CLI flag"
```

---

## Task 9: Summary output — list unmatched CSV rows

**Files:**

- Modify: `tools/edit-config/edit_config_lib/config_editor.py` (or `config_diff.py` — whichever module formats the summary printed to stdout)

- [ ] **Step 1: Locate where the summary is printed**

```
cd tools/edit-config && grep -rn "matched" edit_config.py edit_config_lib/
```

The summary printer lives in `config_diff.py` (`render_diff`) or in `edit_config.py`'s main. Read whichever file is responsible.

- [ ] **Step 2: Add unmatched-CSV-row reporting**

When the op is `SetRicMapping`, after the standard summary, print:

```
RIC mapping summary:
  identifiers filled:  <N>  (feeds: ...)
  identifiers skipped: <N>  (already populated — see warnings above)
  CSV rows unmatched:  <N>  (RICs: 1211.HK, ...)
```

The unmatched-CSV calculation: from the prefix index, subtract the prefixes consumed by `Change` records. The simplest implementation is to attach the full prefix→ric mapping to the op instance (it already is), then in the summary code do:

```python
def _set_ric_summary(op, changes):
    consumed = {c.after for c in changes if c.location == "datascope_ric_identifier"}
    unmatched = sorted(
        ric for ric in op.prefix_to_ric.values() if ric not in consumed
    )
    return unmatched
```

Wire this into the existing summary printer with an `isinstance(planned.op, SetRicMapping)` check. Include the unmatched list in stdout so the CLI tests in Task 8 can assert on it (the test already expects `1211` in output).

- [ ] **Step 3: Re-run CLI tests**

```
cd tools/edit-config && python3 -m pytest tests/test_edit_config_cli.py -v -k ric_mapping
```

Expected: all PASS.

- [ ] **Step 4: Commit**

```bash
git add tools/edit-config/edit_config_lib/config_editor.py tools/edit-config/edit_config_lib/config_diff.py
git commit -m "feat: report unmatched CSV rows in --set-ric-mapping summary"
```

---

## Task 10: YAML spec support

**Files:**

- Modify: `tools/edit-config/edit_config_lib/config_editor.py`
- Modify: `tools/edit-config/tests/test_config_editor.py` (or a YAML-spec-specific test file if one exists)

- [ ] **Step 1: Write failing test**

Add to whichever test file covers `parse_yaml_spec`:

```python
def test_parse_yaml_spec_set_ric_mapping(tmp_path):
    from edit_config_lib.config_editor import parse_yaml_spec

    csv_path = (
        Path(__file__).parent / "fixtures" / "hk-syms-sample.csv"
    )
    spec = tmp_path / "spec.yaml"
    spec.write_text(
        f"version: 1\noperations:\n  - op: set_ric_mapping\n    from_csv: {csv_path}\n",
        encoding="utf-8",
    )
    planned = parse_yaml_spec(str(spec))
    assert len(planned) == 1
    from edit_config_lib.config_ops import SetRicMapping
    assert isinstance(planned[0].op, SetRicMapping)
    assert "Equity.HK.0700-HK/" in planned[0].op.prefix_to_ric
```

- [ ] **Step 2: Run to verify it fails**

```
cd tools/edit-config && python3 -m pytest -v -k yaml_spec_set_ric_mapping
```

Expected: ValueError (`unknown op 'set_ric_mapping'`).

- [ ] **Step 3: Wire YAML spec**

In `tools/edit-config/edit_config_lib/config_editor.py`:

Extend `_OP_REQUIRED_FIELDS`:

```python
_OP_REQUIRED_FIELDS = {
    "add_publisher": {"publisher_id"},
    "remove_publisher": {"publisher_id"},
    "set_min_publishers": {"value"},
    "bump_min_publishers": {"delta"},
    "set_state": {"value"},
    "set_ric_mapping": {"from_csv"},
}
```

Extend `_build_op_from_yaml_entry`:

```python
    if op_name == "set_ric_mapping":
        try:
            entries = load_ric_csv(entry["from_csv"])
        except LoadError as e:
            raise ValueError(str(e))
        prefix_to_ric = build_prefix_index(entries)
        if not prefix_to_ric:
            raise ValueError(
                f"set_ric_mapping from_csv {entry['from_csv']!r}: no rows produced a known feed prefix"
            )
        return SetRicMapping(prefix_to_ric=prefix_to_ric)
```

Extend `_filters_from_yaml_entry` to allow `set_ric_mapping` entries with no targeting fields. The cleanest way: at the top of `parse_yaml_spec`'s per-entry loop, if `entry["op"] == "set_ric_mapping"`, build a no-op `FilterSet()` directly and skip `_filters_from_yaml_entry`. Replace the body of the loop:

```python
    for i, entry in enumerate(data["operations"]):
        if not isinstance(entry, dict):
            raise ValueError(f"operation #{i + 1}: must be a mapping")
        if "op" not in entry:
            raise ValueError(f"operation #{i + 1}: missing 'op' field")
        op = _build_op_from_yaml_entry(entry)
        if entry["op"] == "set_ric_mapping":
            filters = FilterSet()
        else:
            filters = _filters_from_yaml_entry(entry)
        planned.append(PlannedOp(op=op, filters=filters))
```

- [ ] **Step 4: Run tests to verify they pass**

```
cd tools/edit-config && python3 -m pytest -v
```

Expected: all tests PASS.

- [ ] **Step 5: Commit**

```bash
git add tools/edit-config/edit_config_lib/config_editor.py tools/edit-config/tests/test_config_editor.py
git commit -m "feat: YAML spec support for set_ric_mapping op"
```

---

## Task 11: Documentation

**Files:**

- Modify: `tools/edit-config/README.md`
- Modify: `docs/edit_config.md`

- [ ] **Step 1: Update `docs/edit_config.md`**

Add a new section near the other operation docs:

````markdown
### `--set-ric-mapping` — fill empty `datascope_ric` identifiers

Backfills `marketSchedules[].benchmarkMapping.datascope_ric.identifiers[].identifier`
values from an LSEG-style CSV. Useful when feeds are bootstrapped with
empty identifier strings and the RICs are delivered separately.

```bash
python3 tools/edit-config/edit_config.py \
    --config after.json \
    --set-ric-mapping \
    --from-csv hk-syms.csv \
    --dry-run
```

CSV requires `Ticker`, `RIC`, and `Exchange Code` columns. v1 supports
HK equities only — rows whose RIC does not map to a known feed-symbol
prefix are reported as unmatched.

Per-slot rules:

- Empty `identifier` -> filled with the CSV RIC.
- Non-empty `identifier` -> skipped (warning emitted, NEVER overwritten).
- Feed symbol unmatched in CSV -> feed left untouched.
- CSV row unmatched against any feed -> reported in summary.

YAML spec form:

```yaml
version: 1
operations:
  - op: set_ric_mapping
    from_csv: hk-syms.csv
```
````

- [ ] **Step 2: Update `tools/edit-config/README.md`**

Add a one-paragraph mention + example invocation under the existing operation list.

- [ ] **Step 3: Commit**

```bash
git add docs/edit_config.md tools/edit-config/README.md
git commit -m "docs: document --set-ric-mapping operation"
```

---

## Task 12: Smoke test against the real config

**Files:** none modified; verification only.

- [ ] **Step 1: Dry-run against `after.promoted.2026-05-15.json`**

```
python3 tools/edit-config/edit_config.py \
    --config after.promoted.2026-05-15.json \
    --set-ric-mapping \
    --from-csv hk-syms.csv \
    --dry-run | tee /tmp/ric_dry_run.txt
```

Verify:

- Reports ~89 identifiers filled (one per CSV row that matches a feed).
- Reports ~7 unmatched CSV rows OR ~7 feeds without a CSV match (the spec says 89 CSV vs 96 feeds — confirm which side has surplus).
- Does NOT modify the file.

- [ ] **Step 2: Apply against a copy and inspect the diff**

```
cp after.promoted.2026-05-15.json /tmp/after.copy.json
python3 tools/edit-config/edit_config.py \
    --config /tmp/after.copy.json \
    --set-ric-mapping \
    --from-csv hk-syms.csv
diff after.promoted.2026-05-15.json /tmp/after.copy.json | head -100
```

Verify: every diff hunk is a single-line `"identifier": ""` → `"identifier": "NNNN.HK"` swap. No other lines move.

- [ ] **Step 3: Run pre-commit**

```
pre-commit run --files \
    tools/edit-config/edit_config.py \
    tools/edit-config/edit_config_lib/config_ops.py \
    tools/edit-config/edit_config_lib/config_editor.py \
    tools/edit-config/edit_config_lib/config_text_surgery.py \
    tools/edit-config/edit_config_lib/ric_csv.py \
    tools/edit-config/tests/test_ric_csv.py \
    tools/edit-config/tests/test_config_ops.py \
    tools/edit-config/tests/test_config_text_surgery.py \
    tools/edit-config/tests/test_config_editor.py \
    tools/edit-config/tests/test_edit_config_cli.py \
    tools/edit-config/README.md \
    docs/edit_config.md
```

Expected: all hooks pass (black, prettier, trailing whitespace).

- [ ] **Step 4: No final commit needed** unless pre-commit auto-fixed something; in that case:

```bash
git add -u
git commit -m "chore: pre-commit fixups"
```

---

## Self-Review

**Spec coverage:** Every spec section is covered:

- Operation + CLI shape -> Tasks 4, 6, 8
- HK matching rule -> Task 2
- Skip-non-empty, skip-no-match semantics -> Task 5/6
- Dry-run summary with unmatched rows -> Task 9
- Edge cases (multi-schedule, missing structure, duplicate RIC, empty CSV) -> Tasks 1, 5
- YAML spec support -> Task 10
- Tests (op unit, CLI integration, fixtures) -> Tasks 1, 5, 7, 8, 10
- Docs -> Task 11
- Acceptance (byte-minimal diff, real-file smoke) -> Task 12

**Placeholder scan:** No TODOs, no "add error handling", every code-bearing step shows actual code. The "locate where the summary is printed" step (Task 9 Step 1) is a one-grep inspection, not a placeholder — the grep command is provided.

**Type consistency:** `Change(location="datascope_ric_identifier", field="identifier", index=N)` is consistent across Tasks 4, 5, 6, 7. `SetRicMapping(prefix_to_ric=...)` is consistent across Tasks 5, 6, 8, 10. `RicEntry`, `load_ric_csv`, `derive_symbol_prefix`, `build_prefix_index`, `LoadError` are consistent across Tasks 1, 2, 8, 10. `find_ric_identifier_spans()` returns `list[tuple[int, int, str]]` consistently in Tasks 3 and 7.
