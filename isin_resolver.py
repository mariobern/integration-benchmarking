#!/usr/bin/env python3
"""
ISIN Resolver — Tiered ISIN resolution for US equities, ETFs, and ADRs.

Resolves ticker symbols to International Securities Identification Numbers (ISINs)
using a multi-tier strategy:

  Tier 1: FinanceDatabase (local, instant, 158K+ equities with ISINs)
  Tier 2: yfinance (per-ticker Yahoo Finance lookup, ~1-2s each)
  Tier 3: CUSIP computation via python-stdnum (if CUSIP known from Tier 1)

Results are cached in .isin_cache/isin_map.json with configurable TTL.

Usage:
    # Resolve tickers from command line
    python isin_resolver.py --tickers AAPL,MSFT,TSM,SPY

    # Resolve from a file
    python isin_resolver.py --ticker-file tickers.txt

    # Resolve all tickers from ric.csv
    python isin_resolver.py --ric-csv ric.csv

    # Skip yfinance (faster, offline)
    python isin_resolver.py --tickers AAPL,MSFT --no-yfinance

    # Force refresh (ignore cache)
    python isin_resolver.py --tickers AAPL --force-refresh

    # Output to CSV
    python isin_resolver.py --tickers AAPL,MSFT --output isins.csv
"""

import argparse
import csv
import json
import logging
import math
import sys
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# --- Constants ---

CACHE_DIR = Path(".isin_cache")
CACHE_FILE = CACHE_DIR / "isin_map.json"
CACHE_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days


# --- Data Classes ---


@dataclass(frozen=True)
class ISINResult:
    """Result of ISIN resolution for a single ticker."""

    ticker: str
    isin: Optional[str] = None
    cusip: Optional[str] = None
    source: str = ""  # "financedatabase", "yfinance", "cusip_computed", "cache"
    company_name: Optional[str] = None
    exchange: Optional[str] = None
    warnings: tuple[str, ...] = ()
    confidence: str = ""  # "high", "medium", "low" — based on resolution source

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "warnings": list(self.warnings)}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ISINResult":
        known = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in d.items() if k in known}
        filtered["warnings"] = tuple(filtered.get("warnings", []))
        return cls(**filtered)


# --- Cache ---


class ISINCache:
    """JSON file cache for ISIN lookups with TTL."""

    def __init__(self, cache_dir: Path = CACHE_DIR, ttl_seconds: int = CACHE_TTL_SECONDS):
        self.cache_dir = cache_dir
        self.cache_file = cache_dir / "isin_map.json"
        self.ttl_seconds = ttl_seconds
        self._data: dict[str, dict] = {}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        if self.cache_file.exists():
            try:
                raw = json.loads(self.cache_file.read_text())
                self._data = raw if isinstance(raw, dict) else {}
            except (json.JSONDecodeError, OSError):
                self._data = {}
        self._loaded = True

    def get(self, ticker: str) -> Optional[ISINResult]:
        self._load()
        entry = self._data.get(ticker.upper())
        if not entry:
            return None
        cached_at = entry.get("_cached_at", 0)
        if time.time() - cached_at > self.ttl_seconds:
            return None
        result_data = {k: v for k, v in entry.items() if k != "_cached_at"}
        result = ISINResult.from_dict(result_data)
        # Post-cache validation: evict ISINs with bad check digits
        if result.isin and not validate_isin(result.isin):
            logger.warning("Cached ISIN for %s failed validation, evicting", ticker)
            del self._data[ticker.upper()]
            return None
        return result

    def put(self, result: ISINResult) -> None:
        self._load()
        entry = result.to_dict()
        entry["_cached_at"] = time.time()
        self._data[result.ticker.upper()] = entry

    def save(self) -> None:
        self.cache_dir.mkdir(exist_ok=True)
        tmp = self.cache_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2))
        tmp.rename(self.cache_file)

    def clear(self) -> None:
        self._data = {}
        if self.cache_file.exists():
            self.cache_file.unlink()


# --- Helpers ---


def _clean_pandas_value(val: object) -> Optional[str]:
    """Convert a pandas cell value to str, treating NaN/None as None."""
    if val is None:
        return None
    if isinstance(val, float) and math.isnan(val):
        return None
    s = str(val)
    return s if s else None


# --- Country Mapping ---

