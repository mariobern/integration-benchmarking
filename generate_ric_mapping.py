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

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# --- Constants ---

DEFAULT_SYMBOLS_PATH = Path("lazer_symbols.json")

# Asset types that have Datascope benchmarks (RIC-resolvable)
BENCHMARKABLE_ASSET_TYPES = {"equity", "fx", "metal", "commodity", "rates"}

# Asset types with no Datascope benchmark
NON_BENCHMARKABLE_ASSET_TYPES = {
    "crypto",
    "crypto-index",
    "crypto-redemption-rate",
    "funding-rate",
    "nav",
    "kalshi",
    "custom",
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
    "CC": "HG",  # Copper (COMEX)
    "WTI": "CL",  # WTI Crude Oil (NYMEX)
    "NGD": "NG",  # Natural Gas (NYMEX)
    "AL": "ALI",  # Aluminum (LME/COMEX)
    "PL": "PA",  # Palladium (NYMEX)
    "PT": "PL",  # Platinum (NYMEX)
    "UR": "UX",  # Uranium (COMEX)
    "CO": "C",  # Corn (CBOT)
    "BRENT": "LCO",  # Brent Crude (ICE)
    "NID": "NK",  # Nikkei 225 (CME)
    "NL": "MNI",  # Nickel (LME)
    "LE": "MPB",  # Lead (LME)
    "TI": "MSN",  # Tin (LME)
    "RS": "SB",  # Raw Sugar No. 11 (ICE US)
    "GO": "LGO",  # Low Sulphur Gasoil (ICE Europe)
}

_FUTURES_PATTERN = re.compile(r"^Commodities\.([A-Z]+)([FGHJKMNQUVXZ])(\d)/USD$")


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


# --- Equity Index Futures RIC ---

INDEX_FUTURES_PYTH_TO_RIC: dict[str, str] = {
    "EM": "ES",  # E-Mini S&P 500
    "NM": "NQ",  # Nasdaq Mini
    "DM": "YM",  # Dow Jones Mini
    "US500": "ES",  # S&P 500 E-mini (alias for EM)
    "US100": "NQ",  # Nasdaq 100 E-mini (alias for NM)
    "US30": "YM",  # Dow Jones E-mini (alias for DM)
}

_INDEX_FUTURES_PATTERN = re.compile(
    r"^Equity\.US\.([A-Z][A-Z0-9]*)([FGHJKMNQUVXZ])(\d)/USD$"
)


def resolve_equity_futures_ric(symbol: str) -> Optional[str]:
    """Derive RIC for an equity index futures contract.
    Returns None if the symbol is a regular equity (not a futures contract).
    """
    m = _INDEX_FUTURES_PATTERN.match(symbol)
    if not m:
        return None
    pyth_code = m.group(1)
    month = m.group(2)
    year_digit = m.group(3)
    ric_root = INDEX_FUTURES_PYTH_TO_RIC.get(pyth_code)
    if not ric_root:
        return None
    year_2digit = f"2{year_digit}"
    return f"{ric_root}{month}{year_2digit}"


# --- Equity RIC Resolver (NASDAQ Trader) ---

NASDAQ_TRADER_BASE_URL = "https://www.nasdaqtrader.com/dynamic/SymDir"
NASDAQ_LISTED_URL = f"{NASDAQ_TRADER_BASE_URL}/nasdaqlisted.txt"
OTHER_LISTED_URL = f"{NASDAQ_TRADER_BASE_URL}/otherlisted.txt"

EQUITY_CACHE_DIR = Path(".nasdaq_cache")
EQUITY_CACHE_TTL = 24 * 60 * 60  # 24 hours


def ticker_to_ric_base(ticker: str) -> str:
    """Convert dotted ticker to RIC base (BRK.B -> BRKb)."""
    upper = ticker.upper()
    if "." in upper:
        base, cls = upper.rsplit(".", 1)
        if len(cls) == 1 and cls.isalpha():
            return base + cls.lower()
    return upper


