# Publisher Asset Map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `publisher_asset_map.py` — a script that maps, for one UTC date, what every publisher published (feed-level detail + summary + matrix CSVs).

**Architecture:** Extract the asset-class categorization currently embedded in `publisher_feeds.py` into a shared `lib/asset_class.py`, then build a thin CLI script that runs one grouped `publisher_updates` aggregation, joins publisher names from `publishers_metadata_latest`, categorizes each feed's asset class, and writes three CSVs.

**Tech Stack:** Python 3, `clickhouse_connect`, `pytest`. Reuses `lib/config.py` for config + Lazer client.

## Global Constraints

- Use `python3`, not `python` (no `python` on this system; activate venv for `pytest`/`pre-commit`).
- ClickHouse parameterized queries use `{name:String}` / `{name:DateTime}` syntax with `client.query(query, parameters=dict)`.
- Date scope is a full UTC day: `[<date> 00:00:00, <date+1> 00:00:00)`.
- Pure functions go in `lib/`; scripts are thin CLI wrappers (repo convention).
- Tests live in `tests/test_<name>.py`, importing from `lib.<module>`.
- Run `pre-commit run --files <changed files>` before each commit (black + prettier + whitespace). If `pre-commit` is unavailable, run `black <files>` from the venv instead.
- Output CSVs default to `output_csv/`.

---

### Task 1: Extract asset-class categorization into `lib/asset_class.py`

Move `EQUITY_COUNTRY_MAP`, `get_equity_country`, and `categorize_asset_class` out of `publisher_feeds.py` into a shared module, with tests. `publisher_feeds.py` then imports them (behavior unchanged).

**Files:**
- Create: `lib/asset_class.py`
- Create: `tests/test_asset_class.py`
- Modify: `publisher_feeds.py` (remove the three definitions + `EQUITY_COUNTRY_MAP`, lines ~38–114; add an import)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `EQUITY_COUNTRY_MAP: dict[str, str]`
  - `get_equity_country(symbol: Optional[str]) -> str`
  - `categorize_asset_class(asset_type: str, symbol: Optional[str]) -> str`

- [ ] **Step 1: Write the failing test**

Create `tests/test_asset_class.py`:

```python
from lib.asset_class import categorize_asset_class, get_equity_country


class TestGetEquityCountry:
    def test_no_suffix_defaults_us(self):
        assert get_equity_country("AAPL") == "us"

    def test_none_defaults_us(self):
        assert get_equity_country(None) == "us"

    def test_empty_defaults_us(self):
        assert get_equity_country("") == "us"

    def test_london_suffix(self):
        assert get_equity_country("VOD.L") == "gb"

    def test_hong_kong_suffix(self):
        assert get_equity_country("0700.HK") == "hk"

    def test_case_insensitive_suffix(self):
        assert get_equity_country("vod.l") == "gb"


class TestCategorizeAssetClass:
    def test_equity_gets_country_suffix(self):
        assert categorize_asset_class("equity", "AAPL") == "equity-us"

    def test_equity_london(self):
        assert categorize_asset_class("equity", "VOD.L") == "equity-gb"

    def test_non_equity_passthrough(self):
        assert categorize_asset_class("metal", "XAU/USD") == "metal"

    def test_fx_passthrough(self):
        assert categorize_asset_class("fx", "EUR/USD") == "fx"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_asset_class.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lib.asset_class'`

- [ ] **Step 3: Create `lib/asset_class.py`**

Move the block verbatim from `publisher_feeds.py`. The full content:

