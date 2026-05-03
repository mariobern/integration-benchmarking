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

    def test_non_dict_entry_fires_e024(self):
        # exchanges = ["NASDAQ"] is an authoring error — should not be silent.
        ex = ["NASDAQ", {"exchangeId": 1, "name": "X", "sessions": self._SESSIONS_OK}]
        findings = [f for f in check_exchanges([], ex) if f.rule_id == "E024"]
        # The string at index 0 should fire E024; the well-formed dict at index 1 should not.
        assert len(findings) == 1
        assert "at index 0" in findings[0].message
        assert "is not an object" in findings[0].message
        assert "got str" in findings[0].message


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


class TestE019:
    _OK = {"sessions": [{"session": "REGULAR", "marketSchedule": "UTC;O,O,O,O,O,O,O;"}]}

    def test_resolvable_no_finding(self):
        ex = [{"exchangeId": 1, "name": "X", **self._OK}]
        feeds = [{"feedId": 100, "symbol": "S", "exchangeId": 1, "marketSchedules": []}]
        findings = [f for f in check_exchanges(feeds, ex) if f.rule_id == "E019"]
        assert findings == []

    def test_no_exchange_id_no_finding(self):
        ex = []
        feeds = [{"feedId": 100, "symbol": "S", "marketSchedules": []}]
        findings = [f for f in check_exchanges(feeds, ex) if f.rule_id == "E019"]
        assert findings == []

    def test_dangling_int_id(self):
        ex = [{"exchangeId": 1, "name": "X", **self._OK}]
        feeds = [
            {"feedId": 100, "symbol": "S", "exchangeId": 99999, "marketSchedules": []}
        ]
        findings = [f for f in check_exchanges(feeds, ex) if f.rule_id == "E019"]
        assert len(findings) == 1
        assert findings[0].feed_id == 100
        assert findings[0].symbol == "S"
        assert "99999" in findings[0].message

    def test_dangling_string_id_distinct_from_int(self):
        ex = [{"exchangeId": 1, "name": "X", **self._OK}]
        feeds = [
            {"feedId": 100, "symbol": "S", "exchangeId": "1", "marketSchedules": []}
        ]
        findings = [f for f in check_exchanges(feeds, ex) if f.rule_id == "E019"]
        assert len(findings) == 1
        assert "'1'" in findings[0].message  # repr() of string

    def test_unhashable_id_does_not_raise(self):
        ex = [{"exchangeId": 1, "name": "X", **self._OK}]
        feeds = [
            {"feedId": 100, "symbol": "S", "exchangeId": [1, 2], "marketSchedules": []}
        ]
        findings = [f for f in check_exchanges(feeds, ex) if f.rule_id == "E019"]
        assert len(findings) == 1
        assert "[1, 2]" in findings[0].message

    def test_no_exchanges_array_with_exchange_id_set(self):
        feeds = [{"feedId": 100, "symbol": "S", "exchangeId": 1, "marketSchedules": []}]
        findings = [f for f in check_exchanges(feeds, []) if f.rule_id == "E019"]
        assert len(findings) == 1


