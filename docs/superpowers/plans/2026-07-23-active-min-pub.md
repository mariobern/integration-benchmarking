# active_min_pub Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `lazer_dq/active_min_pub.py` — a sweep that, per STABLE `(feed, session)`, computes the distribution of the aggregate's own `publisher_count` (from `price_feeds`) over a multi-day window and flags feeds running close to their `minPublishers` floor.

**Architecture:** Thin CLI wrapper (mirrors `audit_min_pub`). Per feed: one ClickHouse query against `price_feeds` returning `(publish_time, publisher_count)` on the lowest-numbered channel with data (probe 1→2→3). Per session of that feed: mask `publish_time` to the session's open minutes (reusing `lazer_dq.market_schedule`), reduce the masked `publisher_count` array to distribution stats, and assign a verdict driven by `pct_at_floor`. Parallelised per feed via `ThreadPoolExecutor`. Pure functions (channel-agnostic stats/verdict) are unit-tested with mock ClickHouse clients; no live DB in tests.

**Tech Stack:** Python 3.12, numpy, pandas, clickhouse-connect (via `lib.config`), pytest. New-format Lazer config (`lazer_newest.json`).

## Global Constraints

- **Python invocation:** `python3` (not `python`); activate venv first (`source venv/bin/activate`).
- **Config format:** new-format session-only (`lazer_newest.json`); universe + floors come from `lazer_dq.min_pub_common.iter_stable_sessions`.
- **ClickHouse:** `lazer_clickhouse_prod` via `lib.config` (`ThreadLocalClients(load_config(), lazer_only=True)`); parameterized queries use `{name:Type}` syntax with `parameters=dict`.
- **Metric:** aggregate `price_feeds.publisher_count` = actual contributors per aggregate (single column). NEVER `publisher_updates` per-minute.
- **Percentages:** `pct_at_floor` / `pct_at_floor_1` reported on a 0–100 scale.
- **Verdict defaults:** `--critical-pct 1.0`, `--warn-pct 5.0`, `--min-updates 100`.
- **Verdict precedence:** NO_DATA > LOW_SAMPLE > CRITICAL > WARN > OK.
- **Style:** match `audit_min_pub.py` (module-level column list, small pure functions, `from __future__ import annotations`).
- Run `pre-commit run --files <changed files>` before each commit (via venv if not on PATH).

---

## File Structure

- **Create** `lazer_dq/active_min_pub.py` — module: query, channel probe, session-mask reduction, stats, verdict, CLI/main.
- **Create** `lazer_dq/tests/test_active_min_pub.py` — unit tests (mock ClickHouse, pure-function assertions).
- **Create** `docs/active_min_pub.md` — usage + output schema + contrast with `audit_min_pub`.
- **Modify** `CLAUDE.md` — Scripts-table row + one "Key Gotchas" line.
- **Modify** `lazer_dq/audit_min_pub.py:1-14` — one docstring line noting the distinction from `active_min_pub`.

---

## Task 1: Distribution stats + verdict (pure functions)

**Files:**
- Create: `lazer_dq/active_min_pub.py`
- Test: `lazer_dq/tests/test_active_min_pub.py`

**Interfaces:**
- Consumes: nothing (leaf functions).
- Produces:
  - `RESULT_COLUMNS: list[str]` — CSV field order.
  - `distribution_stats(counts: np.ndarray, min_pub: int) -> dict` — returns keys `n_updates, min, p1, p5, median, pct_at_floor, pct_at_floor_1`. `counts` is the masked per-update `publisher_count` array (dtype int). On empty input returns `n_updates=0` and all other numeric keys `0`/`0.0`.
  - `classify(stats: dict, critical_pct: float, warn_pct: float, min_updates: int) -> str` — returns one of `NO_DATA, LOW_SAMPLE, CRITICAL, WARN, OK`. Thresholds are passed as arguments (not read from `stats`). Precedence: NO_DATA > LOW_SAMPLE > CRITICAL > WARN > OK.

- [ ] **Step 1: Write the failing test for `distribution_stats`**

Create `lazer_dq/tests/test_active_min_pub.py`:

```python
import numpy as np
import pandas as pd

from lazer_dq.active_min_pub import (
    RESULT_COLUMNS,
    classify,
    distribution_stats,
)


def test_distribution_stats_basic():
    # min_pub = 2. Values: two updates at floor (<=2), one at floor+1 (==3), rest above.
    counts = np.array([2, 2, 3, 4, 4, 4, 5, 5, 6, 10])
    s = distribution_stats(counts, min_pub=2)
    assert s["n_updates"] == 10
    assert s["min"] == 2
    assert s["median"] == 4.5
    # pct_at_floor: publisher_count <= 2 -> 2/10 = 20.0
    assert s["pct_at_floor"] == 20.0
    # pct_at_floor_1: publisher_count <= 3 -> 3/10 = 30.0
    assert s["pct_at_floor_1"] == 30.0
    # percentiles are numpy linear-interp values
    assert s["p1"] == float(np.percentile(counts, 1))
    assert s["p5"] == float(np.percentile(counts, 5))


def test_distribution_stats_empty():
    s = distribution_stats(np.array([], dtype=int), min_pub=2)
    assert s["n_updates"] == 0
    assert s["min"] == 0
    assert s["pct_at_floor"] == 0.0
    assert s["pct_at_floor_1"] == 0.0
    assert s["median"] == 0.0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source venv/bin/activate && python3 -m pytest lazer_dq/tests/test_active_min_pub.py -q`
