# Publisher Asset Map — Coverage Sampling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the exhaustive full-day session query with uniform-grid probe sampling (exact counts over sampled hours) so `publisher_asset_map` runs in ~2.7 min instead of ~13.

**Architecture:** Add a pure `session_probe_windows` generator (uniform 24h grid, each probe labeled by its ET session). Rework `fetch_publisher_feeds` to run one windowed `count()` query per session over those probes and merge; session comes from which probe window matched, so the per-row `toTimeZone` machinery is removed. Rename `update_count` → `sampled_update_count` for honesty. The international-equity country fix already on this branch stays.

**Tech Stack:** Python 3 (`datetime`, `zoneinfo`), `clickhouse_connect`, `pytest`. Reuses `lib/sql_filters.py` session constants and `lib/config.py`.

## Global Constraints

- Use `python3`, not `python`. Run tests with `python3 -m pytest`. Activate venv (`source venv/bin/activate`) for `pytest`/`pre-commit`.
- Session labels are exactly: `premarket`, `regular`, `afterhours`, `overnight`, and `all` (non-US-equity / not-session-split).
- Probes form a UNIFORM 24h grid starting at premarket open (04:00 ET): a probe every `interval_min` (default 30) minutes, each `width_min` (default 2) minutes wide → `1440 / interval_min` probes. Each probe is labeled by the ET session containing its start time.
- ET session boundaries come from `lib/sql_filters.py` constants (minutes-from-ET-midnight): premarket 240, regular 570, afterhours 960, overnight 1200.
- Counts are SAMPLED, not full-day: the field/columns are named `sampled_update_count` and `sampled_total_updates`.
- Session queries run SEQUENTIALLY (concurrency measured at only ~20%).
- DST/ET conversions use `zoneinfo.ZoneInfo("America/New_York")`. Tests use a non-DST-transition date (2026-06-23, EDT = UTC-4).
- Run `pre-commit run --files <changed files>` before each commit (or `black <files>` if unavailable). Markdown must pass prettier.
- Branch: `feat/publisher-asset-map-sessions`.

---

### Task 1: Probe-window generation (`session_probe_windows`)

Add the pure uniform-grid probe generator and its session-labeling helper. Additive — nothing removed yet.

**Files:**

- Modify: `lib/publisher_asset_map_core.py` (imports + 3 additions)
- Modify: `tests/test_publisher_asset_map_core.py` (add a test class)

**Interfaces:**

- Consumes: `lib.sql_filters` constants.
- Produces:

  - `@dataclass ProbeWindow` with `session: str`, `start_utc: str`, `end_utc: str`.
  - `session_probe_windows(date_str: str, interval_min: int = 30, width_min: int = 2) -> list[ProbeWindow]` — uniform 24h grid from 04:00 ET, each probe labeled by its ET session, UTC strings DST-resolved.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_publisher_asset_map_core.py`:

```python
class TestSessionProbeWindows:
    def test_count_and_width_default(self):
        from lib.publisher_asset_map_core import session_probe_windows

        ws = session_probe_windows("2026-06-23")  # interval 30, width 2
        assert len(ws) == 48
        from datetime import datetime

        s = datetime.fromisoformat(ws[0].start_utc)
        e = datetime.fromisoformat(ws[0].end_utc)
        assert (e - s).total_seconds() == 120  # 2-min wide

    def test_even_spacing(self):
        from datetime import datetime
        from lib.publisher_asset_map_core import session_probe_windows

        ws = session_probe_windows("2026-06-23")
        starts = [datetime.fromisoformat(w.start_utc) for w in ws]
        gaps = {(starts[i + 1] - starts[i]).total_seconds() for i in range(len(starts) - 1)}
        assert gaps == {1800.0}  # uniform 30-min spacing

    def test_first_window_premarket_utc(self):
        from lib.publisher_asset_map_core import session_probe_windows

        ws = session_probe_windows("2026-06-23")
        # 04:00 ET (EDT, UTC-4) -> 08:00 UTC
        assert ws[0].session == "premarket"
        assert ws[0].start_utc == "2026-06-23 08:00:00"

    def test_session_labels_across_day(self):
        from lib.publisher_asset_map_core import session_probe_windows

        ws = session_probe_windows("2026-06-23")
        # k = (ET-offset-from-04:00 in minutes) / 30
        assert ws[11].session == "regular"      # 09:30 ET
        assert ws[24].session == "afterhours"   # 16:00 ET
        assert ws[32].session == "overnight"    # 20:00 ET

    def test_overnight_crosses_into_next_utc_day(self):
        from lib.publisher_asset_map_core import session_probe_windows

        ws = session_probe_windows("2026-06-23")
        # 02:00 ET next day -> 06:00 UTC on 2026-06-24
        assert ws[44].session == "overnight"
        assert ws[44].start_utc.startswith("2026-06-24")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_publisher_asset_map_core.py::TestSessionProbeWindows -v`
Expected: FAIL with `ImportError: cannot import name 'session_probe_windows'`.

- [ ] **Step 3: Update imports**

In `lib/publisher_asset_map_core.py`, change the datetime import and add zoneinfo. Replace:

```python
from datetime import date, timedelta
```

with:

```python
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
```

Then add these module-level constants just after the imports block (after the `from lib import sql_filters as _sf` line):

```python
_ET = ZoneInfo("America/New_York")
_UTC = ZoneInfo("UTC")
```

- [ ] **Step 4: Add `ProbeWindow`, `_session_for_et_minute`, `session_probe_windows`**

Insert after the `PublisherFeedRow` dataclass (before `day_window`):

```python
@dataclass
class ProbeWindow:
    """A short [start_utc, end_utc) sampling window, labeled by its ET session."""

    session: str
    start_utc: str
    end_utc: str


