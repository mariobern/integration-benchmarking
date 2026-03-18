import json

import pytest

from lib.min_publishers import (
    FeedChange,
    _find_feed_block,
    _find_market_schedules_end,
    compute_target_min_publishers,
    evaluate_feeds,
    modify_config,
    write_csv_report,
)


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


# ── Task 3: JSON Surgery Tests ───────────────────────────────────────────

# Sample JSON for testing (formatted like real after.json)
SAMPLE_CONFIG_RAW = json.dumps(
    {
        "feeds": [
            {
                "allowedPublisherIds": [10, 20, 30, 40, 50],
                "feedId": 100,
                "marketSchedules": [
                    {
                        "marketSchedule": "America/New_York;O,O,O,O,O,O,O;",
                        "session": "REGULAR",
                    }
                ],
                "metadata": {"asset_type": "equity", "name": "FOO"},
                "minPublishers": 1,
                "state": "STABLE",
                "symbol": "Equity.US.FOO/USD",
            },
            {
                "allowedPublisherIds": [10, 20, 30, 40, 50, 60, 70, 80],
                "feedId": 200,
                "marketSchedules": [
                    {
                        "allowedPublisherIds": [10, 20, 30, 40, 50, 60, 70, 80],
                        "marketSchedule": "America/New_York;0930-1600,...",
                        "minPublishers": 3,
                        "session": "REGULAR",
                    }
                ],
                "metadata": {"asset_type": "equity", "name": "BAR"},
                "minPublishers": 1,
                "state": "STABLE",
                "symbol": "Equity.US.BAR/USD",
            },
        ]
    },
    indent=2,
)


class TestFindFeedBlock:
    """Locate feed blocks in raw JSON."""

    def test_finds_feed_block(self):
        bounds = _find_feed_block(SAMPLE_CONFIG_RAW, 100)
        assert bounds is not None
        block = SAMPLE_CONFIG_RAW[bounds[0] : bounds[1]]
        assert '"feedId": 100' in block
        assert '"symbol": "Equity.US.FOO/USD"' in block

    def test_returns_none_for_missing_feed(self):
        assert _find_feed_block(SAMPLE_CONFIG_RAW, 999) is None

    def test_finds_second_feed(self):
        bounds = _find_feed_block(SAMPLE_CONFIG_RAW, 200)
        assert bounds is not None
        block = SAMPLE_CONFIG_RAW[bounds[0] : bounds[1]]
        assert '"feedId": 200' in block


class TestFindMarketSchedulesEnd:
    """Locate end of marketSchedules array within a feed block."""

    def test_simple_feed(self):
        bounds = _find_feed_block(SAMPLE_CONFIG_RAW, 100)
        block = SAMPLE_CONFIG_RAW[bounds[0] : bounds[1]]
        end_pos = _find_market_schedules_end(block)
        assert end_pos is not None
        # Everything after end_pos should contain top-level minPublishers
        after = block[end_pos:]
        assert '"minPublishers": 1' in after

    def test_dual_structure_feed(self):
        """Feed with minPublishers in both marketSchedules and top-level."""
        bounds = _find_feed_block(SAMPLE_CONFIG_RAW, 200)
        block = SAMPLE_CONFIG_RAW[bounds[0] : bounds[1]]
        end_pos = _find_market_schedules_end(block)
        assert end_pos is not None
        before = block[:end_pos]
        after = block[end_pos:]
        # Session-level minPublishers is BEFORE end_pos
        assert '"minPublishers": 3' in before
        # Top-level minPublishers is AFTER end_pos
        assert '"minPublishers": 1' in after

    def test_no_market_schedules(self):
        """Feed without marketSchedules key."""
        block = '{"feedId": 1, "minPublishers": 1, "state": "STABLE"}'
        assert _find_market_schedules_end(block) is None


# ── Task 4: modify_config Tests ──────────────────────────────────────────


