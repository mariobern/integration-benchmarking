#!/usr/bin/env python3
"""
Single-publisher benchmark evaluation script for Lazer feeds.

This script evaluates a SINGLE publisher's data quality against benchmark data (Datascope).
It is significantly faster than quick_benchmark.py because it only queries and evaluates
one publisher instead of all publishers.

The publisher ID can be extracted from CSV filename pattern: publisher_{id}_feeds.csv.
In single-feed mode (without CSV), publisher ID must be provided explicitly.

Pass/Fail Criteria:
- A publisher PASSES if: nrmse < 0.01 OR (nrmse < 0.05 AND hit_rate >= threshold)
- nrmse = RMSE / (max_benchmark_price - min_benchmark_price)
- hit_rate = % of observations within 10 basis points (0.1%) of benchmark
- rmse_over_spread is reported as an additional metric but NOT used for pass/fail

Market Hours Filtering:
- US equities: Only regular trading hours (9:30 AM - 4:00 PM EST) are evaluated
- Other asset classes: Full day data is evaluated

Core evaluation logic lives in lib/publisher_eval.py.
Summary stats, CSV output, and interpretation guide live in lib/publisher_output.py.

Usage:
    python publisher_benchmark.py --csv publisher_55_feeds.csv
    python publisher_benchmark.py --csv feeds.csv --publisher-id 55
    python publisher_benchmark.py --publisher-id 55 --feed-id 327 --date 2025-10-06 --mode fx
"""

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from date_utils import expand_date_args, validate_date_args
from lib.benchmark_core import list_asset_classes_in_csv
from lib.config import (
    BENCHMARKABLE_ASSET_CLASSES,
    get_clients,
    load_config,
    normalize_asset_class,
)
from lib.models import (
    OVERNIGHT_REFERENCE_PUBLISHER_ID,
    PublisherBenchmarkResult,
)
from lib.publisher_eval import (
    evaluate_publisher_feed,
    extract_publisher_id_from_filename,
    process_csv,
)
from lib.publisher_output import (
    compute_summary_stats,
    print_interpretation_guide,
    write_results_csv,
)
from lib.thresholds import get_session_thresholds, get_threshold_description


