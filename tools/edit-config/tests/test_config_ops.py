import json
from pathlib import Path

import pytest

from lib.config_ops import (
    AddPublisher,
    Change,
    Warning,
    OpError,
    has_session_publishers,
    get_session,
    SESSION_NAMES,
)


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "after_sample.json"


@pytest.fixture
def feeds():
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))["feeds"]


def feed_by_id(feeds, fid):
    for f in feeds:
        if f["feedId"] == fid:
            return f
    raise AssertionError(f"feed {fid} not in fixture")


class TestSharedRecords:
    def test_change_is_frozen_dataclass(self):
        c = Change(
            feed_id=1,
            symbol="Crypto.BTC/USD",
            location="top_level",
            field="allowedPublisherIds",
            before=[1, 2],
            after=[1, 2, 3],
        )
        with pytest.raises(Exception):
            c.feed_id = 2  # type: ignore[misc]

    def test_warning_record(self):
        w = Warning(feed_id=1, symbol="X", message="hi")
        assert w.message == "hi"

    def test_op_error_is_exception(self):
        with pytest.raises(OpError):
            raise OpError("boom")


class TestSessionHelpers:
    def test_session_names_constant(self):
        assert set(SESSION_NAMES) == {
            "REGULAR",
            "PRE_MARKET",
            "POST_MARKET",
            "OVER_NIGHT",
        }

    def test_has_session_publishers_true_for_equity_4_session(self, feeds):
        assert has_session_publishers(feed_by_id(feeds, 922)) is True

    def test_has_session_publishers_false_for_crypto(self, feeds):
        assert has_session_publishers(feed_by_id(feeds, 1)) is False

    def test_has_session_publishers_false_for_single_session_equity(self, feeds):
        # SMLC has only REGULAR with no per-session allowedPublisherIds
        assert has_session_publishers(feed_by_id(feeds, 1023)) is False

    def test_get_session_returns_dict(self, feeds):
        sess = get_session(feed_by_id(feeds, 922), "PRE_MARKET")
        assert sess is not None
        assert sess["session"] == "PRE_MARKET"

    def test_get_session_missing_returns_none(self, feeds):
        assert get_session(feed_by_id(feeds, 1), "PRE_MARKET") is None


class TestAddPublisher:
    def test_default_on_non_equity_adds_top_level(self, feeds):
        feed = feed_by_id(feeds, 1)  # crypto, no per-session lists
        op = AddPublisher(publisher_id=80)
        changes, warns = op.apply(feed)
        assert feed["allowedPublisherIds"] == [1, 3, 7, 11, 80]
        assert len(changes) == 1
        assert changes[0].location == "top_level"
        assert changes[0].field == "allowedPublisherIds"
        assert changes[0].before == [1, 3, 7, 11]
        assert changes[0].after == [1, 3, 7, 11, 80]
        assert warns == []

    def test_default_on_equity_adds_top_level_and_regular(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = AddPublisher(publisher_id=80)
        changes, warns = op.apply(feed)
        assert 80 in feed["allowedPublisherIds"]
        regular = get_session(feed, "REGULAR")
        assert 80 in regular["allowedPublisherIds"]
        # PRE_MARKET should NOT be touched
        pre = get_session(feed, "PRE_MARKET")
        assert 80 not in pre["allowedPublisherIds"]
        locs = sorted(c.location for c in changes)
        assert locs == ["REGULAR", "top_level"]

    def test_explicit_pre_market_session(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = AddPublisher(publisher_id=80, session="PRE_MARKET")
        changes, warns = op.apply(feed)
        assert 80 in feed["allowedPublisherIds"]
        assert 80 in get_session(feed, "PRE_MARKET")["allowedPublisherIds"]
        # REGULAR not touched
        regular = get_session(feed, "REGULAR")
        assert 80 not in regular["allowedPublisherIds"]

    def test_session_all(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = AddPublisher(publisher_id=80, session="ALL")
        changes, _ = op.apply(feed)
        for sname in SESSION_NAMES:
            sess = get_session(feed, sname)
            assert 80 in sess["allowedPublisherIds"]
        assert 80 in feed["allowedPublisherIds"]
        assert len(changes) == 5  # 4 sessions + top_level

    def test_session_none_only_top_level(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = AddPublisher(publisher_id=80, session="NONE")
        changes, _ = op.apply(feed)
        assert 80 in feed["allowedPublisherIds"]
        for sname in SESSION_NAMES:
            sess = get_session(feed, sname)
            assert 80 not in sess["allowedPublisherIds"]
        assert len(changes) == 1
        assert changes[0].location == "top_level"

    def test_explicit_session_on_non_equity_raises(self, feeds):
        feed = feed_by_id(feeds, 1)  # crypto, no PRE_MARKET
        op = AddPublisher(publisher_id=80, session="PRE_MARKET")
        with pytest.raises(OpError, match="session.*does not exist"):
            op.apply(feed)

    def test_session_all_on_non_equity_raises(self, feeds):
        feed = feed_by_id(feeds, 1)
        op = AddPublisher(publisher_id=80, session="ALL")
        with pytest.raises(OpError, match="no per-session"):
            op.apply(feed)

    def test_noop_when_already_present(self, feeds):
        feed = feed_by_id(feeds, 1)
        op = AddPublisher(publisher_id=3)  # 3 already in [1, 3, 7, 11]
        changes, _ = op.apply(feed)
        assert changes == []

    def test_lists_deduped_and_sorted(self, feeds):
        feed = feed_by_id(feeds, 1)
        feed["allowedPublisherIds"] = [11, 1, 7, 3]  # not sorted
        op = AddPublisher(publisher_id=5)
        op.apply(feed)
        assert feed["allowedPublisherIds"] == [1, 3, 5, 7, 11]

    def test_empty_list_initial(self, feeds):
        feed = feed_by_id(feeds, 5000)  # COMING_SOON, empty list
        op = AddPublisher(publisher_id=80)
        changes, _ = op.apply(feed)
        assert feed["allowedPublisherIds"] == [80]
        assert len(changes) == 1
