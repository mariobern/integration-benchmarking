# Publisher Asset Map — Intl Equity + Session Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Categorize equities by country from the `Equity.<CC>.` symbol prefix, and add a per-update US-equity trading-session dimension to `publisher_asset_map`'s output.

**Architecture:** Fix `get_equity_country` in shared `lib/asset_class.py` to parse the Lazer symbol prefix (suffix fallback preserved). Add a `session_case_sql` helper and a `session` field threaded through `lib/publisher_asset_map_core.py`'s query, rollups, and CSV writers; session bucketing is computed in ClickHouse via `toTimeZone(...)` using boundaries derived from `lib/sql_filters.py`.

**Tech Stack:** Python 3, `clickhouse_connect`, `pytest`. Reuses `lib/sql_filters.py` session constants and `lib/config.py`.

## Global Constraints

- Use `python3`, not `python`. Run tests with `python3 -m pytest`. Activate venv (`source venv/bin/activate`) for `pytest`/`pre-commit`.
- ClickHouse parameterized queries use `{name:DateTime}` syntax with `client.query(query, parameters=dict)`. Do NOT f-string the query body (it would clash with the `{start:DateTime}` braces); inject the session expression with `str.replace`.
- Session labels are exactly: `premarket`, `regular`, `afterhours`, `overnight`, and `all` (non-US-equity / not-session-split).
- Session bucketing applies ONLY to symbols matching `Equity.US.%`; everything else is `all`.
- ET session minute-of-day boundaries derive from `lib/sql_filters.py` constants (single source of truth): premarket 240, regular 570, afterhours 960, overnight 1200.
- Run `pre-commit run --files <changed files>` before each commit (or `black <files>` if `pre-commit` is unavailable). Markdown commits must pass prettier.
- All work lands on branch `feat/publisher-asset-map-sessions`.

---

### Task 1: Country categorization from `Equity.<CC>.` prefix (`lib/asset_class.py`)

Parse the Lazer symbol prefix in `get_equity_country`, keeping the RIC-suffix lookup as a fallback. This fixes international equities collapsing to `equity-us` in both `publisher_asset_map` and `publisher_feeds.py`.

**Files:**

- Modify: `lib/asset_class.py` (the body of `get_equity_country`)
- Modify: `tests/test_asset_class.py` (add prefix tests)

**Interfaces:**

- Consumes: nothing new.
- Produces: `get_equity_country(symbol)` now returns the country from an `Equity.<CC>.…` prefix when present; `categorize_asset_class(asset_type, symbol)` returns `equity-<cc>` accordingly (signature unchanged).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_asset_class.py`:

```python
class TestEquityPrefixCountry:
    def test_us_prefix(self):
        assert get_equity_country("Equity.US.AAPL/USD") == "us"

    def test_us_futures_prefix(self):
        assert get_equity_country("Equity.US.EMH6/USD") == "us"

    def test_hong_kong_prefix(self):
        assert get_equity_country("Equity.HK.0700/HKD") == "hk"

    def test_china_prefix(self):
        assert get_equity_country("Equity.CN.600519/CNY") == "cn"

    def test_japan_prefix(self):
        assert get_equity_country("Equity.JP.7203/JPY") == "jp"

    def test_korea_prefix(self):
        assert get_equity_country("Equity.KR.005930/KRW") == "kr"

    def test_germany_prefix(self):
        assert get_equity_country("Equity.DE.ADS/EUR") == "de"

    def test_categorize_intl_equity(self):
        assert categorize_asset_class("equity", "Equity.HK.0700/HKD") == "equity-hk"

    def test_categorize_us_equity(self):
        assert categorize_asset_class("equity", "Equity.US.AAPL/USD") == "equity-us"

    def test_suffix_fallback_still_works(self):
        # RIC-style symbols (no Equity. prefix) still use the suffix map
        assert get_equity_country("VOD.L") == "gb"
        assert get_equity_country("0700.HK") == "hk"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_asset_class.py::TestEquityPrefixCountry -v`
Expected: FAIL — prefix cases return `us` (e.g. `Equity.HK.0700/HKD` → `us`) instead of the country.

- [ ] **Step 3: Implement the prefix parse**

In `lib/asset_class.py`, replace the body of `get_equity_country` (currently: empty-check, suffix loop, `return "us"`) with:

```python
    if not symbol:
        return "us"  # Default to US if no symbol

    # Lazer symbols are formatted Equity.<CC>.<TICKER>/<CCY>; the country code
    # is the second dotted segment (e.g. Equity.HK.0700/HKD -> hk).
    parts = symbol.split(".")
    if len(parts) >= 3 and parts[0] == "Equity":
        return parts[1].lower()

    # Fall back to RIC-style suffixes (e.g. VOD.L -> gb) for non-prefixed symbols.
    for suffix, country in EQUITY_COUNTRY_MAP.items():
        if symbol.upper().endswith(suffix.upper()):
            return country

    # Plain symbols without prefix or known suffix are assumed US.
    return "us"
