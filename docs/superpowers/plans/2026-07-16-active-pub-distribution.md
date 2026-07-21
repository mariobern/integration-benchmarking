# Active Publisher Distribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A diagnostic script that, for every STABLE (feed, session) in a new-format Lazer config, reports the distribution of per-minute active publisher counts (skew vs minPublishers) and per-publisher update concentration, plus an HTML report renderer.

**Architecture:** One new script `lazer_dq/active_pub_distribution.py` (query + pure metric functions + two-CSV writer with resume), one renderer `lazer_dq/render_active_pub_html.py` (CSVs → self-contained HTML, no DB), reusing `min_pub_common` / `market_schedule` for enumeration and session masking and importing resume helpers from `incumbent_quality`. Spec: `docs/superpowers/specs/2026-07-16-active-pub-distribution-design.md`.

**Tech Stack:** Python 3, numpy/pandas, clickhouse-connect (via `lib.config`), pytest, stdlib `html`/`argparse` for the renderer.

## Global Constraints

- `python` is not on PATH — always `source venv/bin/activate` first, then `python3` / `pytest`.
- Run `pre-commit run --files <changed files>` before every commit (black, prettier, whitespace hooks).
- Do NOT modify `lazer_dq/audit_min_pub.py`, `lazer_dq/qualify_candidates.py`, `lazer_dq/apply_min_pub_remediation.py`, `lazer_dq/incumbent_quality.py`, `lazer_dq/min_pub_common.py`, or `lazer_dq/market_schedule.py` — import from them only.
- All percentage/share/effective-publisher values are rounded to 2 decimal places.
- Every ClickHouse parameter uses `{name:Type}` syntax with `parameters=dict`.
- CSV columns and note values must match the spec exactly: notes are `""`, `NO_SCHEDULE`, `ZERO_OPEN_MINUTES`, `SKIPPED_DEPRECATED`.

## Interfaces available from the existing codebase (read-only)

```python
from lazer_dq.min_pub_common import FeedSession, deprecated_stable_feeds, iter_stable_sessions
# FeedSession(frozen dataclass): feed_id:int, symbol:str, asset_type:str, session:str,
#   allowed:frozenset[int], effective_min_pub:int, schedule_str:str|None
# iter_stable_sessions(config: dict) -> Iterator[FeedSession]   (STABLE, non-DEPRECATED)
# deprecated_stable_feeds(config: dict) -> list[{"feed_id","symbol"}]

from lazer_dq.market_schedule import open_minutes_mask, parse_market_schedule
# parse_market_schedule(s: str) -> MarketSchedule            (raises ValueError)
# open_minutes_mask(sched, start_utc, end_utc) -> pd.Series  (bool, UTC-minute index)
# Schedule grammar: "<tz>;<mon>,...,<sun>[;<overrides>]", day = "O" | "C" | "HHMM-HHMM[&...]"
# e.g. "UTC;O,O,O,O,O,C,C" = 24h Mon-Fri.

from lazer_dq.audit_min_pub import default_window
# default_window() -> (start_utc, end_utc)  last 7 full UTC days

from lazer_dq.incumbent_quality import prune_orphan_rows, resume_done_feed_ids
# resume_done_feed_ids(summary_path: Path) -> set[int]
# prune_orphan_rows(path: Path, done_feed_ids: set) -> int   (rewrites CSV in place)

from lib.config import ThreadLocalClients, load_config
# with ThreadLocalClients(load_config(), lazer_only=True) as pool:
#     client = pool.get_lazer_client()
```

---

### Task 1: Pure metric functions

**Files:**

- Create: `lazer_dq/active_pub_distribution.py`
- Create: `tests/test_active_pub_distribution.py`

**Interfaces:**

- Consumes: numpy only.
- Produces (used by Task 2):

  - `histogram_pcts(active_counts: np.ndarray) -> dict[int, float]`
  - `encode_hist(hist: dict[int, float]) -> str`
  - `skew_metrics(active_counts: np.ndarray, min_pub: int) -> dict` (keys: `open_minutes, pct_minutes_le_min, pct_minutes_le_min_plus_1, p10_active, median_active, p90_active, worst_minute_active`)
  - `concentration_metrics(update_totals: dict[int, int]) -> dict` (keys: `effective_publishers, top1_share_pct, top3_share_pct`)

- [ ] **Step 1: Write the failing tests**

Create `tests/test_active_pub_distribution.py`:

```python
"""Tests for lazer_dq.active_pub_distribution pure functions."""
import numpy as np

from lazer_dq.active_pub_distribution import (
    concentration_metrics,
    encode_hist,
    histogram_pcts,
    skew_metrics,
)


def test_histogram_pcts_and_encode():
    counts = np.array([3, 4, 4, 5, 5, 5, 5, 5])
    hist = histogram_pcts(counts)
    assert hist == {3: 12.5, 4: 25.0, 5: 62.5}
    assert encode_hist(hist) == "3:12.50;4:25.00;5:62.50"


def test_histogram_all_zero_minutes():
    assert encode_hist(histogram_pcts(np.zeros(4, dtype=int))) == "0:100.00"


def test_histogram_empty():
    assert histogram_pcts(np.array([], dtype=int)) == {}
    assert encode_hist({}) == ""


def test_skew_metrics():
    counts = np.array([2, 3, 4, 5, 5, 5, 5, 5, 5, 5])
    m = skew_metrics(counts, min_pub=3)
    assert m["open_minutes"] == 10
    assert m["pct_minutes_le_min"] == 20.0        # 2 and 3
    assert m["pct_minutes_le_min_plus_1"] == 30.0  # 2, 3 and 4
    assert m["p10_active"] == 2.9                  # linear interpolation
    assert m["median_active"] == 5.0
    assert m["p90_active"] == 5.0
    assert m["worst_minute_active"] == 2


def test_concentration_uniform():
    m = concentration_metrics({1: 100, 2: 100, 3: 100, 4: 100})
    assert m["effective_publishers"] == 4.0
    assert m["top1_share_pct"] == 25.0
    assert m["top3_share_pct"] == 75.0


def test_concentration_dominated():
    m = concentration_metrics({1: 80, 2: 10, 3: 10, 4: 0})
    assert m["effective_publishers"] == round(1 / 0.66, 2)  # hhi = .64+.01+.01
    assert m["top1_share_pct"] == 80.0
    assert m["top3_share_pct"] == 100.0


def test_concentration_no_updates():
    assert concentration_metrics({1: 0, 2: 0}) == {
        "effective_publishers": 0.0,
        "top1_share_pct": 0.0,
        "top3_share_pct": 0.0,
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source venv/bin/activate && pytest tests/test_active_pub_distribution.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lazer_dq.active_pub_distribution'` (or ImportError).

