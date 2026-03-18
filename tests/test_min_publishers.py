import json

import pytest

from lib.min_publishers import FeedChange, compute_target_min_publishers, evaluate_feeds


class TestComputeTargetMinPublishers:
    """Rule engine: publisher count -> target minPublishers."""

    def test_below_floor_returns_none(self):
        """2-4 publishers -> no change (None)."""
        assert compute_target_min_publishers(2) is None
        assert compute_target_min_publishers(3) is None
        assert compute_target_min_publishers(4) is None

    def test_needs_attention_returns_none(self):
        """0-1 publishers -> no change (None). NEEDS_ATTENTION handled elsewhere."""
        assert compute_target_min_publishers(0) is None
        assert compute_target_min_publishers(1) is None

    def test_mid_tier_returns_2(self):
        """5-6 publishers -> minPublishers=2."""
        assert compute_target_min_publishers(5) == 2
        assert compute_target_min_publishers(6) == 2

    def test_upper_tier_returns_3(self):
        """7+ publishers -> minPublishers=3."""
        assert compute_target_min_publishers(7) == 3
        assert compute_target_min_publishers(10) == 3
        assert compute_target_min_publishers(20) == 3

    def test_custom_floor(self):
        """--min-publisher-floor changes lower boundary."""
        assert compute_target_min_publishers(3, floor=3) == 2
        assert compute_target_min_publishers(2, floor=3) is None

    def test_custom_cutoff(self):
        """--publisher-tier-cutoff changes upper boundary."""
        assert compute_target_min_publishers(5, cutoff=5) == 3
        assert compute_target_min_publishers(6, cutoff=5) == 3
        assert compute_target_min_publishers(5, cutoff=6) == 2


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_feed(
    feed_id,
    symbol,
    asset_type,
    state,
    min_publishers,
    publisher_ids,
    sessions=None,
):
    """Build a minimal feed dict matching after.json structure."""
    return {
        "feedId": feed_id,
        "symbol": symbol,
        "state": state,
        "minPublishers": min_publishers,
        "allowedPublisherIds": publisher_ids,
        "metadata": {
            "asset_type": asset_type,
            "name": symbol.split(".")[-1].split("/")[0],
        },
        "marketSchedules": sessions
        or [
            {
                "marketSchedule": "America/New_York;O,O,O,O,O,O,O;",
                "session": "REGULAR",
            }
        ],
    }


def _make_extended_equity(
    feed_id, symbol, top_min_pub, top_pubs, regular_min_pub, regular_pubs
):
    """Build an extended-hours equity feed with REGULAR + OVER_NIGHT sessions."""
    return {
        "feedId": feed_id,
        "symbol": symbol,
        "state": "STABLE",
        "minPublishers": top_min_pub,
        "allowedPublisherIds": top_pubs,
        "metadata": {
            "asset_type": "equity",
            "name": symbol.split(".")[-1].split("/")[0],
        },
        "marketSchedules": [
            {
                "allowedPublisherIds": regular_pubs,
                "marketSchedule": "America/New_York;0930-1600,...",
                "minPublishers": regular_min_pub,
                "session": "REGULAR",
            },
            {
                "allowedPublisherIds": [32, 41],
                "marketSchedule": "America/New_York;0000-0400&2000-2400,...",
                "minPublishers": 1,
                "session": "OVER_NIGHT",
            },
        ],
    }


# ── Task 2: Eligibility Tests ───────────────────────────────────────────