# Map common FinanceDatabase country names to ISO 3166-1 alpha-2 codes
# Used for non-US CUSIP-to-ISIN conversion
_COUNTRY_TO_ISO: dict[str, str] = {
    "united states": "US",
    "canada": "CA",
    "united kingdom": "GB",
    "cayman islands": "KY",
    "bermuda": "BM",
    "ireland": "IE",
    "israel": "IL",
    "netherlands": "NL",
    "switzerland": "CH",
    "luxembourg": "LU",
    "japan": "JP",
    "china": "CN",
    "hong kong": "HK",
    "brazil": "BR",
    "mexico": "MX",
    "australia": "AU",
    "singapore": "SG",
    "south korea": "KR",
    "india": "IN",
    "germany": "DE",
    "france": "FR",
    "taiwan": "TW",
}


def _country_name_to_iso(country_name: str) -> str:
    """Convert a FinanceDatabase country name to ISO 3166-1 alpha-2 code.

    Returns 'US' if the country is not recognized.
    """
    if not country_name:
        return "US"
    return _COUNTRY_TO_ISO.get(country_name.strip().lower(), "US")


# --- Tier 1: FinanceDatabase ---


class FinanceDatabaseSource:
    """Bulk ISIN lookup from the FinanceDatabase package (158K+ equities)."""

    def __init__(self) -> None:
        self._equity_data: Optional[dict[str, dict]] = None
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return

        try:
            import financedatabase as fd
        except ImportError:
            logger.warning("financedatabase not installed, skipping Tier 1")
            self._equity_data = {}
            self._loaded = True
            return

        logger.info("Loading FinanceDatabase equities...")
        equities = fd.Equities()
        df = equities.select()

        self._equity_data = {}
        for symbol, row in df.iterrows():
            if not isinstance(symbol, str):
                continue
            isin = row.get("isin")
            cusip = row.get("cusip")
            name = row.get("name")
            country = row.get("country")
            exchange = row.get("exchange")

            # Only store if we have an ISIN or CUSIP
            isin_str = _clean_pandas_value(isin)
            cusip_str = _clean_pandas_value(cusip)
            if isin_str or cusip_str:
                self._equity_data[symbol.upper()] = {
                    "isin": isin_str,
                    "cusip": cusip_str,
                    "name": _clean_pandas_value(name),
                    "country": _clean_pandas_value(country),
                    "exchange": _clean_pandas_value(exchange),
                }

        logger.info("FinanceDatabase loaded: %d equities with ISIN/CUSIP", len(self._equity_data))
        self._loaded = True

    def resolve(self, ticker: str) -> Optional[ISINResult]:
        """Look up a ticker in FinanceDatabase. Returns ISINResult or None."""
        self._load()
        if self._equity_data is None:
            return None

        upper = ticker.upper()
        # Try direct match first
        entry = self._equity_data.get(upper)

        # Try Yahoo-style format (BRK.B -> BRK-B)
        if not entry and "." in upper:
            yahoo_form = upper.replace(".", "-")
            entry = self._equity_data.get(yahoo_form)

        if not entry:
            return None

        isin = entry.get("isin")
        cusip = entry.get("cusip")

        # If we have CUSIP but no ISIN, compute it using the correct country
        if cusip and not isin:
            country_iso = _country_name_to_iso(entry.get("country", ""))
            isin = _cusip_to_isin(cusip, country=country_iso)

        if not isin:
            return None

        return ISINResult(
            ticker=upper,
            isin=isin,
            cusip=cusip,
            source="financedatabase",
            company_name=entry.get("name"),
            exchange=entry.get("exchange"),
            confidence="high",
        )

    def resolve_batch(self, tickers: list[str]) -> dict[str, ISINResult]:
        """Batch resolve — loads DB once, then lookups are instant."""
        self._load()
        results = {}
        for ticker in tickers:
            result = self.resolve(ticker)
            if result:
                results[ticker.upper()] = result
        return results


# --- Tier 2: yfinance ---