- [ ] **Step 3: Write the implementation**

Create `lazer_dq/active_pub_distribution.py`:

```python
"""Diagnostic: active-publisher distribution + update concentration.

For every STABLE (feed, session) in a new-format Lazer config, over a UTC
date window restricted to session open minutes:

  - histogram of per-minute active publisher counts (skew vs minPublishers);
    a publisher is active in a minute iff it has >=1 ACCEPTED update there
  - per-publisher ACCEPTED update totals and concentration
    (effective publishers = inverse HHI, top-1/top-3 shares)

Pure diagnostic: no config edits, no coupling to the min_pub Stage 1-3
pipeline. Render the CSVs with lazer_dq.render_active_pub_html.

Run:
    python3 -m lazer_dq.active_pub_distribution --config lazer_new.json \
        --start-date 2026-07-09 --end-date 2026-07-16 --workers 8
"""
from __future__ import annotations

import numpy as np


def histogram_pcts(active_counts: np.ndarray) -> dict[int, float]:
    """% of open minutes at each active-count k (2 dp). {} for empty input."""
    if len(active_counts) == 0:
        return {}
    values, counts = np.unique(active_counts, return_counts=True)
    n = len(active_counts)
    return {int(k): round(100.0 * c / n, 2) for k, c in zip(values, counts)}


def encode_hist(hist: dict[int, float]) -> str:
    """Compact CSV encoding: '3:12.50;4:25.00;5:62.50' (ascending k)."""
    return ";".join(f"{k}:{pct:.2f}" for k, pct in sorted(hist.items()))


def skew_metrics(active_counts: np.ndarray, min_pub: int) -> dict:
    """Skew of the active-count distribution vs min_pub. Caller ensures len > 0."""
    n = len(active_counts)
    return {
        "open_minutes": n,
        "pct_minutes_le_min": round(
            100.0 * int((active_counts <= min_pub).sum()) / n, 2
        ),
        "pct_minutes_le_min_plus_1": round(
            100.0 * int((active_counts <= min_pub + 1).sum()) / n, 2
        ),
        "p10_active": round(float(np.percentile(active_counts, 10)), 2),
        "median_active": round(float(np.median(active_counts)), 2),
        "p90_active": round(float(np.percentile(active_counts, 90)), 2),
        "worst_minute_active": int(active_counts.min()),
    }


def concentration_metrics(update_totals: dict[int, int]) -> dict:
    """Inverse-HHI effective publishers + top-1/top-3 shares of ACCEPTED updates."""
    total = sum(update_totals.values())
    if total == 0:
        return {
            "effective_publishers": 0.0,
            "top1_share_pct": 0.0,
            "top3_share_pct": 0.0,
        }
    shares = sorted((u / total for u in update_totals.values() if u > 0), reverse=True)
    hhi = sum(s * s for s in shares)
    return {
        "effective_publishers": round(1.0 / hhi, 2),
        "top1_share_pct": round(100.0 * shares[0], 2),
        "top3_share_pct": round(100.0 * sum(shares[:3]), 2),
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source venv/bin/activate && pytest tests/test_active_pub_distribution.py -v`
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
pre-commit run --files lazer_dq/active_pub_distribution.py tests/test_active_pub_distribution.py
git add lazer_dq/active_pub_distribution.py tests/test_active_pub_distribution.py
git commit -m "feat(lazer_dq): active_pub_distribution metric functions

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Row builders (session_rows, process_feed)

**Files:**

- Modify: `lazer_dq/active_pub_distribution.py` (append)
- Modify: `tests/test_active_pub_distribution.py` (append)

**Interfaces:**

- Consumes: Task 1 functions; `FeedSession`, `parse_market_schedule`, `open_minutes_mask` (see codebase interfaces above).
- Produces (used by Task 3):

  - `SUMMARY_COLUMNS: list[str]`, `DETAIL_COLUMNS: list[str]`
  - `session_rows(fs: FeedSession, per_minute: dict[pd.Timestamp, dict[int, int]], mask: pd.Series) -> tuple[dict, list[dict]]`
  - `process_feed(client, feed_sessions: list[FeedSession], start_utc, end_utc) -> tuple[list[dict], list[dict]]` — calls `fetch_per_minute_counts(client, feed_id, start_utc, end_utc)` which Task 3 defines; until then tests monkeypatch it, so define a placeholder in this task (see Step 3).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_active_pub_distribution.py`:

```python
import pandas as pd

from lazer_dq.active_pub_distribution import process_feed, session_rows
from lazer_dq.min_pub_common import FeedSession


def make_fs(**kw):
    defaults = dict(
        feed_id=1,
        symbol="Equity.US.TEST/USD",
        asset_type="equity",
        session="REGULAR",
        allowed=frozenset({10, 20, 30}),
        effective_min_pub=2,
        schedule_str="UTC;O,O,O,O,O,C,C",
    )
    defaults.update(kw)
    return FeedSession(**defaults)


def make_mask(start="2026-07-13 09:00", periods=4, open_all=True):
    idx = pd.date_range(start, periods=periods, freq="1min", tz="UTC")
    return pd.Series(open_all, index=idx)


def minute(start, offset):
    return pd.Timestamp(start, tz="UTC") + pd.Timedelta(minutes=offset)