Expected: FAIL with `ModuleNotFoundError` / `ImportError: cannot import name 'distribution_stats'`.

- [ ] **Step 3: Write minimal `active_min_pub.py` with the module header, `RESULT_COLUMNS`, `distribution_stats`, and `classify`**

Create `lazer_dq/active_min_pub.py`:

```python
"""Aggregate publisher-count headroom sweep (min-pub distance, aggregate level).

For every STABLE (feed, session) in a new-format Lazer config, reads the
aggregate's own publisher_count per update from price_feeds (highest-frequency
channel = lowest-numbered channel with data), session-masks to open hours, and
reports the contributor-count distribution vs the session's minPublishers.

DISTINCT FROM audit_min_pub: that script counts per-MINUTE distinct ACCEPTED
publishers from publisher_updates (availability). This script uses the
per-AGGREGATE publisher_count from price_feeds (contributor headroom). Different
question; do not conflate.

Run:
    python3 -m lazer_dq.active_min_pub --config lazer_newest.json \
        --start-date 2026-07-14 --end-date 2026-07-22 --workers 8
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from lazer_dq.market_schedule import open_minutes_mask, parse_market_schedule
from lazer_dq.min_pub_common import iter_stable_sessions

RESULT_COLUMNS = [
    "feed_id",
    "symbol",
    "asset_type",
    "session",
    "effective_min_pub",
    "n_updates",
    "min",
    "p1",
    "p5",
    "median",
    "pct_at_floor",
    "pct_at_floor_1",
    "verdict",
]


def distribution_stats(counts: np.ndarray, min_pub: int) -> dict:
    """Distribution of aggregate publisher_count vs the min-pub floor.

    counts: per-update contributor counts already masked to the session.
    Empty input -> n_updates=0 with zeroed stats.
    """
    n = int(len(counts))
    if n == 0:
        return {
            "n_updates": 0,
            "min": 0,
            "p1": 0.0,
            "p5": 0.0,
            "median": 0.0,
            "pct_at_floor": 0.0,
            "pct_at_floor_1": 0.0,
        }
    return {
        "n_updates": n,
        "min": int(counts.min()),
        "p1": float(np.percentile(counts, 1)),
        "p5": float(np.percentile(counts, 5)),
        "median": float(np.median(counts)),
        "pct_at_floor": float((counts <= min_pub).mean() * 100.0),
        "pct_at_floor_1": float((counts <= min_pub + 1).mean() * 100.0),
    }


def classify(stats: dict, critical_pct: float, warn_pct: float, min_updates: int) -> str:
    """Verdict precedence: NO_DATA > LOW_SAMPLE > CRITICAL > WARN > OK."""
    if stats["n_updates"] == 0:
        return "NO_DATA"
    if stats["n_updates"] < min_updates:
        return "LOW_SAMPLE"
    if stats["pct_at_floor"] >= critical_pct:
        return "CRITICAL"
    if stats["pct_at_floor"] == 0.0 and stats["pct_at_floor_1"] >= warn_pct:
        return "WARN"
    return "OK"
```

- [ ] **Step 4: Add the `classify` test cases**

Append to `lazer_dq/tests/test_active_min_pub.py`:

```python
def _stats(n_updates, pct_at_floor, pct_at_floor_1):
    return {
        "n_updates": n_updates,
        "pct_at_floor": pct_at_floor,
        "pct_at_floor_1": pct_at_floor_1,
    }


def test_classify_no_data_before_everything():
    s = _stats(0, 0.0, 0.0)
    assert classify(s, critical_pct=1.0, warn_pct=5.0, min_updates=100) == "NO_DATA"


def test_classify_low_sample_below_min_updates():
    s = _stats(99, 50.0, 50.0)  # would be CRITICAL if it had samples
    assert classify(s, critical_pct=1.0, warn_pct=5.0, min_updates=100) == "LOW_SAMPLE"


def test_classify_critical_at_threshold():
    s = _stats(500, 1.0, 1.0)  # exactly at critical_pct
    assert classify(s, critical_pct=1.0, warn_pct=5.0, min_updates=100) == "CRITICAL"


def test_classify_warn_only_when_floor_untouched():
    s = _stats(500, 0.0, 5.0)  # never at floor, but >=warn_pct at floor+1
    assert classify(s, critical_pct=1.0, warn_pct=5.0, min_updates=100) == "WARN"


def test_classify_ok():
    s = _stats(500, 0.0, 4.9)  # below warn_pct at floor+1
    assert classify(s, critical_pct=1.0, warn_pct=5.0, min_updates=100) == "OK"


def test_classify_min_updates_boundary_is_low_sample_exclusive():
    # n_updates == min_updates is NOT low sample (>= passes)
    s_at = _stats(100, 0.0, 0.0)
    assert classify(s_at, critical_pct=1.0, warn_pct=5.0, min_updates=100) == "OK"
    s_below = _stats(100, 2.0, 2.0)
    assert classify(s_below, critical_pct=1.0, warn_pct=5.0, min_updates=100) == "CRITICAL"


def test_result_columns_contract():
    assert RESULT_COLUMNS == [
        "feed_id",
        "symbol",
        "asset_type",
        "session",
        "effective_min_pub",
        "n_updates",
        "min",
        "p1",
        "p5",
        "median",
        "pct_at_floor",
        "pct_at_floor_1",
        "verdict",
    ]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `source venv/bin/activate && python3 -m pytest lazer_dq/tests/test_active_min_pub.py -q`
Expected: PASS (8 tests).

- [ ] **Step 6: Commit**

```bash
source venv/bin/activate
pre-commit run --files lazer_dq/active_min_pub.py lazer_dq/tests/test_active_min_pub.py || true
git add lazer_dq/active_min_pub.py lazer_dq/tests/test_active_min_pub.py
git commit -m "feat(active_min_pub): distribution stats + verdict pure functions"
```

---

## Task 2: Session-masked counts from raw price_feeds rows

**Files:**
- Modify: `lazer_dq/active_min_pub.py`
- Test: `lazer_dq/tests/test_active_min_pub.py`

**Interfaces:**
- Consumes: `parse_market_schedule`, `open_minutes_mask` from `lazer_dq.market_schedule`.
- Produces:
  - `masked_counts(rows: list[tuple], schedule_str: str, start_utc: datetime, end_utc: datetime) -> np.ndarray` — `rows` are `(publish_time_naive_utc, publisher_count)` tuples straight from ClickHouse. Floors each `publish_time` to its UTC minute, keeps only rows whose minute is open per the parsed schedule, and returns the surviving `publisher_count` values as an int array. Raises `ValueError` (propagated from `parse_market_schedule`) on a malformed schedule string — caller handles.

- [ ] **Step 1: Write the failing test**

Append to `lazer_dq/tests/test_active_min_pub.py`:

```python
from datetime import datetime, timezone

