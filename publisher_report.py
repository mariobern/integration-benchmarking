#!/usr/bin/env python3
"""
Combined publisher health report: benchmark quality + uptime in one script.

Combines data quality evaluation (from lib/publisher_eval.py) with
uptime measurement (1s window method) to give publishers a unified health
view per feed.

Health Classification:
- HEALTHY:  Benchmark passes AND uptime >= threshold (default 95%)
- DEGRADED: One of benchmark or uptime fails, but not both
- FAILING:  Benchmark fails AND uptime < threshold

Core health logic lives in lib/publisher_health.py; this file is the CLI wrapper.

Usage:
    python publisher_report.py --csv publisher_55_feeds.csv
    python publisher_report.py --publisher-id 55 --feed-id 327 --date 2026-02-17 --mode fx
"""

import argparse
import csv
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Optional

from date_utils import expand_date_args, validate_date_args
from lib.benchmark_core import list_asset_classes_in_csv
from lib.config import (
    BENCHMARKABLE_ASSET_CLASSES,
    get_clients,
    load_config,
    normalize_asset_class,
)
from lib.publisher_eval import (
    evaluate_publisher_feed,
    extract_publisher_id_from_filename,
    process_csv,
)
from lib.publisher_health import (
    FeedHealthResult,
    classify_health,
    compute_feed_uptime,
    get_uptime_sessions,
    merge_benchmark_and_uptime,
    run_report,
)
from lib.publisher_output import print_interpretation_guide


def format_diagnostics(
    mean_diff: Optional[float],
    t_pvalue: Optional[float],
    normality_pvalue: Optional[float],
    mean_abs_z_score: Optional[float],
    passes: bool,
    uptime_pct: float,
    threshold: float,
) -> str:
    """
    Generate a concise diagnostic string for console output.

    Only produces diagnostics for non-HEALTHY feeds. Returns empty string for feeds
    that pass benchmark and have good uptime.
    """
    parts = []

    # Benchmark diagnostics (only for non-passing feeds)
    if not passes:
        if t_pvalue is not None and mean_diff is not None:
            if t_pvalue < 0.05:
                sign = "+" if mean_diff >= 0 else ""
                parts.append(f"Bias: {sign}{mean_diff:.4f} (significant)")
            else:
                parts.append("Bias: none")
        else:
            parts.append("Data quality: benchmark fail")

        if normality_pvalue is not None and normality_pvalue < 0.05:
            parts.append("Errors: has outliers")

        if mean_abs_z_score is not None and mean_abs_z_score > 1.5:
            parts.append(f"Deviation: {mean_abs_z_score:.1f} (volatile)")

    # Uptime diagnostic
    if uptime_pct < threshold:
        parts.append("Low uptime")

    return ", ".join(parts) if parts else ""


