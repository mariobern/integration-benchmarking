"""Core publisher health evaluation logic.

Extracted from publisher_report.py to enable reuse and keep the script
as a thin CLI wrapper.

Functions:
    classify_health            - HEALTHY/DEGRADED/FAILING classification
    get_uptime_sessions        - Trading session windows for uptime computation
    compute_feed_uptime        - 1-second window uptime for one publisher+feed
    merge_benchmark_and_uptime - Combine benchmark + uptime into FeedHealthResult
    run_report                 - Full report: benchmark + uptime for all feeds
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from lib.config import normalize_asset_class
from lib.models import PublisherBenchmarkResult


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

    if mode in ("fx", "metals", "commodity", "us-treasuries"):
        sessions.append(
            {
                "name": "regular",
                "start": datetime.combine(dt.date(), datetime.min.time()),
                "end": datetime.combine(
                    dt.date() + timedelta(days=1), datetime.min.time()
                ),
            }
        )
    else:
        market_open = (
            dt.replace(hour=9, minute=30, tzinfo=est)
            .astimezone(utc)
            .replace(tzinfo=None)
        )
        market_close = (
            dt.replace(hour=16, minute=0, tzinfo=est)
            .astimezone(utc)
            .replace(tzinfo=None)
        )
        sessions.append({"name": "regular", "start": market_open, "end": market_close})

        if extended_hours:
            pm_start = (
                dt.replace(hour=4, minute=0, tzinfo=est)
                .astimezone(utc)
                .replace(tzinfo=None)
            )
            sessions.append(
                {"name": "premarket", "start": pm_start, "end": market_open}
            )
            ah_end = (
                dt.replace(hour=20, minute=0, tzinfo=est)
                .astimezone(utc)
                .replace(tzinfo=None)
            )
            sessions.append(
                {"name": "afterhours", "start": market_close, "end": ah_end}
            )

        if overnight:
            on_start = (
                dt.replace(hour=20, minute=0, tzinfo=est)
                .astimezone(utc)
                .replace(tzinfo=None)
            )
            next_day = dt + timedelta(days=1)
            on_end = (
                next_day.replace(hour=4, minute=0, tzinfo=est)
                .astimezone(utc)
                .replace(tzinfo=None)
            )
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
            if(total_seconds > 0, updates_total / total_seconds, 0) AS updates_per_second,
            if(total_seconds > 0, seconds_with_data * 100.0 / total_seconds, 0) AS uptime_pct
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
        benchmark_price_range=getattr(benchmark, "benchmark_price_range", None),
        rmse=benchmark.rmse,
        mean_spread=benchmark.mean_spread,
        rmse_over_spread=benchmark.rmse_over_spread,
        mean_diff=getattr(benchmark, "mean_diff", None),
        t_pvalue=getattr(benchmark, "t_pvalue", None),
        normality_pvalue=getattr(benchmark, "normality_pvalue", None),
        mean_abs_z_score=getattr(benchmark, "mean_abs_z_score", None),
        uptime_pct=uptime["uptime_pct"],
        seconds_with_data=uptime["seconds_with_data"],
        total_seconds=uptime["total_seconds"],
        updates_total=uptime["updates_total"],
        updates_per_second=uptime["updates_per_second"],
        health_status=health,
        error=benchmark.error,
        execution_time_ms=getattr(benchmark, "execution_time_ms", 0),
    )


def run_report(
    benchmark_results: list,  # list[PublisherBenchmarkResult]
    publisher_id: int,
    config: dict,
    uptime_threshold: float = 95.0,
    include_extended_hours: bool = False,
    include_overnight: bool = False,
    max_workers: int = 4,
) -> list[FeedHealthResult]:
    """
    Compute uptime for all benchmark results and merge into health results.

    For each benchmark result:
    1. Compute 1s-window uptime for the regular trading session
    2. Optionally compute uptime for extended hours / overnight sessions
    3. Merge benchmark + uptime into FeedHealthResult
    """
    lazer_cfg = config["lazer_clickhouse_prod"]
    import clickhouse_connect

    health_results: list[FeedHealthResult] = []

    def process_single(benchmark_result):
        """Process a single benchmark result: compute uptime and merge."""
        client = clickhouse_connect.get_client(
            host=lazer_cfg["host"],
            username=lazer_cfg["user"],
            password=lazer_cfg["password"],
            secure=True,
            connect_timeout=60,
            send_receive_timeout=300,
        )

        mode = normalize_asset_class(benchmark_result.mode)

        # Get session windows
        sessions = get_uptime_sessions(
            benchmark_result.date,
            mode,
            extended_hours=include_extended_hours,
            overnight=include_overnight,
        )

        # Compute uptime for regular session
        regular_session = next((s for s in sessions if s["name"] == "regular"), None)
        if regular_session:
            regular_uptime = compute_feed_uptime(
                client,
                publisher_id,
                benchmark_result.feed_id,
                regular_session["start"],
                regular_session["end"],
            )
        else:
            regular_uptime = {
                "uptime_pct": 0.0,
                "seconds_with_data": 0,
                "total_seconds": 0,
                "updates_total": 0,
                "updates_per_second": 0.0,
            }

        # Merge benchmark + regular uptime
        health = merge_benchmark_and_uptime(
            benchmark_result, regular_uptime, uptime_threshold
        )

        # Compute uptime for extended/overnight sessions
        for session in sessions:
            if session["name"] == "regular":
                continue

            session_uptime = compute_feed_uptime(
                client,
                publisher_id,
                benchmark_result.feed_id,
                session["start"],
                session["end"],
            )

            if session["name"] == "premarket":
                health.premarket_uptime_pct = session_uptime["uptime_pct"]
            elif session["name"] == "afterhours":
                health.afterhours_uptime_pct = session_uptime["uptime_pct"]
            elif session["name"] == "overnight":
                health.overnight_uptime_pct = session_uptime["uptime_pct"]

        # Populate extended benchmark fields from the benchmark result
        if (
            include_extended_hours
            and hasattr(benchmark_result, "premarket_metrics")
            and benchmark_result.premarket_metrics
        ):
            pm = benchmark_result.premarket_metrics
            health.premarket_n_observations = pm.n_observations
            health.premarket_nrmse = pm.nrmse
            health.premarket_hit_rate = pm.hit_rate
            health.premarket_passes = pm.passes
            health.premarket_error = pm.error

        if (
            include_extended_hours
            and hasattr(benchmark_result, "afterhours_metrics")
            and benchmark_result.afterhours_metrics
        ):
            ah = benchmark_result.afterhours_metrics
            health.afterhours_n_observations = ah.n_observations
            health.afterhours_nrmse = ah.nrmse
            health.afterhours_hit_rate = ah.hit_rate
            health.afterhours_passes = ah.passes
            health.afterhours_error = ah.error

        if (
            include_overnight
            and hasattr(benchmark_result, "overnight_metrics")
            and benchmark_result.overnight_metrics
        ):
            on = benchmark_result.overnight_metrics
            health.overnight_n_observations = on.n_observations
            health.overnight_n_reference_observations = on.n_reference_observations
            health.overnight_nrmse = on.nrmse
            health.overnight_hit_rate = on.hit_rate
            health.overnight_passes = on.passes
            health.overnight_reference_publisher_id = on.reference_publisher_id
            health.overnight_error = on.error

        return health

    # Process in parallel
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_single, br): br for br in benchmark_results}
        for future in as_completed(futures):
            br = futures[future]
            try:
                result = future.result()
                health_results.append(result)
                status_str = result.health_status
                uptime_str = f"{result.uptime_pct:.1f}%"
                print(
                    f"  Feed {result.feed_id} ({result.symbol or 'unknown'}): "
                    f"{status_str} - uptime={uptime_str}"
                )
            except Exception as e:
                print(f"  Feed {br.feed_id}: ERROR computing uptime - {e}")
                # Create a result with 0 uptime on error
                fallback_uptime = {
                    "uptime_pct": 0.0,
                    "seconds_with_data": 0,
                    "total_seconds": 0,
                    "updates_total": 0,
                    "updates_per_second": 0.0,
                }
                health_results.append(
                    merge_benchmark_and_uptime(br, fallback_uptime, uptime_threshold)
                )

    return health_results