def _root_length(ticker: str) -> int:
    """Length of the base ticker before any class-letter suffix.

    A trailing `.X` or `-X` where X is a single alphabetic character is treated
    as a class-letter suffix and stripped before measuring. Other dotted suffixes
    (e.g. `.WS` for warrants) are preserved.

    Examples:
        IBM    -> 3
        TWTR   -> 4
        BRK.B  -> 3
        BRK-B  -> 3
        FOO.WS -> 6
    """
    upper = ticker.upper()
    if len(upper) >= 2 and upper[-2] in ".-" and upper[-1].isalpha():
        return len(upper) - 2
    return len(upper)


def _us_consolidated_suffix(root_len: int) -> str:
    """LSEG consolidated-tape suffix for NYSE / NYSE Arca / NYSE American / Cboe BZX.

    Returns ".K" when the ticker root has 4 or more characters; otherwise the
    consolidated RIC is bare (no suffix at all).
    """
    return ".K" if root_len >= 4 else ""


class EquityResolver:
    """Resolve US equity/ETF tickers to RICs using NASDAQ Trader."""

    def __init__(self, cache_dir: Path = EQUITY_CACHE_DIR, force_refresh: bool = False):
        self.cache_dir = cache_dir
        self.force_refresh = force_refresh
        self._nasdaq: dict[str, str] = {}
        self._other: dict[str, tuple[str, str]] = {}
        self._loaded = False

    def _load_from_files(self, nasdaq_path: Path, other_path: Path) -> None:
        """Load from already-downloaded files."""
        self._nasdaq = {}
        self._other = {}

        for line in nasdaq_path.read_text().strip().split("\n")[1:]:
            if line.startswith("File Creation Time"):
                continue
            parts = line.split("|")
            if len(parts) >= 2:
                symbol = parts[0].strip().upper()
                name = parts[1].strip()
                test = parts[3].strip() if len(parts) > 3 else "N"
                if test != "Y":
                    self._nasdaq[symbol] = name

        for line in other_path.read_text().strip().split("\n")[1:]:
            if line.startswith("File Creation Time"):
                continue
            parts = line.split("|")
            if len(parts) >= 3:
                symbol = parts[0].strip().upper()
                name = parts[1].strip()
                exchange = parts[2].strip()
                test = parts[5].strip() if len(parts) > 5 else "N"
                if test != "Y":
                    self._other[symbol] = (exchange, name)

        self._loaded = True

    def _ensure_loaded(self) -> None:
        """Download NASDAQ Trader files if needed, then parse."""
        if self._loaded:
            return
        import time
        import urllib.error
        import urllib.request

        self.cache_dir.mkdir(exist_ok=True)
        nasdaq_path = self.cache_dir / "nasdaqlisted.txt"
        other_path = self.cache_dir / "otherlisted.txt"

        for url, path in [
            (NASDAQ_LISTED_URL, nasdaq_path),
            (OTHER_LISTED_URL, other_path),
        ]:
            need_download = self.force_refresh or not path.exists()
            if not need_download:
                age = time.time() - path.stat().st_mtime
                need_download = age > EQUITY_CACHE_TTL
            if need_download:
                try:
                    req = urllib.request.Request(
                        url, headers={"User-Agent": "Mozilla/5.0"}
                    )
                    with urllib.request.urlopen(req, timeout=30) as resp:
                        path.write_text(resp.read().decode("utf-8"))
                except (urllib.error.URLError, OSError) as e:
                    if path.exists():
                        print(
                            f"Warning: Failed to refresh {path.name}, using cached: {e}",
                            file=sys.stderr,
                        )
                    else:
                        raise RuntimeError(
                            f"Cannot download {url} and no cached version exists: {e}"
                        ) from e

        self._load_from_files(nasdaq_path, other_path)

    def resolve(self, ticker: str) -> Optional[str]:
        """Resolve ticker to RIC.

        NASDAQ listings -> "<base>.O".
        IEX (`V`) listings -> "<base>.K".
        All other US-consolidated venues (NYSE `N`, NYSE Arca `P`,
        NYSE American `A`, Cboe BZX `Z`, unknown codes) -> LSEG consolidated
        rule: "<base>.K" when the ticker root is 4+ characters, otherwise the
        bare base with no suffix at all (e.g. "IBM", "SPY", "BRKa").
        """
        self._ensure_loaded()
        upper = ticker.upper()
        ric_base = ticker_to_ric_base(upper)
        root_len = _root_length(upper)

        for form in [upper, ric_base]:
            if form in self._nasdaq:
                return f"{ric_base}.O"
            if form in self._other:
                exchange, _ = self._other[form]
                if exchange == "V":
                    return f"{ric_base}.K"
                return f"{ric_base}{_us_consolidated_suffix(root_len)}"
        return None

    def get_name(self, ticker: str) -> Optional[str]:
        """Get company name for a ticker."""
        self._ensure_loaded()
        upper = ticker.upper()
        for form in [upper, ticker_to_ric_base(upper)]:
            if form in self._nasdaq:
                return self._nasdaq[form]
            if form in self._other:
                return self._other[form][1]
        return None


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
            symbol = entry.get("symbol", "")
            asset_type = entry.get("asset_type", "")

            if name:
                existing = self._by_name.get(name)
                if existing is None:
                    self._by_name[name] = entry
                else:
                    # Prefer benchmarkable over non-benchmarkable
                    existing_type = existing.get("asset_type", "")
                    existing_symbol = existing.get("symbol", "")
                    is_benchmarkable = asset_type in BENCHMARKABLE_ASSET_TYPES
                    existing_benchmarkable = existing_type in BENCHMARKABLE_ASSET_TYPES
                    # Prefer non-EXT over EXT symbols
                    is_ext = ".EXT" in symbol
                    existing_ext = ".EXT" in existing_symbol
                    # Prefer US equities over non-US (most users want US)
                    is_us = "Equity.US." in symbol
                    existing_us = "Equity.US." in existing_symbol
                    if (
                        (is_benchmarkable and not existing_benchmarkable)
                        or (is_us and not existing_us)
                        or (
                            existing_ext
                            and not is_ext
                            and is_benchmarkable == existing_benchmarkable
                        )
                    ):
                        self._by_name[name] = entry

            # Extract ticker from symbol (e.g., "AAPL" from "Equity.US.AAPL/USD")
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


