#!/usr/bin/env python3
"""
Feed-level benchmark evaluation script for Lazer feeds.

This script evaluates feed readiness across all publishers for each feed against
benchmark data (Datascope). It is the feed-level counterpart to
publisher_benchmark.py.

Pass/Fail Criteria (per publisher):
- PASS if: nrmse < 0.01 OR (nrmse < 0.05 AND hit_rate >= threshold)
- nrmse = RMSE / (max_benchmark_price - min_benchmark_price)
- hit_rate = % of observations within 10 basis points (0.1%) of benchmark

Feed readiness:
- READY if: passing_publisher_count >= target_publisher_count

Core evaluation logic lives in lib/benchmark_core.py.
Summary stats, CSV output, and publisher summaries live in lib/quick_benchmark_output.py.

Usage:
    python quick_benchmark.py --csv price_id_list.csv
    python quick_benchmark.py --feed-id 327 --date 2025-10-06 --mode fx
"""

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from date_utils import expand_date_args, validate_date_args
from lib.benchmark_core import (
    evaluate_feed_two_queries,
    list_asset_classes_in_csv,
    process_csv,
)
from lib.config import (
    BENCHMARKABLE_ASSET_CLASSES,
    get_clients,
    load_config,
    normalize_asset_class,
)
from lib.models import BenchmarkResult
from lib.quick_benchmark_output import (
    print_console_summary,
    write_results_csv,
)


