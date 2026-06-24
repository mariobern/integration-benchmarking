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


class TestCategorizeAssetClass:
    def test_equity_gets_country_suffix(self):
        assert categorize_asset_class("equity", "AAPL") == "equity-us"

    def test_equity_london(self):
        assert categorize_asset_class("equity", "VOD.L") == "equity-gb"

    def test_non_equity_passthrough(self):
        assert categorize_asset_class("metal", "XAU/USD") == "metal"

    def test_fx_passthrough(self):
        assert categorize_asset_class("fx", "EUR/USD") == "fx"