class TestModifyConfig:
    """End-to-end JSON modification."""

    def test_simple_feed_updated(self, tmp_path):
        """Non-dual feed: top-level minPublishers changed."""
        config = {
            "feeds": [
                {
                    "allowedPublisherIds": [10, 20, 30, 40, 50],
                    "feedId": 100,
                    "marketSchedules": [
                        {"marketSchedule": "X", "session": "REGULAR"}
                    ],
                    "metadata": {"asset_type": "equity", "name": "FOO"},
                    "minPublishers": 1,
                    "state": "STABLE",
                    "symbol": "Equity.US.FOO/USD",
                }
            ]
        }
        config_file = tmp_path / "after.json"
        config_file.write_text(json.dumps(config, indent=2))

        result = modify_config(str(config_file), dry_run=False)

        data = json.loads(config_file.read_text())
        assert data["feeds"][0]["minPublishers"] == 2
        assert result["updated"] == 1

    def test_dual_structure_only_top_level_changed(self, tmp_path):
        """Feed with minPublishers in marketSchedules AND top-level:
        only top-level is changed, session-level stays at 3."""
        config = {
            "feeds": [
                {
                    "allowedPublisherIds": list(range(10, 24)),
                    "feedId": 200,
                    "marketSchedules": [
                        {
                            "allowedPublisherIds": list(range(10, 24)),
                            "marketSchedule": "X",
                            "minPublishers": 3,
                            "session": "REGULAR",
                        }
                    ],
                    "metadata": {"asset_type": "equity", "name": "BAR"},
                    "minPublishers": 1,
                    "state": "STABLE",
                    "symbol": "Equity.US.BAR/USD",
                }
            ]
        }
        config_file = tmp_path / "after.json"
        config_file.write_text(json.dumps(config, indent=2))

        modify_config(str(config_file), dry_run=False)

        raw = config_file.read_text()
        data = json.loads(raw)
        # Top-level should be 3 now
        assert data["feeds"][0]["minPublishers"] == 3
        # Session-level should remain 3
        assert data["feeds"][0]["marketSchedules"][0]["minPublishers"] == 3

    def test_dry_run_no_write(self, tmp_path):
        """Dry run does not modify the file."""
        config = {
            "feeds": [
                {
                    "allowedPublisherIds": [10, 20, 30, 40, 50],
                    "feedId": 100,
                    "marketSchedules": [
                        {"marketSchedule": "X", "session": "REGULAR"}
                    ],
                    "metadata": {"asset_type": "equity", "name": "FOO"},
                    "minPublishers": 1,
                    "state": "STABLE",
                    "symbol": "Equity.US.FOO/USD",
                }
            ]
        }
        config_file = tmp_path / "after.json"
        original = json.dumps(config, indent=2)
        config_file.write_text(original)

        modify_config(str(config_file), dry_run=True)

        assert config_file.read_text() == original

    def test_backup_created(self, tmp_path):
        """Backup file is created on write."""
        config = {
            "feeds": [
                {
                    "allowedPublisherIds": [10, 20, 30, 40, 50],
                    "feedId": 100,
                    "marketSchedules": [
                        {"marketSchedule": "X", "session": "REGULAR"}
                    ],
                    "metadata": {"asset_type": "equity", "name": "FOO"},
                    "minPublishers": 1,
                    "state": "STABLE",
                    "symbol": "Equity.US.FOO/USD",
                }
            ]
        }
        config_file = tmp_path / "after.json"
        config_file.write_text(json.dumps(config, indent=2))

        modify_config(str(config_file), dry_run=False)

        assert (tmp_path / "after.json.bak").exists()

    def test_idempotency(self, tmp_path):
        """Running twice produces no changes on the second run."""
        config = {
            "feeds": [
                {
                    "allowedPublisherIds": [10, 20, 30, 40, 50],
                    "feedId": 100,
                    "marketSchedules": [
                        {"marketSchedule": "X", "session": "REGULAR"}
                    ],
                    "metadata": {"asset_type": "equity", "name": "FOO"},
                    "minPublishers": 1,
                    "state": "STABLE",
                    "symbol": "Equity.US.FOO/USD",
                }
            ]
        }
        config_file = tmp_path / "after.json"
        config_file.write_text(json.dumps(config, indent=2))

        # First run
        modify_config(str(config_file), dry_run=False)
        # Second run
        result = modify_config(str(config_file), dry_run=False)

        assert result["updated"] == 0


# ── Task 5: CSV Report Tests ────────────────────────────────────────────

import csv


class TestWriteCsvReport:
    """CSV audit report generation."""

    def test_csv_columns(self, tmp_path):
        """CSV has correct headers."""
        changes = [
            FeedChange(100, "Equity.US.FOO/USD", "equity", 1, 2, 5, "UPDATED"),
        ]
        csv_path = tmp_path / "report.csv"
        write_csv_report(changes, str(csv_path))

        with open(csv_path) as f:
            reader = csv.DictReader(f)
            assert reader.fieldnames == [
                "feed_id",
                "symbol",
                "asset_type",
                "old_min_publishers",
                "new_min_publishers",
                "allowed_publisher_count",
                "status",
            ]

    def test_csv_all_statuses(self, tmp_path):
        """CSV includes all status types."""
        changes = [
            FeedChange(100, "A/USD", "equity", 1, 2, 5, "UPDATED"),
            FeedChange(200, "B/USD", "equity", 1, None, 3, "SKIPPED_LOW_PUBLISHERS"),
            FeedChange(300, "C/USD", "equity", 2, None, 5, "SKIPPED_EQUAL"),
            FeedChange(400, "D/USD", "equity", 3, None, 5, "SKIPPED_HIGHER"),
            FeedChange(500, "E/USD", "equity", 1, None, 1, "NEEDS_ATTENTION"),
        ]
        csv_path = tmp_path / "report.csv"
        write_csv_report(changes, str(csv_path))

        with open(csv_path) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 5
        statuses = [r["status"] for r in rows]
        assert "UPDATED" in statuses
        assert "SKIPPED_LOW_PUBLISHERS" in statuses
        assert "SKIPPED_EQUAL" in statuses
        assert "SKIPPED_HIGHER" in statuses
        assert "NEEDS_ATTENTION" in statuses

    def test_csv_none_new_min_publishers(self, tmp_path):
        """Skipped feeds have empty new_min_publishers in CSV."""
        changes = [
            FeedChange(100, "A/USD", "equity", 1, None, 3, "SKIPPED_LOW_PUBLISHERS"),
        ]
        csv_path = tmp_path / "report.csv"
        write_csv_report(changes, str(csv_path))

        with open(csv_path) as f:
            rows = list(csv.DictReader(f))
        assert rows[0]["new_min_publishers"] == ""
