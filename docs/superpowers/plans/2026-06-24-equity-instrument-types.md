# Equity Instrument Types Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Label equity feeds by instrument type — `equity-<cc>-futures` for futures and `equity-perp` for perpetuals — using the authoritative `metadata.instrument_type` with an `is_futures_symbol` fallback.

**Architecture:** Two pure helpers in `lib/asset_class.py` (`parse_instrument_type`, `resolve_instrument_type`) plus an optional `instrument_type` arg on `categorize_asset_class`. `publisher_asset_map` builds a `feed_id → instrument_type` map once per run from `feeds_metadata_latest.metadata` and threads it into categorization. `publisher_feeds.py` is untouched (it doesn't pass the new arg).

**Tech Stack:** Python 3 (`json`), `clickhouse_connect`, `pytest`. Reuses `lib/symbol_utils.is_futures_symbol`.

## Global Constraints

- Use `python3`, not `python`. Run tests with `python3 -m pytest`. Activate venv (`source venv/bin/activate`) for `pytest`/`pre-commit`.
- Labels: `spot` → `equity-<country>`; `future` → `equity-<country>-futures`; `perp` → `equity-perp`; `index` → falls through to `equity-<country>` (which yields `equity-index` for `Equity.Index.*`). `<country>` from existing `get_equity_country`.
- Resolution: `instrument_type` = metadata value if present, else `future` if `is_futures_symbol(symbol)` else `spot`.
- `categorize_asset_class(asset_type, symbol, instrument_type=None)` — default `None` MUST preserve today's behavior (so `publisher_feeds.py` is unaffected).
- Metadata JSON shape: `{"items": [{"key": "<k>", "value": {"stringValue": "<v>"}}, ...]}`.
- Equities only; non-equity asset types pass through unchanged.
- Run `pre-commit run --files <changed files>` before each commit (or `black <files>` if unavailable). Markdown must pass prettier.
- Branch: `feat/equity-instrument-types`.

---

### Task 1: `parse_instrument_type` + `resolve_instrument_type` (`lib/asset_class.py`)

Add two pure helpers: extract `instrument_type` from the metadata JSON, and resolve it (with heuristic fallback).

**Files:**

- Modify: `lib/asset_class.py` (imports + 2 functions)
- Modify: `tests/test_asset_class.py` (add a test class)

**Interfaces:**

- Consumes: `lib.symbol_utils.is_futures_symbol`.
- Produces:

  - `parse_instrument_type(metadata_json: str) -> Optional[str]` — the `instrument_type` `stringValue`, or `None` if absent/empty/malformed.
  - `resolve_instrument_type(raw: Optional[str], symbol: str) -> str` — `raw` if truthy, else `"future"`/`"spot"` from `is_futures_symbol`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_asset_class.py`:

```python
class TestInstrumentType:
    def test_parse_present(self):
        from lib.asset_class import parse_instrument_type

        meta = '{"items":[{"key":"asset_type","value":{"stringValue":"equity"}},{"key":"instrument_type","value":{"stringValue":"future"}}]}'
        assert parse_instrument_type(meta) == "future"

    def test_parse_perp(self):
        from lib.asset_class import parse_instrument_type

        meta = '{"items":[{"key":"instrument_type","value":{"stringValue":"perp"}}]}'
        assert parse_instrument_type(meta) == "perp"

    def test_parse_absent_key(self):
        from lib.asset_class import parse_instrument_type

        meta = '{"items":[{"key":"asset_type","value":{"stringValue":"equity"}}]}'
        assert parse_instrument_type(meta) is None

    def test_parse_empty_or_malformed(self):
        from lib.asset_class import parse_instrument_type

        assert parse_instrument_type("") is None
        assert parse_instrument_type("not json") is None

    def test_resolve_present_passthrough(self):
        from lib.asset_class import resolve_instrument_type

        assert resolve_instrument_type("spot", "Equity.DE.MUV2/EUR") == "spot"
        assert resolve_instrument_type("perp", "Pyth.DC.AAPL/USDT") == "perp"

    def test_resolve_missing_uses_heuristic(self):
        from lib.asset_class import resolve_instrument_type

        assert resolve_instrument_type(None, "Equity.US.DMM6/USD") == "future"
        assert resolve_instrument_type(None, "Equity.US.ANSS/USD") == "spot"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_asset_class.py::TestInstrumentType -v`
Expected: FAIL with `ImportError: cannot import name 'parse_instrument_type'`.

- [ ] **Step 3: Implement the helpers**

In `lib/asset_class.py`, add to the imports at the top (after `from typing import Optional`):

```python
import json

from lib.symbol_utils import is_futures_symbol
```

Then add these two functions (place them after `categorize_asset_class`):

```python
def parse_instrument_type(metadata_json: str) -> Optional[str]:
    """Return the ``instrument_type`` value from a feed's metadata JSON, or None.

    Metadata shape: {"items": [{"key": ..., "value": {"stringValue": ...}}, ...]}.
    """
    if not metadata_json:
        return None
    try:
        items = json.loads(metadata_json).get("items", [])
    except (json.JSONDecodeError, TypeError, AttributeError):
        return None
    for item in items:
        if item.get("key") == "instrument_type":
            return item.get("value", {}).get("stringValue")
    return None


def resolve_instrument_type(raw: Optional[str], symbol: str) -> str:
    """Resolve a feed's instrument type: metadata value if present, else heuristic."""
    if raw:
        return raw
    return "future" if is_futures_symbol(symbol) else "spot"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_asset_class.py::TestInstrumentType -v`
Expected: PASS (6 passed).

- [ ] **Step 5: Commit**

```bash
pre-commit run --files lib/asset_class.py tests/test_asset_class.py || black lib/asset_class.py tests/test_asset_class.py
git add lib/asset_class.py tests/test_asset_class.py
git commit -m "feat(asset-class): add instrument_type parse + resolve helpers

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: `instrument_type` arg on `categorize_asset_class` (`lib/asset_class.py`)

Add the optional `instrument_type` parameter and the futures/perp label mapping. Default `None` preserves current behavior.

**Files:**

- Modify: `lib/asset_class.py` (`categorize_asset_class`)
- Modify: `tests/test_asset_class.py` (add tests)

**Interfaces:**

- Consumes: `get_equity_country` (existing).
- Produces: `categorize_asset_class(asset_type, symbol, instrument_type=None)` — `perp` → `equity-perp`; `future` → `equity-<country>-futures`; otherwise `equity-<country>` (equities) or `asset_type` (non-equities).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_asset_class.py`:

```python
class TestCategorizeInstrument:
    def test_us_future(self):
        assert (
            categorize_asset_class("equity", "Equity.US.DMM6/USD", "future")
            == "equity-us-futures"
        )

    def test_hk_future(self):
        assert (
            categorize_asset_class("equity", "Equity.HK.HKHF6/HKD", "future")
            == "equity-hk-futures"
        )

    def test_perp(self):
        assert (
            categorize_asset_class("equity", "Pyth.DC.AAPL/USDT", "perp")
            == "equity-perp"
        )

    def test_spot_excludes_futures_suffix(self):
        # German collision marked spot in metadata -> stays spot equity-de
        assert (
            categorize_asset_class("equity", "Equity.DE.MUV2/EUR", "spot")
            == "equity-de"
        )

    def test_index_falls_through(self):
        assert (
            categorize_asset_class("equity", "Equity.Index.AAPL/USD", "index")
            == "equity-index"
        )

    def test_none_preserves_default(self):
        assert categorize_asset_class("equity", "Equity.US.AAPL/USD") == "equity-us"
        assert categorize_asset_class("metal", "XAU/USD") == "metal"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_asset_class.py::TestCategorizeInstrument -v`
Expected: FAIL — `categorize_asset_class()` takes 2 positional args (the 3-arg calls raise `TypeError`).

- [ ] **Step 3: Update `categorize_asset_class`**

In `lib/asset_class.py`, replace the `categorize_asset_class` function with:

```python
def categorize_asset_class(
    asset_type: str, symbol: Optional[str], instrument_type: Optional[str] = None
) -> str:
    """Categorize asset class, encoding equity instrument type when provided.

    For equities: ``perp`` -> ``equity-perp``; ``future`` ->
    ``equity-<country>-futures``; otherwise ``equity-<country>``. When
    ``instrument_type`` is None the result matches the prior country-only
    behavior. Non-equity assets return their ``asset_type`` unchanged.
    """
    if asset_type != "equity":
        return asset_type
    if instrument_type == "perp":
        return "equity-perp"
    country = get_equity_country(symbol)
    if instrument_type == "future":
        return f"equity-{country}-futures"
    return f"equity-{country}"
```

- [ ] **Step 4: Run the full asset_class suite to verify pass + no regression**

Run: `python3 -m pytest tests/test_asset_class.py -v`
Expected: PASS — new `TestCategorizeInstrument` plus all pre-existing tests (the 2-arg calls still work via the default).

- [ ] **Step 5: Commit**

```bash
pre-commit run --files lib/asset_class.py tests/test_asset_class.py || black lib/asset_class.py tests/test_asset_class.py
git add lib/asset_class.py tests/test_asset_class.py
git commit -m "feat(asset-class): instrument-type-aware equity labels (futures/perp)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Build the instrument-type map and thread it through `fetch_publisher_feeds`

Add `fetch_equity_instrument_types` and pass each feed's resolved instrument type into categorization.

**Files:**

- Modify: `lib/publisher_asset_map_core.py`
- Modify: `tests/test_publisher_asset_map_core.py`

**Interfaces:**

- Consumes: `parse_instrument_type`, `resolve_instrument_type` (Task 1); `categorize_asset_class(..., instrument_type=...)` (Task 2).
- Produces:

  - `fetch_equity_instrument_types(client) -> dict[int, str]` — `feed_id -> resolved instrument_type` for all `asset_type='equity'` feeds.
  - `fetch_publisher_feeds` passes `instrument_type=instr_types.get(feed_id)` into `categorize_asset_class`.

- [ ] **Step 1: Update the fake client and write failing tests**

In `tests/test_publisher_asset_map_core.py`, replace the existing `_FakeClient` class with this version (adds an `instr_rows` branch; `_client()` is unchanged and keeps working since `instr_rows` defaults to `[]`):

```python
class _FakeClient:
    """Names query -> name_rows; publisher_updates query -> feed_rows;
    equity-metadata query -> instr_rows."""

    def __init__(self, name_rows, feed_rows, instr_rows=None):
        self._name_rows = name_rows
        self._feed_rows = feed_rows
        self._instr_rows = instr_rows or []
        self.feed_query_count = 0

    def query(self, sql, parameters=None):
        if "publishers_metadata_latest" in sql:
            return _Result(self._name_rows)
        if "publisher_updates" in sql:
            self.feed_query_count += 1
            return _Result(self._feed_rows)
        return _Result(self._instr_rows)
```

Then append two new tests:

```python
def test_fetch_equity_instrument_types_resolves():
    from lib.publisher_asset_map_core import fetch_equity_instrument_types

    client = _FakeClient(
        name_rows=[],
        feed_rows=[],
        instr_rows=[
            (1, "Equity.US.AAPL/USD", '{"items":[{"key":"instrument_type","value":{"stringValue":"spot"}}]}'),
            (2, "Equity.US.DMH6/USD", ""),  # missing metadata -> heuristic future
            (3, "Equity.US.ANSS/USD", ""),  # missing -> heuristic spot
        ],
    )
    assert fetch_equity_instrument_types(client) == {1: "spot", 2: "future", 3: "spot"}


def test_fetch_labels_futures_and_perp():
    client = _FakeClient(
        name_rows=[(28, "MEMX.Production")],
        feed_rows=[
            (28, 5001, 9, "equity", "Equity.US.DMM6/USD"),  # future (US -> session split)
            (28, 5002, 4, "equity", "Pyth.DC.AAPL/USDT"),  # perp (not Equity.US. -> all)
        ],
        instr_rows=[
            (5001, "Equity.US.DMM6/USD", '{"items":[{"key":"instrument_type","value":{"stringValue":"future"}}]}'),
            (5002, "Pyth.DC.AAPL/USDT", '{"items":[{"key":"instrument_type","value":{"stringValue":"perp"}}]}'),
        ],
    )
    rows = fetch_publisher_feeds(client, "2026-06-23")
    fut = [r for r in rows if r.feed_id == 5001]
    perp = [r for r in rows if r.feed_id == 5002][0]
    assert fut and all(r.asset_class == "equity-us-futures" for r in fut)
    assert {r.session for r in fut} == {"premarket", "regular", "afterhours", "overnight"}
    assert perp.asset_class == "equity-perp"
    assert perp.session == "all"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_publisher_asset_map_core.py::test_fetch_equity_instrument_types_resolves tests/test_publisher_asset_map_core.py::test_fetch_labels_futures_and_perp -v`
Expected: FAIL — `fetch_equity_instrument_types` does not exist; `fetch_publisher_feeds` does not yet apply instrument types (futures/perp would be `equity-us`).

- [ ] **Step 3: Add `fetch_equity_instrument_types` and import the helpers**

In `lib/publisher_asset_map_core.py`, extend the asset_class import line. Replace:

```python
from lib.asset_class import categorize_asset_class
```

with:

```python
from lib.asset_class import (
    categorize_asset_class,
    parse_instrument_type,
    resolve_instrument_type,
)
```

Then add this function just before `fetch_publisher_feeds`:

```python
def fetch_equity_instrument_types(client) -> dict[int, str]:
    """Map feed_id -> resolved instrument_type for all equity feeds."""
    query = (
        "SELECT pyth_lazer_id, symbol, metadata "
        "FROM feeds_metadata_latest WHERE asset_type = 'equity'"
    )
    out: dict[int, str] = {}
    for feed_id, symbol, metadata in client.query(query).result_rows:
        out[int(feed_id)] = resolve_instrument_type(
            parse_instrument_type(metadata or ""), symbol or ""
        )
    return out
```

- [ ] **Step 4: Thread the map into `fetch_publisher_feeds`**

In `fetch_publisher_feeds`, after the `names = fetch_publisher_names(client)` line add:

```python
    instr_types = fetch_equity_instrument_types(client)
```

and change the categorization line from:

```python
            asset_class = categorize_asset_class(asset_type or "unknown", symbol)
```

to:

```python
            asset_class = categorize_asset_class(
                asset_type or "unknown", symbol, instr_types.get(int(feed_id))
            )
```

- [ ] **Step 5: Run the full core suite to verify pass + no regression**

Run: `python3 -m pytest tests/test_publisher_asset_map_core.py -v`
Expected: PASS — the two new tests plus all existing ones (the existing fetch tests use spot symbols with an empty `instr_rows`, so they resolve to `equity-us`/`equity-hk` as before).

- [ ] **Step 6: Commit**

```bash
pre-commit run --files lib/publisher_asset_map_core.py tests/test_publisher_asset_map_core.py || black lib/publisher_asset_map_core.py tests/test_publisher_asset_map_core.py
git add lib/publisher_asset_map_core.py tests/test_publisher_asset_map_core.py
git commit -m "feat(asset-map): label equity feeds by instrument type (futures/perp)

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Docs (`docs/asset-classes.md`)

Document the new labels and the instrument-type source, and bump the stale date.

**Files:**

- Modify: `docs/asset-classes.md`

- [ ] **Step 1: Update `docs/asset-classes.md`**

Make these edits:

1. Bump the `Last updated:` line at the top of the file to `Last updated: 2026-06-24`.

2. Add a new section after the existing equity/futures content (before "### Metal Spot RICs" if present, otherwise at the end of the equity discussion):

```markdown
### Equity Instrument Types

Equity feeds (`asset_type = equity`) are sub-labeled by **instrument type**, read
from `feeds_metadata_latest.metadata` (`instrument_type` key), falling back to the
`is_futures_symbol` symbol pattern when the metadata field is absent:

| instrument_type | label                 | example                                                                                 |
| --------------- | --------------------- | --------------------------------------------------------------------------------------- |
| `spot`          | `equity-<cc>`         | `Equity.US.AAPL/USD` → `equity-us`                                                      |
| `future`        | `equity-<cc>-futures` | `Equity.US.DMM6/USD` → `equity-us-futures`; `Equity.HK.HKHF6/HKD` → `equity-hk-futures` |
| `perp`          | `equity-perp`         | `Pyth.DC.AAPL/USDT` → `equity-perp`                                                     |
| `index`         | `equity-index`        | `Equity.Index.AAPL/USD` → `equity-index`                                                |

The metadata value is authoritative (it correctly marks spot stocks whose tickers
coincidentally match the futures pattern, e.g. `Equity.DE.MUV2/EUR`); the
`is_futures_symbol` fallback only fills feeds missing the field.
```

3. If the asset-class table near the top of the file enumerates equity labels, add `equity-<cc>-futures` and `equity-perp` to it consistent with the existing format.

- [ ] **Step 2: Prettier**

Run: `pre-commit run prettier --files docs/asset-classes.md || true`
Expected: may reformat tables; re-stage and confirm a second run reports `Passed`.

- [ ] **Step 3: Commit**

```bash
git add docs/asset-classes.md
git commit -m "docs(asset-classes): document equity instrument-type labels

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Full test run + live smoke test

**Files:** none (verification only).

- [ ] **Step 1: Run the affected unit suites**

Run: `python3 -m pytest tests/test_asset_class.py tests/test_publisher_asset_map_core.py -v`
Expected: all PASS.

- [ ] **Step 2: Full-suite regression check**

Run: `python3 -m pytest tests/ -q`
Expected: no NEW failures from this branch's work. (The pre-existing hardcoded-cwd and flaky-TTL failures live on other branches and may appear here; judge only against what passed before this work.)

- [ ] **Step 3: Live smoke test (requires `config.yaml`; ~2-3 min — run in the background if your shell times out foreground commands)**

Run:
`python3 publisher_asset_map.py --date 2026-06-23 --output-dir /private/tmp/claude-501/-Users-mariobernardi-Documents-GitHub-integration-benchmarking/2b539957-c245-44e4-8434-ea70738498da/scratchpad/asset_map_instr_out`
Expected: writes three CSVs. Verify on the detail CSV:

- `grep -oE ',equity-(us|hk|kr)-futures,' <detail.csv> | sort | uniq -c` shows market-aware futures labels.
- `grep -c ',equity-perp,' <detail.csv>` is > 0.
- `grep ',equity-de,' <detail.csv>` shows the German names (`MUV2`, `HEN3`, `PAH3`) as `equity-de` (spot), NOT `equity-de-futures`.
- Spot US equities remain `equity-us`.

- [ ] **Step 4: Verify empty-date handling**

Run: `python3 publisher_asset_map.py --date 2099-01-01`
Expected: "No publisher activity found..." message, exit 0, no files.

- [ ] **Step 5: Final confirmation**

No commit (verification only). If the live test surfaces a discrepancy (e.g. a German name labeled `-futures`, or perps still `equity-us`), fix it in the relevant task's files and re-run Steps 1-3.

---

## Notes for the implementer

- `categorize_asset_class`'s new `instrument_type` arg defaults to `None`, which reproduces the old country-only behavior — that's why `publisher_feeds.py` (which calls it with 2 args) needs no change.
- The instrument-type _resolution_ (metadata-or-heuristic) happens in `fetch_equity_instrument_types`, NOT in `categorize_asset_class` — keep that boundary so opt-out callers never hit the heuristic's spot-collision risk.
- `fetch_equity_instrument_types` runs one small query (~1.9k equity rows); it does not meaningfully affect runtime.
- Generated CSVs under the scratch/`output_csv` dir must not be committed.
