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
import time
from pathlib import Path

from lib.config import get_lazer_client, load_config
from lib.publisher_asset_map_core import (
    feeds_by_asset_class,
    feeds_by_session,
    fetch_publisher_feeds,
    session_probe_windows,
    write_outputs,
)


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
    parser.add_argument(
        "--probe-interval-min",
        type=int,
        default=30,
        help="Spacing between probe windows in minutes (default: 30)",
    )
    parser.add_argument(
        "--probe-width-min",
        type=int,
        default=2,
        help="Probe window width in minutes (default: 2)",
    )
    args = parser.parse_args()

    windows = session_probe_windows(
        args.date, args.probe_interval_min, args.probe_width_min
    )
    print(
        f"Sampling {len(windows)} probe windows "
        f"(every {args.probe_interval_min} min x {args.probe_width_min} min) "
        f"for ET trading date {args.date}..."
    )
    # Concise per-session summary: probe count + UTC span (first start -> last end).
    for session in ("premarket", "regular", "afterhours", "overnight"):
        sw = [w for w in windows if w.session == session]
        if sw:
            print(
                f"  {session:10s} {len(sw):2d} probes  "
                f"{sw[0].start_utc} -> {sw[-1].end_utc} UTC"
            )
    if args.asset_class:
        print(f"Asset class filter: {args.asset_class}")

    started = time.time()
    try:
        config = load_config()
        client = get_lazer_client(config)
        rows = fetch_publisher_feeds(
            client,
            args.date,
            args.probe_interval_min,
            args.probe_width_min,
            args.asset_class,
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error during initialization or query: {e}", file=sys.stderr)
        sys.exit(1)
    elapsed = time.time() - started

    if not rows:
        print(
            f"\nNo publisher activity found for {args.date}. "
            "It may be a non-trading day, a future date, or not yet ingested."
        )
        sys.exit(0)

    paths = write_outputs(rows, args.date, args.output_dir)

    publishers = {r.publisher_id for r in rows}
    feeds = {r.feed_id for r in rows}
    per_class = feeds_by_asset_class(rows)

    print(f"\n{'='*50}")
    print("SUMMARY")
    print(f"{'='*50}")
    print(f"Date: {args.date}")
    print(f"Query time: {elapsed:.1f}s")
    print(f"Publishers seen: {len(publishers)}")
    print(f"Unique feeds: {len(feeds)}")
    print("\nFeeds by asset class (distinct feeds across all publishers):")
    for asset_class, count in per_class.items():
        print(f"  {asset_class}: {count}")

    per_session = feeds_by_session(rows)
    if per_session:
        print("\nUS-equity feeds by session (distinct feeds):")
        for session, count in per_session.items():
            print(f"  {session}: {count}")

    print("\nWrote:")
    for p in paths:
        print(f"  {p}")


if __name__ == "__main__":
    main()
