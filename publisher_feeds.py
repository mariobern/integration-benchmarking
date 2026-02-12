#!/usr/bin/env python3
"""
Publisher Feeds Discovery Script.

Retrieves all feeds that a specific publisher is publishing from ClickHouse
and outputs them in CSV format with price_id, date, and asset_class columns.

Usage:
    python publisher_feeds.py --publisher-id 32
    python publisher_feeds.py --publisher-id 11 --output my_feeds.csv
    python publisher_feeds.py --publisher-id 11 --asset-class metal
    python publisher_feeds.py --publisher-id 11 --time-window 5
    python publisher_feeds.py --publisher-id 11 --date-offset 2
"""

import argparse
import csv
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import clickhouse_connect
import yaml

from date_utils import expand_date_args, validate_date_args


@dataclass
class FeedInfo:
    """Information about a feed published by a publisher."""

    price_id: int
    date: str
    asset_class: str


# Symbol suffix to ISO country code mapping for equities
EQUITY_COUNTRY_MAP = {
    # US exchanges (typically no suffix, but some may have these)
    ".N": "us",    # NYSE
    ".OQ": "us",   # NASDAQ
    ".A": "us",    # AMEX
    # European exchanges
    ".L": "gb",    # London Stock Exchange
    ".PA": "fr",   # Euronext Paris
    ".DE": "de",   # Deutsche Börse (Xetra)
    ".AS": "nl",   # Euronext Amsterdam
    ".MI": "it",   # Borsa Italiana (Milan)
    ".MC": "es",   # Bolsa de Madrid
    ".SW": "ch",   # SIX Swiss Exchange
    ".BR": "be",   # Euronext Brussels
    ".VI": "at",   # Vienna Stock Exchange
    ".ST": "se",   # Nasdaq Stockholm
    ".HE": "fi",   # Nasdaq Helsinki
    ".CO": "dk",   # Nasdaq Copenhagen
    ".OL": "no",   # Oslo Stock Exchange
    ".LS": "pt",   # Euronext Lisbon
    ".IR": "ie",   # Euronext Dublin
    ".WA": "pl",   # Warsaw Stock Exchange
    # Asia-Pacific exchanges
    ".HK": "hk",   # Hong Kong Stock Exchange
    ".T": "jp",    # Tokyo Stock Exchange
    ".SS": "cn",   # Shanghai Stock Exchange
    ".SZ": "cn",   # Shenzhen Stock Exchange
    ".KS": "kr",   # Korea Stock Exchange
    ".KQ": "kr",   # KOSDAQ
    ".TW": "tw",   # Taiwan Stock Exchange
    ".SI": "sg",   # Singapore Exchange
    ".AX": "au",   # Australian Securities Exchange
    ".NZ": "nz",   # New Zealand Exchange
    ".BO": "in",   # Bombay Stock Exchange
    ".NS": "in",   # National Stock Exchange of India
    ".BK": "th",   # Stock Exchange of Thailand
    ".JK": "id",   # Indonesia Stock Exchange
    ".KL": "my",   # Bursa Malaysia
    # Other regions
    ".SA": "br",   # B3 (Brazil)
    ".MX": "mx",   # Mexican Stock Exchange
    ".J": "za",    # Johannesburg Stock Exchange
}


