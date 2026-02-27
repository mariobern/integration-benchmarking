"""Tests for generate_price_list.py."""

import pytest

from generate_price_list import resolve_feed_mode


# -- resolve_feed_mode ---------------------------------------------------------


class TestResolveFeedMode:
    """Test asset_type -> CSV mode resolution."""

    def _entry(self, asset_type: str, symbol: str = "") -> dict:
        return {"asset_type": asset_type, "symbol": symbol}

    def test_fx(self):
        assert resolve_feed_mode(self._entry("fx")) == "fx"

    def test_metal_normalizes_to_metals(self):
        assert resolve_feed_mode(self._entry("metal")) == "metals"

    def test_commodity(self):
        assert resolve_feed_mode(self._entry("commodity")) == "commodity"

    def test_rates_normalizes_to_us_treasuries(self):
        assert resolve_feed_mode(self._entry("rates")) == "us-treasuries"

    def test_us_equity(self):
        assert (
            resolve_feed_mode(self._entry("equity", "Equity.US.AAPL/USD"))
            == "us-equities"
        )

    def test_non_us_equity_returns_none(self):
        assert resolve_feed_mode(self._entry("equity", "Equity.FR.C3M/EUR")) is None

    def test_crypto_returns_none(self):
        assert resolve_feed_mode(self._entry("crypto")) is None

    def test_nav_returns_none(self):
        assert resolve_feed_mode(self._entry("nav")) is None

    def test_funding_rate_returns_none(self):
        assert resolve_feed_mode(self._entry("funding-rate")) is None

    def test_kalshi_returns_none(self):
        assert resolve_feed_mode(self._entry("kalshi")) is None

    def test_unknown_type_returns_none(self):
        assert resolve_feed_mode(self._entry("something-new")) is None