def main():
    parser = argparse.ArgumentParser(
        description="Single-publisher benchmark evaluation for Lazer feeds (faster than quick_benchmark.py)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python publisher_benchmark.py --csv publisher_55_feeds.csv
  python publisher_benchmark.py --csv feeds.csv --publisher-id 55
  python publisher_benchmark.py --publisher-id 55 --feed-id 327 --date 2025-10-06 --mode fx
  python publisher_benchmark.py --csv publisher_55_feeds.csv --list-asset-classes
  python publisher_benchmark.py --csv publisher_55_feeds.csv --include-asset-class fx metals us-equities
  python publisher_benchmark.py --csv publisher_55_feeds.csv --feed-id 327 1163
  python publisher_benchmark.py --csv publisher_55_feeds.csv --feed-id 500 --overnight
  python publisher_benchmark.py --publisher-id 55 --feed-id 327 328 --date 2025-10-06 2025-10-07 --mode us-equities
  python publisher_benchmark.py --publisher-id 55 --feed-id 327 --start-date 2025-10-01 --end-date 2025-10-06 --mode fx
""",
    )

    parser.add_argument(
        "--csv", type=Path, help="CSV file containing feed_id,date,mode columns"
    )
    parser.add_argument("--publisher-id", type=int, help="Publisher ID to evaluate")
    parser.add_argument("--output", type=Path, help="Output CSV path")
    parser.add_argument(
        "--workers", type=int, default=4, help="Number of parallel workers (default: 4)"
    )
    parser.add_argument(
        "--date", nargs="+", metavar="YYYY-MM-DD", help="Date(s) to evaluate"
    )
    parser.add_argument("--start-date", help="Range start date (inclusive, YYYY-MM-DD)")
    parser.add_argument("--end-date", help="Range end date (inclusive, YYYY-MM-DD)")
    parser.add_argument(
        "--mode",
        type=str,
        help="Asset class: fx, metals, us-equities, commodity, us-treasuries",
    )
    parser.add_argument(
        "--include-asset-class",
        type=str,
        nargs="+",
        metavar="CLASS",
        help="Only process these asset classes",
    )
    parser.add_argument(
        "--exclude-asset-class",
        type=str,
        nargs="+",
        metavar="CLASS",
        help="Exclude these asset classes",
    )
    parser.add_argument(
        "--feed-id",
        type=int,
        nargs="+",
        metavar="ID",
        dest="feed_ids",
        help="Feed ID(s) to evaluate or filter",
    )
    parser.add_argument(
        "--list-asset-classes",
        action="store_true",
        help="List unique asset classes in CSV and exit",
    )
    parser.add_argument(
        "--extended-hours",
        action="store_true",
        help="Include extended hours for US equities",
    )
    parser.add_argument(
        "--overnight",
        action="store_true",
        help="Include overnight session for US equities",
    )
    parser.add_argument(
        "--skip-scipy-tests",
        action="store_true",
        help="Skip scipy statistical tests for faster execution",
    )
    parser.add_argument(
        "--hit-rate-threshold",
        type=float,
        default=95,
        help="Hit rate pass threshold percentage (default: 95)",
    )

    args = parser.parse_args()

    if args.list_asset_classes and not args.csv:
        parser.error("--list-asset-classes requires --csv")
    if not args.csv and (args.include_asset_class or args.exclude_asset_class):
        parser.error(
            "--include-asset-class and --exclude-asset-class only apply to --csv mode"
        )
    if args.csv and args.mode:
        parser.error(
            "--mode is for single-feed mode. Use either --csv OR (--feed-id, --date, --mode)"
        )
    elif not args.csv and not (args.feed_ids and args.mode):
        parser.error("Either --csv or all of (--feed-id, --date, --mode) are required")

    date_override: list[str] | None = None
    resolved_dates: list[str] = []
    if args.csv and not args.list_asset_classes:
        try:
            validate_date_args(args)
            resolved_dates = expand_date_args(args.date, args.start_date, args.end_date)
            date_override = resolved_dates if resolved_dates else None
        except ValueError as e:
            parser.error(str(e))
    elif not args.csv:
        try:
            validate_date_args(args)
            resolved_dates = expand_date_args(args.date, args.start_date, args.end_date)
        except ValueError as e:
            parser.error(str(e))
        if not resolved_dates:
            parser.error("Single-feed mode requires --date or --start-date/--end-date")
        if args.publisher_id is None:
            parser.error("--publisher-id is required in single-feed mode")

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

    publisher_id = args.publisher_id
    if args.csv and publisher_id is None:
        publisher_id = extract_publisher_id_from_filename(args.csv.name)
        if publisher_id is None:
            print(
                f"Error: Could not extract publisher ID from filename '{args.csv.name}'"
            )
            print(
                "Expected format: publisher_{{id}}_feeds.csv (e.g., publisher_55_feeds.csv)"
            )
            print("Or use --publisher-id to specify explicitly")
            sys.exit(1)
        print(f"Extracted publisher ID {publisher_id} from filename")

    if args.include_asset_class and args.exclude_asset_class:
        include_set = {normalize_asset_class(ac) for ac in args.include_asset_class}
        exclude_set = {normalize_asset_class(ac) for ac in args.exclude_asset_class}
        overlap = include_set & exclude_set
        if overlap:
            parser.error(
                f"Asset classes cannot be both included and excluded: {overlap}"
            )

    output_path = args.output
    if output_path is None:
        output_path = Path(f"publisher_{publisher_id}_benchmark_results.csv")

    total_start = time.time()
    feed_id_filter = set(args.feed_ids) if args.feed_ids else None

    if args.csv:
        results = process_csv(
            args.csv,
            publisher_id,
            args.workers,
            date_override=date_override,
            include_asset_classes=args.include_asset_class,
            exclude_asset_classes=args.exclude_asset_class,
            include_extended_hours=args.extended_hours,
            include_overnight=args.overnight,
            feed_id_filter=feed_id_filter,
            skip_scipy_tests=args.skip_scipy_tests,
            hit_rate_threshold=args.hit_rate_threshold,
        )
    else:
        config = load_config()
        results = []
        feed_date_pairs = [
            (feed_id, date_value, args.mode)
            for feed_id in args.feed_ids
            for date_value in resolved_dates
        ]

        print(
            f"Processing {len(feed_date_pairs)} feed-date evaluations "
            f"for publisher {publisher_id} with {args.workers} workers..."
        )

        def evaluate_single(args_tuple):
            feed_id, date_value, mode = args_tuple
            client_lazer, client_analytics = get_clients(config)
            return evaluate_publisher_feed(
                client_lazer,
                client_analytics,
                publisher_id,
                feed_id,
                date_value,
                mode,
                include_extended_hours=args.extended_hours,
                include_overnight=args.overnight,
                skip_scipy_tests=args.skip_scipy_tests,
                hit_rate_threshold=args.hit_rate_threshold,
            )

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(evaluate_single, task): task for task in feed_date_pairs
            }
            for future in as_completed(futures):
                result = future.result()
                results.append(result)
                status = "PASS" if result.passes else "FAIL"
                if result.error:
                    status = f"ERROR: {result.error[:50]}"
                nrmse_str = f"{result.nrmse:.4f}" if result.nrmse is not None else "N/A"
                hit_rate_str = (
                    f"{result.hit_rate:.1f}%" if result.hit_rate is not None else "N/A"
                )
                print(
                    f"  [{result.execution_time_ms:>4}ms] Feed {result.feed_id} "
                    f"({result.symbol or 'unknown'}): {status} - nrmse={nrmse_str}, "
                    f"hit_rate={hit_rate_str}, n={result.n_observations}"
                )

    total_time = time.time() - total_start
    summary_stats = compute_summary_stats(
        results,
        publisher_id,
        total_time,
        include_extended_hours=args.extended_hours,
        include_overnight=args.overnight,
        hit_rate_threshold=args.hit_rate_threshold,
    )

    write_results_csv(
        results,
        output_path,
        summary_stats,
        include_extended_hours=args.extended_hours,
        include_overnight=args.overnight,
    )

    # Print console summary
    print(f"\n{'='*70}")
    print(f"SUMMARY - Publisher {publisher_id}")
    print(f"{'='*70}")
    modes = {r.mode for r in results if r.mode}
    primary_mode = next(iter(modes)) if len(modes) == 1 else "us-equities"
    print(f"Pass criteria: {get_threshold_description(primary_mode)}")
    print(f"{'='*70}")
    print(f"Total feeds evaluated: {summary_stats['total_feeds']}")
    print(f"PASS: {summary_stats['pass_count']}")
    print(f"  - by nrmse < 0.01 alone: {summary_stats['pass_by_nrmse_alone']}")
    t = get_session_thresholds("regular", primary_mode)
    print(
        f"  - by nrmse < {t.nrmse_conditional} + hit_rate >= {t.hit_rate_threshold}%: {summary_stats['pass_by_nrmse_and_hit_rate']}"
    )
    print(f"FAIL: {summary_stats['fail_count']}")
    print(f"Errors: {summary_stats['error_count']}")
    print(f"Pass rate: {summary_stats['pass_rate_pct']:.1f}%")
    print(f"{'='*70}")
    print("NRMSE Statistics (lower is better):")
    if summary_stats["median_nrmse"] is not None:
        print(f"  Median: {summary_stats['median_nrmse']:.6f}")
        print(f"  Mean: {summary_stats['mean_nrmse']:.6f}")
        print(f"  P90: {summary_stats['p90_nrmse']:.6f}")
        print(f"  P95: {summary_stats['p95_nrmse']:.6f}")
        print(f"  Min: {summary_stats['min_nrmse']:.6f}")
        print(f"  Max: {summary_stats['max_nrmse']:.6f}")
    else:
        print("  No valid NRMSE data")
    print(f"{'='*70}")
    print("Hit Rate Statistics (higher is better, % within 10 bps):")
    if summary_stats["median_hit_rate"] is not None:
        print(f"  Median: {summary_stats['median_hit_rate']:.2f}%")
        print(f"  Mean: {summary_stats['mean_hit_rate']:.2f}%")
        print(f"  Min: {summary_stats['min_hit_rate']:.2f}%")
        print(f"  Max: {summary_stats['max_hit_rate']:.2f}%")
    else:
        print("  No valid hit rate data")
    print(f"{'='*70}")
    print("RMSE/Spread Statistics (reference metric, not used for pass/fail):")
    if summary_stats["median_rmse_over_spread"] is not None:
        print(f"  Median: {summary_stats['median_rmse_over_spread']:.4f}")
        print(f"  Mean: {summary_stats['mean_rmse_over_spread']:.4f}")
        print(f"  P90: {summary_stats['p90_rmse_over_spread']:.4f}")
        print(f"  P95: {summary_stats['p95_rmse_over_spread']:.4f}")
    else:
        print("  No valid rmse/spread data")
    print(f"{'='*70}")
    print(f"Total observations: {summary_stats['total_observations']:,}")
    print(
        f"Mean observations per feed: {summary_stats['mean_observations_per_feed']:,.1f}"
    )
    print(
        f"Median observations per feed: {summary_stats['median_observations_per_feed']:,}"
    )
    print(f"{'='*70}")
    print(f"Total time: {summary_stats['total_time_sec']:.2f}s")
    if summary_stats["total_feeds"] > 0:
        print(f"Average time per feed: {summary_stats['avg_time_per_feed_ms']}ms")
    else:
        print("No feeds were processed (all filtered out or empty CSV)")

    mode_stats = summary_stats.get("mode_stats", {})
    if mode_stats:
        print(f"{'='*60}")
        print("BREAKDOWN BY ASSET CLASS:")
        for mode in sorted(mode_stats.keys()):
            stats = mode_stats[mode]
            total = stats["pass"] + stats["fail"] + stats["error"]
            pass_rate = (stats["pass"] / total * 100) if total > 0 else 0
            print(
                f"  {mode:<15}: {stats['pass']:>3} pass, {stats['fail']:>3} fail, "
                f"{stats['error']:>3} error ({pass_rate:.1f}% pass rate)"
            )

    per_date_breakdown = summary_stats.get("per_date_breakdown", {})
    if len(per_date_breakdown) > 1:
        print(f"\n{'='*70}")
        print("PER-DATE BREAKDOWN")
        print("Date          Total  Pass  Fail  Error  Pass%  Med NRMSE  Med Hit%")
        for date_value in sorted(per_date_breakdown):
            date_stats = per_date_breakdown[date_value]
            median_nrmse = (
                f"{date_stats['median_nrmse']:.6f}"
                if date_stats.get("median_nrmse") is not None
                else "N/A"
            )
            median_hit_rate = (
                f"{date_stats['median_hit_rate']:.2f}%"
                if date_stats.get("median_hit_rate") is not None
                else "N/A"
            )
            print(
                f"{date_value:<12}  "
                f"{int(date_stats.get('total', 0)):>5}  "
                f"{int(date_stats.get('pass', 0)):>4}  "
                f"{int(date_stats.get('fail', 0)):>4}  "
                f"{int(date_stats.get('error', 0)):>5}  "
                f"{float(date_stats.get('pass_rate_pct', 0)):>5.1f}%  "
                f"{median_nrmse:>9}  "
                f"{median_hit_rate:>8}"
            )

    if args.extended_hours:
        ext_stats = summary_stats.get("extended_hours", {})
        if ext_stats:
            print(f"\n{'='*70}")
            print("EXTENDED HOURS - US EQUITIES ONLY")
            print(f"{'='*70}")
            print("\nPRE-MARKET (4:00 AM - 9:30 AM EST):")
            pm_total = ext_stats.get("premarket_total_feeds", 0)
            if pm_total > 0:
                print(f"  Total feeds: {pm_total}")
                print(f"  PASS: {ext_stats.get('premarket_pass_count', 0)}")
                print(f"  FAIL: {ext_stats.get('premarket_fail_count', 0)}")
                print(f"  Errors: {ext_stats.get('premarket_error_count', 0)}")
                print(
                    f"  Pass rate: {ext_stats.get('premarket_pass_rate_pct', 0):.1f}%"
                )
                pm_nrmse = ext_stats.get("premarket_median_nrmse")
                pm_hr = ext_stats.get("premarket_median_hit_rate")
                if pm_nrmse is not None:
                    print(f"  Median NRMSE: {pm_nrmse:.6f}")
                if pm_hr is not None:
                    print(f"  Median Hit Rate: {pm_hr:.2f}%")
            else:
                print("  No pre-market data available")
            print("\nAFTER-HOURS (4:00 PM - 8:00 PM EST):")
            ah_total = ext_stats.get("afterhours_total_feeds", 0)
            if ah_total > 0:
                print(f"  Total feeds: {ah_total}")
                print(f"  PASS: {ext_stats.get('afterhours_pass_count', 0)}")
                print(f"  FAIL: {ext_stats.get('afterhours_fail_count', 0)}")
                print(f"  Errors: {ext_stats.get('afterhours_error_count', 0)}")
                print(
                    f"  Pass rate: {ext_stats.get('afterhours_pass_rate_pct', 0):.1f}%"
                )
                ah_nrmse = ext_stats.get("afterhours_median_nrmse")
                ah_hr = ext_stats.get("afterhours_median_hit_rate")
                if ah_nrmse is not None:
                    print(f"  Median NRMSE: {ah_nrmse:.6f}")
                if ah_hr is not None:
                    print(f"  Median Hit Rate: {ah_hr:.2f}%")
            else:
                print("  No after-hours data available")

    if args.overnight:
        overnight_s = summary_stats.get("overnight", {})
        if overnight_s:
            print(f"\n{'='*70}")
            print("OVERNIGHT SESSION - US EQUITIES ONLY")
            print(f"{'='*70}")
            print(
                f"Benchmark reference: Publisher {overnight_s.get('overnight_reference_publisher_id', 32)} (Blue Ocean ATS)"
            )
            print(
                "NOTE: This is a publisher-vs-publisher comparison, not an official benchmark."
            )
            print(f"{'='*70}")
            on_total = overnight_s.get("overnight_total_feeds", 0)
            if on_total > 0:
                print(f"\nOVERNIGHT (8:00 PM - 4:00 AM EST):")
                print(f"  Total feeds: {on_total}")
                print(f"  PASS: {overnight_s.get('overnight_pass_count', 0)}")
                print(f"  FAIL: {overnight_s.get('overnight_fail_count', 0)}")
                print(f"  Errors: {overnight_s.get('overnight_error_count', 0)}")
                print(
                    f"  Pass rate: {overnight_s.get('overnight_pass_rate_pct', 0):.1f}%"
                )
                on_nrmse = overnight_s.get("overnight_median_nrmse")
                on_hr = overnight_s.get("overnight_median_hit_rate")
                if on_nrmse is not None:
                    print(f"  Median NRMSE: {on_nrmse:.6f}")
                if on_hr is not None:
                    print(f"  Median Hit Rate: {on_hr:.2f}%")
            else:
                print("  No overnight data available")

    print_interpretation_guide(
        summary_stats, hit_rate_threshold=args.hit_rate_threshold, mode=primary_mode
    )


if __name__ == "__main__":
    main()
