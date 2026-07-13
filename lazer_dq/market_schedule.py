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
    hh = int(token[:2])
    mm = int(token[2:])
    if mm > 59:
        raise ValueError(f"bad HHMM token: {token!r}")
    minutes = hh * 60 + mm
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
        start = _parse_hhmm(start_s)
        # Handle 0000 at end of range as end-of-day (1440 minutes)
        if end_s == "0000":
            end = 1440
        else:
            end = _parse_hhmm(end_s)
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
            mm = int(mmdd[:2])
            dd = int(mmdd[2:])
            if not (1 <= mm <= 12) or not (1 <= dd <= 31):
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


def build_exchanges_by_id(config: dict) -> dict[int, dict]:
    return {
        ex["exchangeId"]: ex for ex in config.get("exchanges", []) if "exchangeId" in ex
    }


def resolve_schedule_string(
    feed: dict, session_entry: dict, exchanges_by_id: dict
) -> str | None:
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