```

- [ ] **Step 4: Run the full asset_class suite to verify pass + no regression**

Run: `python3 -m pytest tests/test_asset_class.py -v`
Expected: PASS — the new `TestEquityPrefixCountry` cases and all pre-existing suffix/default tests pass.

- [ ] **Step 5: Commit**

```bash
pre-commit run --files lib/asset_class.py tests/test_asset_class.py || black lib/asset_class.py tests/test_asset_class.py
git add lib/asset_class.py tests/test_asset_class.py
git commit -m "fix(asset-class): derive equity country from Equity.<CC>. prefix

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Session boundary helper + `session_case_sql` (`lib/publisher_asset_map_core.py`)

Add the pure boundary helper and the SQL-expression builder. No query wiring yet (that is Task 3).

**Files:**

- Modify: `lib/publisher_asset_map_core.py` (add two functions + import)
- Modify: `tests/test_publisher_asset_map_core.py` (add tests)

**Interfaces:**

- Consumes: constants in `lib/sql_filters.py` (`US_EQUITY_PREMARKET_OPEN_HOUR/MINUTE`, `US_EQUITY_MARKET_OPEN_HOUR/MINUTE`, `US_EQUITY_MARKET_CLOSE_HOUR/MINUTE`, `US_EQUITY_OVERNIGHT_START_HOUR/MINUTE`).
- Produces:

  - `_et_session_bounds() -> tuple[int, int, int, int]` → `(premarket_start, regular_start, afterhours_start, overnight_start)` minutes-from-ET-midnight = `(240, 570, 960, 1200)`.
  - `session_case_sql(time_column: str, symbol_column: str) -> str` → a ClickHouse `multiIf(...)` expression string that yields `'all'` for non-`Equity.US.%` symbols and one of `premarket/regular/afterhours/overnight` otherwise, based on the ET wall-clock minute-of-day.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_publisher_asset_map_core.py`:

```python
class TestSessionSql:
    def test_bounds_from_constants(self):
        from lib.publisher_asset_map_core import _et_session_bounds

        assert _et_session_bounds() == (240, 570, 960, 1200)

    def test_session_case_sql_has_labels_and_bounds(self):
        from lib.publisher_asset_map_core import session_case_sql

        sql = session_case_sql("pu.publish_time", "fm.symbol")
        for token in ("multiIf", "America/New_York", "Equity.US.%", "fm.symbol"):
            assert token in sql
        for label in ("'all'", "'premarket'", "'regular'", "'afterhours'", "'overnight'"):
            assert label in sql
        for bound in ("240", "570", "960", "1200"):
            assert bound in sql
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_publisher_asset_map_core.py::TestSessionSql -v`
Expected: FAIL with `ImportError: cannot import name '_et_session_bounds'`.

- [ ] **Step 3: Implement the helpers**

In `lib/publisher_asset_map_core.py`, add the import near the top (after the existing `from lib.asset_class import categorize_asset_class` line):

```python
from lib import sql_filters as _sf
```

Then add these two functions (place them after `day_window`):

```python
def _et_session_bounds() -> tuple[int, int, int, int]:
    """ET session boundaries as minutes-from-midnight, from sql_filters constants.

    Returns (premarket_start, regular_start, afterhours_start, overnight_start).
    """
    return (
        _sf.US_EQUITY_PREMARKET_OPEN_HOUR * 60 + _sf.US_EQUITY_PREMARKET_OPEN_MINUTE,
        _sf.US_EQUITY_MARKET_OPEN_HOUR * 60 + _sf.US_EQUITY_MARKET_OPEN_MINUTE,
        _sf.US_EQUITY_MARKET_CLOSE_HOUR * 60 + _sf.US_EQUITY_MARKET_CLOSE_MINUTE,
        _sf.US_EQUITY_OVERNIGHT_START_HOUR * 60 + _sf.US_EQUITY_OVERNIGHT_START_MINUTE,
    )


