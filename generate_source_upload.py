#!/usr/bin/env python3
"""
Generate Source Upload CSV for Pyth Network US Equity Onboarding.

Given a list of tickers, resolves each to its Reuters Instrument Code (RIC),
company name, and Pyth identifiers, then outputs a CSV matching the
source_upload format used for Datascope instrument onboarding.

Three-tier RIC resolution:
  1. Datascope ClickHouse (most accurate - uses the actual RIC Datascope has)
  2. NASDAQ Trader listings (offline fallback - downloaded and cached)
  3. Default .N suffix (last resort, flagged for manual review)

Usage:
    python generate_source_upload.py --tickers AAPL,NVDA,META
    python generate_source_upload.py --ticker-file tickers.txt
    python generate_source_upload.py --ticker-file tickers.txt --output source_upload.csv
    python generate_source_upload.py --tickers AAPL,NVDA --no-clickhouse
"""

import argparse
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import clickhouse_connect
import yaml

# --- Constants ---

NASDAQ_TRADER_BASE_URL = "https://www.nasdaqtrader.com/dynamic/SymDir"
NASDAQ_LISTED_URL = f"{NASDAQ_TRADER_BASE_URL}/nasdaqlisted.txt"
OTHER_LISTED_URL = f"{NASDAQ_TRADER_BASE_URL}/otherlisted.txt"

CACHE_DIR = Path(".nasdaq_cache")
CACHE_TTL_SECONDS = 24 * 60 * 60  # 24 hours

# otherlisted.txt Exchange column -> RIC suffix
OTHER_EXCHANGE_SUFFIX_MAP = {
    "N": ".N",   # NYSE
    "P": ".P",   # NYSE Arca
    "Z": ".Z",   # BATS
    "A": ".A",   # NYSE American (AMEX)
    "V": ".V",   # IEXG
}

# ADR detection keywords (case-insensitive match against security name)
ADR_KEYWORDS = [
    "american depositary",
    "depositary shares",
    "depositary receipts",
    "sponsored adr",
    " adr",
    " ads",
]

# Ticker format: 1-5 uppercase letters, optional dot + single letter (share class)
TICKER_PATTERN = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")


def validate_ticker(ticker: str) -> bool:
    """Validate that a ticker matches expected US equity format."""
    return bool(TICKER_PATTERN.match(ticker.upper()))


def ticker_to_ric_base(ticker: str) -> str:
    """
    Convert a ticker with share class dot notation to RIC base format.

    BRK.B -> BRKb (lowercase class letter, no dot)
    BRK.A -> BRKa
    BF.B  -> BFb
    AAPL  -> AAPL (unchanged)
    """
    upper = ticker.upper()
    if "." in upper:
        base, cls = upper.rsplit(".", 1)
        if len(cls) == 1 and cls.isalpha():
            return base + cls.lower()
    return upper


# --- Data Classes ---


@dataclass
class TickerInfo:
    """Resolved information for a single ticker."""

    ticker: str
    ric: str = ""
    name: str = ""
    asset_class: str = "Equity"
    pyth_lazer_id: Optional[int] = None
    ric_source: str = ""  # "datascope", "nasdaq_trader", "default"
    warnings: list[str] = field(default_factory=list)


@dataclass
class SourceUploadRow:
    """A single row in the source_upload CSV output."""

    source_value: str  # RIC (e.g., AAPL.O)
    source_type: str = "RIC"
    pyth_id: str = ""  # equity.<ticker_lower>
    pythnet_id: str = ""  # Equity.US.<TICKER>/USD
    pyth_lazer_id: str = ""  # numeric ID or empty
    valid_from: str = ""
    valid_to: str = ""
    ticker: str = ""
    asset_full_name: str = ""
    asset_class: str = "Equity"


# --- Config & ClickHouse ---


def load_config() -> dict:
    """Load database configuration from config.yaml."""
    config_path = Path("config.yaml")
    if not config_path.exists():
        raise FileNotFoundError(
            "config.yaml not found. Copy config.yaml.sample to config.yaml "
            "and fill in credentials."
        )
    with open(config_path) as f:
        return yaml.safe_load(f)


