#!/usr/bin/env python3
"""
ISIN Resolver v2 — Enhanced tiered ISIN resolution with OpenFIGI and ADR correction.

Resolves ticker symbols to International Securities Identification Numbers (ISINs)
using a multi-tier strategy:

  Tier 0:   Manual Override (authoritative ISINs from local CSV file)
  Tier 1:   FinanceDatabase (local, instant, 158K+ equities with ISINs)
  Tier 2:   yfinance (per-ticker Yahoo Finance lookup, ~1-2s each)
  Tier 3:   CUSIP computation via python-stdnum (if CUSIP known from Tier 1)

OpenFIGI is used for ADR detection only (free tier does not return CUSIPs/ISINs).

Enhancements over v1:
  - Accepts enriched input (ticker + company_name + denomination_currency)
  - Manual override file for authoritative ISINs (ADR corrections, known gaps)
  - OpenFIGI API for ADR detection confirmation
  - ADR detection: corrects foreign ISINs to US ADR ISINs via manual overrides
  - Currency-based ISIN validation catches misassigned ISINs

Results are cached in .isin_cache/isin_map_v2.json with configurable TTL.

Usage:
    # Resolve tickers (backward compatible)
    python isin_resolver_v2.py --tickers AAPL,MSFT,TSM,SPY

    # Enriched CSV with company name + currency
    python isin_resolver_v2.py --enriched-csv tickers_enriched.csv

    # Skip yfinance / OpenFIGI
    python isin_resolver_v2.py --tickers AAPL,MSFT --no-yfinance --no-openfigi

    # Force refresh (ignore cache)
    python isin_resolver_v2.py --tickers AAPL --force-refresh

    # Output to CSV
    python isin_resolver_v2.py --tickers AAPL,MSFT --output isins.csv
"""

import argparse
import csv
import json
import logging
import math
import os
import sys
import time
from dataclasses import asdict, dataclass, fields
from pathlib import Path
from typing import Any, Optional, Union

logger = logging.getLogger(__name__)

# --- Constants ---

CACHE_DIR = Path(".isin_cache")
CACHE_FILE_V2 = CACHE_DIR / "isin_map_v2.json"
CACHE_TTL_SECONDS = 7 * 24 * 60 * 60  # 7 days

OPENFIGI_BASE_URL = "https://api.openfigi.com/v3/mapping"
OPENFIGI_BATCH_SIZE = 100  # max jobs per request


# --- Data Classes ---


@dataclass(frozen=True)
class TickerInput:
    """Enriched input for ISIN resolution."""

    ticker: str
    company_name: Optional[str] = None
    denomination_currency: Optional[str] = None


@dataclass(frozen=True)
class ISINResult:
    """Result of ISIN resolution for a single ticker."""

    ticker: str
    isin: Optional[str] = None
    cusip: Optional[str] = None
    source: str = ""  # "financedatabase", "openfigi", "yfinance", "cusip_computed", "cache"
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

    def __init__(
        self,
        cache_dir: Path = CACHE_DIR,
        ttl_seconds: int = CACHE_TTL_SECONDS,
        cache_filename: str = "isin_map_v2.json",
    ):
        self.cache_dir = cache_dir
        self.cache_file = cache_dir / cache_filename
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


def _normalize_input(ticker: Union[str, TickerInput]) -> TickerInput:
    """Normalize a str or TickerInput to TickerInput."""
    if isinstance(ticker, TickerInput):
        return TickerInput(
            ticker=ticker.ticker.upper(),
            company_name=ticker.company_name,
            denomination_currency=ticker.denomination_currency,
        )
    return TickerInput(ticker=ticker.upper())


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


# --- Tier 0: Manual Override ---


OVERRIDE_DIR = Path(".isin_overrides")
OVERRIDE_FILE = OVERRIDE_DIR / "isin_overrides.csv"