# --- Asset Class Classification ---

ADR_KEYWORDS = [
    "american depositary",
    "depositary shares",
    "depositary receipts",
    " adr",
    " ads",
]


def _classify_equity(description: str) -> str:
    """Classify equity as Common Stock, ADR, Equity (ETF), etc."""
    lower = description.lower()
    for kw in ADR_KEYWORDS:
        if kw in lower:
            return "American Depositary Shares"
    if "etf" in lower or "fund" in lower or "trust" in lower:
        return "Equity"
    if "class a " in lower:
        return "Class A Common Stock"
    if "class b " in lower:
        return "Class B Common Stock"
    if "class c " in lower:
        return "Class C Common Stock"
    if "preferred" in lower:
        return "Preferred Share"
    if "ordinary" in lower:
        return "Ordinary Shares"
    return "Common Stock"


def _derive_pyth_id(entry: dict) -> str:
    """Derive pyth_id from lazer_symbols entry."""
    asset_type = entry.get("asset_type", "")
    symbol = entry.get("symbol", "")
    name = entry.get("name", "").lower()

    if asset_type == "fx":
        return f"fx.{name}"
    elif asset_type == "metal":
        return f"metal.{name}"
    elif asset_type == "rates":
        return f"rates.{name}"
    elif asset_type == "commodity":
        return f"future.{name}"
    elif asset_type == "equity":
        if _INDEX_FUTURES_PATTERN.match(symbol):
            return f"future.{name}"
        return f"equity.{name}"
    return f"{asset_type}.{name}"


# --- Main Resolver ---