def get_analytics_client(config: dict):
    """Create ClickHouse client for Analytics database (Datascope benchmark data)."""
    analytics_cfg = config["analytics_clickhouse"]
    return clickhouse_connect.get_client(
        host=analytics_cfg["host"],
        username=analytics_cfg["user"],
        password=analytics_cfg["password"],
        secure=True,
        connect_timeout=60,
        send_receive_timeout=300,
    )


def get_lazer_client(config: dict):
    """Create ClickHouse client for Lazer database (feed metadata)."""
    lazer_cfg = config["lazer_clickhouse_prod"]
    return clickhouse_connect.get_client(
        host=lazer_cfg["host"],
        username=lazer_cfg["user"],
        password=lazer_cfg["password"],
        secure=True,
        connect_timeout=60,
        send_receive_timeout=300,
    )


# --- ClickHouse Lookups ---


class ClickHouseLookup:
    """Resolve RICs and pyth_lazer_ids from ClickHouse."""

    def __init__(self, config: dict):
        self.analytics_client = get_analytics_client(config)
        self.lazer_client = get_lazer_client(config)

    def lookup_datascope_rics(self, tickers: list[str]) -> dict[str, list[str]]:
        """
        Query Datascope for known RICs matching the given tickers.

        Returns {ticker_upper: [ric1, ric2, ...]} for tickers found in Datascope,
        ordered by row count descending (most-used RIC first).
        Handles dotted tickers: BRK.B is queried as BRKb.% in Datascope.
        """
        if not tickers:
            return {}

        # Build parameterized LIKE patterns
        ric_base_to_original: dict[str, str] = {}
        params: dict[str, str] = {}
        like_clauses = []
        for i, t in enumerate(tickers):
            ric_base = ticker_to_ric_base(t)
            ric_base_to_original[ric_base.upper()] = t.upper()
            param_name = f"p{i}"
            like_clauses.append(f"ric LIKE {{{param_name}:String}}")
            params[param_name] = f"{ric_base}.%"

        where = " OR ".join(like_clauses)
        query = f"""
            SELECT ric, count() as cnt
            FROM datascope_global_equities_benchmark_data
            WHERE ({where})
              AND ric != ''
            GROUP BY ric
            ORDER BY cnt DESC
        """

        try:
            result = self.analytics_client.query(query, parameters=params)
        except Exception as e:
            print(f"  Warning: Datascope RIC query failed: {e}", file=sys.stderr)
            return {}

        ric_map: dict[str, list[str]] = {}
        for row in result.result_rows:
            ric = row[0]
            dot_idx = ric.rfind(".")
            if dot_idx > 0:
                ric_base = ric[:dot_idx]
                original = ric_base_to_original.get(
                    ric_base.upper(), ric_base.upper()
                )
                ric_map.setdefault(original, []).append(ric)

        return ric_map

    def lookup_lazer_ids(self, tickers: list[str]) -> dict[str, int]:
        """
        Look up pyth_lazer_id for each ticker from feeds_metadata_latest.

        Returns {ticker_upper: pyth_lazer_id}.
        """
        if not tickers:
            return {}

        # Build parameterized IN clause
        symbols = [f"Equity.US.{t.upper()}/USD" for t in tickers]
        params: dict[str, str] = {}
        placeholders = []
        for i, s in enumerate(symbols):
            param_name = f"s{i}"
            params[param_name] = s
            placeholders.append(f"{{{param_name}:String}}")

        query = f"""
            SELECT symbol, pyth_lazer_id
            FROM feeds_metadata_latest
            WHERE symbol IN ({', '.join(placeholders)})
        """

        try:
            result = self.lazer_client.query(query, parameters=params)
        except Exception as e:
            print(f"  Warning: Lazer ID query failed: {e}", file=sys.stderr)
            return {}

        id_map: dict[str, int] = {}
        for row in result.result_rows:
            symbol, lazer_id = row[0], row[1]
            ticker = symbol.replace("Equity.US.", "").replace("/USD", "").upper()
            id_map[ticker] = lazer_id

        return id_map


