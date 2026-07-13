"""Tests for marketSchedule string parsing and open-minute masks."""
from datetime import datetime, timezone

import pandas as pd
import pytest

from lazer_dq.market_schedule import (
    MarketSchedule,
    build_exchanges_by_id,
    open_minutes_mask,
    parse_market_schedule,
    resolve_schedule_string,
)

UTC = timezone.utc

NASDAQ_REGULAR = (
    "America/New_York;0930-1600,0930-1600,0930-1600,0930-1600,0930-1600,C,C;"
    "0101/C,0703/C,1127/0930-1300"
)
CRYPTO_247 = "America/New_York;O,O,O,O,O,O,O;"
FX_STYLE = "America/New_York;O,O,O,O,0000-1700,C,1700-2400;1224/0000-1700"
OVERNIGHT = (
    "America/New_York;0000-0400&2000-2400,0000-0400&2000-2400,0000-0400&2000-2400,"
    "0000-0400&2000-2400,0000-0400,C,2000-2400;"
)
MIDNIGHT_END = "America/New_York;0900-1700,0900-1700,0900-1700,0900-1700,1700-0000,C,C;"


def test_parse_basic_fields():
    s = parse_market_schedule(NASDAQ_REGULAR)
    assert s.tz == "America/New_York"
    assert s.days[0] == ((9 * 60 + 30, 16 * 60),)  # Monday
    assert s.days[5] == ()  # Saturday closed
    assert s.overrides["0101"] == ()
    assert s.overrides["1127"] == ((9 * 60 + 30, 13 * 60),)


def test_parse_open_and_ampersand():
    s = parse_market_schedule(OVERNIGHT)
    assert s.days[0] == ((0, 4 * 60), (20 * 60, 1440))
    assert parse_market_schedule(CRYPTO_247).days[6] == ((0, 1440),)


def test_parse_rejects_malformed():
    with pytest.raises(ValueError):
        parse_market_schedule("America/New_York;O,O,O")  # not 7 day entries
    with pytest.raises(ValueError):
        parse_market_schedule("no-semicolons-here")


def test_mask_regular_monday():
    # 2026-07-06 is a Monday; EDT = UTC-4, so 09:30 ET = 13:30 UTC.
    s = parse_market_schedule(NASDAQ_REGULAR)
    start = datetime(2026, 7, 6, tzinfo=UTC)
    end = datetime(2026, 7, 7, tzinfo=UTC)
    mask = open_minutes_mask(s, start, end)
    assert len(mask) == 1440
    assert bool(mask[pd.Timestamp("2026-07-06 13:30", tz="UTC")]) is True
    assert bool(mask[pd.Timestamp("2026-07-06 13:29", tz="UTC")]) is False
    assert bool(mask[pd.Timestamp("2026-07-06 19:59", tz="UTC")]) is True
    assert bool(mask[pd.Timestamp("2026-07-06 20:00", tz="UTC")]) is False
    # Total: 6.5 hours = 390 open minutes
    assert int(mask.sum()) == 390


def test_mask_holiday_override_closes_day():
    # 2026-07-03 is a Friday but 0703/C closes it.
    s = parse_market_schedule(NASDAQ_REGULAR)
    mask = open_minutes_mask(
        s, datetime(2026, 7, 3, tzinfo=UTC), datetime(2026, 7, 4, tzinfo=UTC)
    )
    assert int(mask.sum()) == 0


def test_mask_247():
    s = parse_market_schedule(CRYPTO_247)
    mask = open_minutes_mask(
        s, datetime(2026, 7, 4, tzinfo=UTC), datetime(2026, 7, 6, tzinfo=UTC)
    )
    assert int(mask.sum()) == 2880  # every minute open, incl. weekend


def test_mask_fx_sunday_open():
    # Sunday entry 1700-2400 ET: 2026-07-12 is a Sunday. 17:00 EDT = 21:00 UTC.
    s = parse_market_schedule(FX_STYLE)
    mask = open_minutes_mask(
        s, datetime(2026, 7, 12, tzinfo=UTC), datetime(2026, 7, 13, 4, tzinfo=UTC)
    )
    assert bool(mask[pd.Timestamp("2026-07-12 20:59", tz="UTC")]) is False
    assert bool(mask[pd.Timestamp("2026-07-12 21:00", tz="UTC")]) is True
    # Monday 00:00 ET (04:00 UTC Mon) is 'O' so still open at end of range
    assert bool(mask[pd.Timestamp("2026-07-13 03:59", tz="UTC")]) is True


def test_resolve_schedule_inline_and_inherited():
    config = {
        "exchanges": [
            {
                "exchangeId": 21,
                "sessions": [{"session": "REGULAR", "marketSchedule": NASDAQ_REGULAR}],
            }
        ]
    }
    ex_by_id = build_exchanges_by_id(config)
    inline_feed = {"feedId": 1}
    inline_entry = {"session": "REGULAAR-ignored", "marketSchedule": CRYPTO_247}
    assert resolve_schedule_string(inline_feed, inline_entry, ex_by_id) == CRYPTO_247

    inherited_feed = {"feedId": 884, "exchangeId": 21}
    inherited_entry = {"session": "REGULAR"}
    assert (
        resolve_schedule_string(inherited_feed, inherited_entry, ex_by_id)
        == NASDAQ_REGULAR
    )
    # No exchangeId and no inline string -> None
    assert (
        resolve_schedule_string({"feedId": 9}, {"session": "REGULAR"}, ex_by_id) is None
    )


def test_parse_midnight_end_as_0000():
    # Regression: real configs use 0000 to mean end-of-day (like 2400)
    s = parse_market_schedule(MIDNIGHT_END)
    assert s.days[4] == ((17 * 60, 1440),)  # Friday 17:00-24:00 (0000)
    assert s.days[5] == ()  # Saturday closed


def test_parse_rejects_invalid_hhmm_minutes():
    # "0165" has MM=65 which is invalid (MM must be <= 59)
    bad_schedule = "America/New_York;0165-1600,C,C,C,C,C,C;"
    with pytest.raises(ValueError, match="bad HHMM token"):
        parse_market_schedule(bad_schedule)


def test_parse_rejects_invalid_override_date():
    # "1332" has month=13 which is invalid (month must be 01-12)
    bad_schedule = "America/New_York;C,C,C,C,C,C,C;1332/C"
    with pytest.raises(ValueError, match="bad override date"):
        parse_market_schedule(bad_schedule)


def test_parse_2400_as_range_end_still_works():
    # "2400" at end of range should parse to 1440, not fail
    schedule = "America/New_York;0930-2400,C,C,C,C,C,C;"
    s = parse_market_schedule(schedule)
    assert s.days[0] == ((9 * 60 + 30, 1440),)
