import json
from pathlib import Path

import pytest

from edit_config_lib.config_ops import (
    AddPublisher,
    Change,
    Warning,
    OpError,
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

    def test_get_session_returns_dict(self, feeds):
        sess = get_session(feed_by_id(feeds, 922), "PRE_MARKET")
        assert sess is not None
        assert sess["session"] == "PRE_MARKET"

    def test_get_session_missing_returns_none(self, feeds):
        assert get_session(feed_by_id(feeds, 1), "PRE_MARKET") is None


class TestAddPublisher:
    def test_default_targets_regular_only(self, feeds):
        feed = feed_by_id(feeds, 1)  # crypto: publishers in REGULAR entry
        op = AddPublisher(publisher_id=80)
        changes, warns = op.apply(feed)
        regular = get_session(feed, "REGULAR")
        assert regular["allowedPublisherIds"] == [1, 3, 7, 11, 80]
        assert len(changes) == 1
        assert changes[0].location == "REGULAR"
        assert changes[0].field == "allowedPublisherIds"
        assert changes[0].before == [1, 3, 7, 11]
        assert changes[0].after == [1, 3, 7, 11, 80]
        assert warns == []

    def test_default_on_us_equity_touches_regular_not_extended(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = AddPublisher(publisher_id=80)
        changes, _ = op.apply(feed)
        assert 80 in get_session(feed, "REGULAR")["allowedPublisherIds"]
        assert 80 not in get_session(feed, "PRE_MARKET")["allowedPublisherIds"]
        assert [c.location for c in changes] == ["REGULAR"]

    def test_explicit_pre_market_session(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = AddPublisher(publisher_id=80, session="PRE_MARKET")
        changes, _ = op.apply(feed)
        assert 80 in get_session(feed, "PRE_MARKET")["allowedPublisherIds"]
        assert 80 not in get_session(feed, "REGULAR")["allowedPublisherIds"]
        assert [c.location for c in changes] == ["PRE_MARKET"]

    def test_session_all_touches_every_session(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = AddPublisher(publisher_id=80, session="ALL")
        changes, _ = op.apply(feed)
        for sname in SESSION_NAMES:
            assert 80 in get_session(feed, sname)["allowedPublisherIds"]
        assert len(changes) == 4  # sessions only — no top_level anymore

    def test_session_all_on_single_session_feed(self, feeds):
        feed = feed_by_id(feeds, 1)  # crypto: REGULAR only
        op = AddPublisher(publisher_id=80, session="ALL")
        changes, _ = op.apply(feed)
        assert len(changes) == 1
        assert changes[0].location == "REGULAR"

    def test_session_none_raises(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = AddPublisher(publisher_id=80, session="NONE")
        with pytest.raises(OpError, match="NONE is invalid for publisher ops"):
            op.apply(feed)

    def test_explicit_session_missing_on_feed_raises(self, feeds):
        feed = feed_by_id(feeds, 1)  # crypto, no PRE_MARKET entry
        op = AddPublisher(publisher_id=80, session="PRE_MARKET")
        with pytest.raises(OpError, match="does not exist"):
            op.apply(feed)

    def test_inserts_list_when_session_lacks_key(self, feeds):
        # Feed 5000's REGULAR entry has NO allowedPublisherIds (COMING_SOON
        # shape) — the op must create it, flagged as an insert (before=None).
        feed = feed_by_id(feeds, 5000)
        op = AddPublisher(publisher_id=80)
        changes, warns = op.apply(feed)
        assert get_session(feed, "REGULAR")["allowedPublisherIds"] == [80]
        assert len(changes) == 1
        assert changes[0].before is None
        assert changes[0].after == [80]
        assert warns == []

    def test_noop_when_already_present(self, feeds):
        feed = feed_by_id(feeds, 1)
        op = AddPublisher(publisher_id=3)  # 3 already in REGULAR [1, 3, 7, 11]
        changes, _ = op.apply(feed)
        assert changes == []

    def test_lists_deduped_and_sorted(self, feeds):
        feed = feed_by_id(feeds, 1)
        get_session(feed, "REGULAR")["allowedPublisherIds"] = [11, 1, 7, 3]
        op = AddPublisher(publisher_id=5)
        op.apply(feed)
        assert get_session(feed, "REGULAR")["allowedPublisherIds"] == [1, 3, 5, 7, 11]


from edit_config_lib.config_ops import RemovePublisher


class TestRemovePublisher:
    def test_default_removes_from_regular_only(self, feeds):
        feed = feed_by_id(feeds, 922)
        # publisher 22 is in REGULAR + PRE_MARKET + POST_MARKET
        op = RemovePublisher(publisher_id=22)
        changes, _ = op.apply(feed)
        assert 22 not in get_session(feed, "REGULAR")["allowedPublisherIds"]
        assert 22 in get_session(feed, "PRE_MARKET")["allowedPublisherIds"]
        assert 22 in get_session(feed, "POST_MARKET")["allowedPublisherIds"]
        assert [c.location for c in changes] == ["REGULAR"]

    def test_session_all_removes_everywhere(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = RemovePublisher(publisher_id=22, session="ALL")
        changes, _ = op.apply(feed)
        for name in SESSION_NAMES:
            sess = get_session(feed, name)
            assert 22 not in (sess.get("allowedPublisherIds") or [])
        # REGULAR + PRE_MARKET + POST_MARKET had 22; OVER_NIGHT did not.
        assert sorted(c.location for c in changes) == [
            "POST_MARKET",
            "PRE_MARKET",
            "REGULAR",
        ]

    def test_explicit_session_removes_only_that_session(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = RemovePublisher(publisher_id=22, session="PRE_MARKET")
        changes, _ = op.apply(feed)
        assert 22 not in get_session(feed, "PRE_MARKET")["allowedPublisherIds"]
        assert 22 in get_session(feed, "REGULAR")["allowedPublisherIds"]
        assert [c.location for c in changes] == ["PRE_MARKET"]

    def test_session_none_raises(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = RemovePublisher(publisher_id=22, session="NONE")
        with pytest.raises(OpError, match="NONE is invalid for publisher ops"):
            op.apply(feed)

    def test_explicit_session_missing_on_feed_raises(self, feeds):
        feed = feed_by_id(feeds, 1)
        op = RemovePublisher(publisher_id=1, session="PRE_MARKET")
        with pytest.raises(OpError, match="does not exist"):
            op.apply(feed)

    def test_noop_when_absent(self, feeds):
        feed = feed_by_id(feeds, 1)
        op = RemovePublisher(publisher_id=999)
        changes, _ = op.apply(feed)
        assert changes == []

    def test_noop_when_session_lacks_key(self, feeds):
        # Feed 5000's REGULAR entry has no allowedPublisherIds at all.
        feed = feed_by_id(feeds, 5000)
        op = RemovePublisher(publisher_id=1)
        changes, warns = op.apply(feed)
        assert changes == []
        assert warns == []

    def test_warns_when_at_or_below_session_min(self, feeds):
        feed = feed_by_id(feeds, 922)
        # OVER_NIGHT has [32, 41, 42] with session minPublishers=2.
        # Remove 32 -> [41, 42] with min=2 -> at-floor warning.
        op = RemovePublisher(publisher_id=32, session="OVER_NIGHT")
        _, warns = op.apply(feed)
        assert any(
            "OVER_NIGHT" in w.message and "headroom" in w.message.lower() for w in warns
        )

    def test_headroom_falls_back_to_feed_level_min(self, feeds):
        # Feed 6000: REGULAR [19, 22] with NO session minPublishers;
        # feed-level minPublishers=1. Remove 19 -> [22] vs min=1 -> warning.
        feed = feed_by_id(feeds, 6000)
        op = RemovePublisher(publisher_id=19)
        _, warns = op.apply(feed)
        assert any("headroom" in w.message.lower() for w in warns)


from edit_config_lib.config_ops import SetMinPublishers


class TestSetMinPublishers:
    def test_default_non_us_writes_feed_level_only(self, feeds):
        feed = feed_by_id(feeds, 1)  # Crypto.BTC/USD
        op = SetMinPublishers(value=2)
        changes, _ = op.apply(feed)
        assert feed["minPublishers"] == 2
        assert "minPublishers" not in get_session(feed, "REGULAR")
        assert [c.location for c in changes] == ["top_level"]

    def test_default_us_writes_feed_level_and_regular(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = SetMinPublishers(value=4)
        changes, _ = op.apply(feed)
        assert feed["minPublishers"] == 4
        assert get_session(feed, "REGULAR")["minPublishers"] == 4
        assert get_session(feed, "PRE_MARKET")["minPublishers"] == 2  # untouched
        assert sorted(c.location for c in changes) == ["REGULAR", "top_level"]

    def test_default_us_inserts_missing_regular_min(self, feeds):
        # Feed 1023 is Equity.US.* with a REGULAR list but NO session min.
        feed = feed_by_id(feeds, 1023)
        op = SetMinPublishers(value=3)
        changes, _ = op.apply(feed)
        assert get_session(feed, "REGULAR")["minPublishers"] == 3
        regular_change = next(c for c in changes if c.location == "REGULAR")
        assert regular_change.before is None  # insert

    def test_explicit_session_on_us_feed(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = SetMinPublishers(value=3, session="PRE_MARKET")
        changes, _ = op.apply(feed)
        assert get_session(feed, "PRE_MARKET")["minPublishers"] == 3
        assert feed["minPublishers"] == 1  # untouched
        assert [c.location for c in changes] == ["PRE_MARKET"]

    def test_explicit_session_on_non_us_feed_raises(self, feeds):
        feed = feed_by_id(feeds, 1)  # crypto
        op = SetMinPublishers(value=2, session="REGULAR")
        with pytest.raises(OpError, match="us-equities-only"):
            op.apply(feed)

    def test_session_all_on_non_us_feed_is_feed_level_only(self, feeds):
        feed = feed_by_id(feeds, 100)  # fx
        op = SetMinPublishers(value=2, session="ALL")
        changes, _ = op.apply(feed)
        assert feed["minPublishers"] == 2
        assert "minPublishers" not in get_session(feed, "REGULAR")
        assert [c.location for c in changes] == ["top_level"]

    def test_session_none_feed_level_only(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = SetMinPublishers(value=4, session="NONE")
        changes, _ = op.apply(feed)
        assert feed["minPublishers"] == 4
        assert get_session(feed, "REGULAR")["minPublishers"] == 3  # untouched
        assert [c.location for c in changes] == ["top_level"]

    def test_feed_level_validated_against_session_union(self, feeds):
        # Feed 1's union is [1, 3, 7, 11] (4 publishers): value 5 must error.
        feed = feed_by_id(feeds, 1)
        op = SetMinPublishers(value=5)
        with pytest.raises(OpError, match="exceed"):
            op.apply(feed)

    def test_unsatisfiable_on_feed_without_any_publishers(self, feeds):
        # Feed 5000 has no publisher lists at all -> union is empty.
        feed = feed_by_id(feeds, 5000)
        op = SetMinPublishers(value=2)
        with pytest.raises(OpError, match="exceed"):
            op.apply(feed)

    def test_session_value_validated_against_session_count(self, feeds):
        feed = feed_by_id(feeds, 922)
        # OVER_NIGHT has 3 publishers: min=5 is unsatisfiable.
        op = SetMinPublishers(value=5, session="OVER_NIGHT")
        with pytest.raises(OpError, match="exceed"):
            op.apply(feed)

    def test_warning_at_floor(self, feeds):
        feed = feed_by_id(feeds, 922)
        op = SetMinPublishers(value=3, session="OVER_NIGHT")
        _, warns = op.apply(feed)
        assert any("headroom" in w.message.lower() for w in warns)

    def test_warning_when_one_on_stable(self, feeds):
        feed = feed_by_id(feeds, 1)
        op = SetMinPublishers(value=1)
        _, warns = op.apply(feed)
        assert any("STABLE" in w.message and "1" in w.message for w in warns)

    def test_noop_when_unchanged(self, feeds):
        feed = feed_by_id(feeds, 1)
        op = SetMinPublishers(value=3)  # already 3
        changes, _ = op.apply(feed)
        assert changes == []

    def test_default_us_skips_regular_without_publisher_list(self, feeds):
        # A US-equity feed whose REGULAR session has no publisher list gets
        # only the feed-level write — a publisher-less session has nothing to
        # satisfy a floor against. (Deliberate scope decision.)
        feed = feed_by_id(feeds, 922)
        del get_session(feed, "REGULAR")["allowedPublisherIds"]
        op = SetMinPublishers(value=2)  # value differs from current top-level (1)
        changes, _ = op.apply(feed)
        assert [c.location for c in changes] == ["top_level"]
        assert "minPublishers" not in get_session(feed, "REGULAR") or (
            get_session(feed, "REGULAR")["minPublishers"] == 3
        )  # session min untouched


from edit_config_lib.config_ops import BumpMinPublishers


class TestBumpMinPublishers:
    def test_bump_up_feed_level(self, feeds):
        feed = feed_by_id(feeds, 1)  # min=3, union has 4 publishers
        op = BumpMinPublishers(delta=+1)
        changes, _ = op.apply(feed)
        assert feed["minPublishers"] == 4
        assert changes[0].before == 3 and changes[0].after == 4

    def test_bump_down(self, feeds):
        feed = feed_by_id(feeds, 1)
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

    def test_hard_error_when_exceeding_session_count(self, feeds):
        feed = feed_by_id(feeds, 922)
        # OVER_NIGHT min=2, count=3. Bump +2 -> 4 -> exceeds.
        op = BumpMinPublishers(delta=+2, session="OVER_NIGHT")
        with pytest.raises(OpError, match="exceed"):
            op.apply(feed)

    def test_hard_error_against_union_at_feed_level(self, feeds):
        feed = feed_by_id(feeds, 1)  # min=3, union of 4
        op = BumpMinPublishers(delta=+2)  # -> 5 > 4
        with pytest.raises(OpError, match="exceed"):
            op.apply(feed)

    def test_explicit_session_on_non_us_feed_raises(self, feeds):
        feed = feed_by_id(feeds, 100)  # fx
        op = BumpMinPublishers(delta=+1, session="REGULAR")
        with pytest.raises(OpError, match="us-equities-only"):
            op.apply(feed)

    def test_bump_inserts_missing_session_min_on_us_feed(self, feeds):
        # Feed 1023 (Equity.US.*) has a REGULAR list but no session min:
        # an explicit-session bump inserts it (before=None marks the insert).
        feed = feed_by_id(feeds, 1023)
        op = BumpMinPublishers(delta=+1, session="REGULAR")
        changes, _ = op.apply(feed)
        assert get_session(feed, "REGULAR")["minPublishers"] == 1  # max(1, 0+1)
        assert len(changes) == 1
        assert changes[0].before is None
        assert changes[0].after == 1


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
        feed["marketSchedules"][0]["benchmarkMapping"]["datascope_ric"]["identifiers"][
            0
        ]["identifier"]
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


# ---------------------------------------------------------------------------
# SetRicFromResolver
# ---------------------------------------------------------------------------
from edit_config_lib.config_ops import ResolvedRic, SetRicFromResolver


def _us_feed(feed_id: int, ticker: str, sessions: list[tuple[str, str]]) -> dict:
    """Build a US-equity feed. `sessions` is [(session_name, identifier_value)]."""
    return {
        "feedId": feed_id,
        "symbol": f"Equity.US.{ticker}/USD",
        "state": "STABLE",
        "metadata": {"name": ticker, "asset_type": "equity"},
        "marketSchedules": [
            {
                "session": name,
                "benchmarkMapping": {
                    "datascope_ric": {
                        "identifiers": [
                            {
                                "identifier": ident,
                                "validFrom": "1970-01-01T00:00:00.000000000Z",
                            }
                        ]
                    }
                },
            }
            for (name, ident) in sessions
        ],
    }


def test_set_ric_rewrites_bare_day_sessions_overnight_noop():
    feed = _us_feed(
        990,
        "BITS",
        [
            ("REGULAR", "BITS"),
            ("PRE_MARKET", "BITS"),
            ("POST_MARKET", "BITS"),
            ("OVER_NIGHT", "BITS.BLUE"),
        ],
    )
    op = SetRicFromResolver(
        rics={990: ResolvedRic(day_ric="BITS.O", overnight_ric="BITS.BLUE")}
    )
    changes, warnings = op.apply(feed)
    assert [c.index for c in changes] == [0, 1, 2]  # 3 day slots, overnight NOOP
    assert all(c.after == "BITS.O" for c in changes)
    assert all(c.before == "BITS" for c in changes)
    assert len(warnings) == 3  # overwriting non-empty -> churn warning each
    assert all("overwriting identifier slot" in w.message for w in warnings)


def test_set_ric_fills_empty_slot_no_warning():
    feed = _us_feed(1703, "IWDA", [("REGULAR", "")])
    op = SetRicFromResolver(
        rics={1703: ResolvedRic(day_ric="IWDA.O", overnight_ric="IWDA.BLUE")}
    )
    changes, warnings = op.apply(feed)
    assert len(changes) == 1
    assert changes[0].before == ""
    assert changes[0].after == "IWDA.O"
    assert changes[0].index == 0
    assert warnings == []  # filling empty is not churn


def test_set_ric_rewrites_wrong_suffix_with_churn_warning():
    feed = _us_feed(1059, "CTRA", [("REGULAR", "CTRA.N")])
    op = SetRicFromResolver(
        rics={1059: ResolvedRic(day_ric="CTRA.K", overnight_ric="CTRA.BLUE")}
    )
    changes, warnings = op.apply(feed)
    assert len(changes) == 1
    assert changes[0].before == "CTRA.N"
    assert changes[0].after == "CTRA.K"
    assert len(warnings) == 1
    assert "CTRA.N" in warnings[0].message and "CTRA.K" in warnings[0].message


def test_set_ric_all_correct_is_noop():
    feed = _us_feed(922, "AAPL", [("REGULAR", "AAPL.O"), ("OVER_NIGHT", "AAPL.BLUE")])
    op = SetRicFromResolver(
        rics={922: ResolvedRic(day_ric="AAPL.O", overnight_ric="AAPL.BLUE")}
    )
    changes, warnings = op.apply(feed)
    assert changes == []
    assert warnings == []


def test_set_ric_overnight_slot_rewritten_when_wrong():
    feed = _us_feed(990, "BITS", [("OVER_NIGHT", "WRONG")])
    op = SetRicFromResolver(
        rics={990: ResolvedRic(day_ric="BITS.O", overnight_ric="BITS.BLUE")}
    )
    changes, warnings = op.apply(feed)
    assert len(changes) == 1
    assert changes[0].after == "BITS.BLUE"


def test_set_ric_no_identifier_slots_warns():
    feed = {
        "feedId": 999,
        "symbol": "Equity.US.FOO/USD",
        "state": "STABLE",
        "marketSchedules": [{"session": "REGULAR", "benchmarkMapping": {}}],
    }
    op = SetRicFromResolver(
        rics={999: ResolvedRic(day_ric="FOO.O", overnight_ric="FOO.BLUE")}
    )
    changes, warnings = op.apply(feed)
    assert changes == []
    assert len(warnings) == 1
    assert "no datascope_ric identifier slots" in warnings[0].message


def test_set_ric_unresolved_feed_warns():
    feed = _us_feed(990, "BITS", [("REGULAR", "BITS")])
    # empty day_ric == resolver could not resolve
    op = SetRicFromResolver(rics={990: ResolvedRic(day_ric="", overnight_ric="")})
    changes, warnings = op.apply(feed)
    assert changes == []
    assert len(warnings) == 1
    assert "no RIC resolved" in warnings[0].message


def test_set_ric_feed_absent_from_map_warns():
    feed = _us_feed(990, "BITS", [("REGULAR", "BITS")])
    op = SetRicFromResolver(rics={})  # 990 not present
    changes, warnings = op.apply(feed)
    assert changes == []
    assert len(warnings) == 1
    assert "no RIC resolved" in warnings[0].message


from edit_config_lib.config_ops import (
    ExchangeInfo,
    build_exchanges_by_id,
    asset_class_matches,
)

EX_FIXTURE_PATH = Path(__file__).parent / "fixtures" / "after_with_exchanges.json"


@pytest.fixture
def ex_config():
    return json.loads(EX_FIXTURE_PATH.read_text(encoding="utf-8"))


@pytest.fixture
def exchanges_by_id(ex_config):
    return build_exchanges_by_id(ex_config["exchanges"])


@pytest.fixture
def ex_feeds(ex_config):
    return ex_config["feeds"]


class TestExchangeHelpers:
    def test_build_maps_by_id(self, exchanges_by_id):
        assert set(exchanges_by_id) == {1, 21}
        ex1 = exchanges_by_id[1]
        assert isinstance(ex1, ExchangeInfo)
        assert ex1.name == "NASDAQ Test Consolidated"
        assert ex1.asset_class == "EXCHANGE_ASSET_CLASS_EQUITY"
        assert set(ex1.sessions) == {
            "REGULAR",
            "PRE_MARKET",
            "POST_MARKET",
            "OVER_NIGHT",
        }
        assert ex1.sessions["REGULAR"] == "America/New_York;0930-1600;R"

    def test_build_hk_single_session(self, exchanges_by_id):
        assert set(exchanges_by_id[21].sessions) == {"REGULAR"}

    def test_empty_list_yields_empty_map(self):
        assert build_exchanges_by_id([]) == {}

    def test_asset_class_matches_equity(self):
        assert asset_class_matches("EXCHANGE_ASSET_CLASS_EQUITY", "equity") is True

    def test_asset_class_mismatch(self):
        assert asset_class_matches("EXCHANGE_ASSET_CLASS_EQUITY", "crypto") is False

    def test_asset_class_blank_does_not_flag(self):
        assert asset_class_matches("", "equity") is True
        assert asset_class_matches("EXCHANGE_ASSET_CLASS_EQUITY", "") is True


from edit_config_lib.config_ops import AddExchangeId


def _sessions_with_schedule(feed):
    return [s["session"] for s in feed["marketSchedules"] if "marketSchedule" in s]


class TestAddExchangeId:
    def test_add_inserts_id_and_strips_all_schedule_strings(
        self, ex_feeds, exchanges_by_id
    ):
        feed = feed_by_id(ex_feeds, 100)  # no exchangeId, strings on all 4 sessions
        op = AddExchangeId(exchange_id=1, exchange=exchanges_by_id[1])
        changes, warns = op.apply(feed)
        # exchangeId inserted (before=None) + 4 schedule deletions.
        id_changes = [c for c in changes if c.field == "exchangeId"]
        sched_changes = [c for c in changes if c.field == "marketSchedule"]
        assert len(id_changes) == 1
        assert id_changes[0].before is None and id_changes[0].after == 1
        assert len(sched_changes) == 4
        assert all(c.after is None for c in sched_changes)
        assert feed["exchangeId"] == 1
        assert _sessions_with_schedule(feed) == []
        assert warns == []

    def test_same_id_with_stale_strings_strips_them_no_id_change(
        self, ex_feeds, exchanges_by_id
    ):
        feed = feed_by_id(ex_feeds, 300)  # exchangeId 1 already + 2 stale strings
        op = AddExchangeId(exchange_id=1, exchange=exchanges_by_id[1])
        changes, warns = op.apply(feed)
        assert [c for c in changes if c.field == "exchangeId"] == []
        assert len(changes) == 2  # both stale strings removed
        assert _sessions_with_schedule(feed) == []
        assert warns == []

    def test_same_id_already_inherited_is_noop(self, ex_feeds, exchanges_by_id):
        feed = feed_by_id(ex_feeds, 200)  # exchangeId 1, no strings
        op = AddExchangeId(exchange_id=1, exchange=exchanges_by_id[1])
        changes, warns = op.apply(feed)
        assert changes == []
        assert warns == []

    def test_reassignment_warns(self, exchanges_by_id):
        # A single-REGULAR feed already on exchange 1, reassigned to 21.
        # (Exchange 21 only defines REGULAR, so coverage holds.)
        feed = {
            "exchangeId": 1,
            "feedId": 999,
            "symbol": "Equity.HK.X/HKD",
            "metadata": {"asset_type": "equity"},
            "marketSchedules": [{"allowedPublisherIds": [1], "session": "REGULAR"}],
        }
        op = AddExchangeId(exchange_id=21, exchange=exchanges_by_id[21])
        changes, warns = op.apply(feed)
        assert feed["exchangeId"] == 21
        assert any("reassigning exchangeId 1 -> 21" in w.message for w in warns)

    def test_session_not_covered_is_error(self, ex_feeds, exchanges_by_id):
        feed = feed_by_id(ex_feeds, 400)  # has OVER_NIGHT; exchange 21 lacks it
        op = AddExchangeId(exchange_id=21, exchange=exchanges_by_id[21])
        with pytest.raises(OpError, match="does not define session"):
            op.apply(feed)

    def test_asset_class_mismatch_warns_but_applies(self, ex_feeds, exchanges_by_id):
        feed = feed_by_id(ex_feeds, 500)  # crypto feed, REGULAR only
        op = AddExchangeId(exchange_id=1, exchange=exchanges_by_id[1])
        changes, warns = op.apply(feed)
        assert feed["exchangeId"] == 1
        assert any("does not match exchange" in w.message for w in warns)


from edit_config_lib.config_ops import RemoveExchangeId


class TestRemoveExchangeId:
    def test_removes_id_and_restores_all_schedules(self, ex_feeds, exchanges_by_id):
        feed = feed_by_id(ex_feeds, 200)  # exchangeId 1, no strings, 4 sessions
        op = RemoveExchangeId(exchanges_by_id=exchanges_by_id)
        changes, warns = op.apply(feed)
        id_changes = [c for c in changes if c.field == "exchangeId"]
        sched_changes = [c for c in changes if c.field == "marketSchedule"]
        assert len(id_changes) == 1 and id_changes[0].after is None
        assert len(sched_changes) == 4
        # Restored strings come from the exchange definition.
        reg = get_session(feed, "REGULAR")
        assert reg["marketSchedule"] == "America/New_York;0930-1600;R"
        assert "exchangeId" not in feed
        assert warns == []

    def test_no_exchange_id_warns_noop(self, ex_feeds, exchanges_by_id):
        feed = feed_by_id(ex_feeds, 100)  # no exchangeId
        op = RemoveExchangeId(exchanges_by_id=exchanges_by_id)
        changes, warns = op.apply(feed)
        assert changes == []
        assert any("no exchangeId to remove" in w.message for w in warns)

    def test_unknown_current_id_is_error(self, exchanges_by_id):
        feed = {
            "exchangeId": 7,  # not in {1, 21}
            "feedId": 888,
            "symbol": "Equity.US.ZZZ/USD",
            "metadata": {"asset_type": "equity"},
            "marketSchedules": [{"allowedPublisherIds": [1], "session": "REGULAR"}],
        }
        op = RemoveExchangeId(exchanges_by_id=exchanges_by_id)
        with pytest.raises(OpError, match="not defined in exchanges"):
            op.apply(feed)

    def test_session_not_covered_is_error(self, exchanges_by_id):
        feed = {
            "exchangeId": 21,  # HK: REGULAR only
            "feedId": 889,
            "symbol": "Equity.HK.Y/HKD",
            "metadata": {"asset_type": "equity"},
            "marketSchedules": [
                {"allowedPublisherIds": [1], "session": "REGULAR"},
                {"allowedPublisherIds": [1], "session": "OVER_NIGHT"},
            ],
        }
        op = RemoveExchangeId(exchanges_by_id=exchanges_by_id)
        with pytest.raises(OpError, match="cannot restore"):
            op.apply(feed)

    def test_existing_schedule_string_left_untouched(self, ex_feeds, exchanges_by_id):
        feed = feed_by_id(
            ex_feeds, 300
        )  # exchangeId 1, REGULAR+OVER_NIGHT both have stale strings
        op = RemoveExchangeId(exchanges_by_id=exchanges_by_id)
        changes, warns = op.apply(feed)
        # id removed; both sessions already had strings -> no marketSchedule changes.
        assert [c for c in changes if c.field == "exchangeId"] == [changes[0]]
        assert [c for c in changes if c.field == "marketSchedule"] == []
        assert (
            get_session(feed, "REGULAR")["marketSchedule"]
            == "America/New_York;0930-1600;STALE-R"
        )
