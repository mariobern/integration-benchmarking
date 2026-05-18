"""Eligibility predicate for US-equity feeds."""

from __future__ import annotations

from typing import Any


def is_us_equity(feed: dict[str, Any]) -> bool:
    """Return True if the feed is a US-equity cash-equity feed."""
    symbol = feed.get("symbol", "")
    if not symbol.startswith("Equity.US."):
        return False
    asset_type = feed.get("metadata", {}).get("asset_type")
    return asset_type == "equity"


def find_session(feed: dict[str, Any], session: str) -> dict[str, Any] | None:
    """Return the session entry for `session`, or None if absent."""
    for entry in feed.get("marketSchedules", []):
        if entry.get("session") == session:
            return entry
    return None


def find_regular(feed: dict[str, Any]) -> dict[str, Any] | None:
    return find_session(feed, "REGULAR")
