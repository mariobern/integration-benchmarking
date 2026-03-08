"""SQL filter builders and time constants for Pyth Lazer benchmark scripts.

This module provides:
- US equity trading session time constants (market hours, extended hours, overnight)
- Futures contract detection
- Benchmark table and column selection
- SQL WHERE clause builders for time-window filtering (with LRU caching)
"""

from __future__ import annotations

from datetime import datetime, timedelta
from functools import lru_cache
from typing import Optional
from zoneinfo import ZoneInfo

from lib.models import TradingSession

# Futures contract month codes
FUTURES_MONTH_CODES = "FGHJKMNQUVXZ"

# US Equities market hours (EST/EDT) - Regular trading session only
US_EQUITY_MARKET_OPEN_HOUR = 9
US_EQUITY_MARKET_OPEN_MINUTE = 30
US_EQUITY_MARKET_CLOSE_HOUR = 16
US_EQUITY_MARKET_CLOSE_MINUTE = 0

# US Equities extended hours (EST/EDT)
US_EQUITY_PREMARKET_OPEN_HOUR = 4
US_EQUITY_PREMARKET_OPEN_MINUTE = 0
US_EQUITY_AFTERHOURS_CLOSE_HOUR = 20
US_EQUITY_AFTERHOURS_CLOSE_MINUTE = 0

# Overnight: 8:00 PM - 4:00 AM EST (next day)
US_EQUITY_OVERNIGHT_START_HOUR = 20
US_EQUITY_OVERNIGHT_START_MINUTE = 0
US_EQUITY_OVERNIGHT_END_HOUR = 4
US_EQUITY_OVERNIGHT_END_MINUTE = 0

# Observation thresholds
REGULAR_MIN_OBSERVATIONS = 100
SESSION_MIN_OBSERVATIONS = 50


def is_futures_symbol(symbol: str) -> bool:
    """Detect if a symbol represents a futures contract."""

    if not symbol:
        return False

    base = symbol.split("/")[0] if "/" in symbol else symbol
    parts = base.split(".")
    if len(parts) < 2:
        return False

    ticker = parts[-1]
    if len(ticker) < 2:
        return False

    month_code = ticker[-2].upper()
    year_digit = ticker[-1]

    return month_code in FUTURES_MONTH_CODES and year_digit.isdigit()


@lru_cache(maxsize=128)
def get_market_hours_filter_sql(
    mode: str, date: str, column_name: str = "publish_time"
) -> str:
    """Generate SQL WHERE clause for regular market hours filtering."""

    if mode not in ("us-equities", "equity-us"):
        return ""

    dt = datetime.strptime(date, "%Y-%m-%d")
    est = ZoneInfo("America/New_York")
    utc = ZoneInfo("UTC")

    market_open_est = dt.replace(
        hour=US_EQUITY_MARKET_OPEN_HOUR,
        minute=US_EQUITY_MARKET_OPEN_MINUTE,
        tzinfo=est,
    )
    market_close_est = dt.replace(
        hour=US_EQUITY_MARKET_CLOSE_HOUR,
        minute=US_EQUITY_MARKET_CLOSE_MINUTE,
        tzinfo=est,
    )

    market_open_utc = market_open_est.astimezone(utc)
    market_close_utc = market_close_est.astimezone(utc)

    return f"""
        AND {column_name} >= '{market_open_utc.strftime('%Y-%m-%d %H:%M:%S')}'
        AND {column_name} < '{market_close_utc.strftime('%Y-%m-%d %H:%M:%S')}'
    """


