"""Tests for lib.sql_filters — SQL filter builders and time constants."""

import pytest

from lib.models import TradingSession
from lib.sql_filters import (
    FUTURES_MONTH_CODES,
    REGULAR_MIN_OBSERVATIONS,
    SESSION_MIN_OBSERVATIONS,
    US_EQUITY_AFTERHOURS_CLOSE_HOUR,
    US_EQUITY_AFTERHOURS_CLOSE_MINUTE,
    US_EQUITY_MARKET_CLOSE_HOUR,
    US_EQUITY_MARKET_CLOSE_MINUTE,
    US_EQUITY_MARKET_OPEN_HOUR,
    US_EQUITY_MARKET_OPEN_MINUTE,
    US_EQUITY_OVERNIGHT_END_HOUR,
    US_EQUITY_OVERNIGHT_END_MINUTE,
    US_EQUITY_OVERNIGHT_START_HOUR,
    US_EQUITY_OVERNIGHT_START_MINUTE,
    US_EQUITY_PREMARKET_OPEN_HOUR,
    US_EQUITY_PREMARKET_OPEN_MINUTE,
    get_benchmark_columns,
    get_benchmark_table,
    get_extended_hours_filter_sql,
    get_market_hours_filter_sql,
    get_overnight_hours_filter_sql,
    get_qualifier_filter_sql,
    is_futures_symbol,
)


# ---------------------------------------------------------------------------
# Time constants
# ---------------------------------------------------------------------------
class TestTimeConstants:
    def test_market_open(self):
        assert US_EQUITY_MARKET_OPEN_HOUR == 9
        assert US_EQUITY_MARKET_OPEN_MINUTE == 30

    def test_market_close(self):
        assert US_EQUITY_MARKET_CLOSE_HOUR == 16
        assert US_EQUITY_MARKET_CLOSE_MINUTE == 0

    def test_premarket_open(self):
        assert US_EQUITY_PREMARKET_OPEN_HOUR == 4
        assert US_EQUITY_PREMARKET_OPEN_MINUTE == 0

    def test_afterhours_close(self):
        assert US_EQUITY_AFTERHOURS_CLOSE_HOUR == 20
        assert US_EQUITY_AFTERHOURS_CLOSE_MINUTE == 0

    def test_overnight_start(self):
        assert US_EQUITY_OVERNIGHT_START_HOUR == 20
        assert US_EQUITY_OVERNIGHT_START_MINUTE == 0

    def test_overnight_end(self):
        assert US_EQUITY_OVERNIGHT_END_HOUR == 4
        assert US_EQUITY_OVERNIGHT_END_MINUTE == 0

    def test_observation_thresholds(self):
        assert REGULAR_MIN_OBSERVATIONS == 100
        assert SESSION_MIN_OBSERVATIONS == 50

    def test_futures_month_codes(self):
        assert FUTURES_MONTH_CODES == "FGHJKMNQUVXZ"
        assert len(FUTURES_MONTH_CODES) == 12


# ---------------------------------------------------------------------------
# is_futures_symbol
# ---------------------------------------------------------------------------
class TestIsFuturesSymbol:
    def test_commodity_futures(self):
        assert is_futures_symbol("Commodities.CCH6/USD") is True

    def test_equity_index_futures(self):
        assert is_futures_symbol("Equity.US.EMH6/USD") is True

    def test_regular_equity(self):
        assert is_futures_symbol("Equity.US.AAPL/USD") is False

    def test_fx_pair(self):
        assert is_futures_symbol("FX.EUR/USD") is False

    def test_empty_string(self):
        assert is_futures_symbol("") is False

    def test_no_dot(self):
        assert is_futures_symbol("AAPL") is False

    def test_short_ticker(self):
        # Single char after dot — too short for month+year
        assert is_futures_symbol("Equity.A") is False

    def test_all_month_codes(self):
        for code in "FGHJKMNQUVXZ":
            assert is_futures_symbol(f"Commodities.CC{code}6/USD") is True

    def test_non_month_code_letter(self):
        # 'A' is not a valid month code
        assert is_futures_symbol("Commodities.CCA6/USD") is False

    def test_no_year_digit(self):
        # Month code present but no digit after it
        assert is_futures_symbol("Commodities.CCH/USD") is False

    def test_year_digit_variations(self):
        for digit in "0123456789":
            assert is_futures_symbol(f"Commodities.CCH{digit}/USD") is True

    def test_without_slash_usd(self):
        # Should still detect based on last part after dots
        assert is_futures_symbol("Commodities.CCH6") is True


