"""Output formatting, CSV writing, and summary statistics for feed_readiness.py.

Functions:
    _regular_status          -- Status extractor for regular-hours consistency
    _session_status          -- Generic session status extractor (returns None if no data)
    _premarket_status        -- Status extractor for pre-market session
    _afterhours_status       -- Status extractor for after-hours session
    _overnight_status        -- Status extractor for overnight session
    _format_ratio            -- Format count/total as percentage string
    _format_id_list          -- Format list of publisher IDs for console output
    compute_publisher_consistency -- Cross-date publisher pass/fail matrix
    write_publisher_consistency_csv -- Write PUBLISHER CONSISTENCY section to CSV
    write_results_csv        -- Write full results CSV with optional detail/consistency sections
    compute_summary_stats    -- Compute aggregate statistics for console summary
    print_console_summary    -- Print FEED READINESS REPORT to console
    print_publisher_consistency -- Print PUBLISHER CONSISTENCY to console
"""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from typing import Callable, Optional

from lib.config import normalize_asset_class
from lib.readiness_core import (
    FeedReadinessResult,
    PublisherReadinessDetail,
    SESSION_AFTERHOURS,
    SESSION_OVERNIGHT,
    SESSION_PREMARKET,
    SESSION_REGULAR,
)
from lib.statistics import distribution_stats as _distribution_stats


# ---------------------------------------------------------------------------
# Status extractors
# ---------------------------------------------------------------------------


def _regular_status(detail: PublisherReadinessDetail) -> str:
    """Status extractor for regular-hours consistency."""
    if detail.benchmark_error or detail.uptime_error:
        return "ERROR"
    return "PASS" if detail.fully_passes else "FAIL"


def _session_status(
    benchmark_passes: bool | None,
    uptime_passes: bool | None,
    uptime_pct: float | None,
) -> str | None:
    """Generic session status extractor. Returns None if no data for this session.

    Note: uptime_passes is expected to always be populated when uptime_pct > 0
    (the uptime module sets both fields together). If uptime_passes is None with
    non-zero uptime_pct, it is treated as a FAIL (not ERROR) since the uptime
    calculation ran but the pass flag was not set.
    """
    if uptime_pct is None or uptime_pct == 0.0:
        return None
    if benchmark_passes is None:
        return "ERROR"
    return "PASS" if (benchmark_passes and uptime_passes) else "FAIL"


def _premarket_status(detail: PublisherReadinessDetail) -> str | None:
    return _session_status(
        detail.premarket_benchmark_passes,
        detail.premarket_uptime_passes,
        detail.premarket_uptime_pct,
    )


def _afterhours_status(detail: PublisherReadinessDetail) -> str | None:
    return _session_status(
        detail.afterhours_benchmark_passes,
        detail.afterhours_uptime_passes,
        detail.afterhours_uptime_pct,
    )


def _overnight_status(detail: PublisherReadinessDetail) -> str | None:
    return _session_status(
        detail.overnight_benchmark_passes,
        detail.overnight_uptime_passes,
        detail.overnight_uptime_pct,
    )


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------


def _format_ratio(count: int, total: int) -> str:
    if total <= 0:
        return "0.0%"
    return f"{(count * 100.0 / total):.1f}%"


def _format_id_list(values: list[int]) -> str:
    if not values:
        return "None"
    return ", ".join(str(value) for value in values)


# ---------------------------------------------------------------------------
# Publisher consistency computation
# ---------------------------------------------------------------------------


