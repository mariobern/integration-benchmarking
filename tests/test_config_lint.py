from lib.config_lint import (
    LintFinding,
    lint_config,
    check_duplicates,
    check_schema,
    check_publishers,
)


def _make_feed(
    feed_id,
    symbol="Crypto.BTC/USD",
    state="STABLE",
    kind="PRICE",
    asset_type="crypto",
    min_publishers=3,
    publisher_ids=None,
    schedules=None,
):
    """Build a minimal feed dict matching after.json structure."""
    feed = {
        "feedId": feed_id,
        "symbol": symbol,
        "state": state,
        "kind": kind,
        "minPublishers": min_publishers,
        "metadata": {"asset_type": asset_type},
        "marketSchedules": schedules
        or [
            {
                "marketSchedule": "America/New_York;O,O,O,O,O,O,O;",
                "session": "REGULAR",
            }
        ],
    }
    if publisher_ids is not None:
        feed["allowedPublisherIds"] = publisher_ids
    return feed


def _make_config(feeds, publishers=None):
    """Build a minimal config dict matching after.json structure."""
    return {
        "feeds": feeds,
        "publishers": publishers
        or [
            {
                "publisherId": 1,
                "name": "pub1",
                "keyType": "PRODUCTION",
                "isActive": True,
            },
            {
                "publisherId": 2,
                "name": "pub2",
                "keyType": "PRODUCTION",
                "isActive": True,
            },
            {
                "publisherId": 3,
                "name": "pub3",
                "keyType": "PRODUCTION",
                "isActive": True,
            },
        ],
    }


class TestLintFinding:
    def test_dataclass_fields(self):
        f = LintFinding(
            rule_id="E001",
            severity="ERROR",
            message="test",
            feed_id=1,
            symbol="Crypto.BTC/USD",
        )
        assert f.rule_id == "E001"
        assert f.severity == "ERROR"
        assert f.feed_id == 1

    def test_optional_fields(self):
        f = LintFinding(
            rule_id="E001", severity="ERROR", message="test", feed_id=None, symbol=None
        )
        assert f.feed_id is None
        assert f.symbol is None


class TestCheckDuplicates:
    def test_e001_duplicate_feed_id(self):
        feeds = [
            _make_feed(1, symbol="Crypto.BTC/USD"),
            _make_feed(1, symbol="Crypto.ETH/USD"),
        ]
        findings = check_duplicates(feeds)
        errors = [f for f in findings if f.rule_id == "E001"]
        assert len(errors) == 1
        assert "1" in errors[0].message

    def test_e001_no_duplicate(self):
        feeds = [
            _make_feed(1, symbol="Crypto.BTC/USD"),
            _make_feed(2, symbol="Crypto.ETH/USD"),
        ]
        findings = check_duplicates(feeds)
        errors = [f for f in findings if f.rule_id == "E001"]
        assert len(errors) == 0

    def test_e002_duplicate_symbol_stable(self):
        feeds = [
            _make_feed(1, symbol="Crypto.BTC/USD", state="STABLE"),
            _make_feed(2, symbol="Crypto.BTC/USD", state="STABLE"),
        ]
        findings = check_duplicates(feeds)
        errors = [f for f in findings if f.rule_id == "E002"]
        assert len(errors) == 1

    def test_e002_duplicate_symbol_coming_soon(self):
        feeds = [
            _make_feed(1, symbol="Crypto.BTC/USD", state="COMING_SOON"),
            _make_feed(2, symbol="Crypto.BTC/USD", state="COMING_SOON"),
        ]
        findings = check_duplicates(feeds)
        errors = [f for f in findings if f.rule_id == "E002"]
        assert len(errors) == 1

    def test_e002_inactive_duplicate_not_flagged(self):
        feeds = [
            _make_feed(1, symbol="Crypto.BTC/USD", state="INACTIVE"),
            _make_feed(2, symbol="Crypto.BTC/USD", state="INACTIVE"),
        ]
        findings = check_duplicates(feeds)
        errors = [f for f in findings if f.rule_id == "E002"]
        assert len(errors) == 0

    def test_e002_stable_and_inactive_not_flagged(self):
        """STABLE + INACTIVE with same symbol is OK (different state groups)."""
        feeds = [
            _make_feed(1, symbol="Crypto.BTC/USD", state="STABLE"),
            _make_feed(2, symbol="Crypto.BTC/USD", state="INACTIVE"),
        ]
        findings = check_duplicates(feeds)
        errors = [f for f in findings if f.rule_id == "E002"]
        assert len(errors) == 0

    def test_e002_stable_and_coming_soon_flagged(self):
        """STABLE + COMING_SOON with same symbol IS a duplicate (both active pipeline)."""
        feeds = [
            _make_feed(1, symbol="Crypto.BTC/USD", state="STABLE"),
            _make_feed(2, symbol="Crypto.BTC/USD", state="COMING_SOON"),
        ]
        findings = check_duplicates(feeds)
        errors = [f for f in findings if f.rule_id == "E002"]
        assert len(errors) == 1

    def test_empty_feeds(self):
        findings = check_duplicates([])
        assert findings == []


