from lib.symbol_utils import is_futures_symbol, is_us_equity


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