def session_case_sql(time_column: str, symbol_column: str) -> str:
    """Build a ClickHouse expression bucketing each row into a trading session.

    Non-US-equity symbols (not matching 'Equity.US.%') yield 'all'. US-equity
    rows are bucketed by ET wall-clock minute-of-day into the four sessions,
    which tile the 24h clock with no gaps.
    """
    pre, reg, aft, ovn = _et_session_bounds()
    et = f"toTimeZone({time_column}, 'America/New_York')"
    m = f"(toHour({et}) * 60 + toMinute({et}))"
    return (
        "multiIf("
        f"{symbol_column} NOT LIKE 'Equity.US.%', 'all', "
        f"{m} >= {ovn} OR {m} < {pre}, 'overnight', "
        f"{m} < {reg}, 'premarket', "
        f"{m} < {aft}, 'regular', "
        "'afterhours')"
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_publisher_asset_map_core.py::TestSessionSql -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
pre-commit run --files lib/publisher_asset_map_core.py tests/test_publisher_asset_map_core.py || black lib/publisher_asset_map_core.py tests/test_publisher_asset_map_core.py
git add lib/publisher_asset_map_core.py tests/test_publisher_asset_map_core.py
git commit -m "feat(asset-map): add ET trading-session SQL helper

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Thread `session` through the data layer

Add a `session` field to `PublisherFeedRow` (defaulted, so existing positional constructions keep working) and wire the session expression into the query, group-by, and row assembly.

**Files:**

- Modify: `lib/publisher_asset_map_core.py` (`PublisherFeedRow`, `fetch_publisher_feeds`)
- Modify: `tests/test_publisher_asset_map_core.py` (`_FakeClient`/`_client` fixtures + `TestFetchPublisherFeeds`)

**Interfaces:**

- Consumes: `session_case_sql` (Task 2).
- Produces:

  - `PublisherFeedRow` gains `session: str = "all"` as its LAST field. Construction order is unchanged for the first six fields: `PublisherFeedRow(publisher_id, publisher_name, feed_id, symbol, asset_class, update_count, session="all")`.
  - `fetch_publisher_feeds` SELECTs a `session` column (via `session_case_sql`), groups by it, and populates `PublisherFeedRow.session`. The query's result rows now have 6 columns: `(publisher_id, feed_id, update_count, asset_type, symbol, session)`.

- [ ] **Step 1: Update the fake-client fixtures to include a session column, and write failing assertions**

In `tests/test_publisher_asset_map_core.py`, the existing `_client()` builds `feed_rows` as 5-tuples. Update it to 6-tuples by appending a session value to each, and update the helper used by the fetch tests. Replace the existing `_client()` definition with:

```python
def _client():
    return _FakeClient(
        name_rows=[(32, "Blueocean.Production"), (11, "Amber.Production")],
        feed_rows=[
            # publisher_id, feed_id, update_count, asset_type, symbol, session
            (32, 1163, 100, "equity", "Equity.US.AAPL/USD", "regular"),
            (32, 345, 20, "metal", "XAU/USD", "all"),
            (11, 999, 5, "equity", "Equity.HK.0700/HKD", "all"),
            (11, 888, 3, None, None, "all"),  # no metadata -> unknown / blank
        ],
    )
```

Then, in `TestFetchPublisherFeeds`, the existing assertions reference `equity-us`/`equity-gb` for these feeds. Because the symbols are now Lazer-prefixed, update the country expectations and add session assertions. Replace the body of `test_categorizes_and_names`, `test_foreign_equity_country`, `test_missing_metadata_is_unknown` with:

```python
    def test_categorizes_and_names(self):
        rows = fetch_publisher_feeds(_client(), "2026-06-23")
        aapl = [r for r in rows if r.feed_id == 1163][0]
        assert aapl.asset_class == "equity-us"
        assert aapl.publisher_name == "Blueocean.Production"
        assert aapl.update_count == 100
        assert aapl.session == "regular"

    def test_foreign_equity_country(self):
        rows = fetch_publisher_feeds(_client(), "2026-06-23")
        hk = [r for r in rows if r.feed_id == 999][0]
        assert hk.asset_class == "equity-hk"
        assert hk.session == "all"

    def test_missing_metadata_is_unknown(self):
        rows = fetch_publisher_feeds(_client(), "2026-06-23")
        orphan = [r for r in rows if r.feed_id == 888][0]
        assert orphan.asset_class == "unknown"
        assert orphan.symbol == ""
        assert orphan.session == "all"
```

Also update `test_asset_class_filter_equity_country` (it previously filtered `equity-us` expecting feed 1163 — still valid) — leave it as-is. And `test_asset_class_filter_plain` (filters `metal` → feed 345) — leave as-is.

One more fixture uses an inline 5-tuple feed row that must become a 6-tuple (it has its own client, not `_client()`). Update `test_missing_publisher_name_is_blank` to:

```python
    def test_missing_publisher_name_is_blank(self):
        client = _FakeClient(
            name_rows=[],
            feed_rows=[(7, 1, 1, "fx", "EUR/USD", "all")],
        )
        rows = fetch_publisher_feeds(client, "2026-06-23")
        assert rows[0].publisher_name == ""
```

(The `test_fetch_publisher_names_null_becomes_empty` test uses `feed_rows=[]`, so it needs no change.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_publisher_asset_map_core.py::TestFetchPublisherFeeds -v`
Expected: FAIL — `fetch_publisher_feeds` unpacks 5 columns but the fixtures now yield 6 (`ValueError: too many values to unpack`), and `PublisherFeedRow` has no `session` attribute.

- [ ] **Step 3: Add the `session` field**

In `lib/publisher_asset_map_core.py`, change the `PublisherFeedRow` dataclass to add `session` as the last field:

```python
@dataclass
class PublisherFeedRow:
    """One (publisher, feed, session) contribution on the analyzed date."""

    publisher_id: int
    publisher_name: str
    feed_id: int
    symbol: str
    asset_class: str
    update_count: int
    session: str = "all"
```

- [ ] **Step 4: Wire the session expression into `fetch_publisher_feeds`**

Replace the `query`/result-loop in `fetch_publisher_feeds` with:

```python
    session_expr = session_case_sql("pu.publish_time", "fm.symbol")
    query = """
        SELECT
            pu.publisher_id AS publisher_id,
            pu.price_feed_id AS feed_id,
            count() AS update_count,
            fm.asset_type AS asset_type,
            fm.symbol AS symbol,
            __SESSION_CASE__ AS session
        FROM publisher_updates pu
        LEFT JOIN feeds_metadata_latest fm ON pu.price_feed_id = fm.pyth_lazer_id
        WHERE pu.publish_time >= {start:DateTime}
          AND pu.publish_time <  {end:DateTime}
        GROUP BY pu.publisher_id, pu.price_feed_id, fm.asset_type, fm.symbol, session
        ORDER BY pu.publisher_id, fm.asset_type, pu.price_feed_id, session
    """.replace(
        "__SESSION_CASE__", session_expr
    )
    result = client.query(query, parameters={"start": start, "end": end})

    rows: list[PublisherFeedRow] = []
    for publisher_id, feed_id, update_count, asset_type, symbol, session in (
        result.result_rows
    ):
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
                session=session or "all",
            )
        )
    return rows