def compute_publisher_consistency(
    results: list[FeedReadinessResult],
    status_extractor: Callable[[PublisherReadinessDetail], str | None] | None = None,
) -> dict:
    if status_extractor is None:
        status_extractor = _regular_status

    dates = sorted({result.date for result in results})

    publisher_statuses: dict[int, dict[str, str]] = {}
    for result in sorted(results, key=lambda r: (r.date, r.feed_id)):
        for detail in result.publisher_details or []:
            status = status_extractor(detail)
            if status is None:
                continue  # no data for this session -> skip
            publisher_statuses.setdefault(detail.publisher_id, {})[result.date] = status

    rows = []
    for publisher_id, date_results in publisher_statuses.items():
        sorted_results = dict(sorted(date_results.items()))
        pass_count = sum(1 for status in sorted_results.values() if status == "PASS")
        fail_count = sum(1 for status in sorted_results.values() if status == "FAIL")
        error_count = sum(1 for status in sorted_results.values() if status == "ERROR")
        dates_seen = len(sorted_results)
        pass_rate = (pass_count / dates_seen * 100.0) if dates_seen > 0 else None
        rows.append(
            {
                "publisher_id": publisher_id,
                "dates_seen": dates_seen,
                "pass_count": pass_count,
                "fail_count": fail_count,
                "error_count": error_count,
                "pass_rate": pass_rate,
                "results": sorted_results,
            }
        )

    rows.sort(key=lambda row: (-(row["pass_rate"] or 0), row["publisher_id"]))

    always_passing: list[int] = []
    always_failing: list[int] = []
    intermittent: list[int] = []
    for row in rows:
        statuses = list(row["results"].values())
        if not statuses:
            continue
        if all(status == "PASS" for status in statuses):
            always_passing.append(row["publisher_id"])
        elif all(status == "FAIL" for status in statuses):
            always_failing.append(row["publisher_id"])
        else:
            intermittent.append(row["publisher_id"])

    return {
        "dates": dates,
        "rows": rows,
        "classifications": {
            "always_passing": always_passing,
            "always_failing": always_failing,
            "intermittent": intermittent,
        },
    }


# ---------------------------------------------------------------------------
# CSV output
# ---------------------------------------------------------------------------


def write_publisher_consistency_csv(
    writer: csv.writer,
    consistency: dict,
    session_prefix: str = "",
) -> None:
    label_prefix = (
        session_prefix.lower().replace(" ", "") + "_" if session_prefix else "regular_"
    )

    writer.writerow([])
    writer.writerow([f"{session_prefix}PUBLISHER CONSISTENCY"])
    writer.writerow(
        [
            "publisher_id",
            "dates_seen",
            "pass_dates",
            "fail_dates",
            "pass_rate",
            "results",
        ]
    )

    for row in consistency["rows"]:
        results_str = ";".join(
            f"{date_value}:{status}" for date_value, status in row["results"].items()
        )
        writer.writerow(
            [
                row["publisher_id"],
                row["dates_seen"],
                row["pass_count"],
                row["fail_count"],
                f"{row['pass_rate']:.2f}%" if row["pass_rate"] is not None else "",
                results_str,
            ]
        )

    writer.writerow([])
    writer.writerow([f"{session_prefix}PUBLISHER CLASSIFICATIONS"])
    _fmt = lambda ids: ";".join(str(x) for x in ids) if ids else ""
    writer.writerow(
        [
            f"{label_prefix}always_passing",
            _fmt(consistency["classifications"]["always_passing"]),
        ]
    )
    writer.writerow(
        [
            f"{label_prefix}always_failing",
            _fmt(consistency["classifications"]["always_failing"]),
        ]
    )
    writer.writerow(
        [
            f"{label_prefix}intermittent",
            _fmt(consistency["classifications"]["intermittent"]),
        ]
    )


