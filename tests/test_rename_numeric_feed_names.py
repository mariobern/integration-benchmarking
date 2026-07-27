"""Tests for rename_numeric_feed_names.py."""

import pytest

from rename_numeric_feed_names import (
    Change,
    OverrideError,
    build_changes,
    derive_name,
    find_duplicate_names,
    in_scope,
    is_candidate,
    load_overrides,
    validate_overrides,
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


def _write_csv(tmp_path, text):
    path = tmp_path / "overrides.csv"
    path.write_text(text, encoding="utf-8")
    return path


class TestLoadOverrides:
    def test_parses_rows(self, tmp_path):
        path = _write_csv(tmp_path, "feed_id,name\n3520,CXMT\n3360,GIGA (HK)\n")
        assert load_overrides(path) == {3520: "CXMT", 3360: "GIGA (HK)"}

    def test_strips_whitespace(self, tmp_path):
        path = _write_csv(tmp_path, "feed_id,name\n 3520 , CXMT \n")
        assert load_overrides(path) == {3520: "CXMT"}

    def test_skips_fully_blank_rows(self, tmp_path):
        path = _write_csv(tmp_path, "feed_id,name\n3520,CXMT\n,\n")
        assert load_overrides(path) == {3520: "CXMT"}

    def test_missing_file_is_error(self, tmp_path):
        with pytest.raises(OverrideError, match="not found"):
            load_overrides(tmp_path / "nope.csv")

    def test_missing_column_is_error(self, tmp_path):
        path = _write_csv(tmp_path, "feed_id\n3520\n")
        with pytest.raises(OverrideError, match="missing required column"):
            load_overrides(path)

    def test_non_integer_feed_id_is_error(self, tmp_path):
        path = _write_csv(tmp_path, "feed_id,name\nabc,CXMT\n")
        with pytest.raises(OverrideError, match="not an integer"):
            load_overrides(path)

    def test_empty_name_is_error(self, tmp_path):
        path = _write_csv(tmp_path, "feed_id,name\n3520,\n")
        with pytest.raises(OverrideError, match="name is empty"):
            load_overrides(path)

    def test_duplicate_feed_id_is_error(self, tmp_path):
        path = _write_csv(tmp_path, "feed_id,name\n3520,CXMT\n3520,OTHER\n")
        with pytest.raises(OverrideError, match="duplicate feed_id"):
            load_overrides(path)


class TestValidateOverrides:
    def test_in_scope_feed_accepted(self):
        feeds = [_feed(feed_id=3520)]
        validate_overrides({3520: "CXMT"}, feeds)

    def test_already_renamed_feed_accepted(self):
        feeds = [_feed(feed_id=3520, name="CHANGXIN MEMORY TECHNOLOGIES")]
        validate_overrides({3520: "CXMT"}, feeds)

    def test_unknown_feed_id_is_error(self):
        with pytest.raises(OverrideError, match="not found in config"):
            validate_overrides({999: "X"}, [_feed(feed_id=3520)])

    def test_out_of_prefix_feed_is_error(self):
        feeds = [_feed(feed_id=922, symbol="Equity.US.AAPL/USD")]
        with pytest.raises(OverrideError, match="outside the configured"):
            validate_overrides({922: "APPLE"}, feeds)


class TestBuildChanges:
    def test_derives_name_for_candidate(self):
        changes, skips = build_changes([_feed(feed_id=3520)])
        assert skips == []
        assert changes == [
            Change(
                feed_id=3520,
                symbol="Equity.CN.688825/CNY",
                before="688825",
                after="CHANGXIN MEMORY TECHNOLOGIES",
                source="rule",
            )
        ]

    def test_out_of_scope_feed_untouched(self):
        feeds = [_feed(feed_id=922, symbol="Equity.US.AAPL/USD", name="AAPL")]
        changes, skips = build_changes(feeds)
        assert changes == []
        assert skips == []

    def test_already_renamed_feed_is_noop(self):
        feeds = [_feed(feed_id=3520, name="CHANGXIN MEMORY TECHNOLOGIES")]
        changes, skips = build_changes(feeds)
        assert changes == []
        assert skips == []

    def test_idempotent_second_pass(self):
        feeds = [_feed(feed_id=3520)]
        changes, _ = build_changes(feeds)
        feeds[0]["metadata"]["name"] = changes[0].after
        changes_again, skips_again = build_changes(feeds)
        assert changes_again == []
        assert skips_again == []

    def test_undeliverable_description_is_skipped(self):
        feeds = [_feed(feed_id=3520, description="SOME CORP / US DOLLAR")]
        changes, skips = build_changes(feeds)
        assert changes == []
        assert len(skips) == 1
        assert skips[0].feed_id == 3520

    def test_override_beats_derived_name(self):
        changes, skips = build_changes([_feed(feed_id=3520)], overrides={3520: "CXMT"})
        assert skips == []
        assert changes[0].after == "CXMT"
        assert changes[0].source == "override"

    def test_override_applies_to_already_renamed_feed(self):
        feeds = [_feed(feed_id=3520, name="CHANGXIN MEMORY TECHNOLOGIES")]
        changes, _ = build_changes(feeds, overrides={3520: "CXMT"})
        assert changes[0].before == "CHANGXIN MEMORY TECHNOLOGIES"
        assert changes[0].after == "CXMT"

    def test_override_matching_current_name_is_noop(self):
        changes, _ = build_changes([_feed(feed_id=3520)], overrides={3520: "688825"})
        assert changes == []

    def test_override_skips_currency_validation(self):
        feeds = [_feed(feed_id=3520, description="BROKEN DESCRIPTION")]
        changes, skips = build_changes(feeds, overrides={3520: "CXMT"})
        assert skips == []
        assert changes[0].after == "CXMT"


class TestFindDuplicateNames:
    def test_reports_dual_listing(self):
        feeds = [
            _feed(
                feed_id=3339,
                symbol="Equity.CN.603986/CNY",
                name="603986",
                description="GIGADEVICE SEMICONDUCTOR INC / CHINESE YUAN",
            ),
            _feed(
                feed_id=3360,
                symbol="Equity.HK.3986/HKD",
                name="3986",
                description="GIGADEVICE SEMICONDUCTOR INC / HONG KONG DOLLAR",
                quote_currency="HKD",
            ),
        ]
        changes, _ = build_changes(feeds)
        duplicates = find_duplicate_names(feeds, changes)
        assert duplicates == [
            (
                "GIGADEVICE SEMICONDUCTOR INC",
                [(3339, "Equity.CN.603986/CNY"), (3360, "Equity.HK.3986/HKD")],
            )
        ]

    def test_overrides_clear_the_duplicate(self):
        feeds = [
            _feed(
                feed_id=3339,
                symbol="Equity.CN.603986/CNY",
                name="603986",
                description="GIGADEVICE SEMICONDUCTOR INC / CHINESE YUAN",
            ),
            _feed(
                feed_id=3360,
                symbol="Equity.HK.3986/HKD",
                name="3986",
                description="GIGADEVICE SEMICONDUCTOR INC / HONG KONG DOLLAR",
                quote_currency="HKD",
            ),
        ]
        overrides = {
            3339: "GIGADEVICE SEMICONDUCTOR INC (CN)",
            3360: "GIGADEVICE SEMICONDUCTOR INC (HK)",
        }
        changes, _ = build_changes(feeds, overrides=overrides)
        assert find_duplicate_names(feeds, changes) == []

    def test_preexisting_duplicate_not_reported_when_untouched(self):
        feeds = [
            _feed(feed_id=979, symbol="Equity.US.BA/USD", name="BA"),
            _feed(feed_id=790, symbol="Equity.GB.BA/GBP", name="BA"),
        ]
        assert find_duplicate_names(feeds, changes=[]) == []

    def test_collision_with_untouched_feed_is_reported(self):
        feeds = [
            _feed(feed_id=3520),
            _feed(
                feed_id=3293,
                symbol="Equity.US.CXMT/USD",
                name="CHANGXIN MEMORY TECHNOLOGIES",
            ),
        ]
        changes, _ = build_changes(feeds)
        duplicates = find_duplicate_names(feeds, changes)
        assert len(duplicates) == 1
        assert duplicates[0][0] == "CHANGXIN MEMORY TECHNOLOGIES"