class TestCheckSchema:
    def test_e007_missing_kind(self):
        feed = _make_feed(1)
        del feed["kind"]
        findings = check_schema([feed])
        assert len(findings) == 1
        assert findings[0].rule_id == "E007"
        assert "kind" in findings[0].message

    def test_e007_missing_metadata_asset_type(self):
        feed = _make_feed(1)
        del feed["metadata"]["asset_type"]
        findings = check_schema([feed])
        assert len(findings) == 1
        assert findings[0].rule_id == "E007"

    def test_e007_missing_metadata_entirely(self):
        feed = _make_feed(1)
        del feed["metadata"]
        findings = check_schema([feed])
        assert len(findings) == 1
        assert findings[0].rule_id == "E007"

    def test_e007_all_fields_present(self):
        feed = _make_feed(1)
        findings = check_schema([feed])
        assert len(findings) == 0

    def test_e007_multiple_missing(self):
        feed = {"feedId": 1}
        findings = check_schema([feed])
        assert len(findings) == 1
        assert "symbol" in findings[0].message or "state" in findings[0].message


def _make_publisher(pub_id, key_type="PRODUCTION"):
    return {
        "publisherId": pub_id,
        "name": f"pub{pub_id}",
        "keyType": key_type,
        "isActive": True,
    }