from lazer_dq.active_min_pub import masked_counts


def test_masked_counts_keeps_only_open_minutes():
    start = datetime(2026, 7, 14, tzinfo=timezone.utc)  # Tuesday
    end = datetime(2026, 7, 15, tzinfo=timezone.utc)
    # REGULAR NY 0930-1600 -> 13:30-20:00 UTC (EDT = UTC-4 in July).
    sched = (
        "America/New_York;0930-1600,0930-1600,0930-1600,0930-1600,0930-1600,C,C;"
    )
    rows = [
        (datetime(2026, 7, 14, 13, 30, 0, 500000), 5),  # 13:30 UTC open -> keep
        (datetime(2026, 7, 14, 13, 30, 0, 900000), 4),  # same minute, keep
        (datetime(2026, 7, 14, 12, 0, 0), 2),           # 12:00 UTC pre-open -> drop
        (datetime(2026, 7, 14, 20, 0, 0), 3),           # 20:00 UTC == close (exclusive) -> drop
        (datetime(2026, 7, 14, 19, 59, 0), 7),          # 19:59 UTC open -> keep
    ]
    counts = masked_counts(rows, sched, start, end)
    assert sorted(counts.tolist()) == [4, 5, 7]


def test_masked_counts_overnight_midnight_crossing():
    start = datetime(2026, 7, 14, tzinfo=timezone.utc)
    end = datetime(2026, 7, 15, tzinfo=timezone.utc)
    # OVER_NIGHT NY 0000-0400 & 2000-2400 -> UTC 04:00-08:00 & 00:00-04:00 (EDT).
    sched = (
        "America/New_York;"
        "0000-0400&2000-2400,0000-0400&2000-2400,0000-0400&2000-2400,"
        "0000-0400&2000-2400,0000-0400,C,2000-2400;"
    )
    rows = [
        (datetime(2026, 7, 14, 5, 0, 0), 2),   # NY 01:00 -> in 0000-0400 -> keep
        (datetime(2026, 7, 14, 1, 0, 0), 9),   # NY 21:00 (prev day) -> in 2000-2400 -> keep
        (datetime(2026, 7, 14, 12, 0, 0), 5),  # NY 08:00 -> daytime -> drop
    ]
    counts = masked_counts(rows, sched, start, end)
    assert sorted(counts.tolist()) == [2, 9]


def test_masked_counts_empty_rows():
    start = datetime(2026, 7, 14, tzinfo=timezone.utc)
    end = datetime(2026, 7, 15, tzinfo=timezone.utc)
    sched = "UTC;O,O,O,O,O,O,O"
    assert masked_counts([], sched, start, end).tolist() == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source venv/bin/activate && python3 -m pytest lazer_dq/tests/test_active_min_pub.py -k masked_counts -q`
Expected: FAIL with `ImportError: cannot import name 'masked_counts'`.

- [ ] **Step 3: Implement `masked_counts`**

Add to `lazer_dq/active_min_pub.py` (after `distribution_stats`):

```python
def masked_counts(rows, schedule_str, start_utc, end_utc) -> np.ndarray:
    """Per-update publisher_count values whose minute is open per the schedule.

    rows: (publish_time_naive_utc, publisher_count) tuples from ClickHouse.
    Raises ValueError on a malformed schedule string (caller handles).
    """
    if not rows:
        return np.array([], dtype=int)
    schedule = parse_market_schedule(schedule_str)
    mask = open_minutes_mask(schedule, start_utc, end_utc)
    open_minutes = set(mask.index[mask.to_numpy()])
    out = []
    for ts, count in rows:
        minute = pd.Timestamp(ts, tz="UTC").floor("min")
        if minute in open_minutes:
            out.append(count)
    return np.array(out, dtype=int)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source venv/bin/activate && python3 -m pytest lazer_dq/tests/test_active_min_pub.py -k masked_counts -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