class YFinanceSource:
    """Per-ticker ISIN lookup via Yahoo Finance."""

    def resolve(self, ticker: str) -> Optional[ISINResult]:
        """Look up ISIN for a ticker via yfinance. Returns ISINResult or None."""
        try:
            import yfinance as yf
        except ImportError:
            logger.warning("yfinance not installed, skipping Tier 2")
            return None

        upper = ticker.upper()
        # yfinance uses '-' for share class tickers
        yf_ticker = upper.replace(".", "-")

        try:
            t = yf.Ticker(yf_ticker)
            isin = t.isin
        except (ValueError, KeyError, AttributeError, ConnectionError, OSError) as e:
            logger.warning("yfinance lookup failed for %s: %s", ticker, e)
            return None

        # yfinance returns "-" when ISIN is not available
        if not isin or isin == "-":
            return None

        # Validate ISIN format (12 chars, starts with 2-letter country code)
        if not _validate_isin_format(isin):
            logger.warning("yfinance returned invalid ISIN for %s: %s", ticker, isin)
            return None

        # Extract CUSIP from US ISINs
        cusip = None
        if isin.startswith("US") and len(isin) == 12:
            cusip = isin[2:11]

        # Get company name from info if available
        name = None
        try:
            info = t.info
            name = info.get("longName") or info.get("shortName")
        except (AttributeError, KeyError, ConnectionError, OSError) as e:
            logger.debug("Could not fetch info for %s: %s", ticker, e)

        return ISINResult(
            ticker=upper,
            isin=isin,
            cusip=cusip,
            source="yfinance",
            company_name=name,
            confidence="medium",
        )


# --- ISIN Utilities ---


def _validate_isin_format(isin: str) -> bool:
    """Check if string looks like a valid ISIN (12 chars, alpha country prefix)."""
    if not isin or len(isin) != 12:
        return False
    if not isin[:2].isalpha():
        return False
    if not isin[2:].isalnum():
        return False
    return True


def _cusip_to_isin(cusip: str, country: str = "US") -> Optional[str]:
    """Convert CUSIP to ISIN using python-stdnum. Returns None on failure."""
    from stdnum.exceptions import ValidationError

    if country != "US":
        try:
            from stdnum.isin import from_natid
            return from_natid(country, cusip)
        except (ValueError, ValidationError):
            return None
    try:
        from stdnum.cusip import to_isin
        return to_isin(cusip)
    except (ValueError, ValidationError):
        return None


def validate_isin(isin: str) -> bool:
    """Validate an ISIN using python-stdnum's check digit algorithm."""
    from stdnum.exceptions import ValidationError

    try:
        from stdnum.isin import validate
        validate(isin)
        return True
    except (ValueError, ValidationError):
        return False


# --- Main Resolver ---


