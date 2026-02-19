#!/usr/bin/env python3
"""
Universal RIC Mapping Generator for Pyth Network.

Given ticker(s), looks them up in lazer_symbols.json, derives the Reuters
Instrument Code (RIC) using asset-class-specific rules, and outputs a CSV
matching the pyth_mappings_export format for Datascope onboarding.

Supports: US equities, ETFs, FX, metals, commodity futures, equity index
futures, and US Treasury rates.

Usage:
    python generate_ric_mapping.py --ticker AAPL
    python generate_ric_mapping.py --ticker AAPL AUDCAD CCH6 XAU US10Y
    python generate_ric_mapping.py --ticker-file new_tickers.txt
    python generate_ric_mapping.py --ticker AAPL --output my_mappings.csv
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# --- Constants ---

DEFAULT_SYMBOLS_PATH = Path("lazer_symbols.json")

# Asset types that have Datascope benchmarks (RIC-resolvable)
BENCHMARKABLE_ASSET_TYPES = {"equity", "fx", "metal", "commodity", "rates"}

# Asset types with no Datascope benchmark
NON_BENCHMARKABLE_ASSET_TYPES = {
    "crypto", "crypto-index", "crypto-redemption-rate",
    "funding-rate", "nav", "kalshi", "custom",
}


# Currencies that use =R suffix when crossed among themselves (no EUR, GBP, or JPY)
_R_SUFFIX_CURRENCIES = {"AUD", "NZD", "CAD", "CHF"}


# --- FX RIC Resolver ---

def resolve_fx_ric(symbol: str) -> Optional[str]:
    """Derive Datascope RIC for an FX symbol.

    Rules (derived from 60 existing pyth_mappings):
    - FX.USDXY -> .DXY (special case)
    - USD pair (one side is USD): non-USD currency + "=" (e.g., EUR=, JPY=)
    - Cross pair with EUR/GBP/JPY involved: BASECCY+QUOTECCY+"=" (e.g., EURGBP=)
    - Cross pair both in {AUD,NZD,CAD,CHF}: BASECCY+QUOTECCY+"=R" (e.g., AUDCAD=R)
    """
    if not symbol.startswith("FX."):
        return None

    body = symbol[3:]  # Strip "FX."

    # Special case: Dollar Index
    if body == "USDXY":
        return ".DXY"

    # Parse base/quote
    if "/" not in body:
        return None
    base, quote = body.split("/", 1)
    base = base.upper()
    quote = quote.upper()

    # USD pair: return the non-USD currency + "="
    if base == "USD" or quote == "USD":
        non_usd = quote if base == "USD" else base
        return f"{non_usd}="

    # Cross pair: both in _R_SUFFIX_CURRENCIES -> use =R
    if base in _R_SUFFIX_CURRENCIES and quote in _R_SUFFIX_CURRENCIES:
        return f"{base}{quote}=R"

    # Cross pair: anything else -> use =
    return f"{base}{quote}="


# --- Metal RIC Map ---

METAL_RIC_MAP = {
    "XAU": "XAU=",
    "XAG": "XAG=",
    "XPT": "XPT=",
    "XPD": "XPD=",
    "XDP": "XPD=",  # Pyth uses XDP for palladium (Metal.XDP/USD)
}


def resolve_metal_ric(symbol: str) -> Optional[str]:
    """Derive RIC for a metal spot symbol. Returns None if unknown."""
    if not symbol.startswith("Metal."):
        return None
    body = symbol[6:]  # Strip "Metal."
    code = body.split("/")[0].upper()
    code = code.replace("_DEPRECATED", "")
    return METAL_RIC_MAP.get(code)


# --- Rates RIC ---

_US_TREASURY_PATTERN = re.compile(r"^Rates\.US(\d+[MY])$")


def resolve_rates_ric(symbol: str) -> Optional[str]:
    """Derive RIC for US Treasury rates. Pattern: US{TENOR}T=RRPS."""
    m = _US_TREASURY_PATTERN.match(symbol)
    if not m:
        return None
    tenor = m.group(1)
    return f"US{tenor}T=RRPS"


# --- Commodity Futures RIC ---

FUTURES_PYTH_TO_RIC: dict[str, str] = {
    "CC":    "HG",   # Copper (COMEX)
    "WTI":   "CL",   # WTI Crude Oil (NYMEX)
    "NGD":   "NG",   # Natural Gas (NYMEX)
    "AL":    "ALI",  # Aluminum (LME/COMEX)
    "PL":    "PA",   # Palladium (NYMEX)
    "PT":    "PL",   # Platinum (NYMEX)
    "UR":    "UX",   # Uranium (COMEX)
    "CO":    "C",    # Corn (CBOT)
    "BRENT": "LCO",  # Brent Crude (ICE)
    "NID":   "NK",   # Nikkei 225 (CME)
}

MONTH_CODES = "FGHJKMNQUVXZ"
_FUTURES_PATTERN = re.compile(
    r"^Commodities\.([A-Z]+)([FGHJKMNQUVXZ])(\d)/USD$"
)


def resolve_commodity_futures_ric(symbol: str) -> Optional[str]:
    """Derive RIC for a commodity futures contract."""
    m = _FUTURES_PATTERN.match(symbol)
    if not m:
        return None

    pyth_code = m.group(1)
    month = m.group(2)
    year_digit = m.group(3)

    ric_root = FUTURES_PYTH_TO_RIC.get(pyth_code)
    if not ric_root:
        return None

    year_2digit = f"2{year_digit}"
    return f"{ric_root}{month}{year_2digit}"


# --- Data Classes ---

@dataclass
class RICResult:
    """Result of RIC resolution for a single ticker."""
    ticker: str
    ric: str = ""
    source_type: str = "RIC"
    pyth_id: str = ""
    pythnet_id: str = ""
    pyth_lazer_id: Optional[int] = None
    valid_from: str = "1970-01-01 00:00:00"
    valid_to: str = ""
    display_ticker: str = ""
    asset_full_name: str = ""
    asset_class: str = ""
    confidence: str = ""  # "high", "medium", "low"
    warnings: list[str] = field(default_factory=list)


# --- Symbol Index ---

class SymbolIndex:
    """Index over lazer_symbols.json for fast ticker lookups."""

    def __init__(self, symbols_path: Path = DEFAULT_SYMBOLS_PATH) -> None:
        with open(symbols_path) as f:
            self._entries: list[dict] = json.load(f)

        # Build indexes
        self._by_name: dict[str, dict] = {}
        self._by_pyth_ticker: dict[str, dict] = {}
        self._by_id: dict[int, dict] = {}

        for entry in self._entries:
            name = entry.get("name", "").upper()
            if name:
                self._by_name[name] = entry

            # Extract ticker from symbol (e.g., "AAPL" from "Equity.US.AAPL/USD")
            symbol = entry.get("symbol", "")
            pyth_ticker = self._extract_ticker(symbol)
            if pyth_ticker and pyth_ticker not in self._by_pyth_ticker:
                self._by_pyth_ticker[pyth_ticker] = entry

            lazer_id = entry.get("pyth_lazer_id")
            if lazer_id is not None:
                self._by_id[lazer_id] = entry

    @staticmethod
    def _extract_ticker(symbol: str) -> Optional[str]:
        """Extract the ticker portion from a Pyth symbol string.

        Examples:
            Equity.US.AAPL/USD -> AAPL
            FX.EUR/USD -> EURUSD (not useful, name is better for FX)
            Commodities.CCH6/USD -> CCH6
            Rates.US10Y -> US10Y
            Metal.XAU/USD -> XAU
        """
        if not symbol:
            return None
        # Try pattern: *.TICKER/QUOTE or *.TICKER
        parts = symbol.rsplit(".", 1)
        if len(parts) < 2:
            return None
        after_dot = parts[1]
        # Remove /QUOTE suffix
        slash = after_dot.find("/")
        if slash > 0:
            ticker = after_dot[:slash]
        else:
            ticker = after_dot
        return ticker.upper() if ticker else None

    def lookup(self, ticker: str) -> Optional[dict]:
        """Look up a ticker by name or extracted symbol ticker."""
        upper = ticker.upper()
        entry = self._by_name.get(upper)
        if entry:
            return entry
        return self._by_pyth_ticker.get(upper)

    def lookup_by_id(self, lazer_id: int) -> Optional[dict]:
        """Look up by pyth_lazer_id."""
        return self._by_id.get(lazer_id)