class TestCheckPublishers:
    def test_e003_invalid_publisher_ref_toplevel(self):
        feeds = [_make_feed(1, publisher_ids=[1, 2, 999])]
        publishers = [_make_publisher(1), _make_publisher(2)]
        findings = check_publishers(feeds, publishers)
        errors = [f for f in findings if f.rule_id == "E003"]
        assert len(errors) == 1
        assert "999" in errors[0].message

    def test_e003_invalid_publisher_ref_session_level(self):
        feeds = [
            _make_feed(
                1,
                symbol="Equity.US.AAPL/USD",
                asset_type="equity",
                publisher_ids=[1, 2],
                schedules=[
                    {"marketSchedule": "America/New_York;O;", "session": "REGULAR"},
                    {
                        "marketSchedule": "America/New_York;0400-0930;",
                        "session": "PRE_MARKET",
                        "allowedPublisherIds": [1, 888],
                        "minPublishers": 1,
                    },
                ],
            )
        ]
        publishers = [_make_publisher(1), _make_publisher(2)]
        findings = check_publishers(feeds, publishers)
        errors = [f for f in findings if f.rule_id == "E003"]
        assert len(errors) == 1
        assert "888" in errors[0].message

    def test_e003_valid_refs(self):
        feeds = [_make_feed(1, publisher_ids=[1, 2])]
        publishers = [_make_publisher(1), _make_publisher(2), _make_publisher(3)]
        findings = check_publishers(feeds, publishers)
        errors = [f for f in findings if f.rule_id == "E003"]
        assert len(errors) == 0

    def test_e004_min_publishers_equals_count(self):
        feeds = [_make_feed(1, min_publishers=3, publisher_ids=[1, 2, 3])]
        publishers = [_make_publisher(1), _make_publisher(2), _make_publisher(3)]
        findings = check_publishers(feeds, publishers)
        errors = [f for f in findings if f.rule_id == "E004"]
        assert len(errors) == 1

    def test_e004_min_publishers_exceeds_count(self):
        feeds = [_make_feed(1, min_publishers=5, publisher_ids=[1, 2, 3])]
        publishers = [_make_publisher(1), _make_publisher(2), _make_publisher(3)]
        findings = check_publishers(feeds, publishers)
        errors = [f for f in findings if f.rule_id == "E004"]
        assert len(errors) == 1

    def test_e004_exempt_asset_type(self):
        feeds = [
            _make_feed(
                1, asset_type="funding-rate", min_publishers=1, publisher_ids=[1]
            )
        ]
        publishers = [_make_publisher(1)]
        findings = check_publishers(feeds, publishers)
        errors = [f for f in findings if f.rule_id == "E004"]
        assert len(errors) == 0

    def test_e004_session_level(self):
        feeds = [
            _make_feed(
                1,
                symbol="Equity.US.AAPL/USD",
                asset_type="equity",
                min_publishers=3,
                publisher_ids=[1, 2, 3, 4, 5],
                schedules=[
                    {"marketSchedule": "America/New_York;O;", "session": "REGULAR"},
                    {
                        "marketSchedule": "America/New_York;0400-0930;",
                        "session": "PRE_MARKET",
                        "allowedPublisherIds": [1, 2],
                        "minPublishers": 2,
                    },
                ],
            )
        ]
        publishers = [_make_publisher(i) for i in range(1, 6)]
        findings = check_publishers(feeds, publishers)
        errors = [f for f in findings if f.rule_id == "E004"]
        assert len(errors) == 1
        assert "PRE_MARKET" in errors[0].message

    def test_e004_min_publishers_zero_not_flagged(self):
        """minPublishers=0 with publishers should not trigger E004."""
        feeds = [_make_feed(1, min_publishers=0, publisher_ids=[1, 2, 3, 4, 5])]
        publishers = [_make_publisher(i) for i in range(1, 6)]
        findings = check_publishers(feeds, publishers)
        errors = [f for f in findings if f.rule_id == "E004"]
        assert len(errors) == 0

    def test_e004_coming_soon_not_checked(self):
        feeds = [
            _make_feed(1, state="COMING_SOON", min_publishers=5, publisher_ids=[1])
        ]
        publishers = [_make_publisher(1)]
        findings = check_publishers(feeds, publishers)
        errors = [f for f in findings if f.rule_id == "E004"]
        assert len(errors) == 0

    def test_e005_stable_no_publishers(self):
        feeds = [_make_feed(1, state="STABLE", publisher_ids=[])]
        publishers = [_make_publisher(1)]
        findings = check_publishers(feeds, publishers)
        errors = [f for f in findings if f.rule_id == "E005"]
        assert len(errors) == 1

    def test_e005_stable_missing_field(self):
        feeds = [
            _make_feed(1, state="STABLE")
        ]  # no publisher_ids kwarg -> field absent
        publishers = [_make_publisher(1)]
        findings = check_publishers(feeds, publishers)
        errors = [f for f in findings if f.rule_id == "E005"]
        assert len(errors) == 1

    def test_e008_session_publisher_not_in_toplevel(self):
        feeds = [
            _make_feed(
                1,
                symbol="Equity.US.AAPL/USD",
                asset_type="equity",
                publisher_ids=[1, 2, 3],
                schedules=[
                    {"marketSchedule": "America/New_York;O;", "session": "REGULAR"},
                    {
                        "marketSchedule": "America/New_York;0400-0930;",
                        "session": "PRE_MARKET",
                        "allowedPublisherIds": [1, 2, 4],
                        "minPublishers": 1,
                    },
                ],
            )
        ]
        publishers = [_make_publisher(i) for i in range(1, 5)]
        findings = check_publishers(feeds, publishers)
        errors = [f for f in findings if f.rule_id == "E008"]
        assert len(errors) == 1
        assert "4" in errors[0].message

    def test_w004_coming_soon_no_publishers(self):
        feeds = [_make_feed(1, state="COMING_SOON")]  # no publisher_ids
        publishers = [_make_publisher(1)]
        findings = check_publishers(feeds, publishers)
        warnings = [f for f in findings if f.rule_id == "W004"]
        assert len(warnings) == 1

    def test_w005_one_headroom(self):
        feeds = [_make_feed(1, min_publishers=4, publisher_ids=[1, 2, 3, 4, 5])]
        publishers = [_make_publisher(i) for i in range(1, 6)]
        findings = check_publishers(feeds, publishers)
        warnings = [f for f in findings if f.rule_id == "W005"]
        assert len(warnings) == 1

    def test_w005_session_level_one_headroom(self):
        feeds = [
            _make_feed(
                1,
                symbol="Equity.US.AAPL/USD",
                asset_type="equity",
                min_publishers=3,
                publisher_ids=[1, 2, 3, 4, 5, 6],
                schedules=[
                    {"marketSchedule": "America/New_York;O;", "session": "REGULAR"},
                    {
                        "marketSchedule": "America/New_York;0400-0930;",
                        "session": "PRE_MARKET",
                        "allowedPublisherIds": [1, 2, 3],
                        "minPublishers": 2,
                    },
                ],
            )
        ]
        publishers = [_make_publisher(i) for i in range(1, 7)]
        findings = check_publishers(feeds, publishers)
        warnings = [f for f in findings if f.rule_id == "W005"]
        assert len(warnings) == 1
        assert "PRE_MARKET" in warnings[0].message

    def test_w005_sufficient_headroom(self):
        feeds = [_make_feed(1, min_publishers=3, publisher_ids=[1, 2, 3, 4, 5])]
        publishers = [_make_publisher(i) for i in range(1, 6)]
        findings = check_publishers(feeds, publishers)
        warnings = [f for f in findings if f.rule_id == "W005"]
        assert len(warnings) == 0

    def test_w006_duplicate_publisher_in_feed(self):
        feeds = [_make_feed(1, publisher_ids=[1, 2, 2, 3])]
        publishers = [_make_publisher(i) for i in range(1, 4)]
        findings = check_publishers(feeds, publishers)
        warnings = [f for f in findings if f.rule_id == "W006"]
        assert len(warnings) == 1
        assert "2" in warnings[0].message

    def test_w007_stable_test_publisher(self):
        feeds = [_make_feed(1, state="STABLE", publisher_ids=[1, 2])]
        publishers = [_make_publisher(1, key_type="TEST"), _make_publisher(2)]
        findings = check_publishers(feeds, publishers)
        warnings = [f for f in findings if f.rule_id == "W007"]
        assert len(warnings) == 1
        assert "1" in warnings[0].message

    def test_w007_coming_soon_test_publisher_not_flagged(self):
        feeds = [_make_feed(1, state="COMING_SOON", publisher_ids=[1])]
        publishers = [_make_publisher(1, key_type="TEST")]
        findings = check_publishers(feeds, publishers)
        warnings = [f for f in findings if f.rule_id == "W007"]
        assert len(warnings) == 0

    def test_missing_allowedPublisherIds_field(self):
        """Feed without allowedPublisherIds field — null-safe handling."""
        feed = _make_feed(1, state="COMING_SOON")
        assert "allowedPublisherIds" not in feed
        findings = check_publishers([feed], [_make_publisher(1)])
        # Should not crash; W004 should fire
        w004 = [f for f in findings if f.rule_id == "W004"]
        assert len(w004) == 1


class TestLintConfigOrchestrator:
    def test_clean_config(self):
        config = _make_config(
            [
                _make_feed(
                    1,
                    symbol="Crypto.BTC/USD",
                    min_publishers=2,
                    publisher_ids=[1, 2, 3],
                ),
                _make_feed(
                    2,
                    symbol="Crypto.ETH/USD",
                    min_publishers=2,
                    publisher_ids=[1, 2, 3],
                ),
            ]
        )
        findings = lint_config(config)
        errors = [f for f in findings if f.severity == "ERROR"]
        assert len(errors) == 0

    def test_empty_feeds(self):
        config = _make_config([])
        findings = lint_config(config)
        assert findings == []