class TestEvaluateFeeds:
    """Feed eligibility and change computation."""

    def test_stable_equity_updated(self):
        """STABLE equity with 5 publishers and minPublishers=1 -> UPDATED to 2."""
        feeds = [
            _make_feed(100, "Equity.US.FOO/USD", "equity", "STABLE", 1, [10, 20, 30, 40, 50])
        ]
        changes = evaluate_feeds(feeds)
        assert len(changes) == 1
        assert changes[0].status == "UPDATED"
        assert changes[0].new_min_publishers == 2

    def test_stable_equity_7_publishers_updated_to_3(self):
        """STABLE equity with 7+ publishers -> UPDATED to 3."""
        feeds = [
            _make_feed(
                100, "Equity.US.FOO/USD", "equity", "STABLE", 1, list(range(10, 18))
            )
        ]
        changes = evaluate_feeds(feeds)
        assert changes[0].new_min_publishers == 3

    def test_coming_soon_skipped(self):
        """COMING_SOON feeds are not processed."""
        feeds = [
            _make_feed(
                100, "Equity.US.FOO/USD", "equity", "COMING_SOON", 1, [10, 20, 30, 40, 50]
            )
        ]
        changes = evaluate_feeds(feeds)
        assert len(changes) == 0

    def test_excluded_asset_type_skipped(self):
        """Feeds with excluded asset types are not processed."""
        feeds = [
            _make_feed(
                100, "FundingRate.X/Y", "funding-rate", "STABLE", 1, [10, 20, 30, 40, 50]
            )
        ]
        changes = evaluate_feeds(feeds)
        assert len(changes) == 0

    def test_asset_class_allowlist(self):
        """--asset-classes overrides default exclusion."""
        feeds = [
            _make_feed(100, "FX.EUR/USD", "fx", "STABLE", 1, [10, 20, 30, 40, 50]),
            _make_feed(200, "Crypto.BTC/USD", "crypto", "STABLE", 1, [10, 20, 30, 40, 50]),
        ]
        changes = evaluate_feeds(feeds, asset_classes=["fx"])
        assert len(changes) == 1
        assert changes[0].feed_id == 100

    def test_needs_attention(self):
        """Feeds with <2 publishers get NEEDS_ATTENTION."""
        feeds = [_make_feed(100, "Equity.US.X/USD", "equity", "STABLE", 1, [10])]
        changes = evaluate_feeds(feeds)
        assert len(changes) == 1
        assert changes[0].status == "NEEDS_ATTENTION"

    def test_low_publishers_skipped(self):
        """Feeds with 2-4 publishers get SKIPPED_LOW_PUBLISHERS."""
        feeds = [_make_feed(100, "Equity.US.X/USD", "equity", "STABLE", 1, [10, 20, 30])]
        changes = evaluate_feeds(feeds)
        assert len(changes) == 1
        assert changes[0].status == "SKIPPED_LOW_PUBLISHERS"

    def test_no_downgrade(self):
        """Existing minPublishers=3 with 5 publishers stays (SKIPPED_HIGHER)."""
        feeds = [
            _make_feed(100, "Equity.US.X/USD", "equity", "STABLE", 3, [10, 20, 30, 40, 50])
        ]
        changes = evaluate_feeds(feeds)
        assert changes[0].status == "SKIPPED_HIGHER"

    def test_skipped_equal(self):
        """Existing minPublishers=2 with 5 publishers (SKIPPED_EQUAL)."""
        feeds = [
            _make_feed(100, "Equity.US.X/USD", "equity", "STABLE", 2, [10, 20, 30, 40, 50])
        ]
        changes = evaluate_feeds(feeds)
        assert changes[0].status == "SKIPPED_EQUAL"

    def test_upgrade_2_to_3(self):
        """Existing minPublishers=2 with 8 publishers -> UPDATED to 3."""
        feeds = [
            _make_feed(100, "Equity.US.X/USD", "equity", "STABLE", 2, list(range(10, 18)))
        ]
        changes = evaluate_feeds(feeds)
        assert changes[0].status == "UPDATED"
        assert changes[0].new_min_publishers == 3

    def test_extended_hours_excluded(self):
        """Extended-hours equities are entirely excluded."""
        feeds = [
            _make_extended_equity(
                100,
                "Equity.US.AAPL/USD",
                1,
                list(range(10, 25)),
                3,
                list(range(10, 22)),
            )
        ]
        changes = evaluate_feeds(feeds)
        assert len(changes) == 0

    def test_empty_allowed_publishers(self):
        """Feed with empty allowedPublisherIds -> NEEDS_ATTENTION."""
        feeds = [_make_feed(100, "Equity.US.X/USD", "equity", "STABLE", 1, [])]
        changes = evaluate_feeds(feeds)
        assert changes[0].status == "NEEDS_ATTENTION"

    def test_missing_allowed_publishers_key(self):
        """Feed with no allowedPublisherIds key -> NEEDS_ATTENTION."""
        feed = _make_feed(100, "Equity.US.X/USD", "equity", "STABLE", 1, [])
        del feed["allowedPublisherIds"]
        changes = evaluate_feeds([feed])
        assert changes[0].status == "NEEDS_ATTENTION"
