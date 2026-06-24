#!/usr/bin/env python3
"""Publisher Asset Map.

For one UTC date, map what every publisher published: feed-level detail plus
per-publisher asset-class summary and matrix CSVs.

Usage:
    python3 publisher_asset_map.py --date 2026-06-23
    python3 publisher_asset_map.py --date 2026-06-23 --asset-class metal
    python3 publisher_asset_map.py --date 2026-06-23 --output-dir output_csv
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

from lib.config import get_lazer_client, load_config
from lib.publisher_asset_map_core import fetch_publisher_feeds, write_outputs


def main():
    parser = argparse.ArgumentParser(
        description="Map what every publisher published on a given UTC date",
    )
    parser.add_argument(
        "--date",
        required=True,
        metavar="YYYY-MM-DD",
        help="UTC day to analyze (full 24h window)",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("output_csv"),
        help="Directory for the three CSV outputs (default: output_csv)",
    )
    parser.add_argument(
        "--asset-class",
        help="Optional asset-class filter (e.g. metal, fx, equity-us)",
    )
    args = parser.parse_args()

    print(f"Querying publisher_updates for {args.date} (full UTC day)...")
    if args.asset_class:
        print(f"Asset class filter: {args.asset_class}")

    try:
        config = load_config()
        client = get_lazer_client(config)
        rows = fetch_publisher_feeds(client, args.date, args.asset_class)
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error querying ClickHouse: {e}", file=sys.stderr)
        sys.exit(1)

    if not rows:
        print(
            f"\nNo publisher activity found for {args.date}. "
            "It may be a non-trading day, a future date, or not yet ingested."
        )
        sys.exit(0)

    paths = write_outputs(rows, args.date, args.output_dir)

    publishers = {r.publisher_id for r in rows}
    feeds = {r.feed_id for r in rows}
    per_class_feeds = defaultdict(set)
    for r in rows:
        per_class_feeds[r.asset_class].add(r.feed_id)

    print(f"\n{'='*50}")
    print("SUMMARY")
    print(f"{'='*50}")
    print(f"Date: {args.date}")
    print(f"Publishers seen: {len(publishers)}")
    print(f"Unique feeds: {len(feeds)}")
    print("\nFeeds by asset class (distinct feeds across all publishers):")
    for asset_class in sorted(per_class_feeds):
        print(f"  {asset_class}: {len(per_class_feeds[asset_class])}")

    print("\nWrote:")
    for p in paths:
        print(f"  {p}")


if __name__ == "__main__":
    main()
