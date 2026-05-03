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