def _session_for_et_minute(minute_of_day: int) -> str:
    """Map an ET minute-of-day (0..1439) to its trading-session label."""
    pre = _sf.US_EQUITY_PREMARKET_OPEN_HOUR * 60 + _sf.US_EQUITY_PREMARKET_OPEN_MINUTE
    reg = _sf.US_EQUITY_MARKET_OPEN_HOUR * 60 + _sf.US_EQUITY_MARKET_OPEN_MINUTE
    aft = _sf.US_EQUITY_MARKET_CLOSE_HOUR * 60 + _sf.US_EQUITY_MARKET_CLOSE_MINUTE
    ovn = _sf.US_EQUITY_OVERNIGHT_START_HOUR * 60 + _sf.US_EQUITY_OVERNIGHT_START_MINUTE
    m = minute_of_day
    if m >= ovn or m < pre:
        return "overnight"
    if m < reg:
        return "premarket"
    if m < aft:
        return "regular"
    return "afterhours"


def session_probe_windows(
    date_str: str, interval_min: int = 30, width_min: int = 2
) -> list[ProbeWindow]:
    """Uniform 24h grid of probe windows from 04:00 ET, each labeled by ET session."""
    d = date.fromisoformat(date_str)
    pre_min = (
        _sf.US_EQUITY_PREMARKET_OPEN_HOUR * 60 + _sf.US_EQUITY_PREMARKET_OPEN_MINUTE
    )
    day_start_et = datetime(d.year, d.month, d.day, tzinfo=_ET) + timedelta(
        minutes=pre_min
    )
    n = 1440 // interval_min
    windows: list[ProbeWindow] = []
    for k in range(n):
        start_et = day_start_et + timedelta(minutes=interval_min * k)
        end_et = start_et + timedelta(minutes=width_min)
        session = _session_for_et_minute(start_et.hour * 60 + start_et.minute)
        windows.append(
            ProbeWindow(
                session=session,
                start_utc=start_et.astimezone(_UTC).strftime("%Y-%m-%d %H:%M:%S"),
                end_utc=end_et.astimezone(_UTC).strftime("%Y-%m-%d %H:%M:%S"),
            )
        )
    return windows
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_publisher_asset_map_core.py::TestSessionProbeWindows -v`
Expected: PASS (5 passed).

- [ ] **Step 6: Commit**

```bash
pre-commit run --files lib/publisher_asset_map_core.py tests/test_publisher_asset_map_core.py || black lib/publisher_asset_map_core.py tests/test_publisher_asset_map_core.py
git add lib/publisher_asset_map_core.py tests/test_publisher_asset_map_core.py
git commit -m "feat(asset-map): add uniform-grid probe window generator

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 2: Rename `update_count` → `sampled_update_count` (and summary total)

