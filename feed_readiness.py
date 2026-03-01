#!/usr/bin/env python3
"""
Combined feed readiness evaluator (benchmark quality + publisher uptime).

A feed is READY only when at least target publisher count pass both:
- benchmark quality (quick_benchmark rules)
- regular-session uptime threshold (feed_uptime rules)

Core evaluation logic lives in lib/readiness_core.py.
Output formatting, CSV writing, and summary stats live in lib/readiness_output.py.
This file is the CLI wrapper.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from date_utils import expand_date_args, validate_date_args
from lib.benchmark_core import list_asset_classes_in_csv
from lib.config import (
    ASSET_CLASS_ALIASES,
    BENCHMARKABLE_ASSET_CLASSES,
    normalize_asset_class,
)
from lib.readiness_core import (
    FeedReadinessResult,
    PublisherReadinessDetail,
    evaluate_feed_readiness,
    merge_results,
    process_csv,
    process_work_items,
)
from lib.readiness_output import (
    _afterhours_status,
    _overnight_status,
    _premarket_status,
    compute_publisher_consistency,
    compute_summary_stats,
    print_console_summary,
    print_publisher_consistency,
    write_publisher_consistency_csv,
    write_results_csv,
    write_summary_csv,
)
from lib.uptime_core import (
    DEFAULT_GAP_THRESHOLD_MS,
    DEFAULT_UPTIME_THRESHOLD_PCT,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Combined feed readiness (benchmark quality + uptime)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single feed, single date
  python feed_readiness.py --feed-id 327 --date 2026-02-10 --mode fx

  # Multi-date range
  python feed_readiness.py --feed-id 327 --start-date 2026-02-10 --end-date 2026-02-12 --mode fx

  # CSV batch
  python feed_readiness.py --csv price_id_list.csv --workers 8

  # With uptime precision + extended hours
  python feed_readiness.py --feed-id 922 --date 2026-02-10 --mode us-equities --precise --extended-hours

  # Detailed mode
  python feed_readiness.py --feed-id 327 --date 2026-02-10 --mode fx --detailed
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
    parser.add_argument("--start-date", help="Range start date (inclusive, YYYY-MM-DD)")
    parser.add_argument("--end-date", help="Range end date (inclusive, YYYY-MM-DD)")
    parser.add_argument("--mode", type=str, help="Asset class for single feed mode")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("feed_readiness_results.csv"),
        help="Output CSV path (default: feed_readiness_results.csv)",
    )
    parser.add_argument(
        "--detailed",
        action="store_true",
        help="Append PUBLISHER DETAIL and consistency sections to CSV",
    )
    parser.add_argument(
        "--target-pub-count",
        type=int,
        default=4,
        help="Target publisher count for feed readiness (default: 4)",
    )
    parser.add_argument(
        "--skip-scipy-tests",
        action="store_true",
        help="Skip benchmark t-test/Wilcoxon/normality tests for faster execution",
    )
    parser.add_argument(
        "--precise",
        action="store_true",
        help="Use 200ms gap-based uptime method instead of default 1-second window",
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
        help="Regular-session uptime pass threshold percent (default: 95.0)",
    )
    parser.add_argument(
        "--extended-hours",
        action="store_true",
        help="Include pre-market and after-hours sessions for US equities",
    )
    parser.add_argument(
        "--overnight",
        action="store_true",
        help="Include overnight session for US equities",
    )
    parser.add_argument(
        "--alignment-tolerance-sec",
        type=int,
        default=60,
        help="Max seconds between publisher and benchmark timestamps for matching (default: 60)",
    )
    parser.add_argument(
        "--workers", type=int, default=4, help="Number of parallel workers (default: 4)"
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
        "--filter-feed-id",
        type=int,
        nargs="+",
        metavar="ID",
        help="Only process these feed IDs when using --csv",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Write a summary CSV of READY feeds only (feed_readiness_summary.csv)",
    )
    parser.add_argument(
        "--list-asset-classes",
        action="store_true",
        help="List unique asset classes in the CSV file and exit",
    )

    args = parser.parse_args()
    single_feed_dates: list[str] = []

    if args.workers <= 0:
        parser.error("--workers must be a positive integer")
    if args.target_pub_count <= 0:
        parser.error("--target-pub-count must be a positive integer")
    if args.gap_threshold <= 0:
        parser.error("--gap-threshold must be a positive integer")
    if not args.precise and args.gap_threshold != DEFAULT_GAP_THRESHOLD_MS:
        parser.error("--gap-threshold requires --precise")
    if args.uptime_threshold < 0 or args.uptime_threshold > 100:
        parser.error("--uptime-threshold must be between 0 and 100")
    if args.alignment_tolerance_sec < 0:
        parser.error("--alignment-tolerance-sec must be non-negative")

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
        except ValueError as exc:
            parser.error(str(exc))
        if not single_feed_dates:
            parser.error("Single-feed mode requires --date or --start-date/--end-date")

    if not args.csv and (args.include_asset_class or args.exclude_asset_class):
        parser.error(
            "--include-asset-class and --exclude-asset-class only apply to --csv mode"
        )
    if not args.csv and args.filter_feed_id:
        parser.error("--filter-feed-id only applies to --csv mode")

    if args.include_asset_class and args.exclude_asset_class:
        include_set = {
            normalize_asset_class(asset) for asset in args.include_asset_class
        }
        exclude_set = {
            normalize_asset_class(asset) for asset in args.exclude_asset_class
        }
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
        print(f"{'='*56}")
        for asset_class, count in sorted(asset_classes.items(), key=lambda x: -x[1]):
            normalized = normalize_asset_class(asset_class)
            benchmarkable = "Y" if normalized in BENCHMARKABLE_ASSET_CLASSES else "N"
            alias_display = ASSET_CLASS_ALIASES.get(
                asset_class.lower(), asset_class.lower()
            )
            print(
                f"  {asset_class:<25} {count:>5} feeds  "
                f"[normalized: {alias_display:<12} benchmarkable: {benchmarkable}]"
            )
        print(f"{'='*56}")
        print(f"  {'TOTAL':<25} {total_feeds:>5} feeds")
        print(
            f"\nBenchmarkable asset classes: {', '.join(sorted(BENCHMARKABLE_ASSET_CLASSES))}"
        )
        sys.exit(0)

    if args.extended_hours or args.overnight:
        if args.csv:
            print(
                "Note: --extended-hours and --overnight only apply to us-equities feeds; "
                "other asset classes are evaluated normally."
            )
        else:
            if normalize_asset_class(args.mode) != "us-equities":
                print(
                    "Warning: --extended-hours/--overnight only apply to us-equities; "
                    "session metrics will be skipped for this run."
                )

    total_start = time.time()
    if args.csv:
        feed_id_filter = set(args.filter_feed_id) if args.filter_feed_id else None
        results = process_csv(
            csv_path=args.csv,
            max_workers=args.workers,
            target_pub_count=args.target_pub_count,
            include_asset_classes=args.include_asset_class,
            exclude_asset_classes=args.exclude_asset_class,
            include_extended_hours=args.extended_hours,
            include_overnight=args.overnight,
            feed_id_filter=feed_id_filter,
            skip_scipy_tests=args.skip_scipy_tests,
            precise=args.precise,
            gap_threshold_ms=args.gap_threshold,
            uptime_threshold_pct=args.uptime_threshold,
            include_detailed=args.detailed,
            tolerance_seconds=args.alignment_tolerance_sec,
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
            target_pub_count=args.target_pub_count,
            include_extended_hours=args.extended_hours,
            include_overnight=args.overnight,
            skip_scipy_tests=args.skip_scipy_tests,
            precise=args.precise,
            gap_threshold_ms=args.gap_threshold,
            uptime_threshold_pct=args.uptime_threshold,
            include_detailed=args.detailed,
            tolerance_seconds=args.alignment_tolerance_sec,
        )

    write_results_csv(
        results=results,
        output_path=args.output,
        include_extended_hours=args.extended_hours,
        include_overnight=args.overnight,
        include_detailed=args.detailed,
    )

    if args.summary:
        stem = args.output.stem
        if "_results" in stem:
            summary_stem = stem.replace("_results", "_summary")
        else:
            summary_stem = f"{stem}_summary"
        summary_path = args.output.with_stem(summary_stem)
        ready_count = write_summary_csv(
            results=results,
            output_path=summary_path,
            include_extended_hours=args.extended_hours,
            include_overnight=args.overnight,
        )
        print(f"Summary written to: {summary_path} ({ready_count} ready feeds)")

    total_time = time.time() - total_start
    print_console_summary(
        results=results,
        total_time_seconds=total_time,
        target_pub_count=args.target_pub_count,
        uptime_threshold_pct=args.uptime_threshold,
    )

    if args.detailed and len({result.date for result in results}) > 1:
        consistency = compute_publisher_consistency(results)
        if consistency["rows"]:
            print_publisher_consistency(consistency)

        # Per-session consistency console output
        if args.extended_hours:
            for session_name, extractor in [
                ("PREMARKET", _premarket_status),
                ("AFTERHOURS", _afterhours_status),
            ]:
                session_consistency = compute_publisher_consistency(
                    results, status_extractor=extractor
                )
                if session_consistency["rows"]:
                    print_publisher_consistency(
                        session_consistency, session_prefix=f"{session_name} "
                    )

        if args.overnight:
            session_consistency = compute_publisher_consistency(
                results, status_extractor=_overnight_status
            )
            if session_consistency["rows"]:
                print_publisher_consistency(
                    session_consistency, session_prefix="OVERNIGHT "
                )

    print(f"\nResults written to: {args.output}")


if __name__ == "__main__":
    main()