```

- [ ] **Step 5: Run the full core suite to verify pass + no regression**

Run: `python3 -m pytest tests/test_publisher_asset_map_core.py -v`
Expected: PASS — fetch tests pass with session assertions; `TestSessionSql` passes; the build_summary/build_matrix/write_outputs tests still pass (they ignore `session`, which defaults to `all`).

- [ ] **Step 6: Commit**

```bash
pre-commit run --files lib/publisher_asset_map_core.py tests/test_publisher_asset_map_core.py || black lib/publisher_asset_map_core.py tests/test_publisher_asset_map_core.py
git add lib/publisher_asset_map_core.py tests/test_publisher_asset_map_core.py
git commit -m "feat(asset-map): bucket publisher_updates by trading session

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: Session in summary rollup + CSV writers

Key the summary by `(publisher, asset_class, session)` and add the `session` column to the detail and summary CSVs. The matrix stays session-agnostic.

**Files:**

- Modify: `lib/publisher_asset_map_core.py` (`build_summary`, `write_outputs`)
- Modify: `tests/test_publisher_asset_map_core.py` (update `build_summary` + `write_outputs` tests)

**Interfaces:**

- Consumes: `PublisherFeedRow.session` (Task 3).
- Produces:

  - `build_summary(rows)` returns dicts keyed by `(publisher_id, asset_class, session)` with keys `publisher_id, publisher_name, asset_class, session, feed_count, total_updates`, sorted by `(publisher_id, asset_class, session)`.
  - `write_outputs` detail CSV columns: `publisher_id, publisher_name, feed_id, symbol, asset_class, session, update_count`, sorted by `(publisher_id, asset_class, feed_id, session)`. Summary CSV columns: `publisher_id, publisher_name, asset_class, session, feed_count, total_updates`. Matrix CSV unchanged.

