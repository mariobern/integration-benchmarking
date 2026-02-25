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

Usage:
    python publisher_benchmark.py --csv publisher_55_feeds.csv
    python publisher_benchmark.py --csv feeds.csv --publisher-id 55
    python publisher_benchmark.py --publisher-id 55 --feed-id 327 --date 2025-10-06 --mode fx
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
from lib.models import (
    OVERNIGHT_REFERENCE_PUBLISHER_ID,
    PublisherBenchmarkResult,
)
from lib.publisher_eval import (
    evaluate_publisher_feed,
    extract_publisher_id_from_filename,
    process_csv,
)
from lib.statistics import distribution_stats


def compute_summary_stats(
    results: list[PublisherBenchmarkResult],
    publisher_id: int,
    total_time: float,
    include_extended_hours: bool = False,
    include_overnight: bool = False,
    hit_rate_threshold: float = 95,
) -> dict:
    """Compute comprehensive summary statistics from benchmark results."""
    total_feeds = len(results)
    error_count = sum(1 for r in results if r.error)
    pass_count = sum(1 for r in results if r.passes and not r.error)
    fail_count = sum(1 for r in results if not r.passes and not r.error)

    pass_by_nrmse_alone = sum(
        1
        for r in results
        if r.passes and not r.error and r.nrmse is not None and r.nrmse < 0.01
    )
    pass_by_nrmse_and_hit_rate = sum(
        1
        for r in results
        if r.passes
        and not r.error
        and r.nrmse is not None
        and r.nrmse >= 0.01
        and r.nrmse < 0.05
        and r.hit_rate is not None
        and r.hit_rate >= hit_rate_threshold
    )

    # RMSE/spread distribution
    valid_rmse_ratios = [
        r.rmse_over_spread
        for r in results
        if r.rmse_over_spread is not None and r.error is None
    ]
    ros_stats = distribution_stats(valid_rmse_ratios)

    # NRMSE distribution
    valid_nrmse_values = [
        r.nrmse for r in results if r.nrmse is not None and r.error is None
    ]
    nrmse_stats = distribution_stats(valid_nrmse_values)

    # Hit rate statistics
    valid_hit_rates = [
        r.hit_rate for r in results if r.hit_rate is not None and r.error is None
    ]
    if valid_hit_rates:
        median_hit_rate = statistics.median(valid_hit_rates)
        mean_hit_rate = statistics.mean(valid_hit_rates)
        min_hit_rate = min(valid_hit_rates)
        max_hit_rate = max(valid_hit_rates)
    else:
        median_hit_rate = mean_hit_rate = min_hit_rate = max_hit_rate = None

    # Observation statistics
    observations = [
        r.n_observations for r in results if r.error is None and r.n_observations > 0
    ]
    total_observations = sum(observations) if observations else 0
    mean_observations = statistics.mean(observations) if observations else 0
    median_observations = statistics.median(observations) if observations else 0

    # Breakdown by asset class
    mode_stats: dict[str, dict[str, int]] = {}
    for r in results:
        normalized_mode = normalize_asset_class(r.mode)
        if normalized_mode not in mode_stats:
            mode_stats[normalized_mode] = {"pass": 0, "fail": 0, "error": 0}
        if r.error:
            mode_stats[normalized_mode]["error"] += 1
        elif r.passes:
            mode_stats[normalized_mode]["pass"] += 1
        else:
            mode_stats[normalized_mode]["fail"] += 1

    # MAE statistics
    valid_mae_values = [r.mae for r in results if r.mae is not None and r.error is None]
    mae_stats = distribution_stats(valid_mae_values)

    # Mean difference statistics
    valid_mean_diff = [
        r.mean_diff for r in results if r.mean_diff is not None and r.error is None
    ]
    median_mean_diff = statistics.median(valid_mean_diff) if valid_mean_diff else None
    mean_mean_diff = statistics.mean(valid_mean_diff) if valid_mean_diff else None

    # T-test summary
    significant_t_tests = sum(
        1
        for r in results
        if r.t_pvalue is not None and r.t_pvalue < 0.05 and r.error is None
    )
    total_t_tests = sum(
        1 for r in results if r.t_pvalue is not None and r.error is None
    )

    # Normality test summary
    normal_distributions = sum(
        1
        for r in results
        if r.normality_pvalue is not None
        and r.normality_pvalue >= 0.05
        and r.error is None
    )
    total_normality_tests = sum(
        1 for r in results if r.normality_pvalue is not None and r.error is None
    )

    # Z-score statistics
    valid_z_scores = [
        r.mean_abs_z_score
        for r in results
        if r.mean_abs_z_score is not None and r.error is None
    ]
    median_z_score = statistics.median(valid_z_scores) if valid_z_scores else None
    mean_z_score = statistics.mean(valid_z_scores) if valid_z_scores else None

    # Extended hours statistics
    extended_hours_stats = {}
    if include_extended_hours:
        us_equity_results = [
            r
            for r in results
            if normalize_asset_class(r.mode) == "us-equities" and r.error is None
        ]

        premarket_results = [
            r.premarket_metrics for r in us_equity_results if r.premarket_metrics
        ]
        pm_pass = sum(1 for pm in premarket_results if pm.passes and not pm.error)
        pm_fail = sum(1 for pm in premarket_results if not pm.passes and not pm.error)
        pm_error = sum(1 for pm in premarket_results if pm.error)
        pm_total = len(premarket_results)

        pm_nrmse_values = [
            pm.nrmse
            for pm in premarket_results
            if pm.nrmse is not None and not pm.error
        ]
        pm_hit_rate_values = [
            pm.hit_rate
            for pm in premarket_results
            if pm.hit_rate is not None and not pm.error
        ]

        extended_hours_stats["premarket_total_feeds"] = pm_total
        extended_hours_stats["premarket_pass_count"] = pm_pass
        extended_hours_stats["premarket_fail_count"] = pm_fail
        extended_hours_stats["premarket_error_count"] = pm_error
        extended_hours_stats["premarket_pass_rate_pct"] = (
            round((pm_pass / pm_total * 100), 2) if pm_total > 0 else 0
        )
        extended_hours_stats["premarket_median_nrmse"] = (
            statistics.median(pm_nrmse_values) if pm_nrmse_values else None
        )
        extended_hours_stats["premarket_median_hit_rate"] = (
            statistics.median(pm_hit_rate_values) if pm_hit_rate_values else None
        )

        afterhours_results = [
            r.afterhours_metrics for r in us_equity_results if r.afterhours_metrics
        ]
        ah_pass = sum(1 for ah in afterhours_results if ah.passes and not ah.error)
        ah_fail = sum(1 for ah in afterhours_results if not ah.passes and not ah.error)
        ah_error = sum(1 for ah in afterhours_results if ah.error)
        ah_total = len(afterhours_results)

        ah_nrmse_values = [
            ah.nrmse
            for ah in afterhours_results
            if ah.nrmse is not None and not ah.error
        ]
        ah_hit_rate_values = [
            ah.hit_rate
            for ah in afterhours_results
            if ah.hit_rate is not None and not ah.error
        ]

        extended_hours_stats["afterhours_total_feeds"] = ah_total
        extended_hours_stats["afterhours_pass_count"] = ah_pass
        extended_hours_stats["afterhours_fail_count"] = ah_fail
        extended_hours_stats["afterhours_error_count"] = ah_error
        extended_hours_stats["afterhours_pass_rate_pct"] = (
            round((ah_pass / ah_total * 100), 2) if ah_total > 0 else 0
        )
        extended_hours_stats["afterhours_median_nrmse"] = (
            statistics.median(ah_nrmse_values) if ah_nrmse_values else None
        )
        extended_hours_stats["afterhours_median_hit_rate"] = (
            statistics.median(ah_hit_rate_values) if ah_hit_rate_values else None
        )

    # Overnight statistics
    overnight_stats = {}
    if include_overnight:
        us_equity_results = [
            r
            for r in results
            if normalize_asset_class(r.mode) == "us-equities" and r.error is None
        ]

        overnight_results = [
            r.overnight_metrics for r in us_equity_results if r.overnight_metrics
        ]
        on_pass = sum(1 for on in overnight_results if on.passes and not on.error)
        on_fail = sum(1 for on in overnight_results if not on.passes and not on.error)
        on_error = sum(1 for on in overnight_results if on.error)
        on_total = len(overnight_results)

        on_nrmse_values = [
            on.nrmse
            for on in overnight_results
            if on.nrmse is not None and not on.error
        ]
        on_hit_rate_values = [
            on.hit_rate
            for on in overnight_results
            if on.hit_rate is not None and not on.error
        ]

        overnight_stats["overnight_total_feeds"] = on_total
        overnight_stats["overnight_pass_count"] = on_pass
        overnight_stats["overnight_fail_count"] = on_fail
        overnight_stats["overnight_error_count"] = on_error
        overnight_stats["overnight_pass_rate_pct"] = (
            round((on_pass / on_total * 100), 2) if on_total > 0 else 0
        )
        overnight_stats["overnight_median_nrmse"] = (
            statistics.median(on_nrmse_values) if on_nrmse_values else None
        )
        overnight_stats["overnight_median_hit_rate"] = (
            statistics.median(on_hit_rate_values) if on_hit_rate_values else None
        )
        overnight_stats[
            "overnight_reference_publisher_id"
        ] = OVERNIGHT_REFERENCE_PUBLISHER_ID

    # Per-date breakdown
    per_date_breakdown: dict[str, dict[str, int | float | None]] = {}
    results_by_date: dict[str, list[PublisherBenchmarkResult]] = {}
    for result in results:
        results_by_date.setdefault(result.date, []).append(result)

    for date_value in sorted(results_by_date):
        date_results = results_by_date[date_value]
        date_total = len(date_results)
        date_pass = sum(1 for r in date_results if r.passes and not r.error)
        date_fail = sum(1 for r in date_results if not r.passes and not r.error)
        date_error = sum(1 for r in date_results if r.error)
        date_nrmse = [
            r.nrmse for r in date_results if r.nrmse is not None and not r.error
        ]
        date_hit_rate = [
            r.hit_rate for r in date_results if r.hit_rate is not None and not r.error
        ]

        per_date_breakdown[date_value] = {
            "total": date_total,
            "pass": date_pass,
            "fail": date_fail,
            "error": date_error,
            "pass_rate_pct": round((date_pass / date_total * 100), 2)
            if date_total > 0
            else 0,
            "median_nrmse": statistics.median(date_nrmse) if date_nrmse else None,
            "median_hit_rate": statistics.median(date_hit_rate)
            if date_hit_rate
            else None,
        }

    return {
        "publisher_id": publisher_id,
        "total_feeds": total_feeds,
        "pass_count": pass_count,
        "fail_count": fail_count,
        "error_count": error_count,
        "pass_rate_pct": round((pass_count / total_feeds * 100), 2)
        if total_feeds > 0
        else 0,
        "pass_by_nrmse_alone": pass_by_nrmse_alone,
        "pass_by_nrmse_and_hit_rate": pass_by_nrmse_and_hit_rate,
        "median_nrmse": nrmse_stats["median"],
        "mean_nrmse": nrmse_stats["mean"],
        "p90_nrmse": nrmse_stats["p90"],
        "p95_nrmse": nrmse_stats["p95"],
        "min_nrmse": nrmse_stats["min"],
        "max_nrmse": nrmse_stats["max"],
        "median_hit_rate": median_hit_rate,
        "mean_hit_rate": mean_hit_rate,
        "min_hit_rate": min_hit_rate,
        "max_hit_rate": max_hit_rate,
        "median_rmse_over_spread": ros_stats["median"],
        "mean_rmse_over_spread": ros_stats["mean"],
        "p90_rmse_over_spread": ros_stats["p90"],
        "p95_rmse_over_spread": ros_stats["p95"],
        "min_rmse_over_spread": ros_stats["min"],
        "max_rmse_over_spread": ros_stats["max"],
        "total_observations": total_observations,
        "mean_observations_per_feed": round(mean_observations, 1)
        if mean_observations
        else 0,
        "median_observations_per_feed": int(median_observations)
        if median_observations
        else 0,
        "total_time_sec": round(total_time, 2),
        "avg_time_per_feed_ms": int((total_time / total_feeds * 1000))
        if total_feeds > 0
        else 0,
        "mode_stats": mode_stats,
        "median_mae": mae_stats["median"],
        "mean_mae": mae_stats["mean"],
        "p90_mae": mae_stats["p90"],
        "p95_mae": mae_stats["p95"],
        "median_mean_diff": median_mean_diff,
        "mean_mean_diff": mean_mean_diff,
        "significant_t_tests": significant_t_tests,
        "total_t_tests": total_t_tests,
        "t_test_significance_rate": round(
            (significant_t_tests / total_t_tests * 100), 2
        )
        if total_t_tests > 0
        else None,
        "normal_distributions": normal_distributions,
        "total_normality_tests": total_normality_tests,
        "normality_rate": round((normal_distributions / total_normality_tests * 100), 2)
        if total_normality_tests > 0
        else None,
        "median_z_score": median_z_score,
        "mean_z_score": mean_z_score,
        "per_date_breakdown": per_date_breakdown,
        "extended_hours": extended_hours_stats,
        "overnight": overnight_stats,
    }