class ISINResolver:
    """Tiered ISIN resolution for US equities, ETFs, and ADRs.

    Tiers (in order):
      1. FinanceDatabase — bulk local DB (instant)
      2. yfinance — per-ticker Yahoo Finance (network, ~1-2s each)
      3. CUSIP computation — if CUSIP known but ISIN missing

    Results are cached in .isin_cache/isin_map.json.
    """

    def __init__(
        self,
        use_yfinance: bool = True,
        cache_dir: Path = CACHE_DIR,
        cache_ttl: int = CACHE_TTL_SECONDS,
    ):
        self.cache = ISINCache(cache_dir=cache_dir, ttl_seconds=cache_ttl)
        self.finance_db = FinanceDatabaseSource()
        self.yfinance = YFinanceSource() if use_yfinance else None

    def resolve(self, ticker: str) -> ISINResult:
        """Resolve a single ticker to its ISIN using tiered strategy."""
        upper = ticker.upper()
        warnings: list[str] = []

        # Check cache first
        cached = self.cache.get(upper)
        if cached:
            return cached

        # Tier 1: FinanceDatabase
        result = self.finance_db.resolve(upper)
        if result and result.isin:
            if validate_isin(result.isin):
                self.cache.put(result)
                return result
            warnings.append(
                f"FinanceDatabase ISIN {result.isin} failed validation"
            )

        # Tier 2: yfinance
        if self.yfinance:
            result = self.yfinance.resolve(upper)
            if result and result.isin:
                if validate_isin(result.isin):
                    self.cache.put(result)
                    return result
                warnings.append(
                    f"yfinance ISIN {result.isin} failed validation"
                )

        # Not resolved
        return ISINResult(
            ticker=upper,
            source="unresolved",
            warnings=tuple(warnings) if warnings else ("No ISIN found in any source",),
            confidence="low",
        )

    def resolve_batch(self, tickers: list[str]) -> dict[str, ISINResult]:
        """Resolve multiple tickers. Uses batch operations where possible."""
        results: dict[str, ISINResult] = {}
        remaining: list[str] = []
        per_ticker_warnings: dict[str, list[str]] = {}

        # Check cache for all tickers first
        for ticker in tickers:
            upper = ticker.upper()
            cached = self.cache.get(upper)
            if cached:
                results[upper] = cached
            else:
                remaining.append(upper)

        if not remaining:
            return results

        # Tier 1: FinanceDatabase batch
        logger.info("Tier 1: FinanceDatabase lookup for %d tickers...", len(remaining))
        fdb_results = self.finance_db.resolve_batch(remaining)
        for ticker, result in fdb_results.items():
            if result.isin and validate_isin(result.isin):
                results[ticker] = result
                self.cache.put(result)
            elif result.isin:
                per_ticker_warnings.setdefault(ticker, []).append(
                    f"FinanceDatabase ISIN {result.isin} failed validation"
                )

        still_remaining = [t for t in remaining if t not in results]

        # Tier 2: yfinance (sequential, per-ticker)
        if self.yfinance and still_remaining:
            logger.info("Tier 2: yfinance lookup for %d tickers...", len(still_remaining))
            for i, ticker in enumerate(still_remaining):
                if (i + 1) % 10 == 0:
                    logger.info("  yfinance progress: %d/%d", i + 1, len(still_remaining))
                result = self.yfinance.resolve(ticker)
                if result and result.isin and validate_isin(result.isin):
                    results[ticker] = result
                    self.cache.put(result)
                elif result and result.isin:
                    per_ticker_warnings.setdefault(ticker, []).append(
                        f"yfinance ISIN {result.isin} failed validation"
                    )

        # Mark unresolved
        for ticker in remaining:
            if ticker not in results:
                warnings = per_ticker_warnings.get(ticker, [])
                if not warnings:
                    warnings = ["No ISIN found in any source"]
                results[ticker] = ISINResult(
                    ticker=ticker,
                    source="unresolved",
                    warnings=tuple(warnings),
                    confidence="low",
                )

        return results

    def save_cache(self) -> None:
        """Persist the cache to disk."""
        self.cache.save()


# --- RIC CSV Parsing ---


def parse_tickers_from_ric_csv(path: Path) -> list[str]:
    """Extract unique tickers from a ric.csv file (strips exchange suffix).

    ric.csv contains RICs like "AAPL.O", "IBM.N". We extract the ticker
    portion (before the last dot) and deduplicate.
    """
    tickers: list[str] = []
    seen: set[str] = set()

    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ric = row.get("ric", "").strip().strip('"')
            if not ric:
                continue
            # Handle OTC tickers like GLCNF.PK
            if ric.endswith(".PK"):
                ticker = ric[:-3]
            elif ric.endswith(".TO"):
                ticker = ric[:-3]
            else:
                dot = ric.rfind(".")
                if dot > 0:
                    ticker = ric[:dot]
                else:
                    ticker = ric

            ticker = ticker.upper()
            if ticker not in seen:
                seen.add(ticker)
                tickers.append(ticker)

    return tickers


def parse_tickers_from_file(path: Path) -> list[str]:
    """Parse tickers from a text file (one per line, or CSV first column)."""
    tickers: list[str] = []
    seen: set[str] = set()

    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split(",")
            candidate = parts[0].strip().upper()
            if not candidate:
                continue
            if candidate.lower() in ("ticker", "symbol", "tickers", "symbols", "ric"):
                continue
            if candidate not in seen:
                seen.add(candidate)
                tickers.append(candidate)

    return tickers


def parse_tickers_from_string(ticker_string: str) -> list[str]:
    """Parse comma-separated tickers, dedup preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for t in ticker_string.split(","):
        t = t.strip().upper()
        if t and t not in seen:
            seen.add(t)
            result.append(t)
    return result


# --- Output ---


def write_csv_output(results: dict[str, ISINResult], output_path: Path) -> None:
    """Write ISIN results to CSV."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = ["ticker", "isin", "cusip", "source", "confidence", "company_name", "exchange", "warnings"]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for ticker in sorted(results.keys()):
            r = results[ticker]
            writer.writerow({
                "ticker": r.ticker,
                "isin": r.isin or "",
                "cusip": r.cusip or "",
                "source": r.source,
                "confidence": r.confidence,
                "company_name": r.company_name or "",
                "exchange": r.exchange or "",
                "warnings": "; ".join(r.warnings) if r.warnings else "",
            })

    print(f"Wrote {len(results)} results to {output_path}")


