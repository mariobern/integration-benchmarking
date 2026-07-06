"""Unit tests for the RIC / benchmark-identifier resolver."""
import json

import pytest

from lazer_dq.benchmark_identifiers import (
    SESSION_BY_MODE,
    resolve_benchmark_identifier,
    session_for_mode,
)


def _schedules(session, identifiers, key="datascope_ric"):
    return [
        {
            "session": session,
            "benchmarkMapping": {key: {"identifiers": identifiers}},
        }
    ]


# ---- session_for_mode ----


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("us-equities", "REGULAR"),
        ("us-equities-pre", "PRE_MARKET"),
        ("us-equities-post", "POST_MARKET"),
        ("us-equities-on", "OVER_NIGHT"),
        ("us-equities-overnight", "OVER_NIGHT"),
        ("fx", "REGULAR"),
        ("metals", "REGULAR"),
        ("us-futures", "REGULAR"),
        ("us-treasuries-yield", "REGULAR"),
        ("us-treasuries-price", "REGULAR"),
        ("something-unknown", "REGULAR"),
    ],
)
def test_session_for_mode(mode, expected):
    assert session_for_mode(mode) == expected


# ---- resolve_benchmark_identifier ----


def test_resolves_single_identifier():
    ms = _schedules(
        "REGULAR", [{"identifier": "AAPL.O", "validFrom": "1970-01-01T00:00:00Z"}]
    )
    assert resolve_benchmark_identifier(ms, "REGULAR") == "AAPL.O"


def test_picks_most_recent_validfrom():
    ms = _schedules(
        "REGULAR",
        [
            {"identifier": "OLD.O", "validFrom": "2020-01-01T00:00:00Z"},
            {"identifier": "NEW.O", "validFrom": "2026-01-01T00:00:00Z"},
        ],
    )
    assert resolve_benchmark_identifier(ms, "REGULAR") == "NEW.O"


def test_overnight_session_isolated_from_regular():
    ms = [
        {
            "session": "REGULAR",
            "benchmarkMapping": {
                "datascope_ric": {
                    "identifiers": [
                        {"identifier": "AAPL.O", "validFrom": "1970-01-01T00:00:00Z"}
                    ]
                }
            },
        },
        {
            "session": "OVER_NIGHT",
            "benchmarkMapping": {
                "datascope_ric": {
                    "identifiers": [
                        {"identifier": "AAPL.BLUE", "validFrom": "1970-01-01T00:00:00Z"}
                    ]
                }
            },
        },
    ]
    assert resolve_benchmark_identifier(ms, "OVER_NIGHT") == "AAPL.BLUE"
    assert resolve_benchmark_identifier(ms, "REGULAR") == "AAPL.O"


def test_parses_json_string_input():
    ms = json.dumps(
        _schedules(
            "REGULAR", [{"identifier": "EUR=", "validFrom": "1970-01-01T00:00:00Z"}]
        )
    )
    assert resolve_benchmark_identifier(ms, "REGULAR") == "EUR="


def test_missing_session_returns_none():
    ms = _schedules(
        "REGULAR", [{"identifier": "AAPL.O", "validFrom": "1970-01-01T00:00:00Z"}]
    )
    assert resolve_benchmark_identifier(ms, "PRE_MARKET") is None


def test_missing_mapping_returns_none():
    assert resolve_benchmark_identifier([{"session": "REGULAR"}], "REGULAR") is None


def test_empty_identifiers_returns_none():
    ms = _schedules("REGULAR", [])
    assert resolve_benchmark_identifier(ms, "REGULAR") is None


def test_none_input_returns_none():
    assert resolve_benchmark_identifier(None, "REGULAR") is None


def test_invalid_json_string_returns_none():
    assert resolve_benchmark_identifier("{not valid json", "REGULAR") is None


def test_crypto_coinpaprika_not_matched_by_datascope_ric():
    # Crypto feeds carry coinpaprika_symbol, NOT datascope_ric.
    ms = _schedules(
        "REGULAR",
        [{"identifier": "btc-bitcoin", "validFrom": "1970-01-01T00:00:00Z"}],
        key="coinpaprika_symbol",
    )
    assert (
        resolve_benchmark_identifier(ms, "REGULAR") is None
    )  # default key = datascope_ric
    assert (
        resolve_benchmark_identifier(ms, "REGULAR", identifier_key="coinpaprika_symbol")
        == "btc-bitcoin"
    )
