"""Config linter rules for after.json validation.

Validates feed definitions, publisher references, schedule consistency,
and business rules. Pure stdlib — no external dependencies.
"""

from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from typing import Optional

from lib.exchange_lint import check_exchanges
from lib.lint_finding import LintFinding  # noqa: F401 – re-exported for callers
from lib.symbol_utils import (
    equity_listing_prefix,
    futures_root,
    is_futures_symbol,
    is_us_equity,
)


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


_BENCHMARKABLE_ASSET_TYPES = frozenset({"equity", "fx", "metal", "commodity", "rates"})


def _is_positive_numeric(value: str) -> bool:
    """Check if value is a positive integer string (non-zero)."""
    return bool(re.match(r"^\d+$", value)) and int(value) > 0


def _is_duration_string(value: str) -> bool:
    """Check if value matches duration format N.Ns (e.g. '600.000000000s')."""
    return bool(re.match(r"^\d+\.\d+s$", value))


def _is_date_string(value: str) -> bool:
    """Check if value is a valid YYYY-MM-DD date."""
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except (ValueError, TypeError):
        return False


_KNOWN_EVENT_TYPES = frozenset({"SPLIT"})

_CORPORATE_ACTION_SCHEMAS: dict[str, dict] = {
    "SPLIT": {
        "required": [
            "adjustmentFactorNumerator",
            "adjustmentFactorDenominator",
            "rejectionThresholdBips",
            "rejectionWindow",
        ],
        "nested_required": {"activation": {"usEquityExDate": ["exDate"]}},
        "validators": {
            "adjustmentFactorNumerator": (
                "positive numeric string",
                _is_positive_numeric,
            ),
            "adjustmentFactorDenominator": (
                "positive numeric string",
                _is_positive_numeric,
            ),
            "rejectionThresholdBips": ("positive numeric string", _is_positive_numeric),
            "rejectionWindow": ("N.Ns", _is_duration_string),
            "exDate": ("YYYY-MM-DD", _is_date_string),
        },
    },
}


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
    """Publisher validation: E003, E004, E005, E008, W004, W005, W006, W007.

    Publishers missing `publisherId` are skipped here, mirroring the policy
    used by `check_publisher_duplicates`. A separate schema rule is the
    right place to flag missing fields.
    """
    findings: list[LintFinding] = []
    valid_pub_ids = {p["publisherId"] for p in publishers if "publisherId" in p}
    test_pub_ids = {
        p["publisherId"]
        for p in publishers
        if "publisherId" in p and p.get("keyType") == "TEST"
    }
    name_test_pub_ids = {
        p["publisherId"]
        for p in publishers
        if "publisherId" in p and p.get("name", "").lower().endswith(".test")
    }

    for feed in feeds:
        fid = feed.get("feedId")
        sym = feed.get("symbol", "")
        state = feed.get("state", "")
        asset_type = feed.get("metadata", {}).get("asset_type", "")
        is_exempt = asset_type in _EXEMPT_ASSET_TYPES
        pub_ids = feed.get("allowedPublisherIds", [])
        # `"minPublishers": null` in JSON returns None from .get() (the
        # default applies only when the key is absent). Coerce to 0 so the
        # int comparisons below do not raise TypeError on malformed input.
        min_pub = feed.get("minPublishers") or 0

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
                            f" ({len(pub_ids)}), Not enough publishers permissioned"
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

            # E009: STABLE referencing .Test-named publishers
            name_test_refs = set(pub_ids) & name_test_pub_ids
            if name_test_refs:
                findings.append(
                    LintFinding(
                        rule_id="E009",
                        severity="ERROR",
                        message=(
                            f"STABLE feed references .Test-suffixed publishers:"
                            f" {sorted(name_test_refs)}"
                        ),
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
                                f" >= publisher count ({session_count}),"
                                f" Not enough publishers permissioned"
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


_US_EQUITY_EXPECTED_SESSIONS = frozenset(
    {"REGULAR", "PRE_MARKET", "POST_MARKET", "OVER_NIGHT"}
)


def _extract_timezone(schedule_str: str) -> str:
    """Extract timezone from a marketSchedule string (first segment before ';')."""
    return schedule_str.split(";")[0] if ";" in schedule_str else ""


def _format_group_label(group_key: tuple) -> str:
    """Render a group key for a finding message.

    Single-part keys read naturally ("commodity"); multi-part keys like
    ("equity", "US") are parenthesized to avoid awkward "X, Y majority"
    phrasing.
    """
    if len(group_key) == 1:
        return str(group_key[0])
    return "(" + ", ".join(str(k) for k in group_key) + ")"


def check_schedules(feeds: list[dict]) -> list[LintFinding]:
    """E006, E010, E011, W001, W002, W003: schedule validation rules.

    E011 fires on STABLE feeds only (CI blocker).
    W003 fires on STABLE + COMING_SOON feeds (advisory).
    Both rules use a single session_groups dict keyed by:
        bucket_key = group_key + (session,)
    where group_key is one of:
        - ("equity", listing_prefix)             for equity spot feeds
        - ("equity", listing_prefix, futures_root) for equity futures
        - (asset_type, futures_root)             for non-equity futures
        - (asset_type,)                          for non-equity spot feeds

    A feed contributes one entry per (session, marketSchedule) row in its
    marketSchedules list. A feed missing a session is not penalized; it
    simply does not participate in that bucket.
    """
    findings: list[LintFinding] = []

    # bucket_key (group_key + (session,)) -> list of (fid, sym, schedule_str, state)
    session_groups: dict[tuple, list[tuple[int, str, str, str]]] = {}

    for feed in feeds:
        fid = feed.get("feedId")
        sym = feed.get("symbol", "")
        state = feed.get("state", "")
        asset_type = feed.get("metadata", {}).get("asset_type", "")
        schedules = feed.get("marketSchedules", [])

        if state == "INACTIVE":
            continue

        sessions = [s.get("session", "") for s in schedules]

        # E010: duplicate session within a single feed
        session_counts = Counter(sessions)
        dup_sessions = sorted({s for s, c in session_counts.items() if c > 1 and s})
        if dup_sessions:
            findings.append(
                LintFinding(
                    rule_id="E010",
                    severity="ERROR",
                    message=(
                        f"duplicate session(s) in marketSchedules: {dup_sessions}"
                    ),
                    feed_id=fid,
                    symbol=sym,
                )
            )

        # E010: identical (session, marketSchedule) tuple repeated
        sched_tuples = [
            (s.get("session", ""), s.get("marketSchedule", "")) for s in schedules
        ]
        tuple_counts = Counter(sched_tuples)
        if any(c > 1 for c in tuple_counts.values()):
            findings.append(
                LintFinding(
                    rule_id="E010",
                    severity="ERROR",
                    message="duplicate verbatim marketSchedules entry",
                    feed_id=fid,
                    symbol=sym,
                )
            )

        sessions_set = set(sessions)

        # E006: non-equity with extended sessions
        if asset_type != "equity":
            extended = sessions_set & _EXTENDED_SESSIONS
            if extended:
                findings.append(
                    LintFinding(
                        rule_id="E006",
                        severity="ERROR",
                        message=f"non-equity ({asset_type}) has extended sessions: {sorted(extended)}",
                        feed_id=fid,
                        symbol=sym,
                    )
                )

        # Build the group key for E011 / W003 (without session).
        sym_parts = sym.split(".")
        if asset_type == "equity":
            prefix = equity_listing_prefix(sym)
            if is_futures_symbol(sym):
                group_key: tuple = (asset_type, prefix, futures_root(sym))
            else:
                group_key = (asset_type, prefix)
        elif len(sym_parts) >= 3 and sym_parts[1] == "Index":
            # <AssetClass>.Index.* (Metal.Index, FX.Index, ...) is a separate
            # sub-namespace from spot/regular feeds in the same asset class.
            if is_futures_symbol(sym):
                group_key = (asset_type, "Index", futures_root(sym))
            else:
                group_key = (asset_type, "Index")
        else:
            if is_futures_symbol(sym):
                group_key = (asset_type, futures_root(sym))
            else:
                group_key = (asset_type,)

        # Push one bucket entry per (session, marketSchedule) row.
        for sched in schedules:
            session = sched.get("session", "")
            sched_str = sched.get("marketSchedule", "")
            bucket_key = group_key + (session,)
            session_groups.setdefault(bucket_key, []).append(
                (fid, sym, sched_str, state)
            )

        # STABLE-only single-feed schedule rules (W001, W002 unchanged)
        if state == "STABLE":
            if is_us_equity(feed):
                missing = _US_EQUITY_EXPECTED_SESSIONS - sessions_set
                if missing:
                    findings.append(
                        LintFinding(
                            rule_id="W001",
                            severity="WARNING",
                            message=f"STABLE US equity missing sessions: {sorted(missing)}",
                            feed_id=fid,
                            symbol=sym,
                        )
                    )

                for sched in schedules:
                    tz = _extract_timezone(sched.get("marketSchedule", ""))
                    if tz and tz != "America/New_York":
                        findings.append(
                            LintFinding(
                                rule_id="W002",
                                severity="WARNING",
                                message=f"US equity using timezone '{tz}' instead of 'America/New_York'",
                                feed_id=fid,
                                symbol=sym,
                            )
                        )
                        break

    # E011: STABLE-only strict per-session schedule inconsistency.
    for bucket_key, entries in session_groups.items():
        stable_entries = [
            (fid, sym, sched_str)
            for fid, sym, sched_str, st in entries
            if st == "STABLE"
        ]
        if len(stable_entries) < 2:
            continue
        distinct = {sched_str for _, _, sched_str in stable_entries}
        if len(distinct) < 2:
            continue

        sig_counter: Counter[str] = Counter(
            sched_str for _, _, sched_str in stable_entries
        )
        top_count = sig_counter.most_common(1)[0][1]
        top_schedules = {s for s, c in sig_counter.items() if c == top_count}
        session = bucket_key[-1]
        group_label = _format_group_label(bucket_key[:-1])

        if len(top_schedules) == 1:
            # Clear majority — flag only the minority feeds.
            reference = next(iter(top_schedules))
            for fid, sym, sched_str in stable_entries:
                if sched_str != reference:
                    findings.append(
                        LintFinding(
                            rule_id="E011",
                            severity="ERROR",
                            message=(
                                f"{session} schedule disagrees with group"
                                f" {group_label}: {len(distinct)} distinct"
                                f" schedules across {len(stable_entries)} STABLE"
                                f" feeds"
                            ),
                            feed_id=fid,
                            symbol=sym,
                        )
                    )
        else:
            # Tie at the top — no clear majority. Flag every STABLE feed
            # in the bucket symmetrically.
            for fid, sym, _sched_str in stable_entries:
                findings.append(
                    LintFinding(
                        rule_id="E011",
                        severity="ERROR",
                        message=(
                            f"{session} schedule has no consensus across group"
                            f" {group_label}: {len(distinct)} distinct schedules"
                            f" across {len(stable_entries)} STABLE feeds, no"
                            f" majority"
                        ),
                        feed_id=fid,
                        symbol=sym,
                    )
                )

    # W003: per-session schedule deviation across STABLE + COMING_SOON.
    for bucket_key, entries in session_groups.items():
        active_entries = [
            (fid, sym, sched_str)
            for fid, sym, sched_str, st in entries
            if st in ("STABLE", "COMING_SOON")
        ]
        if len(active_entries) <= 1:
            continue

        counts: Counter[str] = Counter(sched_str for _, _, sched_str in active_entries)
        majority = counts.most_common(1)[0][0]
        if counts[majority] == 1:
            continue

        session = bucket_key[-1]
        group_label = _format_group_label(bucket_key[:-1])

        for fid, sym, sched_str in active_entries:
            if sched_str != majority:
                findings.append(
                    LintFinding(
                        rule_id="W003",
                        severity="WARNING",
                        message=(
                            f"{session} schedule deviates from {group_label}"
                            f" majority"
                        ),
                        feed_id=fid,
                        symbol=sym,
                    )
                )

    return findings


def check_hermes_ids(feeds: list[dict]) -> list[LintFinding]:
    """E012: duplicate metadata.hermes_id across non-INACTIVE feeds."""
    findings: list[LintFinding] = []
    by_hermes: dict[str, list[dict]] = {}

    for feed in feeds:
        if feed.get("state", "") == "INACTIVE":
            continue
        hermes_id = feed.get("metadata", {}).get("hermes_id", "")
        if not hermes_id:
            continue
        by_hermes.setdefault(hermes_id, []).append(feed)

    for hermes_id, group in by_hermes.items():
        if len(group) < 2:
            continue
        first = group[0]
        feed_ids = [f.get("feedId") for f in group]
        findings.append(
            LintFinding(
                rule_id="E012",
                severity="ERROR",
                message=(
                    f"hermes_id '{hermes_id}' duplicated across feedIds:"
                    f" {', '.join(str(fid) for fid in feed_ids)}"
                ),
                feed_id=first.get("feedId"),
                symbol=first.get("symbol"),
            )
        )

    return findings


def check_benchmark_mapping(feeds: list[dict]) -> list[LintFinding]:
    """E014: STABLE benchmarkable feed missing benchmarkMapping on any session."""
    findings: list[LintFinding] = []

    for feed in feeds:
        if feed.get("state") != "STABLE":
            continue
        asset_type = feed.get("metadata", {}).get("asset_type", "")
        if asset_type not in _BENCHMARKABLE_ASSET_TYPES:
            continue

        fid = feed.get("feedId")
        sym = feed.get("symbol", "")

        for schedule in feed.get("marketSchedules", []):
            session_name = schedule.get("session", "")
            bm = schedule.get("benchmarkMapping")
            if not bm:
                findings.append(
                    LintFinding(
                        rule_id="E014",
                        severity="ERROR",
                        message=f"{session_name} session missing benchmarkMapping",
                        feed_id=fid,
                        symbol=sym,
                    )
                )

    return findings


def check_corporate_actions(feeds: list[dict]) -> list[LintFinding]:
    """E015: corporateActions schema violation. W009: unknown eventType."""
    findings: list[LintFinding] = []

    for feed in feeds:
        fid = feed.get("feedId")
        sym = feed.get("symbol", "")
        actions = feed.get("corporateActions") or []

        for idx, action in enumerate(actions):
            prefix = f"corporateActions[{idx}]"
            event_type = action.get("eventType")

            # Missing eventType is always E015
            if event_type is None:
                findings.append(
                    LintFinding(
                        rule_id="E015",
                        severity="ERROR",
                        message=f"{prefix}: missing required field 'eventType'",
                        feed_id=fid,
                        symbol=sym,
                    )
                )
                continue

            # Unknown eventType -> W009, skip schema validation
            if event_type not in _KNOWN_EVENT_TYPES:
                findings.append(
                    LintFinding(
                        rule_id="W009",
                        severity="WARNING",
                        message=(
                            f"{prefix}: unknown eventType '{event_type}',"
                            f" schema not validated"
                        ),
                        feed_id=fid,
                        symbol=sym,
                    )
                )
                continue

            schema = _CORPORATE_ACTION_SCHEMAS[event_type]

            # Check required top-level fields
            for field in schema["required"]:
                if field not in action:
                    findings.append(
                        LintFinding(
                            rule_id="E015",
                            severity="ERROR",
                            message=f"{prefix}: missing required field '{field}'",
                            feed_id=fid,
                            symbol=sym,
                        )
                    )

            # Check nested required fields
            for level1, level2_dict in schema.get("nested_required", {}).items():
                l1_obj = action.get(level1)
                if not isinstance(l1_obj, dict):
                    findings.append(
                        LintFinding(
                            rule_id="E015",
                            severity="ERROR",
                            message=f"{prefix}: missing required field '{level1}'",
                            feed_id=fid,
                            symbol=sym,
                        )
                    )
                    continue
                for level2, fields in level2_dict.items():
                    l2_obj = l1_obj.get(level2)
                    if not isinstance(l2_obj, dict):
                        findings.append(
                            LintFinding(
                                rule_id="E015",
                                severity="ERROR",
                                message=f"{prefix}: missing required field '{level2}'",
                                feed_id=fid,
                                symbol=sym,
                            )
                        )
                        continue
                    for field in fields:
                        if field not in l2_obj:
                            findings.append(
                                LintFinding(
                                    rule_id="E015",
                                    severity="ERROR",
                                    message=f"{prefix}: missing required field '{field}'",
                                    feed_id=fid,
                                    symbol=sym,
                                )
                            )

            # Validate field formats
            validators = schema.get("validators", {})
            for field, (expected_fmt, validator_fn) in validators.items():
                # Get value — may be top-level or nested
                if field in action:
                    value = action[field]
                else:
                    # Walk nested structure to find the field
                    value = None
                    for nested_key, nested_dict in schema.get(
                        "nested_required", {}
                    ).items():
                        nested_obj = action.get(nested_key)
                        if not isinstance(nested_obj, dict):
                            break
                        for sub_key, sub_fields in nested_dict.items():
                            sub_obj = nested_obj.get(sub_key)
                            if (
                                isinstance(sub_obj, dict)
                                and field in sub_fields
                                and field in sub_obj
                            ):
                                value = sub_obj[field]
                    if value is None:
                        continue  # Already flagged as missing

                if not validator_fn(str(value)):
                    findings.append(
                        LintFinding(
                            rule_id="E015",
                            severity="ERROR",
                            message=(
                                f"{prefix}: '{field}' has invalid format"
                                f" '{value}' (expected {expected_fmt})"
                            ),
                            feed_id=fid,
                            symbol=sym,
                        )
                    )

    return findings


def check_identifier_continuity(feeds: list[dict]) -> list[LintFinding]:
    """E016: identifier date range overlap within same vendor/session."""
    findings: list[LintFinding] = []

    for feed in feeds:
        if feed.get("state") == "INACTIVE":
            continue

        fid = feed.get("feedId")
        sym = feed.get("symbol", "")

        for schedule in feed.get("marketSchedules", []):
            session_name = schedule.get("session", "")
            bm = schedule.get("benchmarkMapping", {}) or {}

            for vendor, vendor_obj in bm.items():
                if not isinstance(vendor_obj, dict):
                    continue
                identifiers = vendor_obj.get("identifiers") or []
                if len(identifiers) < 2:
                    continue

                # Parse and sort by validFrom
                parsed = []
                for idf in identifiers:
                    vf = _parse_iso(idf.get("validFrom", ""))
                    vt_raw = idf.get("validTo")
                    vt = _parse_iso(vt_raw) if vt_raw else None
                    ident = idf.get("identifier", "?")
                    parsed.append((vf, vt, ident))

                parsed.sort(
                    key=lambda x: x[0] or datetime.min.replace(tzinfo=timezone.utc)
                )

                for i in range(len(parsed) - 1):
                    _, end_i, ident_i = parsed[i]
                    start_j, _, ident_j = parsed[i + 1]

                    if end_i is None:
                        findings.append(
                            LintFinding(
                                rule_id="E016",
                                severity="ERROR",
                                message=(
                                    f"session {session_name}: {vendor} identifier"
                                    f" '{ident_i}' has no validTo but is followed"
                                    f" by '{ident_j}'"
                                ),
                                feed_id=fid,
                                symbol=sym,
                            )
                        )
                    elif start_j is not None and end_i > start_j:
                        findings.append(
                            LintFinding(
                                rule_id="E016",
                                severity="ERROR",
                                message=(
                                    f"session {session_name}: {vendor} identifiers"
                                    f" '{ident_i}' and '{ident_j}' have overlapping"
                                    f" date ranges"
                                ),
                                feed_id=fid,
                                symbol=sym,
                            )
                        )

    return findings


def _parse_iso(value: str) -> Optional[datetime]:
    """Parse an ISO-8601 string (with trailing Z and up to 9 fractional digits)."""
    if not value:
        return None
    s = value.replace("Z", "+00:00")
    # datetime.fromisoformat accepts up to 6 fractional-second digits.
    # Trim nanoseconds to microseconds if present.
    if "." in s:
        head, sep, tail = s.partition(".")
        # split off timezone offset from tail
        if "+" in tail:
            frac, tzsep, tz = tail.partition("+")
            tz = tzsep + tz
        elif "-" in tail:
            frac, tzsep, tz = tail.partition("-")
            tz = tzsep + tz
        else:
            frac, tz = tail, ""
        frac = frac[:6]
        s = f"{head}{sep}{frac}{tz}"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    # Coerce naive timestamps (no Z, no offset) to UTC so callers comparing
    # against tz-aware now() do not raise TypeError. A linter should produce
    # an actionable finding, not crash, when input data is mildly malformed.
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def check_expired_futures(feeds: list[dict], now: datetime) -> list[LintFinding]:
    """E013: STABLE or COMING_SOON futures whose every validTo is in the past.

    A feed is flagged when:
      - state is STABLE or COMING_SOON, AND
      - the symbol matches the futures pattern, AND
      - at least one identifier has a validTo, AND
      - every validTo found is earlier than `now`.

    INACTIVE feeds and feeds with no validTo identifiers are skipped.
    """
    findings: list[LintFinding] = []

    for feed in feeds:
        state = feed.get("state", "")
        if state not in ("STABLE", "COMING_SOON"):
            continue
        sym = feed.get("symbol", "")
        if not is_futures_symbol(sym):
            continue

        valid_tos: list[datetime] = []
        for sched in feed.get("marketSchedules", []):
            bm = sched.get("benchmarkMapping", {}) or {}
            for vendor_obj in bm.values():
                if not isinstance(vendor_obj, dict):
                    continue
                for idf in vendor_obj.get("identifiers", []) or []:
                    vt = idf.get("validTo")
                    parsed = _parse_iso(vt) if vt else None
                    if parsed is not None:
                        valid_tos.append(parsed)

        if not valid_tos:
            continue

        if all(vt < now for vt in valid_tos):
            latest = max(valid_tos)
            findings.append(
                LintFinding(
                    rule_id="E013",
                    severity="ERROR",
                    message=(
                        f"{state} futures feed has expired"
                        f" (latest validTo: {latest.isoformat()});"
                        f" change state to INACTIVE"
                    ),
                    feed_id=feed.get("feedId"),
                    symbol=sym,
                )
            )

    return findings


def check_publisher_duplicates(publishers: list[dict]) -> list[LintFinding]:
    """E017: duplicate publisherId, E018: duplicate publisher name.

    Mirrors the uniqueness invariants the Rust governance tool enforces
    in `diff_publishers` (publisher ids/names must be globally unique).
    Catching them here surfaces the violation before the Rust tool's
    stack-trace error reaches CI.

    The `feed_id` slot of the LintFinding holds the duplicated
    publisherId for E017; `symbol` holds the duplicated name for E018.
    This keeps each duplicate distinguishable by `_finding_key` for
    diff-mode comparisons.
    """
    findings: list[LintFinding] = []

    # E017: duplicate publisherId
    id_counts: dict[int, int] = {}
    for p in publishers:
        pid = p.get("publisherId")
        if pid is not None:
            id_counts[pid] = id_counts.get(pid, 0) + 1

    for pid, count in id_counts.items():
        if count > 1:
            findings.append(
                LintFinding(
                    rule_id="E017",
                    severity="ERROR",
                    message=(f"publisherId {pid} is duplicated ({count} occurrences)"),
                    feed_id=pid,
                    symbol=None,
                )
            )

    # E018: duplicate publisher name
    name_counts: dict[str, int] = {}
    for p in publishers:
        name = p.get("name")
        if name:
            name_counts[name] = name_counts.get(name, 0) + 1

    for name, count in name_counts.items():
        if count > 1:
            findings.append(
                LintFinding(
                    rule_id="E018",
                    severity="ERROR",
                    message=(
                        f"publisher name '{name}' is duplicated"
                        f" ({count} occurrences)"
                    ),
                    feed_id=None,
                    symbol=name,
                )
            )

    return findings


def lint_config(config: dict, now: Optional[datetime] = None) -> list[LintFinding]:
    """Orchestrator. Takes the full parsed after.json root object."""
    feeds = config.get("feeds", [])
    publishers = config.get("publishers", [])
    now = now or datetime.now(timezone.utc)

    findings: list[LintFinding] = []
    findings.extend(check_duplicates(feeds))
    findings.extend(check_schema(feeds))
    findings.extend(check_publisher_duplicates(publishers))
    findings.extend(check_publishers(feeds, publishers))
    findings.extend(check_schedules(feeds))
    findings.extend(check_hermes_ids(feeds))
    findings.extend(check_expired_futures(feeds, now))
    findings.extend(check_benchmark_mapping(feeds))
    findings.extend(check_corporate_actions(feeds))
    findings.extend(check_identifier_continuity(feeds))
    findings.extend(check_exchanges(feeds, config.get("exchanges", []) or []))

    return findings


def _finding_key(f: LintFinding) -> tuple[str, Optional[int], Optional[str]]:
    """Identity tuple for diff comparison.

    Two findings are considered "the same" iff this tuple matches.
    Message text is intentionally excluded so magnitude changes within a
    rule (e.g. publisher count dropping further on E004) do not surface
    as new findings.

    Several rules emit multiple distinct findings sharing this tuple
    (E003 top-level vs session-level, E004 top-level vs session-level,
    E010 duplicate-session vs verbatim-duplicate, E015 with multiple
    schema violations on one corporate-action entry). Suppression is
    therefore done by multiplicity (Counter) rather than by set
    membership, so adding a new finding of one of those rules to a
    feed that already has another is correctly reported as new.
    """
    return (f.rule_id, f.feed_id, f.symbol)


def _compute_diff(
    after_config: dict,
    before_config: dict,
    now: Optional[datetime] = None,
) -> tuple[list[LintFinding], int]:
    """Internal helper for diff mode.

    Returns (new_findings, suppressed_count) where suppressed_count is
    the number of after_findings that were filtered out because they
    matched a baseline finding by `_finding_key` multiplicity.

    Suppression is Counter-based, not set-based: a baseline with N
    findings of the same key suppresses up to N after-findings of that
    key. The (N+1)th and later after-findings of that key are reported
    as new. This handles the case where a feed gains an additional
    finding of a rule that can fire multiply (E003/E004/E010/E015).
    """
    now = now or datetime.now(timezone.utc)
    before_findings = lint_config(before_config, now=now)
    after_findings = lint_config(after_config, now=now)

    baseline_counts: Counter[tuple[str, Optional[int], Optional[str]]] = Counter(
        _finding_key(f) for f in before_findings
    )
    new_findings: list[LintFinding] = []
    for f in after_findings:
        k = _finding_key(f)
        if baseline_counts[k] > 0:
            baseline_counts[k] -= 1
        else:
            new_findings.append(f)

    suppressed_count = len(after_findings) - len(new_findings)
    return new_findings, suppressed_count


def lint_config_diff(
    after_config: dict,
    before_config: dict,
    now: Optional[datetime] = None,
) -> list[LintFinding]:
    """Lint after_config and return only findings not present in before_config.

    A finding is "pre-existing" when its `_finding_key` tuple matches a
    finding produced by linting before_config under the same `now`.
    Pre-existing findings are dropped from the result.

    The same `now` is passed to both runs so that time-dependent rules
    (E013) are evaluated against a single instant.
    """
    new_findings, _ = _compute_diff(after_config, before_config, now=now)
    return new_findings


def lint_config_diff_with_count(
    after_config: dict,
    before_config: dict,
    now: Optional[datetime] = None,
) -> tuple[list[LintFinding], int]:
    """Same as `lint_config_diff` but also returns how many after-findings
    were actually suppressed because they matched a baseline finding.

    The CLI uses this to display an accurate "N pre-existing findings
    suppressed" message: N must be the count of after-findings that were
    filtered out, not the total baseline finding count (which would
    overstate suppression whenever the proposal fixes a baseline issue).
    """
    return _compute_diff(after_config, before_config, now=now)
