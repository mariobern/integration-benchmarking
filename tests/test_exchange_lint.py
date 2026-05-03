"""Tests for lib/exchange_lint.py."""

import pytest

from lib.exchange_lint import check_exchanges


class TestEntryPoint:
    def test_empty_inputs(self):
        assert check_exchanges([], []) == []

    def test_no_exchanges_no_exchange_id(self):
        feeds = [{"feedId": 1, "symbol": "X", "marketSchedules": []}]
        assert check_exchanges(feeds, []) == []

    def test_non_list_exchanges_coerced(self):
        # Defensive coercion per spec
        feeds = [{"feedId": 1, "symbol": "X", "marketSchedules": []}]
        # Pass a dict instead of a list — should be treated as []
        assert check_exchanges(feeds, {"oops": "wrong type"}) == []


class TestBuildIndexFirstWriteWins:
    """Regression test for the first-write-wins invariant in _build_index.

    Per spec, the first entry encountered for a duplicate exchangeId is
    canonical. Downstream rules (E019/E020/W010/W011) rely on this so
    diff-mode behavior is deterministic.
    """

    def test_first_entry_canonical_on_duplicate_id(self):
        from lib.exchange_lint import _build_index

        first = {"exchangeId": 1, "name": "FIRST", "sessions": []}
        second = {"exchangeId": 1, "name": "SECOND", "sessions": []}
        by_id, _ = _build_index([first, second])
        assert by_id[1]["name"] == "FIRST"


class TestE024:
    _SESSIONS_OK = [{"session": "REGULAR", "marketSchedule": "UTC;O,O,O,O,O,O,O;"}]

    def test_well_formed_no_finding(self):
        ex = [{"exchangeId": 1, "name": "X", "sessions": self._SESSIONS_OK}]
        findings = check_exchanges([], ex)
        assert [f for f in findings if f.rule_id == "E024"] == []

    def test_missing_exchange_id(self):
        ex = [{"name": "X", "sessions": self._SESSIONS_OK}]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E024"]
        assert len(findings) == 1
        assert "missing required field 'exchangeId'" in findings[0].message
        assert findings[0].feed_id is None
        assert findings[0].symbol is None

    def test_missing_name(self):
        ex = [{"exchangeId": 1, "sessions": self._SESSIONS_OK}]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E024"]
        assert len(findings) == 1
        assert "missing required field 'name'" in findings[0].message

    def test_empty_name_string(self):
        ex = [{"exchangeId": 1, "name": "", "sessions": self._SESSIONS_OK}]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E024"]
        assert len(findings) == 1
        assert "missing required field 'name'" in findings[0].message

    def test_missing_sessions(self):
        ex = [{"exchangeId": 1, "name": "X"}]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E024"]
        assert len(findings) == 1
        assert "empty sessions list" in findings[0].message

    @pytest.mark.parametrize("sessions", [[], None, "not a list"])
    def test_empty_or_invalid_sessions(self, sessions):
        ex = [{"exchangeId": 1, "name": "X", "sessions": sessions}]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E024"]
        assert len(findings) == 1
        assert "empty sessions list" in findings[0].message

    def test_missing_two_fields_emits_two_findings(self):
        ex = [{"sessions": self._SESSIONS_OK}]  # missing exchangeId AND name
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E024"]
        assert len(findings) == 2
        msgs = sorted(f.message for f in findings)
        assert "exchangeId" in msgs[0]
        assert "name" in msgs[1]

    def test_index_is_zero_based(self):
        ex = [
            {"exchangeId": 1, "name": "OK", "sessions": self._SESSIONS_OK},
            {"name": "BROKEN", "sessions": self._SESSIONS_OK},  # index 1
        ]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E024"]
        assert len(findings) == 1
        assert "at index 1" in findings[0].message