Mechanical rename across the dataclass field, `build_summary`, `write_outputs`, the current `fetch_publisher_feeds` construction, and all test references. Behavior is otherwise unchanged (the exhaustive fetch is rewritten in Task 3).

**Files:**

- Modify: `lib/publisher_asset_map_core.py`
- Modify: `tests/test_publisher_asset_map_core.py`

**Interfaces:**

- Produces: `PublisherFeedRow.sampled_update_count` (was `update_count`); `build_summary` dicts use key `sampled_total_updates` (was `total_updates`); detail CSV column `sampled_update_count`, summary CSV column `sampled_total_updates`.

- [ ] **Step 1: Rename the dataclass field**

In `lib/publisher_asset_map_core.py`, in `PublisherFeedRow`, change `update_count: int` to:

```python
    sampled_update_count: int
```

- [ ] **Step 2: Update `build_summary`**

In `build_summary`, change `total_updates[key] += r.update_count` to:

```python
        total_updates[key] += r.sampled_update_count
```

and in the emitted dict change the `"total_updates"` key to `"sampled_total_updates"`:

```python
            "sampled_total_updates": total_updates[(pub_id, asset_class, session)],
```

- [ ] **Step 3: Update the current `fetch_publisher_feeds` construction**

In the existing `fetch_publisher_feeds`, change the `update_count=int(update_count)` keyword in the `PublisherFeedRow(...)` call to:

```python
                sampled_update_count=int(update_count),
```

- [ ] **Step 4: Update `write_outputs` (detail + summary)**

In the detail writer, change the header entry `"update_count"` to `"sampled_update_count"` and the row value `r.update_count` to `r.sampled_update_count`.

In the summary writer, change the header entry `"total_updates"` to `"sampled_total_updates"` and the row value `s["total_updates"]` to `s["sampled_total_updates"]`.

- [ ] **Step 5: Update the affected tests**

In `tests/test_publisher_asset_map_core.py`:

- In `TestBuildSummary.test_groups_by_publisher_and_class`, change `"total_updates": 150,` to `"sampled_total_updates": 150,`.
- In `TestBuildSummary.test_metal_rollup`, change `metal_32[0]["total_updates"] == 20` to `metal_32[0]["sampled_total_updates"] == 20`.
- In `TestFetchPublisherFeeds.test_categorizes_and_names`, change `aapl.update_count == 100` to `aapl.sampled_update_count == 100`.
- In `test_write_outputs_creates_three_csvs`, change `"update_count": "7",` to `"sampled_update_count": "7",`.
- In `test_summary_splits_us_equity_by_session`, change both `reg["total_updates"] == 160` → `reg["sampled_total_updates"] == 160` and `pre["total_updates"] == 40` → `pre["sampled_total_updates"] == 40`.

(Positional `PublisherFeedRow(...)` constructions in tests are unaffected — the renamed field is still the 6th positional argument.)

- [ ] **Step 6: Run the full core suite to verify pass**

Run: `python3 -m pytest tests/test_publisher_asset_map_core.py -v`
Expected: PASS (all tests; the rename is consistent across code and tests).

- [ ] **Step 7: Commit**

