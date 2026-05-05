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


def _remove_from_list(
    target: list[int], pub_id: int
) -> tuple[list[int], list[int]] | None:
    """Helper: remove pub_id from list. Returns (before, after) or None if NOOP."""
    before = list(target)
    if pub_id not in before:
        return None
    target[:] = [p for p in before if p != pub_id]
    return (before, list(target))


def _check_at_floor(
    feed_id: int,
    symbol: str,
    location: str,
    allowed: list[int],
    min_pub: int | None,
) -> Warning | None:
    """Warn if list length is at or below minPublishers (no headroom)."""
    if min_pub is None:
        return None
    if len(allowed) <= min_pub:
        return Warning(
            feed_id=feed_id,
            symbol=symbol,
            message=(
                f"feed {feed_id} {location}: after op, "
                f"{len(allowed)} publishers with minPublishers={min_pub} — "
                f"no headroom"
            ),
        )
    return None


@dataclass
class RemovePublisher:
    publisher_id: int
    session: str | None = None

    def apply(self, feed: dict) -> tuple[list[Change], list[Warning]]:
        changes: list[Change] = []
        warnings: list[Warning] = []
        feed_id = feed["feedId"]
        symbol = feed.get("symbol", "")

        # location, list ref, min_publishers
        targets: list[tuple[str, list[int], int | None]] = []

        if self.session is None:
            # Default: remove from everywhere (top-level + every session list).
            targets.append(
                (
                    "top_level",
                    feed.get("allowedPublisherIds", []),
                    feed.get("minPublishers"),
                )
            )
            for name in SESSION_NAMES:
                sess = get_session(feed, name)
                if sess and "allowedPublisherIds" in sess:
                    targets.append(
                        (name, sess["allowedPublisherIds"], sess.get("minPublishers"))
                    )
        elif self.session == "NONE":
            targets.append(
                (
                    "top_level",
                    feed.get("allowedPublisherIds", []),
                    feed.get("minPublishers"),
                )
            )
        elif self.session == "ALL":
            for name in SESSION_NAMES:
                sess = get_session(feed, name)
                if sess and "allowedPublisherIds" in sess:
                    targets.append(
                        (name, sess["allowedPublisherIds"], sess.get("minPublishers"))
                    )
        elif self.session in SESSION_NAMES:
            sess = get_session(feed, self.session)
            if sess is None or "allowedPublisherIds" not in sess:
                raise OpError(
                    f"feed {feed_id}: session {self.session!r} does not exist on this feed"
                )
            targets.append(
                (
                    self.session,
                    sess["allowedPublisherIds"],
                    sess.get("minPublishers"),
                )
            )
        else:
            raise OpError(f"unknown session value: {self.session!r}")

        for location, ref, min_pub in targets:
            result = _remove_from_list(ref, self.publisher_id)
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
            warn = _check_at_floor(feed_id, symbol, location, after, min_pub)
            if warn is not None:
                warnings.append(warn)

        # session=NONE: warn if publisher still in any session list
        if self.session == "NONE":
            for name in SESSION_NAMES:
                sess = get_session(feed, name)
                if sess and self.publisher_id in sess.get("allowedPublisherIds", []):
                    warnings.append(
                        Warning(
                            feed_id=feed_id,
                            symbol=symbol,
                            message=(
                                f"feed {feed_id}: publisher {self.publisher_id} "
                                f"still in session {name} but not in top-level roster"
                            ),
                        )
                    )
                    break

        return changes, warnings


def _resolve_min_pub_targets(
    feed: dict,
    session: str | None,
) -> list[tuple[str, dict, str]]:
    """Return list of (location, container, key) tuples.

    `container` is the dict that holds the field; `key` is "minPublishers".
    Used by SetMinPublishers and BumpMinPublishers.
    """
    feed_id = feed["feedId"]
    targets: list[tuple[str, dict, str]] = []

    if session is None:
        targets.append(("top_level", feed, "minPublishers"))
        if has_session_publishers(feed):
            regular = get_session(feed, "REGULAR")
            if regular is not None:
                targets.append(("REGULAR", regular, "minPublishers"))
    elif session == "NONE":
        targets.append(("top_level", feed, "minPublishers"))
    elif session == "ALL":
        if not has_session_publishers(feed):
            raise OpError(f"feed {feed_id}: session=ALL requires per-session lists")
        targets.append(("top_level", feed, "minPublishers"))
        for name in SESSION_NAMES:
            sess = get_session(feed, name)
            if sess and "allowedPublisherIds" in sess:
                targets.append((name, sess, "minPublishers"))
    elif session in SESSION_NAMES:
        sess = get_session(feed, session)
        if sess is None or "allowedPublisherIds" not in sess:
            raise OpError(
                f"feed {feed_id}: session {session!r} does not exist on this feed"
            )
        targets.append((session, sess, "minPublishers"))
    else:
        raise OpError(f"unknown session value: {session!r}")

    return targets


def _list_for_target(feed: dict, location: str) -> list[int]:
    if location == "top_level":
        return feed.get("allowedPublisherIds", [])
    sess = get_session(feed, location)
    return sess.get("allowedPublisherIds", []) if sess else []


