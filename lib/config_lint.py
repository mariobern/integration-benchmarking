"""Config linter rules for after.json validation.

Validates feed definitions, publisher references, schedule consistency,
and business rules. Pure stdlib — no external dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class LintFinding:
    """A single lint finding."""

    rule_id: str
    severity: str  # "ERROR" or "WARNING"
    message: str
    feed_id: Optional[int]
    symbol: Optional[str]


def check_duplicates(feeds: list[dict]) -> list[LintFinding]:
    """E001: duplicate feedId, E002: duplicate symbol (STABLE/COMING_SOON)."""
    findings: list[LintFinding] = []

    # E001: duplicate feedId (all feeds)
    id_counts: dict[int, list[int]] = {}
    for idx, feed in enumerate(feeds):
        fid = feed.get("feedId")
        if fid is not None:
            id_counts.setdefault(fid, []).append(idx)

    for fid, indices in id_counts.items():
        if len(indices) > 1:
            locs = ", ".join(f"feeds[{i}]" for i in indices)
            findings.append(
                LintFinding(
                    rule_id="E001",
                    severity="ERROR",
                    message=f"feedId {fid} is duplicated ({locs})",
                    feed_id=fid,
                    symbol=None,
                )
            )

    # E002: duplicate symbol within STABLE/COMING_SOON
    active_symbols: dict[str, list[dict]] = {}
    for feed in feeds:
        state = feed.get("state", "")
        if state in ("STABLE", "COMING_SOON"):
            sym = feed.get("symbol", "")
            active_symbols.setdefault(sym, []).append(feed)

    for sym, dupes in active_symbols.items():
        if len(dupes) > 1:
            ids = [str(f.get("feedId", "?")) for f in dupes]
            findings.append(
                LintFinding(
                    rule_id="E002",
                    severity="ERROR",
                    message=f"symbol '{sym}' duplicated in STABLE/COMING_SOON feeds (feedIds: {', '.join(ids)})",
                    feed_id=dupes[0].get("feedId"),
                    symbol=sym,
                )
            )

    return findings


# Required top-level fields on every feed
_REQUIRED_FIELDS = ("feedId", "symbol", "state", "kind")


def check_schema(feeds: list[dict]) -> list[LintFinding]:
    """E007: missing required fields."""
    findings: list[LintFinding] = []

    for feed in feeds:
        fid = feed.get("feedId")
        sym = feed.get("symbol")
        missing = [f for f in _REQUIRED_FIELDS if f not in feed]

        # Check metadata.asset_type separately
        metadata = feed.get("metadata")
        if metadata is None or "asset_type" not in metadata:
            missing.append("metadata.asset_type")

        if missing:
            findings.append(
                LintFinding(
                    rule_id="E007",
                    severity="ERROR",
                    message=f"missing required fields: {', '.join(missing)}",
                    feed_id=fid,
                    symbol=sym,
                )
            )

    return findings


# Asset types exempt from E004/W005 (single-source feeds)
_EXEMPT_ASSET_TYPES = frozenset(
    {
        "funding-rate",
        "custom",
        "crypto-redemption-rate",
        "nav",
        "crypto-index",
        "kalshi",
    }
)

_EXTENDED_SESSIONS = frozenset({"PRE_MARKET", "POST_MARKET", "OVER_NIGHT"})


def check_publishers(feeds: list[dict], publishers: list[dict]) -> list[LintFinding]:
    """Publisher validation: E003, E004, E005, E008, W004, W005, W006, W007."""
    findings: list[LintFinding] = []
    valid_pub_ids = {p["publisherId"] for p in publishers}
    test_pub_ids = {p["publisherId"] for p in publishers if p.get("keyType") == "TEST"}

    for feed in feeds:
        fid = feed.get("feedId")
        sym = feed.get("symbol", "")
        state = feed.get("state", "")
        asset_type = feed.get("metadata", {}).get("asset_type", "")
        is_exempt = asset_type in _EXEMPT_ASSET_TYPES
        pub_ids = feed.get("allowedPublisherIds", [])
        min_pub = feed.get("minPublishers", 0)

        # Skip most rules for INACTIVE
        if state == "INACTIVE":
            continue

        # E003: invalid publisher ref (top-level)
        invalid_top = set(pub_ids) - valid_pub_ids
        if invalid_top:
            findings.append(
                LintFinding(
                    rule_id="E003",
                    severity="ERROR",
                    message=f"references unknown publisherIds: {sorted(invalid_top)}",
                    feed_id=fid,
                    symbol=sym,
                )
            )

        # W006: duplicate publisher in feed (top-level)
        seen = set()
        dupes = set()
        for pid in pub_ids:
            if pid in seen:
                dupes.add(pid)
            seen.add(pid)
        if dupes:
            findings.append(
                LintFinding(
                    rule_id="W006",
                    severity="WARNING",
                    message=f"duplicate publisherIds in feed: {sorted(dupes)}",
                    feed_id=fid,
                    symbol=sym,
                )
            )

        # STABLE-only rules
        if state == "STABLE":
            # E005: no publishers
            if len(pub_ids) == 0:
                findings.append(
                    LintFinding(
                        rule_id="E005",
                        severity="ERROR",
                        message="STABLE feed with no publishers",
                        feed_id=fid,
                        symbol=sym,
                    )
                )

            # E004: minPublishers >= count (top-level, non-exempt)
            if not is_exempt and len(pub_ids) > 0 and min_pub >= len(pub_ids):
                findings.append(
                    LintFinding(
                        rule_id="E004",
                        severity="ERROR",
                        message=(
                            f"minPublishers ({min_pub}) >= publisher count"
                            f" ({len(pub_ids)}), no fault tolerance"
                        ),
                        feed_id=fid,
                        symbol=sym,
                    )
                )

            # W005: only 1 headroom (top-level, non-exempt)
            if (
                not is_exempt
                and len(pub_ids) > 0
                and min_pub == len(pub_ids) - 1
                and min_pub > 0
            ):
                findings.append(
                    LintFinding(
                        rule_id="W005",
                        severity="WARNING",
                        message=(
                            f"minPublishers ({min_pub}) leaves only 1 headroom"
                            f" ({len(pub_ids)} publishers)"
                        ),
                        feed_id=fid,
                        symbol=sym,
                    )
                )

            # W007: STABLE referencing TEST publisher
            test_refs = set(pub_ids) & test_pub_ids
            if test_refs:
                findings.append(
                    LintFinding(
                        rule_id="W007",
                        severity="WARNING",
                        message=f"STABLE feed references TEST publishers: {sorted(test_refs)}",
                        feed_id=fid,
                        symbol=sym,
                    )
                )

        # COMING_SOON-only rules
        if state == "COMING_SOON":
            # W004: no publishers
            if len(pub_ids) == 0:
                findings.append(
                    LintFinding(
                        rule_id="W004",
                        severity="WARNING",
                        message="COMING_SOON feed with no publishers",
                        feed_id=fid,
                        symbol=sym,
                    )
                )

        # Session-level checks (all non-INACTIVE states)
        top_level_set = set(pub_ids)
        for schedule in feed.get("marketSchedules", []):
            session_name = schedule.get("session", "")
            session_pubs = schedule.get("allowedPublisherIds")
            session_min = schedule.get("minPublishers")

            if session_pubs is None:
                continue  # no session-level publishers

            # E003: invalid publisher ref (session-level)
            invalid_session = set(session_pubs) - valid_pub_ids
            if invalid_session:
                findings.append(
                    LintFinding(
                        rule_id="E003",
                        severity="ERROR",
                        message=(
                            f"session {session_name}: references unknown"
                            f" publisherIds: {sorted(invalid_session)}"
                        ),
                        feed_id=fid,
                        symbol=sym,
                    )
                )

            # E008: session publisher not in top-level list
            not_in_top = set(session_pubs) - top_level_set
            if not_in_top:
                findings.append(
                    LintFinding(
                        rule_id="E008",
                        severity="ERROR",
                        message=(
                            f"session {session_name}: publisherIds"
                            f" {sorted(not_in_top)} not in top-level list"
                        ),
                        feed_id=fid,
                        symbol=sym,
                    )
                )

            # E004/W005 at session level (STABLE non-exempt only)
            if state == "STABLE" and not is_exempt and session_min is not None:
                session_count = len(session_pubs)
                if session_count > 0 and session_min >= session_count:
                    findings.append(
                        LintFinding(
                            rule_id="E004",
                            severity="ERROR",
                            message=(
                                f"session {session_name}: minPublishers ({session_min})"
                                f" >= publisher count ({session_count})"
                            ),
                            feed_id=fid,
                            symbol=sym,
                        )
                    )
                elif (
                    session_count > 0
                    and session_min == session_count - 1
                    and session_min > 0
                ):
                    findings.append(
                        LintFinding(
                            rule_id="W005",
                            severity="WARNING",
                            message=(
                                f"session {session_name}: minPublishers ({session_min})"
                                f" leaves only 1 headroom ({session_count} publishers)"
                            ),
                            feed_id=fid,
                            symbol=sym,
                        )
                    )

    return findings


def check_schedules(feeds: list[dict]) -> list[LintFinding]:
    """Schedule validation rules."""
    # Placeholder — implemented in Task 5
    return []


def lint_config(config: dict) -> list[LintFinding]:
    """Orchestrator. Takes the full parsed after.json root object."""
    feeds = config.get("feeds", [])
    publishers = config.get("publishers", [])

    findings: list[LintFinding] = []
    findings.extend(check_duplicates(feeds))
    findings.extend(check_schema(feeds))
    findings.extend(check_publishers(feeds, publishers))
    findings.extend(check_schedules(feeds))

    return findings