```bash
pre-commit run --files lib/publisher_asset_map_core.py tests/test_publisher_asset_map_core.py || black lib/publisher_asset_map_core.py tests/test_publisher_asset_map_core.py
git add lib/publisher_asset_map_core.py tests/test_publisher_asset_map_core.py
git commit -m "refactor(asset-map): rename update_count -> sampled_update_count

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 3: Rewrite `fetch_publisher_feeds` to probe sampling

Replace the exhaustive full-day query with per-session probe-window queries, merge by `(publisher, feed, asset_class, session)`, and remove the now-dead exhaustive helpers. Rewrite the fetch tests for the multi-query interface.

**Files:**

- Modify: `lib/publisher_asset_map_core.py`
- Modify: `tests/test_publisher_asset_map_core.py`

**Interfaces:**

- Consumes: `session_probe_windows` (Task 1); `fetch_publisher_names`; `categorize_asset_class`; `PublisherFeedRow` (with `sampled_update_count`).
- Produces:
  - `fetch_publisher_feeds(client, date_str, interval_min=30, width_min=2, asset_class_filter=None) -> list[PublisherFeedRow]` — runs one `count()` query per session over its probe windows and merges; `session` = the session label for `Equity.US.%` symbols, else `all`.
  - Internal `_query_probe_windows(client, windows) -> list[tuple]` returning `(publisher_id, feed_id, count, asset_type, symbol)` rows.
- Removes: `day_window`, `_et_session_bounds`, `session_case_sql`.

- [ ] **Step 1: Replace the fetch tests and remove dead-function tests**

In `tests/test_publisher_asset_map_core.py`:

(a) Remove the `TestDayWindow` class (the `day_window` tests) and the `TestSessionSql` class (the `_et_session_bounds`/`session_case_sql` tests) entirely.

(b) In the imports at the top of the file, remove `day_window` from the `from lib.publisher_asset_map_core import (...)` list (leave the other names).

(c) Replace the existing `_FakeClient` / `_client()` definitions and the entire `TestFetchPublisherFeeds` class with:

```python
class _Result:
    def __init__(self, rows):
        self.result_rows = rows


class _FakeClient:
    """Returns name rows for the names query and fixed feed rows for each probe query."""

    def __init__(self, name_rows, feed_rows):
        self._name_rows = name_rows
        self._feed_rows = feed_rows
        self.feed_query_count = 0

    def query(self, sql, parameters=None):
        if "publishers_metadata_latest" in sql:
            return _Result(self._name_rows)
        self.feed_query_count += 1
        return _Result(self._feed_rows)


def _client():
    return _FakeClient(
        name_rows=[(32, "Blueocean.Production"), (11, "Amber.Production")],
        feed_rows=[
            # publisher_id, feed_id, sampled_count, asset_type, symbol
            (32, 1163, 10, "equity", "Equity.US.AAPL/USD"),
            (11, 999, 5, "equity", "Equity.HK.0700/HKD"),
            (1, 1, 7, "crypto", "Crypto.BTC/USD"),
        ],
    )


class TestFetchPublisherFeeds:
    def test_runs_one_query_per_session(self):
        client = _client()
        fetch_publisher_feeds(client, "2026-06-23")
        # default grid spans all four sessions -> 4 probe queries
        assert client.feed_query_count == 4

    def test_us_equity_split_into_sessions(self):
        rows = fetch_publisher_feeds(_client(), "2026-06-23")
        aapl = [r for r in rows if r.feed_id == 1163]
        assert {r.session for r in aapl} == {
            "premarket",
            "regular",
            "afterhours",
            "overnight",
        }
        # each session query returned count 10 for AAPL
        assert all(r.sampled_update_count == 10 for r in aapl)
        assert all(r.asset_class == "equity-us" for r in aapl)
        assert all(r.publisher_name == "Blueocean.Production" for r in aapl)

    def test_intl_equity_is_all_and_summed(self):
        rows = fetch_publisher_feeds(_client(), "2026-06-23")
        hk = [r for r in rows if r.feed_id == 999]
        assert len(hk) == 1
        assert hk[0].session == "all"
        assert hk[0].asset_class == "equity-hk"
        assert hk[0].sampled_update_count == 20  # 5 x 4 session queries

    def test_crypto_is_all_and_summed(self):
        rows = fetch_publisher_feeds(_client(), "2026-06-23")
        btc = [r for r in rows if r.feed_id == 1][0]
        assert btc.session == "all"
        assert btc.asset_class == "crypto"
        assert btc.sampled_update_count == 28  # 7 x 4

    def test_missing_metadata_is_unknown(self):
        client = _FakeClient(
            name_rows=[(7, "X.Prod")],
            feed_rows=[(7, 5, 3, None, None)],
        )
        rows = fetch_publisher_feeds(client, "2026-06-23")
        orphan = [r for r in rows if r.feed_id == 5][0]
        assert orphan.asset_class == "unknown"
        assert orphan.symbol == ""
        assert orphan.session == "all"

    def test_missing_publisher_name_is_blank(self):
        client = _FakeClient(
            name_rows=[],
            feed_rows=[(7, 1, 1, "fx", "EUR/USD")],
        )
        rows = fetch_publisher_feeds(client, "2026-06-23")
        assert rows[0].publisher_name == ""

    def test_asset_class_filter_us_equity(self):
        rows = fetch_publisher_feeds(
            _client(), "2026-06-23", asset_class_filter="equity-us"
        )
        assert {r.feed_id for r in rows} == {1163}

    def test_asset_class_filter_intl(self):
        rows = fetch_publisher_feeds(
            _client(), "2026-06-23", asset_class_filter="equity-hk"
        )
        assert {r.feed_id for r in rows} == {999}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_publisher_asset_map_core.py::TestFetchPublisherFeeds -v`
Expected: FAIL — the current `fetch_publisher_feeds` does a single full-day query (feed_query_count would be 1, sessions not split as asserted).

- [ ] **Step 3: Replace `fetch_publisher_feeds` and add `_query_probe_windows`; remove dead helpers**

In `lib/publisher_asset_map_core.py`:

(a) Delete `day_window`, `_et_session_bounds`, and `session_case_sql` entirely.

(b) Replace the entire `fetch_publisher_feeds` function with:

```python
def _query_probe_windows(client, windows: list[ProbeWindow]):
    """Run one grouped count() over the given probe windows; return raw rows."""
    conds = " OR ".join(
        f"(pu.publish_time >= {{s{i}:DateTime}} AND pu.publish_time < {{e{i}:DateTime}})"
        for i in range(len(windows))
    )
    params: dict[str, str] = {}
    for i, w in enumerate(windows):
        params[f"s{i}"] = w.start_utc
        params[f"e{i}"] = w.end_utc
    query = f"""
        SELECT
            pu.publisher_id AS publisher_id,
            pu.price_feed_id AS feed_id,
            count() AS sampled_update_count,
            fm.asset_type AS asset_type,
            fm.symbol AS symbol
        FROM publisher_updates pu
        LEFT JOIN feeds_metadata_latest fm ON pu.price_feed_id = fm.pyth_lazer_id
        WHERE {conds}
        GROUP BY pu.publisher_id, pu.price_feed_id, fm.asset_type, fm.symbol
    """
    return client.query(query, parameters=params).result_rows


