"""Config linter rules for after.json validation.

Validates feed definitions, publisher references, schedule consistency,
and business rules. Pure stdlib — no external dependencies.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from lib.symbol_utils import futures_root, is_futures_symbol, is_us_equity


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
    """Publisher validation: E003, E004, E005, E008, W004, W005, W006, W007."""
    findings: list[LintFinding] = []
    valid_pub_ids = {p["publisherId"] for p in publishers}
    test_pub_ids = {p["publisherId"] for p in publishers if p.get("keyType") == "TEST"}
    name_test_pub_ids = {
        p["publisherId"]
        for p in publishers
        if p.get("name", "").lower().endswith(".test")
    }

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


_US_EQUITY_EXPECTED_SESSIONS = frozenset(
    {"REGULAR", "PRE_MARKET", "POST_MARKET", "OVER_NIGHT"}
)


def _get_schedule_signature(schedules: list[dict]) -> tuple:
    """Create a hashable signature from a feed's marketSchedules for comparison."""
    return tuple(
        sorted((s.get("session", ""), s.get("marketSchedule", "")) for s in schedules)
    )


def _extract_timezone(schedule_str: str) -> str:
    """Extract timezone from a marketSchedule string (first segment before ';')."""
    return schedule_str.split(";")[0] if ";" in schedule_str else ""


def check_schedules(feeds: list[dict]) -> list[LintFinding]:
    """E006, E010, E011, W001, W002, W003: schedule validation rules."""
    findings: list[LintFinding] = []

    # Collect schedule signatures per asset_type for W003 majority detection
    asset_type_schedules: dict[str, list[tuple[int, str, tuple, bool]]] = {}

    # Collect signatures per E011 group: (asset_type,) or (asset_type, futures_root)
    group_signatures: dict[tuple, list[tuple[int, str, tuple]]] = {}

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

        # E011: collect signature per (asset_type,) or (asset_type, futures_root)
        sig_for_group = _get_schedule_signature(schedules)
        if is_futures_symbol(sym):
            group_key: tuple = (asset_type, futures_root(sym))
        else:
            group_key = (asset_type,)
        group_signatures.setdefault(group_key, []).append((fid, sym, sig_for_group))

        # STABLE-only schedule rules
        if state == "STABLE":
            # W001: US equity missing extended sessions
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

                # W002: US equity wrong timezone
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
                        break  # one finding per feed is enough

            # Collect for W003
            sig = _get_schedule_signature(schedules)
            is_future = is_futures_symbol(sym)
            asset_type_schedules.setdefault(asset_type, []).append(
                (fid, sym, sig, is_future)
            )

    # W003: schedule deviation from asset-class majority
    for asset_type, feed_sigs in asset_type_schedules.items():
        if len(feed_sigs) <= 1:
            continue

        # Find majority schedule (exclude futures from count)
        sig_counts: Counter[tuple] = Counter()
        for _, _, sig, is_future in feed_sigs:
            if not is_future:
                sig_counts[sig] += 1

        if not sig_counts:
            continue

        majority_sig = sig_counts.most_common(1)[0][0]

        for fid, sym, sig, is_future in feed_sigs:
            if sig != majority_sig and not is_future:
                findings.append(
                    LintFinding(
                        rule_id="W003",
                        severity="WARNING",
                        message=f"schedule deviates from {asset_type} majority",
                        feed_id=fid,
                        symbol=sym,
                    )
                )

    # E011: strict schedule inconsistency across asset groups
    for group_key, feed_sigs in group_signatures.items():
        if len(feed_sigs) < 2:
            continue
        distinct_sigs = {sig for _, _, sig in feed_sigs}
        if len(distinct_sigs) < 2:
            continue

        sig_counter: Counter[tuple] = Counter(sig for _, _, sig in feed_sigs)
        reference_sig = sig_counter.most_common(1)[0][0]
        group_label = ", ".join(str(k) for k in group_key)

        for fid, sym, sig in feed_sigs:
            if sig != reference_sig:
                findings.append(
                    LintFinding(
                        rule_id="E011",
                        severity="ERROR",
                        message=(
                            f"schedule disagrees with other feeds in group"
                            f" ({group_label}): {len(distinct_sigs)} distinct"
                            f" schedules across {len(feed_sigs)} feeds"
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
    """E014: STABLE benchmarkable feed missing benchmarkMapping on non-OVERNIGHT session."""
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
            if session_name == "OVER_NIGHT":
                continue
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
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def check_expired_coming_soon_futures(
    feeds: list[dict], now: datetime
) -> list[LintFinding]:
    """E013: COMING_SOON futures whose every validTo is in the past."""
    findings: list[LintFinding] = []

    for feed in feeds:
        if feed.get("state", "") != "COMING_SOON":
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
                        f"COMING_SOON futures feed has expired"
                        f" (latest validTo: {latest.isoformat()});"
                        f" change state to INACTIVE"
                    ),
                    feed_id=feed.get("feedId"),
                    symbol=sym,
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
    findings.extend(check_publishers(feeds, publishers))
    findings.extend(check_schedules(feeds))
    findings.extend(check_hermes_ids(feeds))
    findings.extend(check_expired_coming_soon_futures(feeds, now))
    findings.extend(check_benchmark_mapping(feeds))
    findings.extend(check_corporate_actions(feeds))
    findings.extend(check_identifier_continuity(feeds))

    return findings
