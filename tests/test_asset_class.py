from lib.asset_class import categorize_asset_class, get_equity_country


class TestGetEquityCountry:
    def test_no_suffix_defaults_us(self):
        assert get_equity_country("AAPL") == "us"

    def test_none_defaults_us(self):
        assert get_equity_country(None) == "us"

    def test_empty_defaults_us(self):
        assert get_equity_country("") == "us"

    def test_london_suffix(self):
        assert get_equity_country("VOD.L") == "gb"

    def test_hong_kong_suffix(self):
        assert get_equity_country("0700.HK") == "hk"

    def test_case_insensitive_suffix(self):
        assert get_equity_country("vod.l") == "gb"


class TestEquityPrefixCountry:
    def test_us_prefix(self):
        assert get_equity_country("Equity.US.AAPL/USD") == "us"

    def test_us_futures_prefix(self):
        assert get_equity_country("Equity.US.EMH6/USD") == "us"

    def test_hong_kong_prefix(self):
        assert get_equity_country("Equity.HK.0700/HKD") == "hk"

    def test_china_prefix(self):
        assert get_equity_country("Equity.CN.600519/CNY") == "cn"

    def test_japan_prefix(self):
        assert get_equity_country("Equity.JP.7203/JPY") == "jp"

    def test_korea_prefix(self):
        assert get_equity_country("Equity.KR.005930/KRW") == "kr"

    def test_germany_prefix(self):
        assert get_equity_country("Equity.DE.ADS/EUR") == "de"

    def test_categorize_intl_equity(self):
        assert categorize_asset_class("equity", "Equity.HK.0700/HKD") == "equity-hk"

    def test_categorize_us_equity(self):
        assert categorize_asset_class("equity", "Equity.US.AAPL/USD") == "equity-us"

    def test_suffix_fallback_still_works(self):
        # RIC-style symbols (no Equity. prefix) still use the suffix map
        assert get_equity_country("VOD.L") == "gb"
        assert get_equity_country("0700.HK") == "hk"


class TestCategorizeAssetClass:
    def test_equity_gets_country_suffix(self):
        assert categorize_asset_class("equity", "AAPL") == "equity-us"

    def test_equity_london(self):
        assert categorize_asset_class("equity", "VOD.L") == "equity-gb"

    def test_non_equity_passthrough(self):
        assert categorize_asset_class("metal", "XAU/USD") == "metal"

    def test_fx_passthrough(self):
        assert categorize_asset_class("fx", "EUR/USD") == "fx"


class TestInstrumentType:
    def test_parse_present(self):
        from lib.asset_class import parse_instrument_type

        meta = '{"items":[{"key":"asset_type","value":{"stringValue":"equity"}},{"key":"instrument_type","value":{"stringValue":"future"}}]}'
        assert parse_instrument_type(meta) == "future"

    def test_parse_perp(self):
        from lib.asset_class import parse_instrument_type

        meta = '{"items":[{"key":"instrument_type","value":{"stringValue":"perp"}}]}'
        assert parse_instrument_type(meta) == "perp"

    def test_parse_absent_key(self):
        from lib.asset_class import parse_instrument_type

        meta = '{"items":[{"key":"asset_type","value":{"stringValue":"equity"}}]}'
        assert parse_instrument_type(meta) is None

    def test_parse_empty_or_malformed(self):
        from lib.asset_class import parse_instrument_type

        assert parse_instrument_type("") is None
        assert parse_instrument_type("not json") is None

    def test_resolve_present_passthrough(self):
        from lib.asset_class import resolve_instrument_type

        assert resolve_instrument_type("spot", "Equity.DE.MUV2/EUR") == "spot"
        assert resolve_instrument_type("perp", "Pyth.DC.AAPL/USDT") == "perp"

    def test_resolve_missing_uses_heuristic(self):
        from lib.asset_class import resolve_instrument_type

        assert resolve_instrument_type(None, "Equity.US.DMM6/USD") == "future"
        assert resolve_instrument_type(None, "Equity.US.ANSS/USD") == "spot"