def test_session_rows_metrics_and_details():
    fs = make_fs()
    m0 = "2026-07-13 09:00"
    # minute 0: pubs 10,20 active; minute 1: only 10; minutes 2,3: nothing.
    # pub 99 is NOT allowed -> unlisted, excluded from all metrics.
    per_minute = {
        minute(m0, 0): {10: 5, 20: 1, 99: 7},
        minute(m0, 1): {10: 3},
    }
    summary, details = session_rows(fs, per_minute, make_mask(m0, periods=4))
    assert summary["note"] == ""
    assert summary["allowed_count"] == 3
    assert summary["active_pub_count"] == 2       # 10 and 20
    assert summary["never_published_count"] == 1  # 30
    assert summary["unlisted_active_count"] == 1  # 99
    assert summary["total_accepted_updates"] == 9  # 5+1+3, pub 99 excluded
    assert summary["open_minutes"] == 4
    # active counts per minute: [2, 1, 0, 0]
    assert summary["active_hist"] == "0:50.00;1:25.00;2:25.00"
    assert summary["pct_minutes_le_min"] == 100.0  # all minutes <= min_pub 2
    assert summary["worst_minute_active"] == 0
    assert summary["top1_share_pct"] == round(100.0 * 8 / 9, 2)

    assert [d["publisher_id"] for d in details] == [10, 20, 30]  # rank order
    assert [d["rank"] for d in details] == [1, 2, 3]
    d10 = details[0]
    assert d10["accepted_updates"] == 8
    assert d10["update_share_pct"] == round(100.0 * 8 / 9, 2)
    assert d10["minutes_active"] == 2
    assert d10["pct_open_minutes_active"] == 50.0
    d30 = details[2]
    assert d30["accepted_updates"] == 0
    assert d30["update_share_pct"] == 0.0


def test_session_rows_zero_open_minutes():
    summary, details = session_rows(make_fs(), {}, make_mask(open_all=False))
    assert summary["note"] == "ZERO_OPEN_MINUTES"
    assert details == []
    assert summary["allowed_count"] == 3
    assert "active_hist" not in summary


def test_session_rows_no_updates():
    summary, details = session_rows(make_fs(), {}, make_mask())
    assert summary["note"] == ""
    assert summary["active_hist"] == "0:100.00"
    assert summary["effective_publishers"] == 0.0
    assert len(details) == 3
    assert all(d["update_share_pct"] == 0.0 for d in details)


def test_process_feed_no_schedule(monkeypatch):
    import lazer_dq.active_pub_distribution as apd

    monkeypatch.setattr(apd, "fetch_per_minute_counts", lambda *a: {})
    sessions = [
        make_fs(session="PRE", schedule_str=None),
        make_fs(session="POST", schedule_str="garbage-no-semicolons"),
    ]
    summaries, details = process_feed(None, sessions, None, None)
    assert [s["note"] for s in summaries] == ["NO_SCHEDULE", "NO_SCHEDULE"]
    assert details == []


def test_process_feed_valid_schedule(monkeypatch):
    import lazer_dq.active_pub_distribution as apd

    from datetime import datetime, timezone

    monkeypatch.setattr(
        apd,
        "fetch_per_minute_counts",
        lambda *a: {minute("2026-07-13 00:00", 0): {10: 2}},
    )
    start = datetime(2026, 7, 13, tzinfo=timezone.utc)  # a Monday
    end = datetime(2026, 7, 14, tzinfo=timezone.utc)
    summaries, details = process_feed(None, [make_fs()], start, end)
    assert summaries[0]["note"] == ""
    assert summaries[0]["open_minutes"] == 1440
    assert summaries[0]["active_pub_count"] == 1
    assert len(details) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source venv/bin/activate && pytest tests/test_active_pub_distribution.py -v`
Expected: new tests FAIL with `ImportError: cannot import name 'session_rows'`; Task 1 tests still pass.

- [ ] **Step 3: Write the implementation**

Append to `lazer_dq/active_pub_distribution.py` (add `import pandas as pd` and the `min_pub_common`/`market_schedule` imports below to the import block at the top of the file):

```python
import pandas as pd

from lazer_dq.market_schedule import open_minutes_mask, parse_market_schedule
from lazer_dq.min_pub_common import FeedSession

SUMMARY_COLUMNS = [
    "feed_id",
    "symbol",
    "asset_type",
    "session",
    "note",
    "effective_min_pub",
    "allowed_count",
    "active_pub_count",
    "never_published_count",
    "unlisted_active_count",
    "open_minutes",
    "total_accepted_updates",
    "pct_minutes_le_min",
    "pct_minutes_le_min_plus_1",
    "p10_active",
    "median_active",
    "p90_active",
    "worst_minute_active",
    "active_hist",
    "effective_publishers",
    "top1_share_pct",
    "top3_share_pct",
]

DETAIL_COLUMNS = [
    "feed_id",
    "symbol",
    "session",
    "publisher_id",
    "accepted_updates",
    "update_share_pct",
    "minutes_active",
    "pct_open_minutes_active",
    "rank",
]


def fetch_per_minute_counts(client, feed_id, start_utc, end_utc):
    """Placeholder; defined with the query in the CLI section (Task 3)."""
    raise NotImplementedError


def _base(fs: FeedSession) -> dict:
    return {
        "feed_id": fs.feed_id,
        "symbol": fs.symbol,
        "asset_type": fs.asset_type,
        "session": fs.session,
        "note": "",
        "effective_min_pub": fs.effective_min_pub,
        "allowed_count": len(fs.allowed),
    }


