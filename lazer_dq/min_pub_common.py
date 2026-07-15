"""Config introspection shared by the min_pub audit/remediation pipeline.

Yields per-(feed, session) audit units from a new-format (session-only
publishers) Lazer config, and performs the static hygiene scan.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

import pandas as pd

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
                effective_min_pub=entry.get("minPublishers", feed.get("minPublishers")),
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
