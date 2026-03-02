"""Output formatting, CSV writing, and console reports for publisher_report.py.

Functions:
    format_diagnostics  -- Generate diagnostic string for non-HEALTHY feeds
    print_health_report -- Print unified health report to console
    write_health_csv    -- Write combined health report CSV with SUMMARY section
"""

from __future__ import annotations

import csv
import statistics
from pathlib import Path
from typing import Optional

from lib.publisher_health import FeedHealthResult
from lib.thresholds import get_threshold_description


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
            modes = {r.mode for r in results if r.mode}
            mode = next(iter(modes)) if len(modes) == 1 else "us-equities"
            print(f"    Target: {get_threshold_description(mode)}")
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
