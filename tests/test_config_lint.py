from lib.config_lint import LintFinding, lint_config, check_duplicates, check_schema


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


class TestLintConfigOrchestrator:
    def test_clean_config(self):
        config = _make_config(
            [
                _make_feed(1, symbol="Crypto.BTC/USD", publisher_ids=[1, 2, 3]),
                _make_feed(2, symbol="Crypto.ETH/USD", publisher_ids=[1, 2, 3]),
            ]
        )
        findings = lint_config(config)
        errors = [f for f in findings if f.severity == "ERROR"]
        assert len(errors) == 0

    def test_empty_feeds(self):
        config = _make_config([])
        findings = lint_config(config)
        assert findings == []
