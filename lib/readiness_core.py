"""Core feed readiness evaluation logic.

Extracted from feed_readiness.py to enable reuse and keep the script
as a thin CLI wrapper.

Functions:
    merge_results              - Merge benchmark + uptime into FeedReadinessResult
    evaluate_feed_readiness    - Evaluate one feed's readiness (benchmark + uptime)
    process_work_items         - Parallel evaluation of multiple feeds
    process_csv                - CSV batch processor with filtering
"""

from __future__ import annotations

import csv
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, TypedDict

from lib.benchmark_core import evaluate_feed_two_queries
from lib.config import (
    BENCHMARKABLE_ASSET_CLASSES,
    ThreadLocalClients,
    get_clients,
    load_config,
    normalize_asset_class,
)
from lib.models import (
    BenchmarkResult,
    FeedUptimeResult,
    PublisherFeedMetrics,
    PublisherSessionUptime,
)
from lib.uptime_core import (
    DEFAULT_GAP_THRESHOLD_MS,
    DEFAULT_UPTIME_THRESHOLD_PCT,
    evaluate_feed_uptime,
)

# Session name constants
SESSION_REGULAR = "regular"
SESSION_PREMARKET = "premarket"
SESSION_AFTERHOURS = "afterhours"
SESSION_OVERNIGHT = "overnight"


class SessionReadinessStats(TypedDict):
    ready: bool
    fully_passing_count: int
    fully_passing_publishers: list[int]
    uptime_passing_count: int
    uptime_failing_count: int
    median_uptime_pct: Optional[float]


@dataclass
class PublisherReadinessDetail:
    publisher_id: int
    benchmark_passes: bool
    benchmark_nrmse: Optional[float]
    benchmark_hit_rate: Optional[float]
    benchmark_n_observations: int
    benchmark_error: Optional[str]
    uptime_passes: bool
    uptime_pct: Optional[float]
    uptime_error: Optional[str]
    fully_passes: bool
    benchmark_detail: Optional[PublisherFeedMetrics] = None
    uptime_sessions: Optional[list[PublisherSessionUptime]] = None
    # Extended session benchmark (populated when --extended-hours / --overnight)
    premarket_benchmark_passes: Optional[bool] = None
    premarket_benchmark_nrmse: Optional[float] = None
    premarket_benchmark_hit_rate: Optional[float] = None
    premarket_benchmark_n_observations: Optional[int] = None
    afterhours_benchmark_passes: Optional[bool] = None
    afterhours_benchmark_nrmse: Optional[float] = None
    afterhours_benchmark_hit_rate: Optional[float] = None
    afterhours_benchmark_n_observations: Optional[int] = None
    overnight_benchmark_passes: Optional[bool] = None
    overnight_benchmark_nrmse: Optional[float] = None
    overnight_benchmark_hit_rate: Optional[float] = None
    overnight_benchmark_n_observations: Optional[int] = None
    # Extended session uptime (populated when --extended-hours / --overnight)
    premarket_uptime_passes: Optional[bool] = None
    premarket_uptime_pct: Optional[float] = None
    afterhours_uptime_passes: Optional[bool] = None
    afterhours_uptime_pct: Optional[float] = None
    overnight_uptime_passes: Optional[bool] = None
    overnight_uptime_pct: Optional[float] = None


