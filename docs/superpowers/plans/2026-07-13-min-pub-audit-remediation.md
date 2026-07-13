# min_pub Audit & Remediation Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a three-stage pipeline that audits STABLE feeds in `lazer_to_modify.json` for active-publisher counts at/near `minPublishers`, qualifies new publishers (Datascope benchmark or peer-vs-aggregate), and applies them to the config via `edit_config.py`.

**Architecture:** Three CLI scripts under `lazer_dq/` (`audit_min_pub.py`, `qualify_candidates.py`, `apply_min_pub_remediation.py`) connected by CSV artifacts in `output_csv/`, plus two shared modules (`market_schedule.py` for parsing the config's `marketSchedule` strings, `peer_benchmark.py` for aggregate-reference quality metrics) and one config-introspection helper (`min_pub_common.py`). Spec: `docs/superpowers/specs/2026-07-13-min-pub-audit-remediation-design.md`.

**Tech Stack:** Python 3, pandas/numpy, clickhouse_connect (via `lib/config.py`), pytest, PyYAML. No new dependencies.

## Global Constraints

- Use `python3`, never `python` (not on PATH on this system).
- Run `pre-commit run --files <changed files>` before every commit (black, prettier, whitespace hooks).
- ClickHouse parameterized queries use `{param_name:String}` syntax with `parameters=dict`.
- Publisher 0 (the aggregate) is always excluded from candidate sets; `.Test` publishers are excluded via `summarize_feeds.load_excluded_publishers("publishers.md")`.
- Only feeds with `state == "STABLE"` are audited; symbols starting with `DEPRECATED` are skipped and reported. The hygiene report scans all states (static check only).
- Active publisher = row in `publisher_updates` with `status = 'ACCEPTED'` AND `publisher_id` in the session's current `allowedPublisherIds`. Candidate discovery additionally includes `status = 'REJECTED' AND status_reason = 'UNAUTHORIZED'` rows, and requires `publishers_metadata_latest.key_type IN ('production','Production')`.
- `marketSchedule` day list is **Monday-first**. Day entries: `O` (open 24 h), `C` (closed), or `&`-joined `HHMM-HHMM` ranges (`2400` = end of day). Overrides: `MMDD/C` or `MMDD/<ranges>` applied to that local calendar date. Session entries without a `marketSchedule` key inherit from `exchanges[]` via the feed's `exchangeId`.
- Effective min_pub for a session = session-level `minPublishers` if present, else feed-level `minPublishers`.
- Classification: `CRITICAL` = any open minute with active ≤ min_pub; `WARN` = some open minute at min_pub + 1 (and never ≤ min_pub); `OK` otherwise.
- Selection target: projected **worst-minute** active count ≥ min_pub + 2.
- `lazer_to_modify.json` is only ever modified through `tools/edit-config/edit_config.py` (`--from-spec` + `--apply`); never write it directly.
- All new CSV artifacts go to `output_csv/` (gitignored — verify with `git check-ignore output_csv` before committing; if not ignored, do not `git add` artifacts).
- Commit messages: `feat(lazer_dq): ...` / `test(lazer_dq): ...` / `docs: ...` style, matching recent history.

## File Structure

| File                                                | Responsibility                                                                                                 |
| --------------------------------------------------- | -------------------------------------------------------------------------------------------------------------- |
| `lazer_dq/market_schedule.py` (new)                 | Parse `marketSchedule` strings; compute per-minute open masks; resolve exchange inheritance                    |
| `lazer_dq/min_pub_common.py` (new)                  | Config introspection: iterate STABLE (feed, session) pairs with allowed sets + effective min_pub; hygiene scan |
| `lazer_dq/audit_min_pub.py` (new)                   | Stage 1 CLI: per-minute active counts, classification, audit CSV + hygiene CSV                                 |
| `lazer_dq/peer_benchmark.py` (new)                  | Per-second alignment of candidate vs aggregate; NRMSE + hit-rate + pass logic                                  |
| `lazer_dq/qualify_candidates.py` (new)              | Stage 2 CLI: candidate discovery, activity gate, engine/peer quality gates, selection                          |
| `lazer_dq/apply_min_pub_remediation.py` (new)       | Stage 3 CLI: YAML spec generation, edit_config invocation, verification                                        |
| `lazer_dq/tests/test_market_schedule.py` etc. (new) | One test module per source module                                                                              |
| `docs/min_pub_audit.md` (new), `CLAUDE.md` (modify) | Documentation                                                                                                  |

---

### Task 1: marketSchedule parser (`lazer_dq/market_schedule.py`)

**Files:**

- Create: `lazer_dq/market_schedule.py`
- Test: `lazer_dq/tests/test_market_schedule.py`

**Interfaces:**

- Consumes: nothing from this repo (stdlib + pandas/numpy).
- Produces:

  - `parse_market_schedule(s: str) -> MarketSchedule` — raises `ValueError` on malformed input.
  - `MarketSchedule` frozen dataclass: `tz: str`, `days: tuple[7 × tuple[(start_min, end_min), ...]]` (minutes-of-day ints, end ≤ 1440), `overrides: dict[str MMDD, tuple[(start_min, end_min), ...]]`.
  - `open_minutes_mask(sched: MarketSchedule, start_utc: datetime, end_utc: datetime) -> pd.Series` — bool Series indexed by tz-aware UTC minutes `[start, end)`.
  - `resolve_schedule_string(feed: dict, session_entry: dict, exchanges_by_id: dict) -> str | None`.
  - `build_exchanges_by_id(config: dict) -> dict[int, dict]`.

- [ ] **Step 1: Write the failing tests**

```python
# lazer_dq/tests/test_market_schedule.py
"""Tests for marketSchedule string parsing and open-minute masks."""
from datetime import datetime, timezone

import pandas as pd
import pytest

from lazer_dq.market_schedule import (
    MarketSchedule,
    build_exchanges_by_id,
    open_minutes_mask,
    parse_market_schedule,
    resolve_schedule_string,
)

UTC = timezone.utc

NASDAQ_REGULAR = (
    "America/New_York;0930-1600,0930-1600,0930-1600,0930-1600,0930-1600,C,C;"
    "0101/C,0703/C,1127/0930-1300"
)
CRYPTO_247 = "America/New_York;O,O,O,O,O,O,O;"
FX_STYLE = "America/New_York;O,O,O,O,0000-1700,C,1700-2400;1224/0000-1700"
OVERNIGHT = (
    "America/New_York;0000-0400&2000-2400,0000-0400&2000-2400,0000-0400&2000-2400,"
    "0000-0400&2000-2400,0000-0400,C,2000-2400;"
)


def test_parse_basic_fields():
    s = parse_market_schedule(NASDAQ_REGULAR)
    assert s.tz == "America/New_York"
    assert s.days[0] == ((9 * 60 + 30, 16 * 60),)  # Monday
    assert s.days[5] == ()  # Saturday closed
    assert s.overrides["0101"] == ()
    assert s.overrides["1127"] == ((9 * 60 + 30, 13 * 60),)


def test_parse_open_and_ampersand():
    s = parse_market_schedule(OVERNIGHT)
    assert s.days[0] == ((0, 4 * 60), (20 * 60, 1440))
    assert parse_market_schedule(CRYPTO_247).days[6] == ((0, 1440),)


def test_parse_rejects_malformed():
    with pytest.raises(ValueError):
        parse_market_schedule("America/New_York;O,O,O")  # not 7 day entries
    with pytest.raises(ValueError):
        parse_market_schedule("no-semicolons-here")


def test_mask_regular_monday():
    # 2026-07-06 is a Monday; EDT = UTC-4, so 09:30 ET = 13:30 UTC.
    s = parse_market_schedule(NASDAQ_REGULAR)
    start = datetime(2026, 7, 6, tzinfo=UTC)
    end = datetime(2026, 7, 7, tzinfo=UTC)
    mask = open_minutes_mask(s, start, end)
    assert len(mask) == 1440
    assert bool(mask[pd.Timestamp("2026-07-06 13:30", tz="UTC")]) is True
    assert bool(mask[pd.Timestamp("2026-07-06 13:29", tz="UTC")]) is False
    assert bool(mask[pd.Timestamp("2026-07-06 19:59", tz="UTC")]) is True
    assert bool(mask[pd.Timestamp("2026-07-06 20:00", tz="UTC")]) is False
    # Total: 6.5 hours = 390 open minutes
    assert int(mask.sum()) == 390


def test_mask_holiday_override_closes_day():
    # 2026-07-03 is a Friday but 0703/C closes it.
    s = parse_market_schedule(NASDAQ_REGULAR)
    mask = open_minutes_mask(
        s, datetime(2026, 7, 3, tzinfo=UTC), datetime(2026, 7, 4, tzinfo=UTC)
    )
    assert int(mask.sum()) == 0


def test_mask_247():
    s = parse_market_schedule(CRYPTO_247)
    mask = open_minutes_mask(
        s, datetime(2026, 7, 4, tzinfo=UTC), datetime(2026, 7, 6, tzinfo=UTC)
    )
    assert int(mask.sum()) == 2880  # every minute open, incl. weekend


def test_mask_fx_sunday_open():
    # Sunday entry 1700-2400 ET: 2026-07-12 is a Sunday. 17:00 EDT = 21:00 UTC.
    s = parse_market_schedule(FX_STYLE)
    mask = open_minutes_mask(
        s, datetime(2026, 7, 12, tzinfo=UTC), datetime(2026, 7, 13, 4, tzinfo=UTC)
    )
    assert bool(mask[pd.Timestamp("2026-07-12 20:59", tz="UTC")]) is False
    assert bool(mask[pd.Timestamp("2026-07-12 21:00", tz="UTC")]) is True
    # Monday 00:00 ET (04:00 UTC Mon) is 'O' so still open at end of range
    assert bool(mask[pd.Timestamp("2026-07-13 03:59", tz="UTC")]) is True


def test_resolve_schedule_inline_and_inherited():
    config = {
        "exchanges": [
            {
                "exchangeId": 21,
                "sessions": [
                    {"session": "REGULAR", "marketSchedule": NASDAQ_REGULAR}
                ],
            }
        ]
    }
    ex_by_id = build_exchanges_by_id(config)
    inline_feed = {"feedId": 1}
    inline_entry = {"session": "REGULAAR-ignored", "marketSchedule": CRYPTO_247}
    assert resolve_schedule_string(inline_feed, inline_entry, ex_by_id) == CRYPTO_247

    inherited_feed = {"feedId": 884, "exchangeId": 21}
    inherited_entry = {"session": "REGULAR"}
    assert (
        resolve_schedule_string(inherited_feed, inherited_entry, ex_by_id)
        == NASDAQ_REGULAR
    )
    # No exchangeId and no inline string -> None
    assert resolve_schedule_string({"feedId": 9}, {"session": "REGULAR"}, ex_by_id) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest lazer_dq/tests/test_market_schedule.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lazer_dq.market_schedule'`

- [ ] **Step 3: Write the implementation**

```python
# lazer_dq/market_schedule.py
"""Parser for Lazer config `marketSchedule` strings and open-minute masks.

Format: "<IANA tz>;<mon>,<tue>,<wed>,<thu>,<fri>,<sat>,<sun>;<ov1>,<ov2>,..."
  - Day entries (Monday-first): "O" (open 24h), "C" (closed), or "&"-joined
    "HHMM-HHMM" local-time ranges, end-exclusive; "2400" = end of day.
  - Overrides: "MMDD/C" or "MMDD/<ranges>" — replace that local calendar
    date's windows (year-agnostic; the config is maintained annually).

Session entries without a `marketSchedule` key inherit the schedule from the
top-level `exchanges[]` entry referenced by the feed's `exchangeId`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

Ranges = tuple[tuple[int, int], ...]  # (start_minute, end_minute), end <= 1440


@dataclass(frozen=True)
class MarketSchedule:
    tz: str
    days: tuple[Ranges, ...]  # 7 entries, Monday-first
    overrides: dict  # "MMDD" -> Ranges (empty tuple = closed)


def _parse_hhmm(token: str) -> int:
    if len(token) != 4 or not token.isdigit():
        raise ValueError(f"bad HHMM token: {token!r}")
    minutes = int(token[:2]) * 60 + int(token[2:])
    if minutes > 1440:
        raise ValueError(f"HHMM out of range: {token!r}")
    return minutes


def _parse_ranges(token: str) -> Ranges:
    token = token.strip()
    if token == "C":
        return ()
    if token == "O":
        return ((0, 1440),)
    out = []
    for part in token.split("&"):
        try:
            start_s, end_s = part.split("-")
        except ValueError:
            raise ValueError(f"bad range token: {part!r}")
        start, end = _parse_hhmm(start_s), _parse_hhmm(end_s)
        if end <= start:
            raise ValueError(f"empty/inverted range: {part!r}")
        out.append((start, end))
    return tuple(out)


def parse_market_schedule(s: str) -> MarketSchedule:
    parts = s.split(";")
    if len(parts) < 2:
        raise ValueError(f"marketSchedule needs >=2 ';' sections: {s!r}")
    tz = parts[0].strip()
    if not tz:
        raise ValueError("empty timezone")
    day_tokens = parts[1].split(",")
    if len(day_tokens) != 7:
        raise ValueError(f"expected 7 day entries, got {len(day_tokens)}: {s!r}")
    days = tuple(_parse_ranges(t) for t in day_tokens)
    overrides: dict = {}
    if len(parts) >= 3 and parts[2].strip():
        for ov in parts[2].split(","):
            ov = ov.strip()
            if not ov:
                continue
            try:
                mmdd, spec = ov.split("/", 1)
            except ValueError:
                raise ValueError(f"bad override token: {ov!r}")
            if len(mmdd) != 4 or not mmdd.isdigit():
                raise ValueError(f"bad override date: {mmdd!r}")
            overrides[mmdd] = _parse_ranges(spec)
    return MarketSchedule(tz=tz, days=days, overrides=overrides)


def open_minutes_mask(
    sched: MarketSchedule, start_utc: datetime, end_utc: datetime
) -> pd.Series:
    """Boolean Series over UTC minutes [start_utc, end_utc), True where open.

    DST is handled by pandas tz conversion: each UTC minute is mapped to its
    local wall-clock time, then compared against that local date's windows.
    """
    idx = pd.date_range(start_utc, end_utc, freq="1min", inclusive="left", tz="UTC")
    local = idx.tz_convert(ZoneInfo(sched.tz))
    minute_of_day = np.asarray(local.hour) * 60 + np.asarray(local.minute)
    local_dates = np.asarray(local.date)
    out = np.zeros(len(idx), dtype=bool)
    for d in pd.unique(local_dates):
        mmdd = f"{d.month:02d}{d.day:02d}"
        ranges = sched.overrides.get(mmdd, sched.days[d.weekday()])
        day_sel = local_dates == d
        for start_min, end_min in ranges:
            out |= day_sel & (minute_of_day >= start_min) & (minute_of_day < end_min)
    return pd.Series(out, index=idx)


def build_exchanges_by_id(config: dict) -> dict:
    return {
        ex["exchangeId"]: ex
        for ex in config.get("exchanges", [])
        if "exchangeId" in ex
    }


def resolve_schedule_string(
    feed: dict, session_entry: dict, exchanges_by_id: dict
):
    """Inline `marketSchedule` string, else the exchange's same-session one."""
    if "marketSchedule" in session_entry:
        return session_entry["marketSchedule"]
    exchange = exchanges_by_id.get(feed.get("exchangeId"))
    if not exchange:
        return None
    for ex_session in exchange.get("sessions", []):
        if ex_session.get("session") == session_entry.get("session"):
            return ex_session.get("marketSchedule")
    return None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest lazer_dq/tests/test_market_schedule.py -v`
Expected: all PASS

- [ ] **Step 5: Sanity-check against the real config** (every STABLE schedule string must parse)

Run:

```bash
python3 -c "
import json
from lazer_dq.market_schedule import parse_market_schedule, resolve_schedule_string, build_exchanges_by_id
cfg = json.load(open('lazer_to_modify.json'))
ex = build_exchanges_by_id(cfg)
bad = missing = 0
for f in cfg['feeds']:
    if f.get('state') != 'STABLE':
        continue
    for s in f.get('marketSchedules', []):
        raw = resolve_schedule_string(f, s, ex)
        if raw is None:
            missing += 1
            continue
        try:
            parse_market_schedule(raw)
        except ValueError as e:
            bad += 1
            print('PARSE FAIL', f['feedId'], e)
print(f'unresolved schedules: {missing}, parse failures: {bad}')
"
```

Expected: `parse failures: 0`. If any string fails, extend `_parse_ranges`/`parse_market_schedule` to cover the real-world variant and add a regression test for it before proceeding.

- [ ] **Step 6: Commit**

```bash
pre-commit run --files lazer_dq/market_schedule.py lazer_dq/tests/test_market_schedule.py
git add lazer_dq/market_schedule.py lazer_dq/tests/test_market_schedule.py
git commit -m "feat(lazer_dq): marketSchedule string parser with open-minute masks"
```

---

### Task 2: Config introspection (`lazer_dq/min_pub_common.py`)

**Files:**

- Create: `lazer_dq/min_pub_common.py`
- Test: `lazer_dq/tests/test_min_pub_common.py`

**Interfaces:**

- Consumes: `market_schedule.resolve_schedule_string`, `market_schedule.build_exchanges_by_id` (Task 1).
- Produces:

  - `FeedSession` frozen dataclass: `feed_id: int`, `symbol: str`, `asset_type: str`, `session: str`, `allowed: frozenset[int]`, `effective_min_pub: int`, `schedule_str: str | None`.
  - `iter_stable_sessions(config: dict) -> Iterator[FeedSession]` — STABLE feeds only, DEPRECATED symbols skipped.
  - `deprecated_stable_feeds(config: dict) -> list[dict]` — `{feed_id, symbol}` rows for the skipped ones.
  - `hygiene_rows(config: dict) -> list[dict]` — all states; rows where the feed-level `minPublishers` exceeds the union of allowed publishers across sessions.

- [ ] **Step 1: Write the failing tests**

```python
# lazer_dq/tests/test_min_pub_common.py
from lazer_dq.min_pub_common import (
    FeedSession,
    deprecated_stable_feeds,
    hygiene_rows,
    iter_stable_sessions,
)

CONFIG = {
    "exchanges": [
        {
            "exchangeId": 1,
            "sessions": [{"session": "REGULAR", "marketSchedule": "UTC;O,O,O,O,O,O,O;"}],
        }
    ],
    "feeds": [
        {  # STABLE, session-level minPublishers override, inline schedule
            "feedId": 10,
            "symbol": "Equity.US.AAA/USD",
            "state": "STABLE",
            "minPublishers": 2,
            "metadata": {"asset_type": "equity"},
            "marketSchedules": [
                {
                    "session": "REGULAR",
                    "minPublishers": 3,
                    "allowedPublisherIds": [1, 2, 3, 4],
                    "marketSchedule": "America/New_York;0930-1600,0930-1600,0930-1600,0930-1600,0930-1600,C,C;",
                },
                {
                    "session": "PRE_MARKET",
                    "allowedPublisherIds": [1, 2],
                    "marketSchedule": "America/New_York;0400-0930,0400-0930,0400-0930,0400-0930,0400-0930,C,C;",
                },
            ],
        },
        {  # STABLE crypto, feed-level min_pub only, inherited schedule
            "feedId": 11,
            "symbol": "Crypto.BBB/USD",
            "state": "STABLE",
            "minPublishers": 1,
            "exchangeId": 1,
            "metadata": {"asset_type": "crypto"},
            "marketSchedules": [
                {"session": "REGULAR", "allowedPublisherIds": [5]}
            ],
        },
        {  # COMING_SOON: not audited, but hygiene-scanned
            "feedId": 12,
            "symbol": "InterestRate.CCC/USD",
            "state": "COMING_SOON",
            "minPublishers": 3,
            "metadata": {"asset_type": "interest-rate"},
            "marketSchedules": [{"session": "REGULAR", "allowedPublisherIds": []}],
        },
        {  # DEPRECATED STABLE: skipped, reported
            "feedId": 13,
            "symbol": "DEPRECATED FEED - Equity.US.DDD/USD",
            "state": "STABLE",
            "minPublishers": 1,
            "metadata": {"asset_type": "equity"},
            "marketSchedules": [{"session": "REGULAR", "allowedPublisherIds": [1]}],
        },
        {  # INACTIVE kill-switch: hygiene only
            "feedId": 14,
            "symbol": "Crypto.EEE/USD",
            "state": "INACTIVE",
            "minPublishers": 100,
            "metadata": {"asset_type": "crypto"},
            "marketSchedules": [{"session": "REGULAR", "allowedPublisherIds": [1, 2]}],
        },
    ],
}


def test_iter_stable_sessions_yields_per_session_with_effective_min_pub():
    sessions = list(iter_stable_sessions(CONFIG))
    by_key = {(s.feed_id, s.session): s for s in sessions}
    assert set(by_key) == {(10, "REGULAR"), (10, "PRE_MARKET"), (11, "REGULAR")}
    assert by_key[(10, "REGULAR")].effective_min_pub == 3  # session override
    assert by_key[(10, "PRE_MARKET")].effective_min_pub == 2  # feed-level
    assert by_key[(10, "REGULAR")].allowed == frozenset({1, 2, 3, 4})
    assert by_key[(11, "REGULAR")].schedule_str == "UTC;O,O,O,O,O,O,O;"  # inherited
    assert by_key[(11, "REGULAR")].asset_type == "crypto"


def test_deprecated_reported_not_iterated():
    assert deprecated_stable_feeds(CONFIG) == [
        {"feed_id": 13, "symbol": "DEPRECATED FEED - Equity.US.DDD/USD"}
    ]


def test_hygiene_rows_flag_min_pub_exceeding_allowed():
    rows = hygiene_rows(CONFIG)
    by_id = {r["feed_id"]: r for r in rows}
    assert set(by_id) == {12, 14}
    assert by_id[12]["issue"] == "no_allowed_publishers"
    assert by_id[14]["issue"] == "min_pub_exceeds_allowed"
    assert by_id[14]["allowed_union_count"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest lazer_dq/tests/test_min_pub_common.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lazer_dq.min_pub_common'`

- [ ] **Step 3: Write the implementation**

```python
# lazer_dq/min_pub_common.py
"""Config introspection shared by the min_pub audit/remediation pipeline.

Yields per-(feed, session) audit units from a new-format (session-only
publishers) Lazer config, and performs the static hygiene scan.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

from lazer_dq.market_schedule import build_exchanges_by_id, resolve_schedule_string

DEPRECATED_PREFIX = "DEPRECATED"


@dataclass(frozen=True)
class FeedSession:
    feed_id: int
    symbol: str
    asset_type: str
    session: str
    allowed: frozenset
    effective_min_pub: int
    schedule_str: str | None


def iter_stable_sessions(config: dict) -> Iterator[FeedSession]:
    """One FeedSession per marketSchedules entry of each STABLE feed.

    DEPRECATED-symbol feeds are skipped (see deprecated_stable_feeds).
    Effective min_pub = session-level minPublishers if present, else
    feed-level.
    """
    exchanges_by_id = build_exchanges_by_id(config)
    for feed in config.get("feeds", []):
        if feed.get("state") != "STABLE":
            continue
        symbol = feed.get("symbol", "")
        if symbol.startswith(DEPRECATED_PREFIX):
            continue
        for entry in feed.get("marketSchedules", []):
            yield FeedSession(
                feed_id=feed["feedId"],
                symbol=symbol,
                asset_type=feed.get("metadata", {}).get("asset_type", ""),
                session=entry.get("session", "REGULAR"),
                allowed=frozenset(entry.get("allowedPublisherIds", [])),
                effective_min_pub=entry.get(
                    "minPublishers", feed.get("minPublishers")
                ),
                schedule_str=resolve_schedule_string(feed, entry, exchanges_by_id),
            )


def deprecated_stable_feeds(config: dict) -> list:
    return [
        {"feed_id": f["feedId"], "symbol": f.get("symbol", "")}
        for f in config.get("feeds", [])
        if f.get("state") == "STABLE"
        and f.get("symbol", "").startswith(DEPRECATED_PREFIX)
    ]


def hygiene_rows(config: dict) -> list:
    """Static scan (all states): feed-level minPublishers > allowed union.

    Catches the `minPublishers: 100` kill-switch pattern and feeds that can
    never aggregate (e.g. min_pub 3 with 0 allowed publishers).
    """
    rows = []
    for feed in config.get("feeds", []):
        min_pub = feed.get("minPublishers")
        if min_pub is None:
            continue
        allowed_union = set()
        for entry in feed.get("marketSchedules", []):
            allowed_union.update(entry.get("allowedPublisherIds", []))
        if min_pub <= len(allowed_union):
            continue
        rows.append(
            {
                "feed_id": feed["feedId"],
                "symbol": feed.get("symbol", ""),
                "state": feed.get("state", ""),
                "feed_min_publishers": min_pub,
                "allowed_union_count": len(allowed_union),
                "issue": (
                    "no_allowed_publishers"
                    if not allowed_union
                    else "min_pub_exceeds_allowed"
                ),
            }
        )
    return rows
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest lazer_dq/tests/test_min_pub_common.py lazer_dq/tests/test_market_schedule.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
pre-commit run --files lazer_dq/min_pub_common.py lazer_dq/tests/test_min_pub_common.py
git add lazer_dq/min_pub_common.py lazer_dq/tests/test_min_pub_common.py
git commit -m "feat(lazer_dq): config introspection for min_pub audit (FeedSession, hygiene scan)"
```

---

### Task 3: Stage 1 audit CLI (`lazer_dq/audit_min_pub.py`)

**Files:**

- Create: `lazer_dq/audit_min_pub.py`
- Test: `lazer_dq/tests/test_audit_min_pub.py`

**Interfaces:**

- Consumes: `iter_stable_sessions`, `deprecated_stable_feeds`, `hygiene_rows` (Task 2); `parse_market_schedule`, `open_minutes_mask` (Task 1); `lib.config.load_config`, `lib.config.ThreadLocalClients`.
- Produces:

  - CLI: `python3 -m lazer_dq.audit_min_pub --config lazer_to_modify.json [--start-date YYYY-MM-DD --end-date YYYY-MM-DD] [--workers 8] [--feed-id N ...] [--resume] [--prolonged-threshold 30] [--output-dir output_csv]`
  - `output_csv/min_pub_audit_<start>_<end>.csv` with columns (exact order): `feed_id, symbol, asset_type, session, classification, effective_min_pub, allowed_count, static_margin, open_minutes, minutes_below_min, minutes_at_min, minutes_at_min_plus_1, longest_run_le_min, longest_run_le_min_plus_1, median_active, worst_minute_active, prolonged`
  - `output_csv/hygiene_report.csv` with the Task 2 hygiene columns.
  - Pure functions used by Stage 2/3 tests: `longest_true_run(values: np.ndarray) -> int`, `audit_metrics(active_counts: np.ndarray, min_pub: int, prolonged_threshold: int) -> dict`, `classify(metrics: dict) -> str`, `active_counts_for_session(per_minute_pubs: dict, mask: pd.Series, allowed: frozenset) -> np.ndarray`, `fetch_per_minute_publishers(client, feed_id, start_utc, end_utc) -> dict[pd.Timestamp, set]`.
  - Classification values written to CSV: `CRITICAL`, `WARN`, `OK`, `NO_SCHEDULE` (schedule unresolvable — metrics columns empty), plus one `SKIPPED_DEPRECATED` row per deprecated STABLE feed (session empty, metrics empty).

- [ ] **Step 1: Write the failing tests**

```python
# lazer_dq/tests/test_audit_min_pub.py
import numpy as np
import pandas as pd

from lazer_dq.audit_min_pub import (
    active_counts_for_session,
    audit_metrics,
    classify,
    longest_true_run,
)


def test_longest_true_run():
    assert longest_true_run(np.array([], dtype=bool)) == 0
    assert longest_true_run(np.array([False, False])) == 0
    assert longest_true_run(np.array([True, True, False, True])) == 2
    assert longest_true_run(np.array([True] * 5)) == 5


def test_audit_metrics_counts_and_runs():
    # min_pub = 2: below=1 minute (count 1), at=2 minutes (count 2),
    # at min+1=1 minute (count 3), above=2 minutes (count 4).
    counts = np.array([1, 2, 2, 3, 4, 4])
    m = audit_metrics(counts, min_pub=2, prolonged_threshold=3)
    assert m["open_minutes"] == 6
    assert m["minutes_below_min"] == 1
    assert m["minutes_at_min"] == 2
    assert m["minutes_at_min_plus_1"] == 1
    assert m["longest_run_le_min"] == 3  # [1, 2, 2]
    assert m["longest_run_le_min_plus_1"] == 4  # [1, 2, 2, 3]
    assert m["median_active"] == 2.5
    assert m["worst_minute_active"] == 1
    assert m["prolonged"] is True  # run of 3 at <= min_pub meets threshold 3


def test_classify():
    critical = {"minutes_below_min": 0, "minutes_at_min": 5, "minutes_at_min_plus_1": 0}
    warn = {"minutes_below_min": 0, "minutes_at_min": 0, "minutes_at_min_plus_1": 2}
    ok = {"minutes_below_min": 0, "minutes_at_min": 0, "minutes_at_min_plus_1": 0}
    assert classify(critical) == "CRITICAL"
    assert classify(warn) == "WARN"
    assert classify(ok) == "OK"


def test_active_counts_only_allowed_and_zero_fills_missing_minutes():
    idx = pd.date_range("2026-07-06 13:30", periods=4, freq="1min", tz="UTC")
    mask = pd.Series([True, True, True, False], index=idx)
    per_minute = {
        idx[0]: {1, 2, 99},  # 99 not allowed -> count 2
        idx[2]: {1},
        # idx[1] missing entirely -> count 0
        idx[3]: {1, 2},  # masked out (session closed)
    }
    counts = active_counts_for_session(per_minute, mask, allowed=frozenset({1, 2}))
    assert counts.tolist() == [2, 0, 1]


class FakeResult:
    def __init__(self, rows):
        self.result_rows = rows


class FakeClient:
    """Returns canned (minute, [publisher_ids]) rows for any query."""

    def __init__(self, rows):
        self._rows = rows
        self.queries = []

    def query(self, q, parameters=None):
        self.queries.append((q, parameters))
        return FakeResult(self._rows)


def test_fetch_per_minute_publishers_builds_utc_dict():
    from datetime import datetime, timezone

    from lazer_dq.audit_min_pub import fetch_per_minute_publishers

    t0 = datetime(2026, 7, 6, 13, 30, tzinfo=timezone.utc)
    client = FakeClient([(t0.replace(tzinfo=None), [1, 2])])
    out = fetch_per_minute_publishers(
        client, 10, t0, datetime(2026, 7, 6, 13, 40, tzinfo=timezone.utc)
    )
    key = pd.Timestamp("2026-07-06 13:30", tz="UTC")
    assert out == {key: {1, 2}}
    # Parameterized query, feed scoped, ACCEPTED-only
    q, params = client.queries[0]
    assert "status = 'ACCEPTED'" in q
    assert params["feed_id"] == 10
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest lazer_dq/tests/test_audit_min_pub.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'lazer_dq.audit_min_pub'`

- [ ] **Step 3: Write the implementation**

```python
# lazer_dq/audit_min_pub.py
"""Stage 1 of the min_pub pipeline: audit active publishers vs minPublishers.

For every STABLE (feed, session) in a new-format Lazer config, counts
distinct ACCEPTED allowed publishers per minute over a UTC date window,
restricted to the session's open hours, and classifies:

  CRITICAL  any open minute with active <= min_pub
  WARN      never <= min_pub, but some minute at min_pub + 1
  OK        otherwise

Run:
    python3 -m lazer_dq.audit_min_pub --config lazer_to_modify.json \
        --start-date 2026-07-06 --end-date 2026-07-13 --workers 8
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
from lazer_dq.min_pub_common import (
    FeedSession,
    deprecated_stable_feeds,
    hygiene_rows,
    iter_stable_sessions,
)

AUDIT_COLUMNS = [
    "feed_id",
    "symbol",
    "asset_type",
    "session",
    "classification",
    "effective_min_pub",
    "allowed_count",
    "static_margin",
    "open_minutes",
    "minutes_below_min",
    "minutes_at_min",
    "minutes_at_min_plus_1",
    "longest_run_le_min",
    "longest_run_le_min_plus_1",
    "median_active",
    "worst_minute_active",
    "prolonged",
]

PER_MINUTE_QUERY = """
    SELECT
        toStartOfMinute(publish_time) AS minute,
        groupUniqArrayIf(publisher_id, status = 'ACCEPTED') AS active_pubs
    FROM publisher_updates
    PREWHERE price_feed_id = {feed_id:UInt64}
    WHERE publish_time >= {start:String}
      AND publish_time < {end:String}
    GROUP BY minute
    ORDER BY minute
"""


def fetch_per_minute_publishers(client, feed_id, start_utc, end_utc):
    """dict of UTC-minute Timestamp -> set of ACCEPTED publisher_ids."""
    result = client.query(
        PER_MINUTE_QUERY,
        parameters={
            "feed_id": feed_id,
            "start": start_utc.strftime("%Y-%m-%d %H:%M:%S"),
            "end": end_utc.strftime("%Y-%m-%d %H:%M:%S"),
        },
    )
    return {
        pd.Timestamp(minute, tz="UTC"): set(pubs)
        for minute, pubs in result.result_rows
    }


def active_counts_for_session(per_minute_pubs, mask, allowed):
    """Active-count array over the mask's open minutes; missing minutes = 0."""
    open_minutes = mask.index[mask.to_numpy()]
    return np.array(
        [len(per_minute_pubs.get(m, set()) & allowed) for m in open_minutes],
        dtype=int,
    )


def longest_true_run(values) -> int:
    best = current = 0
    for v in values:
        current = current + 1 if v else 0
        best = max(best, current)
    return best


def audit_metrics(active_counts, min_pub, prolonged_threshold):
    le_min = active_counts <= min_pub
    le_min_plus_1 = active_counts <= min_pub + 1
    return {
        "open_minutes": int(len(active_counts)),
        "minutes_below_min": int((active_counts < min_pub).sum()),
        "minutes_at_min": int((active_counts == min_pub).sum()),
        "minutes_at_min_plus_1": int((active_counts == min_pub + 1).sum()),
        "longest_run_le_min": longest_true_run(le_min),
        "longest_run_le_min_plus_1": longest_true_run(le_min_plus_1),
        "median_active": float(np.median(active_counts)) if len(active_counts) else 0.0,
        "worst_minute_active": int(active_counts.min()) if len(active_counts) else 0,
        "prolonged": bool(longest_true_run(le_min_plus_1) >= prolonged_threshold),
    }


def classify(metrics) -> str:
    if metrics["minutes_below_min"] + metrics["minutes_at_min"] > 0:
        return "CRITICAL"
    if metrics["minutes_at_min_plus_1"] > 0:
        return "WARN"
    return "OK"


def audit_feed(client, feed_sessions, start_utc, end_utc, prolonged_threshold):
    """Audit all sessions of one feed with a single ClickHouse query."""
    per_minute = fetch_per_minute_publishers(
        client, feed_sessions[0].feed_id, start_utc, end_utc
    )
    rows = []
    for fs in feed_sessions:
        base = {
            "feed_id": fs.feed_id,
            "symbol": fs.symbol,
            "asset_type": fs.asset_type,
            "session": fs.session,
            "effective_min_pub": fs.effective_min_pub,
            "allowed_count": len(fs.allowed),
            "static_margin": len(fs.allowed) - fs.effective_min_pub,
        }
        if fs.schedule_str is None:
            rows.append({**base, "classification": "NO_SCHEDULE"})
            continue
        mask = open_minutes_mask(
            parse_market_schedule(fs.schedule_str), start_utc, end_utc
        )
        counts = active_counts_for_session(per_minute, mask, fs.allowed)
        metrics = audit_metrics(counts, fs.effective_min_pub, prolonged_threshold)
        rows.append({**base, **metrics, "classification": classify(metrics)})
    return rows


def default_window():
    """Last 7 full UTC days: [today-7 00:00, today 00:00)."""
    end = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    return end - timedelta(days=7), end


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True)
    p.add_argument("--start-date", help="UTC start date YYYY-MM-DD (inclusive)")
    p.add_argument("--end-date", help="UTC end date YYYY-MM-DD (exclusive)")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--feed-id", type=int, nargs="*", help="restrict to these feeds")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--prolonged-threshold", type=int, default=30)
    p.add_argument("--output-dir", default="output_csv")
    return p.parse_args(argv)


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

    # Static hygiene report (all states) — no ClickHouse needed.
    hygiene = hygiene_rows(config)
    hygiene_path = out_dir / "hygiene_report.csv"
    with open(hygiene_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "feed_id",
                "symbol",
                "state",
                "feed_min_publishers",
                "allowed_union_count",
                "issue",
            ],
        )
        writer.writeheader()
        writer.writerows(hygiene)
    print(f"Hygiene report: {len(hygiene)} rows -> {hygiene_path}")

    # Group audit units by feed (one query per feed covers all its sessions).
    by_feed = {}
    for fs in iter_stable_sessions(config):
        if args.feed_id and fs.feed_id not in args.feed_id:
            continue
        by_feed.setdefault(fs.feed_id, []).append(fs)

    audit_path = out_dir / (
        f"min_pub_audit_{start_utc:%Y-%m-%d}_{end_utc:%Y-%m-%d}.csv"
    )
    done_feed_ids = set()
    if args.resume and audit_path.exists():
        done_feed_ids = set(
            pd.read_csv(audit_path, usecols=["feed_id"])["feed_id"].astype(int)
        )
        print(f"Resume: skipping {len(done_feed_ids)} already-audited feeds")
    todo = {fid: fss for fid, fss in by_feed.items() if fid not in done_feed_ids}
    print(f"Auditing {len(todo)} feeds ({start_utc:%Y-%m-%d} .. {end_utc:%Y-%m-%d})")

    from lib.config import ThreadLocalClients, load_config

    write_lock = threading.Lock()
    new_file = not (args.resume and audit_path.exists())
    csv_file = open(audit_path, "w" if new_file else "a", newline="")
    writer = csv.DictWriter(csv_file, fieldnames=AUDIT_COLUMNS, extrasaction="ignore")
    if new_file:
        writer.writeheader()
        # Deprecated STABLE feeds: reported once, no metrics.
        for row in deprecated_stable_feeds(config):
            writer.writerow(
                {
                    "feed_id": row["feed_id"],
                    "symbol": row["symbol"],
                    "classification": "SKIPPED_DEPRECATED",
                }
            )
        csv_file.flush()

    failures = 0
    with ThreadLocalClients(load_config(), lazer_only=True) as pool:

        def run_one(feed_sessions):
            client = pool.get_lazer_client()
            return audit_feed(
                client, feed_sessions, start_utc, end_utc, args.prolonged_threshold
            )

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(run_one, fss): fid for fid, fss in todo.items()
            }
            for i, future in enumerate(as_completed(futures), 1):
                fid = futures[future]
                try:
                    rows = future.result()
                except Exception as e:  # soft-fail, continue (bulk-runner pattern)
                    failures += 1
                    print(f"  [{i}/{len(todo)}] feed {fid} FAILED: {e}")
                    continue
                with write_lock:
                    writer.writerows(rows)
                    csv_file.flush()
                worst = min(
                    (r["classification"] for r in rows),
                    key=lambda c: ["CRITICAL", "WARN", "NO_SCHEDULE", "OK"].index(c)
                    if c in ("CRITICAL", "WARN", "NO_SCHEDULE", "OK")
                    else 99,
                )
                print(f"  [{i}/{len(todo)}] feed {fid}: {worst}")
    csv_file.close()
    print(f"Audit written to {audit_path} ({failures} feed failures)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest lazer_dq/tests/test_audit_min_pub.py -v`
Expected: all PASS

- [ ] **Step 5: Smoke-test against production on a small feed set** (uses real ClickHouse; needs `config.yaml`)

Run:

```bash
python3 -m lazer_dq.audit_min_pub --config lazer_to_modify.json \
    --feed-id 1 1830 1554 --workers 2 \
    --start-date 2026-07-11 --end-date 2026-07-12
head -5 output_csv/min_pub_audit_2026-07-11_2026-07-12.csv
```

Expected: 3 audited feeds; feed 1554 (1 allowed / min_pub 1) should classify CRITICAL; no tracebacks. Investigate any surprise before continuing.

- [ ] **Step 6: Commit**

```bash
pre-commit run --files lazer_dq/audit_min_pub.py lazer_dq/tests/test_audit_min_pub.py
git add lazer_dq/audit_min_pub.py lazer_dq/tests/test_audit_min_pub.py
git commit -m "feat(lazer_dq): audit_min_pub — per-minute active-vs-minPublishers audit (stage 1)"
```

---

### Task 4: Peer benchmark module (`lazer_dq/peer_benchmark.py`)

**Files:**

- Create: `lazer_dq/peer_benchmark.py`
- Test: `lazer_dq/tests/test_peer_benchmark.py`

**Interfaces:**

- Consumes: pandas/numpy only (queries live in Task 5; this module is pure computation).
- Produces:

  - `PeerThresholds` dataclass: `nrmse_auto: float = 0.05`, `nrmse_cond: float = 0.15`, `min_hit_rate_pct: float = 85.0`, `min_obs: int = 1000`.
  - `align_per_second(pub_df: pd.DataFrame, agg_df: pd.DataFrame) -> pd.DataFrame` — inputs have columns `ts` (datetime) and `price` (float); output has one row per second where **both** sides have data, columns `pub_price`, `agg_price` (last observation in each second).
  - `evaluate_peer(pub_df, agg_df, thresholds: PeerThresholds) -> dict` with keys `n_observations, nrmse, hit_rate_pct, passed (bool), reason (str)`. Reasons: `"pass"`, `"insufficient_obs"`, `"zero_range"`, `"fail_quality"`.
  - Metric definitions (identical shape to the engine's): `rmse = sqrt(mean((pub-agg)^2))`; `nrmse = rmse / (agg.max() - agg.min())`; `hit_rate_pct = mean(|pub-agg|/agg <= 0.001) * 100`. Prices are raw config-exponent integers on both sides of the same feed, so scaling cancels in both metrics — no exponent adjustment needed.
  - Pass logic: `nrmse < nrmse_auto` OR (`nrmse < nrmse_cond` AND `hit_rate_pct >= min_hit_rate_pct`), after `n_observations >= min_obs`.

- [ ] **Step 1: Write the failing tests**

```python
# lazer_dq/tests/test_peer_benchmark.py
import numpy as np
import pandas as pd

from lazer_dq.peer_benchmark import PeerThresholds, align_per_second, evaluate_peer

RNG = np.random.default_rng(42)


def _series(start, n_seconds, price_fn, per_second=2):
    ts, price = [], []
    base = pd.Timestamp(start, tz="UTC")
    for i in range(n_seconds):
        for j in range(per_second):
            ts.append(base + pd.Timedelta(seconds=i, milliseconds=200 * j))
            price.append(price_fn(i))
    return pd.DataFrame({"ts": ts, "price": price})


def test_align_takes_last_per_second_inner_join():
    pub = pd.DataFrame(
        {
            "ts": pd.to_datetime(
                ["2026-07-06 00:00:00.100", "2026-07-06 00:00:00.900",
                 "2026-07-06 00:00:02.500"], utc=True
            ),
            "price": [100.0, 101.0, 103.0],
        }
    )
    agg = pd.DataFrame(
        {
            "ts": pd.to_datetime(
                ["2026-07-06 00:00:00.500", "2026-07-06 00:00:01.000"], utc=True
            ),
            "price": [100.5, 102.0],
        }
    )
    aligned = align_per_second(pub, agg)
    # Only second 00 exists on both sides; last pub obs in that second is 101.0
    assert len(aligned) == 1
    assert aligned.iloc[0]["pub_price"] == 101.0
    assert aligned.iloc[0]["agg_price"] == 100.5


def test_evaluate_peer_good_publisher_passes():
    # Trending series so the range is non-trivial; publisher tracks within 0.01%.
    agg = _series("2026-07-06", 1500, lambda i: 100.0 + i * 0.01)
    pub = _series("2026-07-06", 1500, lambda i: (100.0 + i * 0.01) * 1.0001)
    result = evaluate_peer(pub, agg, PeerThresholds())
    assert result["n_observations"] == 1500
    assert result["passed"] is True
    assert result["reason"] == "pass"
    assert result["hit_rate_pct"] > 99.0


def test_evaluate_peer_bad_publisher_fails_quality():
    agg = _series("2026-07-06", 1500, lambda i: 100.0 + i * 0.01)
    # 5% off and noisy: hit rate ~0, nrmse >> cond threshold
    pub = _series("2026-07-06", 1500, lambda i: (100.0 + i * 0.01) * 1.05)
    result = evaluate_peer(pub, agg, PeerThresholds())
    assert result["passed"] is False
    assert result["reason"] == "fail_quality"


def test_evaluate_peer_insufficient_obs_and_zero_range():
    thresholds = PeerThresholds()
    small_agg = _series("2026-07-06", 10, lambda i: 100.0)
    small_pub = _series("2026-07-06", 10, lambda i: 100.0)
    r = evaluate_peer(small_pub, small_agg, thresholds)
    assert r["passed"] is False and r["reason"] == "insufficient_obs"

    flat_agg = _series("2026-07-06", 1500, lambda i: 100.0)
    flat_pub = _series("2026-07-06", 1500, lambda i: 100.0)
    r = evaluate_peer(flat_pub, flat_agg, thresholds)
    assert r["passed"] is False and r["reason"] == "zero_range"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest lazer_dq/tests/test_peer_benchmark.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# lazer_dq/peer_benchmark.py
"""Peer benchmark: candidate publisher vs the feed's own aggregate price.

Used for feeds with no Datascope benchmark (crypto, funding-rate, NAV,
redemption-rate, custom, and any equity market the DQ engine doesn't
support). Reference = price_feeds aggregate; same NRMSE / hit-rate shape as
lazer_dq/evaluate_feed_standalone.py. Circularity (the aggregate is built
from current publishers) is accepted by design — see the 2026-07-13 spec.

Prices are raw config-exponent integers on both sides of the same feed, so
exponent scaling cancels in nrmse (range-normalized) and hit rate
(ratio-based); no adjustment is applied.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PeerThresholds:
    nrmse_auto: float = 0.05
    nrmse_cond: float = 0.15
    min_hit_rate_pct: float = 85.0
    min_obs: int = 1000


def _last_per_second(df: pd.DataFrame) -> pd.Series:
    out = df.copy()
    out["second"] = out["ts"].dt.floor("1s")
    return out.groupby("second")["price"].last()


def align_per_second(pub_df: pd.DataFrame, agg_df: pd.DataFrame) -> pd.DataFrame:
    """Inner-join last-observation-per-second series from both sides."""
    if pub_df.empty or agg_df.empty:
        return pd.DataFrame(columns=["pub_price", "agg_price"])
    pub = _last_per_second(pub_df).rename("pub_price")
    agg = _last_per_second(agg_df).rename("agg_price")
    return pd.concat([pub, agg], axis=1, join="inner")


def evaluate_peer(
    pub_df: pd.DataFrame, agg_df: pd.DataFrame, thresholds: PeerThresholds
) -> dict:
    aligned = align_per_second(pub_df, agg_df)
    n = len(aligned)
    result = {
        "n_observations": n,
        "nrmse": float("nan"),
        "hit_rate_pct": float("nan"),
        "passed": False,
        "reason": "insufficient_obs",
    }
    if n < thresholds.min_obs:
        return result

    diff = aligned["pub_price"] - aligned["agg_price"]
    rmse = float(np.sqrt((diff**2).mean()))
    agg_range = float(aligned["agg_price"].max() - aligned["agg_price"].min())
    hit_rate = float(
        ((diff.abs() / aligned["agg_price"]).abs() <= 0.001).mean() * 100.0
    )
    result["hit_rate_pct"] = hit_rate
    if agg_range <= 0:
        result["reason"] = "zero_range"
        return result
    nrmse = rmse / agg_range
    result["nrmse"] = float(nrmse)

    passed = nrmse < thresholds.nrmse_auto or (
        nrmse < thresholds.nrmse_cond and hit_rate >= thresholds.min_hit_rate_pct
    )
    result["passed"] = bool(passed)
    result["reason"] = "pass" if passed else "fail_quality"
    return result
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest lazer_dq/tests/test_peer_benchmark.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
pre-commit run --files lazer_dq/peer_benchmark.py lazer_dq/tests/test_peer_benchmark.py
git add lazer_dq/peer_benchmark.py lazer_dq/tests/test_peer_benchmark.py
git commit -m "feat(lazer_dq): peer_benchmark — candidate-vs-aggregate NRMSE/hit-rate"
```

---

### Task 5: Stage 2 qualification CLI (`lazer_dq/qualify_candidates.py`)

**Files:**

- Create: `lazer_dq/qualify_candidates.py`
- Test: `lazer_dq/tests/test_qualify_candidates.py`

**Interfaces:**

- Consumes: `FeedSession`, `iter_stable_sessions` (Task 2); `parse_market_schedule`, `open_minutes_mask` (Task 1); `PeerThresholds`, `evaluate_peer` (Task 4); `lazer_dq.summarize_feeds.load_stats`, `load_excluded_publishers`, `ASSET_CLASS_CONFIG`; `lazer_dq.evaluate_feeds_bulk.compute_times_from_mode`; Stage 1 audit CSV.
- Produces:

  - CLI: `python3 -m lazer_dq.qualify_candidates --config lazer_to_modify.json --audit-csv output_csv/min_pub_audit_<start>_<end>.csv --start-date YYYY-MM-DD --end-date YYYY-MM-DD [--cluster lazer-prod] [--exclude-publisher N ...] [--min-activity 0.90] [--target-margin 2] [--peer-nrmse-auto 0.05] [--peer-nrmse-cond 0.15] [--peer-hit-rate 85] [--min-obs 1000] [--peer-days 2] [--reports-dir dq_reports] [--output-dir output_csv] [--publishers-md publishers.md]`
  - `output_csv/candidates_report.csv`: `feed_id, symbol, session, classification, candidate_publisher_id, activity_pct, gate1_pass, quality_path, engine_mode, benchmark_date, rmse_over_spread, hit_rate, n_obs, nrmse, gate2_pass, selected, selection_rank`
  - `output_csv/qualification_summary.csv`: `feed_id, symbol, session, classification, effective_min_pub, target, worst_minute_before, n_candidates, n_gate1, n_gate2, n_selected, projected_worst_after, met_target`
  - `output_csv/flagged_feeds.csv`: `feed_id, symbol, session, reason, detail` (reasons: `no_candidates`, `candidates_fail_activity`, `candidates_fail_quality`, `still_below_target`, `no_benchmark_data`)
  - `output_csv/min_pub_activity/feed_<id>.csv.gz`: per-minute activity matrix, columns `minute, publisher_id, n_updates` (read by Stage 3 verification).
  - Pure functions for tests and Stage 3: `engine_mode_for(fs: FeedSession) -> str | None`, `activity_pct(matrix_df, mask, publisher_id) -> float`, `projected_worst_minute(matrix_df, mask, publisher_ids: set) -> int`, `select_candidates(passers: list[dict], matrix_df, mask, allowed: frozenset, min_pub: int, target_margin: int) -> tuple[list[int], int]` (returns selected ids + projected worst), `engine_gate(stats_row: dict, mode: str, min_obs: int) -> bool`.
  - Engine mode mapping (`engine_mode_for`): asset_type `fx`→`fx`; `metal`→`metals`; `commodity`→`commodity`; `rates`→`us-treasuries-yield`; `equity` with symbol prefix `Equity.US.` → session-mapped `{REGULAR: us-equities, PRE_MARKET: us-equities-pre, POST_MARKET: us-equities-post, OVER_NIGHT: us-equities-overnight}`; `equity` with prefix `Equity.HK.` and session REGULAR → `hk-equities`; **everything else → `None` (peer path)**.
  - Engine gate: if the mode has thresholds in `ASSET_CLASS_CONFIG` (us-equities modes, hk-equities) use `rmse_over_spread <= default_max_ros[mode] AND hit_rate_0.1pct >= default_min_hit[mode] AND n_observations >= min_obs`; otherwise fall back to the engine's own `pass_fail == "pass"` AND `n_observations >= min_obs`.

- [ ] **Step 1: Write the failing tests**

```python
# lazer_dq/tests/test_qualify_candidates.py
import numpy as np
import pandas as pd
import pytest

from lazer_dq.min_pub_common import FeedSession
from lazer_dq.qualify_candidates import (
    activity_pct,
    engine_gate,
    engine_mode_for,
    projected_worst_minute,
    select_candidates,
)


def _fs(asset_type, symbol, session):
    return FeedSession(
        feed_id=1,
        symbol=symbol,
        asset_type=asset_type,
        session=session,
        allowed=frozenset(),
        effective_min_pub=1,
        schedule_str=None,
    )


def test_engine_mode_for_mapping():
    assert engine_mode_for(_fs("fx", "FX.EUR/USD", "REGULAR")) == "fx"
    assert engine_mode_for(_fs("metal", "Metal.XAU/USD", "REGULAR")) == "metals"
    assert engine_mode_for(_fs("commodity", "Commodities.CL/USD", "REGULAR")) == "commodity"
    assert engine_mode_for(_fs("rates", "Rates.US10Y", "REGULAR")) == "us-treasuries-yield"
    assert engine_mode_for(_fs("equity", "Equity.US.AAPL/USD", "REGULAR")) == "us-equities"
    assert engine_mode_for(_fs("equity", "Equity.US.AAPL/USD", "PRE_MARKET")) == "us-equities-pre"
    assert engine_mode_for(_fs("equity", "Equity.US.AAPL/USD", "OVER_NIGHT")) == "us-equities-overnight"
    assert engine_mode_for(_fs("equity", "Equity.HK.0700/HKD", "REGULAR")) == "hk-equities"
    # No engine support -> peer path
    assert engine_mode_for(_fs("crypto", "Crypto.BTC/USD", "REGULAR")) is None
    assert engine_mode_for(_fs("equity", "Equity.JP.7203/JPY", "REGULAR")) is None
    assert engine_mode_for(_fs("funding-rate", "FundingRate.X/USD", "REGULAR")) is None


def test_engine_gate_with_and_without_configured_thresholds():
    row_good = {"rmse_over_spread": "0.5", "hit_rate_0.1pct": "95", "n_observations": "5000", "pass_fail": "fail"}
    row_bad = {"rmse_over_spread": "5.0", "hit_rate_0.1pct": "95", "n_observations": "5000", "pass_fail": "pass"}
    # us-equities has configured thresholds (max_ros 1.0, min_hit 80) -> uses them
    assert engine_gate(row_good, "us-equities", min_obs=1000) is True
    assert engine_gate(row_bad, "us-equities", min_obs=1000) is False
    # fx has no configured thresholds -> falls back to engine pass_fail
    assert engine_gate(row_bad, "fx", min_obs=1000) is True
    assert engine_gate(row_good, "fx", min_obs=1000) is False
    # observation floor always applies
    thin = dict(row_good, n_observations="10")
    assert engine_gate(thin, "us-equities", min_obs=1000) is False


def _matrix_and_mask():
    """3 open minutes; pubs 1,2 always active; pub 7 active 2/3; pub 8 active 1/3."""
    minutes = pd.date_range("2026-07-06 13:30", periods=3, freq="1min", tz="UTC")
    rows = []
    for m in minutes:
        rows += [(m, 1, 5), (m, 2, 5)]
    rows += [(minutes[0], 7, 5), (minutes[1], 7, 5)]
    rows += [(minutes[2], 8, 5)]
    matrix = pd.DataFrame(rows, columns=["minute", "publisher_id", "n_updates"])
    mask = pd.Series(True, index=minutes)
    return matrix, mask


def test_activity_pct():
    matrix, mask = _matrix_and_mask()
    assert activity_pct(matrix, mask, 1) == pytest.approx(1.0)
    assert activity_pct(matrix, mask, 7) == pytest.approx(2 / 3)
    assert activity_pct(matrix, mask, 99) == 0.0


def test_projected_worst_minute():
    matrix, mask = _matrix_and_mask()
    assert projected_worst_minute(matrix, mask, {1, 2}) == 2
    # adding pub 7 helps minutes 0-1 but minute 2 stays at 2
    assert projected_worst_minute(matrix, mask, {1, 2, 7}) == 2
    assert projected_worst_minute(matrix, mask, {1, 2, 7, 8}) == 3


def test_select_candidates_stops_at_target_and_reports_shortfall():
    matrix, mask = _matrix_and_mask()
    allowed = frozenset({1, 2})
    # min_pub=1, target margin 2 -> need worst-minute >= 3
    passers = [
        {"candidate_publisher_id": 7, "sort_metric": 0.1},
        {"candidate_publisher_id": 8, "sort_metric": 0.2},
    ]
    selected, projected = select_candidates(
        passers, matrix, mask, allowed, min_pub=1, target_margin=2
    )
    assert selected == [7, 8]  # 7 alone leaves worst at 2 -> also takes 8
    assert projected == 3
    # unreachable target: min_pub=4 needs worst >= 6, only 4 pubs exist
    selected2, projected2 = select_candidates(
        passers, matrix, mask, allowed, min_pub=4, target_margin=2
    )
    assert selected2 == [7, 8]
    assert projected2 == 3  # best achievable; caller flags still_below_target
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest lazer_dq/tests/test_qualify_candidates.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# lazer_dq/qualify_candidates.py
"""Stage 2 of the min_pub pipeline: qualify candidate publishers.

Reads the Stage-1 audit CSV, and for each CRITICAL/WARN (feed, session):
  1. discovers candidates — production-key publishers already submitting to
     the feed (ACCEPTED or REJECTED/UNAUTHORIZED) but not in the session's
     allowedPublisherIds and not excluded (publisher 0, publishers.md
     ".Test" entries, --exclude-publisher);
  2. Gate 1 (activity): active >= --min-activity share of open minutes;
  3. Gate 2 (quality): Datascope engine run for supported modes, else peer
     comparison vs the feed's aggregate (lazer_dq/peer_benchmark.py);
  4. selects passers (best quality first) until the projected worst-minute
     active count reaches min_pub + --target-margin.

Run:
    python3 -m lazer_dq.qualify_candidates --config lazer_to_modify.json \
        --audit-csv output_csv/min_pub_audit_2026-07-06_2026-07-13.csv \
        --start-date 2026-07-06 --end-date 2026-07-13 --cluster lazer-prod
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from lazer_dq.evaluate_feeds_bulk import compute_times_from_mode
from lazer_dq.market_schedule import open_minutes_mask, parse_market_schedule
from lazer_dq.min_pub_common import FeedSession, iter_stable_sessions
from lazer_dq.peer_benchmark import PeerThresholds, evaluate_peer
from lazer_dq.summarize_feeds import (
    ASSET_CLASS_CONFIG,
    load_excluded_publishers,
    load_stats,
)

FLAG_REASONS = (
    "no_candidates",
    "candidates_fail_activity",
    "candidates_fail_quality",
    "still_below_target",
    "no_benchmark_data",
)

CANDIDATE_COLUMNS = [
    "feed_id", "symbol", "session", "classification", "candidate_publisher_id",
    "activity_pct", "gate1_pass", "quality_path", "engine_mode", "benchmark_date",
    "rmse_over_spread", "hit_rate", "n_obs", "nrmse", "gate2_pass", "selected",
    "selection_rank",
]
SUMMARY_COLUMNS = [
    "feed_id", "symbol", "session", "classification", "effective_min_pub",
    "target", "worst_minute_before", "n_candidates", "n_gate1", "n_gate2",
    "n_selected", "projected_worst_after", "met_target",
]

ACTIVITY_QUERY = """
    SELECT
        toStartOfMinute(pu.publish_time) AS minute,
        pu.publisher_id AS publisher_id,
        count() AS n_updates
    FROM publisher_updates pu
    INNER JOIN publishers_metadata_latest pml
        ON pu.publisher_id = pml.publisher_id
    PREWHERE pu.price_feed_id = {feed_id:UInt64}
    WHERE pu.publish_time >= {start:String}
      AND pu.publish_time < {end:String}
      AND (
        pu.status = 'ACCEPTED'
        OR (pu.status = 'REJECTED' AND pu.status_reason = 'UNAUTHORIZED')
      )
      AND pu.price IS NOT NULL
      AND pml.key_type IN ('production', 'Production')
    GROUP BY minute, publisher_id
"""

PER_SECOND_PRICES_QUERY = """
    SELECT
        toStartOfSecond(pu.publish_time) AS ts,
        pu.publisher_id AS publisher_id,
        argMax(pu.price, pu.publish_time) AS price
    FROM publisher_updates pu
    INNER JOIN publishers_metadata_latest pml
        ON pu.publisher_id = pml.publisher_id
    PREWHERE pu.price_feed_id = {feed_id:UInt64}
    WHERE pu.publish_time >= {start:String}
      AND pu.publish_time < {end:String}
      AND (
        pu.status = 'ACCEPTED'
        OR (pu.status = 'REJECTED' AND pu.status_reason = 'UNAUTHORIZED')
      )
      AND pu.price IS NOT NULL
      AND pu.publisher_id IN {publisher_ids:Array(UInt64)}
      AND pml.key_type IN ('production', 'Production')
    GROUP BY ts, publisher_id
    ORDER BY ts
"""

AGGREGATE_QUERY = """
    SELECT
        toStartOfSecond(publish_time) AS ts,
        argMax(price, publish_time) AS price
    FROM price_feeds
    WHERE price_feed_id = {feed_id:UInt64}
      AND publish_time >= {start:String}
      AND publish_time < {end:String}
      AND price IS NOT NULL
      AND channel = {channel:UInt8}
    GROUP BY ts
    ORDER BY ts
"""

US_EQUITY_SESSION_MODES = {
    "REGULAR": "us-equities",
    "PRE_MARKET": "us-equities-pre",
    "POST_MARKET": "us-equities-post",
    "OVER_NIGHT": "us-equities-overnight",
}

ENGINE_MODE_THRESHOLDS = {}
for _ac in ASSET_CLASS_CONFIG.values():
    for _m in _ac["modes"]:
        ENGINE_MODE_THRESHOLDS[_m] = (
            _ac["default_max_ros"][_m],
            _ac["default_min_hit"][_m],
        )


def engine_mode_for(fs: FeedSession):
    """DQ-engine mode for this (feed, session), or None -> peer path."""
    if fs.asset_type == "fx":
        return "fx"
    if fs.asset_type == "metal":
        return "metals"
    if fs.asset_type == "commodity":
        return "commodity"
    if fs.asset_type == "rates":
        return "us-treasuries-yield"
    if fs.asset_type == "equity":
        if fs.symbol.startswith("Equity.US."):
            return US_EQUITY_SESSION_MODES.get(fs.session)
        if fs.symbol.startswith("Equity.HK.") and fs.session == "REGULAR":
            return "hk-equities"
    return None


def engine_gate(stats_row: dict, mode: str, min_obs: int) -> bool:
    try:
        n_obs = int(float(stats_row["n_observations"]))
    except (KeyError, ValueError):
        return False
    if n_obs < min_obs:
        return False
    if mode in ENGINE_MODE_THRESHOLDS:
        max_ros, min_hit = ENGINE_MODE_THRESHOLDS[mode]
        try:
            return (
                float(stats_row["rmse_over_spread"]) <= max_ros
                and float(stats_row["hit_rate_0.1pct"]) >= min_hit
            )
        except (KeyError, ValueError):
            return False
    return stats_row.get("pass_fail") == "pass"


def _open_minute_set(mask: pd.Series) -> set:
    return set(mask.index[mask.to_numpy()])


def activity_pct(matrix_df: pd.DataFrame, mask: pd.Series, publisher_id: int) -> float:
    open_minutes = _open_minute_set(mask)
    if not open_minutes:
        return 0.0
    pub_minutes = set(
        matrix_df.loc[matrix_df["publisher_id"] == publisher_id, "minute"]
    )
    return len(pub_minutes & open_minutes) / len(open_minutes)


def projected_worst_minute(matrix_df: pd.DataFrame, mask: pd.Series, publisher_ids) -> int:
    """Worst per-open-minute count of the given publishers (missing minute = 0)."""
    open_minutes = mask.index[mask.to_numpy()]
    if len(open_minutes) == 0:
        return 0
    sub = matrix_df[matrix_df["publisher_id"].isin(publisher_ids)]
    per_minute = sub.groupby("minute")["publisher_id"].nunique()
    counts = per_minute.reindex(open_minutes, fill_value=0)
    return int(counts.min())


def select_candidates(passers, matrix_df, mask, allowed, min_pub, target_margin):
    """Greedy best-quality-first selection until worst-minute target is met.

    passers: list of {"candidate_publisher_id": int, "sort_metric": float}.
    Returns (selected_ids_in_order, projected_worst_after).
    """
    target = min_pub + target_margin
    chosen: list = []
    current = set(allowed)
    projected = projected_worst_minute(matrix_df, mask, current)
    for row in sorted(passers, key=lambda r: r["sort_metric"]):
        if projected >= target:
            break
        pid = row["candidate_publisher_id"]
        current.add(pid)
        chosen.append(pid)
        projected = projected_worst_minute(matrix_df, mask, current)
    return chosen, projected


def candidate_dates(start_utc, end_utc, max_dates=3):
    """Most recent weekdays in [start, end), newest first."""
    dates = []
    d = (end_utc - timedelta(days=1)).date()
    while d >= start_utc.date() and len(dates) < max_dates:
        if d.weekday() <= 4:
            dates.append(d.strftime("%Y-%m-%d"))
        d -= timedelta(days=1)
    return dates


def run_engine(feed_id, date, mode, cluster, reports_dir):
    """Subprocess-run the DQ engine unless stats.csv already exists.

    Returns "ok", "skipped" (exit 2 / missing stats), or "failed".
    """
    stats_path = Path(reports_dir) / cluster / mode / str(feed_id) / date / "stats.csv"
    if stats_path.exists():
        return "ok"
    start_time, end_time = compute_times_from_mode(date, mode)
    argv = [
        sys.executable, "-m", "lazer_dq.evaluate_feed_standalone",
        "--feed-id", str(feed_id), "--date", date, "--mode", mode,
        "--cluster", cluster, "--start-time", start_time, "--end-time", end_time,
        "--output-path", str(reports_dir),
    ]
    result = subprocess.run(argv, check=False)
    if result.returncode == 0:
        return "ok"
    return "skipped" if result.returncode == 2 else "failed"


def peer_windows(mask: pd.Series, peer_days: int):
    """(start, end) UTC strings covering the last `peer_days` days of the mask."""
    open_minutes = mask.index[mask.to_numpy()]
    if len(open_minutes) == 0:
        return None
    end = open_minutes[-1] + pd.Timedelta(minutes=1)
    start = max(open_minutes[0], end - pd.Timedelta(days=peer_days))
    return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")


def fetch_aggregate(client, feed_id, start, end):
    """price_feeds per-second series; tries channels 1..3 (engine pattern)."""
    for channel in (1, 2, 3):
        df = client.query_df(
            AGGREGATE_QUERY,
            parameters={
                "feed_id": feed_id, "start": start, "end": end, "channel": channel,
            },
        )
        if len(df):
            return df
    return pd.DataFrame(columns=["ts", "price"])


def _restrict_to_mask(df: pd.DataFrame, mask: pd.Series) -> pd.DataFrame:
    if df.empty:
        return df
    ts = pd.to_datetime(df["ts"], utc=True)
    minutes = ts.dt.floor("1min")
    open_minutes = _open_minute_set(mask)
    return df[minutes.isin(open_minutes)].assign(ts=ts)


def qualify_feed(
    client, fs_list, audit_by_key, args, excluded, activity_dir
):
    """Qualify one feed's flagged sessions. Returns (candidate_rows, summary_rows, flag_rows)."""
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
    activity_dir.mkdir(parents=True, exist_ok=True)
    matrix.to_csv(activity_dir / f"feed_{feed_id}.csv.gz", index=False)

    candidate_rows, summary_rows, flag_rows = [], [], []
    peer_thresholds = PeerThresholds(
        nrmse_auto=args.peer_nrmse_auto,
        nrmse_cond=args.peer_nrmse_cond,
        min_hit_rate_pct=args.peer_hit_rate,
        min_obs=args.min_obs,
    )

    for fs in fs_list:
        audit_row = audit_by_key[(fs.feed_id, fs.session)]
        mask = open_minutes_mask(
            parse_market_schedule(fs.schedule_str), args.start_utc, args.end_utc
        )
        base = {
            "feed_id": fs.feed_id, "symbol": fs.symbol, "session": fs.session,
            "classification": audit_row["classification"],
        }

        def flag(reason, detail=""):
            flag_rows.append({**base, "reason": reason, "detail": detail})

        all_pubs = set(matrix["publisher_id"].astype(int)) if len(matrix) else set()
        candidates = sorted(all_pubs - set(fs.allowed) - excluded)
        if not candidates:
            flag("no_candidates", f"{len(all_pubs)} submitting, all allowed/excluded")
            summary_rows.append(_summary(base, fs, args, mask, matrix, [], 0, 0, 0))
            continue

        # Gate 1 — activity
        gate1 = []
        for pid in candidates:
            pct = activity_pct(matrix, mask, pid)
            candidate_rows.append(
                {**base, "candidate_publisher_id": pid, "activity_pct": round(pct, 4),
                 "gate1_pass": pct >= args.min_activity}
            )
            if pct >= args.min_activity:
                gate1.append(pid)
        if not gate1:
            flag("candidates_fail_activity", f"{len(candidates)} candidates all below {args.min_activity}")
            summary_rows.append(_summary(base, fs, args, mask, matrix, candidates, 0, 0, 0))
            continue

        # Gate 2 — quality
        mode = engine_mode_for(fs)
        passers = []
        rows_by_pid = {
            r["candidate_publisher_id"]: r
            for r in candidate_rows
            if r["feed_id"] == fs.feed_id and r["session"] == fs.session
        }
        if mode is not None:
            stats, used_date = None, None
            for date in candidate_dates(args.start_utc, args.end_utc):
                outcome = run_engine(fs.feed_id, date, mode, args.cluster, args.reports_dir)
                if outcome == "ok":
                    stats = load_stats(args.reports_dir, args.cluster, mode, fs.feed_id, date)
                    if stats:
                        used_date = date
                        break
            if stats is None:
                flag("no_benchmark_data", f"mode={mode}, no engine data in window")
                summary_rows.append(_summary(base, fs, args, mask, matrix, candidates, len(gate1), 0, 0))
                continue
            stats_by_pid = {}
            for r in stats:
                try:
                    stats_by_pid[int(float(r["publisher_id"]))] = r
                except (KeyError, ValueError):
                    continue
            for pid in gate1:
                row = rows_by_pid[pid]
                row.update({"quality_path": "engine", "engine_mode": mode, "benchmark_date": used_date})
                srow = stats_by_pid.get(pid)
                if srow is None:
                    row["gate2_pass"] = False
                    continue
                row.update(
                    {"rmse_over_spread": srow.get("rmse_over_spread"),
                     "hit_rate": srow.get("hit_rate_0.1pct"),
                     "n_obs": srow.get("n_observations"),
                     "nrmse": srow.get("nrmse")}
                )
                if engine_gate(srow, mode, args.min_obs):
                    row["gate2_pass"] = True
                    passers.append(
                        {"candidate_publisher_id": pid,
                         "sort_metric": float(srow["rmse_over_spread"])}
                    )
                else:
                    row["gate2_pass"] = False
        else:
            window = peer_windows(mask, args.peer_days)
            if window is None:
                flag("no_benchmark_data", "no open minutes in window")
                summary_rows.append(_summary(base, fs, args, mask, matrix, candidates, len(gate1), 0, 0))
                continue
            pstart, pend = window
            agg_df = fetch_aggregate(client, fs.feed_id, pstart, pend)
            agg_df = _restrict_to_mask(agg_df, mask)
            if agg_df.empty:
                flag("no_benchmark_data", "no aggregate (price_feeds) data")
                summary_rows.append(_summary(base, fs, args, mask, matrix, candidates, len(gate1), 0, 0))
                continue
            pub_all = client.query_df(
                PER_SECOND_PRICES_QUERY,
                parameters={"feed_id": fs.feed_id, "start": pstart, "end": pend,
                            "publisher_ids": list(gate1)},
            )
            pub_all = _restrict_to_mask(pub_all, mask)
            for pid in gate1:
                row = rows_by_pid[pid]
                row.update({"quality_path": "peer", "benchmark_date": f"{pstart}..{pend}"})
                pub_df = pub_all[pub_all["publisher_id"] == pid][["ts", "price"]]
                result = evaluate_peer(pub_df, agg_df[["ts", "price"]], peer_thresholds)
                row.update(
                    {"nrmse": round(result["nrmse"], 6) if result["nrmse"] == result["nrmse"] else "",
                     "hit_rate": round(result["hit_rate_pct"], 2) if result["hit_rate_pct"] == result["hit_rate_pct"] else "",
                     "n_obs": result["n_observations"],
                     "gate2_pass": result["passed"]}
                )
                if result["passed"]:
                    passers.append(
                        {"candidate_publisher_id": pid, "sort_metric": result["nrmse"]}
                    )

        if not passers:
            flag("candidates_fail_quality", f"{len(gate1)} active candidates, 0 passed quality")
            summary_rows.append(_summary(base, fs, args, mask, matrix, candidates, len(gate1), 0, 0))
            continue

        selected, projected = select_candidates(
            passers, matrix, mask, fs.allowed, fs.effective_min_pub, args.target_margin
        )
        for rank, pid in enumerate(selected, 1):
            rows_by_pid[pid]["selected"] = True
            rows_by_pid[pid]["selection_rank"] = rank
        target = fs.effective_min_pub + args.target_margin
        if projected < target:
            flag("still_below_target", f"projected worst {projected} < target {target} after adding {selected}")
        summary_rows.append(
            _summary(base, fs, args, mask, matrix, candidates, len(gate1), len(passers), len(selected), projected)
        )
    return candidate_rows, summary_rows, flag_rows


def _summary(base, fs, args, mask, matrix, candidates, n_gate1, n_gate2, n_selected, projected=None):
    before = projected_worst_minute(matrix, mask, set(fs.allowed))
    target = fs.effective_min_pub + args.target_margin
    if projected is None:
        projected = before
    return {
        **base,
        "effective_min_pub": fs.effective_min_pub,
        "target": target,
        "worst_minute_before": before,
        "n_candidates": len(candidates),
        "n_gate1": n_gate1,
        "n_gate2": n_gate2,
        "n_selected": n_selected,
        "projected_worst_after": projected,
        "met_target": projected >= target,
    }


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True)
    p.add_argument("--audit-csv", required=True)
    p.add_argument("--start-date", required=True)
    p.add_argument("--end-date", required=True)
    p.add_argument("--cluster", default="lazer-prod")
    p.add_argument("--exclude-publisher", type=int, action="append", default=[])
    p.add_argument("--min-activity", type=float, default=0.90)
    p.add_argument("--target-margin", type=int, default=2)
    p.add_argument("--peer-nrmse-auto", type=float, default=0.05)
    p.add_argument("--peer-nrmse-cond", type=float, default=0.15)
    p.add_argument("--peer-hit-rate", type=float, default=85.0)
    p.add_argument("--min-obs", type=int, default=1000)
    p.add_argument("--peer-days", type=int, default=2)
    p.add_argument("--reports-dir", default="dq_reports")
    p.add_argument("--output-dir", default="output_csv")
    p.add_argument("--publishers-md", default="publishers.md")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    args.start_utc = datetime.strptime(args.start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    args.end_utc = datetime.strptime(args.end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)

    config = json.loads(Path(args.config).read_text())
    audit = pd.read_csv(args.audit_csv)
    flagged = audit[audit["classification"].isin(["CRITICAL", "WARN"])]
    flagged_keys = {
        (int(r.feed_id), r.session): r._asdict() for r in flagged.itertuples()
    }
    print(f"{len(flagged_keys)} flagged (feed, session) pairs from {args.audit_csv}")

    excluded = load_excluded_publishers(args.publishers_md) | set(args.exclude_publisher)
    by_feed = {}
    for fs in iter_stable_sessions(config):
        if (fs.feed_id, fs.session) in flagged_keys and fs.schedule_str is not None:
            by_feed.setdefault(fs.feed_id, []).append(fs)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    activity_dir = out_dir / "min_pub_activity"

    from lib.config import get_lazer_client, load_config

    client = get_lazer_client(load_config())
    all_candidates, all_summaries, all_flags = [], [], []
    for i, (feed_id, fs_list) in enumerate(sorted(by_feed.items()), 1):
        print(f"[{i}/{len(by_feed)}] qualifying feed {feed_id} ({fs_list[0].symbol})")
        try:
            c, s, f = qualify_feed(
                client, fs_list, flagged_keys, args, excluded, activity_dir
            )
        except Exception as e:  # soft-fail per feed
            print(f"  feed {feed_id} FAILED: {e}")
            all_flags.append(
                {"feed_id": feed_id, "symbol": fs_list[0].symbol, "session": "",
                 "reason": "no_benchmark_data", "detail": f"error: {e}"}
            )
            continue
        all_candidates += c
        all_summaries += s
        all_flags += f

    for name, rows, columns in (
        ("candidates_report.csv", all_candidates, CANDIDATE_COLUMNS),
        ("qualification_summary.csv", all_summaries, SUMMARY_COLUMNS),
        ("flagged_feeds.csv", all_flags, ["feed_id", "symbol", "session", "classification", "reason", "detail"]),
    ):
        path = out_dir / name
        with open(path, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        print(f"Wrote {len(rows)} rows -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest lazer_dq/tests/test_qualify_candidates.py -v`
Expected: all PASS. Also run the full suite to catch import regressions: `python3 -m pytest lazer_dq/tests/ -v` — all PASS.

- [ ] **Step 5: Smoke-test the peer path on one real feed** (feed 1830 was CRITICAL-adjacent in exploration; crypto NAV → peer path)

```bash
python3 -m lazer_dq.audit_min_pub --config lazer_to_modify.json \
    --feed-id 1830 --start-date 2026-07-11 --end-date 2026-07-12 --workers 1
python3 -m lazer_dq.qualify_candidates --config lazer_to_modify.json \
    --audit-csv output_csv/min_pub_audit_2026-07-11_2026-07-12.csv \
    --start-date 2026-07-11 --end-date 2026-07-12
column -s, -t < output_csv/candidates_report.csv | head -12
```

Expected: candidates discovered for feed 1830 (exploration showed 6 non-allowed submitters), activity/gate columns populated, no traceback. If ClickHouse types make `Array(UInt64)` parameters fail, switch `PER_SECOND_PRICES_QUERY` to inline the id list (`AND pu.publisher_id IN (1,2,3)` via f-string of validated ints) and note it in the module docstring.

- [ ] **Step 6: Commit**

```bash
pre-commit run --files lazer_dq/qualify_candidates.py lazer_dq/tests/test_qualify_candidates.py
git add lazer_dq/qualify_candidates.py lazer_dq/tests/test_qualify_candidates.py
git commit -m "feat(lazer_dq): qualify_candidates — activity + quality gates, worst-minute selection (stage 2)"
```

---

### Task 6: Stage 3 apply + verify CLI (`lazer_dq/apply_min_pub_remediation.py`)

**Files:**

- Create: `lazer_dq/apply_min_pub_remediation.py`
- Test: `lazer_dq/tests/test_apply_min_pub_remediation.py`

**Interfaces:**

- Consumes: `candidates_report.csv`, `qualification_summary.csv`, `flagged_feeds.csv` (Task 5); `output_csv/min_pub_activity/feed_<id>.csv.gz`; `iter_stable_sessions` (Task 2); `projected_worst_minute` + mask helpers (Tasks 1/5); `tools/edit-config/edit_config.py` (subprocess); `tools/config-linter/config_linter.py` (subprocess).
- Produces:

  - CLI: `python3 -m lazer_dq.apply_min_pub_remediation --config lazer_to_modify.json [--candidates-csv output_csv/candidates_report.csv] [--summary-csv output_csv/qualification_summary.csv] [--activity-dir output_csv/min_pub_activity] [--start-date --end-date] [--apply] [--skip-linter] [--output-dir output_csv]`
  - Default is **dry-run** (edit_config dry-run diff printed, nothing written). `--apply` writes the config and then runs verification.
  - `output_csv/min_pub_remediation_spec.yaml` — the edit_config batch spec.
  - `output_csv/applied_changes.csv`: `feed_id, symbol, session, publisher_id, quality_path, selection_rank`
  - `output_csv/verification_report.csv`: `check, feed_id, session, status, detail` (checks: `static_margin`, `selected_applied`, `linter`, `projected_margin`; status `PASS`/`FAIL`/`SKIPPED`).
  - Pure functions: `build_spec(selected_df: pd.DataFrame) -> dict` (YAML-able: `{"version": 1, "operations": [{"op": "add_publisher", "publisher_id": P, "feed_id": "1,2,3"} , ...]}` — one op per (publisher, session); `session:` key included only when != REGULAR); `verify_static(config: dict, selected_df, summary_df) -> list[dict]`; `verify_projection(config, selected_df, summary_df, activity_dir, start_utc, end_utc) -> list[dict]`.
  - Exit code: 0 = dry-run OK or apply+verify all PASS; 1 = edit_config failed or any verification FAIL.

- [ ] **Step 1: Write the failing tests**

```python
# lazer_dq/tests/test_apply_min_pub_remediation.py
import pandas as pd

from lazer_dq.apply_min_pub_remediation import build_spec, verify_static


def _selected_df():
    return pd.DataFrame(
        [
            {"feed_id": 10, "symbol": "Equity.US.A/USD", "session": "REGULAR",
             "candidate_publisher_id": 7, "selected": True, "selection_rank": 1,
             "quality_path": "engine"},
            {"feed_id": 11, "symbol": "Crypto.B/USD", "session": "REGULAR",
             "candidate_publisher_id": 7, "selected": True, "selection_rank": 1,
             "quality_path": "peer"},
            {"feed_id": 10, "symbol": "Equity.US.A/USD", "session": "PRE_MARKET",
             "candidate_publisher_id": 8, "selected": True, "selection_rank": 1,
             "quality_path": "engine"},
            {"feed_id": 12, "symbol": "Crypto.C/USD", "session": "REGULAR",
             "candidate_publisher_id": 9, "selected": False, "selection_rank": "",
             "quality_path": "peer"},
        ]
    )


def test_build_spec_groups_by_publisher_and_session():
    spec = build_spec(_selected_df())
    assert spec["version"] == 1
    ops = spec["operations"]
    # publisher 7 REGULAR on feeds 10,11 -> one op; publisher 8 PRE_MARKET -> one op
    assert {
        "op": "add_publisher", "publisher_id": 7, "feed_id": "10,11"
    } in ops
    assert {
        "op": "add_publisher", "publisher_id": 8, "feed_id": "10",
        "session": "PRE_MARKET",
    } in ops
    assert len(ops) == 2  # non-selected publisher 9 excluded


def _mini_config(regular_allowed):
    return {
        "exchanges": [],
        "feeds": [
            {
                "feedId": 10,
                "symbol": "Equity.US.A/USD",
                "state": "STABLE",
                "minPublishers": 2,
                "metadata": {"asset_type": "equity"},
                "marketSchedules": [
                    {"session": "REGULAR",
                     "allowedPublisherIds": regular_allowed,
                     "marketSchedule": "UTC;O,O,O,O,O,O,O;"}
                ],
            }
        ],
    }


def test_verify_static_pass_and_fail():
    selected = pd.DataFrame(
        [{"feed_id": 10, "symbol": "Equity.US.A/USD", "session": "REGULAR",
          "candidate_publisher_id": 7, "selected": True, "selection_rank": 1,
          "quality_path": "peer"}]
    )
    summary = pd.DataFrame(
        [{"feed_id": 10, "session": "REGULAR", "target": 4, "met_target": True}]
    )
    # applied config: pubs 1,2,3 + added 7 -> allowed_count 4 >= target 4, 7 present
    ok = verify_static(_mini_config([1, 2, 3, 7]), selected, summary)
    assert all(r["status"] == "PASS" for r in ok)
    # broken config: 7 missing
    bad = verify_static(_mini_config([1, 2, 3]), selected, summary)
    assert any(
        r["check"] == "selected_applied" and r["status"] == "FAIL" for r in bad
    )
    # duplicate publisher entry -> static FAIL
    dup = verify_static(_mini_config([1, 2, 3, 7, 7]), selected, summary)
    assert any(r["check"] == "static_margin" and r["status"] == "FAIL" for r in dup)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest lazer_dq/tests/test_apply_min_pub_remediation.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

```python
# lazer_dq/apply_min_pub_remediation.py
"""Stage 3 of the min_pub pipeline: apply selected publishers and verify.

Reads Stage-2 outputs, builds a batched edit_config YAML spec, runs
tools/edit-config/edit_config.py (dry-run by default; --apply to write),
then verifies the modified config:

  1. static_margin / selected_applied — every remediated (feed, session)
     contains exactly the selected publishers, no duplicates, and reaches
     allowed_count >= target where Stage 2 said the target was met;
  2. linter — tools/config-linter/config_linter.py error count does not
     increase vs the pre-apply baseline (best-effort: SKIPPED if the linter
     rejects the new format);
  3. projected_margin — worst-minute recomputation from the Stage-2
     activity matrices with the new allowed sets.

Run (dry-run, then apply):
    python3 -m lazer_dq.apply_min_pub_remediation --config lazer_to_modify.json \
        --start-date 2026-07-06 --end-date 2026-07-13
    python3 -m lazer_dq.apply_min_pub_remediation --config lazer_to_modify.json \
        --start-date 2026-07-06 --end-date 2026-07-13 --apply
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

from lazer_dq.market_schedule import open_minutes_mask, parse_market_schedule
from lazer_dq.min_pub_common import iter_stable_sessions
from lazer_dq.qualify_candidates import projected_worst_minute

EDIT_CONFIG = Path("tools/edit-config/edit_config.py")
LINTER = Path("tools/config-linter/config_linter.py")


def build_spec(selected_df: pd.DataFrame) -> dict:
    """Batched edit_config YAML spec: one add_publisher op per (publisher, session)."""
    sel = selected_df[selected_df["selected"] == True]  # noqa: E712 (CSV bools)
    ops = []
    for (publisher_id, session), group in sorted(
        sel.groupby(["candidate_publisher_id", "session"])
    ):
        feed_ids = sorted(set(int(f) for f in group["feed_id"]))
        op = {
            "op": "add_publisher",
            "publisher_id": int(publisher_id),
            "feed_id": ",".join(str(f) for f in feed_ids),
        }
        if session != "REGULAR":
            op["session"] = session
        ops.append(op)
    return {"version": 1, "operations": ops}


def run_edit_config(config_path, spec_path, apply: bool) -> int:
    argv = [
        sys.executable, str(EDIT_CONFIG),
        "--config", str(config_path), "--from-spec", str(spec_path),
    ]
    if apply:
        argv.append("--apply")
    print(f"$ {' '.join(argv)}")
    return subprocess.run(argv, check=False).returncode


def count_linter_errors(config_path) -> int | None:
    """Linter error-line count, or None if the linter can't run on this config."""
    try:
        result = subprocess.run(
            [sys.executable, str(LINTER), "--config", str(config_path)],
            check=False, capture_output=True, text=True, timeout=300,
        )
    except Exception:
        return None
    text = result.stdout + result.stderr
    errors = [l for l in text.splitlines() if "ERROR" in l.upper()]
    if result.returncode != 0 and not errors:
        return None  # linter itself failed (e.g. old-format assumption)
    return len(errors)


def _session_allowed(config: dict) -> dict:
    """{(feed_id, session): list allowedPublisherIds} for STABLE feeds."""
    return {
        (fs.feed_id, fs.session): fs
        for fs in iter_stable_sessions(config)
    }


def verify_static(config: dict, selected_df, summary_df) -> list:
    rows = []
    sessions = _session_allowed(config)
    sel = selected_df[selected_df["selected"] == True]  # noqa: E712
    raw_lists = {
        (f["feedId"], e.get("session", "REGULAR")): e.get("allowedPublisherIds", [])
        for f in config.get("feeds", [])
        for e in f.get("marketSchedules", [])
    }
    for (feed_id, session), group in sel.groupby(["feed_id", "session"]):
        key = (int(feed_id), session)
        fs = sessions.get(key)
        raw = raw_lists.get(key, [])
        # duplicates?
        if len(raw) != len(set(raw)):
            rows.append({"check": "static_margin", "feed_id": feed_id,
                         "session": session, "status": "FAIL",
                         "detail": "duplicate publisher ids in allowed list"})
            continue
        missing = [
            int(p) for p in group["candidate_publisher_id"]
            if fs is None or int(p) not in fs.allowed
        ]
        rows.append({"check": "selected_applied", "feed_id": feed_id,
                     "session": session,
                     "status": "FAIL" if missing else "PASS",
                     "detail": f"missing {missing}" if missing else ""})
        srow = summary_df[
            (summary_df["feed_id"] == int(feed_id)) & (summary_df["session"] == session)
        ]
        if fs is not None and len(srow) and bool(srow.iloc[0]["met_target"]):
            target = int(srow.iloc[0]["target"])
            ok = len(fs.allowed) >= target
            rows.append({"check": "static_margin", "feed_id": feed_id,
                         "session": session,
                         "status": "PASS" if ok else "FAIL",
                         "detail": f"allowed {len(fs.allowed)} vs target {target}"})
    return rows


def verify_projection(config, selected_df, summary_df, activity_dir, start_utc, end_utc):
    rows = []
    sessions = _session_allowed(config)
    sel = selected_df[selected_df["selected"] == True]  # noqa: E712
    for (feed_id, session), _group in sel.groupby(["feed_id", "session"]):
        key = (int(feed_id), session)
        fs = sessions.get(key)
        matrix_path = Path(activity_dir) / f"feed_{int(feed_id)}.csv.gz"
        srow = summary_df[
            (summary_df["feed_id"] == int(feed_id)) & (summary_df["session"] == session)
        ]
        if fs is None or fs.schedule_str is None or not matrix_path.exists() or not len(srow):
            rows.append({"check": "projected_margin", "feed_id": feed_id,
                         "session": session, "status": "SKIPPED",
                         "detail": "missing session/schedule/matrix/summary"})
            continue
        matrix = pd.read_csv(matrix_path)
        matrix["minute"] = pd.to_datetime(matrix["minute"], utc=True)
        mask = open_minutes_mask(
            parse_market_schedule(fs.schedule_str), start_utc, end_utc
        )
        projected = projected_worst_minute(matrix, mask, set(fs.allowed))
        target = int(srow.iloc[0]["target"])
        met_target = bool(srow.iloc[0]["met_target"])
        ok = projected >= target or not met_target
        rows.append({"check": "projected_margin", "feed_id": feed_id,
                     "session": session,
                     "status": "PASS" if ok else "FAIL",
                     "detail": f"projected worst {projected} vs target {target}"
                               + ("" if met_target else " (below target; feed is flagged)")})
    return rows


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True)
    p.add_argument("--candidates-csv", default="output_csv/candidates_report.csv")
    p.add_argument("--summary-csv", default="output_csv/qualification_summary.csv")
    p.add_argument("--activity-dir", default="output_csv/min_pub_activity")
    p.add_argument("--start-date", required=True)
    p.add_argument("--end-date", required=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--skip-linter", action="store_true")
    p.add_argument("--output-dir", default="output_csv")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    start_utc = datetime.strptime(args.start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_utc = datetime.strptime(args.end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    candidates = pd.read_csv(args.candidates_csv)
    summary = pd.read_csv(args.summary_csv)
    spec = build_spec(candidates)
    if not spec["operations"]:
        print("Nothing selected — no operations to apply.")
        return 0
    spec_path = out_dir / "min_pub_remediation_spec.yaml"
    spec_path.write_text(yaml.safe_dump(spec, sort_keys=False))
    n_adds = int((candidates["selected"] == True).sum())  # noqa: E712
    print(f"Spec: {len(spec['operations'])} ops covering {n_adds} (feed, session, publisher) adds -> {spec_path}")

    linter_baseline = None
    if args.apply and not args.skip_linter:
        linter_baseline = count_linter_errors(args.config)

    rc = run_edit_config(args.config, spec_path, apply=args.apply)
    if rc != 0:
        print(f"edit_config exited {rc} — aborting. Config was "
              + ("possibly modified; check git diff." if args.apply else "not modified."))
        return 1
    if not args.apply:
        print("Dry-run complete. Re-run with --apply to write the config.")
        return 0

    # applied_changes.csv
    sel = candidates[candidates["selected"] == True]  # noqa: E712
    applied_path = out_dir / "applied_changes.csv"
    sel[["feed_id", "symbol", "session", "candidate_publisher_id",
         "quality_path", "selection_rank"]].rename(
        columns={"candidate_publisher_id": "publisher_id"}
    ).to_csv(applied_path, index=False)
    print(f"Applied changes -> {applied_path}")

    # Verification
    config = json.loads(Path(args.config).read_text())
    report = verify_static(config, candidates, summary)
    if args.skip_linter:
        report.append({"check": "linter", "feed_id": "", "session": "",
                       "status": "SKIPPED", "detail": "--skip-linter"})
    else:
        after = count_linter_errors(args.config)
        if linter_baseline is None or after is None:
            report.append({"check": "linter", "feed_id": "", "session": "",
                           "status": "SKIPPED",
                           "detail": "linter unavailable on this config format"})
        else:
            report.append({"check": "linter", "feed_id": "", "session": "",
                           "status": "PASS" if after <= linter_baseline else "FAIL",
                           "detail": f"errors before={linter_baseline} after={after}"})
    report += verify_projection(
        config, candidates, summary, args.activity_dir, start_utc, end_utc
    )

    report_path = out_dir / "verification_report.csv"
    with open(report_path, "w", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["check", "feed_id", "session", "status", "detail"]
        )
        writer.writeheader()
        writer.writerows(report)
    failures = [r for r in report if r["status"] == "FAIL"]
    print(f"Verification: {len(report)} checks, {len(failures)} FAIL -> {report_path}")
    for r in failures:
        print(f"  FAIL {r['check']} feed {r['feed_id']}/{r['session']}: {r['detail']}")
    print("Review `git diff` on the config plus the CSVs before committing.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest lazer_dq/tests/test_apply_min_pub_remediation.py -v`
Expected: all PASS

- [ ] **Step 5: End-to-end dry-run against a copy of the real config**

```bash
cp lazer_to_modify.json /tmp/min_pub_e2e_config.json
# Fabricate a tiny selected set from the smoke-test candidates CSV (Task 5 step 5),
# or run stage 2 for real first. Then:
python3 -m lazer_dq.apply_min_pub_remediation --config /tmp/min_pub_e2e_config.json \
    --start-date 2026-07-11 --end-date 2026-07-12
```

Expected: spec YAML written; edit_config dry-run prints its plan + diff; exit 0; `/tmp/min_pub_e2e_config.json` unchanged (`diff lazer_to_modify.json /tmp/min_pub_e2e_config.json` is empty). Then re-run with `--apply` on the **copy** and confirm `verification_report.csv` has no FAIL rows and `git diff` shows nothing (we operated on /tmp).

- [ ] **Step 6: Commit**

```bash
pre-commit run --files lazer_dq/apply_min_pub_remediation.py lazer_dq/tests/test_apply_min_pub_remediation.py
git add lazer_dq/apply_min_pub_remediation.py lazer_dq/tests/test_apply_min_pub_remediation.py
git commit -m "feat(lazer_dq): apply_min_pub_remediation — edit_config spec + verification (stage 3)"
```

---

### Task 7: Documentation + full-suite verification

**Files:**

- Create: `docs/min_pub_audit.md`
- Modify: `CLAUDE.md` (Scripts table + Key Gotchas)

**Interfaces:**

- Consumes: everything above (documents the three CLIs and their artifacts).
- Produces: user-facing docs; no code.

- [ ] **Step 1: Write `docs/min_pub_audit.md`**

Content must cover, in this order (write real prose, not placeholders):

1. **Purpose** — the two failure classes (active == min_pub, active == min_pub + 1) and the three-stage flow diagram from the spec.
2. **Stage 1 usage** — full CLI with defaults, the audit CSV column dictionary (all 17 columns from Task 3), classification semantics (CRITICAL/WARN/OK/NO_SCHEDULE/SKIPPED_DEPRECATED), `--resume`, expected multi-hour runtime at 1,645 feeds, and the hygiene report.
3. **Stage 2 usage** — candidate discovery definition (UNAUTHORIZED-rejected submitters, production keys, publishers.md exclusions), both gates with default thresholds, engine-vs-peer path selection table (the `engine_mode_for` mapping), the `--peer-days 2` bound, and all four output files.
4. **Stage 3 usage** — dry-run-default behavior, the YAML spec, the four verification checks, exit codes, and the "review git diff before committing" step.
5. **Worked example** — the three commands in sequence with a 7-day window.
6. **Caveats** — peer-benchmark circularity (aggregate as reference), `NO_SCHEDULE` rows, linter old-format SKIPPED case.

- [ ] **Step 2: Update `CLAUDE.md`**

Add three rows to the Scripts table:

```markdown
| `lazer_dq/audit_min_pub.py` | Audit STABLE feeds for active publishers at/near minPublishers (per-minute, session-aware) | `python3 -m lazer_dq.audit_min_pub --config lazer_to_modify.json` | [docs/min_pub_audit.md](docs/min_pub_audit.md) |
| `lazer_dq/qualify_candidates.py` | Qualify new publishers for flagged feeds (activity + Datascope/peer quality gates) | `python3 -m lazer_dq.qualify_candidates --config X --audit-csv Y --start-date A --end-date B` | [docs/min_pub_audit.md](docs/min_pub_audit.md) |
| `lazer_dq/apply_min_pub_remediation.py` | Apply qualified publishers via edit_config spec + verify (dry-run default) | `python3 -m lazer_dq.apply_min_pub_remediation --config X --start-date A --end-date B` | [docs/min_pub_audit.md](docs/min_pub_audit.md) |
```

Add one Key Gotchas bullet:

```markdown
- **min_pub pipeline (lazer_dq)** — `audit_min_pub` counts only `status='ACCEPTED'` updates from currently-allowed publishers; `qualify_candidates` discovers candidates from `REJECTED/UNAUTHORIZED` submissions (production keys only) and qualifies non-Datascope feeds by peer comparison against the feed's own `price_feeds` aggregate (circularity accepted by design). `marketSchedule` strings are Monday-first; sessions without one inherit from `exchanges[]` via `exchangeId`. Stage 3 only edits configs through `edit_config.py --from-spec`.
```

- [ ] **Step 3: Run the full test suite**

Run: `python3 -m pytest lazer_dq/tests/ -v`
Expected: all PASS (including the pre-existing test modules — no regressions).

- [ ] **Step 4: Commit**

```bash
pre-commit run --files docs/min_pub_audit.md CLAUDE.md
git add docs/min_pub_audit.md CLAUDE.md
git commit -m "docs: min_pub audit & remediation pipeline usage and gotchas"
```

---

## Production Run (after all tasks; operator-driven, not part of the build)

1. `python3 -m lazer_dq.audit_min_pub --config lazer_to_modify.json --workers 16` (multi-hour; resumable with `--resume`).
2. Review `min_pub_audit_*.csv` + `hygiene_report.csv`.
3. `python3 -m lazer_dq.qualify_candidates --config lazer_to_modify.json --audit-csv <that csv> --start-date <start> --end-date <end>`.
4. `python3 -m lazer_dq.apply_min_pub_remediation --config lazer_to_modify.json --start-date <start> --end-date <end>` (dry-run), review, re-run with `--apply`.
5. Review `git diff lazer_to_modify.json`, `verification_report.csv`, `flagged_feeds.csv`; commit the config change manually.