class TestE020:
    _EX = [
        {
            "exchangeId": 1,
            "name": "X",
            "sessions": [
                {"session": "REGULAR", "marketSchedule": "UTC;O,O,O,O,O,O,O;"}
            ],
        }
    ]

    def test_inline_schedule_no_finding(self):
        feeds = [
            {
                "feedId": 100,
                "symbol": "S",
                "marketSchedules": [
                    {"session": "REGULAR", "marketSchedule": "UTC;O,O,O,O,O,O,O;"},
                ],
            }
        ]
        findings = [f for f in check_exchanges(feeds, []) if f.rule_id == "E020"]
        assert findings == []

    def test_inheritance_no_finding(self):
        feeds = [
            {
                "feedId": 100,
                "symbol": "S",
                "exchangeId": 1,
                "marketSchedules": [
                    {"session": "REGULAR"},  # no marketSchedule, inherits
                ],
            }
        ]
        findings = [f for f in check_exchanges(feeds, self._EX) if f.rule_id == "E020"]
        assert findings == []

    def test_case_1_no_exchange_id(self):
        feeds = [
            {
                "feedId": 100,
                "symbol": "S",
                "marketSchedules": [
                    {"session": "REGULAR"},  # no marketSchedule, no exchangeId
                ],
            }
        ]
        findings = [f for f in check_exchanges(feeds, []) if f.rule_id == "E020"]
        assert len(findings) == 1
        assert "feed has no exchangeId" in findings[0].message
        assert findings[0].feed_id == 100

    def test_case_1_empty_string_market_schedule(self):
        feeds = [
            {
                "feedId": 100,
                "symbol": "S",
                "marketSchedules": [
                    {"session": "REGULAR", "marketSchedule": ""},
                ],
            }
        ]
        findings = [f for f in check_exchanges(feeds, []) if f.rule_id == "E020"]
        assert len(findings) == 1

    def test_case_2_exchange_missing_session(self):
        # Exchange defines REGULAR; feed wants PRE_MARKET
        feeds = [
            {
                "feedId": 100,
                "symbol": "S",
                "exchangeId": 1,
                "marketSchedules": [
                    {"session": "PRE_MARKET"},
                ],
            }
        ]
        findings = [f for f in check_exchanges(feeds, self._EX) if f.rule_id == "E020"]
        assert len(findings) == 1
        assert "PRE_MARKET" in findings[0].message
        assert "exchange 1" in findings[0].message

    def test_e019_suppresses_e020(self):
        feeds = [
            {
                "feedId": 100,
                "symbol": "S",
                "exchangeId": 99999,
                "marketSchedules": [
                    {
                        "session": "REGULAR"
                    },  # would fire E020 case 2 if E019 didn't suppress
                ],
            }
        ]
        all_findings = check_exchanges(feeds, self._EX)
        assert any(f.rule_id == "E019" for f in all_findings)
        assert not any(f.rule_id == "E020" for f in all_findings)


class TestW010:
    _EX = [
        {
            "exchangeId": 1,
            "name": "X",
            "sessions": [
                {"session": "REGULAR", "marketSchedule": "UTC;O,O,O,O,O,O,O;"}
            ],
        }
    ]

    def test_no_exchange_id_no_finding(self):
        feeds = [
            {
                "feedId": 100,
                "symbol": "S",
                "marketSchedules": [
                    {"session": "REGULAR", "marketSchedule": "UTC;C,C,C,C,C,C,C;"},
                ],
            }
        ]
        findings = [f for f in check_exchanges(feeds, []) if f.rule_id == "W010"]
        assert findings == []

    def test_inline_no_inherit_no_finding(self):
        # exchange has no PRE_MARKET, feed has inline PRE_MARKET — nothing to shadow
        feeds = [
            {
                "feedId": 100,
                "symbol": "S",
                "exchangeId": 1,
                "marketSchedules": [
                    {"session": "PRE_MARKET", "marketSchedule": "UTC;O,O,O,O,O,O,O;"},
                ],
            }
        ]
        findings = [f for f in check_exchanges(feeds, self._EX) if f.rule_id == "W010"]
        assert findings == []

    def test_shadow_fires(self):
        # Exchange defines REGULAR + PRE_MARKET; feed overrides REGULAR inline
        # and inherits PRE_MARKET — not all inline, so W011 doesn't suppress.
        ex = [
            {
                "exchangeId": 1,
                "name": "X",
                "sessions": [
                    {"session": "REGULAR", "marketSchedule": "UTC;O,O,O,O,O,O,O;"},
                    {"session": "PRE_MARKET", "marketSchedule": "UTC;O,O,O,O,O,O,O;"},
                ],
            }
        ]
        feeds = [
            {
                "feedId": 100,
                "symbol": "S",
                "exchangeId": 1,
                "marketSchedules": [
                    {"session": "REGULAR", "marketSchedule": "UTC;C,C,C,C,C,C,C;"},
                    {"session": "PRE_MARKET"},  # inherits — not all inline
                ],
            }
        ]
        findings = [f for f in check_exchanges(feeds, ex) if f.rule_id == "W010"]
        assert len(findings) == 1
        assert findings[0].severity == "WARNING"
        assert "REGULAR" in findings[0].message
        assert "exchangeId 1" in findings[0].message

    def test_e019_suppresses_w010(self):
        feeds = [
            {
                "feedId": 100,
                "symbol": "S",
                "exchangeId": 99999,
                "marketSchedules": [
                    {"session": "REGULAR", "marketSchedule": "UTC;C,C,C,C,C,C,C;"},
                ],
            }
        ]
        findings = [f for f in check_exchanges(feeds, self._EX) if f.rule_id == "W010"]
        assert findings == []