# ---------------------------------------------------------------------------
# get_benchmark_table
# ---------------------------------------------------------------------------
class TestGetBenchmarkTable:
    def test_futures_symbol(self):
        assert (
            get_benchmark_table("us-equities", "Equity.US.EMH6/USD")
            == "datascope_futures_benchmark_data"
        )

    def test_futures_commodity(self):
        assert (
            get_benchmark_table("commodity", "Commodities.CCH6/USD")
            == "datascope_futures_benchmark_data"
        )

    def test_fx(self):
        assert get_benchmark_table("fx", "FX.EUR/USD") == "datascope_fx_benchmark_data"

    def test_metals(self):
        assert (
            get_benchmark_table("metals", "Metals.XAU/USD")
            == "datascope_fx_benchmark_data"
        )

    def test_us_equities(self):
        assert (
            get_benchmark_table("us-equities", "Equity.US.AAPL/USD")
            == "datascope_global_equities_benchmark_data"
        )

    def test_us_treasuries(self):
        assert (
            get_benchmark_table("us-treasuries", "Rates.US10Y/USD")
            == "datascope_us_treasury_benchmark_data"
        )

    def test_symbol_none(self):
        assert get_benchmark_table("fx", None) == "datascope_fx_benchmark_data"

    def test_default_fallback(self):
        # Unknown mode defaults to global equities table
        assert (
            get_benchmark_table("unknown", "Something.X/USD")
            == "datascope_global_equities_benchmark_data"
        )


# ---------------------------------------------------------------------------
# get_benchmark_columns
# ---------------------------------------------------------------------------
class TestGetBenchmarkColumns:
    def test_treasuries(self):
        assert get_benchmark_columns("us-treasuries") == (
            "yield",
            "bid_yield",
            "ask_yield",
        )

    def test_fx(self):
        assert get_benchmark_columns("fx") == ("price", "bid_price", "ask_price")

    def test_us_equities(self):
        assert get_benchmark_columns("us-equities") == (
            "price",
            "bid_price",
            "ask_price",
        )

    def test_metals(self):
        assert get_benchmark_columns("metals") == ("price", "bid_price", "ask_price")


# ---------------------------------------------------------------------------
# get_market_hours_filter_sql
# ---------------------------------------------------------------------------
class TestGetMarketHoursFilterSql:
    def test_us_equities_returns_sql(self):
        """US equities should produce a non-empty market hours filter."""
        sql = get_market_hours_filter_sql("us-equities", "2026-01-05")
        assert "AND publish_time >=" in sql
        assert "AND publish_time <" in sql

    def test_equity_us_alias(self):
        """equity-us should also produce market hours filter."""
        sql = get_market_hours_filter_sql("equity-us", "2026-01-05")
        assert "AND publish_time >=" in sql

    def test_fx_returns_empty(self):
        """FX runs 24h — no market hours filter needed."""
        sql = get_market_hours_filter_sql("fx", "2026-01-05")
        assert sql == ""

    def test_metals_returns_empty(self):
        sql = get_market_hours_filter_sql("metals", "2026-01-05")
        assert sql == ""

    def test_custom_column_name(self):
        sql = get_market_hours_filter_sql("us-equities", "2026-01-05", "ts")
        assert "AND ts >=" in sql
        assert "AND ts <" in sql
        assert "publish_time" not in sql

    def test_utc_conversion_est_winter(self):
        """Jan 5, 2026 is EST (UTC-5). Market open 9:30 EST = 14:30 UTC."""
        sql = get_market_hours_filter_sql("us-equities", "2026-01-05")
        assert "2026-01-05 14:30:00" in sql  # market open
        assert "2026-01-05 21:00:00" in sql  # market close

    def test_utc_conversion_edt_summer(self):
        """Jul 6, 2026 is EDT (UTC-4). Market open 9:30 EDT = 13:30 UTC."""
        # Clear lru_cache to avoid stale results
        get_market_hours_filter_sql.cache_clear()
        sql = get_market_hours_filter_sql("us-equities", "2026-07-06")
        assert "2026-07-06 13:30:00" in sql  # market open
        assert "2026-07-06 20:00:00" in sql  # market close