def session_rows(fs, per_minute, mask):
    """(summary_row, detail_rows) for one feed-session.

    per_minute: dict UTC-minute pd.Timestamp -> {publisher_id: accepted_count}.
    Only allowed publishers count toward metrics; others feed
    unlisted_active_count (config snapshot drift sanity flag).
    """
    base = _base(fs)
    open_minutes = mask.index[mask.to_numpy()]
    if len(open_minutes) == 0:
        return {**base, "note": "ZERO_OPEN_MINUTES"}, []

    totals = {p: 0 for p in fs.allowed}
    minutes_active = {p: 0 for p in fs.allowed}
    counts = np.zeros(len(open_minutes), dtype=int)
    unlisted = set()
    for i, m in enumerate(open_minutes):
        for pub, n_updates in per_minute.get(m, {}).items():
            if pub in totals:
                totals[pub] += n_updates
                minutes_active[pub] += 1
                counts[i] += 1
            else:
                unlisted.add(pub)

    total_updates = int(sum(totals.values()))
    summary = {
        **base,
        "active_pub_count": sum(1 for u in totals.values() if u > 0),
        "never_published_count": sum(1 for u in totals.values() if u == 0),
        "unlisted_active_count": len(unlisted),
        "total_accepted_updates": total_updates,
        "active_hist": encode_hist(histogram_pcts(counts)),
        **skew_metrics(counts, fs.effective_min_pub),
        **concentration_metrics(totals),
    }

    n_open = len(open_minutes)
    ordered = sorted(fs.allowed, key=lambda p: (-totals[p], p))
    details = [
        {
            "feed_id": fs.feed_id,
            "symbol": fs.symbol,
            "session": fs.session,
            "publisher_id": p,
            "accepted_updates": totals[p],
            "update_share_pct": round(100.0 * totals[p] / total_updates, 2)
            if total_updates
            else 0.0,
            "minutes_active": minutes_active[p],
            "pct_open_minutes_active": round(100.0 * minutes_active[p] / n_open, 2),
            "rank": rank,
        }
        for rank, p in enumerate(ordered, 1)
    ]
    return summary, details


def process_feed(client, feed_sessions, start_utc, end_utc):
    """All sessions of one feed from a single ClickHouse query."""
    per_minute = fetch_per_minute_counts(
        client, feed_sessions[0].feed_id, start_utc, end_utc
    )
    summaries, details = [], []
    for fs in feed_sessions:
        if fs.schedule_str is None:
            summaries.append({**_base(fs), "note": "NO_SCHEDULE"})
            continue
        try:
            schedule = parse_market_schedule(fs.schedule_str)
        except ValueError:
            summaries.append({**_base(fs), "note": "NO_SCHEDULE"})
            continue
        mask = open_minutes_mask(schedule, start_utc, end_utc)
        s, d = session_rows(fs, per_minute, mask)
        summaries.append(s)
        details.extend(d)
    return summaries, details
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source venv/bin/activate && pytest tests/test_active_pub_distribution.py -v`
Expected: 12 passed.

- [ ] **Step 5: Commit**

```bash
pre-commit run --files lazer_dq/active_pub_distribution.py tests/test_active_pub_distribution.py
git add lazer_dq/active_pub_distribution.py tests/test_active_pub_distribution.py
git commit -m "feat(lazer_dq): active_pub_distribution row builders (session/feed)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: ClickHouse fetch + CLI main with resume

**Files:**

- Modify: `lazer_dq/active_pub_distribution.py` (replace the `fetch_per_minute_counts` placeholder; append CLI)
- Modify: `tests/test_active_pub_distribution.py` (append)

**Interfaces:**

- Consumes: Tasks 1–2; `iter_stable_sessions`, `deprecated_stable_feeds`, `default_window`, `resume_done_feed_ids`, `prune_orphan_rows`, `ThreadLocalClients`, `load_config` (see codebase interfaces above).
- Produces: `python3 -m lazer_dq.active_pub_distribution` CLI writing `output_csv/active_pub_distribution_<start>_<end>.csv` and `output_csv/active_pub_publishers_<start>_<end>.csv`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_active_pub_distribution.py`:

```python
from lazer_dq.active_pub_distribution import fetch_per_minute_counts, parse_args


class _StubResult:
    def __init__(self, rows):
        self.result_rows = rows


class _StubClient:
    def __init__(self, rows):
        self._rows = rows
        self.calls = []

    def query(self, q, parameters=None):
        self.calls.append(parameters)
        return _StubResult(self._rows)


def test_fetch_per_minute_counts_shapes_rows():
    from datetime import datetime, timezone

    ts0 = datetime(2026, 7, 13, 9, 0)
    client = _StubClient([(ts0, 10, 5), (ts0, 20, 1)])
    out = fetch_per_minute_counts(
        client,
        1,
        datetime(2026, 7, 13, tzinfo=timezone.utc),
        datetime(2026, 7, 14, tzinfo=timezone.utc),
    )
    key = pd.Timestamp("2026-07-13 09:00", tz="UTC")
    assert out == {key: {10: 5, 20: 1}}
    assert client.calls[0]["feed_id"] == 1
    assert client.calls[0]["start"] == "2026-07-13 00:00:00"


def test_parse_args_defaults():
    args = parse_args(["--config", "x.json"])
    assert args.workers == 8
    assert args.output_dir == "output_csv"
    assert not args.resume
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source venv/bin/activate && pytest tests/test_active_pub_distribution.py -v`
Expected: `test_fetch_per_minute_counts_shapes_rows` FAILS with `NotImplementedError`; `test_parse_args_defaults` FAILS with ImportError for `parse_args`.

- [ ] **Step 3: Write the implementation**

In `lazer_dq/active_pub_distribution.py`, extend the import block at the top:

```python
import argparse
import csv
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from lazer_dq.audit_min_pub import default_window
from lazer_dq.incumbent_quality import prune_orphan_rows, resume_done_feed_ids
from lazer_dq.min_pub_common import deprecated_stable_feeds, iter_stable_sessions
```

REPLACE the `fetch_per_minute_counts` placeholder (the whole `def` including its docstring and `raise NotImplementedError`) with:

```python
PER_MINUTE_COUNTS_QUERY = """
    SELECT
        toStartOfMinute(publish_time) AS minute,
        publisher_id,
        countIf(status = 'ACCEPTED') AS accepted
    FROM publisher_updates
    PREWHERE price_feed_id = {feed_id:UInt64}
    WHERE publish_time >= {start:String}
      AND publish_time < {end:String}
    GROUP BY minute, publisher_id
    HAVING accepted > 0
    ORDER BY minute
"""


def fetch_per_minute_counts(client, feed_id, start_utc, end_utc):
    """dict UTC-minute pd.Timestamp -> {publisher_id: accepted_update_count}."""
    result = client.query(
        PER_MINUTE_COUNTS_QUERY,
        parameters={
            "feed_id": feed_id,
            "start": start_utc.strftime("%Y-%m-%d %H:%M:%S"),
            "end": end_utc.strftime("%Y-%m-%d %H:%M:%S"),
        },
    )
    out = {}
    for minute, publisher_id, accepted in result.result_rows:
        out.setdefault(pd.Timestamp(minute, tz="UTC"), {})[int(publisher_id)] = int(
            accepted
        )
    return out