class TestW011:
    _EX = [
        {
            "exchangeId": 1,
            "name": "X",
            "sessions": [
                {"session": "REGULAR", "marketSchedule": "UTC;O,O,O,O,O,O,O;"},
                {"session": "PRE_MARKET", "marketSchedule": "UTC;O,O,O,O,O,O,O;"},
            ],
        }
    ]

    def test_partial_inherit_no_finding(self):
        feeds = [
            {
                "feedId": 100,
                "symbol": "S",
                "exchangeId": 1,
                "marketSchedules": [
                    {"session": "REGULAR", "marketSchedule": "UTC;C,C,C,C,C,C,C;"},
                    {"session": "PRE_MARKET"},  # this one inherits
                ],
            }
        ]
        findings = [f for f in check_exchanges(feeds, self._EX) if f.rule_id == "W011"]
        assert findings == []

    def test_all_inline_fires(self):
        feeds = [
            {
                "feedId": 100,
                "symbol": "S",
                "exchangeId": 1,
                "marketSchedules": [
                    {"session": "REGULAR", "marketSchedule": "UTC;C,C,C,C,C,C,C;"},
                    {"session": "PRE_MARKET", "marketSchedule": "UTC;O,O,O,O,O,O,O;"},
                ],
            }
        ]
        findings = [f for f in check_exchanges(feeds, self._EX) if f.rule_id == "W011"]
        assert len(findings) == 1
        assert findings[0].feed_id == 100
        assert "exchangeId 1" in findings[0].message

    def test_zero_sessions_no_finding(self):
        feeds = [{"feedId": 100, "symbol": "S", "exchangeId": 1, "marketSchedules": []}]
        findings = [f for f in check_exchanges(feeds, self._EX) if f.rule_id == "W011"]
        assert findings == []

    def test_w011_suppresses_w010(self):
        feeds = [
            {
                "feedId": 100,
                "symbol": "S",
                "exchangeId": 1,
                "marketSchedules": [
                    {"session": "REGULAR", "marketSchedule": "UTC;C,C,C,C,C,C,C;"},
                    {"session": "PRE_MARKET", "marketSchedule": "UTC;O,O,O,O,O,O,O;"},
                ],
            }
        ]
        all_findings = check_exchanges(feeds, self._EX)
        assert any(f.rule_id == "W011" for f in all_findings)
        assert not any(f.rule_id == "W010" for f in all_findings)

    def test_e019_suppresses_w011(self):
        feeds = [
            {
                "feedId": 100,
                "symbol": "S",
                "exchangeId": 99999,
                "marketSchedules": [
                    {"session": "REGULAR", "marketSchedule": "UTC;C,C,C,C,C,C,C;"},
                ],
            }
        ]
        findings = [f for f in check_exchanges(feeds, self._EX) if f.rule_id == "W011"]
        assert findings == []


class TestSuppressionMatrix:
    """Validates the interaction matrix from the spec:
    E019 → suppresses E020 + W010 on same feed
    W011 → suppresses W010 on same feed
    E024 → gates E021/E023/E025 (entries excluded)
    """

    _EX = [
        {
            "exchangeId": 1,
            "name": "X",
            "sessions": [
                {"session": "REGULAR", "marketSchedule": "UTC;O,O,O,O,O,O,O;"}
            ],
        }
    ]

    def test_e019_blocks_both_e020_and_w010(self):
        feeds = [
            {
                "feedId": 100,
                "symbol": "S",
                "exchangeId": 999,
                "marketSchedules": [
                    {"session": "REGULAR", "marketSchedule": "UTC;C,C,C,C,C,C,C;"},
                    {"session": "PRE_MARKET"},  # would fire E020 case 2
                ],
            }
        ]
        findings = check_exchanges(feeds, self._EX)
        rule_ids = {f.rule_id for f in findings}
        assert "E019" in rule_ids
        assert "E020" not in rule_ids
        assert "W010" not in rule_ids

    def test_w011_blocks_w010_only(self):
        feeds = [
            {
                "feedId": 100,
                "symbol": "S",
                "exchangeId": 1,
                "marketSchedules": [
                    {"session": "REGULAR", "marketSchedule": "UTC;C,C,C,C,C,C,C;"},
                ],
            }
        ]
        findings = check_exchanges(feeds, self._EX)
        rule_ids = {f.rule_id for f in findings}
        assert "W011" in rule_ids
        assert "W010" not in rule_ids

    def test_e024_gates_e021_e023_e025(self):
        # Entries missing 'name' should not appear in tuple/duplicate-id/enum checks.
        ex = [
            {
                "exchangeId": 1,
                "assetClass": "WRONG_VALUE",
                "sessions": self._EX[0]["sessions"],
            },
            {
                "exchangeId": 1,
                "assetClass": "WRONG_VALUE",
                "sessions": self._EX[0]["sessions"],
            },
        ]
        findings = check_exchanges([], ex)
        rule_ids = [f.rule_id for f in findings]
        # Only E024 (twice — missing name on both entries) should appear.
        assert all(r == "E024" for r in rule_ids), rule_ids
        assert "E021" not in rule_ids
        assert "E023" not in rule_ids
        assert "E025" not in rule_ids

    def test_e024_empty_sessions_does_not_suppress_e020(self):
        # Exchange exists but has empty sessions (E024 fires).
        # Feeds inheriting from it should still emit E020 case 2 per session
        # — the kept-noisy decision per spec.
        ex = [{"exchangeId": 1, "name": "X", "sessions": []}]
        feeds = [
            {
                "feedId": 100,
                "symbol": "S",
                "exchangeId": 1,
                "marketSchedules": [
                    {"session": "REGULAR"},  # would fire E020 case 2
                ],
            }
        ]
        findings = check_exchanges(feeds, ex)
        rule_ids = {f.rule_id for f in findings}
        assert "E024" in rule_ids
        assert "E020" in rule_ids


