#!/usr/bin/env python3
"""
Combined publisher health report: benchmark quality + uptime in one script.

Combines data quality evaluation (from publisher_benchmark_95.py) with
uptime measurement (1s window method) to give publishers a unified health
view per feed.

Health Classification:
- HEALTHY:  Benchmark passes AND uptime >= threshold (default 95%)
- DEGRADED: One of benchmark or uptime fails, but not both
- FAILING:  Benchmark fails AND uptime < threshold

Usage:
    python publisher_report.py --csv publisher_55_feeds.csv
    python publisher_report.py --publisher-id 55 --feed-id 327 --date 2026-02-17 --mode fx
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class FeedHealthResult:
    """Combined benchmark + uptime result for a single feed."""
    # Core identification
    publisher_id: int
    feed_id: int
    date: str
    mode: str
    symbol: Optional[str]

    # Benchmark metrics
    passes: bool
    n_observations: int
    nrmse: Optional[float]
    hit_rate: Optional[float]
    benchmark_price_range: Optional[float]
    rmse: Optional[float]
    mean_spread: Optional[float]
    rmse_over_spread: Optional[float]

    # Statistical diagnostics (top 3)
    mean_diff: Optional[float]
    t_pvalue: Optional[float]
    normality_pvalue: Optional[float]
    mean_abs_z_score: Optional[float]

    # Uptime metrics (1s window)
    uptime_pct: float
    seconds_with_data: int
    total_seconds: int
    updates_total: int
    updates_per_second: float

    # Health classification
    health_status: str  # HEALTHY, DEGRADED, FAILING

    # Extended hours (optional)
    premarket_nrmse: Optional[float] = None
    premarket_hit_rate: Optional[float] = None
    premarket_passes: Optional[bool] = None
    premarket_n_observations: Optional[int] = None
    premarket_uptime_pct: Optional[float] = None
    premarket_error: Optional[str] = None

    afterhours_nrmse: Optional[float] = None
    afterhours_hit_rate: Optional[float] = None
    afterhours_passes: Optional[bool] = None
    afterhours_n_observations: Optional[int] = None
    afterhours_uptime_pct: Optional[float] = None
    afterhours_error: Optional[str] = None

    # Overnight (optional)
    overnight_nrmse: Optional[float] = None
    overnight_hit_rate: Optional[float] = None
    overnight_passes: Optional[bool] = None
    overnight_n_observations: Optional[int] = None
    overnight_n_reference_observations: Optional[int] = None
    overnight_uptime_pct: Optional[float] = None
    overnight_reference_publisher_id: Optional[int] = None
    overnight_error: Optional[str] = None

    # Error and timing
    error: Optional[str] = None
    execution_time_ms: int = 0


def classify_health(passes: bool, uptime_pct: float, threshold: float) -> str:
    """
    Classify feed health based on benchmark pass/fail and uptime.

    Args:
        passes: Whether benchmark evaluation passed
        uptime_pct: Uptime percentage (0-100)
        threshold: Minimum uptime percentage for HEALTHY status

    Returns:
        "HEALTHY", "DEGRADED", or "FAILING"
    """
    uptime_ok = uptime_pct >= threshold
    if passes and uptime_ok:
        return "HEALTHY"
    elif passes or uptime_ok:
        return "DEGRADED"
    else:
        return "FAILING"
