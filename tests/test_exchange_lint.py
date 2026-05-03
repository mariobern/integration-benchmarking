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