```

Append at the end of the file:

```python
def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True)
    p.add_argument("--start-date", help="UTC start date YYYY-MM-DD (inclusive)")
    p.add_argument("--end-date", help="UTC end date YYYY-MM-DD (exclusive)")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--feed-id", type=int, nargs="*", help="restrict to these feeds")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--output-dir", default="output_csv")
    return p.parse_args(argv)


def main(argv=None) -> int:
    from datetime import datetime, timezone

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
    stamp = f"{start_utc:%Y-%m-%d}_{end_utc:%Y-%m-%d}"
    summary_path = out_dir / f"active_pub_distribution_{stamp}.csv"
    detail_path = out_dir / f"active_pub_publishers_{stamp}.csv"

    by_feed = {}
    for fs in iter_stable_sessions(config):
        if args.feed_id and fs.feed_id not in args.feed_id:
            continue
        by_feed.setdefault(fs.feed_id, []).append(fs)

    resuming = args.resume and summary_path.exists()
    done = resume_done_feed_ids(summary_path) if args.resume else set()
    if resuming:
        n_pruned = prune_orphan_rows(detail_path, done)
        if n_pruned:
            print(f"Resume: pruned {n_pruned} orphan rows from {detail_path}")
        print(f"Resume: skipping {len(done)} already-processed feeds")
    todo = {fid: fss for fid, fss in by_feed.items() if fid not in done}
    print(f"Processing {len(todo)} feeds ({start_utc:%Y-%m-%d} .. {end_utc:%Y-%m-%d})")

    from lib.config import ThreadLocalClients, load_config

    mode = "a" if resuming else "w"
    summary_f = open(summary_path, mode, newline="")
    detail_f = open(detail_path, mode, newline="")
    summary_w = csv.DictWriter(
        summary_f, fieldnames=SUMMARY_COLUMNS, extrasaction="ignore", restval=""
    )
    detail_w = csv.DictWriter(
        detail_f, fieldnames=DETAIL_COLUMNS, extrasaction="ignore", restval=""
    )
    if not resuming:
        summary_w.writeheader()
        detail_w.writeheader()
        for row in deprecated_stable_feeds(config):
            summary_w.writerow(
                {
                    "feed_id": row["feed_id"],
                    "symbol": row["symbol"],
                    "note": "SKIPPED_DEPRECATED",
                }
            )
        summary_f.flush()
        detail_f.flush()

    write_lock = threading.Lock()
    failures = 0
    with ThreadLocalClients(load_config(), lazer_only=True) as pool:

        def run_one(feed_sessions):
            client = pool.get_lazer_client()
            return process_feed(client, feed_sessions, start_utc, end_utc)

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(run_one, fss): fid for fid, fss in todo.items()}
            for i, future in enumerate(as_completed(futures), 1):
                fid = futures[future]
                try:
                    summaries, details = future.result()
                except Exception as e:  # soft-fail, continue (bulk-runner pattern)
                    failures += 1
                    print(f"  [{i}/{len(todo)}] feed {fid} FAILED: {e}")
                    continue
                with write_lock:
                    # Flush order is intentional: the summary row is the
                    # resume marker, so it must be made durable last. A crash
                    # in between leaves orphan detail rows that --resume
                    # prunes on the next run.
                    detail_w.writerows(details)
                    detail_f.flush()
                    summary_w.writerows(summaries)
                    summary_f.flush()
                worst = max(
                    (s.get("pct_minutes_le_min", 0.0) or 0.0 for s in summaries),
                    default=0.0,
                )
                print(f"  [{i}/{len(todo)}] feed {fid}: worst <=min_pub {worst:.1f}%")
    summary_f.close()
    detail_f.close()
    print(f"Summary written to {summary_path}")
    print(f"Per-publisher detail written to {detail_path} ({failures} feed failures)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source venv/bin/activate && pytest tests/test_active_pub_distribution.py -v`
Expected: 14 passed. (`main()` itself needs ClickHouse and is exercised in the production run, matching how `audit_min_pub`/`incumbent_quality` are verified.)

- [ ] **Step 5: Sanity-check the CLI wiring without a database**

Run: `source venv/bin/activate && python3 -m lazer_dq.active_pub_distribution --config /nonexistent.json 2>&1 | tail -1`
Expected: `FileNotFoundError` traceback mentioning `/nonexistent.json` (proves module imports and arg-parsing run; no DB touched).

- [ ] **Step 6: Commit**

```bash
pre-commit run --files lazer_dq/active_pub_distribution.py tests/test_active_pub_distribution.py
git add lazer_dq/active_pub_distribution.py tests/test_active_pub_distribution.py
git commit -m "feat(lazer_dq): active_pub_distribution CLI with two-CSV resume

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: HTML report renderer

**Files:**

- Create: `lazer_dq/render_active_pub_html.py`
- Modify: `tests/test_active_pub_distribution.py` (append)

**Interfaces:**

- Consumes: the two CSVs from Task 3 (columns per `SUMMARY_COLUMNS` / `DETAIL_COLUMNS`). No imports from `active_pub_distribution` — the renderer reads CSVs only, so it works on any past run's files.
- Produces: `python3 -m lazer_dq.render_active_pub_html --summary S.csv --publishers P.csv [--output R.html] [--top 50]`; also `render_page(summary_df, detail_df, top) -> str` for tests.

Design constraints (from the dataviz pass): single-series histogram → one sequential blue for bars; bars at k ≤ min_pub use the reserved status-critical red, and the caption states "red bars ≤ min pub N" so meaning is never color-alone; text stays in ink tokens, never series colors; light and dark palettes both defined (media query + `data-theme` override); per-bar `title` tooltip carries exact values; no external assets (must render offline / under Artifact CSP); table numerics use `tabular-nums`; wide table scrolls in its own container.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_active_pub_distribution.py`:

```python
from lazer_dq.render_active_pub_html import parse_hist, render_page


def _report_frames():
    summary = pd.DataFrame(
        [
            {
                "feed_id": 1, "symbol": "Equity.US.AAA/USD", "asset_type": "equity",
                "session": "REGULAR", "note": "", "effective_min_pub": 2,
                "allowed_count": 4, "active_pub_count": 3,
                "never_published_count": 1, "unlisted_active_count": 0,
                "open_minutes": 100, "total_accepted_updates": 900,
                "pct_minutes_le_min": 40.0, "pct_minutes_le_min_plus_1": 90.0,
                "p10_active": 1.0, "median_active": 2.0, "p90_active": 3.0,
                "worst_minute_active": 1, "active_hist": "1:40.00;2:50.00;3:10.00",
                "effective_publishers": 1.8, "top1_share_pct": 70.0,
                "top3_share_pct": 99.0,
            },
            {
                "feed_id": 2, "symbol": "Fx.EUR/USD", "asset_type": "fx",
                "session": "REGULAR", "note": "NO_SCHEDULE",
                "effective_min_pub": 2, "allowed_count": 5,
            },
        ]
    )
    detail = pd.DataFrame(
        [
            {"feed_id": 1, "symbol": "Equity.US.AAA/USD", "session": "REGULAR",
             "publisher_id": 10, "accepted_updates": 630, "update_share_pct": 70.0,
             "minutes_active": 90, "pct_open_minutes_active": 90.0, "rank": 1},
            {"feed_id": 1, "symbol": "Equity.US.AAA/USD", "session": "REGULAR",
             "publisher_id": 20, "accepted_updates": 270, "update_share_pct": 30.0,
             "minutes_active": 60, "pct_open_minutes_active": 60.0, "rank": 2},
        ]
    )
    return summary, detail


def test_parse_hist():
    assert parse_hist("3:0.52;4:12.10") == {3: 0.52, 4: 12.1}
    assert parse_hist("") == {}
    assert parse_hist(float("nan")) == {}


def test_render_page_smoke():
    summary, detail = _report_frames()
    page = render_page(summary, detail, top=10)
    assert "Equity.US.AAA/USD" in page
    assert 'class="bar crit"' in page      # k <= min_pub bars marked
    assert "red bars" in page              # not color-alone
    assert "10 (70%)" in page              # dominant publisher callout
    assert "NO_SCHEDULE" in page           # note rows still in the table
    assert "prefers-color-scheme" in page  # dark mode defined
    assert "<script src" not in page       # self-contained
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `source venv/bin/activate && pytest tests/test_active_pub_distribution.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'lazer_dq.render_active_pub_html'`.

- [ ] **Step 3: Write the implementation**

Create `lazer_dq/render_active_pub_html.py`:

```python
"""Render active_pub_distribution CSVs into a self-contained HTML report.

Reads the summary + per-publisher CSVs written by
lazer_dq.active_pub_distribution (no ClickHouse) and writes one offline HTML
file: a worst-first gallery of per-minute active-count histograms, plus a
sortable table of every summary row.

Run:
    python3 -m lazer_dq.render_active_pub_html \
        --summary output_csv/active_pub_distribution_A_B.csv \
        --publishers output_csv/active_pub_publishers_A_B.csv
"""
from __future__ import annotations

import argparse
import html
import sys
from pathlib import Path

import pandas as pd

PAGE_CSS = """
:root{color-scheme:light;
 --surface:#fcfcfb;--page:#f9f9f7;--ink:#0b0b0b;--ink-2:#52514e;--muted:#898781;
 --grid:#e1e0d9;--border:rgba(11,11,11,.10);--bar:#2a78d6;--bar-crit:#d03b3b}
@media (prefers-color-scheme:dark){:root:not([data-theme=light]){color-scheme:dark;
 --surface:#1a1a19;--page:#0d0d0d;--ink:#fff;--ink-2:#c3c2b7;--muted:#898781;
 --grid:#2c2c2a;--border:rgba(255,255,255,.10);--bar:#3987e5;--bar-crit:#d03b3b}}
:root[data-theme=dark]{color-scheme:dark;
 --surface:#1a1a19;--page:#0d0d0d;--ink:#fff;--ink-2:#c3c2b7;--muted:#898781;
 --grid:#2c2c2a;--border:rgba(255,255,255,.10);--bar:#3987e5;--bar-crit:#d03b3b}
body{font-family:system-ui,-apple-system,"Segoe UI",sans-serif;
 background:var(--page);color:var(--ink);margin:24px}
h1{font-size:20px}h2{font-size:16px;margin-top:28px}.sub{color:var(--ink-2)}
.gallery{display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:16px}
.card{background:var(--surface);border:1px solid var(--border);
 border-radius:8px;padding:12px 14px}
.card h3{margin:0 0 10px;font-size:13px;font-weight:600}
.session{color:var(--muted);font-weight:400}
.chart{display:flex;align-items:flex-end;gap:2px;height:96px;
 border-bottom:1px solid var(--grid)}
.col{flex:1;display:flex;flex-direction:column;justify-content:flex-end;
 height:100%;min-width:6px}
.bar{background:var(--bar);border-radius:2px 2px 0 0}
.bar.crit{background:var(--bar-crit)}
.k{font-size:9px;color:var(--muted);text-align:center;margin-top:2px}
.meta{font-size:11px;color:var(--ink-2);margin:8px 0 0;line-height:1.5}
.tablewrap{overflow-x:auto}
table{border-collapse:collapse;font-size:12px;margin-top:12px;background:var(--surface)}
th,td{border:1px solid var(--grid);padding:3px 8px;text-align:right;
 font-variant-numeric:tabular-nums;white-space:nowrap}
th{cursor:pointer;position:sticky;top:0;background:var(--surface)}
td:nth-child(-n+5),th:nth-child(-n+5){text-align:left}
"""

SORT_JS = """
document.querySelectorAll("th").forEach((th, i) => th.addEventListener("click", () => {
  const tb = th.closest("table").querySelector("tbody");
  const asc = th.dataset.asc !== "1";
  th.closest("tr").querySelectorAll("th").forEach(h => delete h.dataset.asc);
  th.dataset.asc = asc ? "1" : "";
  [...tb.rows].sort((a, b) => {
    const x = a.cells[i].textContent, y = b.cells[i].textContent;
    const nx = parseFloat(x), ny = parseFloat(y);
    const c = (isNaN(nx) || isNaN(ny)) ? x.localeCompare(y) : nx - ny;
    return asc ? c : -c;
  }).forEach(r => tb.appendChild(r));
}));
"""


def parse_hist(s) -> dict[int, float]:
    """'3:0.52;4:12.10' -> {3: 0.52, 4: 12.1}. Blank/NaN -> {}."""
    if not isinstance(s, str) or not s.strip():
        return {}
    out = {}
    for token in s.split(";"):
        k, pct = token.split(":")
        out[int(k)] = float(pct)
    return out


def gallery_rows(summary: pd.DataFrame, top: int) -> pd.DataFrame:
    """Metric rows (blank note) sorted worst-skew first."""
    rows = summary[summary["note"].fillna("") == ""].copy()
    return rows.sort_values(
        ["pct_minutes_le_min", "effective_publishers"], ascending=[False, True]
    ).head(top)


def top_publishers(detail: pd.DataFrame, feed_id, session, n=3) -> list[dict]:
    rows = detail[
        (detail["feed_id"] == feed_id) & (detail["session"] == session)
    ].nsmallest(n, "rank")
    return rows.to_dict("records")


def render_card(row, top_pubs) -> str:
    hist = parse_hist(row["active_hist"])
    min_pub = int(row["effective_min_pub"])
    allowed = int(row["allowed_count"])
    max_pct = max(hist.values(), default=0.0) or 1.0
    bars = []
    for k in range(0, allowed + 1):
        pct = hist.get(k, 0.0)
        height = round(100.0 * pct / max_pct) if pct else 0
        height = max(height, 1) if pct else 0
        crit = " crit" if k <= min_pub else ""
        bars.append(
            f'<div class="col" title="{k} active · {pct:.2f}% of open minutes">'
            f'<div class="bar{crit}" style="height:{height}%"></div>'
            f'<span class="k">{k}</span></div>'
        )
    pubs = ", ".join(
        f"{int(p['publisher_id'])} ({p['update_share_pct']:.0f}%)" for p in top_pubs
    )
    sym = html.escape(str(row["symbol"]))
    session = html.escape(str(row["session"]))
    return (
        f'<div class="card"><h3>{int(row["feed_id"])} · {sym} '
        f'<span class="session">{session}</span></h3>'
        f'<div class="chart">{"".join(bars)}</div>'
        f'<p class="meta">min pub {min_pub} (red bars ≤ min pub) · '
        f'≤min {row["pct_minutes_le_min"]:.1f}% of minutes · '
        f'active {int(row["active_pub_count"])}/{allowed} · '
        f'eff. pubs {row["effective_publishers"]:.2f} · '
        f'top-3 share {row["top3_share_pct"]:.0f}% · '
        f"top pubs: {pubs}</p></div>"
    )


def render_table(summary: pd.DataFrame) -> str:
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in summary.columns)
    body = []
    for _, r in summary.iterrows():
        tds = "".join(
            f"<td>{html.escape('' if pd.isna(v) else str(v))}</td>" for v in r
        )
        body.append(f"<tr>{tds}</tr>")
    return (
        f'<div class="tablewrap"><table><thead><tr>{head}</tr></thead>'
        f'<tbody>{"".join(body)}</tbody></table></div>'
    )