class ManualOverrideSource:
    """ISIN overrides from a local CSV file.

    Provides authoritative ISINs for tickers that fail automatic resolution
    or need ADR correction. CSV format: ticker,isin,cusip,company_name

    This is intended as a bridge until Datascope DSS API integration (Phase 2).
    """

    def __init__(self, override_file: Path = OVERRIDE_FILE):
        self._file = override_file
        self._data: Optional[dict[str, dict]] = None
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return
        self._data = {}
        if self._file.exists():
            try:
                with open(self._file, encoding="utf-8-sig") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        ticker = row.get("ticker", "").strip().upper()
                        isin = row.get("isin", "").strip()
                        if ticker and isin:
                            self._data[ticker] = {
                                "isin": isin,
                                "cusip": row.get("cusip", "").strip() or None,
                                "company_name": row.get("company_name", "").strip() or None,
                            }
                logger.info("Manual overrides loaded: %d entries from %s", len(self._data), self._file)
            except (OSError, csv.Error) as e:
                logger.warning("Failed to load override file %s: %s", self._file, e)
        self._loaded = True

    def resolve(self, ticker: str) -> Optional[ISINResult]:
        """Look up a ticker in the manual override file."""
        self._load()
        if not self._data:
            return None

        entry = self._data.get(ticker.upper())
        if not entry:
            return None

        isin = entry["isin"]
        if not _validate_isin_format(isin) or not validate_isin(isin):
            logger.warning("Override ISIN for %s failed validation: %s", ticker, isin)
            return None

        return ISINResult(
            ticker=ticker.upper(),
            isin=isin,
            cusip=entry.get("cusip"),
            source="manual_override",
            company_name=entry.get("company_name"),
            confidence="high",
        )

    def resolve_batch(self, tickers: list[str]) -> dict[str, ISINResult]:
        """Batch resolve from overrides."""
        self._load()
        results = {}
        for ticker in tickers:
            result = self.resolve(ticker)
            if result:
                results[ticker.upper()] = result
        return results


# --- Tier 1.5: OpenFIGI (ADR Detection + Ticker Validation) ---


@dataclass(frozen=True)
class OpenFIGIInfo:
    """Metadata from OpenFIGI for a ticker (not ISIN resolution)."""

    ticker: str
    figi: Optional[str] = None
    composite_figi: Optional[str] = None
    share_class_figi: Optional[str] = None
    name: Optional[str] = None
    security_type: Optional[str] = None  # "Common Stock", "ADR", "ETP", etc.
    security_type2: Optional[str] = None  # "Depositary Receipt", "Mutual Fund", etc.
    is_adr: bool = False


