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

# Session-level minPublishers is a us-equities-only concept in the new config
# format; every other asset class takes minPublishers at the feed level only.
US_EQUITY_SYMBOL_PREFIX = "Equity.US."


@dataclass(frozen=True)
class ExchangeInfo:
    """A resolved entry from the config's top-level `exchanges[]` array.

    `sessions` maps a session name (REGULAR/PRE_MARKET/...) to its
    `marketSchedule` string — the calendar a feed inherits when it carries
    this exchange's id.
    """

    exchange_id: int
    name: str
    asset_class: str
    sessions: dict[str, str]


def build_exchanges_by_id(exchanges: list[dict]) -> dict[int, ExchangeInfo]:
    """Index the raw `exchanges[]` list by exchangeId. The array is sparse
    (some ids are not yet defined); only present ids appear in the map."""
    out: dict[int, ExchangeInfo] = {}
    for ex in exchanges:
        eid = ex.get("exchangeId")
        if eid is None:
            continue
        sessions: dict[str, str] = {}
        for s in ex.get("sessions", []):
            name = s.get("session")
            sched = s.get("marketSchedule")
            if name is not None and sched is not None:
                sessions[name] = sched
        out[eid] = ExchangeInfo(
            exchange_id=eid,
            name=ex.get("name", ""),
            asset_class=ex.get("assetClass", ""),
            sessions=sessions,
        )
    return out


def asset_class_matches(exchange_asset_class: str, feed_asset_type: str) -> bool:
    """True if the exchange's assetClass plausibly matches the feed's
    asset_type. Blanks on either side are treated as a match (nothing to
    compare -> don't warn). Comparison strips the `EXCHANGE_ASSET_CLASS_`
    prefix and lowercases, so `EXCHANGE_ASSET_CLASS_EQUITY` matches `equity`.
    """
    if not exchange_asset_class or not feed_asset_type:
        return True
    prefix = "EXCHANGE_ASSET_CLASS_"
    token = exchange_asset_class
    if token.startswith(prefix):
        token = token[len(prefix) :]
    return token.lower() == feed_asset_type.lower()


@dataclass(frozen=True)
class Change:
    """One atomic edit to a feed."""

    feed_id: int
    symbol: str
    location: str  # "top_level", a SESSION_NAME, or "datascope_ric_identifier"
    field: str  # "allowedPublisherIds", "minPublishers", "state", "identifier"
    before: Any
    after: Any
    index: int | None = None  # for list-positional fields (e.g. ric identifier slot)


@dataclass(frozen=True)
class Warning:
    feed_id: int
    symbol: str
    message: str


class OpError(Exception):
    """Raised by ops on validation errors that should block apply."""


def get_session(feed: dict, session_name: str) -> dict | None:
    """Return the session entry with the given name, or None."""
    for s in feed.get("marketSchedules", []):
        if s.get("session") == session_name:
            return s
    return None


def is_us_equity(feed: dict) -> bool:
    """True for feeds that may carry session-level minPublishers."""
    return feed.get("symbol", "").startswith(US_EQUITY_SYMBOL_PREFIX)


def _session_publisher_union(feed: dict) -> list[int]:
    """Union of every session's allowedPublisherIds — the effective feed
    roster, now that no feed-level allowedPublisherIds exists."""
    ids: set[int] = set()
    for s in feed.get("marketSchedules", []):
        ids.update(s.get("allowedPublisherIds") or [])
    return sorted(ids)