```python
"""Asset-class categorization shared across publisher scripts.

Equities are categorized by ISO country code (3166-1 alpha-2) based on
symbol suffix; all other asset types pass through unchanged.
"""

from typing import Optional

# Symbol suffix to ISO country code mapping for equities
EQUITY_COUNTRY_MAP = {
    # US exchanges (typically no suffix, but some may have these)
    ".N": "us",  # NYSE
    ".OQ": "us",  # NASDAQ
    ".A": "us",  # AMEX
    # European exchanges
    ".L": "gb",  # London Stock Exchange
    ".PA": "fr",  # Euronext Paris
    ".DE": "de",  # Deutsche Börse (Xetra)
    ".AS": "nl",  # Euronext Amsterdam
    ".MI": "it",  # Borsa Italiana (Milan)
    ".MC": "es",  # Bolsa de Madrid
    ".SW": "ch",  # SIX Swiss Exchange
    ".BR": "be",  # Euronext Brussels
    ".VI": "at",  # Vienna Stock Exchange
    ".ST": "se",  # Nasdaq Stockholm
    ".HE": "fi",  # Nasdaq Helsinki
    ".CO": "dk",  # Nasdaq Copenhagen
    ".OL": "no",  # Oslo Stock Exchange
    ".LS": "pt",  # Euronext Lisbon
    ".IR": "ie",  # Euronext Dublin
    ".WA": "pl",  # Warsaw Stock Exchange
    # Asia-Pacific exchanges
    ".HK": "hk",  # Hong Kong Stock Exchange
    ".T": "jp",  # Tokyo Stock Exchange
    ".SS": "cn",  # Shanghai Stock Exchange
    ".SZ": "cn",  # Shenzhen Stock Exchange
    ".KS": "kr",  # Korea Stock Exchange
    ".KQ": "kr",  # KOSDAQ
    ".TW": "tw",  # Taiwan Stock Exchange
    ".SI": "sg",  # Singapore Exchange
    ".AX": "au",  # Australian Securities Exchange
    ".NZ": "nz",  # New Zealand Exchange
    ".BO": "in",  # Bombay Stock Exchange
    ".NS": "in",  # National Stock Exchange of India
    ".BK": "th",  # Stock Exchange of Thailand
    ".JK": "id",  # Indonesia Stock Exchange
    ".KL": "my",  # Bursa Malaysia
    # Other regions
    ".SA": "br",  # B3 (Brazil)
    ".MX": "mx",  # Mexican Stock Exchange
    ".J": "za",  # Johannesburg Stock Exchange
}


def get_equity_country(symbol: Optional[str]) -> str:
    """Determine equity country code from symbol suffix.

    Returns ISO country code (us, gb, hk, jp, etc.) or 'us' as default
    for plain symbols without suffix.
    """
    if not symbol:
        return "us"  # Default to US if no symbol

    # Check for known suffixes
    for suffix, country in EQUITY_COUNTRY_MAP.items():
        if symbol.upper().endswith(suffix.upper()):
            return country

    # Plain symbols without suffix are assumed to be US equities
    # (most common case for feeds like AAPL, MSFT, etc.)
    return "us"


def categorize_asset_class(asset_type: str, symbol: Optional[str]) -> str:
    """Categorize asset class, adding country suffix for equities.

    For equity assets, returns 'equity-{country}' based on symbol pattern.
    For other assets, returns the original asset_type.
    """
    if asset_type == "equity":
        country = get_equity_country(symbol)
        return f"equity-{country}"
    return asset_type
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_asset_class.py -v`
Expected: PASS (10 passed)

- [ ] **Step 5: Update `publisher_feeds.py` to import from the new module**

In `publisher_feeds.py`, delete `EQUITY_COUNTRY_MAP`, `get_equity_country`, and `categorize_asset_class` (the block roughly lines 38–114), and delete the now-unused `from typing import Optional` only if no other usage remains (it is still used in function signatures — keep it). Add this import near the other top-level imports:

```python
from lib.asset_class import categorize_asset_class
```

(`get_equity_country` and `EQUITY_COUNTRY_MAP` are only used internally by `categorize_asset_class`, so the script needs only that import.)

- [ ] **Step 6: Verify `publisher_feeds.py` still imports cleanly**

Run: `python3 -c "import publisher_feeds; print('ok')"`
Expected: prints `ok` (no ImportError, no NameError)

- [ ] **Step 7: Commit**

```bash
pre-commit run --files lib/asset_class.py tests/test_asset_class.py publisher_feeds.py || black lib/asset_class.py tests/test_asset_class.py publisher_feeds.py
git add lib/asset_class.py tests/test_asset_class.py publisher_feeds.py
git commit -m "refactor(asset-class): extract categorization into lib/asset_class.py

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Pure helpers — date window, summary, matrix

Build the pure (DB-free) functions the script needs: UTC day-window bounds, long-form summary rollup, and matrix pivot. Test them in isolation.

**Files:**
- Create: `lib/publisher_asset_map_core.py`
- Create: `tests/test_publisher_asset_map_core.py`

**Interfaces:**
- Consumes: `lib.asset_class.categorize_asset_class` (Task 1).
- Produces:
  - `@dataclass PublisherFeedRow` with fields `publisher_id: int`, `publisher_name: str`, `feed_id: int`, `symbol: str`, `asset_class: str`, `update_count: int`
  - `day_window(date_str: str) -> tuple[str, str]` → `("<date> 00:00:00", "<date+1> 00:00:00")`
  - `build_summary(rows: list[PublisherFeedRow]) -> list[dict]` → one dict per (publisher_id, asset_class) with keys `publisher_id, publisher_name, asset_class, feed_count, total_updates`, sorted by `(publisher_id, asset_class)`
  - `build_matrix(rows: list[PublisherFeedRow]) -> tuple[list[str], list[dict]]` → `(asset_class_columns_sorted, matrix_rows)` where each matrix row is `{publisher_id, publisher_name, <asset_class>: feed_count, ...}` with 0 for absent classes, sorted by `publisher_id`

- [ ] **Step 1: Write the failing test**

Create `tests/test_publisher_asset_map_core.py`:

```python
from lib.publisher_asset_map_core import (
    PublisherFeedRow,
    build_matrix,
    build_summary,
    day_window,
)


