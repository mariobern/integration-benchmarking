"""Generate price_id_list.csv from feed IDs and lazer_symbols.json.

Resolves each feed's asset class from lazer_symbols.json and pairs it with
the requested date(s) to produce a CSV compatible with quick_benchmark.py,
feed_readiness.py, and other batch-processing scripts.

Usage:
    python3 generate_price_list.py --feed-id 327 340 346 --date 2026-02-27
    python3 generate_price_list.py --feed-ids-file feeds.txt --start-date 2026-02-24 --end-date 2026-02-27
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from lib.config import BENCHMARKABLE_ASSET_CLASSES, normalize_asset_class


def resolve_feed_mode(entry: dict) -> str | None:
    """Map a lazer_symbols.json entry to its CSV mode value.

    Returns None if the feed is not benchmarkable (crypto, nav, non-US equity, etc.).
    """
    asset_type = entry.get("asset_type", "")
    symbol = entry.get("symbol", "")

    # Equities require US region check
    if asset_type == "equity":
        if not symbol.startswith("Equity.US."):
            return None
        return "us-equities"

    mode = normalize_asset_class(asset_type)
    if mode not in BENCHMARKABLE_ASSET_CLASSES:
        return None
    return mode


def load_symbols(path: Path) -> list[dict]:
    """Load symbols from a lazer_symbols.json file."""
    if not path.exists():
        raise FileNotFoundError(f"Symbols file not found: {path}")
    with open(path) as f:
        return json.load(f)


def build_lookup(symbols: list[dict]) -> dict[int, dict]:
    """Build a {pyth_lazer_id: entry} lookup dict."""
    return {entry["pyth_lazer_id"]: entry for entry in symbols}


def resolve_feeds(
    feed_ids: list[int], lookup: dict[int, dict]
) -> tuple[dict[int, str], list[str]]:
    """Resolve feed IDs to their CSV mode values.

    Returns:
        resolved: {feed_id: mode} for benchmarkable feeds
        skipped: list of warning messages for skipped feeds
    """
    resolved: dict[int, str] = {}
    skipped: list[str] = []

    for fid in feed_ids:
        if fid not in lookup:
            skipped.append(f"Feed {fid}: not found in symbols file")
            continue

        entry = lookup[fid]
        mode = resolve_feed_mode(entry)

        if mode is None:
            asset_type = entry.get("asset_type", "unknown")
            symbol = entry.get("symbol", "")
            if asset_type == "equity":
                skipped.append(
                    f"Feed {fid} ({symbol}): non-US equity, not benchmarkable"
                )
            else:
                skipped.append(
                    f"Feed {fid} ({symbol}): {asset_type} is not benchmarkable"
                )
            continue

        resolved[fid] = mode

    return resolved, skipped


def expand_dates(start: date, end: date) -> list[date]:
    """Expand a date range into a list of individual dates (inclusive)."""
    if start > end:
        raise ValueError(f"start date {start} is after end date {end}")
    dates = []
    current = start
    while current <= end:
        dates.append(current)
        current += timedelta(days=1)
    return dates


def write_csv(resolved: dict[int, str], dates: list[date], output: Path) -> int:
    """Write price_id_list CSV (no header). Returns row count."""
    output.parent.mkdir(parents=True, exist_ok=True)
    row_count = 0
    with open(output, "w", newline="") as f:
        writer = csv.writer(f)
        for feed_id in sorted(resolved):
            mode = resolved[feed_id]
            for d in dates:
                writer.writerow([feed_id, d.isoformat(), mode])
                row_count += 1
    return row_count


def parse_feed_ids_file(path: Path) -> list[int]:
    """Parse feed IDs from a text file (one per line, # comments allowed)."""
    if not path.exists():
        raise FileNotFoundError(f"Feed IDs file not found: {path}")
    feed_ids = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            feed_ids.append(int(line))
    return feed_ids


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate price_id_list.csv from feed IDs and lazer_symbols.json",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Inline feed IDs with single date
  python3 generate_price_list.py --feed-id 327 340 346 --date 2026-02-27

  # Feed IDs with date range
  python3 generate_price_list.py --feed-id 327 340 --start-date 2026-02-24 --end-date 2026-02-27

  # Feed IDs from file
  python3 generate_price_list.py --feed-ids-file feeds.txt --date 2026-02-27

  # Custom output and symbols paths
  python3 generate_price_list.py --feed-id 327 --date 2026-02-27 --output my_batch.csv --symbols lazer_symbols1.json
""",
    )

    # Feed ID input (mutually exclusive)
    feed_group = parser.add_mutually_exclusive_group(required=True)
    feed_group.add_argument(
        "--feed-id",
        nargs="+",
        type=int,
        help="Space-separated feed IDs",
    )
    feed_group.add_argument(
        "--feed-ids-file",
        type=Path,
        help="Text file with one feed ID per line",
    )

    # Date input (mutually exclusive)
    date_group = parser.add_mutually_exclusive_group(required=True)
    date_group.add_argument(
        "--date",
        type=date.fromisoformat,
        help="Single date (YYYY-MM-DD)",
    )
    date_group.add_argument(
        "--start-date",
        type=date.fromisoformat,
        help="Start of date range (requires --end-date)",
    )

    parser.add_argument(
        "--end-date",
        type=date.fromisoformat,
        help="End of date range (requires --start-date)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("price_id_list.csv"),
        help="Output CSV path (default: price_id_list.csv)",
    )
    parser.add_argument(
        "--symbols",
        type=Path,
        default=Path("lazer_symbols.json"),
        help="Path to lazer_symbols.json (default: lazer_symbols.json)",
    )

    args = parser.parse_args()

    # Validate date range
    if args.start_date and not args.end_date:
        parser.error("--start-date requires --end-date")
    if args.end_date and not args.start_date:
        parser.error("--end-date requires --start-date")

    # Determine dates
    if args.date:
        start, end = args.date, args.date
    else:
        start, end = args.start_date, args.end_date
    dates = expand_dates(start, end)

    # Collect feed IDs
    if args.feed_id:
        feed_ids = args.feed_id
    else:
        feed_ids = parse_feed_ids_file(args.feed_ids_file)

    # Load symbols and resolve
    symbols = load_symbols(args.symbols)
    print(f"Loaded {len(symbols)} symbols from {args.symbols}", file=sys.stderr)

    lookup = build_lookup(symbols)
    resolved, skipped = resolve_feeds(feed_ids, lookup)

    # Print summary to stderr
    print(
        f"Resolved {len(resolved)} feed(s), skipped {len(skipped)}:",
        file=sys.stderr,
    )
    for msg in skipped:
        print(f"  {msg}", file=sys.stderr)

    if not resolved:
        print("No benchmarkable feeds to write.", file=sys.stderr)
        sys.exit(1)

    # Write CSV
    row_count = write_csv(resolved, dates, args.output)
    print(f"Wrote {row_count} rows to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