- [ ] **Step 1: Update the existing summary/detail tests to expect session**

In `tests/test_publisher_asset_map_core.py`:

In `TestBuildSummary`, the `_rows()` helper builds `PublisherFeedRow` positionally with 6 args (session defaults to `all`). Update the three assertions to expect a `session` key:

```python
    def test_groups_by_publisher_and_class(self):
        summary = build_summary(_rows())
        assert {
            "publisher_id": 32,
            "publisher_name": "Blueocean.Production",
            "asset_class": "equity-us",
            "session": "all",
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
        assert metal_32[0]["session"] == "all"

    def test_sorted_by_publisher_then_class(self):
        summary = build_summary(_rows())
        keys = [(r["publisher_id"], r["asset_class"], r["session"]) for r in summary]
        assert keys == sorted(keys)
```

In `test_write_outputs_creates_three_csvs`, update the expected detail row `[0]` to include `session` (these rows use default `session="all"`):

```python
    assert detail[0] == {
        "publisher_id": "11",
        "publisher_name": "Amber.Production",
        "feed_id": "345",
        "symbol": "XAU/USD",
        "asset_class": "metal",
        "session": "all",
        "update_count": "7",
    }
```

(The matrix assertions in that test are unchanged.)

Add a new test that exercises a real session split:

```python
def test_summary_splits_us_equity_by_session():
    rows = [
        PublisherFeedRow(28, "MEMX.Production", 1163, "Equity.US.AAPL/USD",
                         "equity-us", 100, "regular"),
        PublisherFeedRow(28, "MEMX.Production", 1163, "Equity.US.AAPL/USD",
                         "equity-us", 40, "premarket"),
        PublisherFeedRow(28, "MEMX.Production", 1164, "Equity.US.MSFT/USD",
                         "equity-us", 60, "regular"),
    ]
    summary = build_summary(rows)
    reg = [r for r in summary if r["session"] == "regular"][0]
    pre = [r for r in summary if r["session"] == "premarket"][0]
    assert reg["feed_count"] == 2 and reg["total_updates"] == 160
    assert pre["feed_count"] == 1 and pre["total_updates"] == 40
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_publisher_asset_map_core.py::TestBuildSummary tests/test_publisher_asset_map_core.py::test_write_outputs_creates_three_csvs tests/test_publisher_asset_map_core.py::test_summary_splits_us_equity_by_session -v`
Expected: FAIL — summary dicts lack the `session` key; detail CSV lacks the `session` column.