def write_results_csv(
    results: list[FeedReadinessResult],
    output_path: Path,
    include_extended_hours: bool = False,
    include_overnight: bool = False,
    include_detailed: bool = False,
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)

    header = [
        "feed_id",
        "date",
        "mode",
        "symbol",
        "ready",
        "benchmark_ready",
        "uptime_ready",
        "target_pub_count",
        "fully_passing_count",
        "benchmark_only_passing_count",
        "uptime_only_passing_count",
        "both_failing_count",
        "total_publisher_count",
        "benchmark_passing_count",
        "benchmark_failing_count",
        "median_nrmse",
        "median_hit_rate",
        "uptime_passing_count",
        "uptime_failing_count",
        "median_uptime_pct",
        "fully_passing_publishers",
        "benchmark_only_publishers",
        "uptime_only_publishers",
        "both_failing_publishers",
    ]

    if include_extended_hours:
        header.extend(
            [
                "premarket_ready",
                "premarket_benchmark_passing_count",
                "premarket_uptime_passing_count",
                "premarket_uptime_failing_count",
                "premarket_median_uptime_pct",
                "premarket_fully_passing_count",
                "afterhours_ready",
                "afterhours_benchmark_passing_count",
                "afterhours_uptime_passing_count",
                "afterhours_uptime_failing_count",
                "afterhours_median_uptime_pct",
                "afterhours_fully_passing_count",
            ]
        )
    if include_overnight:
        header.extend(
            [
                "overnight_ready",
                "overnight_benchmark_passing_count",
                "overnight_uptime_passing_count",
                "overnight_uptime_failing_count",
                "overnight_median_uptime_pct",
                "overnight_fully_passing_count",
            ]
        )

    header.extend(["benchmark_error", "uptime_error", "error", "execution_time_ms"])

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(header)

        for result in sorted(
            results, key=lambda r: (r.date, r.feed_id, normalize_asset_class(r.mode))
        ):
            row = [
                result.feed_id,
                result.date,
                result.mode,
                result.symbol or "",
                result.ready,
                result.benchmark_ready,
                result.uptime_ready,
                result.target_pub_count,
                result.fully_passing_count,
                result.benchmark_only_passing_count,
                result.uptime_only_passing_count,
                result.both_failing_count,
                result.total_publisher_count,
                result.benchmark_passing_count,
                result.benchmark_failing_count,
                f"{result.median_nrmse:.6f}" if result.median_nrmse is not None else "",
                f"{result.median_hit_rate:.2f}"
                if result.median_hit_rate is not None
                else "",
                result.uptime_passing_count,
                result.uptime_failing_count,
                f"{result.median_uptime_pct:.4f}"
                if result.median_uptime_pct is not None
                else "",
                ";".join(str(pid) for pid in result.fully_passing_publishers),
                ";".join(str(pid) for pid in result.benchmark_only_publishers),
                ";".join(str(pid) for pid in result.uptime_only_publishers),
                ";".join(str(pid) for pid in result.both_failing_publishers),
            ]

            if include_extended_hours:
                row.extend(
                    [
                        result.premarket_ready
                        if result.premarket_ready is not None
                        else "",
                        result.premarket_benchmark_passing_count
                        if result.premarket_benchmark_passing_count is not None
                        else "",
                        result.premarket_uptime_passing_count
                        if result.premarket_uptime_passing_count is not None
                        else "",
                        result.premarket_uptime_failing_count
                        if result.premarket_uptime_failing_count is not None
                        else "",
                        f"{result.premarket_median_uptime_pct:.4f}"
                        if result.premarket_median_uptime_pct is not None
                        else "",
                        result.premarket_fully_passing_count
                        if result.premarket_fully_passing_count is not None
                        else "",
                        result.afterhours_ready
                        if result.afterhours_ready is not None
                        else "",
                        result.afterhours_benchmark_passing_count
                        if result.afterhours_benchmark_passing_count is not None
                        else "",
                        result.afterhours_uptime_passing_count
                        if result.afterhours_uptime_passing_count is not None
                        else "",
                        result.afterhours_uptime_failing_count
                        if result.afterhours_uptime_failing_count is not None
                        else "",
                        f"{result.afterhours_median_uptime_pct:.4f}"
                        if result.afterhours_median_uptime_pct is not None
                        else "",
                        result.afterhours_fully_passing_count
                        if result.afterhours_fully_passing_count is not None
                        else "",
                    ]
                )
            if include_overnight:
                row.extend(
                    [
                        result.overnight_ready
                        if result.overnight_ready is not None
                        else "",
                        result.overnight_benchmark_passing_count
                        if result.overnight_benchmark_passing_count is not None
                        else "",
                        result.overnight_uptime_passing_count
                        if result.overnight_uptime_passing_count is not None
                        else "",
                        result.overnight_uptime_failing_count
                        if result.overnight_uptime_failing_count is not None
                        else "",
                        f"{result.overnight_median_uptime_pct:.4f}"
                        if result.overnight_median_uptime_pct is not None
                        else "",
                        result.overnight_fully_passing_count
                        if result.overnight_fully_passing_count is not None
                        else "",
                    ]
                )

            row.extend(
                [
                    result.benchmark_error or "",
                    result.uptime_error or "",
                    result.error or "",
                    result.execution_time_ms,
                ]
            )
            writer.writerow(row)

        if include_detailed:
            writer.writerow([])
            writer.writerow(["PUBLISHER DETAIL"])
            detail_header = [
                "feed_id",
                "publisher_id",
                "date",
                "mode",
                "symbol",
                "fully_passes",
                "benchmark_passes",
                "uptime_passes",
                "benchmark_nrmse",
                "benchmark_hit_rate",
                "benchmark_n_observations",
                "uptime_pct",
                "benchmark_error",
                "uptime_error",
            ]
            if include_extended_hours:
                detail_header.extend(
                    [
                        "premarket_benchmark_passes",
                        "premarket_benchmark_nrmse",
                        "premarket_benchmark_hit_rate",
                        "premarket_benchmark_n_observations",
                        "premarket_uptime_pct",
                        "premarket_uptime_passes",
                        "afterhours_benchmark_passes",
                        "afterhours_benchmark_nrmse",
                        "afterhours_benchmark_hit_rate",
                        "afterhours_benchmark_n_observations",
                        "afterhours_uptime_pct",
                        "afterhours_uptime_passes",
                    ]
                )
            if include_overnight:
                detail_header.extend(
                    [
                        "overnight_benchmark_passes",
                        "overnight_benchmark_nrmse",
                        "overnight_benchmark_hit_rate",
                        "overnight_benchmark_n_observations",
                        "overnight_uptime_pct",
                        "overnight_uptime_passes",
                    ]
                )
            writer.writerow(detail_header)

            for result in sorted(
                results,
                key=lambda r: (r.date, r.feed_id, normalize_asset_class(r.mode)),
            ):
                details = sorted(
                    result.publisher_details or [],
                    key=lambda detail: detail.publisher_id,
                )
                for detail in details:
                    detail_row = [
                        result.feed_id,
                        detail.publisher_id,
                        result.date,
                        result.mode,
                        result.symbol or "",
                        detail.fully_passes,
                        detail.benchmark_passes,
                        detail.uptime_passes,
                        f"{detail.benchmark_nrmse:.6f}"
                        if detail.benchmark_nrmse is not None
                        else "",
                        f"{detail.benchmark_hit_rate:.2f}"
                        if detail.benchmark_hit_rate is not None
                        else "",
                        detail.benchmark_n_observations,
                        f"{detail.uptime_pct:.4f}"
                        if detail.uptime_pct is not None
                        else "",
                        detail.benchmark_error or "",
                        detail.uptime_error or "",
                    ]
                    if include_extended_hours:
                        detail_row.extend(
                            [
                                detail.premarket_benchmark_passes
                                if detail.premarket_benchmark_passes is not None
                                else "",
                                f"{detail.premarket_benchmark_nrmse:.6f}"
                                if detail.premarket_benchmark_nrmse is not None
                                else "",
                                f"{detail.premarket_benchmark_hit_rate:.2f}"
                                if detail.premarket_benchmark_hit_rate is not None
                                else "",
                                detail.premarket_benchmark_n_observations
                                if detail.premarket_benchmark_n_observations is not None
                                else "",
                                f"{detail.premarket_uptime_pct:.4f}"
                                if detail.premarket_uptime_pct is not None
                                else "",
                                detail.premarket_uptime_passes
                                if detail.premarket_uptime_passes is not None
                                else "",
                                detail.afterhours_benchmark_passes
                                if detail.afterhours_benchmark_passes is not None
                                else "",
                                f"{detail.afterhours_benchmark_nrmse:.6f}"
                                if detail.afterhours_benchmark_nrmse is not None
                                else "",
                                f"{detail.afterhours_benchmark_hit_rate:.2f}"
                                if detail.afterhours_benchmark_hit_rate is not None
                                else "",
                                detail.afterhours_benchmark_n_observations
                                if detail.afterhours_benchmark_n_observations
                                is not None
                                else "",
                                f"{detail.afterhours_uptime_pct:.4f}"
                                if detail.afterhours_uptime_pct is not None
                                else "",
                                detail.afterhours_uptime_passes
                                if detail.afterhours_uptime_passes is not None
                                else "",
                            ]
                        )
                    if include_overnight:
                        detail_row.extend(
                            [
                                detail.overnight_benchmark_passes
                                if detail.overnight_benchmark_passes is not None
                                else "",
                                f"{detail.overnight_benchmark_nrmse:.6f}"
                                if detail.overnight_benchmark_nrmse is not None
                                else "",
                                f"{detail.overnight_benchmark_hit_rate:.2f}"
                                if detail.overnight_benchmark_hit_rate is not None
                                else "",
                                detail.overnight_benchmark_n_observations
                                if detail.overnight_benchmark_n_observations is not None
                                else "",
                                f"{detail.overnight_uptime_pct:.4f}"
                                if detail.overnight_uptime_pct is not None
                                else "",
                                detail.overnight_uptime_passes
                                if detail.overnight_uptime_passes is not None
                                else "",
                            ]
                        )
                    writer.writerow(detail_row)

            consistency = compute_publisher_consistency(results)
            if len(consistency["dates"]) > 1 and consistency["rows"]:
                write_publisher_consistency_csv(writer, consistency)

            # Per-session consistency (only for multi-date with session flags)
            if include_extended_hours:
                for session_name, extractor in [
                    ("PREMARKET", _premarket_status),
                    ("AFTERHOURS", _afterhours_status),
                ]:
                    session_consistency = compute_publisher_consistency(
                        results, status_extractor=extractor
                    )
                    if (
                        len(session_consistency["dates"]) > 1
                        and session_consistency["rows"]
                    ):
                        write_publisher_consistency_csv(
                            writer,
                            session_consistency,
                            session_prefix=f"{session_name} ",
                        )

            if include_overnight:
                session_consistency = compute_publisher_consistency(
                    results, status_extractor=_overnight_status
                )
                if (
                    len(session_consistency["dates"]) > 1
                    and session_consistency["rows"]
                ):
                    write_publisher_consistency_csv(
                        writer, session_consistency, session_prefix="OVERNIGHT "
                    )