def write_results_csv(
    results: list[PublisherBenchmarkResult],
    output_path: Path,
    summary_stats: Optional[dict] = None,
    include_extended_hours: bool = False,
    include_overnight: bool = False,
):
    """Write benchmark results to CSV file with optional summary section."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

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
        "std_diff",
        "mean_pct_diff",
        "std_pct_diff",
        "mae",
        "t_statistic",
        "t_pvalue",
        "wilcoxon_statistic",
        "wilcoxon_pvalue",
        "normality_pvalue",
        "mean_abs_z_score",
    ]

    if include_extended_hours:
        header.extend(
            [
                "premarket_n_observations",
                "premarket_nrmse",
                "premarket_hit_rate",
                "premarket_passes",
                "premarket_error",
                "afterhours_n_observations",
                "afterhours_nrmse",
                "afterhours_hit_rate",
                "afterhours_passes",
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
                "overnight_reference_publisher_id",
                "overnight_error",
            ]
        )

    header.extend(["error", "execution_time_ms"])
    num_cols = len(header)

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
                f"{r.std_diff:.8f}" if r.std_diff is not None else "",
                f"{r.mean_pct_diff:.6f}" if r.mean_pct_diff is not None else "",
                f"{r.std_pct_diff:.6f}" if r.std_pct_diff is not None else "",
                f"{r.mae:.8f}" if r.mae is not None else "",
                f"{r.t_statistic:.4f}" if r.t_statistic is not None else "",
                f"{r.t_pvalue:.6f}" if r.t_pvalue is not None else "",
                f"{r.wilcoxon_statistic:.4f}"
                if r.wilcoxon_statistic is not None
                else "",
                f"{r.wilcoxon_pvalue:.6f}" if r.wilcoxon_pvalue is not None else "",
                f"{r.normality_pvalue:.6f}" if r.normality_pvalue is not None else "",
                f"{r.mean_abs_z_score:.4f}" if r.mean_abs_z_score is not None else "",
            ]

            if include_extended_hours:
                pm = r.premarket_metrics
                ah = r.afterhours_metrics
                row.extend(
                    [
                        pm.n_observations if pm else "",
                        f"{pm.nrmse:.6f}" if pm and pm.nrmse is not None else "",
                        f"{pm.hit_rate:.2f}" if pm and pm.hit_rate is not None else "",
                        pm.passes if pm else "",
                        pm.error or "" if pm else "",
                        ah.n_observations if ah else "",
                        f"{ah.nrmse:.6f}" if ah and ah.nrmse is not None else "",
                        f"{ah.hit_rate:.2f}" if ah and ah.hit_rate is not None else "",
                        ah.passes if ah else "",
                        ah.error or "" if ah else "",
                    ]
                )

            if include_overnight:
                on = r.overnight_metrics
                row.extend(
                    [
                        on.n_observations if on else "",
                        on.n_reference_observations if on else "",
                        f"{on.nrmse:.6f}" if on and on.nrmse is not None else "",
                        f"{on.hit_rate:.2f}" if on and on.hit_rate is not None else "",
                        on.passes if on else "",
                        on.reference_publisher_id if on else "",
                        on.error or "" if on else "",
                    ]
                )

            row.extend([r.error or "", r.execution_time_ms])
            writer.writerow(row)

        if summary_stats:
            writer.writerow([""] * num_cols)
            writer.writerow(["SUMMARY"] + [""] * (num_cols - 1))

            def write_summary_row(key: str, value):
                if value is None:
                    formatted_value = ""
                elif isinstance(value, float):
                    formatted_value = f"{value:.6f}"
                else:
                    formatted_value = str(value)
                writer.writerow([key, formatted_value] + [""] * (num_cols - 2))

            write_summary_row("publisher_id", summary_stats["publisher_id"])
            write_summary_row("total_feeds", summary_stats["total_feeds"])
            write_summary_row("pass_count", summary_stats["pass_count"])
            write_summary_row("fail_count", summary_stats["fail_count"])
            write_summary_row("error_count", summary_stats["error_count"])
            write_summary_row("pass_rate_pct", summary_stats["pass_rate_pct"])
            write_summary_row(
                "pass_by_nrmse_alone", summary_stats["pass_by_nrmse_alone"]
            )
            write_summary_row(
                "pass_by_nrmse_and_hit_rate",
                summary_stats["pass_by_nrmse_and_hit_rate"],
            )
            write_summary_row("median_nrmse", summary_stats["median_nrmse"])
            write_summary_row("mean_nrmse", summary_stats["mean_nrmse"])
            write_summary_row("p90_nrmse", summary_stats["p90_nrmse"])
            write_summary_row("p95_nrmse", summary_stats["p95_nrmse"])
            write_summary_row("min_nrmse", summary_stats["min_nrmse"])
            write_summary_row("max_nrmse", summary_stats["max_nrmse"])
            write_summary_row("median_hit_rate", summary_stats["median_hit_rate"])
            write_summary_row("mean_hit_rate", summary_stats["mean_hit_rate"])
            write_summary_row("min_hit_rate", summary_stats["min_hit_rate"])
            write_summary_row("max_hit_rate", summary_stats["max_hit_rate"])
            write_summary_row(
                "median_rmse_over_spread", summary_stats["median_rmse_over_spread"]
            )
            write_summary_row(
                "mean_rmse_over_spread", summary_stats["mean_rmse_over_spread"]
            )
            write_summary_row(
                "p90_rmse_over_spread", summary_stats["p90_rmse_over_spread"]
            )
            write_summary_row(
                "p95_rmse_over_spread", summary_stats["p95_rmse_over_spread"]
            )
            write_summary_row(
                "min_rmse_over_spread", summary_stats["min_rmse_over_spread"]
            )
            write_summary_row(
                "max_rmse_over_spread", summary_stats["max_rmse_over_spread"]
            )
            write_summary_row("total_observations", summary_stats["total_observations"])
            write_summary_row(
                "mean_observations_per_feed",
                summary_stats["mean_observations_per_feed"],
            )
            write_summary_row(
                "median_observations_per_feed",
                summary_stats["median_observations_per_feed"],
            )
            write_summary_row("total_time_sec", summary_stats["total_time_sec"])
            write_summary_row(
                "avg_time_per_feed_ms", summary_stats["avg_time_per_feed_ms"]
            )
            write_summary_row("median_mae", summary_stats.get("median_mae"))
            write_summary_row("mean_mae", summary_stats.get("mean_mae"))
            write_summary_row("p90_mae", summary_stats.get("p90_mae"))
            write_summary_row("p95_mae", summary_stats.get("p95_mae"))
            write_summary_row("median_mean_diff", summary_stats.get("median_mean_diff"))
            write_summary_row("mean_mean_diff", summary_stats.get("mean_mean_diff"))
            write_summary_row(
                "significant_t_tests", summary_stats.get("significant_t_tests")
            )
            write_summary_row("total_t_tests", summary_stats.get("total_t_tests"))
            write_summary_row(
                "t_test_significance_rate",
                summary_stats.get("t_test_significance_rate"),
            )
            write_summary_row(
                "normal_distributions", summary_stats.get("normal_distributions")
            )
            write_summary_row(
                "total_normality_tests", summary_stats.get("total_normality_tests")
            )
            write_summary_row("normality_rate", summary_stats.get("normality_rate"))
            write_summary_row("median_z_score", summary_stats.get("median_z_score"))
            write_summary_row("mean_z_score", summary_stats.get("mean_z_score"))

            mode_stats = summary_stats.get("mode_stats", {})
            for mode in sorted(mode_stats.keys()):
                stats = mode_stats[mode]
                write_summary_row(f"pass_count_{mode}", stats["pass"])
                write_summary_row(f"fail_count_{mode}", stats["fail"])
                write_summary_row(f"error_count_{mode}", stats["error"])

            ext_stats = summary_stats.get("extended_hours", {})
            if ext_stats:
                write_summary_row("", "")
                write_summary_row("EXTENDED_HOURS", "")
                for key in [
                    "premarket_total_feeds",
                    "premarket_pass_count",
                    "premarket_fail_count",
                    "premarket_error_count",
                    "premarket_pass_rate_pct",
                    "premarket_median_nrmse",
                    "premarket_median_hit_rate",
                    "afterhours_total_feeds",
                    "afterhours_pass_count",
                    "afterhours_fail_count",
                    "afterhours_error_count",
                    "afterhours_pass_rate_pct",
                    "afterhours_median_nrmse",
                    "afterhours_median_hit_rate",
                ]:
                    write_summary_row(key, ext_stats.get(key))

            overnight_stats_csv = summary_stats.get("overnight", {})
            if overnight_stats_csv:
                write_summary_row("", "")
                write_summary_row("OVERNIGHT_SESSION", "")
                for key in [
                    "overnight_reference_publisher_id",
                    "overnight_total_feeds",
                    "overnight_pass_count",
                    "overnight_fail_count",
                    "overnight_error_count",
                    "overnight_pass_rate_pct",
                    "overnight_median_nrmse",
                    "overnight_median_hit_rate",
                ]:
                    write_summary_row(key, overnight_stats_csv.get(key))

            per_date_breakdown = summary_stats.get("per_date_breakdown", {})
            if len(per_date_breakdown) > 1:
                writer.writerow([""] * num_cols)
                writer.writerow(["PER_DATE_BREAKDOWN"] + [""] * (num_cols - 1))
                writer.writerow(
                    [
                        "date",
                        "total",
                        "pass",
                        "fail",
                        "error",
                        "pass_rate_pct",
                        "median_nrmse",
                        "median_hit_rate",
                    ]
                    + [""] * (num_cols - 8)
                )
                for date_value in sorted(per_date_breakdown):
                    date_stats = per_date_breakdown[date_value]
                    writer.writerow(
                        [
                            date_value,
                            date_stats.get("total", ""),
                            date_stats.get("pass", ""),
                            date_stats.get("fail", ""),
                            date_stats.get("error", ""),
                            f"{date_stats.get('pass_rate_pct', 0):.2f}",
                            (
                                f"{date_stats['median_nrmse']:.6f}"
                                if date_stats.get("median_nrmse") is not None
                                else ""
                            ),
                            (
                                f"{date_stats['median_hit_rate']:.2f}"
                                if date_stats.get("median_hit_rate") is not None
                                else ""
                            ),
                        ]
                        + [""] * (num_cols - 8)
                    )

    print(f"\nResults written to: {output_path}")


def print_interpretation_guide(
    summary_stats: dict, hit_rate_threshold: float = 95
) -> None:
    """Print an interpretive guide explaining what the metrics mean."""
    print(f"\n{'='*70}")
    print("INTERPRETATION GUIDE - What These Numbers Mean")
    print(f"{'='*70}")

    print("\n--- PASS/FAIL CRITERIA ---")
    print(
        f"Your feed PASSES if: nrmse < 0.01 OR (nrmse < 0.05 AND hit_rate >= {hit_rate_threshold}%)"
    )
    print("  - nrmse: RMSE normalized by benchmark price range (lower is better)")
    print(
        "  - hit_rate: % of prices within 10 basis points of benchmark (higher is better)"
    )

    print("\n--- ACCURACY METRICS ---")
    print("MAE (Mean Absolute Error):")
    print("  - Average absolute deviation from benchmark price")
    print(
        "  - Interpretation: Lower is better; should be small relative to asset price"
    )
    if summary_stats.get("median_mae") is not None:
        print(f"  - Your median MAE: {summary_stats['median_mae']:.8f}")

    mean_diff = summary_stats.get("mean_mean_diff")
    if mean_diff is not None:
        print(f"\nMean Difference (Systematic Bias): {mean_diff:.8f}")
        if abs(mean_diff) < 1e-8:
            print("  - Your prices show NO systematic bias (excellent)")
        elif mean_diff > 0:
            print("  - Your prices tend to be HIGHER than benchmark")
            print("  - ACTION: Review price source calibration")
        else:
            print("  - Your prices tend to be LOWER than benchmark")
            print("  - ACTION: Review price source calibration")

    print("\n--- STATISTICAL TESTS ---")

    t_rate = summary_stats.get("t_test_significance_rate")
    total_t = summary_stats.get("total_t_tests", 0)
    sig_t = summary_stats.get("significant_t_tests", 0)
    if t_rate is not None:
        print(f"\nT-Test Significance: {sig_t}/{total_t} feeds ({t_rate:.1f}%)")
        print("  - Tests if mean price difference is statistically different from zero")
        if t_rate > 50:
            print(
                "  - HIGH rate (>50%) suggests systematic pricing bias across many feeds"
            )
            print("  - ACTION: Investigate price source accuracy and calibration")
        elif t_rate > 20:
            print("  - MODERATE rate suggests some feeds have systematic bias")
            print("  - ACTION: Review failing feeds individually")
        else:
            print("  - LOW rate (<20%) is good - differences appear mostly random")

    norm_rate = summary_stats.get("normality_rate")
    total_norm = summary_stats.get("total_normality_tests", 0)
    normal_count = summary_stats.get("normal_distributions", 0)
    if norm_rate is not None:
        print(
            f"\nNormality Test: {normal_count}/{total_norm} feeds ({norm_rate:.1f}%) have normally distributed errors"
        )
        if norm_rate >= 70:
            print("  - HIGH rate indicates consistent, predictable error patterns")
            print("  - Errors are likely due to latency/timing rather than data issues")
        elif norm_rate >= 40:
            print("  - MODERATE rate - mixed error patterns")
        else:
            print("  - LOW rate suggests outliers or irregular error patterns")
            print(
                "  - ACTION: Investigate data quality issues, latency spikes, or stale prices"
            )

    median_z = summary_stats.get("median_z_score")
    if median_z is not None:
        print(f"\nMedian Z-Score: {median_z:.4f}")
        print("  - Average deviation from mean in standard deviation units")
        print("  - Expected value for normal distribution: ~0.8")
        if median_z > 1.5:
            print("  - HIGH z-scores indicate frequent large deviations (outliers)")
            print("  - ACTION: Add spike detection or validate price updates")
        elif median_z < 0.5:
            print(
                "  - LOW z-scores indicate very stable, consistent pricing (excellent)"
            )
        else:
            print("  - NORMAL range - typical error volatility")

    print(f"\n{'='*70}")
    print("HOW TO IMPROVE YOUR DATA QUALITY")
    print(f"{'='*70}")
    print("1. REDUCE SYSTEMATIC BIAS:")
    print("   - Calibrate your price source against benchmark")
    print("   - Check for rounding or truncation issues")
    print("   - Verify timezone handling is correct")
    print("\n2. REDUCE RANDOM ERROR:")
    print("   - Improve data freshness (reduce latency)")
    print("   - Increase update frequency during volatile periods")
    print("   - Use faster data sources")
    print("\n3. REDUCE OUTLIERS:")
    print("   - Add spike detection before publishing")
    print("   - Validate price updates against recent history")
    print("   - Implement circuit breakers for extreme moves")
    print("\n4. INCREASE HIT RATE:")
    print(f"   - Target: >{hit_rate_threshold}% of prices within 10 basis points")
    print("   - Monitor real-time deviation from benchmark")
    print("   - Alert on sustained deviations")
    print(f"{'='*70}\n")


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
    print(
        f"Pass criteria: nrmse < 0.01 OR (nrmse < 0.05 AND hit_rate >= {args.hit_rate_threshold}%)"
    )
    print(f"{'='*70}")
    print(f"Total feeds evaluated: {summary_stats['total_feeds']}")
    print(f"PASS: {summary_stats['pass_count']}")
    print(f"  - by nrmse < 0.01 alone: {summary_stats['pass_by_nrmse_alone']}")
    print(
        f"  - by nrmse < 0.05 + hit_rate >= {args.hit_rate_threshold}%: {summary_stats['pass_by_nrmse_and_hit_rate']}"
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
        summary_stats, hit_rate_threshold=args.hit_rate_threshold
    )


if __name__ == "__main__":
    main()