def fetch_publisher_feeds(
    client,
    date_str: str,
    interval_min: int = 30,
    width_min: int = 2,
    asset_class_filter: Optional[str] = None,
) -> list[PublisherFeedRow]:
    """Sample probe windows per session; return per-(publisher, feed, session) rows."""
    names = fetch_publisher_names(client)
    windows = session_probe_windows(date_str, interval_min, width_min)

    by_session: dict[str, list[ProbeWindow]] = defaultdict(list)
    for w in windows:
        by_session[w.session].append(w)

    # (publisher_id, feed_id, asset_class, session) -> [summed_count, symbol]
    acc: dict[tuple[int, int, str, str], list] = {}
    for session_label, wins in by_session.items():
        for publisher_id, feed_id, cnt, asset_type, symbol in _query_probe_windows(
            client, wins
        ):
            symbol = symbol or ""
            asset_class = categorize_asset_class(asset_type or "unknown", symbol)
            session = session_label if symbol.startswith("Equity.US.") else "all"
            key = (int(publisher_id), int(feed_id), asset_class, session)
            if key in acc:
                acc[key][0] += int(cnt)
            else:
                acc[key] = [int(cnt), symbol]

    rows: list[PublisherFeedRow] = []
    for (pub_id, feed_id, asset_class, session), (cnt, symbol) in acc.items():
        if asset_class_filter and asset_class != asset_class_filter:
            continue
        rows.append(
            PublisherFeedRow(
                publisher_id=pub_id,
                publisher_name=names.get(pub_id, ""),
                feed_id=feed_id,
                symbol=symbol,
                asset_class=asset_class,
                sampled_update_count=cnt,
                session=session,
            )
        )
    return rows