# ---------------------------------------------------------------------------
# Summary statistics
# ---------------------------------------------------------------------------


def compute_summary_stats(
    results: list[FeedReadinessResult], total_time_seconds: float
) -> dict:
    total_feeds = len(results)
    error_count = sum(1 for result in results if result.error)
    ready_count = sum(1 for result in results if result.ready and not result.error)
    not_ready_count = sum(
        1 for result in results if not result.ready and not result.error
    )

    benchmark_ready_count = sum(1 for result in results if result.benchmark_ready)
    uptime_ready_count = sum(1 for result in results if result.uptime_ready)

    nrmse_values = [
        result.median_nrmse
        for result in results
        if result.median_nrmse is not None and not result.benchmark_error
    ]
    hit_rate_values = [
        result.median_hit_rate
        for result in results
        if result.median_hit_rate is not None and not result.benchmark_error
    ]
    uptime_values = [
        result.median_uptime_pct
        for result in results
        if result.median_uptime_pct is not None and not result.uptime_error
    ]

    mode_stats: dict[str, dict[str, int]] = {}
    for result in results:
        mode = normalize_asset_class(result.mode)
        if mode not in mode_stats:
            mode_stats[mode] = {"ready": 0, "not_ready": 0, "error": 0}
        if result.error:
            mode_stats[mode]["error"] += 1
        elif result.ready:
            mode_stats[mode]["ready"] += 1
        else:
            mode_stats[mode]["not_ready"] += 1

    per_date_stats: dict[str, dict[str, int]] = {}
    for result in results:
        per_date_stats.setdefault(result.date, {"ready": 0, "not_ready": 0, "error": 0})
        if result.error:
            per_date_stats[result.date]["error"] += 1
        elif result.ready:
            per_date_stats[result.date]["ready"] += 1
        else:
            per_date_stats[result.date]["not_ready"] += 1

    # Extended session stats (only for results that have per-session data)
    extended_session_stats = {}
    for session_name in [SESSION_PREMARKET, SESSION_AFTERHOURS, SESSION_OVERNIGHT]:
        ready_field = f"{session_name}_ready"
        median_uptime_field = f"{session_name}_median_uptime_pct"

        session_results = [r for r in results if getattr(r, ready_field) is not None]
        if session_results:
            session_ready = sum(1 for r in session_results if getattr(r, ready_field))
            session_uptime_values = [
                getattr(r, median_uptime_field)
                for r in session_results
                if getattr(r, median_uptime_field) is not None
            ]
            extended_session_stats[session_name] = {
                "total": len(session_results),
                "ready": session_ready,
                "not_ready": len(session_results) - session_ready,
                "uptime": _distribution_stats(session_uptime_values),
            }

    return {
        "total_feeds": total_feeds,
        "ready_count": ready_count,
        "not_ready_count": not_ready_count,
        "error_count": error_count,
        "benchmark_ready_count": benchmark_ready_count,
        "uptime_ready_count": uptime_ready_count,
        "nrmse": _distribution_stats(
            [value for value in nrmse_values if value is not None]
        ),
        "hit_rate": _distribution_stats(
            [value for value in hit_rate_values if value is not None]
        ),
        "uptime": _distribution_stats(
            [value for value in uptime_values if value is not None]
        ),
        "mode_stats": mode_stats,
        "per_date_stats": per_date_stats,
        "extended_session_stats": extended_session_stats,
        "total_time_sec": total_time_seconds,
        "avg_time_ms": (total_time_seconds / total_feeds * 1000)
        if total_feeds > 0
        else 0,
    }


