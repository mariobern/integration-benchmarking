#!/usr/bin/env python3
"""
Feed-centric uptime measurement script.

Default mode uses a 1-second window uptime method. Use --precise to switch to
gap-based uptime (default 200ms threshold).

Core uptime logic lives in lib/uptime_core.py; this file is the CLI wrapper.
"""

import argparse
import csv
import statistics
import sys
import time
from collections import defaultdict
from pathlib import Path

from date_utils import expand_date_args, validate_date_args
from lib.benchmark_core import list_asset_classes_in_csv
from lib.config import (
    normalize_asset_class,
)
from lib.models import FeedUptimeResult
from lib.uptime_core import (
    DEFAULT_GAP_THRESHOLD_MS,
    DEFAULT_UPTIME_THRESHOLD_PCT,
    SESSION_ORDER,
    compute_publisher_summary,
    evaluate_feed_uptime,
    process_csv,
    process_work_items,
)


def write_results_csv(
    results: list[FeedUptimeResult],
    output_path: Path,
    precise: bool = False,
):
    """Write long-format per-publisher rows and optional publisher summary matrix."""

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if precise:
        detail_header = [
            "feed_id",
            "date",
            "mode",
            "symbol",
            "publisher_id",
            "session",
            "uptime_pct",
            "passes",
            "downtime_ms",
            "period_length_ms",
            "updates_total",
            "updates_per_second",
            "max_gap_ms",
            "gaps_over_threshold",
        ]
    else:
        detail_header = [
            "feed_id",
            "date",
            "mode",
            "symbol",
            "publisher_id",
            "session",
            "uptime_pct",
            "passes",
            "seconds_with_data",
            "total_seconds",
            "updates_total",
            "updates_per_second",
        ]

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(detail_header)

        for result in sorted(
            results, key=lambda r: (r.date, r.feed_id, normalize_asset_class(r.mode))
        ):
            sorted_uptimes = sorted(
                result.publisher_uptimes, key=lambda u: (u.publisher_id, u.session)
            )
            for uptime in sorted_uptimes:
                if precise:
                    writer.writerow(
                        [
                            result.feed_id,
                            result.date,
                            result.mode,
                            result.symbol or "",
                            uptime.publisher_id,
                            uptime.session,
                            f"{uptime.uptime_pct:.4f}",
                            uptime.passes,
                            uptime.downtime_ms
                            if uptime.downtime_ms is not None
                            else "",
                            uptime.period_length_ms
                            if uptime.period_length_ms is not None
                            else "",
                            uptime.updates_total,
                            f"{uptime.updates_per_second:.6f}",
                            uptime.max_gap_ms if uptime.max_gap_ms is not None else "",
                            uptime.gaps_over_threshold
                            if uptime.gaps_over_threshold is not None
                            else "",
                        ]
                    )
                else:
                    writer.writerow(
                        [
                            result.feed_id,
                            result.date,
                            result.mode,
                            result.symbol or "",
                            uptime.publisher_id,
                            uptime.session,
                            f"{uptime.uptime_pct:.4f}",
                            uptime.passes,
                            uptime.seconds_with_data,
                            uptime.total_seconds,
                            uptime.updates_total,
                            f"{uptime.updates_per_second:.6f}",
                        ]
                    )

        unique_dates, session_names, summary_rows = compute_publisher_summary(results)
        if len(unique_dates) > 1 and summary_rows:
            header = ["publisher_id", "dates_seen"]
            for session_name in session_names:
                header.extend(
                    [
                        f"{session_name}_pass_dates",
                        f"{session_name}_fail_dates",
                        f"{session_name}_pass_rate",
                        f"{session_name}_results",
                    ]
                )

            writer.writerow([])
            writer.writerow(["PUBLISHER SUMMARY"])
            writer.writerow(header)

            for row in summary_rows:
                output_row = [row["publisher_id"], row["dates_seen"]]
                sessions = row["sessions"]
                for session_name in session_names:
                    stats = sessions.get(session_name, {})
                    pass_dates = stats.get("pass_dates", 0)
                    fail_dates = stats.get("fail_dates", 0)
                    pass_rate = stats.get("pass_rate")
                    results_str = stats.get("results", "")
                    output_row.extend(
                        [
                            pass_dates,
                            fail_dates,
                            f"{pass_rate:.2f}%" if pass_rate is not None else "",
                            results_str,
                        ]
                    )
                writer.writerow(output_row)

            writer.writerow([])
            writer.writerow(["PUBLISHER CLASSIFICATIONS"])

            for session_name in session_names:
                always_passing = []
                always_failing = []
                intermittent = []
                for row in summary_rows:
                    stats = row["sessions"].get(session_name, {})
                    pass_dates = stats.get("pass_dates", 0)
                    fail_dates = stats.get("fail_dates", 0)
                    if pass_dates + fail_dates == 0:
                        continue
                    pid = int(row["publisher_id"])
                    if pass_dates > 0 and fail_dates == 0:
                        always_passing.append(pid)
                    elif fail_dates > 0 and pass_dates == 0:
                        always_failing.append(pid)
                    else:
                        intermittent.append(pid)

                _fmt = lambda ids: ";".join(str(x) for x in ids) if ids else ""
                writer.writerow(
                    [f"{session_name}_always_passing", _fmt(always_passing)]
                )
                writer.writerow(
                    [f"{session_name}_always_failing", _fmt(always_failing)]
                )
                writer.writerow([f"{session_name}_intermittent", _fmt(intermittent)])