@dataclass
class FeedReadinessResult:
    feed_id: int
    date: str
    mode: str
    symbol: Optional[str]
    ready: bool
    benchmark_ready: bool
    uptime_ready: bool
    target_pub_count: int
    fully_passing_count: int
    benchmark_only_passing_count: int
    uptime_only_passing_count: int
    both_failing_count: int
    total_publisher_count: int
    benchmark_passing_count: int
    benchmark_failing_count: int
    median_nrmse: Optional[float]
    median_hit_rate: Optional[float]
    uptime_passing_count: int
    uptime_failing_count: int
    median_uptime_pct: Optional[float]
    fully_passing_publishers: list[int]
    benchmark_only_publishers: list[int]
    uptime_only_publishers: list[int]
    both_failing_publishers: list[int]
    premarket_benchmark_passing_count: Optional[int] = None
    afterhours_benchmark_passing_count: Optional[int] = None
    overnight_benchmark_passing_count: Optional[int] = None
    # Per-session readiness (populated when --extended-hours / --overnight)
    premarket_ready: Optional[bool] = None
    premarket_fully_passing_count: Optional[int] = None
    premarket_uptime_passing_count: Optional[int] = None
    premarket_uptime_failing_count: Optional[int] = None
    premarket_median_uptime_pct: Optional[float] = None
    premarket_fully_passing_publishers: Optional[list[int]] = None

    afterhours_ready: Optional[bool] = None
    afterhours_fully_passing_count: Optional[int] = None
    afterhours_uptime_passing_count: Optional[int] = None
    afterhours_uptime_failing_count: Optional[int] = None
    afterhours_median_uptime_pct: Optional[float] = None
    afterhours_fully_passing_publishers: Optional[list[int]] = None

    overnight_ready: Optional[bool] = None
    overnight_fully_passing_count: Optional[int] = None
    overnight_uptime_passing_count: Optional[int] = None
    overnight_uptime_failing_count: Optional[int] = None
    overnight_median_uptime_pct: Optional[float] = None
    overnight_fully_passing_publishers: Optional[list[int]] = None
    benchmark_error: Optional[str] = None
    uptime_error: Optional[str] = None
    error: Optional[str] = None
    execution_time_ms: int = 0
    publisher_details: Optional[list[PublisherReadinessDetail]] = None


def _placeholder_benchmark_result(
    feed_id: int,
    date: str,
    mode: str,
    target_pub_count: int,
    error: str,
) -> BenchmarkResult:
    return BenchmarkResult(
        feed_id=feed_id,
        date=date,
        mode=mode,
        symbol=None,
        ready=False,
        target_pub_count=target_pub_count,
        passing_pub_count=0,
        failing_pub_count=0,
        passing_publishers=[],
        failing_publishers=[],
        median_nrmse=None,
        median_hit_rate=None,
        publisher_details=[],
        error=error,
        execution_time_ms=0,
    )


def _placeholder_uptime_result(
    feed_id: int,
    date: str,
    mode: str,
    error: str,
) -> FeedUptimeResult:
    return FeedUptimeResult(
        feed_id=feed_id,
        date=date,
        mode=mode,
        symbol=None,
        publisher_count=0,
        publisher_uptimes=[],
        error=error,
        execution_time_ms=0,
    )


def _compute_session_readiness(
    benchmark_passes_by_pub: dict[int, bool],
    uptime_by_pub: dict[int, PublisherSessionUptime],
    target_pub_count: int,
) -> SessionReadinessStats:
    """Compute readiness stats for a single session."""
    all_pub_ids = sorted(set(benchmark_passes_by_pub) | set(uptime_by_pub))
    fully_passing: list[int] = []

    for pub_id in all_pub_ids:
        bench_passes = benchmark_passes_by_pub.get(pub_id, False)
        uptime_entry = uptime_by_pub.get(pub_id)
        uptime_passes = uptime_entry.passes if uptime_entry else False
        if bench_passes and uptime_passes:
            fully_passing.append(pub_id)

    uptime_rows = list(uptime_by_pub.values())
    uptime_passing_count = sum(1 for u in uptime_rows if u.passes)
    uptime_failing_count = len(uptime_rows) - uptime_passing_count
    uptime_values = [u.uptime_pct for u in uptime_rows]
    median_uptime = statistics.median(uptime_values) if uptime_values else None

    return {
        "ready": len(fully_passing) >= target_pub_count,
        "fully_passing_count": len(fully_passing),
        "fully_passing_publishers": fully_passing,
        "uptime_passing_count": uptime_passing_count,
        "uptime_failing_count": uptime_failing_count,
        "median_uptime_pct": median_uptime,
    }