# ---------------------------------------------------------------------------
# get_extended_hours_filter_sql
# ---------------------------------------------------------------------------
class TestGetExtendedHoursFilterSql:
    def test_premarket_returns_sql(self):
        sql = get_extended_hours_filter_sql(TradingSession.PREMARKET, "2026-01-05")
        assert "AND publish_time >=" in sql
        assert "AND publish_time <" in sql

    def test_afterhours_returns_sql(self):
        sql = get_extended_hours_filter_sql(TradingSession.AFTERHOURS, "2026-01-05")
        assert "AND publish_time >=" in sql
        assert "AND publish_time <" in sql

    def test_premarket_utc_winter(self):
        """Jan 5, 2026 EST. Pre-market 4:00 AM EST = 09:00 UTC, end 9:30 AM EST = 14:30 UTC."""
        get_extended_hours_filter_sql.cache_clear()
        sql = get_extended_hours_filter_sql(TradingSession.PREMARKET, "2026-01-05")
        assert "2026-01-05 09:00:00" in sql  # start
        assert "2026-01-05 14:30:00" in sql  # end

    def test_afterhours_utc_winter(self):
        """Jan 5, 2026 EST. After-hours 4:00 PM EST = 21:00 UTC, end 8:00 PM EST = 01:00 UTC+1."""
        get_extended_hours_filter_sql.cache_clear()
        sql = get_extended_hours_filter_sql(TradingSession.AFTERHOURS, "2026-01-05")
        assert "2026-01-05 21:00:00" in sql  # start
        assert "2026-01-06 01:00:00" in sql  # end (next day in UTC)

    def test_premarket_utc_summer(self):
        """Jul 6, 2026 EDT. Pre-market 4:00 AM EDT = 08:00 UTC."""
        get_extended_hours_filter_sql.cache_clear()
        sql = get_extended_hours_filter_sql(TradingSession.PREMARKET, "2026-07-06")
        assert "2026-07-06 08:00:00" in sql  # start
        assert "2026-07-06 13:30:00" in sql  # end

    def test_custom_column_name(self):
        sql = get_extended_hours_filter_sql(
            TradingSession.PREMARKET, "2026-01-05", "ts"
        )
        assert "AND ts >=" in sql
        assert "publish_time" not in sql

    def test_regular_session_returns_empty(self):
        """REGULAR session is not an extended hours session."""
        sql = get_extended_hours_filter_sql(TradingSession.REGULAR, "2026-01-05")
        assert sql == ""

    def test_overnight_session_returns_empty(self):
        """OVERNIGHT session is not an extended hours session (has its own function)."""
        sql = get_extended_hours_filter_sql(TradingSession.OVERNIGHT, "2026-01-05")
        assert sql == ""


# ---------------------------------------------------------------------------
# get_overnight_hours_filter_sql
# ---------------------------------------------------------------------------
class TestGetOvernightHoursFilterSql:
    def test_returns_sql(self):
        sql = get_overnight_hours_filter_sql("2026-01-05")
        assert "AND publish_time >=" in sql
        assert "AND publish_time <" in sql

    def test_spans_midnight_utc_winter(self):
        """Jan 5, 2026 EST. Overnight 8 PM EST = 01:00 UTC Jan 6, 4 AM EST = 09:00 UTC Jan 6."""
        get_overnight_hours_filter_sql.cache_clear()
        sql = get_overnight_hours_filter_sql("2026-01-05")
        assert "2026-01-06 01:00:00" in sql  # start (next day in UTC)
        assert "2026-01-06 09:00:00" in sql  # end (next day in UTC)

    def test_spans_midnight_utc_summer(self):
        """Jul 6, 2026 EDT. Overnight 8 PM EDT = 00:00 UTC Jul 7, 4 AM EDT = 08:00 UTC Jul 7."""
        get_overnight_hours_filter_sql.cache_clear()
        sql = get_overnight_hours_filter_sql("2026-07-06")
        assert "2026-07-07 00:00:00" in sql  # start
        assert "2026-07-07 08:00:00" in sql  # end

    def test_custom_column_name(self):
        sql = get_overnight_hours_filter_sql("2026-01-05", "ts")
        assert "AND ts >=" in sql
        assert "publish_time" not in sql

    def test_end_is_next_day_est(self):
        """The 4 AM end time is on the NEXT calendar day in EST."""
        get_overnight_hours_filter_sql.cache_clear()
        sql = get_overnight_hours_filter_sql("2026-01-05")
        # Both start and end fall on Jan 6 in UTC (since Jan 5 8PM EST = Jan 6 1AM UTC)
        assert "2026-01-06" in sql


# ---------------------------------------------------------------------------
# get_qualifier_filter_sql
# ---------------------------------------------------------------------------
class TestGetQualifierFilterSql:
    def test_us_equities_returns_filter(self):
        """US equities should produce a non-empty qualifier filter with all patterns."""
        sql = get_qualifier_filter_sql("us-equities")
        assert "CON[IRGCOND]" in sql
        assert "ODD[IRGCOND]" in sql
        assert "378[IRGCOND]" in sql
        assert "2315[IRGCOND]" in sql
        assert "DAP[IRGCOND]" in sql
        assert "PD_[A-Za-z0-9_]*" in sql

    def test_us_equities_allows_null_qualifiers(self):
        """Filter should allow rows where qualifiers IS NULL."""
        sql = get_qualifier_filter_sql("us-equities")
        assert "qualifiers IS NULL" in sql

    def test_fx_returns_empty(self):
        assert get_qualifier_filter_sql("fx") == ""

    def test_metals_returns_empty(self):
        assert get_qualifier_filter_sql("metals") == ""

    def test_commodity_returns_empty(self):
        assert get_qualifier_filter_sql("commodity") == ""

    def test_us_treasuries_returns_empty(self):
        assert get_qualifier_filter_sql("us-treasuries") == ""

    def test_equity_us_alias(self):
        """equity-us should also produce the qualifier filter."""
        sql = get_qualifier_filter_sql("equity-us")
        assert "qualifiers IS NULL" in sql
        assert "CON[IRGCOND]" in sql