- [ ] **Step 3: Update `build_summary`**

Replace `build_summary` in `lib/publisher_asset_map_core.py` with:

```python
def build_summary(rows: list[PublisherFeedRow]) -> list[dict]:
    """One row per (publisher_id, asset_class, session) with counts."""
    feed_count: dict[tuple[int, str, str], int] = defaultdict(int)
    total_updates: dict[tuple[int, str, str], int] = defaultdict(int)
    names: dict[int, str] = {}
    for r in rows:
        key = (r.publisher_id, r.asset_class, r.session)
        feed_count[key] += 1
        total_updates[key] += r.update_count
        names[r.publisher_id] = r.publisher_name

    out = [
        {
            "publisher_id": pub_id,
            "publisher_name": names[pub_id],
            "asset_class": asset_class,
            "session": session,
            "feed_count": feed_count[(pub_id, asset_class, session)],
            "total_updates": total_updates[(pub_id, asset_class, session)],
        }
        for (pub_id, asset_class, session) in feed_count
    ]
    out.sort(key=lambda r: (r["publisher_id"], r["asset_class"], r["session"]))
    return out
```

- [ ] **Step 4: Update `write_outputs` detail + summary writers**

In `write_outputs`, change the detail sort key and header/row to include `session` (between `asset_class` and `update_count`). Replace the detail block:

```python
    sorted_rows = sorted(
        rows, key=lambda r: (r.publisher_id, r.asset_class, r.feed_id, r.session)
    )
    with open(detail_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "publisher_id",
                "publisher_name",
                "feed_id",
                "symbol",
                "asset_class",
                "session",
                "update_count",
            ]
        )
        for r in sorted_rows:
            writer.writerow(
                [
                    r.publisher_id,
                    r.publisher_name,
                    r.feed_id,
                    r.symbol,
                    r.asset_class,
                    r.session,
                    r.update_count,
                ]
            )
```

And replace the summary block's header + row to include `session`:

```python
    summary = build_summary(rows)
    with open(summary_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "publisher_id",
                "publisher_name",
                "asset_class",
                "session",
                "feed_count",
                "total_updates",
            ]
        )
        for s in summary:
            writer.writerow(
                [
                    s["publisher_id"],
                    s["publisher_name"],
                    s["asset_class"],
                    s["session"],
                    s["feed_count"],
                    s["total_updates"],
                ]
            )
```

(The matrix block is unchanged.)

- [ ] **Step 5: Run the full core suite to verify pass**

Run: `python3 -m pytest tests/test_publisher_asset_map_core.py -v`
Expected: PASS (all tests, including the new session-split test and the unchanged matrix assertions).

- [ ] **Step 6: Commit**

```bash
pre-commit run --files lib/publisher_asset_map_core.py tests/test_publisher_asset_map_core.py || black lib/publisher_asset_map_core.py tests/test_publisher_asset_map_core.py
git add lib/publisher_asset_map_core.py tests/test_publisher_asset_map_core.py
git commit -m "feat(asset-map): add session to summary and detail CSVs

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: `feeds_by_session` helper + console block

Add a console rollup of distinct US-equity feeds per session, and print it in the CLI.

**Files:**

- Modify: `lib/publisher_asset_map_core.py` (add `feeds_by_session`)
- Modify: `tests/test_publisher_asset_map_core.py` (add a test)
- Modify: `publisher_asset_map.py` (print the block)

**Interfaces:**

- Consumes: `PublisherFeedRow.session` / `.asset_class` (Tasks 3-4).
- Produces: `feeds_by_session(rows) -> dict[str, int]` → distinct `feed_id` count per session, restricted to `asset_class == "equity-us"` rows, ordered `premarket, regular, afterhours, overnight` (only sessions present are included).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_publisher_asset_map_core.py`:

