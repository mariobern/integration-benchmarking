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

    Accepted shapes:
        MMDD/C            (closed)
        MMDD/O            (open)
        MMDD/HHMM-HHMM    (early close / partial open)

    MM in 01..12. DD must be a real day for the month (0229 always valid,
    since holiday tokens may apply on leap years).

    For the time-range form: start has HH in 00..23 and MM in 00..59;
    end has HH in 00..24 and MM in 00..59 (if HH=24 then MM must be 00,
    representing end-of-day, matching the boundary used in feed-level
    marketSchedule strings like "1700-2400" or "2000-2400"); end > start
    as a 4-digit integer; equal or reversed ranges are rejected.
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

    return _validate_time_range(kind)


_TIME_RANGE = re.compile(r"^(\d{2})(\d{2})-(\d{2})(\d{2})\Z")


def _validate_time_range(kind: str) -> str | None:
    m = _TIME_RANGE.match(kind)
    if not m:
        return f"malformed time range {kind!r}"
    s_h, s_m, e_h, e_m = (int(m.group(i)) for i in range(1, 5))

    # Start: HH 00..23, MM 00..59
    if not (0 <= s_h <= 23 and 0 <= s_m <= 59):
        return f"malformed time range {kind!r}"
    # End: HH 00..24, MM 00..59; if HH=24 then MM must be 0
    if not (0 <= e_h <= 24 and 0 <= e_m <= 59):
        return f"malformed time range {kind!r}"
    if e_h == 24 and e_m != 0:
        return f"malformed time range {kind!r}"

    start = s_h * 100 + s_m
    end = e_h * 100 + e_m
    if end <= start:
        return f"reversed time range {kind!r}"
    return None