def merge_results(
    benchmark_result: BenchmarkResult,
    uptime_result: FeedUptimeResult,
    target_pub_count: int,
    include_detailed: bool = False,
) -> FeedReadinessResult:
    benchmark_details = benchmark_result.publisher_details or []
    benchmark_by_pub = {detail.publisher_id: detail for detail in benchmark_details}

    uptime_sessions_by_pub: dict[int, list[PublisherSessionUptime]] = {}
    for uptime in uptime_result.publisher_uptimes:
        uptime_sessions_by_pub.setdefault(uptime.publisher_id, []).append(uptime)

    regular_uptime_by_pub = {
        uptime.publisher_id: uptime
        for uptime in uptime_result.publisher_uptimes
        if uptime.session == SESSION_REGULAR
    }
    premarket_uptime_by_pub = {
        uptime.publisher_id: uptime
        for uptime in uptime_result.publisher_uptimes
        if uptime.session == SESSION_PREMARKET
    }
    afterhours_uptime_by_pub = {
        uptime.publisher_id: uptime
        for uptime in uptime_result.publisher_uptimes
        if uptime.session == SESSION_AFTERHOURS
    }
    overnight_uptime_by_pub = {
        uptime.publisher_id: uptime
        for uptime in uptime_result.publisher_uptimes
        if uptime.session == SESSION_OVERNIGHT
    }

    premarket_bench_passes: dict[int, bool] = {}
    afterhours_bench_passes: dict[int, bool] = {}
    overnight_bench_passes: dict[int, bool] = {}

    for detail in benchmark_details:
        if detail.premarket_metrics is not None:
            premarket_bench_passes[
                detail.publisher_id
            ] = detail.premarket_metrics.passes and not bool(
                detail.premarket_metrics.error
            )
        if detail.afterhours_metrics is not None:
            afterhours_bench_passes[
                detail.publisher_id
            ] = detail.afterhours_metrics.passes and not bool(
                detail.afterhours_metrics.error
            )
        if detail.overnight_metrics is not None:
            overnight_bench_passes[
                detail.publisher_id
            ] = detail.overnight_metrics.passes and not bool(
                detail.overnight_metrics.error
            )

    all_publisher_ids = sorted(set(benchmark_by_pub) | set(regular_uptime_by_pub))

    fully_passing_publishers: list[int] = []
    benchmark_only_publishers: list[int] = []
    uptime_only_publishers: list[int] = []
    both_failing_publishers: list[int] = []
    readiness_details: list[PublisherReadinessDetail] = []

    # Exclude publisher 0 from total count — it's the aggregate feed
    non_agg_publisher_ids = [pid for pid in all_publisher_ids if pid != 0]

    for publisher_id in all_publisher_ids:
        is_aggregate = publisher_id == 0

        benchmark_detail = benchmark_by_pub.get(publisher_id)
        regular_uptime = regular_uptime_by_pub.get(publisher_id)

        if benchmark_detail is None:
            benchmark_passes = False
            benchmark_nrmse = None
            benchmark_hit_rate = None
            benchmark_n_observations = 0
            benchmark_error = (
                "Benchmark evaluation unavailable"
                if benchmark_result.error
                else "Missing benchmark publisher result"
            )
        else:
            benchmark_passes = benchmark_detail.passes and not bool(
                benchmark_detail.error
            )
            benchmark_nrmse = benchmark_detail.nrmse
            benchmark_hit_rate = benchmark_detail.hit_rate
            benchmark_n_observations = benchmark_detail.n_observations
            benchmark_error = benchmark_detail.error

        if is_aggregate:
            uptime_passes = False
            uptime_pct = None
            uptime_error = None
        elif regular_uptime is None:
            uptime_passes = False
            uptime_pct = None
            uptime_error = (
                "Uptime evaluation unavailable"
                if uptime_result.error
                else "Missing regular-session uptime result"
            )
        else:
            uptime_passes = regular_uptime.passes
            uptime_pct = regular_uptime.uptime_pct
            uptime_error = None

        fully_passes = benchmark_passes and uptime_passes

        if is_aggregate:
            pass  # Publisher 0 excluded from readiness buckets
        elif fully_passes:
            fully_passing_publishers.append(publisher_id)
        elif benchmark_passes and not uptime_passes:
            benchmark_only_publishers.append(publisher_id)
        elif uptime_passes and not benchmark_passes:
            uptime_only_publishers.append(publisher_id)
        else:
            both_failing_publishers.append(publisher_id)

        readiness_details.append(
            PublisherReadinessDetail(
                publisher_id=publisher_id,
                benchmark_passes=benchmark_passes,
                benchmark_nrmse=benchmark_nrmse,
                benchmark_hit_rate=benchmark_hit_rate,
                benchmark_n_observations=benchmark_n_observations,
                benchmark_error=benchmark_error,
                uptime_passes=uptime_passes,
                uptime_pct=uptime_pct,
                uptime_error=uptime_error,
                fully_passes=fully_passes,
                benchmark_detail=benchmark_detail if include_detailed else None,
                uptime_sessions=uptime_sessions_by_pub.get(publisher_id)
                if include_detailed
                else None,
                premarket_benchmark_passes=(
                    benchmark_detail.premarket_metrics.passes
                    and not bool(benchmark_detail.premarket_metrics.error)
                )
                if benchmark_detail is not None
                and benchmark_detail.premarket_metrics is not None
                else None,
                premarket_benchmark_nrmse=benchmark_detail.premarket_metrics.nrmse
                if benchmark_detail is not None
                and benchmark_detail.premarket_metrics is not None
                else None,
                premarket_benchmark_hit_rate=benchmark_detail.premarket_metrics.hit_rate
                if benchmark_detail is not None
                and benchmark_detail.premarket_metrics is not None
                else None,
                premarket_benchmark_n_observations=benchmark_detail.premarket_metrics.n_observations
                if benchmark_detail is not None
                and benchmark_detail.premarket_metrics is not None
                else None,
                afterhours_benchmark_passes=(
                    benchmark_detail.afterhours_metrics.passes
                    and not bool(benchmark_detail.afterhours_metrics.error)
                )
                if benchmark_detail is not None
                and benchmark_detail.afterhours_metrics is not None
                else None,
                afterhours_benchmark_nrmse=benchmark_detail.afterhours_metrics.nrmse
                if benchmark_detail is not None
                and benchmark_detail.afterhours_metrics is not None
                else None,
                afterhours_benchmark_hit_rate=benchmark_detail.afterhours_metrics.hit_rate
                if benchmark_detail is not None
                and benchmark_detail.afterhours_metrics is not None
                else None,
                afterhours_benchmark_n_observations=benchmark_detail.afterhours_metrics.n_observations
                if benchmark_detail is not None
                and benchmark_detail.afterhours_metrics is not None
                else None,
                overnight_benchmark_passes=(
                    benchmark_detail.overnight_metrics.passes
                    and not bool(benchmark_detail.overnight_metrics.error)
                )
                if benchmark_detail is not None
                and benchmark_detail.overnight_metrics is not None
                else None,
                overnight_benchmark_nrmse=benchmark_detail.overnight_metrics.nrmse
                if benchmark_detail is not None
                and benchmark_detail.overnight_metrics is not None
                else None,
                overnight_benchmark_hit_rate=benchmark_detail.overnight_metrics.hit_rate
                if benchmark_detail is not None
                and benchmark_detail.overnight_metrics is not None
                else None,
                overnight_benchmark_n_observations=benchmark_detail.overnight_metrics.n_observations
                if benchmark_detail is not None
                and benchmark_detail.overnight_metrics is not None
                else None,
                premarket_uptime_passes=premarket_uptime_by_pub[publisher_id].passes
                if publisher_id in premarket_uptime_by_pub
                else None,
                premarket_uptime_pct=premarket_uptime_by_pub[publisher_id].uptime_pct
                if publisher_id in premarket_uptime_by_pub
                else None,
                afterhours_uptime_passes=afterhours_uptime_by_pub[publisher_id].passes
                if publisher_id in afterhours_uptime_by_pub
                else None,
                afterhours_uptime_pct=afterhours_uptime_by_pub[publisher_id].uptime_pct
                if publisher_id in afterhours_uptime_by_pub
                else None,
                overnight_uptime_passes=overnight_uptime_by_pub[publisher_id].passes
                if publisher_id in overnight_uptime_by_pub
                else None,
                overnight_uptime_pct=overnight_uptime_by_pub[publisher_id].uptime_pct
                if publisher_id in overnight_uptime_by_pub
                else None,
            )
        )

    regular_uptime_rows = [
        u for u in uptime_result.publisher_uptimes if u.session == SESSION_REGULAR
    ]
    uptime_passing_count = sum(1 for u in regular_uptime_rows if u.passes)
    uptime_failing_count = len(regular_uptime_rows) - uptime_passing_count

    regular_uptime_values = [u.uptime_pct for u in regular_uptime_rows]
    median_uptime_pct = (
        statistics.median(regular_uptime_values) if regular_uptime_values else None
    )

    benchmark_ready = benchmark_result.ready and not bool(benchmark_result.error)
    uptime_ready = (
        not bool(uptime_result.error) and uptime_passing_count >= target_pub_count
    )

    ready = (
        not bool(benchmark_result.error)
        and not bool(uptime_result.error)
        and len(fully_passing_publishers) >= target_pub_count
    )

    error_parts = []
    if benchmark_result.error:
        error_parts.append(f"benchmark: {benchmark_result.error}")
    if uptime_result.error:
        error_parts.append(f"uptime: {uptime_result.error}")

    premarket_stats = (
        _compute_session_readiness(
            premarket_bench_passes, premarket_uptime_by_pub, target_pub_count
        )
        if premarket_bench_passes or premarket_uptime_by_pub
        else None
    )
    afterhours_stats = (
        _compute_session_readiness(
            afterhours_bench_passes, afterhours_uptime_by_pub, target_pub_count
        )
        if afterhours_bench_passes or afterhours_uptime_by_pub
        else None
    )
    overnight_stats = (
        _compute_session_readiness(
            overnight_bench_passes, overnight_uptime_by_pub, target_pub_count
        )
        if overnight_bench_passes or overnight_uptime_by_pub
        else None
    )

    return FeedReadinessResult(
        feed_id=benchmark_result.feed_id,
        date=benchmark_result.date,
        mode=benchmark_result.mode,
        symbol=benchmark_result.symbol or uptime_result.symbol,
        ready=ready,
        benchmark_ready=benchmark_ready,
        uptime_ready=uptime_ready,
        target_pub_count=target_pub_count,
        fully_passing_count=len(fully_passing_publishers),
        benchmark_only_passing_count=len(benchmark_only_publishers),
        uptime_only_passing_count=len(uptime_only_publishers),
        both_failing_count=len(both_failing_publishers),
        total_publisher_count=len(non_agg_publisher_ids),
        benchmark_passing_count=benchmark_result.passing_pub_count,
        benchmark_failing_count=benchmark_result.failing_pub_count,
        median_nrmse=benchmark_result.median_nrmse,
        median_hit_rate=benchmark_result.median_hit_rate,
        uptime_passing_count=uptime_passing_count,
        uptime_failing_count=uptime_failing_count,
        median_uptime_pct=median_uptime_pct,
        fully_passing_publishers=fully_passing_publishers,
        benchmark_only_publishers=benchmark_only_publishers,
        uptime_only_publishers=uptime_only_publishers,
        both_failing_publishers=both_failing_publishers,
        premarket_benchmark_passing_count=benchmark_result.premarket_passing_count,
        afterhours_benchmark_passing_count=benchmark_result.afterhours_passing_count,
        overnight_benchmark_passing_count=benchmark_result.overnight_passing_count,
        premarket_ready=premarket_stats["ready"] if premarket_stats else None,
        premarket_fully_passing_count=premarket_stats["fully_passing_count"]
        if premarket_stats
        else None,
        premarket_uptime_passing_count=premarket_stats["uptime_passing_count"]
        if premarket_stats
        else None,
        premarket_uptime_failing_count=premarket_stats["uptime_failing_count"]
        if premarket_stats
        else None,
        premarket_median_uptime_pct=premarket_stats["median_uptime_pct"]
        if premarket_stats
        else None,
        premarket_fully_passing_publishers=premarket_stats["fully_passing_publishers"]
        if premarket_stats
        else None,
        afterhours_ready=afterhours_stats["ready"] if afterhours_stats else None,
        afterhours_fully_passing_count=afterhours_stats["fully_passing_count"]
        if afterhours_stats
        else None,
        afterhours_uptime_passing_count=afterhours_stats["uptime_passing_count"]
        if afterhours_stats
        else None,
        afterhours_uptime_failing_count=afterhours_stats["uptime_failing_count"]
        if afterhours_stats
        else None,
        afterhours_median_uptime_pct=afterhours_stats["median_uptime_pct"]
        if afterhours_stats
        else None,
        afterhours_fully_passing_publishers=afterhours_stats["fully_passing_publishers"]
        if afterhours_stats
        else None,
        overnight_ready=overnight_stats["ready"] if overnight_stats else None,
        overnight_fully_passing_count=overnight_stats["fully_passing_count"]
        if overnight_stats
        else None,
        overnight_uptime_passing_count=overnight_stats["uptime_passing_count"]
        if overnight_stats
        else None,
        overnight_uptime_failing_count=overnight_stats["uptime_failing_count"]
        if overnight_stats
        else None,
        overnight_median_uptime_pct=overnight_stats["median_uptime_pct"]
        if overnight_stats
        else None,
        overnight_fully_passing_publishers=overnight_stats["fully_passing_publishers"]
        if overnight_stats
        else None,
        benchmark_error=benchmark_result.error,
        uptime_error=uptime_result.error,
        error=" | ".join(error_parts) if error_parts else None,
        publisher_details=readiness_details if include_detailed else None,
    )


