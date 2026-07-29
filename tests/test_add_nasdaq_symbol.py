"""Tests for add_nasdaq_symbol.py."""

from add_nasdaq_symbol import (
    ASIAN_MARKET_PREFIXES,
    Change,
    Skip,
    build_changes,
    plan_change,
    apply_changes,
)


def _feed(
    feed_id=100,
    symbol="Equity.CN.688825/CNY",
    name="688825",
    nasdaq_symbol=None,
):
    """Build a minimal feed dict shaped like a lazer_jpkr.json entry."""
    metadata = {
        "asset_type": "equity",
        "description": "CHANGXIN MEMORY TECHNOLOGIES / CHINESE YUAN",
        "name": name,
        "quote_currency": "CNY",
    }
    if nasdaq_symbol is not None:
        metadata["nasdaq_symbol"] = nasdaq_symbol
    return {
        "feedId": feed_id,
        "symbol": symbol,
        "state": "STABLE",
        "metadata": metadata,
    }


class TestAsianMarketPrefixes:
    def test_includes_all_five_markets(self):
        assert ASIAN_MARKET_PREFIXES == (
            "Equity.HK.",
            "Equity.CN.",
            "Equity.JP.",
            "Equity.KR.",
            "Equity.IN.",
        )


class TestPlanChange:
    def test_numeric_name_becomes_change(self):
        change, skip = plan_change(_feed())
        assert skip is None
        assert change == Change(
            feed_id=100, symbol="Equity.CN.688825/CNY", name="688825"
        )

    def test_alphanumeric_code_becomes_change(self):
        change, skip = plan_change(
            _feed(symbol="Equity.IN.NIFTYBEES/INR", name="NIFTYBEES")
        )
        assert skip is None
        assert change.name == "NIFTYBEES"

    def test_hyphenated_code_becomes_change(self):
        change, skip = plan_change(
            _feed(symbol="Equity.JP.1321-JP/JPY", name="1321-JP")
        )
        assert skip is None
        assert change.name == "1321-JP"

    def test_already_set_is_skipped(self):
        change, skip = plan_change(_feed(nasdaq_symbol="688825"))
        assert change is None
        assert skip == Skip(
            feed_id=100,
            symbol="Equity.CN.688825/CNY",
            reason="nasdaq_symbol already set",
        )

    def test_already_set_is_skipped_even_if_stale(self):
        # Even a mismatched existing value is left alone -- idempotent, not "fix on rerun".
        change, skip = plan_change(_feed(nasdaq_symbol="WRONG"))
        assert change is None
        assert skip.reason == "nasdaq_symbol already set"

    def test_empty_name_is_skipped(self):
        change, skip = plan_change(_feed(name=""))
        assert change is None
        assert "metadata.name is empty" in skip.reason

    def test_name_with_space_is_skipped(self):
        change, skip = plan_change(_feed(name="CHANGXIN MEMORY TECHNOLOGIES"))
        assert change is None
        assert "whitespace" in skip.reason

    def test_name_with_internal_space_is_skipped(self):
        change, skip = plan_change(_feed(name="GIGADEVICE SEMICONDUCTOR INC (CN)"))
        assert change is None
        assert "whitespace" in skip.reason


class TestBuildChanges:
    def test_in_scope_cn_feed_produces_change(self):
        changes, skips = build_changes([_feed(feed_id=3520)])
        assert skips == []
        assert changes == [
            Change(feed_id=3520, symbol="Equity.CN.688825/CNY", name="688825")
        ]

    def test_default_scope_includes_india(self):
        feed = _feed(feed_id=3363, symbol="Equity.IN.NIFTYBEES/INR", name="NIFTYBEES")
        changes, skips = build_changes([feed])
        assert skips == []
        assert changes == [
            Change(feed_id=3363, symbol="Equity.IN.NIFTYBEES/INR", name="NIFTYBEES")
        ]

    def test_out_of_scope_feed_untouched(self):
        feeds = [_feed(feed_id=922, symbol="Equity.US.AAPL/USD", name="AAPL")]
        changes, skips = build_changes(feeds)
        assert changes == []
        assert skips == []

    def test_custom_prefixes_narrow_scope(self):
        feeds = [
            _feed(feed_id=3520),
            _feed(feed_id=884, symbol="Equity.HK.0002/HKD", name="0002"),
        ]
        changes, _ = build_changes(feeds, prefixes=("Equity.HK.",))
        assert [c.feed_id for c in changes] == [884]

    def test_mixed_changes_and_skips(self):
        feeds = [
            _feed(feed_id=3520),
            _feed(feed_id=3521, name="ALREADY MULTI WORD"),
        ]
        changes, skips = build_changes(feeds)
        assert [c.feed_id for c in changes] == [3520]
        assert [s.feed_id for s in skips] == [3521]


def _config(*feeds):
    return {"feeds": list(feeds)}


class TestApplyChanges:
    def test_sets_nasdaq_symbol(self):
        data = _config(_feed(feed_id=3520))
        changes, _ = build_changes(data["feeds"])
        apply_changes(data, changes)
        assert data["feeds"][0]["metadata"]["nasdaq_symbol"] == "688825"

    def test_other_fields_untouched(self):
        data = _config(_feed(feed_id=3520))
        changes, _ = build_changes(data["feeds"])
        apply_changes(data, changes)
        metadata = data["feeds"][0]["metadata"]
        assert metadata["name"] == "688825"
        assert metadata["description"] == "CHANGXIN MEMORY TECHNOLOGIES / CHINESE YUAN"
        assert metadata["quote_currency"] == "CNY"

    def test_symbol_untouched(self):
        data = _config(_feed(feed_id=3520))
        changes, _ = build_changes(data["feeds"])
        apply_changes(data, changes)
        assert data["feeds"][0]["symbol"] == "Equity.CN.688825/CNY"

    def test_metadata_keys_are_alphabetically_sorted(self):
        data = _config(_feed(feed_id=3520))
        changes, _ = build_changes(data["feeds"])
        apply_changes(data, changes)
        keys = list(data["feeds"][0]["metadata"].keys())
        assert keys == sorted(keys)
        assert keys == [
            "asset_type",
            "description",
            "name",
            "nasdaq_symbol",
            "quote_currency",
        ]

    def test_untouched_feed_not_mutated(self):
        data = _config(
            _feed(feed_id=3520),
            _feed(feed_id=922, symbol="Equity.US.AAPL/USD", name="AAPL"),
        )
        changes, _ = build_changes(data["feeds"])
        apply_changes(data, changes)
        assert "nasdaq_symbol" not in data["feeds"][1]["metadata"]
