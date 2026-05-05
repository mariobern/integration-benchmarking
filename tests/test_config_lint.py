from datetime import datetime, timezone

from lib.config_lint import (
    LintFinding,
    lint_config,
    check_duplicates,
    check_schema,
    check_publishers,
    check_publisher_duplicates,
    check_schedules,
    check_hermes_ids,
    check_expired_coming_soon_futures,
    check_benchmark_mapping,
    check_corporate_actions,
    check_identifier_continuity,
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

    def test_e004_message_uses_not_enough_publishers_permissioned(self):
        """E004's trailing clause must read 'Not enough publishers permissioned'."""
        feeds = [_make_feed(1, min_publishers=3, publisher_ids=[1, 2, 3])]
        publishers = [_make_publisher(1), _make_publisher(2), _make_publisher(3)]
        findings = check_publishers(feeds, publishers)
        e004 = [f for f in findings if f.rule_id == "E004"]
        assert len(e004) == 1
        assert "Not enough publishers permissioned" in e004[0].message
        assert "no fault tolerance" not in e004[0].message

    def test_e004_session_level_message_uses_not_enough_publishers_permissioned(self):
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
        e004 = [f for f in findings if f.rule_id == "E004"]
        assert len(e004) == 1
        assert "Not enough publishers permissioned" in e004[0].message

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

    def test_publishers_missing_publisherId_skipped(self):
        """Publishers lacking `publisherId` must not crash check_publishers.

        Mirrors the policy in check_publisher_duplicates: malformed
        publisher entries are silently skipped here; a separate schema
        rule is the right place to flag missing fields.
        """
        feeds = [_make_feed(1, publisher_ids=[1])]
        publishers = [
            _make_publisher(1),
            {"name": "no-id", "keyType": "PRODUCTION"},  # missing publisherId
            {"name": "no-id-but-test", "keyType": "TEST"},  # also missing
            {"name": "evil.test", "keyType": "PRODUCTION"},  # .test name, no id
        ]
        # Should not raise.
        findings = check_publishers(feeds, publishers)
        # Sanity: the well-formed publisher (id=1) is referenced and valid,
        # so no E003 should fire for it.
        e003 = [f for f in findings if f.rule_id == "E003"]
        assert e003 == []


def _us_equity_all_sessions():
    """Return the 4-session schedule set for a properly configured US equity."""
    return [
        {"marketSchedule": "America/New_York;0930-1600;", "session": "REGULAR"},
        {
            "marketSchedule": "America/New_York;0400-0930;",
            "session": "PRE_MARKET",
            "allowedPublisherIds": [1, 2],
            "minPublishers": 1,
        },
        {
            "marketSchedule": "America/New_York;1600-2000;",
            "session": "POST_MARKET",
            "allowedPublisherIds": [1, 2],
            "minPublishers": 1,
        },
        {
            "marketSchedule": "America/New_York;2000-0400;",
            "session": "OVER_NIGHT",
            "allowedPublisherIds": [1, 2],
            "minPublishers": 1,
        },
    ]


def _schedule_with_bm(session="REGULAR"):
    """Return a schedule entry with a benchmarkMapping."""
    return {
        "marketSchedule": "America/New_York;0930-1600;",
        "session": session,
        "benchmarkMapping": {
            "datascope_ric": {
                "identifiers": [
                    {
                        "identifier": "AAPL.O",
                        "validFrom": "1970-01-01T00:00:00.000000000Z",
                    }
                ]
            }
        },
    }


def _schedule_without_bm(session="REGULAR"):
    """Return a schedule entry without benchmarkMapping."""
    return {
        "marketSchedule": "America/New_York;0930-1600;",
        "session": session,
    }


class TestCheckE014BenchmarkMapping:
    def test_e014_stable_equity_with_bm_no_finding(self):
        feed = _make_feed(
            1,
            symbol="Equity.US.AAPL/USD",
            state="STABLE",
            asset_type="equity",
            schedules=[_schedule_with_bm("REGULAR")],
        )
        findings = check_benchmark_mapping([feed])
        assert findings == []

    def test_e014_stable_equity_missing_bm_on_regular(self):
        feed = _make_feed(
            1,
            symbol="Equity.US.AAPL/USD",
            state="STABLE",
            asset_type="equity",
            schedules=[_schedule_without_bm("REGULAR")],
        )
        findings = check_benchmark_mapping([feed])
        errors = [f for f in findings if f.rule_id == "E014"]
        assert len(errors) == 1
        assert "REGULAR" in errors[0].message

    def test_e014_overnight_exempt(self):
        feed = _make_feed(
            1,
            symbol="Equity.US.AAPL/USD",
            state="STABLE",
            asset_type="equity",
            schedules=[_schedule_without_bm("OVER_NIGHT")],
        )
        findings = check_benchmark_mapping([feed])
        assert findings == []

    def test_e014_coming_soon_skipped(self):
        feed = _make_feed(
            1,
            symbol="Equity.US.AAPL/USD",
            state="COMING_SOON",
            asset_type="equity",
            schedules=[_schedule_without_bm("REGULAR")],
        )
        findings = check_benchmark_mapping([feed])
        assert findings == []

    def test_e014_inactive_skipped(self):
        feed = _make_feed(
            1,
            symbol="Equity.US.AAPL/USD",
            state="INACTIVE",
            asset_type="equity",
            schedules=[_schedule_without_bm("REGULAR")],
        )
        findings = check_benchmark_mapping([feed])
        assert findings == []

    def test_e014_crypto_not_benchmarkable(self):
        feed = _make_feed(
            1,
            symbol="Crypto.BTC/USD",
            state="STABLE",
            asset_type="crypto",
            schedules=[_schedule_without_bm("REGULAR")],
        )
        findings = check_benchmark_mapping([feed])
        assert findings == []

    def test_e014_stable_fx_missing_bm(self):
        feed = _make_feed(
            1,
            symbol="FX.EUR/USD",
            state="STABLE",
            asset_type="fx",
            schedules=[_schedule_without_bm("REGULAR")],
        )
        findings = check_benchmark_mapping([feed])
        errors = [f for f in findings if f.rule_id == "E014"]
        assert len(errors) == 1

    def test_e014_empty_bm_dict_flagged(self):
        schedule = {
            "marketSchedule": "America/New_York;0930-1600;",
            "session": "REGULAR",
            "benchmarkMapping": {},
        }
        feed = _make_feed(
            1,
            symbol="Equity.US.AAPL/USD",
            state="STABLE",
            asset_type="equity",
            schedules=[schedule],
        )
        findings = check_benchmark_mapping([feed])
        errors = [f for f in findings if f.rule_id == "E014"]
        assert len(errors) == 1

    def test_e014_multiple_sessions_missing(self):
        feed = _make_feed(
            1,
            symbol="Equity.US.AAPL/USD",
            state="STABLE",
            asset_type="equity",
            schedules=[
                _schedule_without_bm("REGULAR"),
                _schedule_without_bm("PRE_MARKET"),
            ],
        )
        findings = check_benchmark_mapping([feed])
        errors = [f for f in findings if f.rule_id == "E014"]
        assert len(errors) == 2


class TestCheckSchedules:
    def test_e006_non_equity_with_extended_session(self):
        feeds = [
            _make_feed(
                1,
                symbol="FX.EUR/USD",
                asset_type="fx",
                schedules=[
                    {"marketSchedule": "America/New_York;O;", "session": "REGULAR"},
                    {
                        "marketSchedule": "America/New_York;0400-0930;",
                        "session": "PRE_MARKET",
                    },
                ],
            )
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E006"]
        assert len(errors) == 1

    def test_e006_equity_with_extended_ok(self):
        feeds = [
            _make_feed(
                1,
                symbol="Equity.US.AAPL/USD",
                asset_type="equity",
                schedules=_us_equity_all_sessions(),
            )
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E006"]
        assert len(errors) == 0

    def test_w001_equity_missing_extended(self):
        feeds = [
            _make_feed(
                1,
                symbol="Equity.US.AAPL/USD",
                asset_type="equity",
                state="STABLE",
                schedules=[
                    {
                        "marketSchedule": "America/New_York;0930-1600;",
                        "session": "REGULAR",
                    },
                ],
            )
        ]
        findings = check_schedules(feeds)
        warnings = [f for f in findings if f.rule_id == "W001"]
        assert len(warnings) == 1
        # Missing all 3 extended sessions
        assert "PRE_MARKET" in warnings[0].message
        assert "POST_MARKET" in warnings[0].message
        assert "OVER_NIGHT" in warnings[0].message

    def test_w001_non_us_equity_not_flagged(self):
        feeds = [
            _make_feed(
                1,
                symbol="Equity.GB.VOD/GBP",
                asset_type="equity",
                state="STABLE",
                schedules=[
                    {
                        "marketSchedule": "Europe/London;0800-1630;",
                        "session": "REGULAR",
                    },
                ],
            )
        ]
        findings = check_schedules(feeds)
        warnings = [f for f in findings if f.rule_id == "W001"]
        assert len(warnings) == 0

    def test_w002_us_equity_wrong_timezone(self):
        feeds = [
            _make_feed(
                1,
                symbol="Equity.US.AAPL/USD",
                asset_type="equity",
                state="STABLE",
                schedules=[
                    {"marketSchedule": "UTC;0930-1600;", "session": "REGULAR"},
                ],
            )
        ]
        findings = check_schedules(feeds)
        warnings = [f for f in findings if f.rule_id == "W002"]
        assert len(warnings) == 1

    def test_w002_non_us_equity_different_tz_ok(self):
        feeds = [
            _make_feed(
                1,
                symbol="Equity.GB.VOD/GBP",
                asset_type="equity",
                state="STABLE",
                schedules=[
                    {
                        "marketSchedule": "Europe/London;0800-1630;",
                        "session": "REGULAR",
                    },
                ],
            )
        ]
        findings = check_schedules(feeds)
        warnings = [f for f in findings if f.rule_id == "W002"]
        assert len(warnings) == 0

    def test_w003_schedule_deviation(self):
        """One commodity has a different schedule from the majority."""
        majority_schedule = [
            {"marketSchedule": "America/New_York;O,O,O,O,O,O,O;", "session": "REGULAR"}
        ]
        deviant_schedule = [
            {
                "marketSchedule": "America/New_York;0800-1400,0800-1400,0800-1400,0800-1400,0800-1400,C,C;",
                "session": "REGULAR",
            }
        ]
        feeds = [
            _make_feed(
                i,
                symbol=f"Commodities.GOLD{i}/USD",
                asset_type="commodity",
                state="STABLE",
                schedules=majority_schedule,
            )
            for i in range(1, 6)
        ] + [
            _make_feed(
                6,
                symbol="Commodities.ODD/USD",
                asset_type="commodity",
                state="STABLE",
                schedules=deviant_schedule,
            )
        ]
        findings = check_schedules(feeds)
        warnings = [f for f in findings if f.rule_id == "W003"]
        assert len(warnings) == 1
        assert warnings[0].feed_id == 6

    def test_w003_futures_exempt(self):
        """A lone future is silent because its (asset_type, futures_root)
        subgroup has only one feed — no peer to disagree with. Spot peers
        live in a different group and are not compared against it."""
        majority_schedule = [
            {"marketSchedule": "America/New_York;O,O,O,O,O,O,O;", "session": "REGULAR"}
        ]
        deviant_schedule = [
            {"marketSchedule": "America/New_York;0800-1400;", "session": "REGULAR"}
        ]
        feeds = [
            _make_feed(
                i,
                symbol=f"Commodities.GOLD{i}/USD",
                asset_type="commodity",
                state="STABLE",
                schedules=majority_schedule,
            )
            for i in range(1, 4)
        ] + [
            _make_feed(
                4,
                symbol="Commodities.CCH6/USD",
                asset_type="commodity",
                state="STABLE",
                schedules=deviant_schedule,
            )
        ]
        findings = check_schedules(feeds)
        warnings = [f for f in findings if f.rule_id == "W003"]
        assert len(warnings) == 0

    def test_w003_single_feed_in_class(self):
        feeds = [
            _make_feed(1, symbol="Rates.US10Y/USD", asset_type="rates", state="STABLE")
        ]
        findings = check_schedules(feeds)
        warnings = [f for f in findings if f.rule_id == "W003"]
        assert len(warnings) == 0

    def test_inactive_feeds_skipped(self):
        feeds = [
            _make_feed(
                1,
                symbol="FX.EUR/USD",
                asset_type="fx",
                state="INACTIVE",
                schedules=[
                    {"marketSchedule": "America/New_York;O;", "session": "REGULAR"},
                    {
                        "marketSchedule": "America/New_York;0400-0930;",
                        "session": "PRE_MARKET",
                    },
                ],
            )
        ]
        findings = check_schedules(feeds)
        assert len(findings) == 0


class TestCheckE009TestPublishers:
    def test_e009_stable_with_test_named_publisher(self):
        feeds = [_make_feed(1, state="STABLE", publisher_ids=[1, 2])]
        publishers = [
            {
                "publisherId": 1,
                "name": "LoTech.Test",
                "keyType": "PRODUCTION",
                "isActive": True,
            },
            _make_publisher(2),
        ]
        findings = check_publishers(feeds, publishers)
        errors = [f for f in findings if f.rule_id == "E009"]
        assert len(errors) == 1
        assert "1" in errors[0].message

    def test_e009_production_name_not_flagged(self):
        feeds = [_make_feed(1, state="STABLE", publisher_ids=[1])]
        publishers = [
            {
                "publisherId": 1,
                "name": "LoTech.Production",
                "keyType": "PRODUCTION",
                "isActive": True,
            }
        ]
        findings = check_publishers(feeds, publishers)
        errors = [f for f in findings if f.rule_id == "E009"]
        assert len(errors) == 0

    def test_e009_coming_soon_not_flagged(self):
        feeds = [_make_feed(1, state="COMING_SOON", publisher_ids=[1])]
        publishers = [
            {
                "publisherId": 1,
                "name": "LoTech.Test",
                "keyType": "PRODUCTION",
                "isActive": True,
            }
        ]
        findings = check_publishers(feeds, publishers)
        errors = [f for f in findings if f.rule_id == "E009"]
        assert len(errors) == 0

    def test_e009_case_insensitive(self):
        feeds = [_make_feed(1, state="STABLE", publisher_ids=[1])]
        publishers = [
            {
                "publisherId": 1,
                "name": "Foo.test",
                "keyType": "PRODUCTION",
                "isActive": True,
            }
        ]
        findings = check_publishers(feeds, publishers)
        errors = [f for f in findings if f.rule_id == "E009"]
        assert len(errors) == 1


class TestCheckE010DuplicateSession:
    def test_e010_duplicate_session_name(self):
        feeds = [
            _make_feed(
                1,
                schedules=[
                    {
                        "marketSchedule": "America/New_York;O,O,O,O,O,O,O;",
                        "session": "REGULAR",
                    },
                    {
                        "marketSchedule": "America/New_York;0800-1400;",
                        "session": "REGULAR",
                    },
                ],
            )
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E010"]
        assert len(errors) == 1
        assert "REGULAR" in errors[0].message

    def test_e010_identical_tuple_repeated(self):
        feeds = [
            _make_feed(
                1,
                symbol="Equity.US.AAPL/USD",
                asset_type="equity",
                schedules=[
                    {
                        "marketSchedule": "America/New_York;0930-1600;",
                        "session": "REGULAR",
                    },
                    {
                        "marketSchedule": "America/New_York;0930-1600;",
                        "session": "REGULAR",
                    },
                ],
            )
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E010"]
        # Duplicate session name fires AND verbatim duplicate fires
        assert len(errors) >= 1
        assert any("duplicate verbatim" in e.message for e in errors)

    def test_e010_inactive_skipped(self):
        feeds = [
            _make_feed(
                1,
                state="INACTIVE",
                schedules=[
                    {"marketSchedule": "A", "session": "REGULAR"},
                    {"marketSchedule": "B", "session": "REGULAR"},
                ],
            )
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E010"]
        assert len(errors) == 0


class TestCheckE011ScheduleInconsistency:
    def test_e011_equity_group_disagrees(self):
        sched_a = [
            {"marketSchedule": "America/New_York;0930-1600;", "session": "REGULAR"}
        ]
        sched_b = [
            {"marketSchedule": "America/New_York;0800-1500;", "session": "REGULAR"}
        ]
        feeds = [
            _make_feed(
                1,
                symbol="Equity.US.AAPL/USD",
                asset_type="equity",
                schedules=sched_a,
            ),
            _make_feed(
                2,
                symbol="Equity.US.MSFT/USD",
                asset_type="equity",
                schedules=sched_a,
            ),
            _make_feed(
                3,
                symbol="Equity.US.GOOG/USD",
                asset_type="equity",
                schedules=sched_b,
            ),
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E011"]
        assert len(errors) == 1
        assert errors[0].feed_id == 3

    def test_e011_futures_same_root_disagree(self):
        sched_a = [{"marketSchedule": "America/New_York;O;", "session": "REGULAR"}]
        sched_b = [
            {"marketSchedule": "America/New_York;0800-1400;", "session": "REGULAR"}
        ]
        feeds = [
            _make_feed(
                1,
                symbol="Commodities.WTIK6/USD",
                asset_type="commodity",
                schedules=sched_a,
            ),
            _make_feed(
                2,
                symbol="Commodities.WTIM6/USD",
                asset_type="commodity",
                schedules=sched_b,
            ),
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E011"]
        assert len(errors) == 1

    def test_e011_different_futures_roots_not_flagged(self):
        sched_a = [{"marketSchedule": "America/New_York;O;", "session": "REGULAR"}]
        sched_b = [
            {"marketSchedule": "America/New_York;0800-1400;", "session": "REGULAR"}
        ]
        feeds = [
            _make_feed(
                1,
                symbol="Commodities.WTIK6/USD",
                asset_type="commodity",
                schedules=sched_a,
            ),
            _make_feed(
                2,
                symbol="Commodities.CLK6/USD",
                asset_type="commodity",
                schedules=sched_b,
            ),
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E011"]
        assert len(errors) == 0

    def test_e011_spot_and_futures_different_groups(self):
        sched_a = [
            {"marketSchedule": "America/New_York;0930-1600;", "session": "REGULAR"}
        ]
        sched_b = [{"marketSchedule": "America/New_York;O;", "session": "REGULAR"}]
        feeds = [
            _make_feed(
                1,
                symbol="Equity.US.AAPL/USD",
                asset_type="equity",
                schedules=sched_a,
            ),
            _make_feed(
                2,
                symbol="Equity.US.EMH6/USD",
                asset_type="equity",
                schedules=sched_b,
            ),
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E011"]
        assert len(errors) == 0


class TestE011IntlEquityGrouping:
    """E011 must group equities by listing prefix (US, JP, Index, ...) so
    non-US equities are not compared against the US-majority signature."""

    def test_e011_intra_jp_drift_fires(self):
        """3 STABLE Equity.JP feeds, 1 with a different schedule -> E011."""
        sched_a = [{"marketSchedule": "Asia/Tokyo;0900-1500;", "session": "REGULAR"}]
        sched_b = [{"marketSchedule": "Asia/Tokyo;0900-1530;", "session": "REGULAR"}]
        feeds = [
            _make_feed(
                1,
                symbol="Equity.JP.1305/JPY",
                asset_type="equity",
                state="STABLE",
                schedules=sched_a,
            ),
            _make_feed(
                2,
                symbol="Equity.JP.1306/JPY",
                asset_type="equity",
                state="STABLE",
                schedules=sched_a,
            ),
            _make_feed(
                3,
                symbol="Equity.JP.1308/JPY",
                asset_type="equity",
                state="STABLE",
                schedules=sched_b,
            ),
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E011"]
        assert len(errors) == 1
        assert errors[0].feed_id == 3

    def test_e011_cross_prefix_silent(self):
        """An Equity.JP feed and an Equity.US feed with different
        timezones must NOT trip E011 — they belong to different groups."""
        feeds = [
            _make_feed(
                1,
                symbol="Equity.US.AAPL/USD",
                asset_type="equity",
                state="STABLE",
                schedules=[
                    {
                        "marketSchedule": "America/New_York;0930-1600;",
                        "session": "REGULAR",
                    }
                ],
            ),
            _make_feed(
                2,
                symbol="Equity.JP.1305/JPY",
                asset_type="equity",
                state="STABLE",
                schedules=[
                    {"marketSchedule": "Asia/Tokyo;0900-1500;", "session": "REGULAR"}
                ],
            ),
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E011"]
        assert len(errors) == 0

    def test_e011_index_standalone_from_us(self):
        """Equity.Index.* must NOT group with Equity.US.* — they are
        separate prefixes even though both use America/New_York."""
        sched = [
            {"marketSchedule": "America/New_York;0930-1600;", "session": "REGULAR"}
        ]
        sched_dev = [
            {"marketSchedule": "America/New_York;0800-1500;", "session": "REGULAR"}
        ]
        feeds = [
            _make_feed(
                1,
                symbol="Equity.US.AAPL/USD",
                asset_type="equity",
                state="STABLE",
                schedules=sched,
            ),
            _make_feed(
                2,
                symbol="Equity.US.MSFT/USD",
                asset_type="equity",
                state="STABLE",
                schedules=sched,
            ),
            _make_feed(
                3,
                symbol="Equity.Index.TSLA/USD",
                asset_type="equity",
                state="STABLE",
                schedules=sched_dev,
            ),
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E011"]
        # Index is a single-member group; no peer to disagree with.
        assert len(errors) == 0

    def test_e011_intra_index_drift_fires(self):
        """If 2+ Equity.Index feeds disagree, E011 must fire on the minority."""
        sched_a = [
            {"marketSchedule": "America/New_York;0930-1600;", "session": "REGULAR"}
        ]
        sched_b = [
            {"marketSchedule": "America/New_York;0800-1500;", "session": "REGULAR"}
        ]
        feeds = [
            _make_feed(
                1,
                symbol="Equity.Index.TSLA/USD",
                asset_type="equity",
                state="STABLE",
                schedules=sched_a,
            ),
            _make_feed(
                2,
                symbol="Equity.Index.MSTR/USD",
                asset_type="equity",
                state="STABLE",
                schedules=sched_a,
            ),
            _make_feed(
                3,
                symbol="Equity.Index.CRCL/USD",
                asset_type="equity",
                state="STABLE",
                schedules=sched_b,
            ),
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E011"]
        assert len(errors) == 1
        assert errors[0].feed_id == 3

    def test_e011_intl_futures_subgrouped_by_country(self):
        """KR equity futures and US equity futures must not cross-compare."""
        feeds = [
            _make_feed(
                1,
                symbol="Equity.US.EMH6/USD",
                asset_type="equity",
                state="STABLE",
                schedules=[
                    {
                        "marketSchedule": "America/New_York;0930-1600;",
                        "session": "REGULAR",
                    }
                ],
            ),
            _make_feed(
                2,
                symbol="Equity.KR.KSM6/KRW",
                asset_type="equity",
                state="STABLE",
                schedules=[
                    {"marketSchedule": "Asia/Seoul;0900-1530;", "session": "REGULAR"}
                ],
            ),
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E011"]
        assert len(errors) == 0


class TestE011StableOnlyScope:
    """E011 is a CI blocker; it must only fire on STABLE feeds.
    COMING_SOON drift is W003's responsibility."""

    def test_e011_silent_on_coming_soon_only_drift(self):
        """A COMING_SOON feed disagreeing with another COMING_SOON feed
        does NOT fire E011 (no STABLE involvement)."""
        sched_a = [
            {"marketSchedule": "America/New_York;0930-1600;", "session": "REGULAR"}
        ]
        sched_b = [
            {"marketSchedule": "America/New_York;0800-1500;", "session": "REGULAR"}
        ]
        feeds = [
            _make_feed(
                1,
                symbol="Equity.US.NEW1/USD",
                asset_type="equity",
                state="COMING_SOON",
                schedules=sched_a,
            ),
            _make_feed(
                2,
                symbol="Equity.US.NEW2/USD",
                asset_type="equity",
                state="COMING_SOON",
                schedules=sched_b,
            ),
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E011"]
        assert len(errors) == 0

    def test_e011_silent_when_only_coming_soon_deviates(self):
        """Multiple agreeing STABLE feeds + one COMING_SOON deviant ->
        E011 must NOT fire (drift is in non-STABLE feed)."""
        sched_majority = [
            {"marketSchedule": "America/New_York;0930-1600;", "session": "REGULAR"}
        ]
        sched_deviant = [
            {"marketSchedule": "America/New_York;0800-1500;", "session": "REGULAR"}
        ]
        feeds = [
            _make_feed(
                1,
                symbol="Equity.US.AAPL/USD",
                asset_type="equity",
                state="STABLE",
                schedules=sched_majority,
            ),
            _make_feed(
                2,
                symbol="Equity.US.MSFT/USD",
                asset_type="equity",
                state="STABLE",
                schedules=sched_majority,
            ),
            _make_feed(
                3,
                symbol="Equity.US.NEW1/USD",
                asset_type="equity",
                state="COMING_SOON",
                schedules=sched_deviant,
            ),
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E011"]
        assert len(errors) == 0

    def test_e011_fires_when_stable_deviates_from_stable(self):
        """Sanity: STABLE-vs-STABLE drift still fires (already covered by
        TestCheckE011ScheduleInconsistency, repeated here for clarity)."""
        sched_a = [
            {"marketSchedule": "America/New_York;0930-1600;", "session": "REGULAR"}
        ]
        sched_b = [
            {"marketSchedule": "America/New_York;0800-1500;", "session": "REGULAR"}
        ]
        feeds = [
            _make_feed(
                1,
                symbol="Equity.US.AAPL/USD",
                asset_type="equity",
                state="STABLE",
                schedules=sched_a,
            ),
            _make_feed(
                2,
                symbol="Equity.US.MSFT/USD",
                asset_type="equity",
                state="STABLE",
                schedules=sched_a,
            ),
            _make_feed(
                3,
                symbol="Equity.US.GOOG/USD",
                asset_type="equity",
                state="STABLE",
                schedules=sched_b,
            ),
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E011"]
        assert len(errors) == 1
        assert errors[0].feed_id == 3


class TestW003ExpandedScope:
    """W003 must:
    - group equities by listing prefix (same as E011),
    - cover STABLE + COMING_SOON,
    - include futures via futures_root sub-grouping (no longer exempt).
    """

    def test_w003_intl_equity_prefix_grouping(self):
        """3 STABLE Equity.JP majority + 1 STABLE Equity.JP minority -> W003 fires."""
        sched_a = [{"marketSchedule": "Asia/Tokyo;0900-1500;", "session": "REGULAR"}]
        sched_b = [{"marketSchedule": "Asia/Tokyo;0900-1530;", "session": "REGULAR"}]
        feeds = [
            _make_feed(
                i,
                symbol=f"Equity.JP.130{i}/JPY",
                asset_type="equity",
                state="STABLE",
                schedules=sched_a,
            )
            for i in range(1, 4)
        ] + [
            _make_feed(
                4,
                symbol="Equity.JP.1308/JPY",
                asset_type="equity",
                state="STABLE",
                schedules=sched_b,
            )
        ]
        findings = check_schedules(feeds)
        warnings = [f for f in findings if f.rule_id == "W003"]
        assert len(warnings) == 1
        assert warnings[0].feed_id == 4

    def test_w003_cross_prefix_silent(self):
        """An Equity.JP feed and an Equity.US feed must NOT cross-flag W003."""
        us_tickers = ["AAPL", "MSFT", "TSLA"]
        feeds = [
            _make_feed(
                i + 1,
                symbol=f"Equity.US.{ticker}/USD",
                asset_type="equity",
                state="STABLE",
                schedules=[
                    {
                        "marketSchedule": "America/New_York;0930-1600;",
                        "session": "REGULAR",
                    }
                ],
            )
            for i, ticker in enumerate(us_tickers)
        ] + [
            _make_feed(
                4,
                symbol="Equity.JP.1305/JPY",
                asset_type="equity",
                state="STABLE",
                schedules=[
                    {"marketSchedule": "Asia/Tokyo;0900-1500;", "session": "REGULAR"}
                ],
            )
        ]
        findings = check_schedules(feeds)
        warnings = [f for f in findings if f.rule_id == "W003"]
        assert len(warnings) == 0

    def test_w003_coming_soon_drift_fires(self):
        """COMING_SOON spot feed drifts from STABLE majority -> W003 fires."""
        sched_majority = [
            {"marketSchedule": "America/New_York;0930-1600;", "session": "REGULAR"}
        ]
        sched_deviant = [
            {"marketSchedule": "America/New_York;0800-1500;", "session": "REGULAR"}
        ]
        stable_tickers = ["AAPL", "MSFT", "TSLA"]
        feeds = [
            _make_feed(
                i + 1,
                symbol=f"Equity.US.{ticker}/USD",
                asset_type="equity",
                state="STABLE",
                schedules=sched_majority,
            )
            for i, ticker in enumerate(stable_tickers)
        ] + [
            _make_feed(
                4,
                symbol="Equity.US.NEW1/USD",
                asset_type="equity",
                state="COMING_SOON",
                schedules=sched_deviant,
            )
        ]
        findings = check_schedules(feeds)
        warnings = [f for f in findings if f.rule_id == "W003"]
        assert len(warnings) == 1
        assert warnings[0].feed_id == 4

    def test_w003_stable_futures_intra_root_drift_fires(self):
        """Two STABLE futures with the same root but different schedules ->
        W003 fires (futures are no longer exempt under the new grouping)."""
        feeds = [
            _make_feed(
                1,
                symbol="Commodities.WTIK6/USD",
                asset_type="commodity",
                state="STABLE",
                schedules=[
                    {"marketSchedule": "America/New_York;O;", "session": "REGULAR"}
                ],
            ),
            _make_feed(
                2,
                symbol="Commodities.WTIM6/USD",
                asset_type="commodity",
                state="STABLE",
                schedules=[
                    {"marketSchedule": "America/New_York;O;", "session": "REGULAR"}
                ],
            ),
            _make_feed(
                3,
                symbol="Commodities.WTIN6/USD",
                asset_type="commodity",
                state="STABLE",
                schedules=[
                    {
                        "marketSchedule": "America/New_York;0800-1400;",
                        "session": "REGULAR",
                    }
                ],
            ),
        ]
        findings = check_schedules(feeds)
        warnings = [f for f in findings if f.rule_id == "W003"]
        assert len(warnings) == 1
        assert warnings[0].feed_id == 3

    def test_w003_coming_soon_futures_drift_fires(self):
        """COMING_SOON futures drift from STABLE peers in the same root ->
        W003 fires (was previously silent due to futures exemption)."""
        feeds = [
            _make_feed(
                1,
                symbol="Commodities.WTIK6/USD",
                asset_type="commodity",
                state="STABLE",
                schedules=[
                    {"marketSchedule": "America/New_York;O;", "session": "REGULAR"}
                ],
            ),
            _make_feed(
                2,
                symbol="Commodities.WTIM6/USD",
                asset_type="commodity",
                state="STABLE",
                schedules=[
                    {"marketSchedule": "America/New_York;O;", "session": "REGULAR"}
                ],
            ),
            _make_feed(
                3,
                symbol="Commodities.WTIQ6/USD",
                asset_type="commodity",
                state="COMING_SOON",
                schedules=[
                    {
                        "marketSchedule": "America/New_York;0800-1400;",
                        "session": "REGULAR",
                    }
                ],
            ),
        ]
        findings = check_schedules(feeds)
        warnings = [f for f in findings if f.rule_id == "W003"]
        assert len(warnings) == 1
        assert warnings[0].feed_id == 3

    def test_w003_different_futures_roots_silent(self):
        """Different futures roots are different groups -> no W003."""
        feeds = [
            _make_feed(
                1,
                symbol="Commodities.WTIK6/USD",
                asset_type="commodity",
                state="STABLE",
                schedules=[
                    {"marketSchedule": "America/New_York;O;", "session": "REGULAR"}
                ],
            ),
            _make_feed(
                2,
                symbol="Commodities.CLK6/USD",
                asset_type="commodity",
                state="STABLE",
                schedules=[
                    {
                        "marketSchedule": "America/New_York;0800-1400;",
                        "session": "REGULAR",
                    }
                ],
            ),
        ]
        findings = check_schedules(feeds)
        warnings = [f for f in findings if f.rule_id == "W003"]
        assert len(warnings) == 0


class TestCheckE012HermesId:
    def test_e012_duplicate_hermes_id(self):
        f1 = _make_feed(1, symbol="Crypto.BTC/USD")
        f1["metadata"]["hermes_id"] = "abc123"
        f2 = _make_feed(2, symbol="Crypto.ETH/USD")
        f2["metadata"]["hermes_id"] = "abc123"
        findings = check_hermes_ids([f1, f2])
        errors = [f for f in findings if f.rule_id == "E012"]
        assert len(errors) == 1
        assert "1" in errors[0].message and "2" in errors[0].message

    def test_e012_distinct_hermes_ids(self):
        f1 = _make_feed(1)
        f1["metadata"]["hermes_id"] = "abc123"
        f2 = _make_feed(2, symbol="Crypto.ETH/USD")
        f2["metadata"]["hermes_id"] = "def456"
        findings = check_hermes_ids([f1, f2])
        assert findings == []

    def test_e012_inactive_skipped(self):
        f1 = _make_feed(1, state="STABLE")
        f1["metadata"]["hermes_id"] = "abc123"
        f2 = _make_feed(2, symbol="Crypto.ETH/USD", state="INACTIVE")
        f2["metadata"]["hermes_id"] = "abc123"
        findings = check_hermes_ids([f1, f2])
        assert findings == []

    def test_e012_missing_hermes_id_skipped(self):
        f1 = _make_feed(1)
        f2 = _make_feed(2, symbol="Crypto.ETH/USD")
        # neither has hermes_id
        findings = check_hermes_ids([f1, f2])
        assert findings == []


def _futures_feed_with_validto(feed_id, symbol, valid_to, state="COMING_SOON"):
    feed = _make_feed(
        feed_id,
        symbol=symbol,
        state=state,
        asset_type="commodity",
        schedules=[
            {
                "marketSchedule": "America/New_York;O;",
                "session": "REGULAR",
                "benchmarkMapping": {
                    "datascope_ric": {
                        "identifiers": [
                            {
                                "identifier": "CLK26",
                                "validFrom": "1970-01-01T00:00:00.000000000Z",
                                "validTo": valid_to,
                            }
                        ]
                    }
                },
            }
        ],
    )
    return feed


_NOW = datetime(2026, 4, 11, tzinfo=timezone.utc)


class TestCheckE013ExpiredFutures:
    def test_e013_expired_coming_soon_futures(self):
        feed = _futures_feed_with_validto(
            1, "Commodities.WTIK6/USD", "2026-01-01T00:00:00.000000000Z"
        )
        findings = check_expired_coming_soon_futures([feed], _NOW)
        errors = [f for f in findings if f.rule_id == "E013"]
        assert len(errors) == 1

    def test_e013_not_yet_expired(self):
        feed = _futures_feed_with_validto(
            1, "Commodities.WTIK6/USD", "2026-12-01T00:00:00.000000000Z"
        )
        findings = check_expired_coming_soon_futures([feed], _NOW)
        assert findings == []

    def test_e013_stable_state_not_flagged(self):
        feed = _futures_feed_with_validto(
            1,
            "Commodities.WTIK6/USD",
            "2026-01-01T00:00:00.000000000Z",
            state="STABLE",
        )
        findings = check_expired_coming_soon_futures([feed], _NOW)
        assert findings == []

    def test_e013_non_futures_not_flagged(self):
        feed = _futures_feed_with_validto(
            1, "Crypto.BTC/USD", "2026-01-01T00:00:00.000000000Z"
        )
        findings = check_expired_coming_soon_futures([feed], _NOW)
        assert findings == []

    def test_e013_no_validto_skipped(self):
        feed = _make_feed(
            1,
            symbol="Commodities.WTIK6/USD",
            state="COMING_SOON",
            asset_type="commodity",
            schedules=[
                {
                    "marketSchedule": "America/New_York;O;",
                    "session": "REGULAR",
                    "benchmarkMapping": {
                        "datascope_ric": {
                            "identifiers": [
                                {
                                    "identifier": "CLK26",
                                    "validFrom": "1970-01-01T00:00:00.000000000Z",
                                }
                            ]
                        }
                    },
                }
            ],
        )
        findings = check_expired_coming_soon_futures([feed], _NOW)
        assert findings == []

    def test_e013_mixed_expired_and_future_not_flagged(self):
        feed = _make_feed(
            1,
            symbol="Commodities.WTIK6/USD",
            state="COMING_SOON",
            asset_type="commodity",
            schedules=[
                {
                    "marketSchedule": "America/New_York;O;",
                    "session": "REGULAR",
                    "benchmarkMapping": {
                        "datascope_ric": {
                            "identifiers": [
                                {
                                    "identifier": "CLK26-past",
                                    "validTo": "2026-01-01T00:00:00.000000000Z",
                                },
                                {
                                    "identifier": "CLK26-future",
                                    "validTo": "2026-12-01T00:00:00.000000000Z",
                                },
                            ]
                        }
                    },
                }
            ],
        )
        findings = check_expired_coming_soon_futures([feed], _NOW)
        assert findings == []


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

    def test_e014_through_orchestrator(self):
        config = _make_config(
            [
                _make_feed(
                    1,
                    symbol="Equity.US.AAPL/USD",
                    asset_type="equity",
                    state="STABLE",
                    min_publishers=2,
                    publisher_ids=[1, 2, 3],
                    schedules=[_schedule_without_bm("REGULAR")],
                ),
            ]
        )
        findings = lint_config(config)
        e014 = [f for f in findings if f.rule_id == "E014"]
        assert len(e014) == 1

    def test_e015_through_orchestrator(self):
        feed = _make_feed(
            1,
            symbol="Equity.US.BKNG/USD",
            asset_type="equity",
            state="STABLE",
            min_publishers=2,
            publisher_ids=[1, 2, 3],
            schedules=[_schedule_with_bm("REGULAR")],
        )
        action = _valid_split_action()
        action["adjustmentFactorDenominator"] = "0"
        feed["corporateActions"] = [action]
        config = _make_config([feed])
        findings = lint_config(config)
        e015 = [f for f in findings if f.rule_id == "E015"]
        assert len(e015) == 1


def _valid_split_action():
    """Return a valid SPLIT corporate action."""
    return {
        "eventType": "SPLIT",
        "adjustmentFactorNumerator": "25",
        "adjustmentFactorDenominator": "1",
        "rejectionThresholdBips": "1000",
        "rejectionWindow": "600.000000000s",
        "activation": {
            "usEquityExDate": {
                "exDate": "2026-04-06",
            }
        },
    }


class TestCheckE015CorporateActions:
    def test_e015_valid_split_no_finding(self):
        feed = _make_feed(1, publisher_ids=[1, 2, 3])
        feed["corporateActions"] = [_valid_split_action()]
        findings = check_corporate_actions([feed])
        errors = [f for f in findings if f.rule_id == "E015"]
        assert errors == []

    def test_e015_missing_event_type(self):
        action = _valid_split_action()
        del action["eventType"]
        feed = _make_feed(1, publisher_ids=[1, 2, 3])
        feed["corporateActions"] = [action]
        findings = check_corporate_actions([feed])
        errors = [f for f in findings if f.rule_id == "E015"]
        assert len(errors) == 1
        assert "eventType" in errors[0].message

    def test_e015_missing_numerator(self):
        action = _valid_split_action()
        del action["adjustmentFactorNumerator"]
        feed = _make_feed(1, publisher_ids=[1, 2, 3])
        feed["corporateActions"] = [action]
        findings = check_corporate_actions([feed])
        errors = [f for f in findings if f.rule_id == "E015"]
        assert len(errors) == 1
        assert "adjustmentFactorNumerator" in errors[0].message

    def test_e015_missing_nested_exdate(self):
        action = _valid_split_action()
        del action["activation"]["usEquityExDate"]["exDate"]
        feed = _make_feed(1, publisher_ids=[1, 2, 3])
        feed["corporateActions"] = [action]
        findings = check_corporate_actions([feed])
        errors = [f for f in findings if f.rule_id == "E015"]
        assert len(errors) == 1
        assert "exDate" in errors[0].message

    def test_e015_missing_activation_entirely(self):
        action = _valid_split_action()
        del action["activation"]
        feed = _make_feed(1, publisher_ids=[1, 2, 3])
        feed["corporateActions"] = [action]
        findings = check_corporate_actions([feed])
        errors = [f for f in findings if f.rule_id == "E015"]
        assert len(errors) >= 1
        assert any("activation" in e.message for e in errors)

    def test_e015_missing_usEquityExDate(self):
        action = _valid_split_action()
        action["activation"] = {}
        feed = _make_feed(1, publisher_ids=[1, 2, 3])
        feed["corporateActions"] = [action]
        findings = check_corporate_actions([feed])
        errors = [f for f in findings if f.rule_id == "E015"]
        assert len(errors) >= 1
        assert any("usEquityExDate" in e.message for e in errors)

    def test_e015_denominator_zero(self):
        action = _valid_split_action()
        action["adjustmentFactorDenominator"] = "0"
        feed = _make_feed(1, publisher_ids=[1, 2, 3])
        feed["corporateActions"] = [action]
        findings = check_corporate_actions([feed])
        errors = [f for f in findings if f.rule_id == "E015"]
        assert len(errors) == 1
        assert "adjustmentFactorDenominator" in errors[0].message
        assert "invalid" in errors[0].message

    def test_e015_rejection_window_missing_decimal(self):
        action = _valid_split_action()
        action["rejectionWindow"] = "600s"
        feed = _make_feed(1, publisher_ids=[1, 2, 3])
        feed["corporateActions"] = [action]
        findings = check_corporate_actions([feed])
        errors = [f for f in findings if f.rule_id == "E015"]
        assert len(errors) == 1
        assert "rejectionWindow" in errors[0].message

    def test_e015_invalid_exdate(self):
        action = _valid_split_action()
        action["activation"]["usEquityExDate"]["exDate"] = "2026-13-01"
        feed = _make_feed(1, publisher_ids=[1, 2, 3])
        feed["corporateActions"] = [action]
        findings = check_corporate_actions([feed])
        errors = [f for f in findings if f.rule_id == "E015"]
        assert len(errors) == 1
        assert "exDate" in errors[0].message

    def test_e015_multiple_violations_same_action(self):
        action = _valid_split_action()
        action["adjustmentFactorNumerator"] = "0"
        action["rejectionWindow"] = "bad"
        feed = _make_feed(1, publisher_ids=[1, 2, 3])
        feed["corporateActions"] = [action]
        findings = check_corporate_actions([feed])
        errors = [f for f in findings if f.rule_id == "E015"]
        assert len(errors) == 2

    def test_e015_no_corporate_actions_no_finding(self):
        feed = _make_feed(1, publisher_ids=[1, 2, 3])
        findings = check_corporate_actions([feed])
        assert findings == []

    def test_e015_empty_corporate_actions_no_finding(self):
        feed = _make_feed(1, publisher_ids=[1, 2, 3])
        feed["corporateActions"] = []
        findings = check_corporate_actions([feed])
        assert findings == []

    def test_e015_numerator_non_numeric(self):
        action = _valid_split_action()
        action["adjustmentFactorNumerator"] = "abc"
        feed = _make_feed(1, publisher_ids=[1, 2, 3])
        feed["corporateActions"] = [action]
        findings = check_corporate_actions([feed])
        errors = [f for f in findings if f.rule_id == "E015"]
        assert len(errors) == 1


class TestCheckW009UnknownEventType:
    def test_w009_unknown_event_type(self):
        action = {"eventType": "DIVIDEND"}
        feed = _make_feed(1, publisher_ids=[1, 2, 3])
        feed["corporateActions"] = [action]
        findings = check_corporate_actions([feed])
        w009 = [f for f in findings if f.rule_id == "W009"]
        e015 = [f for f in findings if f.rule_id == "E015"]
        assert len(w009) == 1
        assert len(e015) == 0
        assert "DIVIDEND" in w009[0].message

    def test_w009_known_event_type_no_warning(self):
        feed = _make_feed(1, publisher_ids=[1, 2, 3])
        feed["corporateActions"] = [_valid_split_action()]
        findings = check_corporate_actions([feed])
        w009 = [f for f in findings if f.rule_id == "W009"]
        assert w009 == []


def _feed_with_identifiers(feed_id, identifiers, state="STABLE", session="REGULAR"):
    """Build a feed with specific identifiers in benchmarkMapping."""
    return _make_feed(
        feed_id,
        symbol=f"Commodities.TEST{feed_id}/USD",
        asset_type="commodity",
        state=state,
        schedules=[
            {
                "marketSchedule": "America/New_York;O;",
                "session": session,
                "benchmarkMapping": {
                    "datascope_ric": {
                        "identifiers": identifiers,
                    }
                },
            }
        ],
    )


class TestCheckE016IdentifierContinuity:
    def test_e016_single_identifier_no_finding(self):
        """1 identifier → no finding."""
        feed = _feed_with_identifiers(
            1,
            [
                {
                    "identifier": "CLK26",
                    "validFrom": "2026-01-01T00:00:00.000000000Z",
                }
            ],
        )
        findings = check_identifier_continuity([feed])
        assert findings == []

    def test_e016_two_identifiers_no_overlap(self):
        """CLK26 validTo=2026-03-20, CLM26 validFrom=2026-03-20 → no finding."""
        feed = _feed_with_identifiers(
            2,
            [
                {
                    "identifier": "CLK26",
                    "validFrom": "2026-01-01T00:00:00.000000000Z",
                    "validTo": "2026-03-20T17:00:00.000000000Z",
                },
                {
                    "identifier": "CLM26",
                    "validFrom": "2026-03-20T17:00:00.000000000Z",
                },
            ],
        )
        findings = check_identifier_continuity([feed])
        assert findings == []

    def test_e016_overlap_detected(self):
        """CLK26 validTo=2026-03-25, CLM26 validFrom=2026-03-20 → E016, both names in message."""
        feed = _feed_with_identifiers(
            3,
            [
                {
                    "identifier": "CLK26",
                    "validFrom": "2026-01-01T00:00:00.000000000Z",
                    "validTo": "2026-03-25T17:00:00.000000000Z",
                },
                {
                    "identifier": "CLM26",
                    "validFrom": "2026-03-20T17:00:00.000000000Z",
                },
            ],
        )
        findings = check_identifier_continuity([feed])
        assert len(findings) == 1
        assert findings[0].rule_id == "E016"
        assert "CLK26" in findings[0].message
        assert "CLM26" in findings[0].message

    def test_e016_missing_validto_on_non_last(self):
        """CLK26 has no validTo but is followed by CLM26 → E016, 'CLK26' in msg."""
        feed = _feed_with_identifiers(
            4,
            [
                {
                    "identifier": "CLK26",
                    "validFrom": "2026-01-01T00:00:00.000000000Z",
                },
                {
                    "identifier": "CLM26",
                    "validFrom": "2026-03-20T17:00:00.000000000Z",
                },
            ],
        )
        findings = check_identifier_continuity([feed])
        assert len(findings) == 1
        assert findings[0].rule_id == "E016"
        assert "CLK26" in findings[0].message

    def test_e016_inactive_skipped(self):
        """INACTIVE state with overlap → no finding."""
        feed = _feed_with_identifiers(
            5,
            [
                {
                    "identifier": "CLK26",
                    "validFrom": "2026-01-01T00:00:00.000000000Z",
                    "validTo": "2026-03-25T17:00:00.000000000Z",
                },
                {
                    "identifier": "CLM26",
                    "validFrom": "2026-03-20T17:00:00.000000000Z",
                },
            ],
            state="INACTIVE",
        )
        findings = check_identifier_continuity([feed])
        assert findings == []

    def test_e016_no_benchmark_mapping_no_finding(self):
        """crypto feed with no benchmarkMapping → no finding."""
        feed = _make_feed(6, symbol="Crypto.BTC/USD", asset_type="crypto")
        findings = check_identifier_continuity([feed])
        assert findings == []

    def test_e016_last_identifier_no_validto_ok(self):
        """CLK26 has validTo, CLM26 has no validTo (last, open-ended) → no finding."""
        feed = _feed_with_identifiers(
            7,
            [
                {
                    "identifier": "CLK26",
                    "validFrom": "2026-01-01T00:00:00.000000000Z",
                    "validTo": "2026-03-20T17:00:00.000000000Z",
                },
                {
                    "identifier": "CLM26",
                    "validFrom": "2026-03-20T17:00:00.000000000Z",
                },
            ],
        )
        findings = check_identifier_continuity([feed])
        assert findings == []


class TestPerSessionSchedule:
    """Per-session refinement: schedules are compared bucket-by-bucket
    (group_key, session). A feed missing a session is not penalized for
    the omission; it simply doesn't appear in that bucket.
    Refinement addendum to spec 2026-04-28."""

    def test_e011_silent_when_session_sets_differ_but_per_session_agrees(self):
        """A REGULAR-only feed and a REGULAR+OVER_NIGHT feed that agree on
        their REGULAR schedule must NOT trip E011. Their session SETS
        differ but their REGULAR schedules match."""
        nyc_regular = {
            "marketSchedule": "America/New_York;0930-1600;",
            "session": "REGULAR",
        }
        nyc_overnight = {
            "marketSchedule": "America/New_York;2000-2400;",
            "session": "OVER_NIGHT",
        }
        feeds = [
            _make_feed(
                1,
                symbol="Equity.US.AAPL/USD",
                asset_type="equity",
                state="STABLE",
                schedules=[nyc_regular],
            ),
            _make_feed(
                2,
                symbol="Equity.US.MSFT/USD",
                asset_type="equity",
                state="STABLE",
                schedules=[nyc_regular, nyc_overnight],
            ),
            _make_feed(
                3,
                symbol="Equity.US.GOOG/USD",
                asset_type="equity",
                state="STABLE",
                schedules=[nyc_regular],
            ),
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E011"]
        assert len(errors) == 0

    def test_e011_fires_per_session_within_us(self):
        """Per-session drift on REGULAR (with extended sessions also present)
        must fire exactly one E011 tagged with the offending session."""
        nyc_regular = {
            "marketSchedule": "America/New_York;0930-1600;",
            "session": "REGULAR",
        }
        nyc_regular_wrong = {
            "marketSchedule": "America/New_York;0800-1500;",
            "session": "REGULAR",
        }
        nyc_pre = {
            "marketSchedule": "America/New_York;0400-0930;",
            "session": "PRE_MARKET",
        }
        feeds = [
            _make_feed(
                1,
                symbol="Equity.US.AAPL/USD",
                asset_type="equity",
                state="STABLE",
                schedules=[nyc_regular, nyc_pre],
            ),
            _make_feed(
                2,
                symbol="Equity.US.MSFT/USD",
                asset_type="equity",
                state="STABLE",
                schedules=[nyc_regular, nyc_pre],
            ),
            _make_feed(
                3,
                symbol="Equity.US.GOOG/USD",
                asset_type="equity",
                state="STABLE",
                schedules=[nyc_regular_wrong, nyc_pre],
            ),
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E011"]
        assert len(errors) == 1
        assert errors[0].feed_id == 3
        assert "REGULAR" in errors[0].message

    def test_e011_fires_on_extended_session_drift(self):
        """REGULAR matches across all 3 STABLE feeds, but one feed's
        OVER_NIGHT schedule disagrees with the other two's. E011 fires
        only on OVER_NIGHT, not on REGULAR."""
        nyc_regular = {
            "marketSchedule": "America/New_York;0930-1600;",
            "session": "REGULAR",
        }
        nyc_overnight_a = {
            "marketSchedule": "America/New_York;2000-2400;",
            "session": "OVER_NIGHT",
        }
        nyc_overnight_b = {
            "marketSchedule": "America/New_York;0000-0400;",
            "session": "OVER_NIGHT",
        }
        feeds = [
            _make_feed(
                1,
                symbol="Equity.US.AAPL/USD",
                asset_type="equity",
                state="STABLE",
                schedules=[nyc_regular, nyc_overnight_a],
            ),
            _make_feed(
                2,
                symbol="Equity.US.MSFT/USD",
                asset_type="equity",
                state="STABLE",
                schedules=[nyc_regular, nyc_overnight_a],
            ),
            _make_feed(
                3,
                symbol="Equity.US.GOOG/USD",
                asset_type="equity",
                state="STABLE",
                schedules=[nyc_regular, nyc_overnight_b],
            ),
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E011"]
        assert len(errors) == 1
        assert errors[0].feed_id == 3
        assert "OVER_NIGHT" in errors[0].message


class TestIndexSubNamespaceGrouping:
    """Index sub-namespace (Metal.Index, FX.Index, Crypto.Index, ...)
    gets its own group separate from the asset class's spot/regular feeds.
    Mirrors how Equity.Index is handled via equity_listing_prefix."""

    def test_e011_metal_index_separate_from_metal_spot(self):
        """Metal.Index.GOLD (always-open) and Metal.XAU (continuous) must
        land in different groups; their schedule difference is intentional."""
        always_open = [
            {
                "marketSchedule": "America/New_York;O,O,O,O,O,O,O;",
                "session": "REGULAR",
            }
        ]
        continuous = [
            {
                "marketSchedule": "America/New_York;0000-1700&1800-2400,0000-1700&1800-2400,0000-1700&1800-2400,0000-1700&1800-2400,0000-1700,C,1800-2400;",
                "session": "REGULAR",
            }
        ]
        feeds = [
            _make_feed(
                1,
                symbol="Metal.Index.GOLD/USD",
                asset_type="metal",
                state="STABLE",
                schedules=always_open,
            ),
            _make_feed(
                2,
                symbol="Metal.Index.SILVER/USD",
                asset_type="metal",
                state="STABLE",
                schedules=always_open,
            ),
            _make_feed(
                3,
                symbol="Metal.XAU/USD",
                asset_type="metal",
                state="STABLE",
                schedules=continuous,
            ),
            _make_feed(
                4,
                symbol="Metal.XAG/USD",
                asset_type="metal",
                state="STABLE",
                schedules=continuous,
            ),
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E011"]
        assert len(errors) == 0

    def test_e011_fx_index_separate_from_fx_spot(self):
        """FX.Index pairs must not group with FX spot pairs."""
        sched_index = [
            {
                "marketSchedule": "America/New_York;O,O,O,O,O,O,O;",
                "session": "REGULAR",
            }
        ]
        sched_spot = [
            {
                "marketSchedule": "America/New_York;O,O,O,O,0000-1700,C,1700-2400;",
                "session": "REGULAR",
            }
        ]
        feeds = [
            _make_feed(
                1,
                symbol="FX.Index.EUR/USD",
                asset_type="fx",
                state="STABLE",
                schedules=sched_index,
            ),
            _make_feed(
                2,
                symbol="FX.EUR/USD",
                asset_type="fx",
                state="STABLE",
                schedules=sched_spot,
            ),
            _make_feed(
                3,
                symbol="FX.GBP/USD",
                asset_type="fx",
                state="STABLE",
                schedules=sched_spot,
            ),
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E011"]
        assert len(errors) == 0

    def test_e011_intra_metal_index_drift_fires(self):
        """If Metal.Index feeds disagree with each other, E011 must fire
        on the minority — confirms the new sub-group is itself active."""
        sched_a = [
            {
                "marketSchedule": "America/New_York;O,O,O,O,O,O,O;",
                "session": "REGULAR",
            }
        ]
        sched_b = [
            {
                "marketSchedule": "America/New_York;0900-1600,0900-1600,0900-1600,0900-1600,0900-1600,C,C;",
                "session": "REGULAR",
            }
        ]
        feeds = [
            _make_feed(
                1,
                symbol="Metal.Index.GOLD/USD",
                asset_type="metal",
                state="STABLE",
                schedules=sched_a,
            ),
            _make_feed(
                2,
                symbol="Metal.Index.SILVER/USD",
                asset_type="metal",
                state="STABLE",
                schedules=sched_a,
            ),
            _make_feed(
                3,
                symbol="Metal.Index.PLATINUM/USD",
                asset_type="metal",
                state="STABLE",
                schedules=sched_b,
            ),
        ]
        findings = check_schedules(feeds)
        errors = [f for f in findings if f.rule_id == "E011"]
        assert len(errors) == 1
        assert errors[0].feed_id == 3


class TestCheckPublisherDuplicates:
    def test_no_duplicates_no_findings(self):
        publishers = [
            {"publisherId": 1, "name": "alpha", "keyType": "PRODUCTION"},
            {"publisherId": 2, "name": "beta", "keyType": "PRODUCTION"},
            {"publisherId": 3, "name": "gamma", "keyType": "PRODUCTION"},
        ]
        findings = check_publisher_duplicates(publishers)
        assert findings == []

    def test_e017_duplicate_publisher_id(self):
        publishers = [
            {"publisherId": 1, "name": "alpha", "keyType": "PRODUCTION"},
            {"publisherId": 1, "name": "beta", "keyType": "PRODUCTION"},
        ]
        findings = check_publisher_duplicates(publishers)
        e017 = [f for f in findings if f.rule_id == "E017"]
        assert len(e017) == 1
        assert "1" in e017[0].message
        assert e017[0].feed_id == 1

    def test_e018_duplicate_publisher_name(self):
        publishers = [
            {"publisherId": 1, "name": "alpha", "keyType": "PRODUCTION"},
            {"publisherId": 2, "name": "alpha", "keyType": "PRODUCTION"},
        ]
        findings = check_publisher_duplicates(publishers)
        e018 = [f for f in findings if f.rule_id == "E018"]
        assert len(e018) == 1
        assert "alpha" in e018[0].message
        assert e018[0].symbol == "alpha"

    def test_e017_and_e018_independent(self):
        # Two distinct dup classes: id 1 duplicated, name "shared" duplicated
        publishers = [
            {"publisherId": 1, "name": "alpha", "keyType": "PRODUCTION"},
            {"publisherId": 1, "name": "beta", "keyType": "PRODUCTION"},
            {"publisherId": 2, "name": "shared", "keyType": "PRODUCTION"},
            {"publisherId": 3, "name": "shared", "keyType": "PRODUCTION"},
        ]
        findings = check_publisher_duplicates(publishers)
        e017 = [f for f in findings if f.rule_id == "E017"]
        e018 = [f for f in findings if f.rule_id == "E018"]
        assert len(e017) == 1
        assert len(e018) == 1

    def test_skips_publishers_with_missing_id_or_name(self):
        # Missing fields should not crash, no findings produced
        publishers = [
            {"name": "alpha", "keyType": "PRODUCTION"},
            {"publisherId": 1, "keyType": "PRODUCTION"},
            {"keyType": "PRODUCTION"},
        ]
        findings = check_publisher_duplicates(publishers)
        assert findings == []

    def test_three_way_duplicate_id_emits_one_finding(self):
        publishers = [
            {"publisherId": 7, "name": "a", "keyType": "PRODUCTION"},
            {"publisherId": 7, "name": "b", "keyType": "PRODUCTION"},
            {"publisherId": 7, "name": "c", "keyType": "PRODUCTION"},
        ]
        findings = check_publisher_duplicates(publishers)
        e017 = [f for f in findings if f.rule_id == "E017"]
        assert len(e017) == 1
        assert "3" in e017[0].message  # mentions occurrence count

    def test_case_sensitive_name_comparison(self):
        # 'Alpha' and 'alpha' are distinct — not flagged
        publishers = [
            {"publisherId": 1, "name": "Alpha", "keyType": "PRODUCTION"},
            {"publisherId": 2, "name": "alpha", "keyType": "PRODUCTION"},
        ]
        findings = check_publisher_duplicates(publishers)
        assert findings == []

    def test_lint_config_orchestrator_runs_check(self):
        # Verify the new check is wired into lint_config
        config = {
            "feeds": [],
            "publishers": [
                {"publisherId": 1, "name": "alpha", "keyType": "PRODUCTION"},
                {"publisherId": 1, "name": "beta", "keyType": "PRODUCTION"},
            ],
        }
        findings = lint_config(config)
        e017 = [f for f in findings if f.rule_id == "E017"]
        assert len(e017) == 1


class TestLintConfigDiff:
    def test_suppresses_preexisting_finding(self):
        # Both before and after have feed 100 with E005 (STABLE, no publishers).
        feed = _make_feed(
            100,
            symbol="Equity.US.AAPL/USD",
            asset_type="equity",
            publisher_ids=[],
        )
        before = _make_config([feed])
        after = _make_config([dict(feed)])
        from lib.config_lint import lint_config_diff

        result = lint_config_diff(after, before)
        assert result == []

    def test_reports_newly_introduced_finding(self):
        clean = _make_feed(
            100,
            symbol="Equity.US.AAPL/USD",
            asset_type="equity",
            publisher_ids=[1, 2, 3],
        )
        broken = dict(clean)
        broken["allowedPublisherIds"] = []  # E005
        before = _make_config([clean])
        after = _make_config([broken])
        from lib.config_lint import lint_config_diff

        result = lint_config_diff(after, before)
        assert len(result) == 1
        assert result[0].rule_id == "E005"
        assert result[0].feed_id == 100

    def test_reports_finding_on_brand_new_feed(self):
        existing = _make_feed(
            100,
            symbol="Equity.US.AAPL/USD",
            asset_type="equity",
            publisher_ids=[1, 2, 3],
        )
        new_broken = _make_feed(
            999,
            symbol="Equity.US.NVDA/USD",
            asset_type="equity",
            publisher_ids=[],
        )
        before = _make_config([existing])
        after = _make_config([existing, new_broken])
        from lib.config_lint import lint_config_diff

        result = lint_config_diff(after, before)
        e005 = [f for f in result if f.rule_id == "E005"]
        assert len(e005) == 1
        assert e005[0].feed_id == 999

    def test_drops_findings_for_removed_feed(self):
        keep = _make_feed(
            100,
            symbol="Equity.US.AAPL/USD",
            asset_type="equity",
            publisher_ids=[1, 2, 3],
        )
        removed = _make_feed(
            200,
            symbol="Equity.US.MSFT/USD",
            asset_type="equity",
            publisher_ids=[],  # E005
        )
        before = _make_config([keep, removed])
        after = _make_config([keep])
        from lib.config_lint import lint_config_diff

        result = lint_config_diff(after, before)
        assert result == []

    def test_treats_symbol_rename_as_new(self):
        before_feed = _make_feed(
            100,
            symbol="Equity.US.OLD/USD",
            asset_type="equity",
            publisher_ids=[],  # E005
        )
        after_feed = _make_feed(
            100,
            symbol="Equity.US.NEW/USD",
            asset_type="equity",
            publisher_ids=[],  # E005
        )
        before = _make_config([before_feed])
        after = _make_config([after_feed])
        from lib.config_lint import lint_config_diff

        result = lint_config_diff(after, before)
        e005 = [
            f for f in result if f.rule_id == "E005" and f.symbol == "Equity.US.NEW/USD"
        ]
        assert len(e005) == 1
        assert e005[0].symbol == "Equity.US.NEW/USD"

    def test_handles_group_rule_cascade(self):
        # Three STABLE equity feeds with identical schedule. Adding a 4th
        # with a deviating schedule should fire E011 only on the new feed.
        sched_us = [
            {
                "marketSchedule": "America/New_York;O,O,O,O,O,O,O;",
                "session": "REGULAR",
            }
        ]
        sched_other = [
            {
                "marketSchedule": "America/Chicago;O,O,O,O,O,O,O;",
                "session": "REGULAR",
            }
        ]
        existing = [
            _make_feed(
                fid,
                symbol=f"Equity.US.SYM{fid}/USD",
                asset_type="equity",
                publisher_ids=[1, 2, 3],
                schedules=sched_us,
            )
            for fid in (1, 2, 3)
        ]
        deviant = _make_feed(
            4,
            symbol="Equity.US.SYM4/USD",
            asset_type="equity",
            publisher_ids=[1, 2, 3],
            schedules=sched_other,
        )
        before = _make_config(existing)
        after = _make_config(existing + [deviant])
        from lib.config_lint import lint_config_diff

        result = lint_config_diff(after, before)
        e011 = [f for f in result if f.rule_id == "E011"]
        assert len(e011) == 1
        assert e011[0].feed_id == 4

    def test_uses_consistent_now_for_e013(self):
        # COMING_SOON futures feed with all validTo in the past.
        # Same feed in before and after — E013 fires identically.
        feed = {
            "feedId": 500,
            "symbol": "Commodities.GCH5/USD",
            "state": "COMING_SOON",
            "kind": "PRICE",
            "minPublishers": 0,
            "metadata": {"asset_type": "commodity"},
            "marketSchedules": [
                {
                    "marketSchedule": "America/New_York;O,O,O,O,O,O,O;",
                    "session": "REGULAR",
                    "benchmarkMapping": {
                        "datascope": {
                            "identifiers": [
                                {
                                    "identifier": "GCH5",
                                    "validFrom": "2024-01-01T00:00:00Z",
                                    "validTo": "2025-03-27T00:00:00Z",
                                }
                            ]
                        }
                    },
                }
            ],
        }
        before = _make_config([feed])
        after = _make_config([dict(feed)])
        from lib.config_lint import lint_config_diff

        # Now is well after the validTo so E013 fires in both runs.
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        result = lint_config_diff(after, before, now=now)
        assert result == []

    def test_finding_key_is_rule_feed_symbol(self):
        from lib.config_lint import _finding_key

        a = LintFinding(
            rule_id="E001",
            severity="ERROR",
            message="msg-A",
            feed_id=10,
            symbol="X",
        )
        b = LintFinding(
            rule_id="E001",
            severity="ERROR",
            message="msg-B",
            feed_id=10,
            symbol="X",
        )
        assert _finding_key(a) == _finding_key(b)
        assert _finding_key(a) == ("E001", 10, "X")


class TestLintConfigDiffMultiplicity:
    """Counter-based suppression: rules that emit multiple findings with the
    same (rule_id, fid, sym) key (E003/E004/E010/E015) must surface
    *additional* occurrences as new in diff mode, not silently collapse
    them into the baseline.
    """

    def test_e003_session_level_added_to_existing_top_level_is_new(self):
        # Baseline: feed has top-level E003 (unknown publisher 999).
        # After: keeps top-level E003, adds session-level E003 with a
        # different unknown publisher (888). Set-based suppression would
        # hide the new session E003. Counter-based reveals it.
        from lib.config_lint import lint_config_diff

        publishers = [{"publisherId": 1, "name": "p1", "keyType": "PRODUCTION"}]
        before_feed = {
            "feedId": 1,
            "symbol": "Crypto.X/USD",
            "state": "STABLE",
            "kind": "PRICE",
            "metadata": {"asset_type": "crypto"},
            "allowedPublisherIds": [1, 999],
            "minPublishers": 1,
            "marketSchedules": [
                {"session": "REGULAR", "marketSchedule": "America/New_York;O;"}
            ],
        }
        after_feed = {
            "feedId": 1,
            "symbol": "Crypto.X/USD",
            "state": "STABLE",
            "kind": "PRICE",
            "metadata": {"asset_type": "crypto"},
            "allowedPublisherIds": [1, 999],
            "minPublishers": 1,
            "marketSchedules": [
                {
                    "session": "REGULAR",
                    "marketSchedule": "America/New_York;O;",
                    "allowedPublisherIds": [1, 999, 888],
                    "minPublishers": 1,
                }
            ],
        }
        before = {"feeds": [before_feed], "publishers": publishers}
        after = {"feeds": [after_feed], "publishers": publishers}
        new = lint_config_diff(after, before)
        e003 = [f for f in new if f.rule_id == "E003"]
        assert len(e003) == 1
        assert "888" in e003[0].message
        assert "session" in e003[0].message.lower()

    def test_e010_verbatim_dup_added_to_existing_dup_session_is_new(self):
        # Baseline: feed has duplicate session (two REGULAR with different
        # schedules). After: also adds a verbatim duplicate of one entry,
        # producing both flavours of E010 on the same feed. The verbatim
        # E010 must surface as new.
        from lib.config_lint import lint_config_diff

        before_feed = {
            "feedId": 1,
            "symbol": "Crypto.X/USD",
            "state": "STABLE",
            "kind": "PRICE",
            "metadata": {"asset_type": "crypto"},
            "allowedPublisherIds": [1],
            "minPublishers": 1,
            "marketSchedules": [
                {"session": "REGULAR", "marketSchedule": "A;O;"},
                {"session": "REGULAR", "marketSchedule": "B;O;"},
            ],
        }
        after_feed = {
            "feedId": 1,
            "symbol": "Crypto.X/USD",
            "state": "STABLE",
            "kind": "PRICE",
            "metadata": {"asset_type": "crypto"},
            "allowedPublisherIds": [1],
            "minPublishers": 1,
            "marketSchedules": [
                {"session": "REGULAR", "marketSchedule": "A;O;"},
                {"session": "REGULAR", "marketSchedule": "B;O;"},
                {"session": "REGULAR", "marketSchedule": "A;O;"},  # verbatim dup
            ],
        }
        before = {
            "feeds": [before_feed],
            "publishers": [{"publisherId": 1, "name": "p1", "keyType": "PRODUCTION"}],
        }
        after = {"feeds": [after_feed], "publishers": before["publishers"]}
        new = lint_config_diff(after, before)
        e010 = [f for f in new if f.rule_id == "E010"]
        # Baseline already had one E010 (duplicate session). After has two
        # (duplicate session + verbatim dup). Counter-based suppression
        # reports exactly one new E010 — the additional one.
        assert len(e010) == 1
        assert "verbatim" in e010[0].message.lower()

    def test_e015_additional_violation_on_same_feed_is_new(self):
        # Baseline: feed has one corporate action with a missing field
        # (one E015). After: same first action, plus a second action
        # entirely malformed (multiple E015s on the same feed). The
        # additional E015s must surface as new.
        from lib.config_lint import lint_config_diff

        publishers = [{"publisherId": 1, "name": "p1", "keyType": "PRODUCTION"}]
        before_feed = {
            "feedId": 1,
            "symbol": "Equity.US.AAPL/USD",
            "state": "STABLE",
            "kind": "PRICE",
            "metadata": {"asset_type": "equity"},
            "allowedPublisherIds": [1],
            "minPublishers": 1,
            "marketSchedules": [{"session": "REGULAR", "marketSchedule": "A;O;"}],
            "corporateActions": [
                {"eventType": "SPLIT"}  # missing required fields → E015s
            ],
        }
        after_feed = dict(before_feed)
        after_feed["corporateActions"] = [
            {"eventType": "SPLIT"},
            {"eventType": "SPLIT", "rejectionWindow": "bad-format"},
        ]
        before = {"feeds": [before_feed], "publishers": publishers}
        after = {"feeds": [after_feed], "publishers": publishers}
        new = lint_config_diff(after, before)
        e015 = [f for f in new if f.rule_id == "E015"]
        # The first action's E015s match baseline 1:1 and are suppressed.
        # The second action is entirely new — its E015s must surface.
        assert len(e015) >= 1
        assert any("[1]" in f.message for f in e015)

    def test_persistent_dup_findings_still_suppressed(self):
        # Sanity: when the same set of multiple findings exists in both
        # baseline and after, all should be suppressed (no false
        # positives from the Counter approach).
        from lib.config_lint import lint_config_diff

        feed = {
            "feedId": 1,
            "symbol": "Crypto.X/USD",
            "state": "STABLE",
            "kind": "PRICE",
            "metadata": {"asset_type": "crypto"},
            "allowedPublisherIds": [1, 999],
            "minPublishers": 1,
            "marketSchedules": [
                {
                    "session": "REGULAR",
                    "marketSchedule": "A;O;",
                    "allowedPublisherIds": [1, 999, 888],
                    "minPublishers": 1,
                }
            ],
        }
        publishers = [{"publisherId": 1, "name": "p1", "keyType": "PRODUCTION"}]
        config = {"feeds": [feed], "publishers": publishers}
        # Same config on both sides
        new = lint_config_diff(config, config)
        assert new == []


class TestLintConfigDiffWithCount:
    """The accurate suppressed-count is the number of after-findings actually
    filtered out, not the total baseline finding count.
    """

    def test_count_reflects_suppressions_not_total_baseline(self):
        from lib.config_lint import lint_config_diff_with_count

        publishers = [{"publisherId": 1, "name": "p1", "keyType": "PRODUCTION"}]
        # Baseline: 3 distinct issues across 3 feeds.
        baseline_feeds = [
            # Feed 1 — E007 (no kind)
            {
                "feedId": 1,
                "symbol": "A/B",
                "state": "STABLE",
                "metadata": {"asset_type": "crypto"},
                "allowedPublisherIds": [1],
                "minPublishers": 0,
            },
            # Feed 2 — E005 (STABLE, no publishers)
            {
                "feedId": 2,
                "symbol": "C/D",
                "state": "STABLE",
                "kind": "PRICE",
                "metadata": {"asset_type": "crypto"},
                "allowedPublisherIds": [],
                "minPublishers": 0,
            },
            # Feed 3 — E003 (unknown publisher)
            {
                "feedId": 3,
                "symbol": "E/F",
                "state": "STABLE",
                "kind": "PRICE",
                "metadata": {"asset_type": "crypto"},
                "allowedPublisherIds": [1, 999],
                "minPublishers": 0,
            },
        ]
        # After: feed 2 is fixed. Feeds 1 and 3 unchanged.
        after_feeds = [
            baseline_feeds[0],
            {
                "feedId": 2,
                "symbol": "C/D",
                "state": "STABLE",
                "kind": "PRICE",
                "metadata": {"asset_type": "crypto"},
                "allowedPublisherIds": [1],
                "minPublishers": 0,
            },
            baseline_feeds[2],
        ]
        before = {"feeds": baseline_feeds, "publishers": publishers}
        after = {"feeds": after_feeds, "publishers": publishers}

        new_findings, suppressed = lint_config_diff_with_count(after, before)
        # Two findings were carried over (feeds 1 & 3); these are the
        # ones actually filtered out. The third baseline finding (E005
        # on feed 2) was *fixed*, not suppressed.
        assert new_findings == []
        assert suppressed == 2

    def test_count_is_zero_when_nothing_to_suppress(self):
        from lib.config_lint import lint_config_diff_with_count

        clean = {
            "feedId": 1,
            "symbol": "Crypto.X/USD",
            "state": "STABLE",
            "kind": "PRICE",
            "metadata": {"asset_type": "crypto"},
            "allowedPublisherIds": [1, 2, 3],
            "minPublishers": 1,
            "marketSchedules": [{"session": "REGULAR", "marketSchedule": "A;O;"}],
        }
        config = {
            "feeds": [clean],
            "publishers": [
                {"publisherId": i, "name": f"p{i}", "keyType": "PRODUCTION"}
                for i in (1, 2, 3)
            ],
        }
        new_findings, suppressed = lint_config_diff_with_count(config, config)
        assert new_findings == []
        assert suppressed == 0


class TestParseIso:
    """_parse_iso must always return tz-aware datetimes (or None).

    Naive inputs are coerced to UTC so downstream comparisons against
    tz-aware now() do not raise TypeError.
    """

    def _parse(self, value):
        from lib.config_lint import _parse_iso

        return _parse_iso(value)

    def test_z_suffix_is_aware(self):
        dt = self._parse("2026-01-01T00:00:00Z")
        assert dt is not None
        assert dt.tzinfo is not None
        assert dt.utcoffset().total_seconds() == 0

    def test_explicit_utc_offset_is_aware(self):
        dt = self._parse("2026-01-01T00:00:00+00:00")
        assert dt is not None
        assert dt.tzinfo is not None

    def test_non_utc_offset_preserved(self):
        dt = self._parse("2026-01-01T00:00:00+05:30")
        assert dt is not None
        assert dt.utcoffset().total_seconds() == 5.5 * 3600

    def test_z_with_fractional_seconds_is_aware(self):
        dt = self._parse("2026-01-01T00:00:00.123456Z")
        assert dt is not None
        assert dt.tzinfo is not None
        assert dt.microsecond == 123456

    def test_nanosecond_precision_truncated_to_microseconds(self):
        dt = self._parse("2026-01-01T00:00:00.123456789Z")
        assert dt is not None
        assert dt.tzinfo is not None
        assert dt.microsecond == 123456

    def test_naive_input_coerced_to_utc(self):
        """Bare timestamp (no tz indicator) → assumed UTC, tz-aware result."""
        dt = self._parse("2026-01-01T00:00:00")
        assert dt is not None
        assert dt.tzinfo is not None
        assert dt.utcoffset().total_seconds() == 0
        assert dt == datetime(2026, 1, 1, tzinfo=timezone.utc)

    def test_naive_input_with_fractional_coerced_to_utc(self):
        dt = self._parse("2026-01-01T00:00:00.123")
        assert dt is not None
        assert dt.tzinfo is not None
        assert dt.microsecond == 123000

    def test_empty_string_returns_none(self):
        assert self._parse("") is None

    def test_none_returns_none(self):
        assert self._parse(None) is None

    def test_invalid_string_returns_none(self):
        assert self._parse("not-a-date") is None

    def test_e013_does_not_crash_on_naive_validto(self):
        """Regression: naive validTo previously crashed `vt < now` comparison."""
        feed = _futures_feed_with_validto(
            1, "Commodities.CLK6/USD", "2026-01-01T00:00:00"
        )
        # Should produce E013 (validTo is in the past relative to _NOW)
        # rather than raising TypeError.
        findings = check_expired_coming_soon_futures([feed], _NOW)
        e013 = [f for f in findings if f.rule_id == "E013"]
        assert len(e013) == 1
        assert e013[0].feed_id == 1

    def test_e016_does_not_crash_on_mixed_naive_and_aware(self):
        """Regression: naive validFrom previously crashed list.sort() against aware fallback."""
        feed = _feed_with_identifiers(
            1,
            [
                {
                    "identifier": "A",
                    "validFrom": "2026-01-01T00:00:00",
                    "validTo": "2026-06-01T00:00:00Z",
                },
                {
                    "identifier": "B",
                    "validFrom": "2026-06-01T00:00:00Z",
                    "validTo": "2026-12-01T00:00:00",
                },
            ],
        )
        # Should sort cleanly and produce no E016 (back-to-back identifiers).
        findings = check_identifier_continuity([feed])
        assert findings == []


class TestMinPublishersNull:
    """Defensive: `minPublishers: null` (JSON) must not crash the linter.

    `feed.get("minPublishers", 0)` returns None when the key is present
    with value null; the default only applies when the key is absent.
    The fix coerces None to 0 so int comparisons do not raise TypeError.
    """

    _PUBLISHERS = [
        {"publisherId": 1, "name": "pub1", "keyType": "PRODUCTION"},
        {"publisherId": 2, "name": "pub2", "keyType": "PRODUCTION"},
        {"publisherId": 3, "name": "pub3", "keyType": "PRODUCTION"},
    ]

    def test_top_level_null_does_not_crash(self):
        feed = _make_feed(
            1,
            symbol="Crypto.BTC/USD",
            state="STABLE",
            asset_type="crypto",
            min_publishers=None,
            publisher_ids=[1, 2, 3],
        )
        # No crash; should not produce E004 (null treated as 0).
        findings = check_publishers([feed], self._PUBLISHERS)
        assert all(f.rule_id != "E004" for f in findings)

    def test_top_level_null_with_no_publishers_does_not_crash(self):
        """Edge case: minPublishers null AND zero publishers → still no crash, no E004."""
        feed = _make_feed(
            1,
            symbol="Crypto.BTC/USD",
            state="STABLE",
            asset_type="crypto",
            min_publishers=None,
            publisher_ids=[],
        )
        findings = check_publishers([feed], self._PUBLISHERS)
        # E005 is the right rule for empty publisher list, not E004.
        assert all(f.rule_id != "E004" for f in findings)
        assert any(f.rule_id == "E005" for f in findings)

    def test_session_level_null_does_not_crash(self):
        """Session-level null is already guarded by `is not None`; assert no regression."""
        feed = _make_feed(
            1,
            symbol="Crypto.BTC/USD",
            state="STABLE",
            asset_type="crypto",
            min_publishers=1,
            publisher_ids=[1, 2, 3],
            schedules=[
                {
                    "marketSchedule": "America/New_York;O,O,O,O,O,O,O;",
                    "session": "REGULAR",
                    "minPublishers": None,
                    "allowedPublisherIds": [1, 2],
                }
            ],
        )
        findings = check_publishers([feed], self._PUBLISHERS)
        # No crash; the session E004/W005 block is skipped when session_min is None.
        e004 = [f for f in findings if f.rule_id == "E004"]
        assert e004 == []


class TestExchangeOrchestratorIntegration:
    """Verifies that lint_config wires through to check_exchanges."""

    def test_e019_appears_in_lint_config_output(self):
        from lib.config_lint import lint_config

        config = {
            "feeds": [
                {
                    "feedId": 1,
                    "symbol": "X",
                    "state": "STABLE",
                    "kind": "PRICE",
                    "metadata": {"asset_type": "equity"},
                    "exchangeId": 99999,  # dangling
                    "allowedPublisherIds": [1],
                    "minPublishers": 1,
                    "marketSchedules": [
                        {"session": "REGULAR", "marketSchedule": "UTC;O,O,O,O,O,O,O;"},
                    ],
                }
            ],
            "publishers": [{"publisherId": 1, "name": "p1", "keyType": "PRODUCTION"}],
            "exchanges": [
                {
                    "exchangeId": 1,
                    "name": "X",
                    "sessions": [
                        {"session": "REGULAR", "marketSchedule": "UTC;O,O,O,O,O,O,O;"}
                    ],
                },
            ],
        }
        findings = lint_config(config)
        assert any(f.rule_id == "E019" for f in findings)

    def test_no_exchanges_key_does_not_break(self):
        from lib.config_lint import lint_config

        config = {
            "feeds": [],
            "publishers": [],
            # no exchanges key
        }
        findings = lint_config(config)
        # Just confirm no crash; no E0xx exchange rule should fire on empty
        assert all(
            not f.rule_id.startswith("E019")
            and not f.rule_id.startswith("E020")
            and not f.rule_id.startswith("E021")
            for f in findings
        )