class TestE023:
    _OK = {"sessions": [{"session": "REGULAR", "marketSchedule": "UTC;O,O,O,O,O,O,O;"}]}

    def test_distinct_ids_no_finding(self):
        ex = [
            {"exchangeId": 1, "name": "A", **self._OK},
            {"exchangeId": 2, "name": "B", **self._OK},
        ]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E023"]
        assert findings == []

    def test_duplicate_id_pair(self):
        ex = [
            {"exchangeId": 1, "name": "A", **self._OK},
            {"exchangeId": 1, "name": "B", **self._OK},
        ]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E023"]
        assert len(findings) == 1
        assert "duplicate exchangeId 1" in findings[0].message
        assert "appears on 2 entries" in findings[0].message

    def test_duplicate_id_three_way_emits_one_finding(self):
        ex = [
            {"exchangeId": 7, "name": "A", **self._OK},
            {"exchangeId": 7, "name": "B", **self._OK},
            {"exchangeId": 7, "name": "C", **self._OK},
        ]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E023"]
        assert len(findings) == 1
        assert "appears on 3 entries" in findings[0].message

    def test_malformed_entries_excluded(self):
        # Both entries missing 'name' — they're not well-formed,
        # E024 reports them, E023 ignores them.
        ex = [
            {"exchangeId": 1, **self._OK},
            {"exchangeId": 1, **self._OK},
        ]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E023"]
        assert findings == []


class TestE021:
    _SESS = [{"session": "REGULAR", "marketSchedule": "UTC;O,O,O,O,O,O,O;"}]

    def test_distinct_tuples_no_finding(self):
        ex = [
            {
                "exchangeId": 1,
                "name": "NASDAQ",
                "assetClass": "EXCHANGE_ASSET_CLASS_EQUITY",
                "assetSubclass": "EXCHANGE_ASSET_SUBCLASS_COMMON_STOCK",
                "assetSector": "EXCHANGE_ASSET_SECTOR_TECHNOLOGY",
                "sessions": self._SESS,
            },
            {
                "exchangeId": 2,
                "name": "NASDAQ",
                "assetClass": "EXCHANGE_ASSET_CLASS_EQUITY",
                "assetSubclass": "EXCHANGE_ASSET_SUBCLASS_ETF",
                "assetSector": "EXCHANGE_ASSET_SECTOR_BROAD_MARKET",
                "sessions": self._SESS,
            },
        ]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E021"]
        assert findings == []

    def test_duplicate_tuple_distinct_ids(self):
        ex = [
            {
                "exchangeId": 1,
                "name": "NASDAQ",
                "assetClass": "EXCHANGE_ASSET_CLASS_EQUITY",
                "assetSubclass": "EXCHANGE_ASSET_SUBCLASS_COMMON_STOCK",
                "assetSector": "EXCHANGE_ASSET_SECTOR_TECHNOLOGY",
                "sessions": self._SESS,
            },
            {
                "exchangeId": 2,
                "name": "NASDAQ",
                "assetClass": "EXCHANGE_ASSET_CLASS_EQUITY",
                "assetSubclass": "EXCHANGE_ASSET_SUBCLASS_COMMON_STOCK",
                "assetSector": "EXCHANGE_ASSET_SECTOR_TECHNOLOGY",
                "sessions": self._SESS,
            },
        ]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E021"]
        assert len(findings) == 1
        assert "NASDAQ" in findings[0].message
        assert "[1, 2]" in findings[0].message

    def test_three_way_duplicate_one_finding(self):
        common = {
            "name": "X",
            "assetClass": "EXCHANGE_ASSET_CLASS_UNSPECIFIED",
            "assetSubclass": "EXCHANGE_ASSET_SUBCLASS_UNSPECIFIED",
            "assetSector": "EXCHANGE_ASSET_SECTOR_UNSPECIFIED",
            "sessions": self._SESS,
        }
        ex = [
            {"exchangeId": 1, **common},
            {"exchangeId": 2, **common},
            {"exchangeId": 3, **common},
        ]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E021"]
        assert len(findings) == 1
        assert "[1, 2, 3]" in findings[0].message

    def test_missing_classification_treated_as_unspecified(self):
        ex = [
            {"exchangeId": 1, "name": "X", "sessions": self._SESS},
            {
                "exchangeId": 2,
                "name": "X",
                "assetClass": "EXCHANGE_ASSET_CLASS_UNSPECIFIED",
                "assetSubclass": "EXCHANGE_ASSET_SUBCLASS_UNSPECIFIED",
                "assetSector": "EXCHANGE_ASSET_SECTOR_UNSPECIFIED",
                "sessions": self._SESS,
            },
        ]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E021"]
        assert len(findings) == 1

    def test_same_id_same_tuple_only_e023_not_e021(self):
        common = {
            "name": "X",
            "sessions": self._SESS,
        }
        ex = [
            {"exchangeId": 1, **common},
            {"exchangeId": 1, **common},
        ]
        all_findings = check_exchanges([], ex)
        assert any(f.rule_id == "E023" for f in all_findings)
        assert not any(f.rule_id == "E021" for f in all_findings)

    def test_malformed_entries_excluded(self):
        ex = [
            {"name": "X", "sessions": self._SESS},  # missing exchangeId
            {"name": "X", "sessions": self._SESS},
        ]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E021"]
        assert findings == []


