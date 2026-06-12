"""Tests for rank_overnight_candidates.py."""

import pandas as pd

from rank_overnight_candidates import (
    OUTPUT_COLUMNS,
    coerce_bool,
    join_and_rank,
    split_resolved,
)


def _meta():
    return pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "feedId": 1,
                "state": "STABLE",
                "overnight_configured": False,
            },
            {
                "ticker": "BBB",
                "feedId": 2,
                "state": "COMING_SOON",
                "overnight_configured": True,
            },
            {
                "ticker": "CCC",
                "feedId": 3,
                "state": "STABLE",
                "overnight_configured": False,
            },
        ]
    )


def _volume():
    # CCC has no row -> unresolved. BBB has higher after-hours dollar vol than AAA.
    return pd.DataFrame(
        [
            {
                "ticker": "AAA",
                "liquidity_tier": "MEDIUM",
                "total_dollar_vol": 9.0,
                "regular_dollar_vol": 8.0,
                "after_hours_dollar_vol": 1.0,
                "after_hours_pct": 11.0,
                "pre_market_dollar_vol": 0.0,
            },
            {
                "ticker": "BBB",
                "liquidity_tier": "HIGH",
                "total_dollar_vol": 100.0,
                "regular_dollar_vol": 90.0,
                "after_hours_dollar_vol": 5.0,
                "after_hours_pct": 5.0,
                "pre_market_dollar_vol": 5.0,
            },
        ]
    )


class TestCoerceBool:
    def test_string_false(self):
        assert coerce_bool("False") is False

    def test_string_true(self):
        assert coerce_bool("True") is True

    def test_real_bool(self):
        assert coerce_bool(True) is True


class TestSplitResolved:
    def test_unresolved_listed(self):
        resolved, unresolved = split_resolved(_volume(), _meta())
        assert unresolved == ["CCC"]
        assert set(resolved["ticker"]) == {"AAA", "BBB"}


class TestJoinAndRank:
    def test_sorted_desc_by_after_hours_and_columns(self):
        ranked = join_and_rank(_volume(), _meta())
        assert list(ranked["ticker"]) == ["BBB", "AAA"]  # 5.0 > 1.0
        assert list(ranked.columns) == OUTPUT_COLUMNS
        assert ranked.iloc[0]["feedId"] == 2
        assert ranked.iloc[0]["overnight_configured"] is True
