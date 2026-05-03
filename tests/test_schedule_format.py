"""Tests for lib/schedule_format.py."""

import pytest

from lib.schedule_format import validate_holiday_token


class TestBasicKinds:
    @pytest.mark.parametrize("token", ["0101/C", "0619/O", "1225/C", "0229/C"])
    def test_valid_kind(self, token):
        assert validate_holiday_token(token) is None


class TestInvalidKind:
    @pytest.mark.parametrize("token", ["0101/X", "0101/Z", "0101/"])
    def test_unknown_kind(self, token):
        result = validate_holiday_token(token)
        assert result is not None
        assert "unknown kind" in result or "expected MMDD/" in result

    def test_unknown_single_letter_kind_says_unknown(self):
        # Single-letter typos are 'unknown kind', not 'malformed time range'.
        # The kind doesn't look like a time range, so the message reflects that.
        result = validate_holiday_token("0101/X")
        assert result is not None
        assert "unknown kind" in result
        assert "X" in result


class TestInvalidMonth:
    @pytest.mark.parametrize("token", ["1340/C", "0001/C", "1301/C"])
    def test_invalid_month(self, token):
        result = validate_holiday_token(token)
        assert result is not None
        assert "invalid month" in result


class TestInvalidDay:
    @pytest.mark.parametrize(
        "token",
        ["0230/C", "0431/C", "0532/C", "0100/C"],
    )
    def test_invalid_day(self, token):
        result = validate_holiday_token(token)
        assert result is not None
        assert "invalid day" in result


class TestMalformedShape:
    @pytest.mark.parametrize(
        "token",
        ["315/C", "01015/C", "0101", "0101C", ""],
    )
    def test_malformed(self, token):
        result = validate_holiday_token(token)
        assert result is not None
        assert "expected MMDD/" in result

    def test_trailing_newline_rejected(self):
        # \Z anchor (not $) rejects tokens with a trailing newline.
        result = validate_holiday_token("0101/C\n")
        assert result is not None
        assert "expected MMDD/" in result


class TestTimeRange:
    @pytest.mark.parametrize(
        "token",
        [
            "0703/0930-1300",
            "0703/0000-2400",
            "0703/0930-2400",
        ],
    )
    def test_valid_time_range(self, token):
        assert validate_holiday_token(token) is None

    @pytest.mark.parametrize(
        "token",
        ["0703/0930-1", "0703/0930-25"],
    )
    def test_malformed_time_range(self, token):
        result = validate_holiday_token(token)
        assert result is not None
        # These don't match the full HHMM-HHMM shape so the dispatch returns
        # "unknown kind" rather than "malformed time range" — either is valid.
        assert "malformed time range" in result or "unknown kind" in result

    def test_invalid_hour(self):
        # Hour 25 is invalid even with full MMHH form
        result = validate_holiday_token("0703/0930-2500")
        assert result is not None
        assert "malformed time range" in result

    @pytest.mark.parametrize(
        "token",
        [
            "0703/0930-0930",  # zero-length
            "0703/2400-0000",  # reversed (start would be 24:00 anyway)
            "0703/1300-0930",  # end < start
        ],
    )
    def test_reversed_time_range(self, token):
        result = validate_holiday_token(token)
        assert result is not None
        # Either malformed (24:00 in start position) or reversed
        assert "reversed time range" in result or "malformed time range" in result

    def test_24_00_only_at_end(self):
        # 24:30 is invalid — when HH=24, MM must be 00
        result = validate_holiday_token("0703/0930-2430")
        assert result is not None
        assert "malformed time range" in result