class OpenFIGISource:
    """ADR detection and ticker validation via OpenFIGI API.

    OpenFIGI's free tier provides:
    - ADR detection (securityType = "ADR", securityType2 = "Depositary Receipt")
    - Company name validation
    - Ticker existence confirmation
    - FIGI identifiers (useful for future integrations)

    Note: The free tier does NOT return CUSIPs or ISINs. For ISIN resolution,
    use FinanceDatabase, yfinance, or the manual override file.
    """

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("OPENFIGI_API_KEY")
        self._rate_limit = 250 if self.api_key else 25  # requests per minute

    def _make_request(self, jobs: list[dict]) -> list:
        """Send a batch request to OpenFIGI. Returns list of result dicts."""
        import httpx

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["X-OPENFIGI-APIKEY"] = self.api_key

        try:
            response = httpx.post(
                OPENFIGI_BASE_URL,
                json=jobs,
                headers=headers,
                timeout=30.0,
            )
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, httpx.TimeoutException, ValueError) as e:
            logger.warning("OpenFIGI request failed: %s", e)
            return [None] * len(jobs)

    def lookup(self, ticker: str, exch_code: Optional[str] = "US") -> Optional[OpenFIGIInfo]:
        """Look up ticker metadata via OpenFIGI. Returns OpenFIGIInfo or None."""
        job: dict[str, str] = {"idType": "TICKER", "idValue": ticker.upper()}
        if exch_code:
            job["exchCode"] = exch_code

        results = self._make_request([job])
        if not results or results[0] is None:
            return None

        entry = results[0]
        if isinstance(entry, dict) and "error" in entry:
            return None

        data = entry.get("data", []) if isinstance(entry, dict) else entry if isinstance(entry, list) else []
        if not data:
            return None

        # Find best match (prefer Common Stock / ADR / ETP)
        preferred_types = {"Common Stock", "ADR", "Depositary Receipt", "Open-End Fund", "ETP"}
        best_item = None
        for item in data:
            if item.get("securityType", "") in preferred_types:
                best_item = item
                break
        if not best_item:
            best_item = data[0]

        sec_type = best_item.get("securityType", "")
        sec_type2 = best_item.get("securityType2", "")
        is_adr = (
            sec_type in ("ADR",)
            or sec_type2 in ("Depositary Receipt",)
            or "ADR" in best_item.get("name", "").upper()
            or "DEPOSITARY" in best_item.get("name", "").upper()
        )

        return OpenFIGIInfo(
            ticker=ticker.upper(),
            figi=best_item.get("figi"),
            composite_figi=best_item.get("compositeFIGI"),
            share_class_figi=best_item.get("shareClassFIGI"),
            name=best_item.get("name"),
            security_type=sec_type or None,
            security_type2=sec_type2 or None,
            is_adr=is_adr,
        )

    def lookup_batch(
        self, tickers: list[str], exch_code: Optional[str] = "US"
    ) -> dict[str, OpenFIGIInfo]:
        """Batch lookup metadata for multiple tickers."""
        results: dict[str, OpenFIGIInfo] = {}
        ticker_list = [t.upper() for t in tickers]

        for i in range(0, len(ticker_list), OPENFIGI_BATCH_SIZE):
            batch = ticker_list[i : i + OPENFIGI_BATCH_SIZE]
            jobs = []
            for ticker in batch:
                job: dict[str, str] = {"idType": "TICKER", "idValue": ticker}
                if exch_code:
                    job["exchCode"] = exch_code
                jobs.append(job)

            api_results = self._make_request(jobs)

            for ticker, entry in zip(batch, api_results):
                if entry is None:
                    continue
                if isinstance(entry, dict) and "error" in entry:
                    continue

                data = entry.get("data", []) if isinstance(entry, dict) else entry if isinstance(entry, list) else []
                if not data:
                    continue

                preferred_types = {"Common Stock", "ADR", "Depositary Receipt", "Open-End Fund", "ETP"}
                best_item = None
                for item in data:
                    if item.get("securityType", "") in preferred_types:
                        best_item = item
                        break
                if not best_item:
                    best_item = data[0]

                sec_type = best_item.get("securityType", "")
                sec_type2 = best_item.get("securityType2", "")
                is_adr = (
                    sec_type in ("ADR",)
                    or sec_type2 in ("Depositary Receipt",)
                    or "ADR" in best_item.get("name", "").upper()
                    or "DEPOSITARY" in best_item.get("name", "").upper()
                )

                results[ticker] = OpenFIGIInfo(
                    ticker=ticker,
                    figi=best_item.get("figi"),
                    composite_figi=best_item.get("compositeFIGI"),
                    share_class_figi=best_item.get("shareClassFIGI"),
                    name=best_item.get("name"),
                    security_type=sec_type or None,
                    security_type2=sec_type2 or None,
                    is_adr=is_adr,
                )

            if i + OPENFIGI_BATCH_SIZE < len(ticker_list):
                time.sleep(0.5)

        return results

    def is_adr(self, ticker: str) -> bool:
        """Check if a ticker is an ADR. Convenience method."""
        info = self.lookup(ticker)
        return info.is_adr if info else False


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


# --- ADR / Currency Validation ---


def _check_adr_correction_needed(
    result: ISINResult, ticker_input: TickerInput
) -> bool:
    """Check if an ISIN result needs ADR correction.

    Returns True if:
    - denomination_currency is USD
    - The resolved ISIN has a non-US prefix
    """
    if not ticker_input.denomination_currency:
        return False
    if ticker_input.denomination_currency.upper() != "USD":
        return False
    if not result.isin:
        return False
    return not result.isin.startswith("US")


