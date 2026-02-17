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
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from publisher_benchmark_95 import PublisherBenchmarkResult


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


def get_uptime_sessions(
    date_str: str,
    mode: str,
    extended_hours: bool = False,
    overnight: bool = False,
) -> list[dict]:
    """
    Get trading session windows for uptime computation.

    Returns list of dicts with 'name', 'start' (UTC datetime), 'end' (UTC datetime).
    """
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    est = ZoneInfo("America/New_York")
    utc = ZoneInfo("UTC")

    sessions: list[dict] = []

    if mode in ("fx", "metals"):
        sessions.append({
            "name": "regular",
            "start": datetime.combine(dt.date(), datetime.min.time()),
            "end": datetime.combine(dt.date() + timedelta(days=1), datetime.min.time()),
        })
    else:
        market_open = dt.replace(hour=9, minute=30, tzinfo=est).astimezone(utc).replace(tzinfo=None)
        market_close = dt.replace(hour=16, minute=0, tzinfo=est).astimezone(utc).replace(tzinfo=None)
        sessions.append({"name": "regular", "start": market_open, "end": market_close})

        if extended_hours:
            pm_start = dt.replace(hour=4, minute=0, tzinfo=est).astimezone(utc).replace(tzinfo=None)
            sessions.append({"name": "premarket", "start": pm_start, "end": market_open})
            ah_end = dt.replace(hour=20, minute=0, tzinfo=est).astimezone(utc).replace(tzinfo=None)
            sessions.append({"name": "afterhours", "start": market_close, "end": ah_end})

        if overnight:
            on_start = dt.replace(hour=20, minute=0, tzinfo=est).astimezone(utc).replace(tzinfo=None)
            next_day = dt + timedelta(days=1)
            on_end = next_day.replace(hour=4, minute=0, tzinfo=est).astimezone(utc).replace(tzinfo=None)
            sessions.append({"name": "overnight", "start": on_start, "end": on_end})

    return sessions


def compute_feed_uptime(
    client,
    publisher_id: int,
    feed_id: int,
    start_utc: datetime,
    end_utc: datetime,
) -> dict:
    """
    Compute uptime using 1-second window method.

    Counts seconds that have at least one update. Matches dashboard calculation.
    """
    start_str = start_utc.strftime("%Y-%m-%d %H:%M:%S")
    end_str = end_utc.strftime("%Y-%m-%d %H:%M:%S")

    query = f"""
        WITH
            parseDateTimeBestEffort('{start_str}') AS start_time,
            parseDateTimeBestEffort('{end_str}') AS end_time,
            dateDiff('second', start_time, end_time) AS total_seconds,

            per_second AS (
                SELECT
                    toStartOfSecond(publish_time) AS second_start,
                    count() AS update_count
                FROM publisher_updates
                PREWHERE price_feed_id = {feed_id}
                    AND publisher_id = {publisher_id}
                WHERE publish_time >= start_time
                    AND publish_time < end_time
                GROUP BY second_start
            )
        SELECT
            sum(update_count) AS updates_total,
            count() AS seconds_with_data,
            total_seconds,
            updates_total / total_seconds AS updates_per_second,
            (seconds_with_data * 100.0 / total_seconds) AS uptime_pct
        FROM per_second
    """

    result = client.query(query)

    if not result.result_rows or result.result_rows[0][0] is None:
        total_seconds = int((end_utc - start_utc).total_seconds())
        return {
            "uptime_pct": 0.0,
            "seconds_with_data": 0,
            "total_seconds": total_seconds,
            "updates_total": 0,
            "updates_per_second": 0.0,
        }

    row = result.result_rows[0]
    return {
        "uptime_pct": float(row[4] or 0),
        "seconds_with_data": int(row[1] or 0),
        "total_seconds": int(row[2] or 0),
        "updates_total": int(row[0] or 0),
        "updates_per_second": float(row[3] or 0),
    }


def merge_benchmark_and_uptime(
    benchmark: PublisherBenchmarkResult,
    uptime: dict,
    threshold: float = 95.0,
) -> FeedHealthResult:
    """
    Merge a benchmark result with uptime data into a FeedHealthResult.

    Args:
        benchmark: Result from evaluate_publisher_feed()
        uptime: Dict from compute_feed_uptime() for the regular session
        threshold: Minimum uptime % for HEALTHY classification
    """
    health = classify_health(benchmark.passes, uptime["uptime_pct"], threshold)

    return FeedHealthResult(
        publisher_id=benchmark.publisher_id,
        feed_id=benchmark.feed_id,
        date=benchmark.date,
        mode=benchmark.mode,
        symbol=benchmark.symbol,
        passes=benchmark.passes,
        n_observations=benchmark.n_observations,
        nrmse=benchmark.nrmse,
        hit_rate=benchmark.hit_rate,
        benchmark_price_range=getattr(benchmark, 'benchmark_price_range', None),
        rmse=benchmark.rmse,
        mean_spread=benchmark.mean_spread,
        rmse_over_spread=benchmark.rmse_over_spread,
        mean_diff=getattr(benchmark, 'mean_diff', None),
        t_pvalue=getattr(benchmark, 't_pvalue', None),
        normality_pvalue=getattr(benchmark, 'normality_pvalue', None),
        mean_abs_z_score=getattr(benchmark, 'mean_abs_z_score', None),
        uptime_pct=uptime["uptime_pct"],
        seconds_with_data=uptime["seconds_with_data"],
        total_seconds=uptime["total_seconds"],
        updates_total=uptime["updates_total"],
        updates_per_second=uptime["updates_per_second"],
        health_status=health,
        error=benchmark.error,
        execution_time_ms=getattr(benchmark, 'execution_time_ms', 0),
    )


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