class TestE022:
    def test_no_overrides_no_finding(self):
        feeds = [
            {
                "feedId": 100,
                "symbol": "S",
                "marketSchedules": [
                    {"session": "REGULAR", "marketSchedule": "UTC;O,O,O,O,O,O,O;"},
                ],
            }
        ]
        findings = [f for f in check_exchanges(feeds, []) if f.rule_id == "E022"]
        assert findings == []

    def test_valid_tokens_no_finding(self):
        feeds = [
            {
                "feedId": 100,
                "symbol": "S",
                "marketSchedules": [
                    {
                        "session": "REGULAR",
                        "scheduleOverrides": {
                            "holidayOverrides": ["0101/C", "0619/O", "0703/0930-1300"]
                        },
                    }
                ],
            }
        ]
        findings = [f for f in check_exchanges(feeds, []) if f.rule_id == "E022"]
        assert findings == []

    def test_one_bad_token(self):
        feeds = [
            {
                "feedId": 100,
                "symbol": "S",
                "marketSchedules": [
                    {
                        "session": "REGULAR",
                        "scheduleOverrides": {"holidayOverrides": ["0315/X"]},
                    }
                ],
            }
        ]
        findings = [f for f in check_exchanges(feeds, []) if f.rule_id == "E022"]
        assert len(findings) == 1
        assert "'0315/X'" in findings[0].message
        assert findings[0].feed_id == 100

    def test_three_bad_tokens_emit_three_findings(self):
        feeds = [
            {
                "feedId": 100,
                "symbol": "S",
                "marketSchedules": [
                    {
                        "session": "REGULAR",
                        "scheduleOverrides": {
                            "holidayOverrides": ["0315/X", "315/C", "1340/C"]
                        },
                    }
                ],
            }
        ]
        findings = [f for f in check_exchanges(feeds, []) if f.rule_id == "E022"]
        assert len(findings) == 3

    def test_holiday_overrides_not_a_list(self):
        feeds = [
            {
                "feedId": 100,
                "symbol": "S",
                "marketSchedules": [
                    {
                        "session": "REGULAR",
                        "scheduleOverrides": {
                            "holidayOverrides": "0315/C"
                        },  # string, not list
                    }
                ],
            }
        ]
        findings = [f for f in check_exchanges(feeds, []) if f.rule_id == "E022"]
        assert len(findings) == 1
        assert "must be a list of strings" in findings[0].message

    def test_empty_or_null_overrides_no_finding(self):
        for overrides in ([], None):
            feeds = [
                {
                    "feedId": 100,
                    "symbol": "S",
                    "marketSchedules": [
                        {
                            "session": "REGULAR",
                            "scheduleOverrides": {"holidayOverrides": overrides},
                        }
                    ],
                }
            ]
            findings = [f for f in check_exchanges(feeds, []) if f.rule_id == "E022"]
            assert findings == []
