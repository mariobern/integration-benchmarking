from lib.symbol_utils import (
    equity_listing_prefix,
    futures_root,
    is_futures_symbol,
    is_us_equity,
)


class TestIsFuturesSymbol:
    def test_commodity_future(self):
        assert is_futures_symbol("Commodities.CCH6/USD") is True

    def test_equity_future(self):
        assert is_futures_symbol("Equity.US.EMH6/USD") is True

    def test_all_month_codes(self):
        for code in "FGHJKMNQUVXZ":
            assert is_futures_symbol(f"Commodities.CC{code}6/USD") is True

    def test_regular_equity(self):
        assert is_futures_symbol("Equity.US.AAPL/USD") is False

    def test_crypto(self):
        assert is_futures_symbol("Crypto.BTC/USD") is False

    def test_fx(self):
        assert is_futures_symbol("FX.EUR/USD") is False

    def test_empty_string(self):
        assert is_futures_symbol("") is False

    def test_short_ticker(self):
        assert is_futures_symbol("X.A/USD") is False


class TestIsUsEquity:
    def test_us_equity(self):
        assert is_us_equity({"symbol": "Equity.US.AAPL/USD"}) is True

    def test_non_us_equity(self):
        assert is_us_equity({"symbol": "Equity.GB.VOD/GBP"}) is False

    def test_crypto(self):
        assert is_us_equity({"symbol": "Crypto.BTC/USD"}) is False

    def test_missing_symbol(self):
        assert is_us_equity({}) is False

    def test_us_equity_future(self):
        assert is_us_equity({"symbol": "Equity.US.EMH6/USD"}) is True


class TestFuturesRoot:
    def test_commodity_future(self):
        assert futures_root("Commodities.WTIK6/USD") == "WTI"

    def test_equity_future(self):
        assert futures_root("Equity.US.EMH6/USD") == "EM"

    def test_longer_root(self):
        assert futures_root("Commodities.BRENTJ6/USD") == "BRENT"

    def test_non_futures_returns_empty(self):
        assert futures_root("Equity.US.AAPL/USD") == ""

    def test_crypto_returns_empty(self):
        assert futures_root("Crypto.BTC/USD") == ""

    def test_empty_string(self):
        assert futures_root("") == ""


class TestEquityListingPrefix:
    def test_us_equity(self):
        assert equity_listing_prefix("Equity.US.AAPL/USD") == "US"

    def test_jp_equity(self):
        assert equity_listing_prefix("Equity.JP.1305/JPY") == "JP"

    def test_kr_equity(self):
        assert equity_listing_prefix("Equity.KR.000100/KRW") == "KR"

    def test_index_equity(self):
        assert equity_listing_prefix("Equity.Index.TSLA/USD") == "Index"

    def test_us_equity_future(self):
        assert equity_listing_prefix("Equity.US.EMH6/USD") == "US"

    def test_non_equity_crypto(self):
        assert equity_listing_prefix("Crypto.BTC/USD") == ""

    def test_non_equity_fx(self):
        assert equity_listing_prefix("FX.EUR/USD") == ""

    def test_non_equity_commodity(self):
        assert equity_listing_prefix("Commodities.WTIK6/USD") == ""

    def test_malformed_two_segments(self):
        assert equity_listing_prefix("Equity.US") == ""

    def test_malformed_no_dots(self):
        assert equity_listing_prefix("EquityUSAAPL") == ""

    def test_empty_string(self):
        assert equity_listing_prefix("") == ""
