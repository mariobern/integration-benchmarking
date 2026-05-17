import pytest
import json
from pathlib import Path

# Minimal lazer_symbols fixture
SAMPLE_SYMBOLS = [
    {
        "pyth_lazer_id": 922,
        "name": "AAPL",
        "symbol": "Equity.US.AAPL/USD",
        "description": "APPLE INC",
        "asset_type": "equity",
        "quote_currency": "USD",
    },
    {
        "pyth_lazer_id": 327,
        "name": "EURUSD",
        "symbol": "FX.EUR/USD",
        "description": "EURO / US DOLLAR",
        "asset_type": "fx",
        "quote_currency": "USD",
    },
    {
        "pyth_lazer_id": 346,
        "name": "XAUUSD",
        "symbol": "Metal.XAU/USD",
        "description": "GOLD SPOT / US DOLLAR",
        "asset_type": "metal",
        "quote_currency": "USD",
    },
    {
        "pyth_lazer_id": 2931,
        "name": "CCH6",
        "symbol": "Commodities.CCH6/USD",
        "description": "COMEX HIGH GRADE COPPER MARCH 2026",
        "asset_type": "commodity",
        "quote_currency": "USD",
    },
    {
        "pyth_lazer_id": 1527,
        "name": "US10Y",
        "symbol": "Rates.US10Y",
        "description": "US TREASURY 10 YEAR",
        "asset_type": "rates",
        "quote_currency": "USD",
    },
    {
        "pyth_lazer_id": 311,
        "name": "AUDCAD",
        "symbol": "FX.AUD/CAD",
        "description": "AUSTRALIAN DOLLAR / CANADIAN DOLLAR",
        "asset_type": "fx",
        "quote_currency": "CAD",
    },
    {
        "pyth_lazer_id": 2279,
        "name": "DMH6",
        "symbol": "Equity.US.DMH6/USD",
        "description": "PYTH US30 20 MARCH 2026",
        "asset_type": "equity",
        "quote_currency": "USD",
    },
    {
        "pyth_lazer_id": 9001,
        "name": "NLH6",
        "symbol": "Commodities.NLH6/USD",
        "description": "NICKEL 18 MARCH 2026",
        "asset_type": "commodity",
        "quote_currency": "USD",
    },
    {
        "pyth_lazer_id": 9002,
        "name": "RSK6",
        "symbol": "Commodities.RSK6/USD",
        "description": "RAW SUGAR 30 APRIL 2026",
        "asset_type": "commodity",
        "quote_currency": "USD",
    },
    {
        "pyth_lazer_id": 9003,
        "name": "US500H6",
        "symbol": "Equity.US.US500H6/USD",
        "description": "PYTH US500 20 MARCH 2026",
        "asset_type": "equity",
        "quote_currency": "USD",
    },
    {
        "pyth_lazer_id": 1,
        "name": "BTCUSD",
        "symbol": "Crypto.BTC/USD",
        "description": "BITCOIN / US DOLLAR",
        "asset_type": "crypto",
        "quote_currency": "USD",
    },
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

        assert resolve_commodity_futures_ric("Commodities.BRENTH6/USD") == "LCOH26"

    def test_nikkei_march_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric

        assert resolve_commodity_futures_ric("Commodities.NIDH6/USD") == "NKH26"

    def test_nickel_february_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric

        assert resolve_commodity_futures_ric("Commodities.NLG6/USD") == "MNIG26"

    def test_nickel_march_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric

        assert resolve_commodity_futures_ric("Commodities.NLH6/USD") == "MNIH26"

    def test_lead_june_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric

        assert resolve_commodity_futures_ric("Commodities.LEM6/USD") == "MPBM26"

    def test_lead_september_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric

        assert resolve_commodity_futures_ric("Commodities.LEU6/USD") == "MPBU26"

    def test_tin_march_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric

        assert resolve_commodity_futures_ric("Commodities.TIH6/USD") == "MSNH26"

    def test_raw_sugar_february_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric

        assert resolve_commodity_futures_ric("Commodities.RSH6/USD") == "SBH26"

    def test_raw_sugar_may_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric

        assert resolve_commodity_futures_ric("Commodities.RSK6/USD") == "SBK26"

    def test_gasoil_march_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric

        assert resolve_commodity_futures_ric("Commodities.GOH6/USD") == "LGOH26"

    def test_gasoil_april_2026(self):
        from generate_ric_mapping import resolve_commodity_futures_ric

        assert resolve_commodity_futures_ric("Commodities.GOJ6/USD") == "LGOJ26"

    def test_unknown_commodity(self):
        from generate_ric_mapping import resolve_commodity_futures_ric

        result = resolve_commodity_futures_ric("Commodities.ZZZZH6/USD")
        assert result is None


class TestEquityIndexFuturesResolver:
    def test_emini_sp500_march(self):
        from generate_ric_mapping import resolve_equity_futures_ric

        assert resolve_equity_futures_ric("Equity.US.EMH6/USD") == "ESH26"

    def test_nasdaq_mini(self):
        from generate_ric_mapping import resolve_equity_futures_ric

        result = resolve_equity_futures_ric("Equity.US.NMH6/USD")
        assert result is not None and result.startswith("NQ")

    def test_dow_mini(self):
        from generate_ric_mapping import resolve_equity_futures_ric

        assert resolve_equity_futures_ric("Equity.US.DMH6/USD") == "YMH26"

    def test_non_futures(self):
        from generate_ric_mapping import resolve_equity_futures_ric

        assert resolve_equity_futures_ric("Equity.US.AAPL/USD") is None

    def test_us500_march_2026(self):
        from generate_ric_mapping import resolve_equity_futures_ric

        assert resolve_equity_futures_ric("Equity.US.US500H6/USD") == "ESH26"

    def test_us100_march_2026(self):
        from generate_ric_mapping import resolve_equity_futures_ric

        assert resolve_equity_futures_ric("Equity.US.US100H6/USD") == "NQH26"

    def test_us30_march_2026(self):
        from generate_ric_mapping import resolve_equity_futures_ric

        assert resolve_equity_futures_ric("Equity.US.US30H6/USD") == "YMH26"

    def test_us500_june_2026(self):
        from generate_ric_mapping import resolve_equity_futures_ric

        assert resolve_equity_futures_ric("Equity.US.US500M6/USD") == "ESM26"

    def test_us30_september_2025(self):
        from generate_ric_mapping import resolve_equity_futures_ric

        assert resolve_equity_futures_ric("Equity.US.US30U5/USD") == "YMU25"


class TestRootLength:
    """Length of the base ticker before any class-letter suffix."""

    def test_three_char_plain(self):
        from generate_ric_mapping import _root_length

        assert _root_length("IBM") == 3

    def test_four_char_plain(self):
        from generate_ric_mapping import _root_length

        assert _root_length("TWTR") == 4

    def test_dotted_class_letter(self):
        from generate_ric_mapping import _root_length

        assert _root_length("BRK.B") == 3

    def test_dotted_class_letter_lowercase(self):
        from generate_ric_mapping import _root_length

        assert _root_length("brk.b") == 3

    def test_hyphenated_class_letter(self):
        from generate_ric_mapping import _root_length

        assert _root_length("BRK-B") == 3

    def test_single_char_ticker(self):
        from generate_ric_mapping import _root_length

        assert _root_length("A") == 1

    def test_two_char_ticker(self):
        from generate_ric_mapping import _root_length

        assert _root_length("AB") == 2

    def test_four_char_no_dot(self):
        from generate_ric_mapping import _root_length

        assert _root_length("BABA") == 4

    def test_dotted_non_class_suffix_not_stripped(self):
        # ".WS" (warrants) is not a single class letter, so it should NOT be stripped.
        from generate_ric_mapping import _root_length

        assert _root_length("FOO.WS") == 6


class TestUSConsolidatedSuffix:
    """LSEG consolidated-tape suffix rule for NYSE/Arca/American/Cboe BZX."""

    def test_three_char_root_is_bare(self):
        from generate_ric_mapping import _us_consolidated_suffix

        assert _us_consolidated_suffix(3) == ""

    def test_four_char_root_gets_dot_k(self):
        from generate_ric_mapping import _us_consolidated_suffix

        assert _us_consolidated_suffix(4) == ".K"

    def test_five_char_root_gets_dot_k(self):
        from generate_ric_mapping import _us_consolidated_suffix

        assert _us_consolidated_suffix(5) == ".K"

    def test_one_char_root_is_bare(self):
        from generate_ric_mapping import _us_consolidated_suffix

        assert _us_consolidated_suffix(1) == ""


class TestEquityResolver:
    def test_nasdaq_ticker(self, tmp_path):
        from generate_ric_mapping import EquityResolver

        nasdaq_file = tmp_path / "nasdaqlisted.txt"
        nasdaq_file.write_text(
            "Symbol|Security Name|Market Category|Test Issue\nAAPL|Apple Inc|Q|N\n"
        )
        other_file = tmp_path / "otherlisted.txt"
        other_file.write_text(
            "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue\n"
        )
        resolver = EquityResolver(cache_dir=tmp_path)
        resolver._load_from_files(nasdaq_file, other_file)
        assert resolver.resolve("AAPL") == "AAPL.O"

    def test_nyse_ticker(self, tmp_path):
        from generate_ric_mapping import EquityResolver

        nasdaq_file = tmp_path / "nasdaqlisted.txt"
        nasdaq_file.write_text("Symbol|Security Name|Market Category|Test Issue\n")
        other_file = tmp_path / "otherlisted.txt"
        other_file.write_text(
            "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue\nJPM|JPMorgan Chase|N|||100|N\n"
        )
        resolver = EquityResolver(cache_dir=tmp_path)
        resolver._load_from_files(nasdaq_file, other_file)
        assert resolver.resolve("JPM") == "JPM"

    def test_dotted_ticker(self, tmp_path):
        from generate_ric_mapping import EquityResolver

        nasdaq_file = tmp_path / "nasdaqlisted.txt"
        nasdaq_file.write_text("Symbol|Security Name|Market Category|Test Issue\n")
        other_file = tmp_path / "otherlisted.txt"
        other_file.write_text(
            "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue\nBRK.B|Berkshire Hathaway B|N|||100|N\n"
        )
        resolver = EquityResolver(cache_dir=tmp_path)
        resolver._load_from_files(nasdaq_file, other_file)
        assert resolver.resolve("BRK.B") == "BRKb"

    def test_consolidated_short_root_nyse_is_bare(self, tmp_path):
        from generate_ric_mapping import EquityResolver

        nasdaq_file = tmp_path / "nasdaqlisted.txt"
        nasdaq_file.write_text("Symbol|Security Name|Market Category|Test Issue\n")
        other_file = tmp_path / "otherlisted.txt"
        other_file.write_text(
            "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue\n"
            "IBM|International Business Machines|N|||100|N\n"
        )
        resolver = EquityResolver(cache_dir=tmp_path)
        resolver._load_from_files(nasdaq_file, other_file)
        assert resolver.resolve("IBM") == "IBM"

    def test_consolidated_long_root_nyse_gets_dot_k(self, tmp_path):
        from generate_ric_mapping import EquityResolver

        nasdaq_file = tmp_path / "nasdaqlisted.txt"
        nasdaq_file.write_text("Symbol|Security Name|Market Category|Test Issue\n")
        other_file = tmp_path / "otherlisted.txt"
        other_file.write_text(
            "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue\n"
            "TWTR|Twitter Inc|N|||100|N\n"
        )
        resolver = EquityResolver(cache_dir=tmp_path)
        resolver._load_from_files(nasdaq_file, other_file)
        assert resolver.resolve("TWTR") == "TWTR.K"

    def test_consolidated_short_root_arca_is_bare(self, tmp_path):
        from generate_ric_mapping import EquityResolver

        nasdaq_file = tmp_path / "nasdaqlisted.txt"
        nasdaq_file.write_text("Symbol|Security Name|Market Category|Test Issue\n")
        other_file = tmp_path / "otherlisted.txt"
        other_file.write_text(
            "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue\n"
            "SPY|SPDR S&P 500 ETF Trust|P|||100|N\n"
        )
        resolver = EquityResolver(cache_dir=tmp_path)
        resolver._load_from_files(nasdaq_file, other_file)
        assert resolver.resolve("SPY") == "SPY"

    def test_consolidated_long_root_cboe_bzx_gets_dot_k(self, tmp_path):
        from generate_ric_mapping import EquityResolver

        nasdaq_file = tmp_path / "nasdaqlisted.txt"
        nasdaq_file.write_text("Symbol|Security Name|Market Category|Test Issue\n")
        other_file = tmp_path / "otherlisted.txt"
        other_file.write_text(
            "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue\n"
            "CBOE|Cboe Global Markets|Z|||100|N\n"
        )
        resolver = EquityResolver(cache_dir=tmp_path)
        resolver._load_from_files(nasdaq_file, other_file)
        assert resolver.resolve("CBOE") == "CBOE.K"

    def test_consolidated_nyse_american_long_root_gets_dot_k(self, tmp_path):
        from generate_ric_mapping import EquityResolver

        nasdaq_file = tmp_path / "nasdaqlisted.txt"
        nasdaq_file.write_text("Symbol|Security Name|Market Category|Test Issue\n")
        other_file = tmp_path / "otherlisted.txt"
        other_file.write_text(
            "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue\n"
            "LIVE|Live Ventures Inc|A|||100|N\n"
        )
        resolver = EquityResolver(cache_dir=tmp_path)
        resolver._load_from_files(nasdaq_file, other_file)
        assert resolver.resolve("LIVE") == "LIVE.K"

    def test_consolidated_iex_unchanged(self, tmp_path):
        from generate_ric_mapping import EquityResolver

        nasdaq_file = tmp_path / "nasdaqlisted.txt"
        nasdaq_file.write_text("Symbol|Security Name|Market Category|Test Issue\n")
        other_file = tmp_path / "otherlisted.txt"
        other_file.write_text(
            "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue\n"
            "INTC|Intel Corp|V|||100|N\n"
        )
        resolver = EquityResolver(cache_dir=tmp_path)
        resolver._load_from_files(nasdaq_file, other_file)
        assert resolver.resolve("INTC") == "INTC.K"

    def test_consolidated_dotted_long_root(self, tmp_path):
        # Hypothetical 4-char-root ticker with class letter: root=LONG (4), class=b
        # Expected RIC: "LONGb.K"
        from generate_ric_mapping import EquityResolver

        nasdaq_file = tmp_path / "nasdaqlisted.txt"
        nasdaq_file.write_text("Symbol|Security Name|Market Category|Test Issue\n")
        other_file = tmp_path / "otherlisted.txt"
        other_file.write_text(
            "ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue\n"
            "LONG.B|Long Corp Class B|N|||100|N\n"
        )
        resolver = EquityResolver(cache_dir=tmp_path)
        resolver._load_from_files(nasdaq_file, other_file)
        assert resolver.resolve("LONG.B") == "LONGb.K"


class TestRICResolver:
    """Integration tests for the main resolve() dispatcher."""

    def test_resolve_equity(self, symbols_path, tmp_path):
        from generate_ric_mapping import RICResolver

        nasdaq = tmp_path / "nasdaqlisted.txt"
        nasdaq.write_text(
            "Symbol|Security Name|Market Category|Test Issue\nAAPL|Apple Inc|Q|N\n"
        )
        other = tmp_path / "otherlisted.txt"
        other.write_text("ACT Symbol|Security Name|Exchange|CQS|ETF|Lot|Test\n")
        resolver = RICResolver(symbols_path, equity_cache_dir=tmp_path)
        resolver._equity._load_from_files(nasdaq, other)
        result = resolver.resolve("AAPL")
        assert result.ric == "AAPL.O"
        assert result.asset_class == "Common Stock"
        assert result.pyth_lazer_id == 922

    def test_resolve_equity_fallback_short_root_is_bare(self, symbols_path, tmp_path):
        from generate_ric_mapping import RICResolver

        # AAPL is in the lazer_symbols fixture but absent from both NASDAQ Trader files,
        # forcing the low-confidence fallback path.
        nasdaq = tmp_path / "nasdaqlisted.txt"
        nasdaq.write_text("Symbol|Security Name|Market Category|Test Issue\n")
        other = tmp_path / "otherlisted.txt"
        other.write_text("ACT Symbol|Security Name|Exchange|CQS|ETF|Lot|Test\n")
        resolver = RICResolver(symbols_path, equity_cache_dir=tmp_path)
        resolver._equity._load_from_files(nasdaq, other)
        result = resolver.resolve("AAPL")
        # AAPL root length = 4 -> ".K"
        assert result.ric == "AAPL.K"
        assert result.confidence == "low"
        assert any("verify exchange suffix" in w for w in result.warnings)

    def test_resolve_equity_fallback_long_root_gets_dot_k(self, symbols_path, tmp_path):
        # Confirms the >=4 branch of the fallback. Reuses the AAPL fixture entry which
        # has a 4-char root; .K is expected.
        from generate_ric_mapping import RICResolver

        nasdaq = tmp_path / "nasdaqlisted.txt"
        nasdaq.write_text("Symbol|Security Name|Market Category|Test Issue\n")
        other = tmp_path / "otherlisted.txt"
        other.write_text("ACT Symbol|Security Name|Exchange|CQS|ETF|Lot|Test\n")
        resolver = RICResolver(symbols_path, equity_cache_dir=tmp_path)
        resolver._equity._load_from_files(nasdaq, other)
        result = resolver.resolve("AAPL")
        assert result.ric == "AAPL.K"

    def test_resolve_fx(self, symbols_path):
        from generate_ric_mapping import RICResolver

        resolver = RICResolver(symbols_path)
        result = resolver.resolve("EURUSD")
        assert result.ric == "EUR="
        assert result.asset_class == "Forex"

    def test_resolve_fx_cross(self, symbols_path):
        from generate_ric_mapping import RICResolver

        resolver = RICResolver(symbols_path)
        result = resolver.resolve("AUDCAD")
        assert result.ric == "AUDCAD=R"
        assert result.asset_class == "Forex"

    def test_resolve_metal(self, symbols_path):
        from generate_ric_mapping import RICResolver

        resolver = RICResolver(symbols_path)
        result = resolver.resolve("XAUUSD")
        assert result.ric == "XAU="
        assert result.asset_class == "Metal"

    def test_resolve_commodity_futures(self, symbols_path):
        from generate_ric_mapping import RICResolver

        resolver = RICResolver(symbols_path)
        result = resolver.resolve("CCH6")
        assert result.ric == "HGH26"
        assert result.asset_class == "Commodity Future"

    def test_resolve_rates(self, symbols_path):
        from generate_ric_mapping import RICResolver

        resolver = RICResolver(symbols_path)
        result = resolver.resolve("US10Y")
        assert result.ric == "US10YT=RRPS"
        assert result.asset_class == "Rates"

    def test_resolve_crypto_skipped(self, symbols_path):
        from generate_ric_mapping import RICResolver

        resolver = RICResolver(symbols_path)
        result = resolver.resolve("BTCUSD")
        assert result.ric == ""
        assert len(result.warnings) > 0

    def test_resolve_not_found(self, symbols_path):
        from generate_ric_mapping import RICResolver

        resolver = RICResolver(symbols_path)
        result = resolver.resolve("ZZZZZ")
        assert result.ric == ""
        assert len(result.warnings) > 0

    def test_resolve_nickel_futures(self, symbols_path):
        from generate_ric_mapping import RICResolver

        resolver = RICResolver(symbols_path)
        result = resolver.resolve("NLH6")
        assert result.ric == "MNIH26"
        assert result.asset_class == "Commodity Future"
        assert result.confidence == "high"

    def test_resolve_sugar_futures(self, symbols_path):
        from generate_ric_mapping import RICResolver

        resolver = RICResolver(symbols_path)
        result = resolver.resolve("RSK6")
        assert result.ric == "SBK26"
        assert result.asset_class == "Commodity Future"

    def test_resolve_us500_futures(self, symbols_path):
        from generate_ric_mapping import RICResolver

        resolver = RICResolver(symbols_path)
        result = resolver.resolve("US500H6")
        assert result.ric == "ESH26"
        assert result.asset_class == "Equity Future"
        assert result.confidence == "high"


class TestCSVOutput:
    def test_csv_format(self, symbols_path, tmp_path):
        from generate_ric_mapping import RICResolver, write_csv

        resolver = RICResolver(symbols_path)
        results = [resolver.resolve("EURUSD"), resolver.resolve("US10Y")]
        output = tmp_path / "output.csv"
        write_csv(results, output)
        assert output.exists()
        import csv

        with open(output) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 2
        assert rows[0]["source_value"] == "EUR="
        assert rows[0]["source_type"] == "RIC"


class TestCLI:
    def test_single_ticker(self, symbols_path, tmp_path):
        """Test CLI with a single ticker."""
        import subprocess

        output = tmp_path / "out.csv"
        result = subprocess.run(
            [
                "python3",
                "generate_ric_mapping.py",
                "--ticker",
                "EURUSD",
                "--symbols",
                str(symbols_path),
                "--output",
                str(output),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert output.exists()

    def test_ticker_file(self, symbols_path, tmp_path):
        """Test CLI with ticker file input."""
        import subprocess

        ticker_file = tmp_path / "tickers.txt"
        ticker_file.write_text("EURUSD\nUS10Y\n")
        output = tmp_path / "out.csv"
        result = subprocess.run(
            [
                "python3",
                "generate_ric_mapping.py",
                "--ticker-file",
                str(ticker_file),
                "--symbols",
                str(symbols_path),
                "--output",
                str(output),
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert output.exists()
        import csv

        with open(output) as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 2


@pytest.mark.skipif(
    not Path("lazer_symbols.json").exists(), reason="lazer_symbols.json not available"
)
class TestIntegration:
    """Validate resolved RICs against known pyth_mappings_export values."""

    KNOWN_MAPPINGS = {
        # FX
        "EURUSD": ("EUR=", "Forex"),
        "AUDCAD": ("AUDCAD=R", "Forex"),
        # Metals
        "XAUUSD": ("XAU=", "Metal"),
        "XAGUSD": ("XAG=", "Metal"),
        # Rates
        "US10Y": ("US10YT=RRPS", "Rates"),
        "US3M": ("US3MT=RRPS", "Rates"),
    }

    def test_known_mappings(self):
        from generate_ric_mapping import RICResolver

        resolver = RICResolver()
        for ticker, (expected_ric, expected_class) in self.KNOWN_MAPPINGS.items():
            result = resolver.resolve(ticker)
            assert (
                result.ric == expected_ric
            ), f"{ticker}: got {result.ric}, expected {expected_ric}"
            assert (
                result.asset_class == expected_class
            ), f"{ticker}: got {result.asset_class}"

    def test_crypto_skipped(self):
        from generate_ric_mapping import RICResolver

        resolver = RICResolver()
        result = resolver.resolve("BTCUSD")
        assert result.ric == ""