def get_equity_country(symbol: Optional[str]) -> str:
    """
    Determine equity country code from symbol suffix.

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
    """
    Categorize asset class, adding country suffix for equities.

    For equity assets, returns 'equity-{country}' based on symbol pattern.
    For other assets, returns the original asset_type.
    """
    if asset_type == "equity":
        country = get_equity_country(symbol)
        return f"equity-{country}"
    return asset_type


def load_config() -> dict:
    """Load database configuration from config.yaml."""
    config_path = Path("config.yaml")
    if not config_path.exists():
        raise FileNotFoundError(
            "config.yaml not found. Copy config.yaml.sample to config.yaml and fill in credentials."
        )
    with open(config_path) as f:
        return yaml.safe_load(f)


def get_lazer_client(config: dict):
    """Create ClickHouse client for Lazer database."""
    lazer_cfg = config["lazer_clickhouse_prod"]

    connect_timeout = 60
    send_receive_timeout = 300

    return clickhouse_connect.get_client(
        host=lazer_cfg["host"],
        username=lazer_cfg["user"],
        password=lazer_cfg["password"],
        secure=True,
        connect_timeout=connect_timeout,
        send_receive_timeout=send_receive_timeout,
    )


def query_feeds_from_junction(
    client,
    publisher_id: int,
    time_window_minutes: int,
    date_offset_days: int = 1,
    asset_class_filter: Optional[str] = None,
) -> list[FeedInfo]:
    """
    Query feeds from feed_publisher_junction table (fast, pre-aggregated).

    This is the primary query method using the materialized view.
    """
    asset_filter = ""
    if asset_class_filter:
        # Handle equity-{country} filter by matching base asset type
        if asset_class_filter.startswith("equity-"):
            asset_filter = "AND fm.asset_type = 'equity'"
        else:
            asset_filter = f"AND fm.asset_type = '{asset_class_filter}'"

    query = f"""
        SELECT
            fpj.feed_id AS price_id,
            toDate(fpj.last_updated_at) - {date_offset_days} AS date,
            COALESCE(fm.asset_type, 'unknown') AS asset_class,
            fm.symbol
        FROM feed_publisher_junction fpj
        FINAL
        LEFT JOIN feeds_metadata_latest fm ON fpj.feed_id = fm.pyth_lazer_id
        WHERE fpj.publisher_id = {publisher_id}
          AND fpj.last_updated_at >= now() - INTERVAL {time_window_minutes} MINUTE
          {asset_filter}
        ORDER BY fm.asset_type, fpj.feed_id
    """

    result = client.query(query)
    feeds = []
    for row in result.result_rows:
        price_id, date, asset_type, symbol = row[0], str(row[1]), row[2], row[3]
        asset_class = categorize_asset_class(asset_type, symbol)

        # Apply post-filter for equity-{country} filters
        if asset_class_filter and asset_class_filter.startswith("equity-"):
            if asset_class != asset_class_filter:
                continue

        feeds.append(FeedInfo(price_id=price_id, date=date, asset_class=asset_class))
    return feeds


def query_feeds_from_updates(
    client,
    publisher_id: int,
    time_window_minutes: int,
    date_offset_days: int = 1,
    asset_class_filter: Optional[str] = None,
) -> list[FeedInfo]:
    """
    Query feeds from publisher_updates table (fallback, slower but precise).

    Used when feed_publisher_junction returns no results.
    """
    asset_filter = ""
    if asset_class_filter:
        # Handle equity-{country} filter by matching base asset type
        if asset_class_filter.startswith("equity-"):
            asset_filter = "AND fm.asset_type = 'equity'"
        else:
            asset_filter = f"AND fm.asset_type = '{asset_class_filter}'"

    query = f"""
        SELECT DISTINCT
            pu.price_feed_id AS price_id,
            toDate(pu.publish_time) - {date_offset_days} AS date,
            COALESCE(fm.asset_type, 'unknown') AS asset_class,
            fm.symbol
        FROM publisher_updates pu
        LEFT JOIN feeds_metadata_latest fm ON pu.price_feed_id = fm.pyth_lazer_id
        WHERE pu.publisher_id = {publisher_id}
          AND pu.publish_time >= now() - INTERVAL {time_window_minutes} MINUTE
          {asset_filter}
        ORDER BY fm.asset_type, pu.price_feed_id
    """

    result = client.query(query)
    feeds = []
    for row in result.result_rows:
        price_id, date, asset_type, symbol = row[0], str(row[1]), row[2], row[3]
        asset_class = categorize_asset_class(asset_type, symbol)

        # Apply post-filter for equity-{country} filters
        if asset_class_filter and asset_class_filter.startswith("equity-"):
            if asset_class != asset_class_filter:
                continue

        feeds.append(FeedInfo(price_id=price_id, date=date, asset_class=asset_class))
    return feeds


def get_publisher_feeds(
    client,
    publisher_id: int,
    time_window_minutes: int = 1,
    date_offset_days: int = 1,
    asset_class_filter: Optional[str] = None,
) -> list[FeedInfo]:
    """
    Get all feeds for a publisher, trying junction table first then falling back.

    Returns list of FeedInfo objects.
    """
    # Try fast query using junction table first
    feeds = query_feeds_from_junction(
        client, publisher_id, time_window_minutes, date_offset_days, asset_class_filter
    )

    if feeds:
        return feeds

    # Fallback to publisher_updates if junction returns nothing
    print(
        f"No data in feed_publisher_junction for last {time_window_minutes} minute(s), "
        "trying publisher_updates...",
        file=sys.stderr,
    )
    return query_feeds_from_updates(
        client, publisher_id, time_window_minutes, date_offset_days, asset_class_filter
    )


def write_csv(feeds: list[FeedInfo], output_path: Path) -> None:
    """Write feeds to CSV file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        # No header to match price_id_metal.csv format
        for feed in feeds:
            writer.writerow([feed.price_id, feed.date, feed.asset_class])

    print(f"Results written to: {output_path}")


