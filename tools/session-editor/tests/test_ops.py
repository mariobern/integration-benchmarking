"""AddSession / RemoveSession ops."""

import pytest

from session_editor_lib.feed_filter import find_session
from session_editor_lib.ops import AddSession, RemoveSession


# ---- construction validation ------------------------------------------------


def test_add_session_invalid_session_rejected():
    with pytest.raises(ValueError, match="not addable"):
        AddSession(session="WEEKEND")


def test_add_session_regular_not_addable():
    with pytest.raises(ValueError, match="not addable"):
        AddSession(session="REGULAR")


def test_add_session_zero_min_publishers_rejected():
    with pytest.raises(ValueError, match="min_publishers must be >= 1"):
        AddSession(session="OVER_NIGHT", min_publishers=0)


def test_remove_session_invalid_rejected():
    with pytest.raises(ValueError, match="not a valid session"):
        RemoveSession(session="BOGUS")


# ---- AddSession behavior ----------------------------------------------------


class TestAddSession:
    def test_adds_overnight_to_abnb(self, abnb_feed):
        op = AddSession(session="OVER_NIGHT", min_publishers=100)
        outcome = op.apply(abnb_feed)

        assert outcome.action == "added"
        new = find_session(abnb_feed, "OVER_NIGHT")
        assert new is not None
        assert new["allowedPublisherIds"] == []
        assert new["minPublishers"] == 100
        # ABNB's REGULAR RIC is ABNB.O -> ABNB.BLUE on OVER_NIGHT
        ident = new["benchmarkMapping"]["datascope_ric"]["identifiers"][0]["identifier"]
        assert ident == "ABNB.BLUE"

    def test_canonical_insertion_order(self, abnb_feed):
        # ABNB starts: REGULAR, PRE_MARKET, POST_MARKET. Add OVER_NIGHT.
        AddSession(session="OVER_NIGHT", min_publishers=100).apply(abnb_feed)
        order = [s["session"] for s in abnb_feed["marketSchedules"]]
        assert order == ["REGULAR", "PRE_MARKET", "POST_MARKET", "OVER_NIGHT"]

    def test_inserts_middle_correctly(self, equity_a_feed):
        # feedId 921 has only REGULAR. Add OVER_NIGHT first, then PRE_MARKET:
        # canonical order should re-sort.
        AddSession(session="OVER_NIGHT", min_publishers=100).apply(equity_a_feed)
        AddSession(session="PRE_MARKET", min_publishers=100).apply(equity_a_feed)
        order = [s["session"] for s in equity_a_feed["marketSchedules"]]
        assert order == ["REGULAR", "PRE_MARKET", "OVER_NIGHT"]

    def test_idempotent_re_add_is_skip(self, aapl_feed):
        outcome = AddSession(session="OVER_NIGHT").apply(aapl_feed)
        assert outcome.action == "skipped"
        assert "already present" in outcome.reason

    def test_skips_non_us_equity(self, btc_feed):
        outcome = AddSession(session="OVER_NIGHT").apply(btc_feed)
        assert outcome.action == "skipped"
        assert "US-equity" in outcome.reason

    def test_force_allows_non_us_equity(self, btc_feed):
        # With force=True the op will try; BTC has REGULAR so it succeeds.
        outcome = AddSession(session="OVER_NIGHT", force=True).apply(btc_feed)
        assert outcome.action == "added"

    def test_default_min_publishers_is_100(self, equity_a_feed):
        AddSession(session="PRE_MARKET").apply(equity_a_feed)
        new = find_session(equity_a_feed, "PRE_MARKET")
        assert new["minPublishers"] == 100

    def test_no_regular_blocks_add(self):
        # Feed shaped like a US equity but with no REGULAR session.
        feed = {
            "feedId": 9999,
            "symbol": "Equity.US.NOREG/USD",
            "metadata": {"asset_type": "equity"},
            "marketSchedules": [],
        }
        outcome = AddSession(session="OVER_NIGHT").apply(feed)
        assert outcome.action == "skipped"
        assert "no REGULAR" in outcome.reason


# ---- RemoveSession behavior -------------------------------------------------


class TestRemoveSession:
    def test_removes_overnight(self, aapl_feed):
        outcome = RemoveSession(session="OVER_NIGHT").apply(aapl_feed)
        assert outcome.action == "removed"
        assert find_session(aapl_feed, "OVER_NIGHT") is None

    def test_idempotent_re_remove_is_skip(self, abnb_feed):
        # ABNB doesn't have OVER_NIGHT.
        outcome = RemoveSession(session="OVER_NIGHT").apply(abnb_feed)
        assert outcome.action == "skipped"
        assert "not present" in outcome.reason

    def test_refuses_remove_regular_without_force(self, aapl_feed):
        outcome = RemoveSession(session="REGULAR").apply(aapl_feed)
        assert outcome.action == "skipped"
        assert "refusing to remove REGULAR" in outcome.reason
        assert find_session(aapl_feed, "REGULAR") is not None

    def test_force_allows_remove_regular(self, aapl_feed):
        outcome = RemoveSession(session="REGULAR", force=True).apply(aapl_feed)
        assert outcome.action == "removed"
        assert find_session(aapl_feed, "REGULAR") is None

    def test_skips_non_us_equity(self, btc_feed):
        outcome = RemoveSession(session="REGULAR").apply(btc_feed)
        assert outcome.action == "skipped"
        assert "US-equity" in outcome.reason