def render_page(summary: pd.DataFrame, detail: pd.DataFrame, top: int) -> str:
    cards = [
        render_card(row, top_publishers(detail, row["feed_id"], row["session"]))
        for _, row in gallery_rows(summary, top).iterrows()
    ]
    return (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Active publisher distribution</title>"
        f"<style>{PAGE_CSS}</style></head><body>"
        "<h1>Active publisher distribution</h1>"
        f'<p class="sub">{len(summary)} feed-session rows · gallery: worst '
        f"{len(cards)} by % of open minutes ≤ min pub · bar height = "
        "share of open minutes at that active-publisher count</p>"
        f'<div class="gallery">{"".join(cards)}</div>'
        "<h2>All feed-sessions (click a header to sort)</h2>"
        f"{render_table(summary)}"
        f"<script>{SORT_JS}</script></body></html>"
    )


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--summary", required=True)
    p.add_argument("--publishers", required=True)
    p.add_argument("--output", help="default: <summary path>.html")
    p.add_argument("--top", type=int, default=50)
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    summary = pd.read_csv(args.summary)
    detail = pd.read_csv(args.publishers)
    out_path = Path(args.output) if args.output else Path(args.summary).with_suffix(
        ".html"
    )
    out_path.write_text(render_page(summary, detail, args.top))
    print(f"Report written to {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `source venv/bin/activate && pytest tests/test_active_pub_distribution.py -v`
Expected: 16 passed.

- [ ] **Step 5: Eyeball the rendered output**

The validator checks color, not layout — render a real page and look at it:

```bash
source venv/bin/activate && python3 - <<'EOF'
import sys
sys.path.insert(0, ".")
from tests.test_active_pub_distribution import _report_frames
from lazer_dq.render_active_pub_html import render_page
from pathlib import Path
s, d = _report_frames()
Path("output_csv/_render_check.html").write_text(render_page(s, d, 10))
EOF
```

Then Read `output_csv/_render_check.html` (or open it) and confirm: bars render at sensible heights, `k` labels sit under bars, the critical bars are the ones at k ≤ 2, no overlapping text; delete the file afterwards. If anything is off, fix the CSS and re-run the smoke test.

- [ ] **Step 6: Commit**

```bash
pre-commit run --files lazer_dq/render_active_pub_html.py tests/test_active_pub_distribution.py
git add lazer_dq/render_active_pub_html.py tests/test_active_pub_distribution.py
git commit -m "feat(lazer_dq): HTML histogram report for active_pub_distribution

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Documentation

**Files:**

- Create: `docs/active_pub_distribution.md`
- Modify: `CLAUDE.md` (scripts table — add one row after the `lazer_dq/incumbent_quality.py` row)

**Interfaces:**

- Consumes: everything above (documents it). Produces: docs only, no code.

- [ ] **Step 1: Write `docs/active_pub_distribution.md`**

````markdown
# active_pub_distribution — active-publisher histogram + concentration

Diagnostic sweep of all STABLE (feed, session) pairs in a new-format Lazer
config. Answers two questions the min_pub audit's CRITICAL/WARN/OK collapses
away:

1. **How often does the feed run close to minPublishers?** Histogram of
   per-minute active publisher counts over session open minutes (a publisher
   is active in a minute iff it has ≥ 1 ACCEPTED update there). Mass near
   `min_pub` = fragile; mass near `allowed_count` = healthy margin.
2. **Is update volume concentrated?** Per-publisher ACCEPTED-update shares:
   `effective_publishers` (inverse HHI — "effectively 3.2 publishers even
   though 10 are allowed"), `top1_share_pct`, `top3_share_pct`.

Methodology matches `lazer_dq.audit_min_pub` (same session masks, same
active-in-minute definition), so results line up with audit classifications.
Design spec: `docs/superpowers/specs/2026-07-16-active-pub-distribution-design.md`.

## Usage

​```bash

# Sweep (default window: last 7 full UTC days)

python3 -m lazer_dq.active_pub_distribution --config lazer_new.json \
 --start-date 2026-07-09 --end-date 2026-07-16 --workers 8

# Interrupted? Re-run with --resume (summary row = completion marker;

# orphan detail rows from a mid-feed crash are pruned automatically)

python3 -m lazer_dq.active_pub_distribution --config lazer_new.json \
 --start-date 2026-07-09 --end-date 2026-07-16 --resume

# HTML report (no ClickHouse needed)

python3 -m lazer_dq.render_active_pub_html \
 --summary output_csv/active_pub_distribution_2026-07-09_2026-07-16.csv \
 --publishers output_csv/active_pub_publishers_2026-07-09_2026-07-16.csv \
 --top 50
​```

## Outputs

### `active_pub_distribution_<start>_<end>.csv` — one row per (feed, session)

| Column                                                         | Meaning                                                                                                                                                                                                                                                |
| -------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `note`                                                         | blank = metrics present; `NO_SCHEDULE` / `ZERO_OPEN_MINUTES` / `SKIPPED_DEPRECATED` = identity + `effective_min_pub` + `allowed_count` only                                                                                                            |
| `allowed_count` / `active_pub_count` / `never_published_count` | allowed-list size vs publishers that actually produced ≥ 1 ACCEPTED update vs dead weight                                                                                                                                                              |
| `unlisted_active_count`                                        | Sanity flag: distinct publishers NOT in the config's allowed list with ACCEPTED updates in the window. Non-zero ⇒ the analyzed config file differs from what production enforced (snapshot drift); such publishers are excluded from all other metrics |
| `pct_minutes_le_min` / `pct_minutes_le_min_plus_1`             | % of open minutes at or below min_pub / min_pub+1 (the left-skew signal; `le_min` matches the audit's CRITICAL condition)                                                                                                                              |
| `p10_active, median_active, p90_active, worst_minute_active`   | Distribution percentiles of the per-minute active count                                                                                                                                                                                                |
| `active_hist`                                                  | Full histogram: `"3:0.52;4:12.10;5:87.38"` = % of open minutes at each active count                                                                                                                                                                    |
| `effective_publishers`                                         | Inverse HHI of update shares; compare to `effective_min_pub`                                                                                                                                                                                           |
| `top1_share_pct` / `top3_share_pct`                            | % of all ACCEPTED updates from the 1 / 3 most active publishers                                                                                                                                                                                        |

### `active_pub_publishers_<start>_<end>.csv` — one row per (feed, session, allowed publisher)

Includes zero-update publishers (the "allowed but never publishes" list):
`accepted_updates, update_share_pct, minutes_active, pct_open_minutes_active,
rank` (1 = most updates; ties by publisher_id; zero-update publishers last).

### HTML report

Self-contained file (works offline, publishable as a claude.ai Artifact):
worst-N gallery of histograms (red bars = counts ≤ min_pub) annotated with
effective publishers, top-3 share, and dominant publisher IDs, plus a
sortable table of every summary row. Light + dark mode.

## Interpretation notes

- A feed can be audit-OK yet fragile here: e.g. always 2 above min_pub but
  with 90% of updates from one publisher (`effective_publishers` ≈ 1) — one
  publisher outage away from CRITICAL.
- `pct_minutes_le_min > 0` ⇔ the audit classified that session CRITICAL over
  the same window (same definition, same masks).
- This tool only describes; it sets no thresholds and edits no configs.
````

(The ​``` fences above are literal — remove the zero-width guards when writing the file.)