# --- NASDAQ Trader Source ---


class NasdaqTraderSource:
    """Download and parse NASDAQ Trader listing files for RIC resolution."""

    def __init__(self, force_refresh: bool = False):
        self.force_refresh = force_refresh
        self._nasdaq_tickers: dict[str, str] = {}  # ticker -> name
        self._other_tickers: dict[str, tuple[str, str]] = {}  # ticker -> (exchange, name)
        self._loaded = False

    def _ensure_cache_dir(self) -> None:
        CACHE_DIR.mkdir(exist_ok=True)

    def _is_cache_valid(self, path: Path) -> bool:
        if self.force_refresh or not path.exists():
            return False
        age = time.time() - path.stat().st_mtime
        return age < CACHE_TTL_SECONDS

    def _download(self, url: str, cache_path: Path) -> str:
        if self._is_cache_valid(cache_path):
            return cache_path.read_text()

        self._ensure_cache_dir()
        print(f"  Downloading {url}...")
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = resp.read().decode("utf-8")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as e:
            if cache_path.exists():
                print(f"  Warning: Download failed ({e}), using stale cache", file=sys.stderr)
                return cache_path.read_text()
            raise RuntimeError(f"Cannot fetch {url} and no cached version available") from e
        cache_path.write_text(data)
        return data

    def _load(self) -> None:
        if self._loaded:
            return

        # Parse nasdaqlisted.txt (pipe-delimited, all NASDAQ stocks)
        # Format: Symbol|Security Name|...|Test Issue|...
        nasdaq_data = self._download(
            NASDAQ_LISTED_URL, CACHE_DIR / "nasdaqlisted.txt"
        )
        for line in nasdaq_data.strip().split("\n")[1:]:  # skip header
            if line.startswith("File Creation Time"):
                continue
            parts = line.split("|")
            if len(parts) >= 2:
                symbol = parts[0].strip().upper()
                name = parts[1].strip()
                test_issue = parts[3].strip() if len(parts) > 3 else "N"
                if test_issue != "Y":  # skip test issues
                    self._nasdaq_tickers[symbol] = name

        # Parse otherlisted.txt (pipe-delimited, NYSE/ARCA/BATS/AMEX)
        # Format: ACT Symbol|Security Name|Exchange|...
        other_data = self._download(
            OTHER_LISTED_URL, CACHE_DIR / "otherlisted.txt"
        )
        for line in other_data.strip().split("\n")[1:]:  # skip header
            if line.startswith("File Creation Time"):
                continue
            parts = line.split("|")
            if len(parts) >= 3:
                symbol = parts[0].strip().upper()
                name = parts[1].strip()
                exchange = parts[2].strip()
                test_issue = parts[5].strip() if len(parts) > 5 else "N"
                if test_issue != "Y":
                    self._other_tickers[symbol] = (exchange, name)

        self._loaded = True

    def resolve(self, ticker: str) -> Optional[tuple[str, str]]:
        """
        Resolve a ticker to (ric, name) using NASDAQ Trader data.

        Returns None if ticker not found.
        For dotted tickers like BRK.B, produces RIC BRKb.N (Datascope format).
        """
        self._load()
        upper = ticker.upper()
        ric_base = ticker_to_ric_base(upper)

        # NASDAQ Trader stores BRK.B as "BRK.B" in otherlisted.txt
        # Check using the original ticker form (with dot)
        lookup_forms = [upper]
        if ric_base != upper:
            lookup_forms.append(ric_base)

        for form in lookup_forms:
            # Check NASDAQ first -> .O suffix
            if form in self._nasdaq_tickers:
                ric = f"{ric_base}.O"
                return ric, self._nasdaq_tickers[form]

            # Check other listings
            if form in self._other_tickers:
                exchange, name = self._other_tickers[form]
                suffix = OTHER_EXCHANGE_SUFFIX_MAP.get(exchange, ".N")
                ric = f"{ric_base}{suffix}"
                return ric, name

        return None


# --- US Stock Symbols Source ---