def _format_uptime_stats(values: list[float]) -> str:
    return (
        f"Median uptime: {statistics.median(values):.2f}% | "
        f"Mean: {statistics.fmean(values):.2f}% | "
        f"Min: {min(values):.2f}% | "
        f"Max: {max(values):.2f}%"
    )


def _format_id_list(values: list[int]) -> str:
    if not values:
        return "None"
    return ", ".join(str(v) for v in values)


def print_publisher_consistency(results: list[FeedUptimeResult]):
    """Print cross-date publisher pass/fail consistency matrix."""

    unique_dates, session_names, summary_rows = compute_publisher_summary(results)
    if len(unique_dates) <= 1 or not summary_rows:
        return

    print()
    print("=" * 70)
    print(f"PUBLISHER CONSISTENCY (across {len(unique_dates)} dates)")
    print("=" * 70)

    for session_name in session_names:
        print()
        print(f"{session_name.upper()} SESSION:")
        print("  Publisher  Pass  Fail  Rate    Results")

        always_passing: list[int] = []
        always_failing: list[int] = []
        intermittent: list[int] = []

        for row in summary_rows:
            publisher_id = int(row["publisher_id"])
            stats = row["sessions"].get(session_name, {})
            evaluated_dates = int(stats.get("evaluated_dates", 0))
            if evaluated_dates == 0:
                continue

            pass_dates = int(stats.get("pass_dates", 0))
            fail_dates = int(stats.get("fail_dates", 0))
            pass_rate = stats.get("pass_rate")
            results_str = str(stats.get("results", "")).replace(";", " ")
            rate_str = f"{pass_rate:.1f}%" if pass_rate is not None else "N/A"

            print(
                f"  {publisher_id:<9} {pass_dates:<5} {fail_dates:<5} {rate_str:<7}  {results_str}"
            )

            if pass_dates > 0 and fail_dates == 0:
                always_passing.append(publisher_id)
            elif fail_dates > 0 and pass_dates == 0:
                always_failing.append(publisher_id)
            else:
                intermittent.append(publisher_id)

        print()
        print(f"  Always passing: {_format_id_list(always_passing)}")
        print(f"  Always failing: {_format_id_list(always_failing)}")
        print(f"  Intermittent: {_format_id_list(intermittent)}")


def print_console_summary(
    results: list[FeedUptimeResult],
    total_time_seconds: float,
    precise: bool,
    gap_threshold_ms: int,
    uptime_threshold_pct: float,
):
    """Print aggregated console summary."""

    all_uptimes = [
        (result, uptime) for result in results for uptime in result.publisher_uptimes
    ]
    errors = [result for result in results if result.error]
    publisher_feed_combos = {
        (result.feed_id, result.date, uptime.publisher_id)
        for result, uptime in all_uptimes
    }

    session_values: dict[str, list[float]] = defaultdict(list)
    session_passes: dict[str, int] = defaultdict(int)
    session_totals: dict[str, int] = defaultdict(int)
    for _, uptime in all_uptimes:
        session_values[uptime.session].append(uptime.uptime_pct)
        session_totals[uptime.session] += 1
        if uptime.passes:
            session_passes[uptime.session] += 1

    method_label = f"{gap_threshold_ms}ms gap-based" if precise else "1s window"
    print()
    print("=" * 70)
    print("FEED UPTIME REPORT")
    print("=" * 70)
    print(
        f"Feeds evaluated: {len(results)} | Publisher-feed combos: {len(publisher_feed_combos)} "
        f"| Method: {method_label} | Pass threshold: {uptime_threshold_pct:.1f}%"
    )
    if errors:
        print(f"Errors: {len(errors)}")

    ordered_sessions = [s for s in SESSION_ORDER if s in session_values]
    ordered_sessions.extend(sorted(s for s in session_values if s not in SESSION_ORDER))

    for session_name in ordered_sessions:
        values = session_values[session_name]
        if not values:
            continue
        pass_count = session_passes[session_name]
        fail_count = session_totals[session_name] - pass_count
        print()
        print(f"{session_name.upper()} SESSION:")
        print(f"  {_format_uptime_stats(values)}")
        print(
            f"  Publishers passing (>={uptime_threshold_pct:.1f}%): {pass_count} | "
            f"Failing: {fail_count}"
        )

    avg_feed_ms = (
        statistics.fmean([r.execution_time_ms for r in results]) if results else 0.0
    )
    print()
    print(f"Timing: {total_time_seconds:.1f}s total, {avg_feed_ms:.0f}ms avg/feed")
    print("=" * 70)

    print_publisher_consistency(results)


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