def _validate_currency_consistency(
    result: ISINResult, ticker_input: TickerInput
) -> ISINResult:
    """Post-resolution check: flag ISINs inconsistent with denomination currency.

    For USD-denominated securities, certain ISIN prefixes are suspicious
    (e.g., IN for India, AR for Argentina) and likely indicate wrong data.
    """
    if not ticker_input.denomination_currency or not result.isin:
        return result

    currency = ticker_input.denomination_currency.upper()
    isin_prefix = result.isin[:2]

    if currency == "USD" and isin_prefix not in {
        "US",  # US domestic
        "KY",  # Cayman (SPACs, Chinese ADRs)
        "CA",  # Canadian cross-listings
        "BM",  # Bermuda redomiciles
        "JE",  # Jersey (Ferguson)
        "LU",  # Luxembourg (Spotify)
        "GB",  # UK (AstraZeneca)
        "DE",  # Germany (SAP)
        "IE",  # Ireland (Flutter, Accenture)
        "IL",  # Israel (Wix)
        "NO",  # Norway (EchoStar — but check specific cases)
        "PL",  # Poland (Flutter alt)
    }:
        new_warnings = result.warnings + (
            f"ISIN prefix {isin_prefix} unexpected for USD denomination — "
            f"may be wrong security",
        )
        return ISINResult(
            ticker=result.ticker,
            isin=result.isin,
            cusip=result.cusip,
            source=result.source,
            company_name=result.company_name,
            exchange=result.exchange,
            warnings=new_warnings,
            confidence="low",
        )
    return result


# --- Main Resolver ---