class USStockSymbolsSource:
    """Load company names and metadata from the US-Stock-Symbols repo."""

    def __init__(self, repo_path: Path):
        self.repo_path = repo_path
        self._data: dict[str, dict[str, str]] = {}  # ticker -> {name, country}
        self._loaded = False

    def _load(self) -> None:
        if self._loaded:
            return

        for subdir in ["nasdaq", "nyse", "amex"]:
            json_path = self.repo_path / subdir / f"{subdir}_full_tickers.json"
            if not json_path.exists():
                continue
            with open(json_path) as f:
                entries = json.load(f)
            for entry in entries:
                symbol = entry.get("symbol", "").upper()
                name = entry.get("name", "")
                country = entry.get("country", "")
                if symbol and name:
                    self._data[symbol] = {"name": name, "country": country}

        self._loaded = True

    def get_name(self, ticker: str) -> Optional[str]:
        """Look up company name for a ticker."""
        self._load()
        entry = self._data.get(ticker.upper())
        return entry["name"] if entry else None

    def get_country(self, ticker: str) -> str:
        """Look up country for a ticker. Returns empty string if not found."""
        self._load()
        entry = self._data.get(ticker.upper())
        return entry.get("country", "") if entry else ""


# --- Asset Classification ---


def classify_asset(name: str, country: str = "") -> str:
    """
    Classify as 'American Depositary Shares' or 'Equity'.

    ADR detection: name contains ADR keywords or country is non-US.
    Everything else (including ETFs) is 'Equity' per existing convention.
    """
    name_lower = name.lower()
    for keyword in ADR_KEYWORDS:
        if keyword in name_lower:
            return "American Depositary Shares"

    if country and country.lower() not in ("united states", "us", "usa", ""):
        return "American Depositary Shares"

    return "Equity"


# --- Core Resolution ---


def resolve_tickers(
    tickers: list[str],
    clickhouse_lookup: Optional[ClickHouseLookup],
    nasdaq_source: NasdaqTraderSource,
    us_stocks_source: Optional[USStockSymbolsSource],
) -> list[TickerInfo]:
    """
    Resolve a list of tickers using the 3-tier strategy.

    Returns a TickerInfo for each ticker in input order.
    """
    results: list[TickerInfo] = []

    # Batch ClickHouse lookups for efficiency
    datascope_rics: dict[str, list[str]] = {}
    lazer_ids: dict[str, int] = {}

    if clickhouse_lookup:
        print("Querying Datascope for known RICs...")
        datascope_rics = clickhouse_lookup.lookup_datascope_rics(tickers)
        print(f"  Found RICs for {len(datascope_rics)} tickers in Datascope")

        print("Querying feeds_metadata for pyth_lazer_ids...")
        lazer_ids = clickhouse_lookup.lookup_lazer_ids(tickers)
        print(f"  Found lazer IDs for {len(lazer_ids)} tickers")

    for ticker in tickers:
        upper = ticker.upper()
        info = TickerInfo(ticker=upper)
        info.pyth_lazer_id = lazer_ids.get(upper)

        # Tier 1: Datascope ClickHouse
        ds_rics = datascope_rics.get(upper, [])
        if ds_rics:
            if len(ds_rics) == 1:
                info.ric = ds_rics[0]
            else:
                # Multiple RICs - prefer one with a matching lazer_id
                info.ric = ds_rics[0]  # default to first
                info.warnings.append(
                    f"Multiple Datascope RICs: {', '.join(ds_rics)}; using {info.ric}"
                )
            info.ric_source = "datascope"

        # Tier 2: NASDAQ Trader
        if not info.ric:
            nasdaq_result = nasdaq_source.resolve(upper)
            if nasdaq_result:
                info.ric, info.name = nasdaq_result
                info.ric_source = "nasdaq_trader"

        # Tier 3: Default .N
        if not info.ric:
            ric_base = ticker_to_ric_base(upper)
            info.ric = f"{ric_base}.N"
            info.ric_source = "default"
            info.warnings.append(
                f"Not found in Datascope or NASDAQ Trader; defaulting to {info.ric}"
            )

        # Resolve name if not yet set (Datascope doesn't provide names)
        if not info.name:
            # Try NASDAQ Trader for name even if RIC came from Datascope
            nasdaq_result = nasdaq_source.resolve(upper)
            if nasdaq_result:
                _, info.name = nasdaq_result

        # Try US-Stock-Symbols as name fallback
        if not info.name and us_stocks_source:
            info.name = us_stocks_source.get_name(upper) or ""

        # Final fallback name
        if not info.name:
            info.name = upper
            info.warnings.append("Could not resolve company name")

        # Classify asset type (use country from US-Stock-Symbols if available)
        country = us_stocks_source.get_country(upper) if us_stocks_source else ""
        info.asset_class = classify_asset(info.name, country)

        results.append(info)

    return results


