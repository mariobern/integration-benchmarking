"""Validation helpers for marketSchedule / holidayOverrides token formats.

Pure functions, no I/O, no exceptions raised. Designed for the linter
to embed reason strings into LintFinding messages.
"""

from __future__ import annotations

import re

# Days per month (non-leap-year). 0229 is treated as valid since it is a
# legitimate holiday-override format that may apply on leap years.
_DAYS_PER_MONTH = {
    1: 31,
    2: 29,
    3: 31,
    4: 30,
    5: 31,
    6: 30,
    7: 31,
    8: 31,
    9: 30,
    10: 31,
    11: 30,
    12: 31,
}

_TOKEN_SHAPE = re.compile(r"^(\d{2})(\d{2})/(.+)\Z")
_EXPECTED = "expected MMDD/{C|O|HHMM-HHMM}"


def validate_holiday_token(token: str) -> str | None:
    """Return None if `token` is valid, else a short reason string.

    Currently accepted shapes:
        MMDD/C            (closed)
        MMDD/O            (open)

    MM in 01..12. DD must be a real day for the month (0229 always valid,
    since holiday tokens may apply on leap years).

    The MMDD/HHMM-HHMM (early close / partial open) form is added in a
    follow-up task; it is currently rejected as an unknown kind.
    """
    if not isinstance(token, str):
        return _EXPECTED
    m = _TOKEN_SHAPE.match(token)
    if not m:
        return _EXPECTED
    mm_str, dd_str, kind = m.group(1), m.group(2), m.group(3)
    mm, dd = int(mm_str), int(dd_str)

    if not (1 <= mm <= 12):
        return f"invalid month {mm_str}"
    if not (1 <= dd <= _DAYS_PER_MONTH[mm]):
        return f"invalid day {dd_str} for month {mm_str}"

    if kind in ("C", "O"):
        return None

    # Time-range kind handled in Task 2; for now reject anything else.
    return f"unknown kind {kind!r}"
