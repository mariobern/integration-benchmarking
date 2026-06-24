"""Asset-class categorization shared across publisher scripts.

Equities are categorized by ISO country code (3166-1 alpha-2) based on
symbol suffix; all other asset types pass through unchanged.
"""

from typing import Optional

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
    """Determine equity country code from symbol suffix.

    Returns ISO country code (us, gb, hk, jp, etc.) or 'us' as default
    for plain symbols without suffix.
    """
    if not symbol:
        return "us"  # Default to US if no symbol

    # Check for known suffixes
    for suffix, country in EQUITY_COUNTRY_MAP.items():
        if symbol.upper().endswith(suffix.upper()):
            return country

    # Plain symbols without suffix are assumed to be US equities
    # (most common case for feeds like AAPL, MSFT, etc.)
    return "us"


def categorize_asset_class(asset_type: str, symbol: Optional[str]) -> str:
    """Categorize asset class, adding country suffix for equities.

    For equity assets, returns 'equity-{country}' based on symbol pattern.
    For other assets, returns the original asset_type.
    """
    if asset_type == "equity":
        country = get_equity_country(symbol)
        return f"equity-{country}"
    return asset_type