```

- [ ] **Step 4: Run the full core suite to verify pass**

Run: `python3 -m pytest tests/test_publisher_asset_map_core.py -v`
Expected: PASS — new `TestFetchPublisherFeeds`, `TestSessionProbeWindows`, and the unchanged summary/matrix/write_outputs/feeds_by_session tests all pass; no references to the removed functions remain.

- [ ] **Step 5: Confirm no lingering references to removed symbols**

Run: `grep -rn "day_window\|session_case_sql\|_et_session_bounds" lib/ tests/ publisher_asset_map.py`
Expected: no output (all references removed).

- [ ] **Step 6: Commit**

```bash
pre-commit run --files lib/publisher_asset_map_core.py tests/test_publisher_asset_map_core.py || black lib/publisher_asset_map_core.py tests/test_publisher_asset_map_core.py
git add lib/publisher_asset_map_core.py tests/test_publisher_asset_map_core.py
git commit -m "feat(asset-map): sample probe windows per session instead of full-day scan

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 4: CLI flags + console (probe windows, progress, elapsed)

Add `--probe-interval-min` / `--probe-width-min`, pass them through, and print the probe windows used, per-session-query progress, and elapsed time.

**Files:**

- Modify: `publisher_asset_map.py`

**Interfaces:**

- Consumes: `fetch_publisher_feeds(client, date, interval_min, width_min, asset_class)`, `session_probe_windows`.

- [ ] **Step 1: Update imports and the fetch call**

In `publisher_asset_map.py`, add `session_probe_windows` to the import:

```python
from lib.publisher_asset_map_core import (
    feeds_by_asset_class,
    feeds_by_session,
    fetch_publisher_feeds,
    session_probe_windows,
    write_outputs,
)
```

Also add `import time` next to `import sys`.

- [ ] **Step 2: Add the CLI flags**

After the `--asset-class` argument, add:

```python
    parser.add_argument(
        "--probe-interval-min",
        type=int,
        default=30,
        help="Spacing between probe windows in minutes (default: 30)",
    )
    parser.add_argument(
        "--probe-width-min",
        type=int,
        default=2,
        help="Probe window width in minutes (default: 2)",
    )
```

- [ ] **Step 3: Print probe windows, time the fetch, pass flags through**

Replace the block from the first `print(f"Querying ...")` line through the `rows = fetch_publisher_feeds(...)` call with:

```python
    windows = session_probe_windows(args.date, args.probe_interval_min, args.probe_width_min)
    print(
        f"Sampling {len(windows)} probe windows "
        f"(every {args.probe_interval_min} min x {args.probe_width_min} min) "
        f"for ET trading date {args.date}..."
    )
    # Concise per-session summary: probe count + UTC span (first start -> last end).
    for session in ("premarket", "regular", "afterhours", "overnight"):
        sw = [w for w in windows if w.session == session]
        if sw:
            print(
                f"  {session:10s} {len(sw):2d} probes  "
                f"{sw[0].start_utc} -> {sw[-1].end_utc} UTC"
            )
    if args.asset_class:
        print(f"Asset class filter: {args.asset_class}")

    started = time.time()
    try:
        config = load_config()
        client = get_lazer_client(config)
        rows = fetch_publisher_feeds(
            client,
            args.date,
            args.probe_interval_min,
            args.probe_width_min,
            args.asset_class,
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error during initialization or query: {e}", file=sys.stderr)
        sys.exit(1)
    elapsed = time.time() - started
```

- [ ] **Step 4: Print elapsed time in the summary**

In the SUMMARY block, after the `print(f"Date: {args.date}")` line, add:

```python
    print(f"Query time: {elapsed:.1f}s")
```

- [ ] **Step 5: Verify the CLI parses and shows the new flags**

Run: `python3 publisher_asset_map.py --help`
Expected: help text lists `--probe-interval-min` and `--probe-width-min` (no traceback).

- [ ] **Step 6: Commit**

```bash
pre-commit run --files publisher_asset_map.py || black publisher_asset_map.py
git add publisher_asset_map.py
git commit -m "feat(asset-map): probe-grid CLI flags, window list, and elapsed time

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 5: Docs update

Document sampling semantics, the `sampled_*` columns, the probe flags, and that counts are sampled (not full-day).

**Files:**

- Modify: `docs/publisher_asset_map.md`

- [ ] **Step 1: Update `docs/publisher_asset_map.md`**

Make these edits:

1. Replace the "How it works" description of the query with:

```markdown
For one **ET trading date**, the tool samples short **probe windows** on a uniform
24h grid (default: every 30 min, 2 min wide; tunable via `--probe-interval-min` and
`--probe-width-min`) rather than scanning the whole day. It runs one windowed
`count()` query per US-equity trading session (premarket / regular / afterhours /
overnight) and labels each update's session by which probe window it fell in. This
keeps the query fast (~2–3 min vs ~13 min for a full-day scan) while covering every
market's hours.