class RICResolver:
    """Orchestrates RIC resolution across all asset classes."""

    def __init__(
        self,
        symbols_path: Path = DEFAULT_SYMBOLS_PATH,
        equity_cache_dir: Path = EQUITY_CACHE_DIR,
        force_refresh: bool = False,
    ):
        self._index = SymbolIndex(symbols_path)
        self._equity = EquityResolver(
            cache_dir=equity_cache_dir, force_refresh=force_refresh
        )

    def resolve(self, ticker: str) -> RICResult:
        """Resolve a ticker to its Datascope RIC."""
        entry = self._index.lookup(ticker)
        if not entry:
            return RICResult(
                ticker=ticker,
                warnings=[f"Ticker '{ticker}' not found in lazer_symbols.json"],
            )

        asset_type = entry.get("asset_type", "")
        symbol = entry.get("symbol", "")
        description = entry.get("description", "")

        # Skip non-benchmarkable assets
        if asset_type in NON_BENCHMARKABLE_ASSET_TYPES:
            return RICResult(
                ticker=ticker,
                pyth_lazer_id=entry.get("pyth_lazer_id"),
                pythnet_id=symbol,
                warnings=[f"Asset type '{asset_type}' has no Datascope benchmark"],
            )

        result = RICResult(
            ticker=ticker,
            pyth_lazer_id=entry.get("pyth_lazer_id"),
            pythnet_id=symbol,
            pyth_id=_derive_pyth_id(entry),
            display_ticker=entry.get("name", ticker),
            asset_full_name=description,
            valid_from="1970-01-01 00:00:00",
        )

        # Dispatch to asset-class resolver
        if asset_type == "fx":
            result.ric = resolve_fx_ric(symbol) or ""
            result.asset_class = "Forex"
            result.confidence = "high" if result.ric else "low"

        elif asset_type == "metal":
            result.ric = resolve_metal_ric(symbol) or ""
            result.asset_class = "Metal"
            result.confidence = "high" if result.ric else "low"

        elif asset_type == "rates":
            result.ric = resolve_rates_ric(symbol) or ""
            result.asset_class = "Rates"
            result.confidence = "high" if result.ric else "low"

        elif asset_type == "commodity":
            result.ric = resolve_commodity_futures_ric(symbol) or ""
            result.asset_class = "Commodity Future"
            result.confidence = "high" if result.ric else "low"

        elif asset_type == "equity":
            futures_ric = resolve_equity_futures_ric(symbol)
            if futures_ric:
                result.ric = futures_ric
                result.asset_class = "Equity Future"
                result.confidence = "high"
            elif symbol.startswith("Equity.US."):
                # Use the name field as the canonical ticker (handles BRK.B vs BRK-B)
                equity_ticker = entry.get("name", "")
                if not equity_ticker:
                    # Fallback: extract from symbol
                    equity_ticker = symbol.replace("Equity.US.", "").replace("/USD", "")
                    equity_ticker = equity_ticker.replace(".EXT", "")
                result.ric = self._equity.resolve(equity_ticker) or ""
                result.asset_class = _classify_equity(description)
                result.display_ticker = equity_ticker
                if result.ric:
                    result.confidence = "medium"
                else:
                    ric_base = ticker_to_ric_base(equity_ticker)
                    suffix = _us_consolidated_suffix(_root_length(equity_ticker))
                    result.ric = f"{ric_base}{suffix}"
                    result.confidence = "low"
                    result.warnings.append(
                        f"Defaulting to {result.ric} — verify exchange suffix"
                    )
            else:
                result.warnings.append(
                    f"Non-US equity '{symbol}' — RIC resolution not supported"
                )
                result.confidence = "low"

        if not result.ric and not result.warnings:
            result.warnings.append(f"Could not derive RIC for {symbol}")

        return result

    def resolve_batch(self, tickers: list[str]) -> list[RICResult]:
        """Resolve multiple tickers."""
        return [self.resolve(t) for t in tickers]


# --- CSV Output ---

CSV_COLUMNS = [
    "source_value",
    "source_type",
    "pyth_id",
    "pythnet_id",
    "pyth_lazer_id",
    "valid_from",
    "valid_to",
    "ticker",
    "asset_full_name",
    "asset_class",
]


def _result_to_row(r: RICResult) -> dict:
    """Convert a RICResult to a CSV row dict."""
    return {
        "source_value": r.ric,
        "source_type": r.source_type,
        "pyth_id": r.pyth_id,
        "pythnet_id": r.pythnet_id,
        "pyth_lazer_id": r.pyth_lazer_id or "",
        "valid_from": r.valid_from,
        "valid_to": r.valid_to,
        "ticker": r.display_ticker,
        "asset_full_name": r.asset_full_name,
        "asset_class": r.asset_class,
    }