def main():
    parser = argparse.ArgumentParser(
        description="Feed-level benchmark evaluation for Lazer feeds",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process feeds from CSV file
  python quick_benchmark.py --csv price_id_list.csv

  # Process a single feed
  python quick_benchmark.py --feed-id 327 --date 2025-10-06 --mode fx

  # Multiple feed IDs
  python quick_benchmark.py --feed-id 327 328 329 --date 2025-10-06 --mode fx

  # Multiple feed IDs x multiple dates (cartesian product)
  python quick_benchmark.py --feed-id 327 328 --date 2025-10-06 2025-10-07 --mode fx

  # Include US-equity extended hours
  python quick_benchmark.py --feed-id 1163 --date 2025-10-02 --mode us-equities --extended-hours

  # Include overnight session against publisher 32
  python quick_benchmark.py --feed-id 1163 --date 2025-10-02 --mode us-equities --overnight

  # Skip scipy tests for faster runs
  python quick_benchmark.py --csv price_id_list.csv --skip-scipy-tests

  # Output detailed per-publisher rows
  python quick_benchmark.py --csv price_id_list.csv --detailed

  # Filter CSV run to specific feed IDs
  python quick_benchmark.py --csv price_id_list.csv --filter-feed-id 327 1163
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
    parser.add_argument(
        "--mode",
        choices=[
            "fx",
            "metals",
            "us-equities",
            "commodity",
            "us-treasuries",
            "treasuries",
            "rates",
        ],
        help="Mode for single feed evaluation",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("quick_benchmark_results.csv"),
        help="Output CSV path (default: quick_benchmark_results.csv)",
    )
    parser.add_argument(
        "--target-pub-count",
        type=int,
        default=4,
        help="Target publisher count for feed readiness (default: 4)",
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
        help="Only process feeds with these asset classes",
    )
    parser.add_argument(
        "--exclude-asset-class",
        type=str,
        nargs="+",
        metavar="CLASS",
        help="Exclude feeds with these asset classes",
    )
    parser.add_argument(
        "--extended-hours",
        action="store_true",
        help="Include pre-market and after-hours evaluation for US equities",
    )
    parser.add_argument(
        "--overnight",
        action="store_true",
        help="Include overnight evaluation for US equities using publisher 32 as reference",
    )
    parser.add_argument(
        "--skip-scipy-tests",
        action="store_true",
        help="Skip t-test/Wilcoxon/normality tests for faster execution",
    )
    parser.add_argument(
        "--detailed",
        action="store_true",
        help="Append detailed per-publisher rows to CSV output",
    )
    parser.add_argument(
        "--filter-feed-id",
        type=int,
        nargs="+",
        metavar="ID",
        help="Only process these feed IDs when using --csv",
    )
    parser.add_argument(
        "--list-asset-classes",
        action="store_true",
        help="List unique asset classes in the CSV file and exit",
    )
    parser.add_argument(
        "--hit-rate-threshold",
        type=float,
        default=95,
        help="Hit rate pass threshold percentage (default: 95). Use 98 for strict mode.",
    )

    args = parser.parse_args()

    single_feed_dates: list[str] = []

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
        print(f"{'='*50}")
        for ac, count in sorted(asset_classes.items(), key=lambda x: -x[1]):
            normalized = normalize_asset_class(ac)
            benchmarkable = "Y" if normalized in BENCHMARKABLE_ASSET_CLASSES else "N"
            print(f"  {ac:<25} {count:>5} feeds  [benchmarkable: {benchmarkable}]")
        print(f"{'='*50}")
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
            args.csv,
            args.output,
            args.target_pub_count,
            args.workers,
            include_asset_classes=args.include_asset_class,
            exclude_asset_classes=args.exclude_asset_class,
            include_extended_hours=args.extended_hours,
            include_overnight=args.overnight,
            skip_scipy_tests=args.skip_scipy_tests,
            include_detailed=args.detailed,
            feed_id_filter=feed_id_filter,
            hit_rate_threshold=args.hit_rate_threshold,
            write_results_fn=write_results_csv,
        )
    else:
        config = load_config()
        results = []

        # Build cartesian product of feed_ids x dates
        feed_date_pairs = [(fid, d) for fid in args.feed_id for d in single_feed_dates]

        if args.workers > 1 and len(feed_date_pairs) > 1:

            def evaluate_single(feed_id: int, date_value: str) -> BenchmarkResult:
                client_lazer, client_analytics = get_clients(config)
                return evaluate_feed_two_queries(
                    client_lazer,
                    client_analytics,
                    feed_id,
                    date_value,
                    args.mode,
                    target_pub_count=args.target_pub_count,
                    include_extended_hours=args.extended_hours,
                    include_overnight=args.overnight,
                    skip_scipy_tests=args.skip_scipy_tests,
                    include_detailed=args.detailed,
                    hit_rate_threshold=args.hit_rate_threshold,
                )

            worker_count = min(args.workers, len(feed_date_pairs))
            with ThreadPoolExecutor(max_workers=worker_count) as executor:
                futures = {
                    executor.submit(evaluate_single, fid, d): (fid, d)
                    for fid, d in feed_date_pairs
                }
                for future in as_completed(futures):
                    results.append(future.result())
        else:
            client_lazer, client_analytics = get_clients(config)
            for feed_id, date_value in feed_date_pairs:
                results.append(
                    evaluate_feed_two_queries(
                        client_lazer,
                        client_analytics,
                        feed_id,
                        date_value,
                        args.mode,
                        target_pub_count=args.target_pub_count,
                        include_extended_hours=args.extended_hours,
                        include_overnight=args.overnight,
                        skip_scipy_tests=args.skip_scipy_tests,
                        include_detailed=args.detailed,
                        hit_rate_threshold=args.hit_rate_threshold,
                    )
                )

        results.sort(key=lambda r: (r.date, r.feed_id))
        write_results_csv(
            results,
            args.output,
            include_extended_hours=args.extended_hours,
            include_overnight=args.overnight,
            include_detailed=args.detailed,
        )

    total_time = time.time() - total_start
    print_console_summary(
        results,
        total_time,
        include_extended_hours=args.extended_hours,
        include_overnight=args.overnight,
        hit_rate_threshold=args.hit_rate_threshold,
    )


if __name__ == "__main__":
    main()