def evaluate_feed_readiness(
    client_lazer,
    client_analytics,
    feed_id: int,
    date: str,
    mode: str,
    target_pub_count: int = 4,
    include_extended_hours: bool = False,
    include_overnight: bool = False,
    skip_scipy_tests: bool = False,
    precise: bool = False,
    gap_threshold_ms: int = DEFAULT_GAP_THRESHOLD_MS,
    uptime_threshold_pct: float = DEFAULT_UPTIME_THRESHOLD_PCT,
    include_detailed: bool = False,
    tolerance_seconds: int = 60,
    include_agg: bool = True,
) -> FeedReadinessResult:
    start_time = time.time()
    normalized_mode = normalize_asset_class(mode)

    if normalized_mode in BENCHMARKABLE_ASSET_CLASSES:
        try:
            benchmark_result = evaluate_feed_two_queries(
                client_lazer,
                client_analytics,
                feed_id,
                date,
                normalized_mode,
                target_pub_count=target_pub_count,
                tolerance_seconds=tolerance_seconds,
                include_extended_hours=include_extended_hours,
                include_overnight=include_overnight,
                skip_scipy_tests=skip_scipy_tests,
                include_detailed=True,
                include_agg=include_agg,
            )
        except Exception as exc:
            benchmark_result = _placeholder_benchmark_result(
                feed_id=feed_id,
                date=date,
                mode=normalized_mode,
                target_pub_count=target_pub_count,
                error=str(exc),
            )
    else:
        benchmark_result = _placeholder_benchmark_result(
            feed_id=feed_id,
            date=date,
            mode=normalized_mode,
            target_pub_count=target_pub_count,
            error="Asset class not benchmarkable",
        )

    try:
        uptime_result = evaluate_feed_uptime(
            client=client_lazer,
            feed_id=feed_id,
            date=date,
            mode=normalized_mode,
            include_extended_hours=include_extended_hours,
            include_overnight=include_overnight,
            precise=precise,
            gap_threshold_ms=gap_threshold_ms,
            uptime_threshold_pct=uptime_threshold_pct,
        )
    except Exception as exc:
        uptime_result = _placeholder_uptime_result(
            feed_id=feed_id,
            date=date,
            mode=normalized_mode,
            error=str(exc),
        )

    merged = merge_results(
        benchmark_result=benchmark_result,
        uptime_result=uptime_result,
        target_pub_count=target_pub_count,
        include_detailed=include_detailed,
    )
    merged.execution_time_ms = int((time.time() - start_time) * 1000)
    return merged