def _resolve_publisher_sessions(feed: dict, session: str | None) -> list[str]:
    """Session names a publisher op targets.

    Publisher lists live ONLY in marketSchedules entries in the new config
    format; there is no feed-level roster, so session=NONE is invalid here.
    """
    feed_id = feed["feedId"]
    if session is None:
        return ["REGULAR"]
    if session == "ALL":
        return [s["session"] for s in feed.get("marketSchedules", [])]
    if session == "NONE":
        raise OpError(
            f"feed {feed_id}: session=NONE is invalid for publisher ops — "
            f"the new config format has no feed-level allowedPublisherIds"
        )
    if session in SESSION_NAMES:
        return [session]
    raise OpError(f"unknown session value: {session!r}")


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
    session: str | None = None  # None|REGULAR|PRE_MARKET|POST_MARKET|OVER_NIGHT|ALL

    def apply(self, feed: dict) -> tuple[list[Change], list[Warning]]:
        changes: list[Change] = []
        feed_id = feed["feedId"]
        symbol = feed.get("symbol", "")

        for name in _resolve_publisher_sessions(feed, self.session):
            sess = get_session(feed, name)
            if sess is None:
                raise OpError(
                    f"feed {feed_id}: session {name!r} does not exist on this feed"
                )
            if "allowedPublisherIds" not in sess or sess["allowedPublisherIds"] is None:
                # Missing (or null) list: create it. before=None marks
                # "field absent — insert" for the diff and the text applier.
                sess["allowedPublisherIds"] = [self.publisher_id]
                changes.append(
                    Change(
                        feed_id=feed_id,
                        symbol=symbol,
                        location=name,
                        field="allowedPublisherIds",
                        before=None,
                        after=[self.publisher_id],
                    )
                )
                continue
            result = _add_publisher_to_list(
                sess["allowedPublisherIds"], self.publisher_id
            )
            if result is None:
                continue
            before, after = result
            changes.append(
                Change(
                    feed_id=feed_id,
                    symbol=symbol,
                    location=name,
                    field="allowedPublisherIds",
                    before=before,
                    after=after,
                )
            )

        return changes, []


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

        names = _resolve_publisher_sessions(feed, self.session)
        explicit = self.session in SESSION_NAMES
        feed_min = feed.get("minPublishers")

        for name in names:
            sess = get_session(feed, name)
            if sess is None:
                if explicit:
                    raise OpError(
                        f"feed {feed_id}: session {name!r} does not exist "
                        f"on this feed"
                    )
                continue
            ref = sess.get("allowedPublisherIds")
            if not ref:
                continue  # nothing to remove from a missing/empty list
            result = _remove_from_list(ref, self.publisher_id)
            if result is None:
                continue
            before, after = result
            changes.append(
                Change(
                    feed_id=feed_id,
                    symbol=symbol,
                    location=name,
                    field="allowedPublisherIds",
                    before=before,
                    after=after,
                )
            )
            # Headroom check: session minPublishers when present, else the
            # feed-level value (still enforced in the new format).
            warn = _check_at_floor(
                feed_id, symbol, name, after, sess.get("minPublishers", feed_min)
            )
            if warn is not None:
                warnings.append(warn)

        return changes, warnings


def _resolve_min_pub_targets(
    feed: dict,
    session: str | None,
) -> list[tuple[str, dict, str]]:
    """Return list of (location, container, key) tuples for minPublishers ops.

    Feed-level minPublishers exists on every feed and stays editable.
    Session-level minPublishers is a us-equities-only concept: non-US feeds
    never get session targets, and explicitly asking for one is an error.
    Session targets are limited to entries that already have a publisher list
    (a publisher-less session has nothing to satisfy a floor against).
    """
    feed_id = feed["feedId"]
    us = is_us_equity(feed)
    targets: list[tuple[str, dict, str]] = []

    if session is None:
        targets.append(("top_level", feed, "minPublishers"))
        if us:
            regular = get_session(feed, "REGULAR")
            if regular is not None and regular.get("allowedPublisherIds"):
                targets.append(("REGULAR", regular, "minPublishers"))
    elif session == "NONE":
        targets.append(("top_level", feed, "minPublishers"))
    elif session == "ALL":
        targets.append(("top_level", feed, "minPublishers"))
        if us:
            for s in feed.get("marketSchedules", []):
                if s.get("allowedPublisherIds"):
                    targets.append((s["session"], s, "minPublishers"))
    elif session in SESSION_NAMES:
        if not us:
            raise OpError(
                f"feed {feed_id} ({feed.get('symbol', '')}): session-level "
                f"minPublishers is a us-equities-only concept; this feed "
                f"takes minPublishers at the feed level (omit --session or "
                f"use --session NONE)"
            )
        sess = get_session(feed, session)
        if sess is None:
            raise OpError(
                f"feed {feed_id}: session {session!r} does not exist on this feed"
            )
        targets.append((session, sess, "minPublishers"))
    else:
        raise OpError(f"unknown session value: {session!r}")

    return targets


