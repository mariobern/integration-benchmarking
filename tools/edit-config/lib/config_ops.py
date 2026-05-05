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


def _add_publisher_to_list(
    target: list[int], pub_id: int
) -> tuple[list[int], list[int]] | None:
    """Helper: dedupe + sort + add. Returns (before, after) or None if NOOP."""
    before = list(target)
    if pub_id in before:
        merged = sorted(set(before))
        if merged == before:
            return None  # already present and sorted -> NOOP
        target[:] = merged
        return (before, merged)
    merged = sorted(set(before) | {pub_id})
    target[:] = merged
    return (before, merged)


@dataclass
class AddPublisher:
    publisher_id: int
    session: str | None = (
        None  # None|REGULAR|PRE_MARKET|POST_MARKET|OVER_NIGHT|ALL|NONE
    )

    def apply(self, feed: dict) -> tuple[list[Change], list[Warning]]:
        changes: list[Change] = []
        warnings: list[Warning] = []
        feed_id = feed["feedId"]
        symbol = feed.get("symbol", "")

        # Determine which lists to touch.
        targets: list[tuple[str, list[int]]] = []  # (location, list ref)

        if self.session is None:
            # Default scope
            targets.append(("top_level", feed.setdefault("allowedPublisherIds", [])))
            if has_session_publishers(feed):
                regular = get_session(feed, "REGULAR")
                if regular is not None and "allowedPublisherIds" in regular:
                    targets.append(("REGULAR", regular["allowedPublisherIds"]))
        elif self.session == "NONE":
            targets.append(("top_level", feed.setdefault("allowedPublisherIds", [])))
        elif self.session == "ALL":
            if not has_session_publishers(feed):
                raise OpError(
                    f"feed {feed_id}: session=ALL requires per-session publisher lists; "
                    f"feed has no per-session lists"
                )
            targets.append(("top_level", feed.setdefault("allowedPublisherIds", [])))
            for name in SESSION_NAMES:
                sess = get_session(feed, name)
                if sess is not None and "allowedPublisherIds" in sess:
                    targets.append((name, sess["allowedPublisherIds"]))
        elif self.session in SESSION_NAMES:
            sess = get_session(feed, self.session)
            if sess is None or "allowedPublisherIds" not in sess:
                raise OpError(
                    f"feed {feed_id}: session {self.session!r} does not exist on this feed"
                )
            targets.append(("top_level", feed.setdefault("allowedPublisherIds", [])))
            targets.append((self.session, sess["allowedPublisherIds"]))
        else:
            raise OpError(f"unknown session value: {self.session!r}")

        for location, ref in targets:
            result = _add_publisher_to_list(ref, self.publisher_id)
            if result is None:
                continue
            before, after = result
            changes.append(
                Change(
                    feed_id=feed_id,
                    symbol=symbol,
                    location=location,
                    field="allowedPublisherIds",
                    before=before,
                    after=after,
                )
            )

        return changes, warnings