def _make_error_result(
    feed_id: int,
    date: str,
    mode: str,
    target_pub_count: int,
    error: str,
    execution_time_ms: int = 0,
    include_detailed: bool = False,
) -> FeedReadinessResult:
    """Create a FeedReadinessResult for an error case."""
    return FeedReadinessResult(
        feed_id=feed_id,
        date=date,
        mode=normalize_asset_class(mode) if mode else "",
        symbol=None,
        ready=False,
        benchmark_ready=False,
        uptime_ready=False,
        target_pub_count=target_pub_count,
        fully_passing_count=0,
        benchmark_only_passing_count=0,
        uptime_only_passing_count=0,
        both_failing_count=0,
        total_publisher_count=0,
        benchmark_passing_count=0,
        benchmark_failing_count=0,
        median_nrmse=None,
        median_hit_rate=None,
        uptime_passing_count=0,
        uptime_failing_count=0,
        median_uptime_pct=None,
        fully_passing_publishers=[],
        benchmark_only_publishers=[],
        uptime_only_publishers=[],
        both_failing_publishers=[],
        benchmark_error=error,
        uptime_error=error,
        error=error,
        execution_time_ms=execution_time_ms,
        publisher_details=[] if include_detailed else None,
    )


def process_work_items(
    work_items: list[tuple[int, str, str]],
    max_workers: int,
    target_pub_count: int,
    include_extended_hours: bool = False,
    include_overnight: bool = False,
    skip_scipy_tests: bool = False,
    precise: bool = False,
    gap_threshold_ms: int = DEFAULT_GAP_THRESHOLD_MS,
    uptime_threshold_pct: float = DEFAULT_UPTIME_THRESHOLD_PCT,
    include_detailed: bool = False,
    tolerance_seconds: int = 60,
    include_agg: bool = True,
) -> list[FeedReadinessResult]:
    if not work_items:
        print("Warning: No feeds to process")
        return []

    config = load_config()
    worker_count = max(1, min(max_workers, len(work_items)))
    print(f"Processing {len(work_items)} feeds with {worker_count} workers...")

    def evaluate_single(
        pool: ThreadLocalClients, item: tuple[int, str, str]
    ) -> FeedReadinessResult:
        feed_id, date, mode = item
        start_time = time.time()
        try:
            client_lazer, client_analytics = pool.get_clients()
            return evaluate_feed_readiness(
                client_lazer=client_lazer,
                client_analytics=client_analytics,
                feed_id=feed_id,
                date=date,
                mode=mode,
                target_pub_count=target_pub_count,
                include_extended_hours=include_extended_hours,
                include_overnight=include_overnight,
                skip_scipy_tests=skip_scipy_tests,
                precise=precise,
                gap_threshold_ms=gap_threshold_ms,
                uptime_threshold_pct=uptime_threshold_pct,
                include_detailed=include_detailed,
                tolerance_seconds=tolerance_seconds,
                include_agg=include_agg,
            )
        except Exception as exc:
            return _make_error_result(
                feed_id=feed_id,
                date=date,
                mode=mode,
                target_pub_count=target_pub_count,
                error=str(exc),
                execution_time_ms=int((time.time() - start_time) * 1000),
                include_detailed=include_detailed,
            )

    results: list[FeedReadinessResult] = []
    with ThreadLocalClients(config) as pool, ThreadPoolExecutor(
        max_workers=worker_count
    ) as executor:
        futures = {
            executor.submit(evaluate_single, pool, item): item for item in work_items
        }
        for future in as_completed(futures):
            feed_id, date, _ = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = _make_error_result(
                    feed_id=feed_id,
                    date=date,
                    mode="",
                    target_pub_count=target_pub_count,
                    error=str(exc),
                    include_detailed=include_detailed,
                )

            results.append(result)
            status = "READY" if result.ready else "NOT READY"
            if result.error:
                status = f"ERROR: {result.error[:60]}"

            print(
                f"  [{result.execution_time_ms:>5}ms] Feed {result.feed_id} ({result.date}, {result.mode}): "
                f"{status} | fully={result.fully_passing_count} "
                f"bench_only={result.benchmark_only_passing_count} "
                f"uptime_only={result.uptime_only_passing_count} "
                f"both_fail={result.both_failing_count}"
            )

    return sorted(
        results, key=lambda r: (r.date, r.feed_id, normalize_asset_class(r.mode))
    )


