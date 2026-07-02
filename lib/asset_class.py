"""Asset-class categorization shared across publisher scripts.

Equities are categorized by ISO country code (3166-1 alpha-2) using the
``Equity.<CC>.`` Lazer prefix first, falling back to RIC-style symbol suffix;
all other asset types pass through unchanged.
"""

import json
from typing import Optional

from lib.symbol_utils import is_futures_symbol

# Symbol suffix to ISO country code mapping for equities
EQUITY_COUNTRY_MAP = {
    # US exchanges (typically no suffix, but some may have these)
    ".N": "us",  # NYSE
    ".OQ": "us",  # NASDAQ
    ".A": "us",  # AMEX
    # European exchanges
    ".L": "gb",  # London Stock Exchange
    ".PA": "fr",  # Euronext Paris
    ".DE": "de",  # Deutsche Börse (Xetra)
    ".AS": "nl",  # Euronext Amsterdam
    ".MI": "it",  # Borsa Italiana (Milan)
    ".MC": "es",  # Bolsa de Madrid
    ".SW": "ch",  # SIX Swiss Exchange
    ".BR": "be",  # Euronext Brussels
    ".VI": "at",  # Vienna Stock Exchange
    ".ST": "se",  # Nasdaq Stockholm
    ".HE": "fi",  # Nasdaq Helsinki
    ".CO": "dk",  # Nasdaq Copenhagen
    ".OL": "no",  # Oslo Stock Exchange
    ".LS": "pt",  # Euronext Lisbon
    ".IR": "ie",  # Euronext Dublin
    ".WA": "pl",  # Warsaw Stock Exchange
    # Asia-Pacific exchanges
    ".HK": "hk",  # Hong Kong Stock Exchange
    ".T": "jp",  # Tokyo Stock Exchange
    ".SS": "cn",  # Shanghai Stock Exchange
    ".SZ": "cn",  # Shenzhen Stock Exchange
    ".KS": "kr",  # Korea Stock Exchange
    ".KQ": "kr",  # KOSDAQ
    ".TW": "tw",  # Taiwan Stock Exchange
    ".SI": "sg",  # Singapore Exchange
    ".AX": "au",  # Australian Securities Exchange
    ".NZ": "nz",  # New Zealand Exchange
    ".BO": "in",  # Bombay Stock Exchange
    ".NS": "in",  # National Stock Exchange of India
    ".BK": "th",  # Stock Exchange of Thailand
    ".JK": "id",  # Indonesia Stock Exchange
    ".KL": "my",  # Bursa Malaysia
    # Other regions
    ".SA": "br",  # B3 (Brazil)
    ".MX": "mx",  # Mexican Stock Exchange
    ".J": "za",  # Johannesburg Stock Exchange
}


def get_equity_country(symbol: Optional[str]) -> str:
    """Determine the equity country code from the symbol.

    Parses the Lazer prefix ``Equity.<CC>.`` first (e.g. ``Equity.HK.0700/HKD``
    -> ``hk``); falls back to the RIC-style suffix map (e.g. ``VOD.L`` -> ``gb``);
    defaults to ``us`` for plain/unknown symbols.
    """
    if not symbol:
        return "us"  # Default to US if no symbol

    # Lazer symbols are formatted Equity.<CC>.<TICKER>/<CCY>; the country code
    # is the second dotted segment (e.g. Equity.HK.0700/HKD -> hk).
    parts = symbol.split(".")
    if len(parts) >= 3 and parts[0] == "Equity":
        return parts[1].lower()

    # Fall back to RIC-style suffixes (e.g. VOD.L -> gb) for non-prefixed symbols.
    for suffix, country in EQUITY_COUNTRY_MAP.items():
        if symbol.upper().endswith(suffix.upper()):
            return country

    # Plain symbols without prefix or known suffix are assumed US.
    return "us"


def categorize_asset_class(
    asset_type: str, symbol: Optional[str], instrument_type: Optional[str] = None
) -> str:
    """Categorize asset class, encoding equity instrument type when provided.

    For equities: ``perp`` -> ``equity-perp``; ``future`` ->
    ``equity-<country>-futures``; otherwise ``equity-<country>``. When
    ``instrument_type`` is None the result matches the prior country-only
    behavior. Non-equity assets return their ``asset_type`` unchanged.
    """
    if asset_type != "equity":
        return asset_type
    if instrument_type == "perp":
        return "equity-perp"
    country = get_equity_country(symbol)
    if instrument_type == "future":
        return f"equity-{country}-futures"
    return f"equity-{country}"


def parse_instrument_type(metadata_json: str) -> Optional[str]:
    """Return the ``instrument_type`` value from a feed's metadata JSON, or None.

    Metadata shape: {"items": [{"key": ..., "value": {"stringValue": ...}}, ...]}.
    """
    if not metadata_json:
        return None
    try:
        items = json.loads(metadata_json).get("items", [])
    except (json.JSONDecodeError, TypeError, AttributeError):
        return None
    for item in items:
        if not isinstance(item, dict):
            continue
        if item.get("key") == "instrument_type":
            value = item.get("value")
            return value.get("stringValue") if isinstance(value, dict) else None
    return None


def resolve_instrument_type(raw: Optional[str], symbol: str) -> str:
    """Resolve a feed's instrument type: metadata value if present, else heuristic."""
    if raw:
        return raw
    return "future" if is_futures_symbol(symbol) else "spot"