Equities are categorized by country from the Lazer symbol prefix
`Equity.<CC>.<TICKER>/<CCY>` (e.g. `Equity.HK.0700/HKD` -> `equity-hk`,
`Equity.US.AAPL/USD` -> `equity-us`). Only US-equity symbols (`Equity.US.*`) are
split by session; every other row (fx, metals, crypto, international equities) uses
`session = all`.
```

2. In the Outputs section, update the columns:

- detail: `publisher_id, publisher_name, feed_id, symbol, asset_class, session, sampled_update_count`
- summary (per `publisher, asset_class, session`): `publisher_id, publisher_name, asset_class, session, feed_count, sampled_total_updates`
- matrix: unchanged — publisher × asset_class distinct feed counts (session-agnostic)

3. Add a note:

```markdown
> **Sampled counts:** `sampled_update_count` / `sampled_total_updates` are updates
> observed within the probe windows, NOT full-day totals. A publisher absent from a
> session's probes has no row for that session (the implicit "silent" signal).
```

4. If a CLI/arguments table is present, add rows for `--probe-interval-min` (default 30) and `--probe-width-min` (default 2).

- [ ] **Step 2: Prettier**

Run: `pre-commit run prettier --files docs/publisher_asset_map.md || true`
Expected: may reformat; re-stage and confirm a second run reports `Passed`.

- [ ] **Step 3: Commit**

```bash
git add docs/publisher_asset_map.md
git commit -m "docs(asset-map): document probe sampling and sampled_* columns

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task 6: Full test run + live smoke test

**Files:** none (verification only).

- [ ] **Step 1: Run the affected unit suites**

Run: `python3 -m pytest tests/test_asset_class.py tests/test_publisher_asset_map_core.py -v`
Expected: all PASS.

- [ ] **Step 2: Full-suite regression check**

Run: `python3 -m pytest tests/ -q`
Expected: no NEW failures from this branch's work. (The pre-existing hardcoded-cwd and flaky-TTL failures live on other branches and may appear here; judge only against what passed before this rework.)

- [ ] **Step 3: Live smoke test (requires `config.yaml`)**

Run (write to a scratch dir; this may take ~2–3 min — run in the background if your shell times out foreground commands):
`python3 publisher_asset_map.py --date 2026-06-23 --output-dir /private/tmp/claude-501/-Users-mariobernardi-Documents-GitHub-integration-benchmarking/2b539957-c245-44e4-8434-ea70738498da/scratchpad/asset_map_sampling_out`
Expected: prints the probe windows, a "Query time: …s" line in the SUMMARY, and writes three CSVs. Verify on the detail CSV:

- `grep -m5 ',equity-us,' <detail.csv>` shows session values among `premarket/regular/afterhours/overnight` (not `all`).
- `grep -m5 -E ',equity-(hk|cn|jp|kr|de),' <detail.csv>` shows international equities by country, each `session=all`.
- `grep -m1 ',crypto,' <detail.csv>` shows `session=all`.
- The header reads `...,asset_class,session,sampled_update_count`.

- [ ] **Step 4: Verify empty-date handling**

Run: `python3 publisher_asset_map.py --date 2099-01-01`
Expected: "No publisher activity found..." message, exit 0, no files.

- [ ] **Step 5: Final confirmation**

No commit (verification only). If the live test surfaces a discrepancy (e.g. US equities all `all`, or a country mis-parse), fix it in the relevant task's files and re-run Steps 1–3.

---

## Notes for the implementer

- The probe-query f-string is safe: `f"{{s{i}:DateTime}}"` renders to the literal ClickHouse placeholder `{s0:DateTime}` (doubled braces escape), and the only interpolation in the query body is `{conds}`. Do NOT add other `{...}` to that query body.
- `session_probe_windows` is pure and deterministic — no `Date.now()`/clock reads; the date comes from `--date`.
- Generated CSVs under the scratch/`output_csv` dir must not be committed.
- The international-equity country fix (`get_equity_country` prefix parse) is already implemented earlier on this branch — do not re-implement it.