def _list_for_target(feed: dict, location: str) -> list[int]:
    if location == "top_level":
        # No feed-level roster exists in the new format; validate against the
        # union of all session lists.
        return _session_publisher_union(feed)
    sess = get_session(feed, location)
    return (sess.get("allowedPublisherIds") or []) if sess else []


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
            old = container.get(key)
            new = max(1, (old or 0) + self.delta)
            if new > len(allowed):
                raise OpError(
                    f"feed {feed_id} {location}: bumped minPublishers={new} "
                    f"exceeds publisher count {len(allowed)} — unsatisfiable"
                )

        for location, container, key in targets:
            allowed = _list_for_target(feed, location)
            old = container.get(key)
            new = max(1, (old or 0) + self.delta)
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


@dataclass
class SetRicMapping:
    """Fill empty `datascope_ric.identifiers[].identifier` slots from a CSV-derived mapping.

    `prefix_to_ric` maps a feed-symbol prefix (e.g. `"Equity.HK.0700-HK/"`)
    to the RIC string to write (e.g. `"0700.HK"`).

    Per-slot semantics:
      - empty string  -> Change (fill with the RIC).
      - any non-empty -> Warning (skipped, no overwrite).

    Per-feed semantics:
      - feed.symbol does not match any prefix -> silent skip (no warnings).
      - feed has no datascope_ric.identifiers[] slots -> Warning.
    """

    prefix_to_ric: dict[str, str]

    def apply(self, feed: dict) -> tuple[list[Change], list[Warning]]:
        feed_id = feed["feedId"]
        symbol = feed.get("symbol", "")

        ric = None
        for prefix, candidate in self.prefix_to_ric.items():
            if symbol.startswith(prefix):
                ric = candidate
                break
        if ric is None:
            return [], []

        slots: list[dict] = []
        for schedule in feed.get("marketSchedules", []):
            bm = schedule.get("benchmarkMapping", {})
            ds = bm.get("datascope_ric", {})
            for ident in ds.get("identifiers", []) or []:
                if isinstance(ident, dict) and "identifier" in ident:
                    slots.append(ident)

        if not slots:
            return [], [
                Warning(
                    feed_id=feed_id,
                    symbol=symbol,
                    message=(
                        f"feed {feed_id}: no datascope_ric identifier slots — skipped"
                    ),
                )
            ]

        changes: list[Change] = []
        warnings: list[Warning] = []
        for i, slot in enumerate(slots):
            current = slot["identifier"]
            if current == "":
                changes.append(
                    Change(
                        feed_id=feed_id,
                        symbol=symbol,
                        location="datascope_ric_identifier",
                        field="identifier",
                        before="",
                        after=ric,
                        index=i,
                    )
                )
                slot["identifier"] = ric
            else:
                warnings.append(
                    Warning(
                        feed_id=feed_id,
                        symbol=symbol,
                        message=(
                            f"feed {feed_id}: identifier slot {i} already populated "
                            f"({current!r}) — skipped"
                        ),
                    )
                )
        return changes, warnings


@dataclass(frozen=True)
class ResolvedRic:
    """A feed's resolved Datascope RICs, consumed by SetRicFromResolver.

    `day_ric` applies to REGULAR/PRE_MARKET/POST_MARKET sessions; `overnight_ric`
    (the `TICKER.BLUE` form) applies to OVER_NIGHT. An empty `day_ric` means the
    resolver could not derive a RIC for the feed.
    """

    day_ric: str
    overnight_ric: str
    confidence: str = ""
    warnings: tuple[str, ...] = ()


