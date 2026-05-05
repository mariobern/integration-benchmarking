import json
from pathlib import Path

import pytest

from lib.config_ops import (
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
