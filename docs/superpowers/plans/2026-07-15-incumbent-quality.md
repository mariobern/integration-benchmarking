# Incumbent Publisher Quality Sweep Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `lazer_dq/incumbent_quality.py` — a quality sweep scoring every incumbent (and, with `--include-candidates`, every candidate) publisher on every session of every STABLE feed — then run it over `lazer_new.json` and write a summary report.

**Architecture:** New stage importing the qualification pipeline's evaluation machinery (`engine_mode_for`/`engine_gate`/`run_engine` for the Datascope path, `evaluate_peer` vs the `price_feeds` aggregate for everything else) so incumbent scores are directly comparable to candidate-qualification scores. Threaded per-feed like `audit_min_pub`, resumable, three CSV outputs.

**Tech Stack:** Python 3, pandas, ClickHouse via `lib.config` clients, pytest, pre-commit (black/prettier).

## Global Constraints

- Spec: `docs/superpowers/specs/2026-07-15-incumbent-quality-design.md` — binding for columns, verdicts, CLI, error handling.
- Branch: `feat/incumbent-quality`. Work in the main working dir (inputs `lazer_new.json`, `output_csv/` are untracked — a worktree won't have them).
- Use `python3`, never `python`. Run `pre-commit run --files <changed files>` before every commit.
- `qualify_candidates.py` behavior must not change; its tests must stay green after the helper extraction.
- Output columns (exact order):
  - `incumbent_report.csv`: `feed_id, symbol, session, publisher_id, publisher_role, quality_path, engine_mode, benchmark_date, activity_pct, rmse_over_spread, hit_rate, nrmse, n_obs, verdict, reason`
  - `incumbent_quality_summary.csv`: `feed_id, symbol, session, asset_type, quality_path, n_incumbents, n_pass, n_fail, n_no_data, n_no_benchmark, all_pass, n_candidates, n_candidates_pass, audit_classification`
  - `flagged_incumbents.csv`: `feed_id, symbol, session, publisher_id, publisher_role, verdict, reason, detail`
- Verdicts: `PASS` / `FAIL` / `NO_DATA` / `NO_BENCHMARK`. Flagged CSV contains incumbents with verdict != PASS, plus candidates with verdict == FAIL.
- Peer thresholds default to qualification's: nrmse_auto 0.05, nrmse_cond 0.15, hit rate 85.0, min_obs 1000. Engine gate = `engine_gate()` unchanged.
- Resume granularity is per feed (whole feeds are written atomically under the write lock, so feed-level resume skips exactly the already-written (feed_id, session) keys).
- Test suite: `python3 -m pytest lazer_dq/tests/ tests/ -q` (or activate `venv/` first if `pytest` missing).

---

### Task 1: Extract shared mask helpers into `min_pub_common`

**Files:**

- Modify: `lazer_dq/min_pub_common.py` (append helpers)
- Modify: `lazer_dq/qualify_candidates.py:284-295, 417-423` (remove privates, import shared)
- Test: `lazer_dq/tests/test_min_pub_common.py` (append test)

**Interfaces:**

- Consumes: nothing new.
- Produces: `min_pub_common.open_minute_set(mask: pd.Series) -> set` and `min_pub_common.restrict_to_mask(df: pd.DataFrame, mask: pd.Series) -> pd.DataFrame` — Task 3 imports both names from `lazer_dq.min_pub_common`.

- [ ] **Step 1: Check current private-helper usage**

Run: `grep -rn "_restrict_to_mask\|_open_minute_set" lazer_dq/ tests/ --include='*.py'`
Expected: matches only inside `lazer_dq/qualify_candidates.py` (definition + call sites in `activity_pct` and `qualify_feed`). If anything else imports them, update those imports too in Step 4.

- [ ] **Step 2: Write the failing test**

Append to `lazer_dq/tests/test_min_pub_common.py`:

```python
import pandas as pd

from lazer_dq.min_pub_common import open_minute_set, restrict_to_mask


def test_open_minute_set_returns_only_open_minutes():
    idx = pd.date_range("2026-07-06 00:00", periods=4, freq="1min", tz="UTC")
    mask = pd.Series([True, False, True, False], index=idx)
    assert open_minute_set(mask) == {idx[0], idx[2]}


def test_restrict_to_mask_filters_closed_minutes_and_coerces_ts():
    idx = pd.date_range("2026-07-06 00:00", periods=4, freq="1min", tz="UTC")
    mask = pd.Series([True, False, True, False], index=idx)
    df = pd.DataFrame(
        {
            "ts": [
                "2026-07-06 00:00:30",
                "2026-07-06 00:01:30",
                "2026-07-06 00:02:59",
            ],
            "price": [1.0, 2.0, 3.0],
        }
    )
    out = restrict_to_mask(df, mask)
    assert list(out["price"]) == [1.0, 3.0]
    assert str(out["ts"].dtype).startswith("datetime64")


def test_restrict_to_mask_empty_df_passthrough():
    idx = pd.date_range("2026-07-06 00:00", periods=1, freq="1min", tz="UTC")
    mask = pd.Series([True], index=idx)
    df = pd.DataFrame(columns=["ts", "price"])
    assert restrict_to_mask(df, mask).empty
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python3 -m pytest lazer_dq/tests/test_min_pub_common.py -q`
Expected: FAIL with `ImportError: cannot import name 'open_minute_set'`

- [ ] **Step 4: Implement**

Append to `lazer_dq/min_pub_common.py` (add `import pandas as pd` to its imports):

```python
def open_minute_set(mask: pd.Series) -> set:
    """The mask's open minutes as a set (mask: bool Series indexed by minute)."""
    return set(mask.index[mask.to_numpy()])


def restrict_to_mask(df: pd.DataFrame, mask: pd.Series) -> pd.DataFrame:
    """Rows whose minute-floored ts is an open minute; ts coerced to UTC datetime."""
    if df.empty:
        return df
    ts = pd.to_datetime(df["ts"], utc=True)
    minutes = ts.dt.floor("1min")
    return df[minutes.isin(open_minute_set(mask))].assign(ts=ts)
```

In `lazer_dq/qualify_candidates.py`: delete the `_open_minute_set` and `_restrict_to_mask` function definitions; change the import line

```python
from lazer_dq.min_pub_common import FeedSession, iter_stable_sessions
```

to

```python
from lazer_dq.min_pub_common import (
    FeedSession,
    iter_stable_sessions,
    open_minute_set,
    restrict_to_mask,
)
```

and rename the three call sites: `_open_minute_set(mask)` → `open_minute_set(mask)` (in `activity_pct`), `_restrict_to_mask(agg_df, mask)` → `restrict_to_mask(agg_df, mask)` and `_restrict_to_mask(pub_all, mask)` → `restrict_to_mask(pub_all, mask)` (in `qualify_feed`).

- [ ] **Step 5: Run the affected suites**

Run: `python3 -m pytest lazer_dq/tests/test_min_pub_common.py lazer_dq/tests/test_qualify_candidates.py -q`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
pre-commit run --files lazer_dq/min_pub_common.py lazer_dq/qualify_candidates.py lazer_dq/tests/test_min_pub_common.py
git add lazer_dq/min_pub_common.py lazer_dq/qualify_candidates.py lazer_dq/tests/test_min_pub_common.py
git commit -m "refactor(lazer_dq): extract mask helpers to min_pub_common

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

### Task 2: `incumbent_quality` pure logic

**Files:**

- Create: `lazer_dq/incumbent_quality.py`
- Test: `lazer_dq/tests/test_incumbent_quality.py`

**Interfaces:**

- Consumes: `qualify_candidates.engine_gate`, `min_pub_common` (Task 1).
- Produces (Task 3 builds on these exact names):

  - `REPORT_COLUMNS`, `SUMMARY_COLUMNS`, `FLAGGED_COLUMNS` (lists, per Global Constraints)
  - `ensure_new_format(config: dict) -> None` (raises `ValueError` on old format)
  - `discover_candidates(matrix_pubs: set, production_pubs: set, allowed, excluded: set) -> list[int]`
  - `verdict_from_peer(result: dict) -> tuple[str, str]`
  - `verdict_from_engine(srow: dict | None, mode: str, min_obs: int) -> tuple[str, str]`
  - `summarize_session(rows: list[dict]) -> dict` (count fields only, no base keys)
  - `load_audit_classifications(path) -> dict[(int, str), str]`
  - `resume_done_feed_ids(summary_path: Path) -> set[int]`
  - `parse_args(argv=None) -> argparse.Namespace`

- [ ] **Step 1: Write the failing tests**

Create `lazer_dq/tests/test_incumbent_quality.py`:

```python
from pathlib import Path

import pandas as pd
import pytest

from lazer_dq.incumbent_quality import (
    FLAGGED_COLUMNS,
    REPORT_COLUMNS,
    SUMMARY_COLUMNS,
    discover_candidates,
    ensure_new_format,
    load_audit_classifications,
    parse_args,
    resume_done_feed_ids,
    summarize_session,
    verdict_from_engine,
    verdict_from_peer,
)


def test_column_contracts():
    assert REPORT_COLUMNS == [
        "feed_id", "symbol", "session", "publisher_id", "publisher_role",
        "quality_path", "engine_mode", "benchmark_date", "activity_pct",
        "rmse_over_spread", "hit_rate", "nrmse", "n_obs", "verdict", "reason",
    ]
    assert SUMMARY_COLUMNS == [
        "feed_id", "symbol", "session", "asset_type", "quality_path",
        "n_incumbents", "n_pass", "n_fail", "n_no_data", "n_no_benchmark",
        "all_pass", "n_candidates", "n_candidates_pass", "audit_classification",
    ]
    assert FLAGGED_COLUMNS == [
        "feed_id", "symbol", "session", "publisher_id", "publisher_role",
        "verdict", "reason", "detail",
    ]


def test_ensure_new_format_rejects_feed_level_publishers():
    old = {"feeds": [{"feedId": 1, "allowedPublisherIds": [1, 2]}]}
    with pytest.raises(ValueError, match="old-format"):
        ensure_new_format(old)
    new = {"feeds": [{"feedId": 1, "marketSchedules": [{"session": "REGULAR"}]}]}
    ensure_new_format(new)  # no raise


def test_discover_candidates_excludes_allowed_nonproduction_and_excluded():
    matrix_pubs = {1, 2, 3, 4, 5}
    production = {1, 2, 3, 4}
    allowed = frozenset({1})
    excluded = {2}
    assert discover_candidates(matrix_pubs, production, allowed, excluded) == [3, 4]


def test_verdict_from_peer_mapping():
    assert verdict_from_peer(
        {"reason": "pass", "passed": True, "n_observations": 5000}
    ) == ("PASS", "pass")
    assert verdict_from_peer(
        {"reason": "fail_quality", "passed": False, "n_observations": 5000}
    ) == ("FAIL", "fail_quality")
    assert verdict_from_peer(
        {"reason": "insufficient_obs", "passed": False, "n_observations": 0}
    ) == ("NO_DATA", "no_submissions")
    assert verdict_from_peer(
        {"reason": "insufficient_obs", "passed": False, "n_observations": 10}
    ) == ("NO_DATA", "insufficient_obs")
    assert verdict_from_peer(
        {"reason": "zero_range", "passed": False, "n_observations": 5000}
    ) == ("NO_BENCHMARK", "zero_range")


def test_verdict_from_engine_mapping():
    good = {
        "rmse_over_spread": "0.0001", "hit_rate_0.1pct": "100",
        "n_observations": "5000", "nrmse": "0.0001", "pass_fail": "pass",
    }
    bad = {
        "rmse_over_spread": "999", "hit_rate_0.1pct": "0",
        "n_observations": "5000", "nrmse": "9.9", "pass_fail": "fail",
    }
    thin = dict(good, n_observations="3")
    assert verdict_from_engine(None, "us-equities", 1000) == ("NO_DATA", "no_engine_row")
    assert verdict_from_engine(good, "us-equities", 1000) == ("PASS", "pass")
    assert verdict_from_engine(bad, "us-equities", 1000) == ("FAIL", "fail_quality")
    assert verdict_from_engine(thin, "us-equities", 1000) == ("NO_DATA", "insufficient_obs")


def _row(role, verdict):
    return {"publisher_role": role, "verdict": verdict}


def test_summarize_session_counts_roles_separately():
    rows = [
        _row("incumbent", "PASS"),
        _row("incumbent", "FAIL"),
        _row("incumbent", "NO_DATA"),
        _row("incumbent", "NO_BENCHMARK"),
        _row("candidate", "PASS"),
        _row("candidate", "FAIL"),
    ]
    s = summarize_session(rows)
    assert s == {
        "n_incumbents": 4, "n_pass": 1, "n_fail": 1, "n_no_data": 1,
        "n_no_benchmark": 1, "all_pass": False,
        "n_candidates": 2, "n_candidates_pass": 1,
    }
    s_all = summarize_session([_row("incumbent", "PASS")])
    assert s_all["all_pass"] is True
    assert summarize_session([])["all_pass"] is False


def test_load_audit_classifications(tmp_path):
    p = tmp_path / "audit.csv"
    p.write_text(
        "feed_id,symbol,session,classification\n"
        "1,Crypto.A/USD,REGULAR,OK\n"
        "2,Crypto.B/USD,PRE_MARKET,WARN\n"
        "3,DEPRECATED X,,SKIPPED_DEPRECATED\n"
    )
    m = load_audit_classifications(p)
    assert m[(1, "REGULAR")] == "OK"
    assert m[(2, "PRE_MARKET")] == "WARN"
    assert (3, "") not in m  # NaN session rows are skipped


def test_resume_done_feed_ids(tmp_path):
    p = tmp_path / "incumbent_quality_summary.csv"
    assert resume_done_feed_ids(p) == set()
    p.write_text("feed_id,symbol\n1,X\n1,X\n7,Y\n")
    assert resume_done_feed_ids(p) == {1, 7}


def test_parse_args_defaults():
    args = parse_args(
        ["--config", "c.json", "--start-date", "2026-07-08", "--end-date", "2026-07-15"]
    )
    assert args.include_candidates is False
    assert args.workers == 8
    assert args.min_obs == 1000
    assert args.peer_nrmse_auto == 0.05
    assert args.peer_nrmse_cond == 0.15
    assert args.peer_hit_rate == 85.0
    assert args.peer_days == 2
    assert args.cluster == "lazer-prod"
    assert args.output_dir == "output_csv"
    assert args.audit_csv is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest lazer_dq/tests/test_incumbent_quality.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'lazer_dq.incumbent_quality'`

- [ ] **Step 3: Implement the module (pure logic only)**

Create `lazer_dq/incumbent_quality.py`:

```python
# lazer_dq/incumbent_quality.py
"""Quality sweep of incumbent (and optionally candidate) publishers.

For every session of every STABLE feed in a new-format Lazer config, score
each currently-allowed publisher's price quality with the same gates the
min_pub qualification pipeline applies to candidates:

  - Datascope path (engine_mode_for): DQ-engine per-publisher stats gated by
    engine_gate;
  - peer path (everything else): evaluate_peer vs the price_feeds aggregate
    (circularity accepted by design, as in qualify_candidates).

With --include-candidates, non-allowed production-key publishers submitting
in the window are scored too (publisher_role=candidate). Measure-only: no
activity gate, no selection, no config mutation.

Run:
    python3 -m lazer_dq.incumbent_quality --config lazer_new.json \
        --start-date 2026-07-08 --end-date 2026-07-15 \
        --include-candidates \
        --audit-csv output_csv/min_pub_audit_2026-07-06_2026-07-13.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from lazer_dq.market_schedule import open_minutes_mask, parse_market_schedule
from lazer_dq.min_pub_common import iter_stable_sessions, restrict_to_mask
from lazer_dq.peer_benchmark import PeerThresholds, evaluate_peer
from lazer_dq.qualify_candidates import (
    ACTIVITY_QUERY,
    PER_SECOND_PRICES_QUERY,
    activity_pct,
    candidate_dates,
    engine_gate,
    engine_mode_for,
    fetch_aggregate,
    fetch_production_publisher_ids,
    peer_windows,
    run_engine,
)
from lazer_dq.summarize_feeds import load_excluded_publishers, load_stats

REPORT_COLUMNS = [
    "feed_id",
    "symbol",
    "session",
    "publisher_id",
    "publisher_role",
    "quality_path",
    "engine_mode",
    "benchmark_date",
    "activity_pct",
    "rmse_over_spread",
    "hit_rate",
    "nrmse",
    "n_obs",
    "verdict",
    "reason",
]
SUMMARY_COLUMNS = [
    "feed_id",
    "symbol",
    "session",
    "asset_type",
    "quality_path",
    "n_incumbents",
    "n_pass",
    "n_fail",
    "n_no_data",
    "n_no_benchmark",
    "all_pass",
    "n_candidates",
    "n_candidates_pass",
    "audit_classification",
]
FLAGGED_COLUMNS = [
    "feed_id",
    "symbol",
    "session",
    "publisher_id",
    "publisher_role",
    "verdict",
    "reason",
    "detail",
]


def ensure_new_format(config: dict) -> None:
    """Reject old-format configs (feed-level allowedPublisherIds)."""
    for feed in config.get("feeds", []):
        if "allowedPublisherIds" in feed:
            raise ValueError(
                f"old-format config: feed {feed.get('feedId')} has feed-level "
                "allowedPublisherIds; only session-only configs are supported"
            )


def discover_candidates(matrix_pubs, production_pubs, allowed, excluded):
    """Non-allowed production-key publishers submitting in the window."""
    return sorted((set(matrix_pubs) & set(production_pubs)) - set(allowed) - set(excluded))


def verdict_from_peer(result: dict) -> tuple:
    """Map an evaluate_peer result to (verdict, reason)."""
    if result["reason"] == "zero_range":
        return "NO_BENCHMARK", "zero_range"
    if result["reason"] == "insufficient_obs":
        if result["n_observations"] == 0:
            return "NO_DATA", "no_submissions"
        return "NO_DATA", "insufficient_obs"
    if result["passed"]:
        return "PASS", "pass"
    return "FAIL", "fail_quality"


def verdict_from_engine(srow, mode: str, min_obs: int) -> tuple:
    """Map a DQ-engine stats row (or its absence) to (verdict, reason)."""
    if srow is None:
        return "NO_DATA", "no_engine_row"
    try:
        n_obs = int(float(srow["n_observations"]))
    except (KeyError, ValueError):
        return "NO_DATA", "bad_stats_row"
    if n_obs < min_obs:
        return "NO_DATA", "insufficient_obs"
    if engine_gate(srow, mode, min_obs):
        return "PASS", "pass"
    return "FAIL", "fail_quality"


def summarize_session(rows) -> dict:
    """Per-role verdict counts for one feed-session's report rows."""
    inc = [r for r in rows if r["publisher_role"] == "incumbent"]
    cand = [r for r in rows if r["publisher_role"] == "candidate"]

    def count(rs, verdict):
        return sum(1 for r in rs if r["verdict"] == verdict)

    n_pass = count(inc, "PASS")
    return {
        "n_incumbents": len(inc),
        "n_pass": n_pass,
        "n_fail": count(inc, "FAIL"),
        "n_no_data": count(inc, "NO_DATA"),
        "n_no_benchmark": count(inc, "NO_BENCHMARK"),
        "all_pass": len(inc) > 0 and n_pass == len(inc),
        "n_candidates": len(cand),
        "n_candidates_pass": count(cand, "PASS"),
    }


def load_audit_classifications(path) -> dict:
    """(feed_id, session) -> classification from a Stage-1 min_pub audit CSV."""
    df = pd.read_csv(path)
    out = {}
    for r in df.itertuples():
        if r.session != r.session:  # NaN (e.g. SKIPPED_DEPRECATED rows)
            continue
        out[(int(r.feed_id), str(r.session))] = str(r.classification)
    return out


def resume_done_feed_ids(summary_path: Path) -> set:
    if not Path(summary_path).exists():
        return set()
    return set(
        pd.read_csv(summary_path, usecols=["feed_id"])["feed_id"].astype(int)
    )


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True)
    p.add_argument("--start-date", required=True, help="UTC YYYY-MM-DD (inclusive)")
    p.add_argument("--end-date", required=True, help="UTC YYYY-MM-DD (exclusive)")
    p.add_argument("--include-candidates", action="store_true")
    p.add_argument("--audit-csv", help="Stage-1 audit CSV to join classification")
    p.add_argument("--cluster", default="lazer-prod")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--feed-id", type=int, nargs="*", help="restrict to these feeds")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--exclude-publisher", type=int, action="append", default=[])
    p.add_argument("--peer-nrmse-auto", type=float, default=0.05)
    p.add_argument("--peer-nrmse-cond", type=float, default=0.15)
    p.add_argument("--peer-hit-rate", type=float, default=85.0)
    p.add_argument("--min-obs", type=int, default=1000)
    p.add_argument("--peer-days", type=int, default=2)
    p.add_argument("--reports-dir", default="dq_reports")
    p.add_argument("--output-dir", default="output_csv")
    p.add_argument("--publishers-md", default="publishers.md")
    return p.parse_args(argv)
```

(The imports of `restrict_to_mask`, `evaluate_peer`, query constants, etc. are used by Task 3's functions in this same module — leave them in place; `# noqa` is not needed because Task 3 lands before this file is ever linted for unused imports in CI. If pre-commit's hooks flag nothing, proceed.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest lazer_dq/tests/test_incumbent_quality.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
pre-commit run --files lazer_dq/incumbent_quality.py lazer_dq/tests/test_incumbent_quality.py
git add lazer_dq/incumbent_quality.py lazer_dq/tests/test_incumbent_quality.py
git commit -m "feat(lazer_dq): incumbent_quality pure logic — columns, verdicts, rollup, CLI

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

### Task 3: `evaluate_feed` orchestration + `main`

**Files:**

- Modify: `lazer_dq/incumbent_quality.py` (append)
- Test: `lazer_dq/tests/test_incumbent_quality.py` (append)

**Interfaces:**

- Consumes: everything Task 2 produced; `run_engine`, `load_stats`, `fetch_aggregate`, `peer_windows`, `activity_pct`, `ACTIVITY_QUERY`, `PER_SECOND_PRICES_QUERY`, `restrict_to_mask`, `open_minutes_mask`, `parse_market_schedule`, `FeedSession`.
- Produces: `evaluate_feed(client, fs_list, args, excluded, production_pubs) -> (report_rows, summary_rows, flagged_rows)` and `main(argv=None) -> int`. Tasks 5–6 run `python3 -m lazer_dq.incumbent_quality`.

- [ ] **Step 1: Write the failing tests**

Append to `lazer_dq/tests/test_incumbent_quality.py`:

```python
import numpy as np

import lazer_dq.incumbent_quality as iq
from lazer_dq.min_pub_common import FeedSession


ALWAYS_OPEN = "UTC;O,O,O,O,O,O,O;"


def _args(extra=()):
    args = iq.parse_args(
        [
            "--config", "unused.json",
            "--start-date", "2026-07-06",
            "--end-date", "2026-07-07",
            "--min-obs", "50",
            *extra,
        ]
    )
    from datetime import datetime, timezone

    args.start_utc = datetime(2026, 7, 6, tzinfo=timezone.utc)
    args.end_utc = datetime(2026, 7, 7, tzinfo=timezone.utc)
    return args


def _minutes(n):
    return pd.date_range("2026-07-06 00:00", periods=n, freq="1min", tz="UTC")


def _seconds(n):
    return pd.date_range("2026-07-06 00:00:00", periods=n, freq="1s", tz="UTC")


class FakeClient:
    """Dispatches query_df by query shape (activity / aggregate / per-second)."""

    def __init__(self, activity, aggregate, per_second):
        self.activity = activity
        self.aggregate = aggregate
        self.per_second = per_second

    def query_df(self, query, parameters=None):
        if "price_feeds" in query:
            return self.aggregate.copy()
        if "toStartOfMinute" in query:
            return self.activity.copy()
        return self.per_second.copy()


def _peer_fixture():
    """Crypto feed: incumbents 10 (good), 11 (bad), 12 (silent); candidate 30 (good)."""
    n = 200
    secs = _seconds(n)
    agg_prices = 100.0 + np.arange(n) % 10  # range 9 > 0
    aggregate = pd.DataFrame({"ts": secs, "price": agg_prices})
    frames = []
    for pid, prices in (
        (10, agg_prices),           # identical -> PASS
        (11, agg_prices + 50.0),    # nrmse ~5.5 -> FAIL
        (30, agg_prices),           # candidate, identical -> PASS
    ):
        frames.append(
            pd.DataFrame({"ts": secs, "publisher_id": pid, "price": prices})
        )
    per_second = pd.concat(frames, ignore_index=True)
    mins = _minutes(60)
    activity = pd.DataFrame(
        {
            "minute": list(mins) * 3,
            "publisher_id": [10] * 60 + [11] * 60 + [30] * 60,
            "n_updates": 1,
        }
    )
    fs = FeedSession(
        feed_id=99,
        symbol="Crypto.TEST/USD",
        asset_type="crypto",
        session="REGULAR",
        allowed=frozenset({10, 11, 12}),
        effective_min_pub=2,
        schedule_str=ALWAYS_OPEN,
    )
    return FakeClient(activity, aggregate, per_second), fs


def test_evaluate_feed_peer_path_verdicts():
    client, fs = _peer_fixture()
    args = _args(["--include-candidates"])
    report, summary, flagged = iq.evaluate_feed(
        client, [fs], args, excluded={0}, production_pubs={10, 11, 12, 30}
    )
    by_pid = {(r["publisher_id"], r["publisher_role"]): r for r in report}
    assert by_pid[(10, "incumbent")]["verdict"] == "PASS"
    assert by_pid[(11, "incumbent")]["verdict"] == "FAIL"
    assert by_pid[(12, "incumbent")]["verdict"] == "NO_DATA"
    assert by_pid[(30, "candidate")]["verdict"] == "PASS"
    assert all(r["quality_path"] == "peer" for r in report)
    (s,) = summary
    assert s["n_incumbents"] == 3 and s["n_pass"] == 1 and s["n_fail"] == 1
    assert s["n_no_data"] == 1 and s["all_pass"] is False
    assert s["n_candidates"] == 1 and s["n_candidates_pass"] == 1
    # flagged: failing incumbents (FAIL + NO_DATA) but not the passing candidate
    flagged_keys = {(r["publisher_id"], r["verdict"]) for r in flagged}
    assert flagged_keys == {(11, "FAIL"), (12, "NO_DATA")}


def test_evaluate_feed_peer_path_without_candidates_flag():
    client, fs = _peer_fixture()
    args = _args()
    report, summary, _ = iq.evaluate_feed(
        client, [fs], args, excluded={0}, production_pubs={10, 11, 12, 30}
    )
    assert {r["publisher_role"] for r in report} == {"incumbent"}
    assert summary[0]["n_candidates"] == 0


def test_evaluate_feed_zero_range_aggregate_is_no_benchmark():
    client, fs = _peer_fixture()
    client.aggregate = pd.DataFrame(
        {"ts": _seconds(200), "price": [100.0] * 200}  # flat -> zero_range
    )
    args = _args()
    report, summary, _ = iq.evaluate_feed(
        client, [fs], args, excluded={0}, production_pubs={10, 11, 12}
    )
    active = [r for r in report if r["publisher_id"] in (10, 11)]
    assert all(r["verdict"] == "NO_BENCHMARK" for r in active)
    assert all(r["reason"] == "zero_range" for r in active)


def test_evaluate_feed_no_schedule_soft_skip():
    client, fs0 = _peer_fixture()
    fs = FeedSession(
        feed_id=fs0.feed_id,
        symbol=fs0.symbol,
        asset_type=fs0.asset_type,
        session=fs0.session,
        allowed=fs0.allowed,
        effective_min_pub=fs0.effective_min_pub,
        schedule_str=None,
    )
    args = _args()
    report, summary, flagged = iq.evaluate_feed(
        client, [fs], args, excluded={0}, production_pubs=set()
    )
    assert report == []
    assert summary[0]["quality_path"] == "none"
    assert summary[0]["all_pass"] is False
    assert flagged[0]["reason"] == "no_schedule"


def test_evaluate_feed_engine_path(monkeypatch):
    n_mins = 60
    activity = pd.DataFrame(
        {
            "minute": list(_minutes(n_mins)) * 2,
            "publisher_id": [20] * n_mins + [21] * n_mins,
            "n_updates": 1,
        }
    )
    client = FakeClient(activity, pd.DataFrame(), pd.DataFrame())
    fs = FeedSession(
        feed_id=42,
        symbol="Equity.US.TEST/USD",
        asset_type="equity",
        session="REGULAR",
        allowed=frozenset({20, 21, 22}),
        effective_min_pub=2,
        schedule_str=ALWAYS_OPEN,
    )
    monkeypatch.setattr(iq, "run_engine", lambda *a, **k: "ok")
    stats = [
        {"publisher_id": "20", "rmse_over_spread": "0.0001",
         "hit_rate_0.1pct": "100", "n_observations": "5000",
         "nrmse": "0.0001", "pass_fail": "pass"},
        {"publisher_id": "21", "rmse_over_spread": "999",
         "hit_rate_0.1pct": "0", "n_observations": "5000",
         "nrmse": "9.9", "pass_fail": "fail"},
    ]
    monkeypatch.setattr(iq, "load_stats", lambda *a, **k: stats)
    args = _args()
    report, summary, flagged = iq.evaluate_feed(
        client, [fs], args, excluded={0}, production_pubs={20, 21}
    )
    by_pid = {r["publisher_id"]: r for r in report}
    assert by_pid[20]["verdict"] == "PASS"
    assert by_pid[21]["verdict"] == "FAIL"
    assert by_pid[22]["verdict"] == "NO_DATA"  # incumbent absent from stats
    assert by_pid[20]["quality_path"] == "engine"
    assert by_pid[20]["engine_mode"] == "us-equities"
    assert by_pid[20]["benchmark_date"] != ""
    (s,) = summary
    assert (s["n_pass"], s["n_fail"], s["n_no_data"]) == (1, 1, 1)


def test_evaluate_feed_engine_no_data_is_no_benchmark(monkeypatch):
    activity = pd.DataFrame(columns=["minute", "publisher_id", "n_updates"])
    client = FakeClient(activity, pd.DataFrame(), pd.DataFrame())
    fs = FeedSession(
        feed_id=42,
        symbol="Equity.US.TEST/USD",
        asset_type="equity",
        session="REGULAR",
        allowed=frozenset({20}),
        effective_min_pub=1,
        schedule_str=ALWAYS_OPEN,
    )
    monkeypatch.setattr(iq, "run_engine", lambda *a, **k: "skipped")
    args = _args()
    report, summary, _ = iq.evaluate_feed(
        client, [fs], args, excluded={0}, production_pubs={20}
    )
    assert report[0]["verdict"] == "NO_BENCHMARK"
    assert report[0]["reason"] == "no_engine_data"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest lazer_dq/tests/test_incumbent_quality.py -q`
Expected: new tests FAIL with `AttributeError: ... has no attribute 'evaluate_feed'`; Task 2's tests still PASS.

- [ ] **Step 3: Implement**

Append to `lazer_dq/incumbent_quality.py`:

```python
def _score_engine(rows, fs, mode, args):
    """Datascope path: one engine run per feed/date serves every publisher."""
    stats, used_date = None, None
    for date in candidate_dates(args.start_utc, args.end_utc):
        if run_engine(fs.feed_id, date, mode, args.cluster, args.reports_dir) == "ok":
            stats = load_stats(args.reports_dir, args.cluster, mode, fs.feed_id, date)
            if stats:
                used_date = date
                break
    if not stats:
        for row in rows:
            row.update({"verdict": "NO_BENCHMARK", "reason": "no_engine_data"})
        return
    stats_by_pid = {}
    for r in stats:
        try:
            stats_by_pid[int(float(r["publisher_id"]))] = r
        except (KeyError, ValueError):
            continue
    for row in rows:
        srow = stats_by_pid.get(row["publisher_id"])
        verdict, reason = verdict_from_engine(srow, mode, args.min_obs)
        row["benchmark_date"] = used_date
        if srow is not None:
            row.update(
                {
                    "rmse_over_spread": srow.get("rmse_over_spread", ""),
                    "hit_rate": srow.get("hit_rate_0.1pct", ""),
                    "nrmse": srow.get("nrmse", ""),
                    "n_obs": srow.get("n_observations", ""),
                }
            )
        row.update({"verdict": verdict, "reason": reason})


def _score_peer(client, rows, fs, mask, thresholds, args):
    """Peer path: each publisher vs the price_feeds aggregate."""
    window = peer_windows(mask, args.peer_days)
    if window is None:
        for row in rows:
            row.update({"verdict": "NO_BENCHMARK", "reason": "no_open_minutes"})
        return
    pstart, pend = window
    agg_df = restrict_to_mask(fetch_aggregate(client, fs.feed_id, pstart, pend), mask)
    if agg_df.empty:
        for row in rows:
            row.update({"verdict": "NO_BENCHMARK", "reason": "no_aggregate_data"})
        return
    pids = [row["publisher_id"] for row in rows]
    if pids:
        pub_all = client.query_df(
            PER_SECOND_PRICES_QUERY,
            parameters={
                "feed_id": fs.feed_id,
                "start": pstart,
                "end": pend,
                "publisher_ids": pids,
            },
        )
        pub_all = restrict_to_mask(pub_all, mask)
    else:
        pub_all = pd.DataFrame(columns=["ts", "publisher_id", "price"])
    for row in rows:
        if len(pub_all):
            pub_df = pub_all[pub_all["publisher_id"] == row["publisher_id"]][
                ["ts", "price"]
            ]
        else:
            pub_df = pd.DataFrame(columns=["ts", "price"])
        result = evaluate_peer(pub_df, agg_df[["ts", "price"]], thresholds)
        verdict, reason = verdict_from_peer(result)
        row.update(
            {
                "benchmark_date": f"{pstart}..{pend}",
                "nrmse": round(result["nrmse"], 6)
                if result["nrmse"] == result["nrmse"]
                else "",
                "hit_rate": round(result["hit_rate_pct"], 2)
                if result["hit_rate_pct"] == result["hit_rate_pct"]
                else "",
                "n_obs": result["n_observations"],
                "verdict": verdict,
                "reason": reason,
            }
        )


def _skip_session(base, fs, reason, detail):
    summary = {
        **base,
        "quality_path": "none",
        "n_incumbents": len(fs.allowed),
        "n_pass": 0,
        "n_fail": 0,
        "n_no_data": 0,
        "n_no_benchmark": 0,
        "all_pass": False,
        "n_candidates": 0,
        "n_candidates_pass": 0,
    }
    flagged = {
        **base,
        "publisher_id": "",
        "publisher_role": "",
        "verdict": "",
        "reason": reason,
        "detail": detail,
    }
    return summary, flagged


def evaluate_feed(client, fs_list, args, excluded, production_pubs):
    """Sweep all sessions of one feed. Returns (report, summary, flagged) row lists."""
    feed_id = fs_list[0].feed_id
    start_s = args.start_utc.strftime("%Y-%m-%d %H:%M:%S")
    end_s = args.end_utc.strftime("%Y-%m-%d %H:%M:%S")
    matrix = client.query_df(
        ACTIVITY_QUERY,
        parameters={"feed_id": feed_id, "start": start_s, "end": end_s},
    )
    if len(matrix):
        matrix["minute"] = pd.to_datetime(matrix["minute"], utc=True)
    else:
        matrix = pd.DataFrame(columns=["minute", "publisher_id", "n_updates"])
    matrix_pubs = set(matrix["publisher_id"].astype(int)) if len(matrix) else set()

    thresholds = PeerThresholds(
        nrmse_auto=args.peer_nrmse_auto,
        nrmse_cond=args.peer_nrmse_cond,
        min_hit_rate_pct=args.peer_hit_rate,
        min_obs=args.min_obs,
    )
    report_rows, summary_rows, flagged_rows = [], [], []

    for fs in fs_list:
        base = {
            "feed_id": fs.feed_id,
            "symbol": fs.symbol,
            "session": fs.session,
            "asset_type": fs.asset_type,
        }
        if fs.schedule_str is None:
            s, f = _skip_session(base, fs, "no_schedule", "market schedule unresolvable")
            summary_rows.append(s)
            flagged_rows.append(f)
            continue
        try:
            schedule = parse_market_schedule(fs.schedule_str)
        except ValueError:
            s, f = _skip_session(base, fs, "no_schedule", "market schedule unparsable")
            summary_rows.append(s)
            flagged_rows.append(f)
            continue
        mask = open_minutes_mask(schedule, args.start_utc, args.end_utc)

        pubs = [("incumbent", pid) for pid in sorted(fs.allowed)]
        if args.include_candidates:
            pubs += [
                ("candidate", pid)
                for pid in discover_candidates(
                    matrix_pubs, production_pubs, fs.allowed, excluded
                )
            ]
        mode = engine_mode_for(fs)
        quality_path = "engine" if mode else "peer"
        rows = [
            {
                **base,
                "publisher_id": pid,
                "publisher_role": role,
                "quality_path": quality_path,
                "engine_mode": mode or "",
                "benchmark_date": "",
                "activity_pct": round(activity_pct(matrix, mask, pid), 4),
                "rmse_over_spread": "",
                "hit_rate": "",
                "nrmse": "",
                "n_obs": "",
            }
            for role, pid in pubs
        ]
        if mode:
            _score_engine(rows, fs, mode, args)
        else:
            _score_peer(client, rows, fs, mask, thresholds, args)

        report_rows.extend(rows)
        summary_rows.append(
            {**base, "quality_path": quality_path, **summarize_session(rows)}
        )
        for row in rows:
            failing_incumbent = (
                row["publisher_role"] == "incumbent" and row["verdict"] != "PASS"
            )
            failing_candidate = (
                row["publisher_role"] == "candidate" and row["verdict"] == "FAIL"
            )
            if failing_incumbent or failing_candidate:
                flagged_rows.append(
                    {
                        **{
                            k: row[k]
                            for k in (
                                "feed_id",
                                "symbol",
                                "session",
                                "publisher_id",
                                "publisher_role",
                                "verdict",
                                "reason",
                            )
                        },
                        "detail": (
                            f"activity={row['activity_pct']}, nrmse={row['nrmse']}, "
                            f"hit={row['hit_rate']}, n_obs={row['n_obs']}"
                        ),
                    }
                )
    return report_rows, summary_rows, flagged_rows


def main(argv=None) -> int:
    args = parse_args(argv)
    args.start_utc = datetime.strptime(args.start_date, "%Y-%m-%d").replace(
        tzinfo=timezone.utc
    )
    args.end_utc = datetime.strptime(args.end_date, "%Y-%m-%d").replace(
        tzinfo=timezone.utc
    )

    config = json.loads(Path(args.config).read_text())
    ensure_new_format(config)

    audit_cls = load_audit_classifications(args.audit_csv) if args.audit_csv else {}
    excluded = load_excluded_publishers(args.publishers_md) | set(
        args.exclude_publisher
    )

    by_feed = {}
    for fs in iter_stable_sessions(config):
        if args.feed_id and fs.feed_id not in args.feed_id:
            continue
        by_feed.setdefault(fs.feed_id, []).append(fs)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "incumbent_report.csv"
    summary_path = out_dir / "incumbent_quality_summary.csv"
    flagged_path = out_dir / "flagged_incumbents.csv"

    done = resume_done_feed_ids(summary_path) if args.resume else set()
    if done:
        print(f"Resume: skipping {len(done)} already-swept feeds")
    todo = {fid: fss for fid, fss in by_feed.items() if fid not in done}
    print(
        f"Sweeping {len(todo)} feeds "
        f"({args.start_utc:%Y-%m-%d} .. {args.end_utc:%Y-%m-%d}, "
        f"candidates={'on' if args.include_candidates else 'off'})"
    )

    from lib.config import ThreadLocalClients, load_config

    new_file = not (args.resume and summary_path.exists())
    file_mode = "w" if new_file else "a"
    report_f = open(report_path, file_mode, newline="")
    summary_f = open(summary_path, file_mode, newline="")
    flagged_f = open(flagged_path, file_mode, newline="")
    report_w = csv.DictWriter(report_f, fieldnames=REPORT_COLUMNS, extrasaction="ignore")
    summary_w = csv.DictWriter(
        summary_f, fieldnames=SUMMARY_COLUMNS, extrasaction="ignore"
    )
    flagged_w = csv.DictWriter(
        flagged_f, fieldnames=FLAGGED_COLUMNS, extrasaction="ignore"
    )
    if new_file:
        for w in (report_w, summary_w, flagged_w):
            w.writeheader()

    write_lock = threading.Lock()
    failures = 0
    with ThreadLocalClients(load_config(), lazer_only=True) as pool:
        production_pubs = (
            fetch_production_publisher_ids(pool.get_lazer_client())
            if args.include_candidates
            else set()
        )
        if args.include_candidates:
            print(f"{len(production_pubs)} production-key publishers")

        def run_one(fss):
            client = pool.get_lazer_client()
            return evaluate_feed(client, fss, args, excluded, production_pubs)

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(run_one, fss): fid for fid, fss in todo.items()
            }
            for i, future in enumerate(as_completed(futures), 1):
                fid = futures[future]
                try:
                    report_rows, summary_rows, flagged_rows = future.result()
                except Exception as e:  # soft-fail per feed (bulk-runner pattern)
                    failures += 1
                    print(f"  [{i}/{len(todo)}] feed {fid} FAILED: {e}")
                    continue
                for row in summary_rows:
                    row["audit_classification"] = audit_cls.get(
                        (row["feed_id"], row["session"]), ""
                    )
                with write_lock:
                    report_w.writerows(report_rows)
                    summary_w.writerows(summary_rows)
                    flagged_w.writerows(flagged_rows)
                    for f in (report_f, summary_f, flagged_f):
                        f.flush()
                n_fail = sum(r["n_fail"] for r in summary_rows)
                print(
                    f"  [{i}/{len(todo)}] feed {fid}: "
                    f"{len(report_rows)} publishers, {n_fail} failing incumbents"
                )
    for f in (report_f, summary_f, flagged_f):
        f.close()
    print(
        f"Done ({failures} feed failures) -> "
        f"{report_path}, {summary_path}, {flagged_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run the full new test file**

Run: `python3 -m pytest lazer_dq/tests/test_incumbent_quality.py -q`
Expected: all PASS.

- [ ] **Step 5: Run the whole suite (regression check)**

Run: `python3 -m pytest lazer_dq/tests/ tests/ -q`
Expected: all PASS (~200 tests), no new failures vs main.

- [ ] **Step 6: Commit**

```bash
pre-commit run --files lazer_dq/incumbent_quality.py lazer_dq/tests/test_incumbent_quality.py
git add lazer_dq/incumbent_quality.py lazer_dq/tests/test_incumbent_quality.py
git commit -m "feat(lazer_dq): incumbent_quality sweep — engine/peer scoring, workers, resume

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

### Task 4: Documentation

**Files:**

- Create: `docs/incumbent_quality.md`
- Modify: `CLAUDE.md` (scripts table — add one row after the `lazer_dq/apply_min_pub_remediation.py` row)

**Interfaces:**

- Consumes: the CLI and outputs exactly as shipped by Task 3.
- Produces: docs; no code.

- [ ] **Step 1: Write `docs/incumbent_quality.md`**

```markdown
# Incumbent Publisher Quality Sweep

`lazer_dq/incumbent_quality.py` scores the price quality of every
**incumbent** (currently-allowed) publisher on every session of every STABLE
feed in a new-format Lazer config — the population the min_pub pipeline
never benchmarks. With `--include-candidates` it also scores non-allowed
production-key publishers submitting in the window, using identical
thresholds, so both roles are directly comparable.

Measure-only: no activity gate, no selection, no config mutation. Candidate
selection remains `lazer_dq/qualify_candidates.py`'s job.

## Usage

    python3 -m lazer_dq.incumbent_quality \
        --config lazer_new.json \
        --start-date 2026-07-08 --end-date 2026-07-15 \
        --include-candidates \
        --audit-csv output_csv/min_pub_audit_2026-07-06_2026-07-13.csv \
        --workers 8 --resume

Dates are UTC, end exclusive. `--resume` appends and skips feeds already in
the summary CSV. `--feed-id 12 3050` restricts the sweep. Full sweeps are
multi-hour; run with `--resume` so restarts are cheap.

## Quality paths

| Path     | Feeds                                                       | Method                                                                                                |
| -------- | ----------------------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| `engine` | fx, metals, commodity, rates, US/HK/JP/KR/IN equities       | DQ engine (`evaluate_feed_standalone`) per-publisher stats, gated by `qualify_candidates.engine_gate` |
| `peer`   | everything else (crypto, RR, NAV, funding rates, custom, …) | `peer_benchmark.evaluate_peer` vs the feed's own `price_feeds` aggregate                              |

## Verdicts

| Verdict        | Meaning                                                                                                                   |
| -------------- | ------------------------------------------------------------------------------------------------------------------------- |
| `PASS`         | Met the quality gate for the feed's path                                                                                  |
| `FAIL`         | Enough data, failed the gate                                                                                              |
| `NO_DATA`      | No (or too few) observations for this publisher in the window (`reason`: no_submissions, insufficient_obs, no_engine_row) |
| `NO_BENCHMARK` | The reference itself was unavailable (`reason`: no_engine_data, no_aggregate_data, zero_range, no_open_minutes)           |

## Outputs (in `--output-dir`, default `output_csv/`)

- `incumbent_report.csv` — one row per publisher × feed-session (metrics + verdict).
- `incumbent_quality_summary.csv` — one row per feed-session (role-split verdict counts, `all_pass`, and `audit_classification` when `--audit-csv` is given).
- `flagged_incumbents.csv` — incumbents with verdict != PASS, plus failing candidates when `--include-candidates`.

## Caveats

- **Peer-path circularity**: incumbents are compared against an aggregate
  they themselves produce. Accepted by design (same trade-off as candidate
  qualification); a dominant bad incumbent partially self-validates.
- **Flat-reference feeds** (zero price variance, e.g. NAV) can never pass
  the peer gate — they come back `NO_BENCHMARK`/`zero_range`.
- **Non-production incumbents**: the per-second price query filters to
  production keys, so an incumbent publishing only with a non-production key
  scores `NO_DATA`.
- **Engine benchmark date** is the most recent weekday with engine data in
  the window (up to 3 tried), not the whole window.
```

- [ ] **Step 2: Add the CLAUDE.md scripts-table row**

Insert into the Scripts table in `CLAUDE.md`, directly after the `lazer_dq/apply_min_pub_remediation.py` row:

```markdown
| `lazer_dq/incumbent_quality.py` | Quality sweep of incumbent (and optionally candidate) publishers on all STABLE feed-sessions (engine/peer paths, qualification thresholds) | `python3 -m lazer_dq.incumbent_quality --config lazer_new.json --start-date A --end-date B` | [docs/incumbent_quality.md](docs/incumbent_quality.md) |
```

- [ ] **Step 3: Verify docs render and tables are consistent**

Run: `grep -c "incumbent_quality" CLAUDE.md docs/incumbent_quality.md`
Expected: at least 1 match in CLAUDE.md, several in the doc.

- [ ] **Step 4: Commit**

```bash
pre-commit run --files docs/incumbent_quality.md CLAUDE.md
git add docs/incumbent_quality.md CLAUDE.md
git commit -m "docs: incumbent_quality usage doc + scripts-table entry

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

### Task 5: Live smoke test (3 feeds)

**Files:**

- No repo changes expected (fixes only if the smoke exposes bugs).
- Output: scratchpad dir (NOT `output_csv/`).

**Interfaces:**

- Consumes: the shipped CLI; ClickHouse credentials in `config.yaml`.
- Produces: verified real-data behavior before the full sweep.

- [ ] **Step 1: Run the smoke sweep**

Run (substitute `$SCRATCH` with the session scratchpad path):

```bash
python3 -m lazer_dq.incumbent_quality \
    --config lazer_new.json \
    --start-date 2026-07-08 --end-date 2026-07-15 \
    --include-candidates \
    --audit-csv output_csv/min_pub_audit_2026-07-06_2026-07-13.csv \
    --feed-id 3050 12 1830 \
    --output-dir $SCRATCH/smoke_out
```

Expected: exits 0; progress lines for 3 feeds; three CSVs in `$SCRATCH/smoke_out`.

- [ ] **Step 2: Verify path routing and verdict shapes**

Check `$SCRATCH/smoke_out/incumbent_report.csv`:

- feed 3050 (`Equity.US.*`): `quality_path=engine`, `engine_mode` per session (`us-equities`, `us-equities-pre`, …), non-empty `benchmark_date` where the engine ran.
- feed 12 (`Crypto.TON/USD`): `quality_path=peer`, `benchmark_date` is a `start..end` range, nrmse/hit populated for active incumbents.
- feed 1830 (`Crypto.NAV.USCC/USD`, flat NAV): peer path with `NO_BENCHMARK`/`zero_range` (or `NO_DATA` if publishers were silent) — must NOT be `FAIL`.
- Summary rows carry `audit_classification` values matching the min_pub audit CSV for those feeds.
- Candidate rows (publisher_role=candidate) appear where non-allowed publishers submitted (feed 12 had 7-8 candidates in the qualification run).

- [ ] **Step 3: Fix anything the smoke exposed**

If behavior deviates, fix the code, re-run the affected pytest tests, re-run the smoke, and commit the fix:

```bash
pre-commit run --files <changed files>
git add <changed files>
git commit -m "fix(lazer_dq): incumbent_quality smoke fixes — <what>

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

### Task 6: Production run

**Files:**

- Output: `output_csv/incumbent_report.csv`, `output_csv/incumbent_quality_summary.csv`, `output_csv/flagged_incumbents.csv` (untracked, not committed).

- [ ] **Step 1: Launch the full sweep (multi-hour, run detached with a log)**

```bash
nohup python3 -m lazer_dq.incumbent_quality \
    --config lazer_new.json \
    --start-date 2026-07-08 --end-date 2026-07-15 \
    --include-candidates \
    --audit-csv output_csv/min_pub_audit_2026-07-06_2026-07-13.csv \
    --workers 8 --resume \
    > incumbent_quality_run.log 2>&1 &
```

- [ ] **Step 2: Monitor and resume on interruption**

Check progress: `tail -5 incumbent_quality_run.log; wc -l output_csv/incumbent_quality_summary.csv`. The sweep covers ~1,645 feeds / ~2,505 feed-sessions. If the process dies, rerun the same command — `--resume` skips completed feeds.

- [ ] **Step 3: Sanity-check the finished outputs**

```bash
python3 - <<'EOF'
import pandas as pd
s = pd.read_csv("output_csv/incumbent_quality_summary.csv")
r = pd.read_csv("output_csv/incumbent_report.csv")
print("feed-sessions:", len(s), "unique feeds:", s.feed_id.nunique())
print("publisher rows:", len(r), "by verdict:", r.verdict.value_counts().to_dict())
print("by role:", r.publisher_role.value_counts().to_dict())
print("audit joined:", (s.audit_classification != "").sum(), "rows")
EOF
```

Expected: feed-sessions ≈ 2,505 (minus deprecated/no-schedule variance); unique feeds ≈ 1,645; verdict counts plausible (no verdict column empty). Record the numbers in the progress ledger.

### Task 7: Summary report

**Files:**

- Create: `docs/incumbent_quality_report_2026-07-15.md` (adjust date to actual run date)

**Interfaces:**

- Consumes: the three output CSVs + `output_csv/min_pub_audit_2026-07-06_2026-07-13.csv`.
- Produces: committed report.

- [ ] **Step 1: Compute the report tables**

Write a throwaway script in the scratchpad (pattern: compute → print markdown tables → paste), producing:

1. Verdict counts overall and by `publisher_role`.
2. Pass rate by `asset_type` × `quality_path` (incumbents only).
3. **OK feeds with failing incumbents**: summary rows where `audit_classification == "OK"` and `n_fail > 0`, sorted by `n_fail` desc — full table.
4. Candidate bench: feeds with `n_candidates_pass > 0`, total passing candidates.
5. NO_DATA / NO_BENCHMARK inventory by reason (from the report CSV).

- [ ] **Step 2: Write the report**

Structure (fill each table from Step 1; every number in prose must come from the computed tables):

```markdown
# Incumbent Quality Report — <run date>

Window <start>..<end>, config `lazer_new.json`, sweep with candidates.

## 1. Headline

[counts: publishers evaluated, PASS/FAIL/NO_DATA/NO_BENCHMARK, OK-feeds-with-failing-incumbents count]

## 2. Method (one paragraph + caveats: peer circularity, zero_range, non-production incumbents)

## 3. Pass rates by asset type and path

[table 2]

## 4. OK feeds with failing incumbents

[table 3 — the headline deliverable]

## 5. Candidate bench

[table 4]

## 6. Unmeasurable inventory

[table 5]
```

- [ ] **Step 3: Verify and commit**

Cross-check three prose numbers against the CSVs directly (pandas one-liners), then:

```bash
pre-commit run --files docs/incumbent_quality_report_<date>.md
git add docs/incumbent_quality_report_<date>.md
git commit -m "docs: incumbent quality report <date> — first production sweep

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
