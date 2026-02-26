"""Shared statistical computation functions for benchmark scripts."""

from __future__ import annotations

import statistics as _statistics
from typing import Optional


def compute_statistical_metrics(
    diffs: list[float],
    signed_pct_diffs: list[float],
    min_observations: int = 20,
) -> dict:
    """Compute advanced statistical metrics for price differences."""

    result = {
        "mean_diff": None,
        "std_diff": None,
        "mean_pct_diff": None,
        "std_pct_diff": None,
        "mae": None,
        "t_statistic": None,
        "t_pvalue": None,
        "wilcoxon_statistic": None,
        "wilcoxon_pvalue": None,
        "normality_pvalue": None,
        "mean_abs_z_score": None,
    }

    n = len(diffs)
    if n < 2:
        return result

    result["mean_diff"] = _statistics.mean(diffs)
    result["std_diff"] = _statistics.stdev(diffs)
    result["mean_pct_diff"] = _statistics.mean(signed_pct_diffs)
    result["std_pct_diff"] = _statistics.stdev(signed_pct_diffs) if n >= 2 else None
    result["mae"] = _statistics.mean([abs(d) for d in diffs])

    if result["std_diff"] and result["std_diff"] > 0:
        z_scores = [(d - result["mean_diff"]) / result["std_diff"] for d in diffs]
        result["mean_abs_z_score"] = _statistics.mean([abs(z) for z in z_scores])

    if n < min_observations:
        return result

    try:
        from scipy import stats
    except Exception:
        return result

    try:
        t_stat, t_pval = stats.ttest_1samp(diffs, 0)
        result["t_statistic"] = float(t_stat)
        result["t_pvalue"] = float(t_pval)
    except Exception:
        pass

    try:
        non_zero_diffs = [d for d in diffs if d != 0]
        if len(non_zero_diffs) >= min_observations:
            w_stat, w_pval = stats.wilcoxon(non_zero_diffs)
            result["wilcoxon_statistic"] = float(w_stat)
            result["wilcoxon_pvalue"] = float(w_pval)
    except Exception:
        pass

    try:
        _, norm_pval = stats.normaltest(diffs)
        result["normality_pvalue"] = float(norm_pval)
    except Exception:
        pass

    return result


def distribution_stats(values: list[float]) -> dict[str, Optional[float]]:
    """Compute distribution statistics: median, mean, min, max, p90, p95."""
    if not values:
        return {
            "median": None,
            "mean": None,
            "min": None,
            "max": None,
            "p90": None,
            "p95": None,
        }

    sorted_values = sorted(values)
    n = len(sorted_values)
    if n >= 2:
        try:
            quantiles = _statistics.quantiles(sorted_values, n=100)
            p90 = quantiles[89]
            p95 = quantiles[94]
        except _statistics.StatisticsError:
            p90 = sorted_values[min(int(n * 0.90), n - 1)]
            p95 = sorted_values[min(int(n * 0.95), n - 1)]
    else:
        p90 = sorted_values[0]
        p95 = sorted_values[0]

    return {
        "median": _statistics.median(sorted_values),
        "mean": _statistics.mean(sorted_values),
        "min": min(sorted_values),
        "max": max(sorted_values),
        "p90": p90,
        "p95": p95,
    }