def write_csv(
    results: list[RICResult], output_path: Path, append: bool = False
) -> None:
    """Write results in pyth_mappings_export CSV format."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    valid = [r for r in results if r.ric]
    mode = "a" if append else "w"
    with open(output_path, mode, newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        if not append:
            writer.writeheader()
        for r in valid:
            writer.writerow(_result_to_row(r))
    action = "Appended" if append else "Wrote"
    print(f"{action} {len(valid)} rows to {output_path}")
    if len(valid) < len(results):
        skipped = len(results) - len(valid)
        print(f"Skipped {skipped} tickers (no RIC resolved)")


# --- Summary ---


def print_summary(results: list[RICResult]) -> None:
    """Print resolution summary to console."""
    total = len(results)
    resolved = sum(1 for r in results if r.ric)
    by_class: dict[str, int] = {}
    by_confidence: dict[str, int] = {}
    warnings_list: list[str] = []

    for r in results:
        if r.ric:
            by_class[r.asset_class] = by_class.get(r.asset_class, 0) + 1
        by_confidence[r.confidence] = by_confidence.get(r.confidence, 0) + 1
        for w in r.warnings:
            warnings_list.append(f"  {r.ticker}: {w}")

    print(f"\n{'='*60}")
    print("RIC MAPPING SUMMARY")
    print(f"{'='*60}")
    print(f"Total tickers:  {total}")
    print(f"Resolved:       {resolved}")
    print(f"Unresolved:     {total - resolved}")
    print()
    if by_class:
        print("By asset class:")
        for cls, cnt in sorted(by_class.items()):
            print(f"  {cls}: {cnt}")
    print()
    print("Confidence:")
    for level in ["high", "medium", "low"]:
        cnt = by_confidence.get(level, 0)
        if cnt:
            print(f"  {level}: {cnt}")
    if warnings_list:
        print(f"\nWarnings ({len(warnings_list)}):")
        for w in warnings_list:
            print(w)


# --- CLI ---


def parse_tickers_from_file(path: Path) -> list[str]:
    """Parse tickers from file (one per line, or CSV first column)."""
    tickers: list[str] = []
    seen: set[str] = set()
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            candidate = line.split(",")[0].strip()
            if candidate.lower() in ("ticker", "symbol"):
                continue
            if candidate and candidate not in seen:
                seen.add(candidate)
                tickers.append(candidate)
    return tickers


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate RIC mappings for Pyth Lazer tickers (all asset classes)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python generate_ric_mapping.py --ticker AAPL
  python generate_ric_mapping.py --ticker AAPL AUDCAD CCH6 XAU US10Y
  python generate_ric_mapping.py --ticker-file new_tickers.txt
  python generate_ric_mapping.py --ticker AAPL --output my_mappings.csv
  python generate_ric_mapping.py --ticker AAPL --symbols after.json
""",
    )

    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument("--ticker", nargs="+", help="Ticker(s) to resolve")
    input_group.add_argument("--ticker-file", type=Path, help="File with tickers")

    parser.add_argument(
        "--output",
        type=Path,
        default=Path("ric_mappings.csv"),
        help="Output CSV path (default: ric_mappings.csv)",
    )
    parser.add_argument(
        "--symbols",
        type=Path,
        default=DEFAULT_SYMBOLS_PATH,
        help="Path to lazer_symbols.json",
    )
    parser.add_argument(
        "--force-refresh", action="store_true", help="Re-download NASDAQ Trader data"
    )
    parser.add_argument(
        "--append-to",
        type=Path,
        default=None,
        help="Append to existing CSV instead of creating new",
    )

    args = parser.parse_args()

    if not args.symbols.exists():
        print(f"Error: {args.symbols} not found", file=sys.stderr)
        sys.exit(1)

    if args.ticker:
        tickers = args.ticker
    else:
        if not args.ticker_file.exists():
            print(f"Error: {args.ticker_file} not found", file=sys.stderr)
            sys.exit(1)
        tickers = parse_tickers_from_file(args.ticker_file)

    if not tickers:
        print("Error: No tickers provided", file=sys.stderr)
        sys.exit(1)

    print(f"Resolving RICs for {len(tickers)} ticker(s)...")
    resolver = RICResolver(
        symbols_path=args.symbols,
        force_refresh=args.force_refresh,
    )

    results = resolver.resolve_batch(tickers)
    print_summary(results)

    output_path = args.append_to or args.output
    append = args.append_to is not None and args.append_to.exists()
    write_csv(results, output_path, append=append)


if __name__ == "__main__":
    main()
