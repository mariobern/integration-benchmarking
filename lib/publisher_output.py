"""Output formatting for single-publisher benchmark results.

Extracted from publisher_benchmark.py. Contains summary computation,
CSV writing, and interpretation guide for PublisherBenchmarkResult data.

Functions:
    compute_summary_stats      - Comprehensive summary statistics
    write_results_csv          - CSV output with optional summary section
    print_interpretation_guide - Console guide explaining metrics
"""

from __future__ import annotations

import csv
import statistics
from pathlib import Path
from typing import Optional

from lib.config import normalize_asset_class
from lib.models import OVERNIGHT_REFERENCE_PUBLISHER_ID, PublisherBenchmarkResult
from lib.statistics import distribution_stats
from lib.thresholds import get_session_thresholds, get_threshold_description


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

    pass_by_nrmse_alone = 0
    pass_by_nrmse_and_hit_rate = 0
    for r in results:
        if not (r.passes and not r.error and r.nrmse is not None):
            continue
        t = get_session_thresholds("regular", r.mode or "us-equities")
        if r.nrmse < t.nrmse_auto_pass:
            pass_by_nrmse_alone += 1
        elif (
            r.nrmse < t.nrmse_conditional
            and r.hit_rate is not None
            and r.hit_rate >= t.hit_rate_threshold
        ):
            pass_by_nrmse_and_hit_rate += 1

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
    summary_stats: dict, hit_rate_threshold: float = 95, mode: str = "us-equities"
) -> None:
    """Print an interpretive guide explaining what the metrics mean."""
    print(f"\n{'='*70}")
    print("INTERPRETATION GUIDE - What These Numbers Mean")
    print(f"{'='*70}")

    print("\n--- PASS/FAIL CRITERIA ---")
    print(f"Your feed PASSES if: {get_threshold_description(mode)}")
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
    t = get_session_thresholds("regular", mode)
    print(f"   - Target: >{t.hit_rate_threshold}% of prices within 10 basis points")
    print("   - Monitor real-time deviation from benchmark")
    print("   - Alert on sustained deviations")
    print(f"{'='*70}\n")