# ---------------------------------------------------------------------------
# Console output
# ---------------------------------------------------------------------------


def print_console_summary(
    results: list[FeedReadinessResult],
    total_time_seconds: float,
    target_pub_count: int,
    uptime_threshold_pct: float,
) -> None:
    summary = compute_summary_stats(results, total_time_seconds)

    print()
    print("=" * 70)
    print("FEED READINESS REPORT")
    print("=" * 70)
    print(
        f"Feeds evaluated: {summary['total_feeds']} | Target publishers: {target_pub_count}"
    )
    print("Benchmark: nrmse < 0.01 OR (nrmse < 0.05 AND hit_rate >= 95%)")
    print(
        f"Uptime: regular session >= {uptime_threshold_pct:.1f}% (1s window unless --precise)"
    )
    print("=" * 70)

    total = summary["total_feeds"]
    print("\nCOMBINED READINESS:")
    print(
        f"  Ready (both pass): {summary['ready_count']} / {total} "
        f"({_format_ratio(summary['ready_count'], total)})"
    )
    print(
        f"  Benchmark-only ready: {summary['benchmark_ready_count']} / {total} "
        f"({_format_ratio(summary['benchmark_ready_count'], total)})"
    )
    print(
        f"  Uptime-only ready: {summary['uptime_ready_count']} / {total} "
        f"({_format_ratio(summary['uptime_ready_count'], total)})"
    )
    print(f"  Errors: {summary['error_count']}")

    nrmse_stats = summary["nrmse"]
    hit_rate_stats = summary["hit_rate"]
    print("\nBENCHMARK QUALITY:")
    if nrmse_stats["median"] is not None:
        print(
            "  NRMSE: "
            f"median={nrmse_stats['median']:.6f} "
            f"mean={nrmse_stats['mean']:.6f} "
            f"p90={nrmse_stats['p90']:.6f} "
            f"p95={nrmse_stats['p95']:.6f}"
        )
    else:
        print("  NRMSE: no data")

    if hit_rate_stats["median"] is not None:
        print(
            "  Hit rate: "
            f"median={hit_rate_stats['median']:.2f}% "
            f"mean={hit_rate_stats['mean']:.2f}% "
            f"min={hit_rate_stats['min']:.2f}% "
            f"max={hit_rate_stats['max']:.2f}%"
        )
    else:
        print("  Hit rate: no data")

    uptime_stats = summary["uptime"]
    print("\nUPTIME (REGULAR SESSION):")
    if uptime_stats["median"] is not None:
        print(
            f"  Median: {uptime_stats['median']:.4f}% | "
            f"Mean: {uptime_stats['mean']:.4f}% | "
            f"Min: {uptime_stats['min']:.4f}% | "
            f"Max: {uptime_stats['max']:.4f}%"
        )
    else:
        print("  No data")

    print("\nBY ASSET CLASS:")
    mode_stats = summary["mode_stats"]
    if mode_stats:
        for mode in sorted(mode_stats):
            stats = mode_stats[mode]
            print(
                f"  {mode:<15} ready={stats['ready']:<4} "
                f"not_ready={stats['not_ready']:<4} error={stats['error']:<4}"
            )
    else:
        print("  No feeds processed")

    per_date_stats = summary["per_date_stats"]
    if len(per_date_stats) > 1:
        print("\nBY DATE:")
        for date_value in sorted(per_date_stats):
            stats = per_date_stats[date_value]
            print(
                f"  {date_value:<12} ready={stats['ready']:<4} "
                f"not_ready={stats['not_ready']:<4} error={stats['error']:<4}"
            )

    extended_stats = summary.get("extended_session_stats", {})
    if extended_stats:
        print("\nEXTENDED SESSION READINESS:")
        for session_name, stats in extended_stats.items():
            session_total = stats["total"]
            print(f"\n  {session_name.upper()}:")
            print(
                f"    Ready: {stats['ready']} / {session_total} "
                f"({_format_ratio(stats['ready'], session_total)})"
            )
            print(
                f"    Not ready: {stats['not_ready']} / {session_total} "
                f"({_format_ratio(stats['not_ready'], session_total)})"
            )
            uptime_s = stats["uptime"]
            if uptime_s["median"] is not None:
                print(
                    f"    Uptime: median={uptime_s['median']:.4f}% "
                    f"min={uptime_s['min']:.4f}% max={uptime_s['max']:.4f}%"
                )
            else:
                print("    Uptime: no data")

    print(
        f"\nTiming: {summary['total_time_sec']:.1f}s total, {summary['avg_time_ms']:.0f}ms avg/feed"
    )


def print_publisher_consistency(consistency: dict, session_prefix: str = "") -> None:
    print()
    print("=" * 70)
    print(f"PUBLISHER CONSISTENCY (across {len(consistency['dates'])} dates)")
    print("=" * 70)

    session_label = session_prefix.strip() if session_prefix else "REGULAR"
    print(f"\n{session_label} SESSION:")
    print("  Publisher  Pass  Fail  Rate    Results")
    for row in consistency["rows"]:
        if row["dates_seen"] == 0:
            continue
        results_str = " ".join(
            f"{date_value}:{status}" for date_value, status in row["results"].items()
        )
        rate_str = f"{row['pass_rate']:.1f}%" if row["pass_rate"] is not None else "N/A"
        print(
            f"  {row['publisher_id']:<9} {row['pass_count']:<5} "
            f"{row['fail_count']:<5} {rate_str:<7}  {results_str}"
        )

    print()
    print(
        f"  Always passing: {_format_id_list(consistency['classifications']['always_passing'])}"
    )
    print(
        f"  Always failing: {_format_id_list(consistency['classifications']['always_failing'])}"
    )
    print(
        f"  Intermittent: {_format_id_list(consistency['classifications']['intermittent'])}"
    )