def print_health_report(
    results: list[FeedHealthResult],
    publisher_id: int,
    uptime_threshold: float = 95.0,
) -> None:
    """
    Print unified health report to console.

    Sections:
    1. Executive Summary - overall counts and key metrics
    2. Feeds Needing Attention - only non-HEALTHY feeds with diagnostics
    3. All Feeds - full table
    4. Action Items - what to fix
    """
    total = len(results)
    healthy_count = sum(1 for r in results if r.health_status == "HEALTHY")
    degraded_count = sum(1 for r in results if r.health_status == "DEGRADED")
    failing_count = sum(1 for r in results if r.health_status == "FAILING")

    pass_count = sum(1 for r in results if r.passes and not r.error)
    fail_count = sum(1 for r in results if not r.passes and not r.error)
    error_count = sum(1 for r in results if r.error)

    valid_nrmse = [r.nrmse for r in results if r.nrmse is not None and not r.error]
    median_nrmse = statistics.median(valid_nrmse) if valid_nrmse else None

    valid_uptime = [r.uptime_pct for r in results if not r.error]
    median_uptime = statistics.median(valid_uptime) if valid_uptime else None

    uptime_above = sum(
        1 for r in results if r.uptime_pct >= uptime_threshold and not r.error
    )

    # Collect unique dates for display
    dates = sorted({r.date for r in results})
    date_display = dates[0] if len(dates) == 1 else f"{dates[0]} to {dates[-1]}"

    # Section 1: Executive Summary
    print(f"\n{'='*70}")
    print(f"PUBLISHER HEALTH REPORT - Publisher {publisher_id} - {date_display}")
    print(f"{'='*70}")
    print(
        f"Overall: {healthy_count}/{total} feeds HEALTHY, "
        f"{degraded_count} DEGRADED, {failing_count} FAILING"
    )
    print()

    benchmark_str = (
        f"{pass_count}/{total} pass ({pass_count/total*100:.1f}%)"
        if total > 0
        else "N/A"
    )
    nrmse_str = (
        f"Median NRMSE: {median_nrmse:.6f}"
        if median_nrmse is not None
        else "Median NRMSE: N/A"
    )
    print(f"  Benchmark:  {benchmark_str:<25} |  {nrmse_str}")

    uptime_str = (
        f"{uptime_above}/{total} above {uptime_threshold:.0f}%" if total > 0 else "N/A"
    )
    uptime_med_str = (
        f"Median uptime: {median_uptime:.2f}%"
        if median_uptime is not None
        else "Median uptime: N/A"
    )
    print(f"  Uptime:     {uptime_str:<25} |  {uptime_med_str}")

    if error_count > 0:
        print(f"  Errors:     {error_count} feeds had errors")

    print(f"{'='*70}")

    # Section 2: Feeds Needing Attention
    attention_feeds = [r for r in results if r.health_status != "HEALTHY"]

    if not attention_feeds:
        print(f"\nAll feeds are HEALTHY - no action needed!")
    else:
        print(f"\nFEEDS NEEDING ATTENTION ({len(attention_feeds)} of {total}):")
        print(f"{'-'*90}")
        print(
            f"{'Feed':<8} {'Symbol':<25} {'Status':<10} {'Pass':<6} {'Uptime':<8} {'Diagnostics'}"
        )
        print(f"{'-'*90}")

        for r in sorted(
            attention_feeds,
            key=lambda x: (
                {"FAILING": 0, "DEGRADED": 1}.get(x.health_status, 2),
                x.feed_id,
            ),
        ):
            symbol_str = (r.symbol or "unknown")[:25]
            pass_str = "PASS" if r.passes else "FAIL"
            uptime_str = f"{r.uptime_pct:.1f}%"
            diag = format_diagnostics(
                r.mean_diff,
                r.t_pvalue,
                r.normality_pvalue,
                r.mean_abs_z_score,
                r.passes,
                r.uptime_pct,
                uptime_threshold,
            )
            print(
                f"{r.feed_id:<8} {symbol_str:<25} {r.health_status:<10} {pass_str:<6} {uptime_str:<8} {diag}"
            )

        print(f"{'-'*90}")

    # Section 3: All Feeds
    print(f"\nALL FEEDS:")
    print(f"{'-'*110}")
    print(
        f"{'Feed':<8} {'Symbol':<22} {'Date':<12} {'Mode':<14} {'Pass':<6} {'NRMSE':<10} {'Hit%':<8} {'Uptime%':<9} {'Status'}"
    )
    print(f"{'-'*110}")

    for r in sorted(results, key=lambda x: (x.date, x.feed_id)):
        symbol_str = (r.symbol or "unknown")[:22]
        pass_str = "PASS" if r.passes else ("ERR" if r.error else "FAIL")
        nrmse_str = f"{r.nrmse:.6f}" if r.nrmse is not None else "N/A"
        hit_str = f"{r.hit_rate:.1f}%" if r.hit_rate is not None else "N/A"
        uptime_str = f"{r.uptime_pct:.2f}%"
        print(
            f"{r.feed_id:<8} {symbol_str:<22} {r.date:<12} {r.mode:<14} {pass_str:<6} {nrmse_str:<10} {hit_str:<8} {uptime_str:<9} {r.health_status}"
        )

    print(f"{'-'*110}")

    # Section 4: Action Items
    quality_fails = sum(1 for r in results if not r.passes and not r.error)
    uptime_fails = sum(
        1 for r in results if r.uptime_pct < uptime_threshold and not r.error
    )

    if quality_fails > 0 or uptime_fails > 0:
        print(f"\n{'='*70}")
        print("HOW TO IMPROVE:")
        print(f"{'='*70}")
        if quality_fails > 0:
            print(f"  - {quality_fails} feed(s) failing data quality:")
            print(f"    Check price source calibration, reduce latency")
            print(f"    Target: nrmse < 0.01 or (nrmse < 0.05 + hit_rate >= 95%)")
        if uptime_fails > 0:
            print(
                f"  - {uptime_fails} feed(s) with low uptime (< {uptime_threshold:.0f}%):"
            )
            print(f"    Investigate connectivity gaps, increase update frequency")
        print(f"  - See CSV output for detailed per-feed metrics")
        print(f"{'='*70}")
    print()