def get_asset_class_summary(feeds: list[FeedInfo]) -> dict[str, int]:
    """Get count of feeds per asset class."""
    summary = {}
    for feed in feeds:
        summary[feed.asset_class] = summary.get(feed.asset_class, 0) + 1
    return dict(sorted(summary.items(), key=lambda x: -x[1]))


def main():
    parser = argparse.ArgumentParser(
        description="Discover feeds published by a specific publisher",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Get all feeds for publisher 32
  python publisher_feeds.py --publisher-id 32

  # Get feeds with custom output path
  python publisher_feeds.py --publisher-id 11 --output my_feeds.csv

  # Filter by asset class (metal, fx, crypto, equity, etc.)
  python publisher_feeds.py --publisher-id 11 --asset-class metal

  # Use larger time window (5 minutes)
  python publisher_feeds.py --publisher-id 32 --time-window 5

  # Use custom date offset (e.g., 2 days before for older benchmark data)
  python publisher_feeds.py --publisher-id 11 --date-offset 2

Asset classes: crypto, fx, metal, commodity, equity-us, equity-gb, equity-hk,
               equity-jp, equity-de, equity-fr (etc.), rates, nav,
               crypto-redemption-rate, crypto-index, funding-rate, kalshi, custom

Note: Equities are categorized by country code (ISO 3166-1 alpha-2) based on
      symbol suffix. US equities (no suffix) → equity-us, .L → equity-gb, etc.
""",
    )

    parser.add_argument(
        "--publisher-id",
        type=int,
        required=True,
        help="Publisher ID to query (e.g., 32)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output CSV path (default: publisher_{id}_feeds.csv)",
    )
    parser.add_argument(
        "--time-window",
        type=int,
        default=1,
        help="Time window in minutes to look back (default: 1)",
    )
    parser.add_argument(
        "--asset-class",
        type=str,
        help="Filter by asset class (e.g., metal, fx, crypto, equity-us, equity-gb)",
    )
    parser.add_argument(
        "--date-offset",
        type=int,
        default=1,
        help="Days to subtract from query date for benchmark data availability (default: 1)",
    )
    parser.add_argument(
        "--date",
        nargs="+",
        metavar="YYYY-MM-DD",
        help="Explicit date(s) for output rows. Overrides --date-offset.",
    )
    parser.add_argument(
        "--start-date",
        help="Range start date (inclusive, YYYY-MM-DD). Requires --end-date.",
    )
    parser.add_argument(
        "--end-date",
        help="Range end date (inclusive, YYYY-MM-DD). Requires --start-date.",
    )
    args = parser.parse_args()
    try:
        validate_date_args(args)
    except ValueError as e:
        parser.error(str(e))

    dates = expand_date_args(args.date, args.start_date, args.end_date)

    # Set default output path if not provided
    if args.output is None:
        args.output = Path(f"publisher_{args.publisher_id}_feeds.csv")

    print(f"Querying feeds for publisher {args.publisher_id}...")
    print(f"Time window: last {args.time_window} minute(s)")
    if dates:
        print(f"Output dates ({len(dates)}): {dates[0]} to {dates[-1]}")
        print("Date flags override --date-offset for CSV output rows")
    else:
        print(f"Date offset: {args.date_offset} day(s) before query date")
    if args.asset_class:
        print(f"Asset class filter: {args.asset_class}")

    try:
        config = load_config()
        client = get_lazer_client(config)

        discovered_feeds = get_publisher_feeds(
            client,
            args.publisher_id,
            args.time_window,
            args.date_offset,
            args.asset_class,
        )

        if not discovered_feeds:
            print(
                f"\nNo feeds found for publisher {args.publisher_id} "
                f"in the last {args.time_window} minute(s)."
            )
            print("Try increasing --time-window or check if the publisher is active.")
            sys.exit(0)

        unique_feed_count = len(discovered_feeds)
        feeds = discovered_feeds
        if dates:
            feeds = [
                FeedInfo(price_id=feed.price_id, date=date_value, asset_class=feed.asset_class)
                for feed in discovered_feeds
                for date_value in dates
            ]

        # Write results
        write_csv(feeds, args.output)

        # Print summary
        print(f"\n{'='*50}")
        print("SUMMARY")
        print(f"{'='*50}")
        print(f"Publisher ID: {args.publisher_id}")
        print(f"Unique feeds: {unique_feed_count}")
        unique_dates = sorted({feed.date for feed in feeds})
        if unique_dates:
            print(f"Date range: {unique_dates[0]} to {unique_dates[-1]} ({len(unique_dates)} date(s))")
        print(f"Total output rows: {len(feeds)}")

        summary = get_asset_class_summary(discovered_feeds)
        print("\nFeeds by asset class:")
        for asset_class, count in summary.items():
            print(f"  {asset_class}: {count}")

    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error querying ClickHouse: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