@dataclass
class SetRicFromResolver:
    """Overwrite `datascope_ric` identifier slots from pre-resolved RICs.

    `rics` maps feedId -> ResolvedRic. Per identifier slot the target value is
    `overnight_ric` when the slot's session is OVER_NIGHT, else `day_ric`. Slots
    already equal to the target are NOOPs; differing slots (empty, bare, or
    wrong) are overwritten. Overwriting a non-empty value also emits a Warning so
    the dry-run diff surfaces churn (e.g. CTRA.N -> CTRA.K). Reuses the
    `datascope_ric_identifier` Change location, so the text-surgery applier needs
    no changes.

    Per-feed semantics:
      - feedId absent from `rics`, or `day_ric` empty -> Warning (unresolved).
      - feed has no datascope_ric identifier slots -> Warning (cannot insert).
    """

    rics: dict[int, ResolvedRic]

    def apply(self, feed: dict) -> tuple[list[Change], list[Warning]]:
        feed_id = feed["feedId"]
        symbol = feed.get("symbol", "")

        resolved = self.rics.get(feed_id)
        if resolved is None or not resolved.day_ric:
            return [], [
                Warning(
                    feed_id=feed_id,
                    symbol=symbol,
                    message=f"feed {feed_id}: no RIC resolved — skipped",
                )
            ]

        # (session, identifier-dict) pairs in document order. Order matches
        # config_text_surgery.find_ric_identifier_spans, so Change.index lines up.
        slots: list[tuple[str, dict]] = []
        for schedule in feed.get("marketSchedules", []):
            session = schedule.get("session", "")
            bm = schedule.get("benchmarkMapping", {})
            ds = bm.get("datascope_ric", {})
            for ident in ds.get("identifiers", []) or []:
                if isinstance(ident, dict) and "identifier" in ident:
                    slots.append((session, ident))

        if not slots:
            return [], [
                Warning(
                    feed_id=feed_id,
                    symbol=symbol,
                    message=(
                        f"feed {feed_id}: no datascope_ric identifier slots — skipped"
                    ),
                )
            ]

        changes: list[Change] = []
        warnings: list[Warning] = []
        for i, (session, slot) in enumerate(slots):
            target = (
                resolved.overnight_ric if session == "OVER_NIGHT" else resolved.day_ric
            )
            current = slot["identifier"]
            if current == target:
                continue
            changes.append(
                Change(
                    feed_id=feed_id,
                    symbol=symbol,
                    location="datascope_ric_identifier",
                    field="identifier",
                    before=current,
                    after=target,
                    index=i,
                )
            )
            slot["identifier"] = target
            if current != "":
                warnings.append(
                    Warning(
                        feed_id=feed_id,
                        symbol=symbol,
                        message=(
                            f"feed {feed_id}: overwriting identifier slot {i} "
                            f"({current!r} -> {target!r})"
                        ),
                    )
                )
        return changes, warnings


