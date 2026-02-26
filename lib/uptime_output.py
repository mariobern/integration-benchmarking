"""Output formatting, CSV writing, and console reports for feed_uptime.py.

Functions:
    write_results_csv          -- Write long-format per-publisher CSV with summary
    print_console_summary      -- Print FEED UPTIME REPORT to console
    print_publisher_consistency -- Print cross-date publisher consistency matrix
"""

from __future__ import annotations

import csv
import statistics
from collections import defaultdict
from pathlib import Path

from lib.config import normalize_asset_class
from lib.models import FeedUptimeResult
from lib.uptime_core import (
    SESSION_ORDER,
    compute_publisher_summary,
)


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