```python
def test_feeds_by_session_us_equity_only():
    from lib.publisher_asset_map_core import feeds_by_session

    rows = [
        PublisherFeedRow(28, "MEMX.Production", 1163, "Equity.US.AAPL/USD",
                         "equity-us", 100, "regular"),
        PublisherFeedRow(28, "MEMX.Production", 1163, "Equity.US.AAPL/USD",
                         "equity-us", 40, "premarket"),
        PublisherFeedRow(28, "MEMX.Production", 1164, "Equity.US.MSFT/USD",
                         "equity-us", 60, "regular"),
        # non-US-equity rows are ignored
        PublisherFeedRow(11, "Amber.Production", 999, "Equity.HK.0700/HKD",
                         "equity-hk", 9, "all"),
        PublisherFeedRow(1, "Lazer.Binance", 1, "Crypto.BTC/USD", "crypto", 5, "all"),
    ]
    # premarket: feed 1163; regular: feeds 1163 + 1164 (distinct)
    assert feeds_by_session(rows) == {"premarket": 1, "regular": 2}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_publisher_asset_map_core.py::test_feeds_by_session_us_equity_only -v`
Expected: FAIL with `ImportError: cannot import name 'feeds_by_session'`.

- [ ] **Step 3: Implement `feeds_by_session`**

Add to `lib/publisher_asset_map_core.py` (after `feeds_by_asset_class`):

```python
_SESSION_ORDER = ("premarket", "regular", "afterhours", "overnight")


def feeds_by_session(rows: list[PublisherFeedRow]) -> dict[str, int]:
    """Distinct US-equity feed count per session, in canonical session order."""
    feeds: dict[str, set] = defaultdict(set)
    for r in rows:
        if r.asset_class == "equity-us":
            feeds[r.session].add(r.feed_id)
    return {s: len(feeds[s]) for s in _SESSION_ORDER if s in feeds}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_publisher_asset_map_core.py::test_feeds_by_session_us_equity_only -v`
Expected: PASS.

- [ ] **Step 5: Print the block in the CLI**

In `publisher_asset_map.py`, update the import line to include `feeds_by_session`:

```python
from lib.publisher_asset_map_core import (
    feeds_by_asset_class,
    feeds_by_session,
    fetch_publisher_feeds,
    write_outputs,
)
```

Then, after the existing per-asset-class loop (the block ending with the `for asset_class, count in per_class.items()` lines) and before the `print("\nWrote:")` block, insert:

```python
    per_session = feeds_by_session(rows)
    if per_session:
        print("\nUS-equity feeds by session (distinct feeds):")
        for session, count in per_session.items():
            print(f"  {session}: {count}")
```

- [ ] **Step 6: Verify the CLI still imports and shows help**

Run: `python3 publisher_asset_map.py --help`
Expected: argparse help (no traceback).

- [ ] **Step 7: Commit**

```bash
pre-commit run --files lib/publisher_asset_map_core.py tests/test_publisher_asset_map_core.py publisher_asset_map.py || black lib/publisher_asset_map_core.py tests/test_publisher_asset_map_core.py publisher_asset_map.py
git add lib/publisher_asset_map_core.py tests/test_publisher_asset_map_core.py publisher_asset_map.py
git commit -m "feat(asset-map): print US-equity per-session console breakdown

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Docs update

Document the `session` column, the four sessions + `all`, and international-equity categorization in `docs/publisher_asset_map.md`.

**Files:**

- Modify: `docs/publisher_asset_map.md`

**Interfaces:**

- Consumes/Produces: nothing importable.

- [ ] **Step 1: Update `docs/publisher_asset_map.md`**

Make these edits:

1. In the "How it works" section, after the sentence describing equity ISO categorization, replace/extend the equity description so it reads:

```markdown
Equities are categorized by country from the Lazer symbol prefix
`Equity.<CC>.<TICKER>/<CCY>` (e.g. `Equity.HK.0700/HKD` → `equity-hk`,
`Equity.CN.600519/CNY` → `equity-cn`, `Equity.US.AAPL/USD` → `equity-us`).

