#!/usr/bin/env python3
"""
Combined feed readiness evaluator (benchmark quality + publisher uptime).

A feed is READY only when at least target publisher count pass both:
- benchmark quality (quick_benchmark rules)
- regular-session uptime threshold (feed_uptime rules)
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional, TypedDict

from date_utils import expand_date_args, validate_date_args
from lib.uptime_core import (
    DEFAULT_GAP_THRESHOLD_MS,
    DEFAULT_UPTIME_THRESHOLD_PCT,
    evaluate_feed_uptime,
)
from lib.config import (
    ASSET_CLASS_ALIASES,
    BENCHMARKABLE_ASSET_CLASSES,
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
from lib.benchmark_core import (
    evaluate_feed_two_queries,
    list_asset_classes_in_csv,
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


def _distribution_stats(values: list[float]) -> dict[str, Optional[float]]:
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
            quantiles = statistics.quantiles(sorted_values, n=100)
            p90 = quantiles[89]
            p95 = quantiles[94]
        except statistics.StatisticsError:
            p90 = sorted_values[min(int(n * 0.90), n - 1)]
            p95 = sorted_values[min(int(n * 0.95), n - 1)]
    else:
        p90 = sorted_values[0]
        p95 = sorted_values[0]

    return {
        "median": statistics.median(sorted_values),
        "mean": statistics.mean(sorted_values),
        "min": min(sorted_values),
        "max": max(sorted_values),
        "p90": p90,
        "p95": p95,
    }


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

    for publisher_id in all_publisher_ids:
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

        if regular_uptime is None:
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

        if fully_passes:
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
        total_publisher_count=len(all_publisher_ids),
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
                include_extended_hours=include_extended_hours,
                include_overnight=include_overnight,
                skip_scipy_tests=skip_scipy_tests,
                include_detailed=True,
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
) -> list[FeedReadinessResult]:
    if not work_items:
        print("Warning: No feeds to process")
        return []

    config = load_config()
    worker_count = max(1, min(max_workers, len(work_items)))
    print(f"Processing {len(work_items)} feeds with {worker_count} workers...")

    def evaluate_single(item: tuple[int, str, str]) -> FeedReadinessResult:
        feed_id, date, mode = item
        start_time = time.time()
        try:
            client_lazer, client_analytics = get_clients(config)
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
            )
        except Exception as exc:
            return FeedReadinessResult(
                feed_id=feed_id,
                date=date,
                mode=normalize_asset_class(mode),
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
                benchmark_error=str(exc),
                uptime_error=str(exc),
                error=str(exc),
                execution_time_ms=int((time.time() - start_time) * 1000),
                publisher_details=[] if include_detailed else None,
            )

    results: list[FeedReadinessResult] = []
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {executor.submit(evaluate_single, item): item for item in work_items}
        for future in as_completed(futures):
            feed_id, date, _ = futures[future]
            try:
                result = future.result()
            except Exception as exc:
                result = FeedReadinessResult(
                    feed_id=feed_id,
                    date=date,
                    mode="",
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
                    benchmark_error=str(exc),
                    uptime_error=str(exc),
                    error=str(exc),
                    execution_time_ms=0,
                    publisher_details=[] if include_detailed else None,
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
    )


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
                continue  # no data for this session → skip
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


def _format_ratio(count: int, total: int) -> str:
    if total <= 0:
        return "0.0%"
    return f"{(count * 100.0 / total):.1f}%"


def _format_id_list(values: list[int]) -> str:
    if not values:
        return "None"
    return ", ".join(str(value) for value in values)


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


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Combined feed readiness (benchmark quality + uptime)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single feed, single date
  python feed_readiness.py --feed-id 327 --date 2026-02-10 --mode fx

  # Multi-date range
  python feed_readiness.py --feed-id 327 --start-date 2026-02-10 --end-date 2026-02-12 --mode fx

  # CSV batch
  python feed_readiness.py --csv price_id_list.csv --workers 8

  # With uptime precision + extended hours
  python feed_readiness.py --feed-id 922 --date 2026-02-10 --mode us-equities --precise --extended-hours

  # Detailed mode
  python feed_readiness.py --feed-id 327 --date 2026-02-10 --mode fx --detailed
""",
    )

    parser.add_argument(
        "--csv", type=Path, help="CSV file containing feed_id,date,mode columns"
    )
    parser.add_argument(
        "--feed-id", type=int, nargs="+", metavar="ID", help="Feed ID(s) to evaluate"
    )
    parser.add_argument(
        "--date",
        nargs="+",
        metavar="YYYY-MM-DD",
        help="Date(s) for single feed evaluation (YYYY-MM-DD)",
    )
    parser.add_argument("--start-date", help="Range start date (inclusive, YYYY-MM-DD)")
    parser.add_argument("--end-date", help="Range end date (inclusive, YYYY-MM-DD)")
    parser.add_argument("--mode", type=str, help="Asset class for single feed mode")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("feed_readiness_results.csv"),
        help="Output CSV path (default: feed_readiness_results.csv)",
    )
    parser.add_argument(
        "--detailed",
        action="store_true",
        help="Append PUBLISHER DETAIL and consistency sections to CSV",
    )
    parser.add_argument(
        "--target-pub-count",
        type=int,
        default=4,
        help="Target publisher count for feed readiness (default: 4)",
    )
    parser.add_argument(
        "--skip-scipy-tests",
        action="store_true",
        help="Skip benchmark t-test/Wilcoxon/normality tests for faster execution",
    )
    parser.add_argument(
        "--precise",
        action="store_true",
        help="Use 200ms gap-based uptime method instead of default 1-second window",
    )
    parser.add_argument(
        "--gap-threshold",
        type=int,
        default=DEFAULT_GAP_THRESHOLD_MS,
        help="Gap threshold in milliseconds for --precise mode (default: 200)",
    )
    parser.add_argument(
        "--uptime-threshold",
        type=float,
        default=DEFAULT_UPTIME_THRESHOLD_PCT,
        help="Regular-session uptime pass threshold percent (default: 95.0)",
    )
    parser.add_argument(
        "--extended-hours",
        action="store_true",
        help="Include pre-market and after-hours sessions for US equities",
    )
    parser.add_argument(
        "--overnight",
        action="store_true",
        help="Include overnight session for US equities",
    )
    parser.add_argument(
        "--workers", type=int, default=4, help="Number of parallel workers (default: 4)"
    )
    parser.add_argument(
        "--include-asset-class",
        type=str,
        nargs="+",
        metavar="CLASS",
        help="Only process feeds with these asset classes (CSV mode)",
    )
    parser.add_argument(
        "--exclude-asset-class",
        type=str,
        nargs="+",
        metavar="CLASS",
        help="Exclude feeds with these asset classes (CSV mode)",
    )
    parser.add_argument(
        "--filter-feed-id",
        type=int,
        nargs="+",
        metavar="ID",
        help="Only process these feed IDs when using --csv",
    )
    parser.add_argument(
        "--list-asset-classes",
        action="store_true",
        help="List unique asset classes in the CSV file and exit",
    )

    args = parser.parse_args()
    single_feed_dates: list[str] = []

    if args.workers <= 0:
        parser.error("--workers must be a positive integer")
    if args.target_pub_count <= 0:
        parser.error("--target-pub-count must be a positive integer")
    if args.gap_threshold <= 0:
        parser.error("--gap-threshold must be a positive integer")
    if not args.precise and args.gap_threshold != DEFAULT_GAP_THRESHOLD_MS:
        parser.error("--gap-threshold requires --precise")
    if args.uptime_threshold < 0 or args.uptime_threshold > 100:
        parser.error("--uptime-threshold must be between 0 and 100")

    if args.list_asset_classes:
        if not args.csv:
            parser.error("--list-asset-classes requires --csv")
    elif args.csv and (
        args.feed_id or args.date or args.start_date or args.end_date or args.mode
    ):
        parser.error(
            "Use either --csv OR (--feed-id, --date/--start-date+--end-date, --mode), not both"
        )
    elif not args.csv and not (args.feed_id and args.mode):
        parser.error(
            "Either --csv or all of (--feed-id, --date/--start-date+--end-date, --mode) required"
        )

    if not args.csv:
        try:
            validate_date_args(args)
            single_feed_dates = expand_date_args(
                args.date, args.start_date, args.end_date
            )
        except ValueError as exc:
            parser.error(str(exc))
        if not single_feed_dates:
            parser.error("Single-feed mode requires --date or --start-date/--end-date")

    if not args.csv and (args.include_asset_class or args.exclude_asset_class):
        parser.error(
            "--include-asset-class and --exclude-asset-class only apply to --csv mode"
        )
    if not args.csv and args.filter_feed_id:
        parser.error("--filter-feed-id only applies to --csv mode")

    if args.include_asset_class and args.exclude_asset_class:
        include_set = {
            normalize_asset_class(asset) for asset in args.include_asset_class
        }
        exclude_set = {
            normalize_asset_class(asset) for asset in args.exclude_asset_class
        }
        overlap = include_set & exclude_set
        if overlap:
            parser.error(
                f"Asset classes cannot be both included and excluded: {overlap}"
            )

    if args.csv and not args.csv.exists():
        print(f"Error: CSV file '{args.csv}' not found")
        sys.exit(1)

    if args.list_asset_classes:
        asset_classes = list_asset_classes_in_csv(args.csv)
        total_feeds = sum(asset_classes.values())

        print(f"\nAsset classes in {args.csv}:")
        print(f"{'='*56}")
        for asset_class, count in sorted(asset_classes.items(), key=lambda x: -x[1]):
            normalized = normalize_asset_class(asset_class)
            benchmarkable = "Y" if normalized in BENCHMARKABLE_ASSET_CLASSES else "N"
            alias_display = ASSET_CLASS_ALIASES.get(
                asset_class.lower(), asset_class.lower()
            )
            print(
                f"  {asset_class:<25} {count:>5} feeds  "
                f"[normalized: {alias_display:<12} benchmarkable: {benchmarkable}]"
            )
        print(f"{'='*56}")
        print(f"  {'TOTAL':<25} {total_feeds:>5} feeds")
        print(
            f"\nBenchmarkable asset classes: {', '.join(sorted(BENCHMARKABLE_ASSET_CLASSES))}"
        )
        sys.exit(0)

    if args.extended_hours or args.overnight:
        if args.csv:
            print(
                "Note: --extended-hours and --overnight only apply to us-equities feeds; "
                "other asset classes are evaluated normally."
            )
        else:
            if normalize_asset_class(args.mode) != "us-equities":
                print(
                    "Warning: --extended-hours/--overnight only apply to us-equities; "
                    "session metrics will be skipped for this run."
                )

    total_start = time.time()
    if args.csv:
        feed_id_filter = set(args.filter_feed_id) if args.filter_feed_id else None
        results = process_csv(
            csv_path=args.csv,
            max_workers=args.workers,
            target_pub_count=args.target_pub_count,
            include_asset_classes=args.include_asset_class,
            exclude_asset_classes=args.exclude_asset_class,
            include_extended_hours=args.extended_hours,
            include_overnight=args.overnight,
            feed_id_filter=feed_id_filter,
            skip_scipy_tests=args.skip_scipy_tests,
            precise=args.precise,
            gap_threshold_ms=args.gap_threshold,
            uptime_threshold_pct=args.uptime_threshold,
            include_detailed=args.detailed,
        )
    else:
        work_items = [
            (feed_id, date, args.mode)
            for feed_id in args.feed_id
            for date in single_feed_dates
        ]
        results = process_work_items(
            work_items=work_items,
            max_workers=args.workers,
            target_pub_count=args.target_pub_count,
            include_extended_hours=args.extended_hours,
            include_overnight=args.overnight,
            skip_scipy_tests=args.skip_scipy_tests,
            precise=args.precise,
            gap_threshold_ms=args.gap_threshold,
            uptime_threshold_pct=args.uptime_threshold,
            include_detailed=args.detailed,
        )

    write_results_csv(
        results=results,
        output_path=args.output,
        include_extended_hours=args.extended_hours,
        include_overnight=args.overnight,
        include_detailed=args.detailed,
    )

    total_time = time.time() - total_start
    print_console_summary(
        results=results,
        total_time_seconds=total_time,
        target_pub_count=args.target_pub_count,
        uptime_threshold_pct=args.uptime_threshold,
    )

    if args.detailed and len({result.date for result in results}) > 1:
        consistency = compute_publisher_consistency(results)
        if consistency["rows"]:
            print_publisher_consistency(consistency)

        # Per-session consistency console output
        if args.extended_hours:
            for session_name, extractor in [
                ("PREMARKET", _premarket_status),
                ("AFTERHOURS", _afterhours_status),
            ]:
                session_consistency = compute_publisher_consistency(
                    results, status_extractor=extractor
                )
                if session_consistency["rows"]:
                    print_publisher_consistency(
                        session_consistency, session_prefix=f"{session_name} "
                    )

        if args.overnight:
            session_consistency = compute_publisher_consistency(
                results, status_extractor=_overnight_status
            )
            if session_consistency["rows"]:
                print_publisher_consistency(
                    session_consistency, session_prefix="OVERNIGHT "
                )

    print(f"\nResults written to: {args.output}")


if __name__ == "__main__":
    main()