class ISINResolver:
    """Enhanced tiered ISIN resolution with ADR detection and manual overrides.

    Tiers (in order):
      0.   Manual Override — authoritative ISINs from local CSV file
      1.   FinanceDatabase — bulk local DB (instant)
      2.   yfinance — per-ticker Yahoo Finance (network, ~1-2s each)
      3.   CUSIP computation — if CUSIP known but ISIN missing

    OpenFIGI is used for ADR detection only (free tier does not return CUSIPs/ISINs).

    When denomination_currency is provided:
      - Detects ADR misassignment (foreign ISIN for USD security)
      - Checks manual overrides for correct US ADR ISIN
      - Uses OpenFIGI to confirm ADR status
      - Validates ISIN prefix consistency with currency

    Results are cached in .isin_cache/isin_map_v2.json.
    """

    def __init__(
        self,
        use_yfinance: bool = True,
        use_openfigi: bool = True,
        openfigi_api_key: Optional[str] = None,
        cache_dir: Path = CACHE_DIR,
        cache_ttl: int = CACHE_TTL_SECONDS,
        override_file: Path = OVERRIDE_FILE,
    ):
        self.manual_override = ManualOverrideSource(override_file=override_file)
        self.cache = ISINCache(cache_dir=cache_dir, ttl_seconds=cache_ttl)
        self.finance_db = FinanceDatabaseSource()
        self.openfigi = OpenFIGISource(api_key=openfigi_api_key) if use_openfigi else None
        self.yfinance = YFinanceSource() if use_yfinance else None

    def resolve(self, ticker: Union[str, TickerInput]) -> ISINResult:
        """Resolve a single ticker to its ISIN using tiered strategy.

        Accepts either a plain str (backward compatible) or a TickerInput
        with enriched metadata for ADR correction.
        """
        ticker_input = _normalize_input(ticker)
        upper = ticker_input.ticker
        warnings: list[str] = []

        # Tier 0: Manual Override (highest priority, authoritative)
        override = self.manual_override.resolve(upper)
        if override:
            self.cache.put(override)
            return override

        # Check cache
        cached = self.cache.get(upper)
        if cached:
            # Even cached results get ADR correction if currency is provided
            if _check_adr_correction_needed(cached, ticker_input):
                corrected = self._try_adr_correction(cached, ticker_input)
                if corrected:
                    return corrected
            return cached

        # Tier 1: FinanceDatabase
        result = self.finance_db.resolve(upper)
        if result and result.isin:
            if validate_isin(result.isin):
                # Check if ADR correction is needed before caching
                if _check_adr_correction_needed(result, ticker_input):
                    corrected = self._try_adr_correction(result, ticker_input)
                    if corrected:
                        self.cache.put(corrected)
                        return corrected
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
                    # Check ADR correction for yfinance results too
                    if _check_adr_correction_needed(result, ticker_input):
                        corrected = self._try_adr_correction(result, ticker_input)
                        if corrected:
                            self.cache.put(corrected)
                            return corrected
                    # Apply currency validation
                    validated = _validate_currency_consistency(result, ticker_input)
                    self.cache.put(validated)
                    return validated
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

    def _try_adr_correction(
        self, original: ISINResult, ticker_input: TickerInput
    ) -> Optional[ISINResult]:
        """Attempt to correct a foreign ISIN to US ADR ISIN.

        Called when denomination_currency="USD" and the resolved ISIN is non-US.
        Checks manual overrides for the correct US ADR ISIN, and optionally
        uses OpenFIGI to confirm ADR status.
        """
        logger.info(
            "ADR correction: %s has non-US ISIN %s with USD denomination, "
            "checking manual overrides...",
            ticker_input.ticker,
            original.isin,
        )

        # Check manual overrides for the correct US ADR ISIN
        override = self.manual_override.resolve(ticker_input.ticker)
        if override and override.isin and override.isin.startswith("US"):
            return ISINResult(
                ticker=original.ticker,
                isin=override.isin,
                cusip=override.cusip,
                source="manual_override",
                company_name=override.company_name or original.company_name,
                exchange=original.exchange,
                warnings=original.warnings + (
                    f"ADR corrected: replaced {original.isin} ({original.source}) "
                    f"with US ADR {override.isin}",
                ),
                confidence="high",
            )

        # Use OpenFIGI to confirm ADR status (adds warning if confirmed)
        if self.openfigi:
            info = self.openfigi.lookup(ticker_input.ticker)
            if info and info.is_adr:
                logger.info(
                    "ADR confirmed by OpenFIGI for %s but no manual override available",
                    ticker_input.ticker,
                )
                return ISINResult(
                    ticker=original.ticker,
                    isin=original.isin,
                    cusip=original.cusip,
                    source=original.source,
                    company_name=original.company_name,
                    exchange=original.exchange,
                    warnings=original.warnings + (
                        f"ADR detected: {original.isin} is foreign ISIN for USD-denominated "
                        f"security — add US ADR ISIN to manual overrides",
                    ),
                    confidence="low",
                )

        logger.info(
            "ADR correction: no override found for %s, keeping %s",
            ticker_input.ticker,
            original.isin,
        )
        return None

    def resolve_batch(
        self, tickers: Union[list[str], list[TickerInput]]
    ) -> dict[str, ISINResult]:
        """Resolve multiple tickers. Uses batch operations where possible.

        Accepts either list[str] (backward compatible) or list[TickerInput].
        """
        inputs = [_normalize_input(t) for t in tickers]
        input_map = {inp.ticker: inp for inp in inputs}
        results: dict[str, ISINResult] = {}
        remaining: list[str] = []
        per_ticker_warnings: dict[str, list[str]] = {}

        # Tier 0: Manual overrides first (highest priority)
        override_results = self.manual_override.resolve_batch(
            [inp.ticker for inp in inputs]
        )
        for ticker, result in override_results.items():
            results[ticker] = result
            self.cache.put(result)

        # Check cache for remaining tickers
        for inp in inputs:
            upper = inp.ticker
            if upper in results:
                continue
            cached = self.cache.get(upper)
            if cached:
                # Apply ADR correction even for cached results
                if _check_adr_correction_needed(cached, inp):
                    corrected = self._try_adr_correction(cached, inp)
                    if corrected:
                        results[upper] = corrected
                        self.cache.put(corrected)
                        continue
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
                inp = input_map[ticker]
                # Check ADR correction
                if _check_adr_correction_needed(result, inp):
                    corrected = self._try_adr_correction(result, inp)
                    if corrected:
                        results[ticker] = corrected
                        self.cache.put(corrected)
                        continue
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
                    inp = input_map[ticker]
                    # Check ADR correction
                    if _check_adr_correction_needed(result, inp):
                        corrected = self._try_adr_correction(result, inp)
                        if corrected:
                            results[ticker] = corrected
                            self.cache.put(corrected)
                            continue
                    validated = _validate_currency_consistency(result, inp)
                    results[ticker] = validated
                    self.cache.put(validated)
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
    """Extract unique tickers from a ric.csv file (strips exchange suffix)."""
    tickers: list[str] = []
    seen: set[str] = set()

    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ric = row.get("ric", "").strip().strip('"')
            if not ric:
                continue
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


