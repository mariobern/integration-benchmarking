"""Tests for extract_overnight_candidates.py."""

import csv

from extract_overnight_candidates import (
    build_candidates,
    extract_ticker,
    has_overnight_session,
    is_candidate,
    write_meta,
    write_tickers,
)


def _feed(symbol, state, sessions):
    """Build a minimal feed dict with the given session labels."""
    return {
        "symbol": symbol,
        "state": state,
        "feedId": 100,
        "marketSchedules": [{"session": s} for s in sessions],
    }


class TestHasOvernightSession:
    def test_true_when_overnight_present(self):
        feed = _feed("Equity.US.AAPL/USD", "STABLE", ["REGULAR", "OVER_NIGHT"])
        assert has_overnight_session(feed) is True

    def test_false_when_absent(self):
        feed = _feed("Equity.US.A/USD", "STABLE", ["REGULAR"])
        assert has_overnight_session(feed) is False

    def test_false_when_no_schedules(self):
        assert has_overnight_session({"marketSchedules": []}) is False


class TestExtractTicker:
    def test_simple(self):
        assert extract_ticker("Equity.US.AAPL/USD") == "AAPL"

    def test_dotted(self):
        assert extract_ticker("Equity.US.BRK.B/USD") == "BRK.B"

    def test_uppercased_to_match_volume_profile(self):
        assert extract_ticker("Equity.US.brkb/USD") == "BRKB"

    def test_hk_prefix_and_hkd_quote(self):
        assert extract_ticker("Equity.HK.0002/HKD", "Equity.HK.") == "0002"


class TestIsCandidate:
    def test_stable_no_overnight_included(self):
        assert is_candidate(_feed("Equity.US.A/USD", "STABLE", ["REGULAR"])) is True

    def test_stable_with_overnight_excluded(self):
        feed = _feed("Equity.US.AAPL/USD", "STABLE", ["REGULAR", "OVER_NIGHT"])
        assert is_candidate(feed) is False

    def test_coming_soon_no_overnight_included(self):
        feed = _feed("Equity.US.NEW/USD", "COMING_SOON", ["REGULAR"])
        assert is_candidate(feed) is True

    def test_coming_soon_with_overnight_included(self):
        feed = _feed("Equity.US.NEW/USD", "COMING_SOON", ["REGULAR", "OVER_NIGHT"])
        assert is_candidate(feed) is True

    def test_inactive_excluded(self):
        feed = _feed("Equity.US.DEAD/USD", "INACTIVE", ["REGULAR", "OVER_NIGHT"])
        assert is_candidate(feed) is False

    def test_non_us_equity_excluded(self):
        assert is_candidate(_feed("Crypto.BTC/USD", "STABLE", ["REGULAR"])) is False

    def test_hk_prefix_includes_hk_feed(self):
        feed = _feed("Equity.HK.0002/HKD", "STABLE", ["REGULAR"])
        assert is_candidate(feed, "Equity.HK.") is True

    def test_hk_prefix_excludes_us_feed(self):
        feed = _feed("Equity.US.A/USD", "STABLE", ["REGULAR"])
        assert is_candidate(feed, "Equity.HK.") is False


class TestBuildCandidates:
    def test_rows_and_flag(self):
        feeds = [
            _feed("Equity.US.A/USD", "STABLE", ["REGULAR"]),
            _feed("Equity.US.AAPL/USD", "STABLE", ["REGULAR", "OVER_NIGHT"]),
            _feed("Equity.US.NEW/USD", "COMING_SOON", ["REGULAR", "OVER_NIGHT"]),
            _feed("Crypto.BTC/USD", "STABLE", ["REGULAR"]),
        ]
        rows = build_candidates(feeds)
        tickers = [r["ticker"] for r in rows]
        assert tickers == [
            "A",
            "NEW",
        ]  # AAPL (stable+overnight) and BTC excluded; sorted
        by_ticker = {r["ticker"]: r for r in rows}
        assert by_ticker["A"]["overnight_configured"] is False
        assert by_ticker["NEW"]["overnight_configured"] is True
        assert by_ticker["NEW"]["state"] == "COMING_SOON"

    def test_prefix_selects_only_that_namespace(self):
        feeds = [
            _feed("Equity.US.A/USD", "STABLE", ["REGULAR"]),
            _feed("Equity.HK.0002/HKD", "STABLE", ["REGULAR"]),
            _feed("Equity.HK.0005/HKD", "COMING_SOON", ["REGULAR"]),
        ]
        rows = build_candidates(feeds, "Equity.HK.")
        assert [r["ticker"] for r in rows] == ["0002", "0005"]


class TestWriters:
    def test_write_tickers_one_per_line(self, tmp_path):
        rows = [{"ticker": "A"}, {"ticker": "NEW"}]
        path = tmp_path / "t.txt"
        write_tickers(rows, path)
        assert path.read_text().splitlines() == ["A", "NEW"]

    def test_write_meta_roundtrip(self, tmp_path):
        rows = [
            {
                "ticker": "A",
                "feedId": 1,
                "state": "STABLE",
                "overnight_configured": False,
            },
        ]
        path = tmp_path / "m.csv"
        write_meta(rows, path)
        with open(path) as f:
            got = list(csv.DictReader(f))
        assert got[0]["ticker"] == "A"
        assert got[0]["overnight_configured"] == "False"
