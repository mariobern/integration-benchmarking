import pytest
import json
from pathlib import Path

# Minimal lazer_symbols fixture
SAMPLE_SYMBOLS = [
    {"pyth_lazer_id": 922, "name": "AAPL", "symbol": "Equity.US.AAPL/USD",
     "description": "APPLE INC", "asset_type": "equity", "quote_currency": "USD"},
    {"pyth_lazer_id": 327, "name": "EURUSD", "symbol": "FX.EUR/USD",
     "description": "EURO / US DOLLAR", "asset_type": "fx", "quote_currency": "USD"},
    {"pyth_lazer_id": 346, "name": "XAUUSD", "symbol": "Metal.XAU/USD",
     "description": "GOLD SPOT / US DOLLAR", "asset_type": "metal", "quote_currency": "USD"},
    {"pyth_lazer_id": 2931, "name": "CCH6", "symbol": "Commodities.CCH6/USD",
     "description": "COMEX HIGH GRADE COPPER MARCH 2026", "asset_type": "commodity",
     "quote_currency": "USD"},
    {"pyth_lazer_id": 1527, "name": "US10Y", "symbol": "Rates.US10Y",
     "description": "US TREASURY 10 YEAR", "asset_type": "rates", "quote_currency": "USD"},
    {"pyth_lazer_id": 311, "name": "AUDCAD", "symbol": "FX.AUD/CAD",
     "description": "AUSTRALIAN DOLLAR / CANADIAN DOLLAR", "asset_type": "fx",
     "quote_currency": "CAD"},
    {"pyth_lazer_id": 2279, "name": "DMH6", "symbol": "Equity.US.DMH6/USD",
     "description": "PYTH US30 20 MARCH 2026", "asset_type": "equity",
     "quote_currency": "USD"},
    {"pyth_lazer_id": 1, "name": "BTCUSD", "symbol": "Crypto.BTC/USD",
     "description": "BITCOIN / US DOLLAR", "asset_type": "crypto", "quote_currency": "USD"},
]

@pytest.fixture
def symbols_path(tmp_path):
    path = tmp_path / "lazer_symbols.json"
    path.write_text(json.dumps(SAMPLE_SYMBOLS))
    return path


class TestSymbolIndex:
    def test_lookup_by_name(self, symbols_path):
        from generate_ric_mapping import SymbolIndex
        idx = SymbolIndex(symbols_path)
        entry = idx.lookup("AAPL")
        assert entry is not None
        assert entry["pyth_lazer_id"] == 922
        assert entry["symbol"] == "Equity.US.AAPL/USD"

    def test_lookup_case_insensitive(self, symbols_path):
        from generate_ric_mapping import SymbolIndex
        idx = SymbolIndex(symbols_path)
        assert idx.lookup("aapl") is not None
        assert idx.lookup("Aapl") is not None

    def test_lookup_by_pyth_ticker(self, symbols_path):
        from generate_ric_mapping import SymbolIndex
        idx = SymbolIndex(symbols_path)
        # CCH6 is extractable from Commodities.CCH6/USD
        entry = idx.lookup("CCH6")
        assert entry is not None
        assert entry["pyth_lazer_id"] == 2931

    def test_lookup_not_found(self, symbols_path):
        from generate_ric_mapping import SymbolIndex
        idx = SymbolIndex(symbols_path)
        assert idx.lookup("ZZZZZ") is None

    def test_lookup_by_lazer_id(self, symbols_path):
        from generate_ric_mapping import SymbolIndex
        idx = SymbolIndex(symbols_path)
        entry = idx.lookup_by_id(922)
        assert entry is not None
        assert entry["name"] == "AAPL"


