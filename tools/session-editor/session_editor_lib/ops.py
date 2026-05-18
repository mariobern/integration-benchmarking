"""Session add/remove operations on after.json feed dicts.

Pure data operations: mutate a feed dict in place (or return None to skip).
The editor module orchestrates selection, simulation, and serialization.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from .feed_filter import find_regular, find_session, is_us_equity
from .templates import (
    ADDABLE_SESSIONS,
    CANONICAL_ORDER,
    SCHEDULE_BY_SESSION,
    VALID_SESSIONS,
    overnight_identifier,
)


# ---- exceptions --------------------------------------------------------------


class SessionOpError(ValueError):
    """Raised when an op cannot be applied to a feed (caller decides skip vs fail)."""


# ---- result type -------------------------------------------------------------


@dataclass
class OpOutcome:
    feed_id: int
    symbol: str
    session: str
    action: str  # "added" | "removed" | "skipped"
    reason: str = ""


# ---- ops ---------------------------------------------------------------------


@dataclass
class AddSession:
    session: str
    # Default 100 is a deliberate "not ready" sentinel; see
    # docs/superpowers/specs/2026-05-18-session-editor-design.md for rationale.
    min_publishers: int = 100
    force: bool = False

    def __post_init__(self) -> None:
        if self.session not in ADDABLE_SESSIONS:
            raise ValueError(
                f"AddSession: {self.session!r} is not addable "
                f"(must be one of {sorted(ADDABLE_SESSIONS)})"
            )
        if self.min_publishers < 1:
            raise ValueError("min_publishers must be >= 1")

    def apply(self, feed: dict[str, Any]) -> OpOutcome:
        feed_id = feed.get("feedId", -1)
        symbol = feed.get("symbol", "")

        if not self.force and not is_us_equity(feed):
            return OpOutcome(
                feed_id,
                symbol,
                self.session,
                "skipped",
                "not a US-equity feed (use --force to override)",
            )

        if find_session(feed, self.session) is not None:
            return OpOutcome(
                feed_id,
                symbol,
                self.session,
                "skipped",
                "session already present",
            )

        regular = find_regular(feed)
        if regular is None:
            return OpOutcome(
                feed_id,
                symbol,
                self.session,
                "skipped",
                "no REGULAR session to derive benchmarkMapping from",
            )

        new_entry = _build_session_entry(
            session=self.session,
            min_publishers=self.min_publishers,
            regular=regular,
        )
        _insert_canonical(feed.setdefault("marketSchedules", []), new_entry)
        return OpOutcome(feed_id, symbol, self.session, "added")


@dataclass
class RemoveSession:
    session: str
    force: bool = False

    def __post_init__(self) -> None:
        if self.session not in VALID_SESSIONS:
            raise ValueError(
                f"RemoveSession: {self.session!r} is not a valid session "
                f"(must be one of {sorted(VALID_SESSIONS)})"
            )

    def apply(self, feed: dict[str, Any]) -> OpOutcome:
        feed_id = feed.get("feedId", -1)
        symbol = feed.get("symbol", "")

        if not self.force and not is_us_equity(feed):
            return OpOutcome(
                feed_id,
                symbol,
                self.session,
                "skipped",
                "not a US-equity feed (use --force to override)",
            )

        if self.session == "REGULAR" and not self.force:
            return OpOutcome(
                feed_id,
                symbol,
                self.session,
                "skipped",
                "refusing to remove REGULAR without --force",
            )

        schedules = feed.get("marketSchedules", [])
        for i, entry in enumerate(schedules):
            if entry.get("session") == self.session:
                schedules.pop(i)
                return OpOutcome(feed_id, symbol, self.session, "removed")

        return OpOutcome(
            feed_id, symbol, self.session, "skipped", "session not present"
        )


# ---- internals ---------------------------------------------------------------


def _build_session_entry(
    *, session: str, min_publishers: int, regular: dict[str, Any]
) -> dict[str, Any]:
    """Construct a new session dict using REGULAR as the benchmarkMapping source."""
    entry: dict[str, Any] = {
        "allowedPublisherIds": [],
        "marketSchedule": SCHEDULE_BY_SESSION[session],
        "minPublishers": min_publishers,
        "session": session,
    }
    benchmark = copy.deepcopy(regular.get("benchmarkMapping"))
    if benchmark is not None:
        if session == "OVER_NIGHT":
            benchmark = _rewrite_to_overnight(benchmark)
        entry["benchmarkMapping"] = benchmark
    # Keep canonical key ordering: alphabetic, matching the rest of after.json.
    return dict(sorted(entry.items()))


def _rewrite_to_overnight(mapping: dict[str, Any]) -> dict[str, Any]:
    """Rewrite every RIC identifier to the .BLUE form."""
    for _vendor, vendor_block in mapping.items():
        for ident in vendor_block.get("identifiers", []):
            ident["identifier"] = overnight_identifier(ident["identifier"])
    return mapping


def _insert_canonical(
    schedules: list[dict[str, Any]], new_entry: dict[str, Any]
) -> None:
    """Insert new_entry into schedules at the canonical position."""
    target_idx = CANONICAL_ORDER.index(new_entry["session"])
    insert_at = len(schedules)
    for i, entry in enumerate(schedules):
        try:
            entry_idx = CANONICAL_ORDER.index(entry.get("session", ""))
        except ValueError:
            entry_idx = len(CANONICAL_ORDER)
        if entry_idx > target_idx:
            insert_at = i
            break
    schedules.insert(insert_at, new_entry)