US-equity activity is additionally split by trading session, computed from each
update's ET wall-clock time (DST-aware): `premarket` (04:00–09:30),
`regular` (09:30–16:00), `afterhours` (16:00–20:00), `overnight` (20:00–04:00).
Every other row (fx, metals, crypto, international equities) uses `session = all`.
```

2. In the Outputs table, update the detail and summary column lists:

- detail row columns → `publisher_id, publisher_name, feed_id, symbol, asset_class, session, update_count`
- summary row granularity → `per (publisher, asset_class, session)`; columns → `publisher_id, publisher_name, asset_class, session, feed_count, total_updates`
- matrix row → add a parenthetical: `(session-agnostic; a US-equity feed counts once regardless of sessions)`

3. Add a short note after the Outputs table:

```markdown
> A US-equity feed active in multiple sessions appears as multiple detail rows
> (one per session). The matrix counts each feed once per asset class.
```

- [ ] **Step 2: Run prettier on the doc**

Run: `pre-commit run prettier --files docs/publisher_asset_map.md || true`
Expected: prettier may reformat tables; re-stage if it changes the file. Confirm a second run reports `Passed`.

- [ ] **Step 3: Commit**

```bash
git add docs/publisher_asset_map.md
git commit -m "docs(asset-map): document session column and intl-equity categorization

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 7: Full test run + live smoke test

Confirm the whole suite passes and the live query actually buckets sessions and segregates countries.

**Files:** none (verification only).

- [ ] **Step 1: Run the affected unit suites**

Run: `python3 -m pytest tests/test_asset_class.py tests/test_publisher_asset_map_core.py -v`
Expected: all PASS.

- [ ] **Step 2: Full suite regression check**

Run: `python3 -m pytest tests/ -q`
Expected: no new failures introduced by these changes (compare against the known baseline; the previously-fixed cwd and TTL tests are on separate branches and may not be present here — judge only against what passed before this branch's work).

- [ ] **Step 3: Live smoke test (requires `config.yaml`)**

Run (use a recent weekday and a scratch output dir):
`python3 publisher_asset_map.py --date 2026-06-23 --output-dir /private/tmp/claude-501/-Users-mariobernardi-Documents-GitHub-integration-benchmarking/2b539957-c245-44e4-8434-ea70738498da/scratchpad/asset_map_sessions_out`
Expected: SUMMARY prints, including the new "US-equity feeds by session" block. Then verify the detail CSV:

- `grep -m5 ',equity-us,' <detail.csv>` shows session values among `premarket/regular/afterhours/overnight` (NOT `all`).
- `grep -m5 ',equity-hk,\|,equity-cn,\|,equity-jp,\|,equity-de,' <detail.csv>` shows international equities now categorized by country (no longer collapsed to `equity-us`), each with `session=all`.
- `grep ',crypto,' <detail.csv> | head -1` shows `session=all`.

- [ ] **Step 4: Verify empty-date handling still works**

Run: `python3 publisher_asset_map.py --date 2099-01-01`
Expected: "No publisher activity found..." message, exit 0, no files.

- [ ] **Step 5: Final confirmation**

No commit (verification only). If the live test surfaces a discrepancy (e.g. session always `all` for US equities, or a country mis-parse), fix it in the relevant task's files and re-run Steps 1-3.

---

## Notes for the implementer

- Do NOT f-string the SQL query body — the `{start:DateTime}`/`{end:DateTime}` placeholders must reach `client.query` intact. Inject the session expression with `.replace("__SESSION_CASE__", session_expr)` as shown.
- `PublisherFeedRow.session` defaults to `"all"`, so any existing positional 6-argument construction in tests keeps working; only the new tests pass `session` explicitly.
- The matrix CSV and `feeds_by_asset_class` are intentionally session-agnostic — do not add session to them.
- Generated CSVs under `output_csv/` (or the scratch dir) must not be committed.
