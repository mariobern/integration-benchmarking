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
