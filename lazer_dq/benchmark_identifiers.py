"""Resolve the benchmark identifier (Datascope RIC) for a feed/session.

The Lazer config stores per-session benchmark identifiers under
``market_schedules[].benchmarkMapping``. TradFi feeds carry a ``datascope_ric``
(e.g. ``AAPL.O``); crypto feeds instead carry a ``coinpaprika_symbol`` (e.g.
``btc-bitcoin``). This module maps a benchmarking *mode* to the market session
whose identifier we want, and extracts the most recently valid identifier.

Pure stdlib so it is unit-testable without pandas or a database.
"""
import json

# Map a benchmarking mode to the market_schedules session whose identifier we
# query by. Any mode not listed here uses the REGULAR session.
SESSION_BY_MODE = {
    "us-equities": "REGULAR",
    "us-equities-pre": "PRE_MARKET",
    "us-equities-post": "POST_MARKET",
    "us-equities-on": "OVER_NIGHT",
    "us-equities-overnight": "OVER_NIGHT",
}


def session_for_mode(mode):
    """Return the market session name for a mode (default REGULAR)."""
    return SESSION_BY_MODE.get(mode, "REGULAR")


def resolve_benchmark_identifier(
    market_schedules, session_name, identifier_key="datascope_ric"
):
    """Return the identifier string for a session, or None if unavailable.

    - ``market_schedules`` may be a list of session dicts, a JSON string, or None.
    - Finds the session entry whose ``session`` == ``session_name``.
    - Reads ``benchmarkMapping[identifier_key]["identifiers"]`` and returns the
      identifier whose ``validFrom`` is the maximum (most recently valid).
    - Returns None if the input, session, mapping, or identifiers are missing.
    """
    if market_schedules is None:
        return None
    if isinstance(market_schedules, str):
        try:
            market_schedules = json.loads(market_schedules)
        except (ValueError, TypeError):
            return None
    if not isinstance(market_schedules, list):
        return None

    for session in market_schedules:
        if not isinstance(session, dict) or session.get("session") != session_name:
            continue
        mapping = session.get("benchmarkMapping") or {}
        identifiers = (mapping.get(identifier_key) or {}).get("identifiers") or []
        if not identifiers:
            return None
        best = max(identifiers, key=lambda i: i.get("validFrom", ""))
        return best.get("identifier")
    return None