def parse_enriched_csv(path: Path) -> list[TickerInput]:
    """Parse enriched CSV with ticker, company_name, denomination_currency columns."""
    inputs: list[TickerInput] = []
    seen: set[str] = set()

    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ticker = row.get("ticker", "").strip().upper()
            if not ticker or ticker.lower() in ("ticker",):
                continue
            if ticker in seen:
                continue
            seen.add(ticker)

            company_name = row.get("company_name", "").strip() or None
            currency = row.get("denomination_currency", "").strip() or None

            inputs.append(TickerInput(
                ticker=ticker,
                company_name=company_name,
                denomination_currency=currency,
            ))

    return inputs


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
    adr_corrected: list[str] = []
    currency_warnings: list[str] = []

    for ticker, r in sorted(results.items()):
        by_source[r.source] = by_source.get(r.source, 0) + 1
        if r.isin:
            resolved += 1
        else:
            unresolved_tickers.append(ticker)
        if any("ADR corrected" in w for w in r.warnings):
            adr_corrected.append(ticker)
        if any("unexpected for USD denomination" in w for w in r.warnings):
            currency_warnings.append(ticker)

    print(f"\n{'='*60}")
    print("ISIN RESOLUTION SUMMARY (v2)")
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

    if adr_corrected:
        print(f"\nADR corrections applied ({len(adr_corrected)}):")
        for t in adr_corrected:
            r = results[t]
            adr_warn = [w for w in r.warnings if "ADR corrected" in w]
            print(f"  {t}: {adr_warn[0] if adr_warn else ''}")

    if currency_warnings:
        print(f"\nCurrency validation warnings ({len(currency_warnings)}):")
        for t in currency_warnings:
            print(f"  {t}")

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
        description="Resolve ticker symbols to ISINs (v2 — with OpenFIGI + ADR correction)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python isin_resolver_v2.py --tickers AAPL,MSFT,TSM,SPY
  python isin_resolver_v2.py --enriched-csv tickers_enriched.csv
  python isin_resolver_v2.py --ticker-file tickers.txt
  python isin_resolver_v2.py --ric-csv ric.csv
  python isin_resolver_v2.py --tickers AAPL,MSFT --no-yfinance --no-openfigi
  python isin_resolver_v2.py --tickers AAPL --force-refresh --output isins.csv
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
    input_group.add_argument(
        "--enriched-csv", type=Path,
        help="CSV with ticker,company_name,denomination_currency columns",
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
        "--no-openfigi", action="store_true",
        help="Skip OpenFIGI lookups",
    )
    parser.add_argument(
        "--openfigi-api-key", type=str, default=None,
        help="OpenFIGI API key (or set OPENFIGI_API_KEY env var)",
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

    # Parse input
    enriched_inputs: Optional[list[TickerInput]] = None

    if args.tickers:
        tickers = parse_tickers_from_string(args.tickers)
    elif args.ticker_file:
        if not args.ticker_file.exists():
            print(f"Error: File not found: {args.ticker_file}", file=sys.stderr)
            sys.exit(1)
        tickers = parse_tickers_from_file(args.ticker_file)
    elif args.enriched_csv:
        if not args.enriched_csv.exists():
            print(f"Error: File not found: {args.enriched_csv}", file=sys.stderr)
            sys.exit(1)
        enriched_inputs = parse_enriched_csv(args.enriched_csv)
        tickers = [inp.ticker for inp in enriched_inputs]
    else:
        if not args.ric_csv.exists():
            print(f"Error: File not found: {args.ric_csv}", file=sys.stderr)
            sys.exit(1)
        tickers = parse_tickers_from_ric_csv(args.ric_csv)

    if not tickers and not enriched_inputs:
        print("Error: No tickers provided", file=sys.stderr)
        sys.exit(1)

    count = len(enriched_inputs) if enriched_inputs else len(tickers)
    print(f"Resolving ISINs for {count} tickers (v2)...")

    # Initialize resolver
    resolver = ISINResolver(
        use_yfinance=not args.no_yfinance,
        use_openfigi=not args.no_openfigi,
        openfigi_api_key=args.openfigi_api_key,
    )

    if args.force_refresh:
        resolver.cache.clear()

    # Resolve
    if enriched_inputs:
        results = resolver.resolve_batch(enriched_inputs)
    else:
        results = resolver.resolve_batch(tickers)

    resolver.save_cache()

    # Output
    print_summary(results)

    if args.output:
        write_csv_output(results, args.output)


if __name__ == "__main__":
    main()