- [ ] **Step 2: Add the CLAUDE.md scripts-table row**

In `CLAUDE.md`, directly after the `lazer_dq/incumbent_quality.py` table row, add:

```markdown
| `lazer_dq/active_pub_distribution.py` | Active-publisher histogram vs minPublishers + update concentration (effective publishers, top-N shares) for all STABLE feed-sessions; HTML report via `lazer_dq/render_active_pub_html.py` | `python3 -m lazer_dq.active_pub_distribution --config lazer_new.json --start-date A --end-date B` | [docs/active_pub_distribution.md](docs/active_pub_distribution.md) |
```

- [ ] **Step 3: Run the full test suite**

Run: `source venv/bin/activate && pytest tests/test_active_pub_distribution.py -v && pytest tests/ -q`
Expected: all green (pre-existing failures unrelated to this work, if any, noted explicitly).

- [ ] **Step 4: Commit**

```bash
pre-commit run --files docs/active_pub_distribution.md CLAUDE.md
git add docs/active_pub_distribution.md CLAUDE.md
git commit -m "docs: active_pub_distribution usage doc + scripts-table entry

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## After the plan: production run (not a coding task)

Run against the current production config over the last 7 full UTC days, render the HTML report, publish it as an Artifact, and hand-write the findings doc (`docs/active_pub_findings_<date>.md`) in the style of `docs/min_pub_sweep_*` — top-line stats, worst left-skew offenders, concentration callouts (compare against the pub-71 concentration seen in the 2026-07-15 incumbent sweep). These need ClickHouse access and human judgment, so they stay with Mario + the main session rather than a plan task.