class TestFXResolver:
    def test_usd_pair_base_eur(self):
        from generate_ric_mapping import resolve_fx_ric
        assert resolve_fx_ric("FX.EUR/USD") == "EUR="

    def test_usd_pair_quote_jpy(self):
        from generate_ric_mapping import resolve_fx_ric
        assert resolve_fx_ric("FX.USD/JPY") == "JPY="

    def test_usd_pair_quote_aud(self):
        from generate_ric_mapping import resolve_fx_ric
        assert resolve_fx_ric("FX.USD/AUD") == "AUD="

    def test_usd_pair_nzd_usd(self):
        from generate_ric_mapping import resolve_fx_ric
        assert resolve_fx_ric("FX.NZD/USD") == "NZD="

    def test_cross_eur_gbp(self):
        from generate_ric_mapping import resolve_fx_ric
        assert resolve_fx_ric("FX.EUR/GBP") == "EURGBP="

    def test_cross_gbp_jpy(self):
        from generate_ric_mapping import resolve_fx_ric
        assert resolve_fx_ric("FX.GBP/JPY") == "GBPJPY="

    def test_cross_eur_nok(self):
        from generate_ric_mapping import resolve_fx_ric
        assert resolve_fx_ric("FX.EUR/NOK") == "EURNOK="

    def test_cross_aud_cad_uses_R(self):
        from generate_ric_mapping import resolve_fx_ric
        assert resolve_fx_ric("FX.AUD/CAD") == "AUDCAD=R"

    def test_cross_nzd_chf_uses_R(self):
        from generate_ric_mapping import resolve_fx_ric
        assert resolve_fx_ric("FX.NZD/CHF") == "NZDCHF=R"

    def test_cross_cad_chf_uses_R(self):
        from generate_ric_mapping import resolve_fx_ric
        assert resolve_fx_ric("FX.CAD/CHF") == "CADCHF=R"

    def test_cross_aud_jpy_no_R(self):
        from generate_ric_mapping import resolve_fx_ric
        assert resolve_fx_ric("FX.AUD/JPY") == "AUDJPY="

    def test_cross_chf_jpy_no_R(self):
        from generate_ric_mapping import resolve_fx_ric
        assert resolve_fx_ric("FX.CHF/JPY") == "CHFJPY="

    def test_usd_index_dxy(self):
        from generate_ric_mapping import resolve_fx_ric
        assert resolve_fx_ric("FX.USDXY") == ".DXY"

    def test_exotic_brl(self):
        from generate_ric_mapping import resolve_fx_ric
        assert resolve_fx_ric("FX.USD/BRL") == "BRL="

    def test_exotic_inr(self):
        from generate_ric_mapping import resolve_fx_ric
        assert resolve_fx_ric("FX.USD/INR") == "INR="


class TestMetalResolver:
    def test_gold(self):
        from generate_ric_mapping import resolve_metal_ric
        assert resolve_metal_ric("Metal.XAU/USD") == "XAU="

    def test_silver(self):
        from generate_ric_mapping import resolve_metal_ric
        assert resolve_metal_ric("Metal.XAG/USD") == "XAG="

    def test_platinum(self):
        from generate_ric_mapping import resolve_metal_ric
        assert resolve_metal_ric("Metal.XPT/USD") == "XPT="

    def test_palladium(self):
        from generate_ric_mapping import resolve_metal_ric
        assert resolve_metal_ric("Metal.XDP/USD") == "XPD="

    def test_unknown_metal(self):
        from generate_ric_mapping import resolve_metal_ric
        result = resolve_metal_ric("Metal.XCU/USD")
        assert result is None


class TestRatesResolver:
    def test_10y_treasury(self):
        from generate_ric_mapping import resolve_rates_ric
        assert resolve_rates_ric("Rates.US10Y") == "US10YT=RRPS"

    def test_3m_treasury(self):
        from generate_ric_mapping import resolve_rates_ric
        assert resolve_rates_ric("Rates.US3M") == "US3MT=RRPS"

    def test_30y_treasury(self):
        from generate_ric_mapping import resolve_rates_ric
        assert resolve_rates_ric("Rates.US30Y") == "US30YT=RRPS"

    def test_1m_treasury(self):
        from generate_ric_mapping import resolve_rates_ric
        assert resolve_rates_ric("Rates.US1M") == "US1MT=RRPS"

    def test_non_us_rate(self):
        from generate_ric_mapping import resolve_rates_ric
        result = resolve_rates_ric("Rates.SOFR")
        assert result is None


class TestCommodityFuturesResolver:
    def test_copper_march_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric
        assert resolve_commodity_futures_ric("Commodities.CCH6/USD") == "HGH26"

    def test_wti_crude_april_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric
        assert resolve_commodity_futures_ric("Commodities.WTIJ6/USD") == "CLJ26"

    def test_natural_gas_march_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric
        assert resolve_commodity_futures_ric("Commodities.NGDH6/USD") == "NGH26"

    def test_aluminum_march_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric
        assert resolve_commodity_futures_ric("Commodities.ALH6/USD") == "ALIH26"

    def test_palladium_june_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric
        assert resolve_commodity_futures_ric("Commodities.PLM6/USD") == "PAM26"

    def test_platinum_april_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric
        assert resolve_commodity_futures_ric("Commodities.PTJ6/USD") == "PLJ26"

    def test_uranium_march_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric
        assert resolve_commodity_futures_ric("Commodities.URH6/USD") == "UXH26"

    def test_corn_march_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric
        assert resolve_commodity_futures_ric("Commodities.COH6/USD") == "CH26"

    def test_brent_march_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric
        assert resolve_commodity_futures_ric("Commodities.BRENTH6/USD") is not None

    def test_nikkei_march_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric
        assert resolve_commodity_futures_ric("Commodities.NIDH6/USD") == "NKH26"

    def test_unknown_commodity(self):
        from generate_ric_mapping import resolve_commodity_futures_ric
        result = resolve_commodity_futures_ric("Commodities.ZZZZH6/USD")
        assert result is None
