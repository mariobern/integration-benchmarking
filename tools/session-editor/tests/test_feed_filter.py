"""Eligibility predicate + session lookup helpers."""

from session_editor_lib.feed_filter import find_regular, find_session, is_us_equity


def test_aapl_is_us_equity(aapl_feed):
    assert is_us_equity(aapl_feed)


def test_equity_a_is_us_equity(equity_a_feed):
    assert is_us_equity(equity_a_feed)


def test_btc_is_not_us_equity(btc_feed):
    assert not is_us_equity(btc_feed)


def test_find_regular_present(aapl_feed):
    reg = find_regular(aapl_feed)
    assert reg is not None
    assert reg["session"] == "REGULAR"


def test_find_session_absent(abnb_feed):
    assert find_session(abnb_feed, "OVER_NIGHT") is None


def test_find_session_present(aapl_feed):
    s = find_session(aapl_feed, "POST_MARKET")
    assert s is not None
    assert s["session"] == "POST_MARKET"