def _rows():
    return [
        PublisherFeedRow(32, "Blueocean.Production", 1163, "AAPL", "equity-us", 100),
        PublisherFeedRow(32, "Blueocean.Production", 1164, "MSFT", "equity-us", 50),
        PublisherFeedRow(32, "Blueocean.Production", 345, "XAU/USD", "metal", 20),
        PublisherFeedRow(11, "Amber.Production", 345, "XAU/USD", "metal", 7),
    ]


class TestDayWindow:
    def test_basic_day(self):
        assert day_window("2026-06-23") == (
            "2026-06-23 00:00:00",
            "2026-06-24 00:00:00",
        )

    def test_month_rollover(self):
        assert day_window("2026-06-30") == (
            "2026-06-30 00:00:00",
            "2026-07-01 00:00:00",
        )


class TestBuildSummary:
    def test_groups_by_publisher_and_class(self):
        summary = build_summary(_rows())
        assert {
            "publisher_id": 32,
            "publisher_name": "Blueocean.Production",
            "asset_class": "equity-us",
            "feed_count": 2,
            "total_updates": 150,
        } in summary

    def test_metal_rollup(self):
        summary = build_summary(_rows())
        metal_32 = [
            r for r in summary if r["publisher_id"] == 32 and r["asset_class"] == "metal"
        ]
        assert metal_32[0]["feed_count"] == 1
        assert metal_32[0]["total_updates"] == 20

    def test_sorted_by_publisher_then_class(self):
        summary = build_summary(_rows())
        keys = [(r["publisher_id"], r["asset_class"]) for r in summary]
        assert keys == sorted(keys)