# --- Output ---


def build_rows(infos: list[TickerInfo]) -> list[SourceUploadRow]:
    """Convert resolved TickerInfo list to SourceUploadRow list."""
    rows = []
    for info in infos:
        rows.append(
            SourceUploadRow(
                source_value=info.ric,
                pyth_id=f"equity.{info.ticker.lower()}",
                pythnet_id=f"Equity.US.{info.ticker}/USD",
                pyth_lazer_id=str(info.pyth_lazer_id) if info.pyth_lazer_id else "",
                ticker=info.ticker,
                asset_full_name=info.name,
                asset_class=info.asset_class,
            )
        )
    return rows


def write_csv(rows: list[SourceUploadRow], output_path: Path) -> None:
    """Write source upload CSV matching the expected format."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="") as f:
        # Write header as raw string to match reference format (space after commas)
        f.write(
            "source_value, source_type, pyth_id, pythnet_id, pyth_lazer_id, "
            "valid_from, valid_to, ticker, asset_full_name, asset_class\n"
        )
        # Write data rows with standard csv.writer (no space after commas)
        writer = csv.writer(f)
        for row in rows:
            writer.writerow([
                row.source_value,
                row.source_type,
                row.pyth_id,
                row.pythnet_id,
                row.pyth_lazer_id,
                row.valid_from,
                row.valid_to,
                row.ticker,
                row.asset_full_name,
                row.asset_class,
            ])

    print(f"\nWrote {len(rows)} rows to {output_path}")


def print_summary(infos: list[TickerInfo]) -> None:
    """Print resolution summary to console."""
    total = len(infos)
    by_source = {"datascope": 0, "nasdaq_trader": 0, "default": 0}
    with_lazer = 0
    warnings = []

    for info in infos:
        by_source[info.ric_source] = by_source.get(info.ric_source, 0) + 1
        if info.pyth_lazer_id:
            with_lazer += 1
        for w in info.warnings:
            warnings.append(f"  {info.ticker}: {w}")

    print(f"\n{'='*60}")
    print("RESOLUTION SUMMARY")
    print(f"{'='*60}")
    print(f"Total tickers: {total}")
    print()
    print("RIC resolution source:")
    print(f"  Datascope ClickHouse: {by_source['datascope']}")
    print(f"  NASDAQ Trader:        {by_source['nasdaq_trader']}")
    print(f"  Default (.N):         {by_source['default']}")
    print()
    print(f"With pyth_lazer_id: {with_lazer}/{total}")
    print(f"Without pyth_lazer_id: {total - with_lazer}/{total}")

    if warnings:
        print(f"\nWarnings ({len(warnings)}):")
        for w in warnings:
            print(w)


# --- Input Parsing ---


def parse_tickers_from_string(ticker_string: str) -> list[str]:
    """Parse comma-separated ticker string, de-duplicate preserving order."""
    seen: set[str] = set()
    result: list[str] = []
    for t in ticker_string.split(","):
        t = t.strip().upper()
        if not t or t in seen:
            continue
        if not validate_ticker(t):
            print(f"Warning: Skipping invalid ticker format: {t}", file=sys.stderr)
            continue
        seen.add(t)
        result.append(t)
    return result


def parse_tickers_from_file(file_path: Path) -> list[str]:
    """
    Parse tickers from a file (one per line, or CSV first column).

    Supports:
      - One ticker per line: AAPL\\nNVDA\\nMETA
      - CSV with header: ticker,other_col\\nAAPL,whatever
      - CSV without header: AAPL\\nNVDA
    """
    seen: set[str] = set()
    result: list[str] = []

    with open(file_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue

            # Handle CSV: take first column
            parts = line.split(",")
            candidate = parts[0].strip().upper()

            if not candidate:
                continue

            # Skip header-like rows
            if candidate.lower() in ("ticker", "symbol", "tickers", "symbols"):
                continue

            if not validate_ticker(candidate):
                print(f"Warning: Skipping invalid ticker format: {candidate}", file=sys.stderr)
                continue

            if candidate not in seen:
                seen.add(candidate)
                result.append(candidate)

    return result


# --- Main ---


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate source upload CSV for Pyth US equity onboarding",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # From comma-separated tickers
  python generate_source_upload.py --tickers AAPL,NVDA,META

  # From a file (one ticker per line or CSV)
  python generate_source_upload.py --ticker-file tickers.txt

  # Custom output path
  python generate_source_upload.py --tickers AAPL,NVDA --output my_upload.csv

  # Offline mode (skip ClickHouse, use NASDAQ Trader only)
  python generate_source_upload.py --tickers AAPL,NVDA --no-clickhouse

  # Force re-download NASDAQ Trader data
  python generate_source_upload.py --tickers AAPL --force-refresh
""",
    )

    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--tickers",
        type=str,
        help="Comma-separated ticker list (e.g., AAPL,NVDA,META)",
    )
    input_group.add_argument(
        "--ticker-file",
        type=Path,
        help="File with tickers (one per line or CSV)",
    )

    parser.add_argument(
        "--output",
        type=Path,
        default=Path("source_upload.csv"),
        help="Output CSV path (default: source_upload.csv)",
    )
    parser.add_argument(
        "--no-clickhouse",
        action="store_true",
        help="Skip ClickHouse lookups (offline mode, NASDAQ Trader only)",
    )
    parser.add_argument(
        "--us-stocks-path",
        type=Path,
        default=Path("../US-Stock-Symbols"),
        help="Path to US-Stock-Symbols repo (default: ../US-Stock-Symbols)",
    )
    parser.add_argument(
        "--force-refresh",
        action="store_true",
        help="Re-download NASDAQ Trader data (ignore cache)",
    )

    args = parser.parse_args()

    # Parse input tickers
    if args.tickers:
        tickers = parse_tickers_from_string(args.tickers)
    else:
        if not args.ticker_file.exists():
            print(f"Error: File not found: {args.ticker_file}", file=sys.stderr)
            sys.exit(1)
        tickers = parse_tickers_from_file(args.ticker_file)

    if not tickers:
        print("Error: No tickers provided", file=sys.stderr)
        sys.exit(1)

    print(f"Processing {len(tickers)} tickers...")

    # Initialize data sources
    clickhouse_lookup = None
    if not args.no_clickhouse:
        try:
            config = load_config()
            clickhouse_lookup = ClickHouseLookup(config)
        except FileNotFoundError as e:
            print(f"Warning: {e}", file=sys.stderr)
            print("Falling back to offline mode (NASDAQ Trader only)", file=sys.stderr)
        except Exception as e:
            print(f"Warning: ClickHouse connection failed: {e}", file=sys.stderr)
            print("Falling back to offline mode (NASDAQ Trader only)", file=sys.stderr)

    print("\nLoading NASDAQ Trader listings...")
    nasdaq_source = NasdaqTraderSource(force_refresh=args.force_refresh)

    us_stocks_source = None
    if args.us_stocks_path.exists():
        print(f"Loading US-Stock-Symbols from {args.us_stocks_path}...")
        us_stocks_source = USStockSymbolsSource(args.us_stocks_path)
    else:
        print(f"US-Stock-Symbols not found at {args.us_stocks_path}, skipping")

    # Resolve tickers
    infos = resolve_tickers(tickers, clickhouse_lookup, nasdaq_source, us_stocks_source)

    # Build and write output
    rows = build_rows(infos)
    write_csv(rows, args.output)

    # Print summary
    print_summary(infos)


if __name__ == "__main__":
    main()
