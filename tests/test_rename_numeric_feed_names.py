"""Tests for rename_numeric_feed_names.py."""

from rename_numeric_feed_names import (
    derive_name,
    in_scope,
    is_candidate,
)


def _feed(
    feed_id=100,
    symbol="Equity.CN.688825/CNY",
    name="688825",
    description="CHANGXIN MEMORY TECHNOLOGIES / CHINESE YUAN",
    quote_currency="CNY",
):
    """Build a minimal feed dict shaped like a lazer-state.json entry."""
    return {
        "feedId": feed_id,
        "symbol": symbol,
        "state": "STABLE",
        "metadata": {
            "asset_type": "equity",
            "description": description,
            "name": name,
            "quote_currency": quote_currency,
        },
    }


class TestInScope:
    def test_cn_prefix_in_scope(self):
        assert in_scope(_feed()) is True

    def test_us_prefix_out_of_scope(self):
        assert in_scope(_feed(symbol="Equity.US.AAPL/USD")) is False

    def test_custom_prefixes_respected(self):
        assert in_scope(_feed(), prefixes=("Equity.JP.",)) is False


class TestIsCandidate:
    def test_numeric_name_is_candidate(self):
        assert is_candidate(_feed()) is True

    def test_numeric_with_trailing_letter_is_candidate(self):
        assert is_candidate(_feed(name="0700A")) is True

    def test_already_renamed_is_not_candidate(self):
        assert is_candidate(_feed(name="CHANGXIN MEMORY TECHNOLOGIES")) is False

    def test_alphanumeric_futures_code_is_not_candidate(self):
        assert is_candidate(_feed(symbol="Equity.KR.KSM6/KRW", name="KSM6")) is False

    def test_out_of_scope_never_candidate(self):
        assert is_candidate(_feed(symbol="Equity.US.AAPL/USD", name="123")) is False


class TestDeriveName:
    def test_happy_path(self):
        name, reason = derive_name(_feed())
        assert name == "CHANGXIN MEMORY TECHNOLOGIES"
        assert reason is None

    def test_strips_trailing_whitespace(self):
        feed = _feed(
            symbol="Equity.KR.001040/KRW",
            description="CJ CORP  / SOUTH KOREAN WON",
            quote_currency="KRW",
        )
        name, reason = derive_name(feed)
        assert name == "CJ CORP"
        assert reason is None

    def test_splits_on_last_separator(self):
        feed = _feed(description="FOO / BAR CORP / CHINESE YUAN")
        name, reason = derive_name(feed)
        assert name == "FOO / BAR CORP"
        assert reason is None

    def test_currency_mismatch_is_skipped(self):
        feed = _feed(description="SOME CORP / US DOLLAR")
        name, reason = derive_name(feed)
        assert name is None
        assert "does not match expected" in reason

    def test_unmapped_currency_is_skipped(self):
        feed = _feed(
            symbol="Equity.TW.2330/TWD",
            description="TSMC / TAIWAN DOLLAR",
            quote_currency="TWD",
        )
        name, reason = derive_name(feed)
        assert name is None
        assert "no currency name mapped" in reason

    def test_missing_separator_is_skipped(self):
        feed = _feed(description="CHANGXIN MEMORY TECHNOLOGIES")
        name, reason = derive_name(feed)
        assert name is None
        assert "separator" in reason

    def test_empty_derived_name_is_skipped(self):
        feed = _feed(description=" / CHINESE YUAN")
        name, reason = derive_name(feed)
        assert name is None
        assert "empty" in reason
