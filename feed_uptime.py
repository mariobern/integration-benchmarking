#!/usr/bin/env python3
"""
Feed-centric uptime measurement script.

Default mode uses a 1-second window uptime method. Use --precise to switch to
gap-based uptime (default 200ms threshold).

Core uptime logic lives in lib/uptime_core.py.
Output formatting, CSV writing, and console reports live in lib/uptime_output.py.
This file is the CLI wrapper.
"""

import argparse
import sys
import time
from pathlib import Path

from date_utils import expand_date_args, validate_date_args
from lib.benchmark_core import list_asset_classes_in_csv
from lib.config import normalize_asset_class
from lib.models import FeedUptimeResult
from lib.uptime_core import (
    DEFAULT_GAP_THRESHOLD_MS,
    DEFAULT_UPTIME_THRESHOLD_PCT,
    process_csv,
    process_work_items,
)
from lib.uptime_output import (
    print_console_summary,
    write_results_csv,
)


def main():
    parser = argparse.ArgumentParser(
        description="Feed-centric uptime measurement across publishers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process feeds from CSV file
  python feed_uptime.py --csv price_id_list.csv

  # Process a single feed
  python feed_uptime.py --feed-id 922 --date 2026-02-09 --mode us-equities

  # Multi-date range
  python feed_uptime.py --feed-id 922 --start-date 2026-02-09 --end-date 2026-02-12 --mode us-equities

  # Session flags for US equities
  python feed_uptime.py --feed-id 922 --date 2026-02-09 --mode us-equities --extended-hours --overnight

  # CSV filtering
  python feed_uptime.py --csv feeds.csv --include-asset-class us-equities fx
  python feed_uptime.py --csv feeds.csv --exclude-asset-class crypto
  python feed_uptime.py --csv feeds.csv --filter-feed-id 922 327

  # Threshold controls
  python feed_uptime.py --csv feeds.csv --uptime-threshold 95
  python feed_uptime.py --csv feeds.csv --precise --gap-threshold 100
""",
    )

    parser.add_argument(
        "--csv", type=Path, help="CSV file containing feed_id,date,mode columns"
    )
    parser.add_argument(
        "--feed-id", type=int, nargs="+", metavar="ID", help="Feed ID(s) to evaluate"
    )
    parser.add_argument(
        "--date",
        nargs="+",
        metavar="YYYY-MM-DD",
        help="Date(s) for single feed evaluation (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--start-date",
        help="Range start date (inclusive, YYYY-MM-DD) for single-feed mode",
    )
    parser.add_argument(
        "--end-date",
        help="Range end date (inclusive, YYYY-MM-DD) for single-feed mode",
    )
    parser.add_argument("--mode", type=str, help="Asset class for single feed mode")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("feed_uptime_results.csv"),
        help="Output CSV path (default: feed_uptime_results.csv)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of parallel workers (default: 4)",
    )
    parser.add_argument(
        "--include-asset-class",
        type=str,
        nargs="+",
        metavar="CLASS",
        help="Only process feeds with these asset classes (CSV mode)",
    )
    parser.add_argument(
        "--exclude-asset-class",
        type=str,
        nargs="+",
        metavar="CLASS",
        help="Exclude feeds with these asset classes (CSV mode)",
    )
    parser.add_argument(
        "--list-asset-classes",
        action="store_true",
        help="List unique asset classes in the CSV file and exit",
    )
    parser.add_argument(
        "--filter-feed-id",
        type=int,
        nargs="+",
        metavar="ID",
        help="Only process these feed IDs when using --csv",
    )
    parser.add_argument(
        "--extended-hours",
        action="store_true",
        help="Include premarket and after-hours sessions for US equities",
    )
    parser.add_argument(
        "--overnight",
        action="store_true",
        help="Include overnight session for US equities",
    )
    parser.add_argument(
        "--precise",
        action="store_true",
        help="Use 200ms gap-based method instead of default 1-second window",
    )
    parser.add_argument(
        "--gap-threshold",
        type=int,
        default=DEFAULT_GAP_THRESHOLD_MS,
        help="Gap threshold in milliseconds for --precise mode (default: 200)",
    )
    parser.add_argument(
        "--uptime-threshold",
        type=float,
        default=DEFAULT_UPTIME_THRESHOLD_PCT,
        help="Pass threshold percentage (default: 95.0)",
    )

    args = parser.parse_args()
    single_feed_dates: list[str] = []

    if args.workers <= 0:
        parser.error("--workers must be a positive integer")
    if args.gap_threshold <= 0:
        parser.error("--gap-threshold must be a positive integer")
    if not args.precise and args.gap_threshold != DEFAULT_GAP_THRESHOLD_MS:
        parser.error("--gap-threshold requires --precise")
    if args.uptime_threshold < 0 or args.uptime_threshold > 100:
        parser.error("--uptime-threshold must be between 0 and 100")

    if args.list_asset_classes:
        if not args.csv:
            parser.error("--list-asset-classes requires --csv")
    elif args.csv and (
        args.feed_id or args.date or args.start_date or args.end_date or args.mode
    ):
        parser.error(
            "Use either --csv OR (--feed-id, --date/--start-date+--end-date, --mode), not both"
        )
    elif not args.csv and not (args.feed_id and args.mode):
        parser.error(
            "Either --csv or all of (--feed-id, --date/--start-date+--end-date, --mode) required"
        )

    if not args.csv:
        try:
            validate_date_args(args)
            single_feed_dates = expand_date_args(
                args.date, args.start_date, args.end_date
            )
        except ValueError as e:
            parser.error(str(e))
        if not single_feed_dates:
            parser.error("Single-feed mode requires --date or --start-date/--end-date")

    if not args.csv and (args.include_asset_class or args.exclude_asset_class):
        parser.error(
            "--include-asset-class and --exclude-asset-class only apply to --csv mode"
        )

    if not args.csv and args.filter_feed_id:
        parser.error("--filter-feed-id only applies to --csv mode")

    if args.include_asset_class and args.exclude_asset_class:
        include_set = {normalize_asset_class(ac) for ac in args.include_asset_class}
        exclude_set = {normalize_asset_class(ac) for ac in args.exclude_asset_class}
        overlap = include_set & exclude_set
        if overlap:
            parser.error(
                f"Asset classes cannot be both included and excluded: {overlap}"
            )

    if args.csv and not args.csv.exists():
        print(f"Error: CSV file '{args.csv}' not found")
        sys.exit(1)

    if args.list_asset_classes:
        asset_classes = list_asset_classes_in_csv(args.csv)
        total_feeds = sum(asset_classes.values())

        print(f"\nAsset classes in {args.csv}:")
        print(f"{'=' * 50}")
        for asset_class, count in sorted(asset_classes.items(), key=lambda x: -x[1]):
            normalized = normalize_asset_class(asset_class)
            print(f"  {asset_class:<25} {count:>5} feeds  [normalized: {normalized}]")
        print(f"{'=' * 50}")
        print(f"  {'TOTAL':<25} {total_feeds:>5} feeds")
        sys.exit(0)

    total_start = time.time()
    results: list[FeedUptimeResult]
    if args.csv:
        feed_id_filter = set(args.filter_feed_id) if args.filter_feed_id else None
        results = process_csv(
            csv_path=args.csv,
            max_workers=args.workers,
            include_asset_classes=args.include_asset_class,
            exclude_asset_classes=args.exclude_asset_class,
            include_extended_hours=args.extended_hours,
            include_overnight=args.overnight,
            feed_id_filter=feed_id_filter,
            precise=args.precise,
            gap_threshold_ms=args.gap_threshold,
            uptime_threshold_pct=args.uptime_threshold,
        )
    else:
        work_items = [
            (feed_id, date, args.mode)
            for feed_id in args.feed_id
            for date in single_feed_dates
        ]
        results = process_work_items(
            work_items=work_items,
            max_workers=args.workers,
            include_extended_hours=args.extended_hours,
            include_overnight=args.overnight,
            precise=args.precise,
            gap_threshold_ms=args.gap_threshold,
            uptime_threshold_pct=args.uptime_threshold,
        )

    write_results_csv(results, args.output, precise=args.precise)
    total_time = time.time() - total_start
    print_console_summary(
        results=results,
        total_time_seconds=total_time,
        precise=args.precise,
        gap_threshold_ms=args.gap_threshold,
        uptime_threshold_pct=args.uptime_threshold,
    )
    print(f"\nResults written to: {args.output}")


if __name__ == "__main__":
    main()