source venv/bin/activate
pre-commit run --files lazer_dq/active_min_pub.py lazer_dq/tests/test_active_min_pub.py || true
git add lazer_dq/active_min_pub.py lazer_dq/tests/test_active_min_pub.py
git commit -m "feat(active_min_pub): session-masked per-update counts"
```

---

## Task 3: ClickHouse fetch with channel probing

**Files:**
- Modify: `lazer_dq/active_min_pub.py`
- Test: `lazer_dq/tests/test_active_min_pub.py`

**Interfaces:**
- Consumes: a ClickHouse client exposing `.query(sql, parameters=dict)` returning an object with `.result_rows` (list of `(publish_time, publisher_count)`).
- Produces:
  - `PRICE_FEEDS_QUERY: str` — parameterized SQL (feed_id, channel, start, end).
  - `fetch_feed_rows(client, feed_id, start_utc, end_utc, channels=(1, 2, 3)) -> list[tuple]` — probes channels in order, returns `.result_rows` from the first channel with data; `[]` if none have data.

- [ ] **Step 1: Write the failing test**

Append to `lazer_dq/tests/test_active_min_pub.py`:

```python
from lazer_dq.active_min_pub import fetch_feed_rows


class FakeResult:
    def __init__(self, rows):
        self.result_rows = rows


class ChannelClient:
    """Returns rows only for a specific channel; records queried channels."""

    def __init__(self, rows_by_channel):
        self._rows_by_channel = rows_by_channel
        self.channels_tried = []

    def query(self, sql, parameters=None):
        chan = parameters["channel"]
        self.channels_tried.append(chan)
        return FakeResult(self._rows_by_channel.get(chan, []))


def test_fetch_feed_rows_uses_lowest_channel_with_data():
    t = datetime(2026, 7, 14, 13, 30, tzinfo=timezone.utc)
    client = ChannelClient({2: [(t.replace(tzinfo=None), 5)]})  # only chan 2 has data
    rows = fetch_feed_rows(
        client, 100, t, datetime(2026, 7, 15, tzinfo=timezone.utc)
    )
    assert rows == [(t.replace(tzinfo=None), 5)]
    assert client.channels_tried == [1, 2]  # stopped at 2, never tried 3


def test_fetch_feed_rows_no_data_returns_empty():
    client = ChannelClient({})  # no channel has data
    rows = fetch_feed_rows(
        client,
        100,
        datetime(2026, 7, 14, tzinfo=timezone.utc),
        datetime(2026, 7, 15, tzinfo=timezone.utc),
    )
    assert rows == []
    assert client.channels_tried == [1, 2, 3]


def test_fetch_feed_rows_query_is_parameterized_and_scoped():
    client = ChannelClient({1: [(datetime(2026, 7, 14, 13, 30), 5)]})
    fetch_feed_rows(
        client,
        321,
        datetime(2026, 7, 14, tzinfo=timezone.utc),
        datetime(2026, 7, 15, tzinfo=timezone.utc),
    )
    # last query used channel 1 and feed 321
    from lazer_dq.active_min_pub import PRICE_FEEDS_QUERY

    assert "price_feeds" in PRICE_FEEDS_QUERY
    assert "publisher_count" in PRICE_FEEDS_QUERY
    assert "publisher_updates" not in PRICE_FEEDS_QUERY
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source venv/bin/activate && python3 -m pytest lazer_dq/tests/test_active_min_pub.py -k fetch_feed_rows -q`
Expected: FAIL with `ImportError: cannot import name 'fetch_feed_rows'`.

- [ ] **Step 3: Implement query + fetch**

Add to `lazer_dq/active_min_pub.py` (after imports/`RESULT_COLUMNS`):

```python
PRICE_FEEDS_QUERY = """
    SELECT publish_time, publisher_count
    FROM price_feeds
    WHERE price_feed_id = {feed_id:UInt64}
      AND channel = {channel:UInt8}
      AND publish_time >= {start:String}
      AND publish_time < {end:String}
    ORDER BY publish_time
"""