class TestBuildMatrix:
    def test_columns_are_sorted_classes(self):
        cols, _ = build_matrix(_rows())
        assert cols == ["equity-us", "metal"]

    def test_absent_class_is_zero(self):
        _, matrix = build_matrix(_rows())
        amber = [r for r in matrix if r["publisher_id"] == 11][0]
        assert amber["equity-us"] == 0
        assert amber["metal"] == 1

    def test_feed_counts(self):
        _, matrix = build_matrix(_rows())
        blue = [r for r in matrix if r["publisher_id"] == 32][0]
        assert blue["equity-us"] == 2
        assert blue["metal"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_publisher_asset_map_core.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lib.publisher_asset_map_core'`

- [ ] **Step 3: Implement `lib/publisher_asset_map_core.py`**

```python
"""Pure helpers for publisher_asset_map: day windows and rollups."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass
class PublisherFeedRow:
    """One (publisher, feed) contribution on the analyzed date."""

    publisher_id: int
    publisher_name: str
    feed_id: int
    symbol: str
    asset_class: str
    update_count: int


def day_window(date_str: str) -> tuple[str, str]:
    """Return [start, end) ClickHouse DateTime strings for the full UTC day."""
    start = date.fromisoformat(date_str)
    end = start + timedelta(days=1)
    return (f"{start.isoformat()} 00:00:00", f"{end.isoformat()} 00:00:00")


def build_summary(rows: list[PublisherFeedRow]) -> list[dict]:
    """One row per (publisher_id, asset_class) with feed_count and total_updates."""
    feed_count: dict[tuple[int, str], int] = defaultdict(int)
    total_updates: dict[tuple[int, str], int] = defaultdict(int)
    names: dict[int, str] = {}
    for r in rows:
        key = (r.publisher_id, r.asset_class)
        feed_count[key] += 1
        total_updates[key] += r.update_count
        names[r.publisher_id] = r.publisher_name

    out = [
        {
            "publisher_id": pub_id,
            "publisher_name": names[pub_id],
            "asset_class": asset_class,
            "feed_count": feed_count[(pub_id, asset_class)],
            "total_updates": total_updates[(pub_id, asset_class)],
        }
        for (pub_id, asset_class) in feed_count
    ]
    out.sort(key=lambda r: (r["publisher_id"], r["asset_class"]))
    return out


def build_matrix(rows: list[PublisherFeedRow]) -> tuple[list[str], list[dict]]:
    """Wide pivot: publisher rows, one column per asset class (feed counts)."""
    classes = sorted({r.asset_class for r in rows})
    counts: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    names: dict[int, str] = {}
    for r in rows:
        counts[r.publisher_id][r.asset_class] += 1
        names[r.publisher_id] = r.publisher_name

    matrix = []
    for pub_id in sorted(counts):
        row = {"publisher_id": pub_id, "publisher_name": names[pub_id]}
        for cls in classes:
            row[cls] = counts[pub_id].get(cls, 0)
        matrix.append(row)
    return classes, matrix
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_publisher_asset_map_core.py -v`
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
pre-commit run --files lib/publisher_asset_map_core.py tests/test_publisher_asset_map_core.py || black lib/publisher_asset_map_core.py tests/test_publisher_asset_map_core.py
git add lib/publisher_asset_map_core.py tests/test_publisher_asset_map_core.py
git commit -m "feat(asset-map): add day-window, summary, and matrix helpers

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Data layer — query publisher_updates + publisher names

Add DB functions to `lib/publisher_asset_map_core.py`: fetch publisher names, run the grouped query, and assemble `PublisherFeedRow` objects with categorized asset classes and the optional asset-class filter. The ClickHouse client is passed in (so it is mockable in tests).

**Files:**
- Modify: `lib/publisher_asset_map_core.py`
- Modify: `tests/test_publisher_asset_map_core.py`

**Interfaces:**
- Consumes: `lib.asset_class.categorize_asset_class`; `day_window` (Task 2); a ClickHouse client exposing `.query(sql, parameters=dict)` returning an object with `.result_rows`.
- Produces:
  - `fetch_publisher_names(client) -> dict[int, str]`
  - `fetch_publisher_feeds(client, date_str: str, asset_class_filter: Optional[str] = None) -> list[PublisherFeedRow]`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_publisher_asset_map_core.py`:

```python
from lib.publisher_asset_map_core import (  # noqa: E402
    fetch_publisher_feeds,
    fetch_publisher_names,
)


class _FakeResult:
    def __init__(self, rows):
        self.result_rows = rows


class _FakeClient:
    """Returns names rows for the names query, feed rows otherwise."""

    def __init__(self, name_rows, feed_rows):
        self._name_rows = name_rows
        self._feed_rows = feed_rows
        self.last_params = None

    def query(self, sql, parameters=None):
        self.last_params = parameters
        if "publishers_metadata_latest" in sql:
            return _FakeResult(self._name_rows)
        return _FakeResult(self._feed_rows)


def _client():
    return _FakeClient(
        name_rows=[(32, "Blueocean.Production"), (11, "Amber.Production")],
        feed_rows=[
            # publisher_id, feed_id, update_count, asset_type, symbol
            (32, 1163, 100, "equity", "AAPL"),
            (32, 345, 20, "metal", "XAU/USD"),
            (11, 999, 5, "equity", "VOD.L"),
            (11, 888, 3, None, None),  # no metadata -> unknown / blank
        ],
    )


class TestFetchPublisherNames:
    def test_builds_id_to_name_map(self):
        names = fetch_publisher_names(_client())
        assert names == {32: "Blueocean.Production", 11: "Amber.Production"}


class TestFetchPublisherFeeds:
    def test_categorizes_and_names(self):
        rows = fetch_publisher_feeds(_client(), "2026-06-23")
        aapl = [r for r in rows if r.feed_id == 1163][0]
        assert aapl.asset_class == "equity-us"
        assert aapl.publisher_name == "Blueocean.Production"
        assert aapl.update_count == 100

    def test_foreign_equity_country(self):
        rows = fetch_publisher_feeds(_client(), "2026-06-23")
        vod = [r for r in rows if r.feed_id == 999][0]
        assert vod.asset_class == "equity-gb"

    def test_missing_metadata_is_unknown(self):
        rows = fetch_publisher_feeds(_client(), "2026-06-23")
        orphan = [r for r in rows if r.feed_id == 888][0]
        assert orphan.asset_class == "unknown"
        assert orphan.symbol == ""

    def test_missing_publisher_name_is_blank(self):
        client = _FakeClient(
            name_rows=[],
            feed_rows=[(7, 1, 1, "fx", "EUR/USD")],
        )
        rows = fetch_publisher_feeds(client, "2026-06-23")
        assert rows[0].publisher_name == ""

    def test_passes_day_window_params(self):
        client = _client()
        fetch_publisher_feeds(client, "2026-06-23")
        assert client.last_params["start"] == "2026-06-23 00:00:00"
        assert client.last_params["end"] == "2026-06-24 00:00:00"

    def test_asset_class_filter_equity_country(self):
        rows = fetch_publisher_feeds(
            _client(), "2026-06-23", asset_class_filter="equity-us"
        )
        assert {r.feed_id for r in rows} == {1163}

    def test_asset_class_filter_plain(self):
        rows = fetch_publisher_feeds(_client(), "2026-06-23", asset_class_filter="metal")
        assert {r.feed_id for r in rows} == {345}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_publisher_asset_map_core.py -v`
Expected: FAIL with `ImportError: cannot import name 'fetch_publisher_feeds'`

- [ ] **Step 3: Implement the data functions**

Add to the top of `lib/publisher_asset_map_core.py`:

```python
from typing import Optional

from lib.asset_class import categorize_asset_class
```

Append these functions to `lib/publisher_asset_map_core.py`:

```python
def fetch_publisher_names(client) -> dict[int, str]:
    """Map publisher_id -> name from publishers_metadata_latest (live)."""
    query = """
        SELECT publisher_id, name
        FROM publishers_metadata_latest
        FINAL
    """
    result = client.query(query)
    return {int(row[0]): row[1] for row in result.result_rows}


def fetch_publisher_feeds(
    client,
    date_str: str,
    asset_class_filter: Optional[str] = None,
) -> list[PublisherFeedRow]:
    """Query one UTC day of publisher_updates, grouped per (publisher, feed)."""
    start, end = day_window(date_str)
    names = fetch_publisher_names(client)

    query = """
        SELECT
            pu.publisher_id AS publisher_id,
            pu.price_feed_id AS feed_id,
            count() AS update_count,
            fm.asset_type AS asset_type,
            fm.symbol AS symbol
        FROM publisher_updates pu
        LEFT JOIN feeds_metadata_latest fm ON pu.price_feed_id = fm.pyth_lazer_id
        WHERE pu.publish_time >= {start:DateTime}
          AND pu.publish_time <  {end:DateTime}
        GROUP BY pu.publisher_id, pu.price_feed_id, fm.asset_type, fm.symbol
        ORDER BY pu.publisher_id, fm.asset_type, pu.price_feed_id
    """
    result = client.query(query, parameters={"start": start, "end": end})

    rows: list[PublisherFeedRow] = []
    for publisher_id, feed_id, update_count, asset_type, symbol in result.result_rows:
        asset_type = asset_type or "unknown"
        symbol = symbol or ""
        asset_class = categorize_asset_class(asset_type, symbol)

        if asset_class_filter and asset_class != asset_class_filter:
            continue

        rows.append(
            PublisherFeedRow(
                publisher_id=int(publisher_id),
                publisher_name=names.get(int(publisher_id), ""),
                feed_id=int(feed_id),
                symbol=symbol,
                asset_class=asset_class,
                update_count=int(update_count),
            )
        )
    return rows
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_publisher_asset_map_core.py -v`
Expected: PASS (all tests, including the 8 from Task 2)

- [ ] **Step 5: Commit**

```bash
pre-commit run --files lib/publisher_asset_map_core.py tests/test_publisher_asset_map_core.py || black lib/publisher_asset_map_core.py tests/test_publisher_asset_map_core.py
git add lib/publisher_asset_map_core.py tests/test_publisher_asset_map_core.py
git commit -m "feat(asset-map): query publisher_updates and join publisher names

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: CSV writers

Add the three CSV writers to `lib/publisher_asset_map_core.py`, writing into a target directory with the date in each filename. Test by writing to a `tmp_path` and reading back.

**Files:**
- Modify: `lib/publisher_asset_map_core.py`
- Modify: `tests/test_publisher_asset_map_core.py`

**Interfaces:**
- Consumes: `PublisherFeedRow`, `build_summary`, `build_matrix` (Tasks 2–3).
- Produces:
  - `write_outputs(rows: list[PublisherFeedRow], date_str: str, output_dir: Path) -> list[Path]` → writes the three CSVs and returns their paths in order `[detail, summary, matrix]`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_publisher_asset_map_core.py`:

```python
import csv  # noqa: E402
from pathlib import Path  # noqa: E402

from lib.publisher_asset_map_core import write_outputs  # noqa: E402


def test_write_outputs_creates_three_csvs(tmp_path: Path):
    rows = [
        PublisherFeedRow(32, "Blueocean.Production", 1163, "AAPL", "equity-us", 100),
        PublisherFeedRow(32, "Blueocean.Production", 345, "XAU/USD", "metal", 20),
        PublisherFeedRow(11, "Amber.Production", 345, "XAU/USD", "metal", 7),
    ]
    paths = write_outputs(rows, "2026-06-23", tmp_path)

    assert [p.name for p in paths] == [
        "publisher_asset_map_2026-06-23.csv",
        "publisher_asset_map_summary_2026-06-23.csv",
        "publisher_asset_map_matrix_2026-06-23.csv",
    ]
    for p in paths:
        assert p.exists()

    with open(paths[0]) as f:
        detail = list(csv.DictReader(f))
    assert detail[0] == {
        "publisher_id": "11",
        "publisher_name": "Amber.Production",
        "feed_id": "345",
        "symbol": "XAU/USD",
        "asset_class": "metal",
        "update_count": "7",
    }

    with open(paths[2]) as f:
        matrix = list(csv.DictReader(f))
    assert matrix[0]["publisher_id"] == "11"
    assert matrix[0]["equity-us"] == "0"
    assert matrix[0]["metal"] == "1"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_publisher_asset_map_core.py::test_write_outputs_creates_three_csvs -v`
Expected: FAIL with `ImportError: cannot import name 'write_outputs'`

- [ ] **Step 3: Implement `write_outputs`**

Add `import csv` and `from pathlib import Path` to the imports at the top of `lib/publisher_asset_map_core.py`, then append:

```python
def write_outputs(
    rows: list[PublisherFeedRow],
    date_str: str,
    output_dir: Path,
) -> list[Path]:
    """Write detail, summary, and matrix CSVs. Returns their paths in order."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    detail_path = output_dir / f"publisher_asset_map_{date_str}.csv"
    summary_path = output_dir / f"publisher_asset_map_summary_{date_str}.csv"
    matrix_path = output_dir / f"publisher_asset_map_matrix_{date_str}.csv"

    sorted_rows = sorted(
        rows, key=lambda r: (r.publisher_id, r.asset_class, r.feed_id)
    )
    with open(detail_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["publisher_id", "publisher_name", "feed_id", "symbol",
             "asset_class", "update_count"]
        )
        for r in sorted_rows:
            writer.writerow(
                [r.publisher_id, r.publisher_name, r.feed_id, r.symbol,
                 r.asset_class, r.update_count]
            )

    summary = build_summary(rows)
    with open(summary_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            ["publisher_id", "publisher_name", "asset_class",
             "feed_count", "total_updates"]
        )
        for s in summary:
            writer.writerow(
                [s["publisher_id"], s["publisher_name"], s["asset_class"],
                 s["feed_count"], s["total_updates"]]
            )

    classes, matrix = build_matrix(rows)
    with open(matrix_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["publisher_id", "publisher_name", *classes])
        for m in matrix:
            writer.writerow(
                [m["publisher_id"], m["publisher_name"], *[m[c] for c in classes]]
            )

    return [detail_path, summary_path, matrix_path]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_publisher_asset_map_core.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
pre-commit run --files lib/publisher_asset_map_core.py tests/test_publisher_asset_map_core.py || black lib/publisher_asset_map_core.py tests/test_publisher_asset_map_core.py
git add lib/publisher_asset_map_core.py tests/test_publisher_asset_map_core.py
git commit -m "feat(asset-map): write detail, summary, and matrix CSVs

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: CLI script `publisher_asset_map.py`

Thin wrapper: parse args, connect, fetch rows, write CSVs, print a console summary. Handles the empty-result edge case.

**Files:**
- Create: `publisher_asset_map.py`

**Interfaces:**
- Consumes: `lib.config.load_config`, `lib.config.get_lazer_client`; `lib.publisher_asset_map_core.fetch_publisher_feeds`, `write_outputs`, `build_summary` (for the console block).
- Produces: an executable script (`__main__`); no importable API other than `main()`.

- [ ] **Step 1: Implement the script**

```python
#!/usr/bin/env python3
"""Publisher Asset Map.

For one UTC date, map what every publisher published: feed-level detail plus
per-publisher asset-class summary and matrix CSVs.

Usage:
    python3 publisher_asset_map.py --date 2026-06-23
    python3 publisher_asset_map.py --date 2026-06-23 --asset-class metal
    python3 publisher_asset_map.py --date 2026-06-23 --output-dir output_csv
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

from lib.config import get_lazer_client, load_config
from lib.publisher_asset_map_core import fetch_publisher_feeds, write_outputs


def main():
    parser = argparse.ArgumentParser(
        description="Map what every publisher published on a given UTC date",
    )
    parser.add_argument(
        "--date",
        required=True,
        metavar="YYYY-MM-DD",
        help="UTC day to analyze (full 24h window)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output_csv"),
        help="Directory for the three CSV outputs (default: output_csv)",
    )
    parser.add_argument(
        "--asset-class",
        help="Optional asset-class filter (e.g. metal, fx, equity-us)",
    )
    args = parser.parse_args()

    print(f"Querying publisher_updates for {args.date} (full UTC day)...")
    if args.asset_class:
        print(f"Asset class filter: {args.asset_class}")

    try:
        config = load_config()
        client = get_lazer_client(config)
        rows = fetch_publisher_feeds(client, args.date, args.asset_class)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error querying ClickHouse: {e}", file=sys.stderr)
        sys.exit(1)

    if not rows:
        print(
            f"\nNo publisher activity found for {args.date}. "
            "It may be a non-trading day, a future date, or not yet ingested."
        )
        sys.exit(0)

    paths = write_outputs(rows, args.date, args.output_dir)

    publishers = {r.publisher_id for r in rows}
    feeds = {r.feed_id for r in rows}
    per_class_feeds = defaultdict(set)
    for r in rows:
        per_class_feeds[r.asset_class].add(r.feed_id)

    print(f"\n{'='*50}")
    print("SUMMARY")
    print(f"{'='*50}")
    print(f"Date: {args.date}")
    print(f"Publishers seen: {len(publishers)}")
    print(f"Unique feeds: {len(feeds)}")
    print("\nFeeds by asset class (distinct feeds across all publishers):")
    for asset_class in sorted(per_class_feeds):
        print(f"  {asset_class}: {len(per_class_feeds[asset_class])}")

    print("\nWrote:")
    for p in paths:
        print(f"  {p}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Verify the script imports and shows help**

Run: `python3 publisher_asset_map.py --help`
Expected: argparse help text listing `--date`, `--output-dir`, `--asset-class` (no traceback).

- [ ] **Step 3: Verify `--date` is required**

Run: `python3 publisher_asset_map.py; echo "exit=$?"`
Expected: argparse error "the following arguments are required: --date", `exit=2`.

- [ ] **Step 4: Commit**

```bash
pre-commit run --files publisher_asset_map.py || black publisher_asset_map.py
git add publisher_asset_map.py
git commit -m "feat(asset-map): add publisher_asset_map.py CLI

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Docs + CLAUDE.md Scripts table entry

Document the script and register it in the repo's Scripts table.

**Files:**
- Create: `docs/publisher_asset_map.md`
- Modify: `CLAUDE.md` (add a row to the Scripts table)

**Interfaces:**
- Consumes: nothing (documentation only).
- Produces: nothing importable.

- [ ] **Step 1: Write `docs/publisher_asset_map.md`**

```markdown
# Publisher Asset Map

Maps what **every** publisher published on a specific UTC date, across all asset
classes. Complements `publisher_feeds.py` (which covers a single publisher in a
short rolling window) by giving a full-day, all-publisher view.

## Usage

\`\`\`bash
# Full day, all publishers
python3 publisher_asset_map.py --date 2026-06-23

# Filter to one asset class
python3 publisher_asset_map.py --date 2026-06-23 --asset-class metal

# Custom output directory
python3 publisher_asset_map.py --date 2026-06-23 --output-dir output_csv
\`\`\`

## Arguments

| Argument        | Description                                          | Default      |
| --------------- | ---------------------------------------------------- | ------------ |
| `--date`        | UTC day to analyze (`YYYY-MM-DD`), required          | -            |
| `--output-dir`  | Directory for the three CSV outputs                  | `output_csv` |
| `--asset-class` | Optional asset-class filter (e.g. `metal`, `fx`)     | All          |

## How it works

Runs one grouped aggregation over `publisher_updates` for the full UTC day
(`[date 00:00:00, date+1 00:00:00)`), joining `feeds_metadata_latest` for symbol
and asset type, then joins publisher names live from `publishers_metadata_latest`.
Equities are categorized by ISO country code from the symbol suffix
(`.L` → `equity-gb`, `.HK` → `equity-hk`, etc.; plain symbols → `equity-us`).

> **Performance:** this scans a full day of `publisher_updates` across all
> publishers — heavier than `publisher_feeds.py`'s 1-minute snapshot, but a single
> grouped aggregation ClickHouse handles well.

## Outputs

Three CSVs (with the date in each filename), written to `--output-dir`:

| File                                       | Granularity                  | Columns                                                            |
| ------------------------------------------ | ---------------------------- | ----------------------------------------------------------------- |
| `publisher_asset_map_<date>.csv`           | one row per (publisher,feed) | `publisher_id, publisher_name, feed_id, symbol, asset_class, update_count` |
| `publisher_asset_map_summary_<date>.csv`   | per (publisher, asset_class) | `publisher_id, publisher_name, asset_class, feed_count, total_updates`     |
| `publisher_asset_map_matrix_<date>.csv`    | one row per publisher        | `publisher_id, publisher_name, <one column per asset_class>` (feed counts) |

Feeds with no metadata are reported as `asset_class=unknown` with a blank symbol;
publishers with no name match get a blank `publisher_name`.
\`\`\`

(Replace the `\`\`\`` fences above with real triple-backticks when saving — they are
escaped here only to keep this plan's code block intact.)

- [ ] **Step 2: Add a row to the CLAUDE.md Scripts table**

In `CLAUDE.md`, find the Scripts table row for `publisher_report.py` and add a new row immediately after it:

\`\`\`markdown
| `publisher_asset_map.py`               | Map every publisher's feeds + asset classes for one UTC date (detail + summary + matrix CSVs)                                                  | `python3 publisher_asset_map.py --date 2026-06-23`                                                     | [docs/publisher_asset_map.md](docs/publisher_asset_map.md)               |
\`\`\`

- [ ] **Step 3: Run pre-commit (prettier) on the docs**

Run: `pre-commit run --files docs/publisher_asset_map.md CLAUDE.md || true`
Expected: prettier may reformat the Markdown tables; re-stage if it does.

- [ ] **Step 4: Commit**

```bash
git add docs/publisher_asset_map.md CLAUDE.md
git commit -m "docs(asset-map): document publisher_asset_map.py

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Full test run + manual smoke test

Confirm the whole suite passes and the script runs end-to-end against a real recent date.

**Files:** none (verification only).

- [ ] **Step 1: Run the new unit tests**

Run: `python3 -m pytest tests/test_asset_class.py tests/test_publisher_asset_map_core.py -v`
Expected: all PASS.

- [ ] **Step 2: Confirm no regression in publisher_feeds-related tests**

Run: `python3 -m pytest tests/ -q`
Expected: no new failures introduced by the refactor (compare against the pre-existing baseline; the suite passes the tests that passed before).

- [ ] **Step 3: Manual smoke test (requires `config.yaml` with live credentials)**

Run: `python3 publisher_asset_map.py --date <a recent weekday>`
Expected: prints the SUMMARY block (publishers seen, unique feeds, per-class counts) and writes three files under `output_csv/`. Spot-check the detail CSV header and a few rows; confirm the matrix CSV has one row per publisher and one column per asset class.

- [ ] **Step 4: Verify empty-date handling**

Run: `python3 publisher_asset_map.py --date 2099-01-01`
Expected: "No publisher activity found for 2099-01-01..." message, exit 0, no files written.

- [ ] **Step 5: Final confirmation**

No commit needed (verification task). If the manual smoke test surfaced issues, fix them in the relevant task's files and re-run.

---

## Notes for the implementer

- The `output_csv/` directory is untracked working output — do **not** commit generated CSVs.
- `publishers_metadata_latest` and `publisher_updates` live on the Lazer cluster (`lazer_clickhouse_prod`); `get_lazer_client` connects there.
- If `pre-commit` is not on PATH, it lives in the project venv (`source venv/bin/activate`); fall back to `black <files>` as the commands above already do.