def write_health_csv(
    results: list[FeedHealthResult],
    output_path: Path,
    include_extended_hours: bool = False,
    include_overnight: bool = False,
) -> None:
    """Write combined health report to CSV with SUMMARY section."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Base header
    header = [
        "publisher_id",
        "feed_id",
        "date",
        "mode",
        "symbol",
        "passes",
        "n_observations",
        "nrmse",
        "hit_rate",
        "benchmark_price_range",
        "rmse",
        "mean_spread",
        "rmse_over_spread",
        "mean_diff",
        "t_pvalue",
        "normality_pvalue",
        "mean_abs_z_score",
        "uptime_pct",
        "seconds_with_data",
        "total_seconds",
        "updates_total",
        "updates_per_second",
        "health_status",
    ]

    if include_extended_hours:
        header.extend(
            [
                "premarket_n_observations",
                "premarket_nrmse",
                "premarket_hit_rate",
                "premarket_passes",
                "premarket_uptime_pct",
                "premarket_error",
                "afterhours_n_observations",
                "afterhours_nrmse",
                "afterhours_hit_rate",
                "afterhours_passes",
                "afterhours_uptime_pct",
                "afterhours_error",
            ]
        )

    if include_overnight:
        header.extend(
            [
                "overnight_n_observations",
                "overnight_n_reference_observations",
                "overnight_nrmse",
                "overnight_hit_rate",
                "overnight_passes",
                "overnight_uptime_pct",
                "overnight_reference_publisher_id",
                "overnight_error",
            ]
        )

    header.extend(["error", "execution_time_ms"])

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)

        for r in sorted(results, key=lambda x: (x.date, x.feed_id)):
            row = [
                r.publisher_id,
                r.feed_id,
                r.date,
                r.mode,
                r.symbol or "",
                r.passes,
                r.n_observations,
                f"{r.nrmse:.6f}" if r.nrmse is not None else "",
                f"{r.hit_rate:.2f}" if r.hit_rate is not None else "",
                f"{r.benchmark_price_range:.6f}"
                if r.benchmark_price_range is not None
                else "",
                f"{r.rmse:.6f}" if r.rmse is not None else "",
                f"{r.mean_spread:.6f}" if r.mean_spread is not None else "",
                f"{r.rmse_over_spread:.6f}" if r.rmse_over_spread is not None else "",
                f"{r.mean_diff:.8f}" if r.mean_diff is not None else "",
                f"{r.t_pvalue:.6f}" if r.t_pvalue is not None else "",
                f"{r.normality_pvalue:.6f}" if r.normality_pvalue is not None else "",
                f"{r.mean_abs_z_score:.4f}" if r.mean_abs_z_score is not None else "",
                f"{r.uptime_pct:.2f}",
                r.seconds_with_data,
                r.total_seconds,
                r.updates_total,
                f"{r.updates_per_second:.1f}",
                r.health_status,
            ]

            if include_extended_hours:
                row.extend(
                    [
                        r.premarket_n_observations or "",
                        f"{r.premarket_nrmse:.6f}"
                        if r.premarket_nrmse is not None
                        else "",
                        f"{r.premarket_hit_rate:.2f}"
                        if r.premarket_hit_rate is not None
                        else "",
                        r.premarket_passes if r.premarket_passes is not None else "",
                        f"{r.premarket_uptime_pct:.2f}"
                        if r.premarket_uptime_pct is not None
                        else "",
                        r.premarket_error or "",
                        r.afterhours_n_observations or "",
                        f"{r.afterhours_nrmse:.6f}"
                        if r.afterhours_nrmse is not None
                        else "",
                        f"{r.afterhours_hit_rate:.2f}"
                        if r.afterhours_hit_rate is not None
                        else "",
                        r.afterhours_passes if r.afterhours_passes is not None else "",
                        f"{r.afterhours_uptime_pct:.2f}"
                        if r.afterhours_uptime_pct is not None
                        else "",
                        r.afterhours_error or "",
                    ]
                )

            if include_overnight:
                row.extend(
                    [
                        r.overnight_n_observations or "",
                        r.overnight_n_reference_observations or "",
                        f"{r.overnight_nrmse:.6f}"
                        if r.overnight_nrmse is not None
                        else "",
                        f"{r.overnight_hit_rate:.2f}"
                        if r.overnight_hit_rate is not None
                        else "",
                        r.overnight_passes if r.overnight_passes is not None else "",
                        f"{r.overnight_uptime_pct:.2f}"
                        if r.overnight_uptime_pct is not None
                        else "",
                        r.overnight_reference_publisher_id or "",
                        r.overnight_error or "",
                    ]
                )

            row.extend([r.error or "", r.execution_time_ms])
            writer.writerow(row)

        # SUMMARY section
        writer.writerow([])
        writer.writerow(["SUMMARY"])

        total = len(results)
        pass_count = sum(1 for r in results if r.passes and not r.error)
        fail_count = sum(1 for r in results if not r.passes and not r.error)
        error_count = sum(1 for r in results if r.error)
        healthy_count = sum(1 for r in results if r.health_status == "HEALTHY")
        degraded_count = sum(1 for r in results if r.health_status == "DEGRADED")
        failing_count = sum(1 for r in results if r.health_status == "FAILING")

        valid_nrmse = [r.nrmse for r in results if r.nrmse is not None and not r.error]
        valid_uptime = [r.uptime_pct for r in results if not r.error]
        valid_hit_rate = [
            r.hit_rate for r in results if r.hit_rate is not None and not r.error
        ]

        writer.writerow(["total_feeds", total])
        writer.writerow(["pass_count", pass_count])
        writer.writerow(["fail_count", fail_count])
        writer.writerow(["error_count", error_count])
        writer.writerow(
            ["pass_rate_pct", f"{pass_count/total*100:.1f}" if total > 0 else "0"]
        )
        writer.writerow(["healthy_count", healthy_count])
        writer.writerow(["degraded_count", degraded_count])
        writer.writerow(["failing_count", failing_count])
        writer.writerow(
            [
                "median_nrmse",
                f"{statistics.median(valid_nrmse):.6f}" if valid_nrmse else "",
            ]
        )
        writer.writerow(
            ["mean_nrmse", f"{statistics.mean(valid_nrmse):.6f}" if valid_nrmse else ""]
        )
        writer.writerow(
            [
                "median_hit_rate",
                f"{statistics.median(valid_hit_rate):.2f}" if valid_hit_rate else "",
            ]
        )
        writer.writerow(
            [
                "median_uptime_pct",
                f"{statistics.median(valid_uptime):.2f}" if valid_uptime else "",
            ]
        )
        writer.writerow(
            [
                "mean_uptime_pct",
                f"{statistics.mean(valid_uptime):.2f}" if valid_uptime else "",
            ]
        )

    print(f"Results written to {output_path}")


def main():
    parser = argparse.ArgumentParser(
        description="Combined publisher health report: benchmark quality + uptime",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full report from CSV
  python publisher_report.py --csv publisher_55_feeds.csv

  # With explicit publisher ID
  python publisher_report.py --csv feeds.csv --publisher-id 55

  # Single-feed mode
  python publisher_report.py --publisher-id 55 --feed-id 327 --date 2026-02-17 --mode fx

  # Multiple feeds x dates
  python publisher_report.py --publisher-id 55 --feed-id 327 328 --date 2026-02-17 2026-02-18 --mode fx

  # Date range
  python publisher_report.py --publisher-id 55 --feed-id 327 --start-date 2026-02-10 --end-date 2026-02-17 --mode fx

  # With extended hours and overnight
  python publisher_report.py --csv publisher_55_feeds.csv --extended-hours --overnight

  # Custom uptime threshold
  python publisher_report.py --csv publisher_55_feeds.csv --uptime-threshold 99.0

  # Skip statistical tests for faster execution
  python publisher_report.py --csv publisher_55_feeds.csv --skip-scipy-tests
""",
    )

    parser.add_argument(
        "--csv", type=Path, help="CSV file with feed_id,date,mode columns"
    )
    parser.add_argument("--publisher-id", type=int, help="Publisher ID")
    parser.add_argument("--output", type=Path, help="Output CSV path")
    parser.add_argument(
        "--workers", type=int, default=4, help="Parallel workers (default: 4)"
    )
    parser.add_argument(
        "--date", nargs="+", metavar="YYYY-MM-DD", help="Date(s) to evaluate"
    )
    parser.add_argument("--start-date", help="Range start date (inclusive)")
    parser.add_argument("--end-date", help="Range end date (inclusive)")
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
        help="Only these asset classes",
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
        help="Feed ID(s)",
    )
    parser.add_argument(
        "--list-asset-classes",
        action="store_true",
        help="List asset classes in CSV and exit",
    )
    parser.add_argument(
        "--extended-hours",
        action="store_true",
        help="Include extended hours (US equities)",
    )
    parser.add_argument(
        "--overnight",
        action="store_true",
        help="Include overnight session (US equities)",
    )
    parser.add_argument(
        "--skip-scipy-tests",
        action="store_true",
        help="Skip statistical tests for faster execution",
    )
    parser.add_argument(
        "--uptime-threshold",
        type=float,
        default=95.0,
        help="Minimum uptime %% for HEALTHY status (default: 95.0)",
    )

    args = parser.parse_args()

    # Validation (same as publisher_benchmark.py)
    if args.list_asset_classes and not args.csv:
        parser.error("--list-asset-classes requires --csv")

    if not args.csv and (args.include_asset_class or args.exclude_asset_class):
        parser.error(
            "--include-asset-class and --exclude-asset-class only apply to --csv mode"
        )

    if args.csv and args.mode:
        parser.error("--mode is for single-feed mode only")
    elif not args.csv and not (args.feed_ids and args.mode):
        parser.error("Either --csv or all of (--feed-id, --date, --mode) are required")

    date_override = None
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

    # Handle --list-asset-classes
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
        sys.exit(0)

    # Determine publisher ID
    publisher_id = args.publisher_id
    if args.csv and publisher_id is None:
        publisher_id = extract_publisher_id_from_filename(args.csv.name)
        if publisher_id is None:
            print(f"Error: Could not extract publisher ID from '{args.csv.name}'")
            print("Use --publisher-id to specify explicitly")
            sys.exit(1)
        print(f"Extracted publisher ID {publisher_id} from filename")

    # Validate include/exclude don't overlap
    if args.include_asset_class and args.exclude_asset_class:
        include_set = {normalize_asset_class(ac) for ac in args.include_asset_class}
        exclude_set = {normalize_asset_class(ac) for ac in args.exclude_asset_class}
        overlap = include_set & exclude_set
        if overlap:
            parser.error(f"Cannot both include and exclude: {overlap}")

    # Output path
    output_path = args.output or Path(f"publisher_{publisher_id}_health_report.csv")

    total_start = time.time()
    feed_id_filter = set(args.feed_ids) if args.feed_ids else None

    # Load config once for both phases
    config = load_config()

    # Phase 1: Run benchmark evaluation
    print(f"\n{'='*70}")
    print(f"PHASE 1: BENCHMARK EVALUATION - Publisher {publisher_id}")
    print(f"{'='*70}")

    if args.csv:
        benchmark_results = process_csv(
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
        )
    else:
        benchmark_results = []
        feed_date_pairs = [
            (fid, dv, args.mode) for fid in args.feed_ids for dv in resolved_dates
        ]
        print(
            f"Processing {len(feed_date_pairs)} evaluations with {args.workers} workers..."
        )

        def eval_single(args_tuple):
            fid, dv, mode = args_tuple
            cl, ca = get_clients(config)
            return evaluate_publisher_feed(
                cl,
                ca,
                publisher_id,
                fid,
                dv,
                mode,
                include_extended_hours=args.extended_hours,
                include_overnight=args.overnight,
                skip_scipy_tests=args.skip_scipy_tests,
            )

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(eval_single, t): t for t in feed_date_pairs}
            for future in as_completed(futures):
                t = futures[future]
                try:
                    r = future.result()
                    benchmark_results.append(r)
                    status = "PASS" if r.passes else "FAIL"
                    if r.error:
                        status = f"ERROR: {r.error[:50]}"
                    nrmse_s = f"{r.nrmse:.4f}" if r.nrmse is not None else "N/A"
                    print(
                        f"  Feed {r.feed_id} ({r.symbol or 'unknown'}): {status} nrmse={nrmse_s}"
                    )
                except Exception as e:
                    fid, dv, mode_val = t
                    print(f"  Feed {fid} ({dv}): ERROR - {e}")

    if not benchmark_results:
        print("No feeds to evaluate.")
        sys.exit(0)

    # Phase 2: Compute uptime and merge
    print(f"\n{'='*70}")
    print(f"PHASE 2: UPTIME COMPUTATION - Publisher {publisher_id}")
    print(f"{'='*70}")

    health_results = run_report(
        benchmark_results,
        publisher_id,
        config,
        uptime_threshold=args.uptime_threshold,
        include_extended_hours=args.extended_hours,
        include_overnight=args.overnight,
        max_workers=args.workers,
    )

    total_time = time.time() - total_start

    # Output
    print_health_report(health_results, publisher_id, args.uptime_threshold)
    print_interpretation_guide(
        {
            "median_mae": None,
            "mean_mean_diff": None,
            "t_test_significance_rate": None,
            "total_t_tests": 0,
            "significant_t_tests": 0,
            "normality_rate": None,
            "total_normality_tests": 0,
            "normal_distributions": 0,
            "median_z_score": None,
        }
    )
    write_health_csv(
        health_results,
        output_path,
        include_extended_hours=args.extended_hours,
        include_overnight=args.overnight,
    )

    print(f"\nTotal time: {total_time:.1f}s")


if __name__ == "__main__":
    main()
