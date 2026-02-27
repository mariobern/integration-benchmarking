"""Tests for generate_price_list.py."""

import json
from pathlib import Path

import pytest

from generate_price_list import (
    build_lookup,
    load_symbols,
    resolve_feed_mode,
    resolve_feeds,
)


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


# -- load_symbols + build_lookup -----------------------------------------------


SAMPLE_SYMBOLS = [
    {"pyth_lazer_id": 327, "asset_type": "fx", "symbol": "FX.EUR/USD"},
    {"pyth_lazer_id": 345, "asset_type": "metal", "symbol": "Metal.XAG/USD"},
    {"pyth_lazer_id": 922, "asset_type": "equity", "symbol": "Equity.US.AAPL/USD"},
    {"pyth_lazer_id": 1, "asset_type": "crypto", "symbol": "Crypto.BTC/USD"},
    {"pyth_lazer_id": 779, "asset_type": "equity", "symbol": "Equity.FR.C3M/EUR"},
]


class TestLoadSymbols:
    def test_loads_json_file(self, tmp_path: Path):
        path = tmp_path / "symbols.json"
        path.write_text(json.dumps(SAMPLE_SYMBOLS))
        result = load_symbols(path)
        assert len(result) == 5

    def test_file_not_found_raises(self, tmp_path: Path):
        with pytest.raises(FileNotFoundError):
            load_symbols(tmp_path / "missing.json")


class TestBuildLookup:
    def test_builds_dict_keyed_by_id(self):
        lookup = build_lookup(SAMPLE_SYMBOLS)
        assert 327 in lookup
        assert lookup[327]["asset_type"] == "fx"

    def test_all_ids_present(self):
        lookup = build_lookup(SAMPLE_SYMBOLS)
        assert set(lookup.keys()) == {327, 345, 922, 1, 779}


# -- resolve_feeds -------------------------------------------------------------


class TestResolveFeeds:
    def setup_method(self):
        self.lookup = build_lookup(SAMPLE_SYMBOLS)

    def test_resolves_benchmarkable_feeds(self):
        resolved, skipped = resolve_feeds([327, 345, 922], self.lookup)
        assert len(resolved) == 3
        assert resolved[327] == "fx"
        assert resolved[345] == "metals"
        assert resolved[922] == "us-equities"

    def test_skips_crypto(self):
        resolved, skipped = resolve_feeds([1], self.lookup)
        assert len(resolved) == 0
        assert len(skipped) == 1
        assert "not benchmarkable" in skipped[0].lower()

    def test_skips_non_us_equity(self):
        resolved, skipped = resolve_feeds([779], self.lookup)
        assert len(resolved) == 0
        assert len(skipped) == 1
        assert "non-US" in skipped[0]

    def test_skips_unknown_feed_id(self):
        resolved, skipped = resolve_feeds([99999], self.lookup)
        assert len(resolved) == 0
        assert len(skipped) == 1
        assert "not found" in skipped[0].lower()

    def test_mixed_valid_and_invalid(self):
        resolved, skipped = resolve_feeds([327, 1, 99999], self.lookup)
        assert len(resolved) == 1
        assert 327 in resolved
        assert len(skipped) == 2