def process_csv(
    csv_path: Path,
    max_workers: int,
    target_pub_count: int,
    include_asset_classes: Optional[list[str]] = None,
    exclude_asset_classes: Optional[list[str]] = None,
    include_extended_hours: bool = False,
    include_overnight: bool = False,
    feed_id_filter: Optional[set[int]] = None,
    skip_scipy_tests: bool = False,
    precise: bool = False,
    gap_threshold_ms: int = DEFAULT_GAP_THRESHOLD_MS,
    uptime_threshold_pct: float = DEFAULT_UPTIME_THRESHOLD_PCT,
    include_detailed: bool = False,
    tolerance_seconds: int = 60,
    include_agg: bool = True,
) -> list[FeedReadinessResult]:
    include_normalized = None
    if include_asset_classes:
        include_normalized = {
            normalize_asset_class(asset) for asset in include_asset_classes
        }

    exclude_normalized: set[str] = set()
    if exclude_asset_classes:
        exclude_normalized = {
            normalize_asset_class(asset) for asset in exclude_asset_classes
        }

    work_items: list[tuple[int, str, str]] = []
    skipped_by_asset_class = 0

    with open(csv_path) as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or not row[0].strip():
                continue
            if len(row) < 3:
                print(f"Warning: Skipping incomplete row: {row}")
                continue

            feed_id_str, date_value, mode_value = (
                row[0].strip(),
                row[1].strip(),
                row[2].strip(),
            )
            normalized_mode = normalize_asset_class(mode_value)

            if include_normalized and normalized_mode not in include_normalized:
                skipped_by_asset_class += 1
                continue
            if normalized_mode in exclude_normalized:
                skipped_by_asset_class += 1
                continue

            try:
                feed_id = int(feed_id_str)
                datetime.strptime(date_value, "%Y-%m-%d")
            except ValueError:
                print(f"Warning: Skipping invalid row: {row}")
                continue

            work_items.append((feed_id, date_value, mode_value))

    if skipped_by_asset_class > 0:
        print(f"Filtered out {skipped_by_asset_class} feeds by asset class")

    skipped_by_feed_id = 0
    if feed_id_filter is not None:
        filtered_work_items = []
        for feed_id, date_value, mode_value in work_items:
            if feed_id in feed_id_filter:
                filtered_work_items.append((feed_id, date_value, mode_value))
            else:
                skipped_by_feed_id += 1
        work_items = filtered_work_items

    if skipped_by_feed_id > 0:
        keep_ids = ", ".join(str(feed_id) for feed_id in sorted(feed_id_filter))
        print(
            f"Filtered out {skipped_by_feed_id} feeds by feed ID "
            f"(kept {len(work_items)} matching: {keep_ids})"
        )

    return process_work_items(
        work_items=work_items,
        max_workers=max_workers,
        target_pub_count=target_pub_count,
        include_extended_hours=include_extended_hours,
        include_overnight=include_overnight,
        skip_scipy_tests=skip_scipy_tests,
        precise=precise,
        gap_threshold_ms=gap_threshold_ms,
        uptime_threshold_pct=uptime_threshold_pct,
        include_detailed=include_detailed,
        tolerance_seconds=tolerance_seconds,
        include_agg=include_agg,
    )