@dataclass
class AddExchangeId:
    """Assign `exchange_id` to a feed and strip each session's now-redundant
    `marketSchedule` string (the feed inherits the exchange's calendar).

    `exchange` is the pre-resolved ExchangeInfo for `exchange_id`, captured at
    construction time (the id is fixed per invocation).
    """

    exchange_id: int
    exchange: ExchangeInfo

    def apply(self, feed: dict) -> tuple[list[Change], list[Warning]]:
        feed_id = feed["feedId"]
        symbol = feed.get("symbol", "")
        changes: list[Change] = []
        warnings: list[Warning] = []
        schedules = feed.get("marketSchedules", [])

        # 1. Session coverage (hard error): every feed session must exist on
        #    the exchange, else stripping its string leaves nothing to inherit.
        uncovered = [
            s.get("session")
            for s in schedules
            if s.get("session") not in self.exchange.sessions
        ]
        if uncovered:
            raise OpError(
                f"feed {feed_id}: exchange {self.exchange_id} "
                f"({self.exchange.name!r}) does not define session(s) "
                f"{uncovered} that this feed has — cannot inherit a schedule"
            )

        # 2. Asset-class check (warning only).
        feed_asset = feed.get("metadata", {}).get("asset_type", "")
        if not asset_class_matches(self.exchange.asset_class, feed_asset):
            warnings.append(
                Warning(
                    feed_id=feed_id,
                    symbol=symbol,
                    message=(
                        f"feed {feed_id}: asset_type {feed_asset!r} does not "
                        f"match exchange {self.exchange_id} assetClass "
                        f"{self.exchange.asset_class!r}"
                    ),
                )
            )

        # 3. exchangeId field change (+ reassignment warning).
        current = feed.get("exchangeId")
        if current != self.exchange_id:
            if current is not None:
                warnings.append(
                    Warning(
                        feed_id=feed_id,
                        symbol=symbol,
                        message=(
                            f"feed {feed_id}: reassigning exchangeId "
                            f"{current} -> {self.exchange_id}"
                        ),
                    )
                )
            changes.append(
                Change(
                    feed_id=feed_id,
                    symbol=symbol,
                    location="top_level",
                    field="exchangeId",
                    before=current,
                    after=self.exchange_id,
                )
            )
            feed["exchangeId"] = self.exchange_id

        # 4. Strip per-session marketSchedule strings (inheritance).
        for s in schedules:
            if "marketSchedule" in s:
                changes.append(
                    Change(
                        feed_id=feed_id,
                        symbol=symbol,
                        location=s["session"],
                        field="marketSchedule",
                        before=s["marketSchedule"],
                        after=None,
                    )
                )
                del s["marketSchedule"]

        return changes, warnings


@dataclass
class RemoveExchangeId:
    """Remove a feed's `exchangeId` and restore each session's
    `marketSchedule` string from that exchange's definition.

    `exchanges_by_id` is the whole map because different feeds in a batch may
    reference different exchanges; the schedule to restore comes from the
    feed's current id.
    """

    exchanges_by_id: dict[int, ExchangeInfo]

    def apply(self, feed: dict) -> tuple[list[Change], list[Warning]]:
        feed_id = feed["feedId"]
        symbol = feed.get("symbol", "")
        warnings: list[Warning] = []

        current = feed.get("exchangeId")
        if current is None:
            warnings.append(
                Warning(
                    feed_id=feed_id,
                    symbol=symbol,
                    message=f"feed {feed_id}: no exchangeId to remove",
                )
            )
            return [], warnings

        exchange = self.exchanges_by_id.get(current)
        if exchange is None:
            raise OpError(
                f"feed {feed_id}: current exchangeId {current} is not defined "
                f"in exchanges[] — cannot restore schedules"
            )

        schedules = feed.get("marketSchedules", [])
        uncovered = [
            s.get("session")
            for s in schedules
            if s.get("session") not in exchange.sessions
        ]
        if uncovered:
            raise OpError(
                f"feed {feed_id}: exchange {current} ({exchange.name!r}) does "
                f"not define session(s) {uncovered} — cannot restore a schedule"
            )

        changes: list[Change] = [
            Change(
                feed_id=feed_id,
                symbol=symbol,
                location="top_level",
                field="exchangeId",
                before=current,
                after=None,
            )
        ]
        del feed["exchangeId"]

        for s in schedules:
            if "marketSchedule" not in s:
                sched = exchange.sessions[s["session"]]
                changes.append(
                    Change(
                        feed_id=feed_id,
                        symbol=symbol,
                        location=s["session"],
                        field="marketSchedule",
                        before=None,
                        after=sched,
                    )
                )
                s["marketSchedule"] = sched

        return changes, warnings


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
