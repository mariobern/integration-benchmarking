"""Shared symbol utilities for Pyth Lazer feed analysis.

Extracted from sql_filters.py to allow use without ClickHouse dependencies.
"""

from __future__ import annotations

# Futures contract month codes: F=Jan, G=Feb, H=Mar, J=Apr, K=May, M=Jun,
# N=Jul, Q=Aug, U=Sep, V=Oct, X=Nov, Z=Dec
FUTURES_MONTH_CODES = "FGHJKMNQUVXZ"


def is_futures_symbol(symbol: str) -> bool:
    """Detect if a symbol represents a futures contract.

    Pattern: [ROOT][MONTH_CODE][YEAR_DIGIT] where month code is one of
    FGHJKMNQUVXZ and year digit is 0-9.
    """
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


def is_us_equity(feed: dict) -> bool:
    """Check if a feed is a US equity by symbol prefix."""
    return feed.get("symbol", "").startswith("Equity.US.")


def futures_root(symbol: str) -> str:
    """Return the root ticker of a futures symbol, or '' if not a future.

    Commodities.WTIK6/USD -> 'WTI'; Equity.US.EMH6/USD -> 'EM'.
    """
    if not is_futures_symbol(symbol):
        return ""
    base = symbol.split("/")[0] if "/" in symbol else symbol
    ticker = base.split(".")[-1]
    return ticker[:-2]