def print_summary(results: dict[str, ISINResult]) -> None:
    """Print resolution summary to console."""
    total = len(results)
    by_source: dict[str, int] = {}
    resolved = 0
    unresolved_tickers: list[str] = []

    for ticker, r in sorted(results.items()):
        by_source[r.source] = by_source.get(r.source, 0) + 1
        if r.isin:
            resolved += 1
        else:
            unresolved_tickers.append(ticker)

    print(f"\n{'='*60}")
    print("ISIN RESOLUTION SUMMARY")
    print(f"{'='*60}")
    print(f"Total tickers: {total}")
    if total:
        print(f"Resolved:      {resolved} ({resolved / total * 100:.1f}%)")
    else:
        print("Resolved:      0 (no tickers)")
    print(f"Unresolved:    {total - resolved}")
    print()
    print("By source:")
    for source, count in sorted(by_source.items(), key=lambda x: -x[1]):
        print(f"  {source}: {count}")

    if unresolved_tickers and len(unresolved_tickers) <= 20:
        print(f"\nUnresolved tickers ({len(unresolved_tickers)}):")
        for t in unresolved_tickers:
            print(f"  {t}")
    elif unresolved_tickers:
        print(f"\nUnresolved tickers: {len(unresolved_tickers)} (too many to list)")

    # ISIN country breakdown
    country_counts: dict[str, int] = {}
    for r in results.values():
        if r.isin:
            prefix = r.isin[:2]
            country_counts[prefix] = country_counts.get(prefix, 0) + 1
    if country_counts:
        print("\nISIN country prefixes:")
        for prefix, count in sorted(country_counts.items(), key=lambda x: -x[1]):
            print(f"  {prefix}: {count}")


# --- CLI ---


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resolve ticker symbols to ISINs using tiered strategy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python isin_resolver.py --tickers AAPL,MSFT,TSM,SPY
  python isin_resolver.py --ticker-file tickers.txt
  python isin_resolver.py --ric-csv ric.csv
  python isin_resolver.py --tickers AAPL,MSFT --no-yfinance
  python isin_resolver.py --tickers AAPL --force-refresh --output isins.csv
""",
    )

    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--tickers", type=str,
        help="Comma-separated ticker list (e.g., AAPL,MSFT,TSM)",
    )
    input_group.add_argument(
        "--ticker-file", type=Path,
        help="File with tickers (one per line or CSV first column)",
    )
    input_group.add_argument(
        "--ric-csv", type=Path,
        help="RIC CSV file (extracts tickers from RIC column, strips suffix)",
    )

    parser.add_argument(
        "--output", type=Path, default=None,
        help="Output CSV path (default: print to console only)",
    )
    parser.add_argument(
        "--no-yfinance", action="store_true",
        help="Skip yfinance lookups (faster, offline)",
    )
    parser.add_argument(
        "--force-refresh", action="store_true",
        help="Ignore cache, re-resolve all tickers",
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    # Parse input tickers
    if args.tickers:
        tickers = parse_tickers_from_string(args.tickers)
    elif args.ticker_file:
        if not args.ticker_file.exists():
            print(f"Error: File not found: {args.ticker_file}", file=sys.stderr)
            sys.exit(1)
        tickers = parse_tickers_from_file(args.ticker_file)
    else:
        if not args.ric_csv.exists():
            print(f"Error: File not found: {args.ric_csv}", file=sys.stderr)
            sys.exit(1)
        tickers = parse_tickers_from_ric_csv(args.ric_csv)

    if not tickers:
        print("Error: No tickers provided", file=sys.stderr)
        sys.exit(1)

    print(f"Resolving ISINs for {len(tickers)} tickers...")

    # Initialize resolver
    resolver = ISINResolver(use_yfinance=not args.no_yfinance)

    if args.force_refresh:
        resolver.cache.clear()

    # Resolve
    results = resolver.resolve_batch(tickers)
    resolver.save_cache()

    # Output
    print_summary(results)

    if args.output:
        write_csv_output(results, args.output)


if __name__ == "__main__":
    main()