@dataclass
class SetMinPublishers:
    value: int
    session: str | None = None

    def apply(self, feed: dict) -> tuple[list[Change], list[Warning]]:
        changes: list[Change] = []
        warnings: list[Warning] = []
        feed_id = feed["feedId"]
        symbol = feed.get("symbol", "")
        state = feed.get("state", "")

        if self.value < 1:
            raise OpError(f"minPublishers must be >= 1; got {self.value}")

        targets = _resolve_min_pub_targets(feed, self.session)

        # Before mutation: pre-validate all targets so a later failure
        # doesn't leave earlier targets partially mutated.
        for location, container, key in targets:
            allowed = _list_for_target(feed, location)
            if self.value > len(allowed):
                raise OpError(
                    f"feed {feed_id} {location}: minPublishers={self.value} "
                    f"exceeds publisher count {len(allowed)} — unsatisfiable"
                )

        for location, container, key in targets:
            allowed = _list_for_target(feed, location)
            old = container.get(key)
            if old == self.value:
                continue
            container[key] = self.value
            changes.append(
                Change(
                    feed_id=feed_id,
                    symbol=symbol,
                    location=location,
                    field="minPublishers",
                    before=old,
                    after=self.value,
                )
            )
            if self.value >= len(allowed):
                warnings.append(
                    Warning(
                        feed_id=feed_id,
                        symbol=symbol,
                        message=(
                            f"feed {feed_id} {location}: minPublishers={self.value} "
                            f"with {len(allowed)} publishers — no headroom"
                        ),
                    )
                )
            if self.value == 1 and state == "STABLE":
                warnings.append(
                    Warning(
                        feed_id=feed_id,
                        symbol=symbol,
                        message=(
                            f"feed {feed_id} {location}: minPublishers=1 on STABLE feed"
                        ),
                    )
                )

        return changes, warnings


@dataclass
class BumpMinPublishers:
    delta: int
    session: str | None = None

    def apply(self, feed: dict) -> tuple[list[Change], list[Warning]]:
        changes: list[Change] = []
        warnings: list[Warning] = []
        feed_id = feed["feedId"]
        symbol = feed.get("symbol", "")
        state = feed.get("state", "")

        targets = _resolve_min_pub_targets(feed, self.session)

        # Before mutation: pre-validate all targets so a later failure
        # doesn't leave earlier targets partially mutated.
        for location, container, key in targets:
            allowed = _list_for_target(feed, location)
            old = container.get(key, 0)
            new = max(1, old + self.delta)
            if new > len(allowed):
                raise OpError(
                    f"feed {feed_id} {location}: bumped minPublishers={new} "
                    f"exceeds publisher count {len(allowed)} — unsatisfiable"
                )

        for location, container, key in targets:
            allowed = _list_for_target(feed, location)
            old = container.get(key, 0)
            new = max(1, old + self.delta)
            if new == old:
                continue
            container[key] = new
            changes.append(
                Change(
                    feed_id=feed_id,
                    symbol=symbol,
                    location=location,
                    field="minPublishers",
                    before=old,
                    after=new,
                )
            )
            if new >= len(allowed):
                warnings.append(
                    Warning(
                        feed_id=feed_id,
                        symbol=symbol,
                        message=(
                            f"feed {feed_id} {location}: minPublishers={new} "
                            f"with {len(allowed)} publishers — no headroom"
                        ),
                    )
                )
            if new == 1 and state == "STABLE":
                warnings.append(
                    Warning(
                        feed_id=feed_id,
                        symbol=symbol,
                        message=(
                            f"feed {feed_id} {location}: minPublishers=1 on STABLE feed"
                        ),
                    )
                )

        return changes, warnings


VALID_STATES = ("STABLE", "COMING_SOON", "INACTIVE")

_STATE_WARNINGS = {
    ("STABLE", "COMING_SOON"): "regression: STABLE feed downgraded to COMING_SOON",
    ("STABLE", "INACTIVE"): "deactivation of live STABLE feed",
    ("INACTIVE", "STABLE"): "reactivation of INACTIVE feed — verify intent",
}


@dataclass
class SetState:
    value: str

    def apply(self, feed: dict) -> tuple[list[Change], list[Warning]]:
        if self.value not in VALID_STATES:
            raise OpError(
                f"invalid state {self.value!r}; must be one of {VALID_STATES}"
            )

        feed_id = feed["feedId"]
        symbol = feed.get("symbol", "")
        old = feed.get("state")

        if old == self.value:
            return [], []

        feed["state"] = self.value
        changes = [
            Change(
                feed_id=feed_id,
                symbol=symbol,
                location="top_level",
                field="state",
                before=old,
                after=self.value,
            )
        ]
        warnings: list[Warning] = []
        msg = _STATE_WARNINGS.get((old, self.value))
        if msg:
            warnings.append(
                Warning(
                    feed_id=feed_id,
                    symbol=symbol,
                    message=f"feed {feed_id}: {msg}",
                )
            )
        return changes, warnings
