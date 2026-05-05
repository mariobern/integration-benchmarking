"""Operation classes for surgical edits to after.json.

Each Op takes a parsed feed dict and mutates it in place, returning a
list of Change records describing what was modified and a list of
Warning records for soft guardrails. Errors raise OpError.

Changes describe (feed_id, location, field, before, after) tuples.
The orchestrator applies them to the raw JSON text using config_text_surgery.
"""

from dataclasses import dataclass
from typing import Any


SESSION_NAMES: tuple[str, ...] = ("REGULAR", "PRE_MARKET", "POST_MARKET", "OVER_NIGHT")


@dataclass(frozen=True)
class Change:
    """One atomic edit to a feed."""

    feed_id: int
    symbol: str
    location: str  # "top_level" or one of SESSION_NAMES
    field: str  # "allowedPublisherIds", "minPublishers", "state"
    before: Any
    after: Any


@dataclass(frozen=True)
class Warning:
    feed_id: int
    symbol: str
    message: str


class OpError(Exception):
    """Raised by ops on validation errors that should block apply."""


def has_session_publishers(feed: dict) -> bool:
    """True if any marketSchedule entry has an `allowedPublisherIds` field."""
    return any("allowedPublisherIds" in s for s in feed.get("marketSchedules", []))


def get_session(feed: dict, session_name: str) -> dict | None:
    """Return the session entry with the given name, or None."""
    for s in feed.get("marketSchedules", []):
        if s.get("session") == session_name:
            return s
    return None