class TestE025:
    _SESS = [{"session": "REGULAR", "marketSchedule": "UTC;O,O,O,O,O,O,O;"}]

    def test_known_values_no_finding(self):
        ex = [
            {
                "exchangeId": 1,
                "name": "X",
                "assetClass": "EXCHANGE_ASSET_CLASS_EQUITY",
                "assetSubclass": "EXCHANGE_ASSET_SUBCLASS_COMMON_STOCK",
                "assetSector": "EXCHANGE_ASSET_SECTOR_TECHNOLOGY",
                "sessions": self._SESS,
            }
        ]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E025"]
        assert findings == []

    def test_unspecified_no_finding(self):
        ex = [
            {
                "exchangeId": 1,
                "name": "X",
                "assetClass": "EXCHANGE_ASSET_CLASS_UNSPECIFIED",
                "assetSubclass": "EXCHANGE_ASSET_SUBCLASS_UNSPECIFIED",
                "assetSector": "EXCHANGE_ASSET_SECTOR_UNSPECIFIED",
                "sessions": self._SESS,
            }
        ]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E025"]
        assert findings == []

    def test_missing_classification_no_finding(self):
        # Missing -> default UNSPECIFIED; not flagged
        ex = [{"exchangeId": 1, "name": "X", "sessions": self._SESS}]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E025"]
        assert findings == []

    def test_unknown_class(self):
        ex = [
            {
                "exchangeId": 1,
                "name": "X",
                "assetClass": "EXCHANGE_ASSET_CLASS_EQUTIY",  # typo
                "sessions": self._SESS,
            }
        ]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E025"]
        assert len(findings) == 1
        assert "assetClass" in findings[0].message
        assert "EQUTIY" in findings[0].message

    def test_unknown_subclass(self):
        ex = [
            {
                "exchangeId": 1,
                "name": "X",
                "assetSubclass": "EXCHANGE_ASSET_SUBCLASS_BANANA",
                "sessions": self._SESS,
            }
        ]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E025"]
        assert len(findings) == 1
        assert "assetSubclass" in findings[0].message

    def test_unknown_sector(self):
        ex = [
            {
                "exchangeId": 1,
                "name": "X",
                "assetSector": "EXCHANGE_ASSET_SECTOR_NONSENSE",
                "sessions": self._SESS,
            }
        ]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E025"]
        assert len(findings) == 1
        assert "assetSector" in findings[0].message

    def test_three_unknown_fields_emits_three(self):
        ex = [
            {
                "exchangeId": 1,
                "name": "X",
                "assetClass": "WRONG1",
                "assetSubclass": "WRONG2",
                "assetSector": "WRONG3",
                "sessions": self._SESS,
            }
        ]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E025"]
        assert len(findings) == 3

    def test_malformed_entries_excluded(self):
        ex = [{"name": "X", "assetClass": "WRONG", "sessions": self._SESS}]  # no id
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E025"]
        assert findings == []
