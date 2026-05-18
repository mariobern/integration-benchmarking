"""Canonical US-equity market-schedule templates.

Source of truth: feedId 922 (Equity.US.AAPL/USD) in after.json. These strings
match it byte-for-byte and are shared across every standard US-equity feed
that was expanded into the 4-session shape by PR #26 (backfill-apids).

Only the non-REGULAR sessions are templated. We never synthesize a REGULAR
schedule — feeds without one are not eligible for `--add-session`.
"""

from __future__ import annotations

PRE_MARKET_SCHEDULE = (
    "America/New_York;"
    "0400-0930,0400-0930,0400-0930,0400-0930,0400-0930,C,C;"
    "0101/C,0119/C,0216/C,0403/C,0525/C,0619/C,0703/C,0907/C,1126/C,1225/C"
)

POST_MARKET_SCHEDULE = (
    "America/New_York;"
    "1600-2000,1600-2000,1600-2000,1600-2000,1600-2000,C,C;"
    "0101/C,0119/C,0216/C,0403/C,0525/C,0619/C,0703/C,0907/C,1126/C,1225/C"
)

OVER_NIGHT_SCHEDULE = (
    "America/New_York;"
    "0000-0400&2000-2400,0000-0400&2000-2400,0000-0400&2000-2400,"
    "0000-0400&2000-2400,0000-0400,C,2000-2400;"
    "0118/C,0119/2000-2400,0215/C,0216/2000-2400,0402/0000-0400,0403/C,"
    "0524/C,0525/2000-2400,0618/0000-0400,0619/C,0702/0000-0400,0703/C,"
    "0906/C,0907/2000-2400,1125/0000-0400,1126/2000-2400,1224/0000-0400,"
    "1225/C,1231/0000-0400,0101/C"
)

SCHEDULE_BY_SESSION = {
    "PRE_MARKET": PRE_MARKET_SCHEDULE,
    "POST_MARKET": POST_MARKET_SCHEDULE,
    "OVER_NIGHT": OVER_NIGHT_SCHEDULE,
}

CANONICAL_ORDER = ("REGULAR", "PRE_MARKET", "POST_MARKET", "OVER_NIGHT")

VALID_SESSIONS = frozenset(CANONICAL_ORDER)
ADDABLE_SESSIONS = frozenset(SCHEDULE_BY_SESSION.keys())

# Exchange suffixes that get rewritten to .BLUE on OVER_NIGHT benchmarkMapping.
# Matches the LSEG/Datascope US-equity convention used in PR #26.
US_EQUITY_EXCHANGE_SUFFIXES = (".O", ".N", ".A", ".K")


def overnight_identifier(reg_identifier: str) -> str:
    """Rewrite a REGULAR-session RIC into the OVER_NIGHT (.BLUE) form.

    e.g. ``"AAPL.O" -> "AAPL.BLUE"``, ``"BRKb.N" -> "BRKb.BLUE"``.

    Returns the input unchanged if no known suffix is present.
    """
    for suffix in US_EQUITY_EXCHANGE_SUFFIXES:
        if reg_identifier.endswith(suffix):
            return reg_identifier[: -len(suffix)] + ".BLUE"
    return reg_identifier
