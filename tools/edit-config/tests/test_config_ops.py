import json
from pathlib import Path

import pytest

from edit_config_lib.config_ops import (
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

    def test_session_regular_on_non_equity_raises(self, feeds):
        # Non-US-equity feeds have no per-session REGULAR roster (only top-level).
        # --session REGULAR must error so users don't think they targeted something
        # specific when only the top-level list exists.
        feed = feed_by_id(feeds, 1)
        op = AddPublisher(publisher_id=80, session="REGULAR")
        with pytest.raises(OpError, match="session.*does not exist"):
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

    def test_missing_top_level_field_warns_and_skips(self, feeds):
        # Some feeds (e.g. inactive crypto) lack a top-level allowedPublisherIds.
        # AddPublisher must NOT invent the field — text-surgery cannot insert
        # it later. Instead, emit a Warning and produce no Change.
        feed = feed_by_id(feeds, 1)  # crypto, no per-session lists
        del feed["allowedPublisherIds"]
        op = AddPublisher(publisher_id=80)
        changes, warns = op.apply(feed)
        assert changes == []
        assert "allowedPublisherIds" not in feed  # not invented
        assert len(warns) == 1
        assert "no top-level allowedPublisherIds" in warns[0].message

    def test_missing_top_level_field_with_session_all(self, feeds):
        # session=ALL on an equity-style feed: top-level missing -> warn for
        # top_level only; session targets still get their changes.
        feed = feed_by_id(feeds, 922)
        del feed["allowedPublisherIds"]
        op = AddPublisher(publisher_id=80, session="ALL")
        changes, warns = op.apply(feed)
        assert "allowedPublisherIds" not in feed
        assert any("top-level" in w.message for w in warns)
        # All four sessions should still be edited.
        assert sorted(c.location for c in changes) == sorted(SESSION_NAMES)


from edit_config_lib.config_ops import RemovePublisher


class TestRemovePublisher:
    def test_default_removes_everywhere_on_equity(self, feeds):
        feed = feed_by_id(feeds, 922)
        # publisher 22 is in top-level + REGULAR + PRE_MARKET + POST_MARKET
        op = RemovePublisher(publisher_id=22)
        changes, _ = op.apply(feed)
        assert 22 not in feed["allowedPublisherIds"]
        for name in SESSION_NAMES:
            sess = get_session(feed, name)
            if sess and "allowedPublisherIds" in sess:
                assert 22 not in sess["allowedPublisherIds"]
        # 4 changes: top_level + REGULAR + PRE_MARKET + POST_MARKET
        # (OVER_NIGHT didn't have 22)
        assert len(changes) == 4

    def test_default_on_non_equity_removes_top_level(self, feeds):
        feed = feed_by_id(feeds, 1)
        op = RemovePublisher(publisher_id=3)
        changes, _ = op.apply(feed)
        assert 3 not in feed["allowedPublisherIds"]
        assert len(changes) == 1

    def test_explicit_session_removes_only_that_session(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = RemovePublisher(publisher_id=22, session="PRE_MARKET")
        changes, _ = op.apply(feed)
        assert 22 in feed["allowedPublisherIds"]  # top-level untouched
        assert 22 not in get_session(feed, "PRE_MARKET")["allowedPublisherIds"]
        assert 22 in get_session(feed, "REGULAR")["allowedPublisherIds"]
        assert len(changes) == 1
        assert changes[0].location == "PRE_MARKET"

    def test_session_all_removes_everywhere(self, feeds):
        # session=ALL mirrors AddPublisher: removes from top-level AND every
        # per-session list.
        feed = feed_by_id(feeds, 922)
        op = RemovePublisher(publisher_id=22, session="ALL")
        changes, _ = op.apply(feed)
        assert 22 not in feed["allowedPublisherIds"]
        for name in SESSION_NAMES:
            sess = get_session(feed, name)
            if sess and "allowedPublisherIds" in sess:
                assert 22 not in sess["allowedPublisherIds"]
        assert any(c.location == "top_level" for c in changes)

    def test_session_none_warns_about_consistency(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = RemovePublisher(publisher_id=22, session="NONE")
        changes, warns = op.apply(feed)
        assert 22 not in feed["allowedPublisherIds"]
        # 22 still in REGULAR session -> consistency warning
        assert any("still in session" in w.message for w in warns)

    def test_noop_when_absent(self, feeds):
        feed = feed_by_id(feeds, 1)
        op = RemovePublisher(publisher_id=999)
        changes, _ = op.apply(feed)
        assert changes == []

    def test_session_regular_on_non_equity_raises(self, feeds):
        # Non-US-equity feeds have no per-session REGULAR roster (only top-level).
        # --session REGULAR must error rather than silently editing top-level.
        feed = feed_by_id(feeds, 1)
        target = feed["allowedPublisherIds"][0]
        op = RemovePublisher(publisher_id=target, session="REGULAR")
        with pytest.raises(OpError, match="session.*does not exist"):
            op.apply(feed)

    def test_warns_when_at_or_below_min_publishers(self, feeds):
        feed = feed_by_id(feeds, 922)
        # OVER_NIGHT has [32, 41, 42] with minPublishers=2.
        # Remove 32 -> [41, 42] with min=2 -> at-floor warning.
        op = RemovePublisher(publisher_id=32, session="OVER_NIGHT")
        changes, warns = op.apply(feed)
        assert any(
            "OVER_NIGHT" in w.message and "headroom" in w.message.lower() for w in warns
        )

    def test_warns_for_top_level_at_floor(self, feeds):
        feed = feed_by_id(feeds, 6000)
        # top-level [19, 22], minPublishers=1. Remove 19 -> [22], min=1 -> warn
        op = RemovePublisher(publisher_id=19)
        changes, warns = op.apply(feed)
        assert any(
            "top_level" in w.message or "headroom" in w.message.lower() for w in warns
        )


from edit_config_lib.config_ops import SetMinPublishers


class TestSetMinPublishers:
    def test_default_on_non_equity_writes_top_level(self, feeds):
        feed = feed_by_id(feeds, 1)
        op = SetMinPublishers(value=2)
        changes, _ = op.apply(feed)
        assert feed["minPublishers"] == 2
        assert len(changes) == 1
        assert changes[0].location == "top_level"
        assert changes[0].field == "minPublishers"
        assert changes[0].after == 2

    def test_default_on_equity_writes_top_and_regular(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = SetMinPublishers(value=4)
        changes, _ = op.apply(feed)
        assert feed["minPublishers"] == 4
        assert get_session(feed, "REGULAR")["minPublishers"] == 4
        assert get_session(feed, "PRE_MARKET")["minPublishers"] == 2  # untouched
        locs = sorted(c.location for c in changes)
        assert locs == ["REGULAR", "top_level"]

    def test_explicit_session(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = SetMinPublishers(value=3, session="PRE_MARKET")
        changes, _ = op.apply(feed)
        assert get_session(feed, "PRE_MARKET")["minPublishers"] == 3
        assert feed["minPublishers"] == 1  # untouched
        assert len(changes) == 1
        assert changes[0].location == "PRE_MARKET"

    def test_hard_error_when_value_exceeds_count(self, feeds):
        feed = feed_by_id(feeds, 922)
        # OVER_NIGHT has 3 publishers, set min=5 -> unsatisfiable
        op = SetMinPublishers(value=5, session="OVER_NIGHT")
        with pytest.raises(OpError, match="exceed"):
            op.apply(feed)

    def test_warning_at_floor(self, feeds):
        feed = feed_by_id(feeds, 922)
        # OVER_NIGHT has 3 publishers, set min=3 -> at-floor warning
        op = SetMinPublishers(value=3, session="OVER_NIGHT")
        changes, warns = op.apply(feed)
        assert any("headroom" in w.message.lower() for w in warns)

    def test_warning_when_one_on_stable(self, feeds):
        feed = feed_by_id(feeds, 1)
        op = SetMinPublishers(value=1)
        changes, warns = op.apply(feed)
        assert any("STABLE" in w.message and "1" in w.message for w in warns)

    def test_noop_when_unchanged(self, feeds):
        feed = feed_by_id(feeds, 1)
        op = SetMinPublishers(value=3)  # already 3
        changes, _ = op.apply(feed)
        assert changes == []

    def test_session_none_only_top_level(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = SetMinPublishers(value=4, session="NONE")
        changes, _ = op.apply(feed)
        assert feed["minPublishers"] == 4
        assert get_session(feed, "REGULAR")["minPublishers"] == 3  # untouched
        assert len(changes) == 1
        assert changes[0].location == "top_level"


from edit_config_lib.config_ops import BumpMinPublishers


class TestBumpMinPublishers:
    def test_bump_up(self, feeds):
        feed = feed_by_id(feeds, 1)  # min=3
        op = BumpMinPublishers(delta=+1)
        changes, _ = op.apply(feed)
        assert feed["minPublishers"] == 4
        assert changes[0].before == 3 and changes[0].after == 4

    def test_bump_down(self, feeds):
        feed = feed_by_id(feeds, 1)  # min=3
        op = BumpMinPublishers(delta=-1)
        changes, _ = op.apply(feed)
        assert feed["minPublishers"] == 2

    def test_clamped_at_one(self, feeds):
        feed = feed_by_id(feeds, 6000)  # min=1
        op = BumpMinPublishers(delta=-5)
        changes, _ = op.apply(feed)
        assert feed["minPublishers"] == 1
        assert changes == []  # NOOP since value didn't change

    def test_zero_delta_is_noop(self, feeds):
        feed = feed_by_id(feeds, 1)
        op = BumpMinPublishers(delta=0)
        changes, _ = op.apply(feed)
        assert changes == []

    def test_hard_error_when_exceeding_count(self, feeds):
        feed = feed_by_id(feeds, 922)
        # OVER_NIGHT min=2, count=3. Bump +2 -> 4 -> exceeds.
        op = BumpMinPublishers(delta=+2, session="OVER_NIGHT")
        with pytest.raises(OpError, match="exceed"):
            op.apply(feed)


from edit_config_lib.config_ops import SetState


VALID_STATES = ("STABLE", "COMING_SOON", "INACTIVE")


class TestSetState:
    def test_promote_coming_soon_to_stable(self, feeds):
        feed = feed_by_id(feeds, 5000)
        op = SetState(value="STABLE")
        changes, warns = op.apply(feed)
        assert feed["state"] == "STABLE"
        assert len(changes) == 1
        assert changes[0].field == "state"
        assert changes[0].before == "COMING_SOON" and changes[0].after == "STABLE"
        # COMING_SOON -> STABLE is the natural progression; no warning
        assert warns == []

    def test_regression_stable_to_coming_soon_warns(self, feeds):
        feed = feed_by_id(feeds, 1)
        op = SetState(value="COMING_SOON")
        changes, warns = op.apply(feed)
        assert feed["state"] == "COMING_SOON"
        assert any("regression" in w.message.lower() for w in warns)

    def test_deactivation_warns(self, feeds):
        feed = feed_by_id(feeds, 1)
        op = SetState(value="INACTIVE")
        changes, warns = op.apply(feed)
        assert feed["state"] == "INACTIVE"
        assert any("deactivat" in w.message.lower() for w in warns)

    def test_reactivation_warns(self, feeds):
        feed = feed_by_id(feeds, 6000)  # INACTIVE
        op = SetState(value="STABLE")
        changes, warns = op.apply(feed)
        assert feed["state"] == "STABLE"
        assert any("reactivat" in w.message.lower() for w in warns)

    def test_noop_when_already_target(self, feeds):
        feed = feed_by_id(feeds, 1)  # STABLE
        op = SetState(value="STABLE")
        changes, _ = op.apply(feed)
        assert changes == []

    def test_invalid_state_raises(self, feeds):
        feed = feed_by_id(feeds, 1)
        op = SetState(value="DELETED")
        with pytest.raises(OpError, match="invalid state"):
            op.apply(feed)


# ---------------------------------------------------------------------------
# SetRicMapping
# ---------------------------------------------------------------------------
from edit_config_lib.config_ops import SetRicMapping


def _hk_feed(feed_id: int, ticker: str, identifier: str = "") -> dict:
    return {
        "feedId": feed_id,
        "symbol": f"Equity.HK.{ticker}-HK/HKD",
        "state": "COMING_SOON",
        "marketSchedules": [
            {
                "benchmarkMapping": {
                    "datascope_ric": {
                        "identifiers": [
                            {
                                "identifier": identifier,
                                "validFrom": "1970-01-01T00:00:00.000000000Z",
                            }
                        ]
                    }
                }
            }
        ],
    }


def test_set_ric_mapping_fills_empty_identifier():
    feed = _hk_feed(884, "0002")
    op = SetRicMapping(prefix_to_ric={"Equity.HK.0002-HK/": "0002.HK"})
    changes, warnings = op.apply(feed)
    assert len(changes) == 1
    c = changes[0]
    assert c.feed_id == 884
    assert c.location == "datascope_ric_identifier"
    assert c.field == "identifier"
    assert c.before == ""
    assert c.after == "0002.HK"
    assert c.index == 0
    assert warnings == []
    # working copy was updated
    assert (
        feed["marketSchedules"][0]["benchmarkMapping"]["datascope_ric"][
            "identifiers"
        ][0]["identifier"]
        == "0002.HK"
    )


def test_set_ric_mapping_skips_populated_identifier_with_warning():
    feed = _hk_feed(884, "0002", identifier="EXISTING.HK")
    op = SetRicMapping(prefix_to_ric={"Equity.HK.0002-HK/": "0002.HK"})
    changes, warnings = op.apply(feed)
    assert changes == []
    assert len(warnings) == 1
    assert "already populated" in warnings[0].message


def test_set_ric_mapping_skips_unmatched_symbol():
    feed = _hk_feed(884, "0002")
    op = SetRicMapping(prefix_to_ric={"Equity.HK.0700-HK/": "0700.HK"})
    changes, warnings = op.apply(feed)
    assert changes == []
    assert warnings == []


def test_set_ric_mapping_skips_feed_without_datascope_ric_structure():
    feed = {
        "feedId": 999,
        "symbol": "Equity.HK.0002-HK/HKD",
        "state": "COMING_SOON",
        "marketSchedules": [{"benchmarkMapping": {}}],
    }
    op = SetRicMapping(prefix_to_ric={"Equity.HK.0002-HK/": "0002.HK"})
    changes, warnings = op.apply(feed)
    assert changes == []
    assert len(warnings) == 1
    assert "no datascope_ric identifier slots" in warnings[0].message


def test_set_ric_mapping_handles_multi_slot_feed():
    feed = {
        "feedId": 884,
        "symbol": "Equity.HK.0002-HK/HKD",
        "state": "COMING_SOON",
        "marketSchedules": [
            {
                "benchmarkMapping": {
                    "datascope_ric": {
                        "identifiers": [
                            {"identifier": ""},
                            {"identifier": "ALREADY.HK"},
                        ]
                    }
                }
            }
        ],
    }
    op = SetRicMapping(prefix_to_ric={"Equity.HK.0002-HK/": "0002.HK"})
    changes, warnings = op.apply(feed)
    assert len(changes) == 1
    assert changes[0].index == 0
    assert changes[0].after == "0002.HK"
    assert len(warnings) == 1