@lru_cache(maxsize=128)
def get_extended_hours_filter_sql(
    session: TradingSession,
    date: str,
    column_name: str = "publish_time",
) -> str:
    """Generate SQL WHERE clause for pre-market or after-hours filtering."""

    dt = datetime.strptime(date, "%Y-%m-%d")
    est = ZoneInfo("America/New_York")
    utc = ZoneInfo("UTC")

    if session == TradingSession.PREMARKET:
        start_est = dt.replace(
            hour=US_EQUITY_PREMARKET_OPEN_HOUR,
            minute=US_EQUITY_PREMARKET_OPEN_MINUTE,
            tzinfo=est,
        )
        end_est = dt.replace(
            hour=US_EQUITY_MARKET_OPEN_HOUR,
            minute=US_EQUITY_MARKET_OPEN_MINUTE,
            tzinfo=est,
        )
    elif session == TradingSession.AFTERHOURS:
        start_est = dt.replace(
            hour=US_EQUITY_MARKET_CLOSE_HOUR,
            minute=US_EQUITY_MARKET_CLOSE_MINUTE,
            tzinfo=est,
        )
        end_est = dt.replace(
            hour=US_EQUITY_AFTERHOURS_CLOSE_HOUR,
            minute=US_EQUITY_AFTERHOURS_CLOSE_MINUTE,
            tzinfo=est,
        )
    else:
        return ""

    start_utc = start_est.astimezone(utc)
    end_utc = end_est.astimezone(utc)

    return f"""
        AND {column_name} >= '{start_utc.strftime('%Y-%m-%d %H:%M:%S')}'
        AND {column_name} < '{end_utc.strftime('%Y-%m-%d %H:%M:%S')}'
    """


@lru_cache(maxsize=128)
def get_overnight_hours_filter_sql(date: str, column_name: str = "publish_time") -> str:
    """Generate SQL WHERE clause for overnight session filtering (8 PM - 4 AM ET)."""

    dt = datetime.strptime(date, "%Y-%m-%d")
    est = ZoneInfo("America/New_York")
    utc = ZoneInfo("UTC")

    overnight_start_est = dt.replace(
        hour=US_EQUITY_OVERNIGHT_START_HOUR,
        minute=US_EQUITY_OVERNIGHT_START_MINUTE,
        tzinfo=est,
    )
    overnight_end_est = (dt + timedelta(days=1)).replace(
        hour=US_EQUITY_OVERNIGHT_END_HOUR,
        minute=US_EQUITY_OVERNIGHT_END_MINUTE,
        tzinfo=est,
    )

    overnight_start_utc = overnight_start_est.astimezone(utc)
    overnight_end_utc = overnight_end_est.astimezone(utc)

    return f"""
        AND {column_name} >= '{overnight_start_utc.strftime('%Y-%m-%d %H:%M:%S')}'
        AND {column_name} < '{overnight_end_utc.strftime('%Y-%m-%d %H:%M:%S')}'
    """


def get_benchmark_table(mode: str, symbol: Optional[str]) -> str:
    """Determine which benchmark table to use based on mode and symbol."""

    if symbol and is_futures_symbol(symbol):
        return "datascope_futures_benchmark_data"

    if mode in ("fx", "metals"):
        return "datascope_fx_benchmark_data"
    if mode == "us-treasuries":
        return "datascope_us_treasury_benchmark_data"
    return "datascope_global_equities_benchmark_data"


def get_benchmark_columns(mode: str) -> tuple[str, str, str]:
    """Get benchmark columns by mode (treasuries use yield columns)."""

    if mode == "us-treasuries":
        return ("yield", "bid_yield", "ask_yield")
    return ("price", "bid_price", "ask_price")


def get_qualifier_filter_sql(mode: str) -> str:
    """Return SQL WHERE clause fragment to exclude irregular trade qualifiers.

    Only applies to US equities benchmark data. For all other asset classes,
    returns an empty string (no filtering needed).
    """

    if mode not in ("us-equities", "equity-us"):
        return ""

    return """
        AND (
          qualifiers IS NULL
          OR (
            qualifiers NOT LIKE '%CON[IRGCOND]%'
            AND qualifiers NOT LIKE '%ODD[IRGCOND]%'
            AND qualifiers NOT LIKE '%378[IRGCOND]%'
            AND qualifiers NOT LIKE '%2315[IRGCOND]%'
            AND qualifiers NOT LIKE '%DAP[IRGCOND]%'
            AND NOT match(qualifiers, 'PD_[A-Za-z0-9_]*')
          )
        )
    """