def fetch_feed_rows(client, feed_id, start_utc, end_utc, channels=(1, 2, 3)) -> list:
    """(publish_time, publisher_count) rows from the lowest channel with data."""
    for channel in channels:
        result = client.query(
            PRICE_FEEDS_QUERY,
            parameters={
                "feed_id": feed_id,
                "channel": channel,
                "start": start_utc.strftime("%Y-%m-%d %H:%M:%S"),
                "end": end_utc.strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
        if result.result_rows:
            return list(result.result_rows)
    return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source venv/bin/activate && python3 -m pytest lazer_dq/tests/test_active_min_pub.py -k fetch_feed_rows -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
source venv/bin/activate
pre-commit run --files lazer_dq/active_min_pub.py lazer_dq/tests/test_active_min_pub.py || true
git add lazer_dq/active_min_pub.py lazer_dq/tests/test_active_min_pub.py
git commit -m "feat(active_min_pub): price_feeds fetch with channel probing"
```

---

## Task 4: Per-feed orchestration (rows -> per-session result rows)

**Files:**
- Modify: `lazer_dq/active_min_pub.py`
- Test: `lazer_dq/tests/test_active_min_pub.py`

**Interfaces:**
- Consumes: `fetch_feed_rows`, `masked_counts`, `distribution_stats`, `classify`, and `FeedSession` from `lazer_dq.min_pub_common`.
- Produces:
  - `analyze_feed(client, feed_sessions, start_utc, end_utc, critical_pct, warn_pct, min_updates) -> list[dict]` — one query for the feed (via `fetch_feed_rows`), then one result dict per session in `feed_sessions`. Each dict has every key in `RESULT_COLUMNS`. A session whose `schedule_str` is `None` or malformed gets `verdict="NO_SCHEDULE"` and zeroed stats (mirrors `audit_min_pub`'s NO_SCHEDULE handling).

- [ ] **Step 1: Write the failing test**

Append to `lazer_dq/tests/test_active_min_pub.py`:

```python
from lazer_dq.active_min_pub import analyze_feed
from lazer_dq.min_pub_common import FeedSession


def _regular_session(feed_id=100, min_pub=2):
    return FeedSession(
        feed_id=feed_id,
        symbol="Equity.US.TEST/USD",
        asset_type="equity-us",
        session="REGULAR",
        allowed=frozenset({1, 2, 3, 4, 5}),
        effective_min_pub=min_pub,
        schedule_str="UTC;O,O,O,O,O,O,O",  # always open -> no masking effect
    )


def test_analyze_feed_one_row_per_session_with_verdict():
    start = datetime(2026, 7, 14, tzinfo=timezone.utc)
    end = datetime(2026, 7, 15, tzinfo=timezone.utc)
    # 200 updates all well above floor -> OK; feed_id 100, channel 1 has data.
    t = datetime(2026, 7, 14, 13, 30)
    rows = [(t, 5)] * 200
    client = ChannelClient({1: rows})
    result = analyze_feed(
        client,
        [_regular_session()],
        start,
        end,
        critical_pct=1.0,
        warn_pct=5.0,
        min_updates=100,
    )
    assert len(result) == 1
    r = result[0]
    assert set(r.keys()) == set(RESULT_COLUMNS)
    assert r["session"] == "REGULAR"
    assert r["n_updates"] == 200
    assert r["verdict"] == "OK"


def test_analyze_feed_no_data_when_no_channel_has_rows():
    start = datetime(2026, 7, 14, tzinfo=timezone.utc)
    end = datetime(2026, 7, 15, tzinfo=timezone.utc)
    client = ChannelClient({})  # empty
    result = analyze_feed(
        client, [_regular_session()], start, end, 1.0, 5.0, 100
    )
    assert result[0]["verdict"] == "NO_DATA"
    assert result[0]["n_updates"] == 0


def test_analyze_feed_malformed_schedule_yields_no_schedule():
    start = datetime(2026, 7, 14, tzinfo=timezone.utc)
    end = datetime(2026, 7, 15, tzinfo=timezone.utc)
    t = datetime(2026, 7, 14, 13, 30)
    client = ChannelClient({1: [(t, 5)] * 200})
    bad = FeedSession(
        feed_id=100,
        symbol="Equity.US.TEST/USD",
        asset_type="equity-us",
        session="PRE_MARKET",
        allowed=frozenset({1, 2}),
        effective_min_pub=2,
        schedule_str="not-a-schedule",
    )
    result = analyze_feed(client, [bad], start, end, 1.0, 5.0, 100)
    assert result[0]["verdict"] == "NO_SCHEDULE"
    assert set(result[0].keys()) == set(RESULT_COLUMNS)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source venv/bin/activate && python3 -m pytest lazer_dq/tests/test_active_min_pub.py -k analyze_feed -q`
Expected: FAIL with `ImportError: cannot import name 'analyze_feed'`.

- [ ] **Step 3: Implement `analyze_feed`**

Add to `lazer_dq/active_min_pub.py` (after `classify`):

```python
def _base_row(fs) -> dict:
    return {
        "feed_id": fs.feed_id,
        "symbol": fs.symbol,
        "asset_type": fs.asset_type,
        "session": fs.session,
        "effective_min_pub": fs.effective_min_pub,
    }


def _zeroed_stats() -> dict:
    return {
        "n_updates": 0,
        "min": 0,
        "p1": 0.0,
        "p5": 0.0,
        "median": 0.0,
        "pct_at_floor": 0.0,
        "pct_at_floor_1": 0.0,
    }


def analyze_feed(
    client, feed_sessions, start_utc, end_utc, critical_pct, warn_pct, min_updates
) -> list:
    """One price_feeds query for the feed; one result row per session."""
    rows = fetch_feed_rows(client, feed_sessions[0].feed_id, start_utc, end_utc)
    out = []
    for fs in feed_sessions:
        base = _base_row(fs)
        if not fs.schedule_str:
            out.append({**base, **_zeroed_stats(), "verdict": "NO_SCHEDULE"})
            continue
        try:
            counts = masked_counts(rows, fs.schedule_str, start_utc, end_utc)
        except ValueError:
            out.append({**base, **_zeroed_stats(), "verdict": "NO_SCHEDULE"})
            continue
        stats = distribution_stats(counts, fs.effective_min_pub)
        verdict = classify(stats, critical_pct, warn_pct, min_updates)
        out.append({**base, **stats, "verdict": verdict})
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source venv/bin/activate && python3 -m pytest lazer_dq/tests/test_active_min_pub.py -k analyze_feed -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Run the full test module**

Run: `source venv/bin/activate && python3 -m pytest lazer_dq/tests/test_active_min_pub.py -q`
Expected: PASS (all tests so far).

- [ ] **Step 6: Commit**

```bash
source venv/bin/activate
pre-commit run --files lazer_dq/active_min_pub.py lazer_dq/tests/test_active_min_pub.py || true
git add lazer_dq/active_min_pub.py lazer_dq/tests/test_active_min_pub.py
git commit -m "feat(active_min_pub): per-feed orchestration to per-session rows"
```

---

## Task 5: CLI, parallel sweep, CSV + console output

**Files:**
- Modify: `lazer_dq/active_min_pub.py`
- Test: `lazer_dq/tests/test_active_min_pub.py`

**Interfaces:**
- Consumes: `iter_stable_sessions`, `analyze_feed`, `ThreadLocalClients`/`load_config` from `lib.config`.
- Produces:
  - `default_window() -> tuple[datetime, datetime]` — last 7 full UTC days.
  - `parse_args(argv=None)` — flags: `--config` (required), `--start-date`, `--end-date`, `--critical-pct` (default 1.0), `--warn-pct` (default 5.0), `--min-updates` (default 100), `--workers` (default 8), `--feed-id` (nargs `*`), `--output-dir` (default `output_csv`).
  - `summarize(rows: list[dict]) -> dict[str, int]` — verdict -> count tally over result rows.
  - `main(argv=None) -> int`.

- [ ] **Step 1: Write the failing test for `default_window`, `parse_args`, and `summarize`**

Append to `lazer_dq/tests/test_active_min_pub.py`:

```python
from lazer_dq.active_min_pub import default_window, parse_args, summarize


def test_default_window_is_seven_full_utc_days():
    start, end = default_window()
    assert (end - start) == pd.Timedelta(days=7).to_pytimedelta()
    assert end.hour == 0 and end.minute == 0 and end.second == 0


def test_parse_args_defaults():
    args = parse_args(["--config", "lazer_newest.json"])
    assert args.config == "lazer_newest.json"
    assert args.critical_pct == 1.0
    assert args.warn_pct == 5.0
    assert args.min_updates == 100
    assert args.workers == 8


def test_summarize_tallies_by_verdict():
    rows = [
        {"verdict": "CRITICAL"},
        {"verdict": "CRITICAL"},
        {"verdict": "WARN"},
        {"verdict": "OK"},
        {"verdict": "NO_DATA"},
        {"verdict": "LOW_SAMPLE"},
    ]
    tally = summarize(rows)
    assert tally["CRITICAL"] == 2
    assert tally["WARN"] == 1
    assert tally["OK"] == 1
    assert tally["NO_DATA"] == 1
    assert tally["LOW_SAMPLE"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source venv/bin/activate && python3 -m pytest lazer_dq/tests/test_active_min_pub.py -k "default_window or parse_args or summarize" -q`
Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement CLI, `summarize`, `default_window`, and `main`**

Add to `lazer_dq/active_min_pub.py` (end of file, before any `__main__` guard):

```python
def default_window():
    """Last 7 full UTC days: [today-7 00:00, today 00:00)."""
    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return end - timedelta(days=7), end


def summarize(rows) -> dict:
    tally: dict = {}
    for r in rows:
        tally[r["verdict"]] = tally.get(r["verdict"], 0) + 1
    return tally


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True)
    p.add_argument("--start-date", help="UTC start date YYYY-MM-DD (inclusive)")
    p.add_argument("--end-date", help="UTC end date YYYY-MM-DD (exclusive)")
    p.add_argument("--critical-pct", type=float, default=1.0)
    p.add_argument("--warn-pct", type=float, default=5.0)
    p.add_argument("--min-updates", type=int, default=100)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--feed-id", type=int, nargs="*", help="restrict to these feeds")
    p.add_argument("--output-dir", default="output_csv")
    return p.parse_args(argv)


_VERDICT_ORDER = ["NO_DATA", "LOW_SAMPLE", "CRITICAL", "WARN", "OK", "NO_SCHEDULE"]


def main(argv=None) -> int:
    args = parse_args(argv)
    if bool(args.start_date) != bool(args.end_date):
        print("ERROR: pass both --start-date and --end-date, or neither")
        return 1
    if args.start_date:
        start_utc = datetime.strptime(args.start_date, "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
        end_utc = datetime.strptime(args.end_date, "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
    else:
        start_utc, end_utc = default_window()

    config = json.loads(Path(args.config).read_text())
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    by_feed: dict = {}
    for fs in iter_stable_sessions(config):
        if args.feed_id and fs.feed_id not in args.feed_id:
            continue
        by_feed.setdefault(fs.feed_id, []).append(fs)

    out_path = out_dir / (
        f"active_min_pub_{start_utc:%Y-%m-%d}_{end_utc:%Y-%m-%d}.csv"
    )
    print(f"Analyzing {len(by_feed)} feeds ({start_utc:%Y-%m-%d} .. {end_utc:%Y-%m-%d})")

    from lib.config import ThreadLocalClients, load_config

    write_lock = threading.Lock()
    all_rows: list = []
    csv_file = open(out_path, "w", newline="")
    writer = csv.DictWriter(csv_file, fieldnames=RESULT_COLUMNS, extrasaction="ignore")
    writer.writeheader()

    failures = 0
    with ThreadLocalClients(load_config(), lazer_only=True) as pool:

        def run_one(feed_sessions):
            client = pool.get_lazer_client()
            return analyze_feed(
                client,
                feed_sessions,
                start_utc,
                end_utc,
                args.critical_pct,
                args.warn_pct,
                args.min_updates,
            )

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(run_one, fss): fid for fid, fss in by_feed.items()
            }
            for i, future in enumerate(as_completed(futures), 1):
                fid = futures[future]
                try:
                    rows = future.result()
                except Exception as e:  # soft-fail, continue
                    failures += 1
                    print(f"  [{i}/{len(by_feed)}] feed {fid} FAILED: {e}")
                    continue
                with write_lock:
                    writer.writerows(rows)
                    csv_file.flush()
                    all_rows.extend(rows)
    csv_file.close()

    tally = summarize(all_rows)
    print(f"\nAnalysis written to {out_path} ({failures} feed failures)")
    for v in _VERDICT_ORDER:
        if v in tally:
            print(f"  {v:12} {tally[v]}")

    critical = sorted(
        (r for r in all_rows if r["verdict"] == "CRITICAL"),
        key=lambda r: r["pct_at_floor"],
        reverse=True,
    )
    if critical:
        print(f"\nCRITICAL feed-sessions ({len(critical)}):")
        for r in critical:
            print(
                f"  feed {r['feed_id']:>5} {r['symbol']:24} {r['session']:11} "
                f"min_pub={r['effective_min_pub']} pct_at_floor={r['pct_at_floor']:.2f}%"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source venv/bin/activate && python3 -m pytest lazer_dq/tests/test_active_min_pub.py -q`
Expected: PASS (all tests).

- [ ] **Step 5: Smoke-test the CLI arg validation (no DB)**

Run: `source venv/bin/activate && python3 -m lazer_dq.active_min_pub --config lazer_newest.json --start-date 2026-07-14`
Expected: prints `ERROR: pass both --start-date and --end-date, or neither` and exits 1.

- [ ] **Step 6: Commit**

```bash
source venv/bin/activate
pre-commit run --files lazer_dq/active_min_pub.py lazer_dq/tests/test_active_min_pub.py || true
git add lazer_dq/active_min_pub.py lazer_dq/tests/test_active_min_pub.py
git commit -m "feat(active_min_pub): CLI, parallel sweep, CSV + console output"
```

---

## Task 6: Docs + audit_min_pub distinction note

**Files:**
- Create: `docs/active_min_pub.md`
- Modify: `CLAUDE.md` (Scripts table + Key Gotchas)
- Modify: `lazer_dq/audit_min_pub.py:1-14` (docstring note)

**Interfaces:** none (docs only).

- [ ] **Step 1: Write `docs/active_min_pub.md`**

Create `docs/active_min_pub.md`:

```markdown
# active_min_pub

Aggregate publisher-count headroom sweep. For every STABLE `(feed, session)` in a
new-format Lazer config, reads the aggregate's own `publisher_count` per update
from the `price_feeds` table (highest-frequency channel = lowest-numbered channel
with data), session-masks to open hours, and reports the contributor-count
distribution vs the session's `minPublishers`.

## Distinct from `audit_min_pub`

| | `active_min_pub` | `audit_min_pub` |
| --- | --- | --- |
| Question | Aggregate contributor-count headroom | Per-minute publisher availability |
| Source | `price_feeds.publisher_count` | `publisher_updates` (distinct ACCEPTED) |
| Granularity | per aggregate update | per minute |

Use `active_min_pub` to answer "how close does each feed run to its min-pub floor,
at the aggregate level?" — the input to feed-by-feed remediation.

## Usage

    python3 -m lazer_dq.active_min_pub \
        --config lazer_newest.json \
        --start-date 2026-07-14 --end-date 2026-07-22 \
        [--critical-pct 1.0] [--warn-pct 5.0] [--min-updates 100] [--workers 8]

`--start-date`/`--end-date` are UTC (`end` exclusive). Omit both for the last 7
full UTC days. `--feed-id N ...` restricts the sweep.

## Output

`output_csv/active_min_pub_<start>_<end>.csv`, one row per feed-session:

`feed_id, symbol, asset_type, session, effective_min_pub, n_updates, min, p1, p5,
median, pct_at_floor, pct_at_floor_1, verdict`

- `pct_at_floor` — % of in-session updates with `publisher_count <= min_pub` (primary trigger).
- `pct_at_floor_1` — % with `publisher_count <= min_pub + 1` (context).

### Verdicts (precedence: NO_DATA > LOW_SAMPLE > CRITICAL > WARN > OK)

- **CRITICAL** — `pct_at_floor >= --critical-pct` (default 1.0%): regularly at/below floor.
- **WARN** — never at floor but `pct_at_floor_1 >= --warn-pct` (default 5.0%).
- **OK** — otherwise.
- **LOW_SAMPLE** — fewer than `--min-updates` (default 100) in-session updates.
- **NO_DATA** — no aggregate updates in the window (non-trading / not ingested).
- **NO_SCHEDULE** — session has no resolvable/parsable market schedule.

The console prints the verdict tally and the CRITICAL list (sorted by `pct_at_floor`).

## Sessions

US-equities feeds carry REGULAR / PRE_MARKET / POST_MARKET / OVER_NIGHT as distinct
`marketSchedules` entries, each with its own `minPublishers` and hours, so each gets
a standalone row masked to its own window. OVER_NIGHT (midnight-crossing) needs no
special-casing here because this analysis never touches a Datascope benchmark.
```

- [ ] **Step 2: Add the Scripts-table row and Key Gotchas line to `CLAUDE.md`**

In `CLAUDE.md`, add a row to the Scripts table (after the `incumbent_quality.py` row):

```markdown
| `lazer_dq/active_min_pub.py`            | Aggregate publisher-count headroom sweep: per STABLE feed-session, distribution of `price_feeds.publisher_count` per update vs `minPublishers`                                                                          | `python3 -m lazer_dq.active_min_pub --config lazer_newest.json --start-date A --end-date B`             | [docs/active_min_pub.md](docs/active_min_pub.md)                         |
```

Add to the "Key Gotchas" list:

```markdown
- **`active_min_pub` vs `audit_min_pub`** — `active_min_pub` reads the per-aggregate `publisher_count` from `price_feeds` (contributor headroom, the min-pub-distance question); `audit_min_pub` counts per-minute distinct ACCEPTED publishers from `publisher_updates` (availability). Different question — do not conflate. `active_min_pub` picks the highest-frequency channel by probing `price_feeds.channel` 1→2→3 (config `minChannel` is symbolic `realTime`/`rate`, not a channel number).
```

- [ ] **Step 3: Add the distinction note to `audit_min_pub.py`**

In `lazer_dq/audit_min_pub.py`, edit the module docstring (line 1-14) to add, after the opening summary line:

```python
"""Stage 1 of the min_pub pipeline: audit active publishers vs minPublishers.

NOTE: measures per-MINUTE distinct ACCEPTED publishers (availability). For the
aggregate contributor-count headroom question (per-aggregate publisher_count vs
minPublishers) use lazer_dq.active_min_pub instead — different question.

For every STABLE (feed, session) in a new-format Lazer config, counts
...
```

- [ ] **Step 4: Verify docs render / no broken table**

Run: `source venv/bin/activate && python3 -c "import lazer_dq.audit_min_pub, lazer_dq.active_min_pub; print('imports OK')"`
Expected: `imports OK` (confirms the docstring edit didn't break the module).

- [ ] **Step 5: Commit**

```bash
source venv/bin/activate
pre-commit run --files docs/active_min_pub.md CLAUDE.md lazer_dq/audit_min_pub.py || true
git add docs/active_min_pub.md CLAUDE.md lazer_dq/audit_min_pub.py
git commit -m "docs(active_min_pub): usage doc, scripts-table row, audit distinction note"
```

---

## Task 7: End-to-end verification

**Files:** none (verification only).

- [ ] **Step 1: Full test suite for the module**

Run: `source venv/bin/activate && python3 -m pytest lazer_dq/tests/test_active_min_pub.py -v`
Expected: all tests PASS.

- [ ] **Step 2: Confirm no regression in the existing min_pub tests**

Run: `source venv/bin/activate && python3 -m pytest lazer_dq/tests/test_audit_min_pub.py lazer_dq/tests/test_min_pub_common.py -q`
Expected: all PASS (the docstring edit is inert).

- [ ] **Step 3: Live smoke run against ClickHouse (requires `config.yaml`)**

Run:
```bash
source venv/bin/activate
python3 -m lazer_dq.active_min_pub --config lazer_newest.json \
    --start-date 2026-07-14 --end-date 2026-07-15 \
    --feed-id 1080 --workers 2
```
Expected: prints "Analyzing 1 feeds …", writes `output_csv/active_min_pub_2026-07-14_2026-07-15.csv`, and prints a verdict tally. (Feed 1080 = DIA ETF from the transcript; adjust if needed.) Confirm the CSV has one row per session for the feed with populated `n_updates` and a plausible `pct_at_floor`.

- [ ] **Step 4: Sanity-check against the transcript's manual method**

Manually eyeball one feed-session: the `min` in the CSV should match the lowest `publisher_count` you see querying `price_feeds` directly for that feed/session window. Document the spot-check in the PR description.

---

## Self-Review Notes

- **Spec coverage:** universe/floors (Task 5 `iter_stable_sessions`), channel probe (Task 3), session mask incl. overnight (Task 2), stats + verdict incl. NO_DATA/LOW_SAMPLE distinct (Task 1), CSV + console (Task 5), docs + distinction note (Task 6), session coverage (Task 2 overnight test + Task 6 docs). All spec sections mapped.
- **`NO_SCHEDULE`** is an implementation-level verdict not in the spec's five; it mirrors `audit_min_pub` for robustness and is documented. Precedence list in output includes it last.
- **Percent scale** is 0–100 consistently (stats, thresholds, tests).
