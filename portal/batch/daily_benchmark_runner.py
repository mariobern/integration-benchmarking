#!/usr/bin/env python3
"""
Daily batch job to run benchmarks for all active publishers.

This script orchestrates the daily benchmark evaluation:
1. Discovers all active publishers from ClickHouse
2. For each publisher, generates their feed list
3. Runs publisher_benchmark.py to evaluate performance
4. Stores results in Postgres
5. Computes daily summary aggregates

Usage:
    python -m portal.batch.daily_benchmark_runner
    python -m portal.batch.daily_benchmark_runner --date 2025-01-25
    python -m portal.batch.daily_benchmark_runner --publisher-id 55
    python -m portal.batch.daily_benchmark_runner --dry-run
"""

import argparse
import logging
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

import clickhouse_connect
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from portal.batch.result_parser import parse_benchmark_csv, result_to_dict
from portal.batch.uptime_runner import compute_and_store_uptime_for_publisher
from portal.batch.uptime_summary import (
    compute_daily_uptime_summary,
    link_uptime_to_benchmark_summary,
)
from portal.config import settings
from portal.db import get_session
from portal.models import (
    BenchmarkJob,
    BenchmarkResult,
    Feed,
    Publisher,
    PublisherDailySummary,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Path to benchmark scripts (relative to project root)
PROJECT_ROOT = Path(__file__).parent.parent.parent
PUBLISHER_FEEDS_SCRIPT = PROJECT_ROOT / "publisher_feeds.py"
PUBLISHER_BENCHMARK_SCRIPT = PROJECT_ROOT / "publisher_benchmark.py"


def get_clickhouse_client():
    """Create ClickHouse client for Lazer database."""
    config = settings.get_clickhouse_lazer_config()
    return clickhouse_connect.get_client(**config)


def get_active_publishers(client, time_window_minutes: int = 5) -> list[int]:
    """
    Query all publishers with recent activity.

    Args:
        client: ClickHouse client
        time_window_minutes: How far back to look for activity

    Returns:
        List of active publisher IDs
    """
    query = f"""
        SELECT DISTINCT publisher_id
        FROM feed_publisher_junction
        FINAL
        WHERE last_updated_at >= now() - INTERVAL {time_window_minutes} MINUTE
        ORDER BY publisher_id
    """
    result = client.query(query)
    return [row[0] for row in result.result_rows]


def run_publisher_feeds(
    publisher_id: int,
    output_path: Path,
    date_offset: int = 1,
    time_window: int = 5,
) -> bool:
    """
    Run publisher_feeds.py to generate feeds CSV for a publisher.

    Args:
        publisher_id: Publisher ID to query
        output_path: Path to write CSV output
        date_offset: Days to subtract for benchmark data availability
        time_window: Time window in minutes to look back

    Returns:
        True if successful, False otherwise
    """
    cmd = [
        sys.executable,
        str(PUBLISHER_FEEDS_SCRIPT),
        "--publisher-id",
        str(publisher_id),
        "--output",
        str(output_path),
        "--date-offset",
        str(date_offset),
        "--time-window",
        str(time_window),
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,  # 5 minute timeout
            cwd=str(PROJECT_ROOT),
        )

        if result.returncode != 0:
            logger.error(
                f"publisher_feeds.py failed for publisher {publisher_id}: {result.stderr}"
            )
            return False

        return output_path.exists() and output_path.stat().st_size > 0

    except subprocess.TimeoutExpired:
        logger.error(f"publisher_feeds.py timed out for publisher {publisher_id}")
        return False
    except Exception as e:
        logger.error(
            f"Error running publisher_feeds.py for publisher {publisher_id}: {e}"
        )
        return False


def discover_feeds_parallel(
    publishers: list[int],
    max_workers: int = 8,
    date_offset: int = 1,
    time_window: int = 60,
) -> tuple[dict[int, Optional[Path]], str]:
    """
    Discover feeds for multiple publishers in parallel.

    This function runs publisher_feeds.py concurrently for each publisher,
    which is much faster than sequential discovery since each call involves
    a ClickHouse query with network latency.

    Args:
        publishers: List of publisher IDs to discover feeds for
        max_workers: Maximum number of parallel workers
        date_offset: Days to subtract for benchmark data availability
        time_window: Time window in minutes to look back for activity

    Returns:
        Tuple of (results dict, temp_dir path)
        - results: Dictionary mapping publisher_id to Path or None (if failed)
        - temp_dir: Path to temporary directory containing CSV files (caller must clean up)
    """
    temp_dir = tempfile.mkdtemp(prefix="benchmark_feeds_")
    results: dict[int, Optional[Path]] = {}

    def discover_single(pid: int) -> tuple[int, Optional[Path]]:
        """Discover feeds for a single publisher."""
        feeds_csv = Path(temp_dir) / f"publisher_{pid}_feeds.csv"
        success = run_publisher_feeds(pid, feeds_csv, date_offset, time_window)
        if success and feeds_csv.exists() and feeds_csv.stat().st_size > 0:
            return (pid, feeds_csv)
        return (pid, None)

    logger.info(
        f"Discovering feeds for {len(publishers)} publishers with {max_workers} workers..."
    )
    discovery_start = time.time()

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(discover_single, pid): pid for pid in publishers}
        completed = 0
        for future in as_completed(futures):
            pid, path = future.result()
            results[pid] = path
            completed += 1
            if completed % 10 == 0 or completed == len(publishers):
                logger.info(f"  Discovery progress: {completed}/{len(publishers)}")

    discovery_time = time.time() - discovery_start
    success_count = sum(1 for p in results.values() if p is not None)
    logger.info(
        f"Feed discovery complete: {success_count}/{len(publishers)} publishers "
        f"in {discovery_time:.1f}s"
    )

    return results, temp_dir


def run_publisher_benchmark(
    csv_path: Path,
    output_path: Path,
    publisher_id: int,
    workers: int = 16,
    include_extended_hours: bool = True,
    include_overnight: bool = False,
    include_asset_classes: Optional[list[str]] = None,
    skip_scipy_tests: bool = False,
) -> bool:
    """
    Run publisher_benchmark.py to evaluate a publisher's feeds.

    Args:
        csv_path: Path to feeds CSV
        output_path: Path to write results CSV
        publisher_id: Publisher ID
        workers: Number of parallel workers
        include_extended_hours: Whether to evaluate extended hours
        include_overnight: Whether to evaluate overnight session (US equities only)
        include_asset_classes: Asset classes to include (None = all benchmarkable)
        skip_scipy_tests: Whether to skip scipy statistical tests for faster execution

    Returns:
        True if successful, False otherwise
    """
    cmd = [
        sys.executable,
        str(PUBLISHER_BENCHMARK_SCRIPT),
        "--csv",
        str(csv_path),
        "--publisher-id",
        str(publisher_id),
        "--output",
        str(output_path),
        "--workers",
        str(workers),
    ]

    if include_extended_hours:
        cmd.append("--extended-hours")

    if include_overnight:
        cmd.append("--overnight")

    if skip_scipy_tests:
        cmd.append("--skip-scipy-tests")

    # Only include benchmarkable asset classes by default
    if include_asset_classes is None:
        include_asset_classes = [
            "fx",
            "metals",
            "us-equities",
            "commodity",
            "us-treasuries",
        ]

    if include_asset_classes:
        cmd.extend(["--include-asset-class"] + include_asset_classes)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=1800,  # 30 minute timeout
            cwd=str(PROJECT_ROOT),
        )

        if result.returncode != 0:
            logger.error(
                f"publisher_benchmark.py failed for publisher {publisher_id}: {result.stderr}"
            )
            return False

        return output_path.exists() and output_path.stat().st_size > 0

    except subprocess.TimeoutExpired:
        logger.error(f"publisher_benchmark.py timed out for publisher {publisher_id}")
        return False
    except Exception as e:
        logger.error(
            f"Error running publisher_benchmark.py for publisher {publisher_id}: {e}"
        )
        return False


def store_results(session, results: list[dict], publisher_id: int) -> int:
    """
    Store benchmark results in Postgres using upsert.

    Args:
        session: SQLAlchemy session
        results: List of result dictionaries
        publisher_id: Publisher ID

    Returns:
        Number of results stored
    """
    if not results:
        return 0

    count = 0
    for result_dict in results:
        stmt = insert(BenchmarkResult).values(**result_dict)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_results_publisher_feed_date",
            set_={
                "passes": stmt.excluded.passes,
                "n_observations": stmt.excluded.n_observations,
                "nrmse": stmt.excluded.nrmse,
                "hit_rate": stmt.excluded.hit_rate,
                "benchmark_price_range": stmt.excluded.benchmark_price_range,
                "rmse": stmt.excluded.rmse,
                "mean_spread": stmt.excluded.mean_spread,
                "rmse_over_spread": stmt.excluded.rmse_over_spread,
                "mean_diff": stmt.excluded.mean_diff,
                "std_diff": stmt.excluded.std_diff,
                "mean_pct_diff": stmt.excluded.mean_pct_diff,
                "std_pct_diff": stmt.excluded.std_pct_diff,
                "mae": stmt.excluded.mae,
                "t_statistic": stmt.excluded.t_statistic,
                "t_pvalue": stmt.excluded.t_pvalue,
                "wilcoxon_statistic": stmt.excluded.wilcoxon_statistic,
                "wilcoxon_pvalue": stmt.excluded.wilcoxon_pvalue,
                "normality_pvalue": stmt.excluded.normality_pvalue,
                "mean_abs_z_score": stmt.excluded.mean_abs_z_score,
                "premarket_n_observations": stmt.excluded.premarket_n_observations,
                "premarket_nrmse": stmt.excluded.premarket_nrmse,
                "premarket_hit_rate": stmt.excluded.premarket_hit_rate,
                "premarket_passes": stmt.excluded.premarket_passes,
                "premarket_error": stmt.excluded.premarket_error,
                "afterhours_n_observations": stmt.excluded.afterhours_n_observations,
                "afterhours_nrmse": stmt.excluded.afterhours_nrmse,
                "afterhours_hit_rate": stmt.excluded.afterhours_hit_rate,
                "afterhours_passes": stmt.excluded.afterhours_passes,
                "afterhours_error": stmt.excluded.afterhours_error,
                "overnight_n_observations": stmt.excluded.overnight_n_observations,
                "overnight_n_reference_observations": stmt.excluded.overnight_n_reference_observations,
                "overnight_nrmse": stmt.excluded.overnight_nrmse,
                "overnight_hit_rate": stmt.excluded.overnight_hit_rate,
                "overnight_passes": stmt.excluded.overnight_passes,
                "overnight_reference_publisher_id": stmt.excluded.overnight_reference_publisher_id,
                "overnight_error": stmt.excluded.overnight_error,
                "error": stmt.excluded.error,
                "execution_time_ms": stmt.excluded.execution_time_ms,
            },
        )
        session.execute(stmt)
        count += 1

    session.commit()
    return count


def update_publisher_registry(session, publisher_id: int) -> None:
    """Update or create publisher in registry."""
    stmt = insert(Publisher).values(
        publisher_id=publisher_id,
        name=f"Publisher {publisher_id}",
        is_active=True,
        last_seen_at=datetime.utcnow(),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["publisher_id"],
        set_={
            "is_active": True,
            "last_seen_at": datetime.utcnow(),
            "updated_at": datetime.utcnow(),
        },
    )
    session.execute(stmt)
    session.commit()


def update_feed_registry(session, results: list[dict]) -> None:
    """Update or create feeds in registry from results."""
    seen_feeds = {}
    for r in results:
        feed_id = r["feed_id"]
        if feed_id not in seen_feeds:
            seen_feeds[feed_id] = {
                "feed_id": feed_id,
                "symbol": r.get("symbol"),
                "asset_class": r.get("asset_class"),
            }

    for feed_data in seen_feeds.values():
        stmt = insert(Feed).values(
            feed_id=feed_data["feed_id"],
            symbol=feed_data["symbol"],
            asset_class=feed_data["asset_class"],
            is_active=True,
            last_seen_at=datetime.utcnow(),
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=["feed_id"],
            set_={
                "symbol": feed_data["symbol"],
                "asset_class": feed_data["asset_class"],
                "is_active": True,
                "last_seen_at": datetime.utcnow(),
                "updated_at": datetime.utcnow(),
            },
        )
        session.execute(stmt)

    session.commit()


def compute_daily_summary(
    session,
    publisher_id: int,
    target_date: date,
    batch_duration_sec: float,
) -> None:
    """
    Compute and store daily summary aggregates for a publisher.

    Args:
        session: SQLAlchemy session
        publisher_id: Publisher ID
        target_date: Date of the benchmark
        batch_duration_sec: How long the batch took
    """
    # Query all results for this publisher/date
    results = (
        session.query(BenchmarkResult)
        .filter(
            BenchmarkResult.publisher_id == publisher_id,
            BenchmarkResult.benchmark_date == target_date,
        )
        .all()
    )

    if not results:
        logger.warning(
            f"No results found for publisher {publisher_id} on {target_date}"
        )
        return

    # Compute counts
    total_feeds = len(results)
    error_results = [r for r in results if r.error is not None]
    valid_results = [r for r in results if r.error is None]
    pass_results = [r for r in valid_results if r.passes]
    fail_results = [r for r in valid_results if not r.passes]

    pass_count = len(pass_results)
    fail_count = len(fail_results)
    error_count = len(error_results)
    pass_rate_pct = (pass_count / total_feeds * 100) if total_feeds > 0 else 0

    # Pass criteria breakdown
    pass_by_nrmse_alone = sum(
        1 for r in pass_results if r.nrmse is not None and float(r.nrmse) < 0.01
    )
    pass_by_nrmse_and_hit_rate = pass_count - pass_by_nrmse_alone

    # NRMSE aggregates
    valid_nrmse = [float(r.nrmse) for r in valid_results if r.nrmse is not None]
    if valid_nrmse:
        sorted_nrmse = sorted(valid_nrmse)
        median_nrmse = statistics.median(sorted_nrmse)
        mean_nrmse = statistics.mean(sorted_nrmse)
        min_nrmse = min(sorted_nrmse)
        max_nrmse = max(sorted_nrmse)
        n = len(sorted_nrmse)
        p90_nrmse = sorted_nrmse[min(int(n * 0.90), n - 1)]
        p95_nrmse = sorted_nrmse[min(int(n * 0.95), n - 1)]
    else:
        median_nrmse = mean_nrmse = min_nrmse = max_nrmse = p90_nrmse = p95_nrmse = None

    # Hit rate aggregates
    valid_hit_rate = [
        float(r.hit_rate) for r in valid_results if r.hit_rate is not None
    ]
    if valid_hit_rate:
        median_hit_rate = statistics.median(valid_hit_rate)
        mean_hit_rate = statistics.mean(valid_hit_rate)
        min_hit_rate = min(valid_hit_rate)
        max_hit_rate = max(valid_hit_rate)
    else:
        median_hit_rate = mean_hit_rate = min_hit_rate = max_hit_rate = None

    # RMSE/Spread aggregates
    valid_ros = [
        float(r.rmse_over_spread)
        for r in valid_results
        if r.rmse_over_spread is not None
    ]
    if valid_ros:
        sorted_ros = sorted(valid_ros)
        median_ros = statistics.median(sorted_ros)
        mean_ros = statistics.mean(sorted_ros)
        n = len(sorted_ros)
        p90_ros = sorted_ros[min(int(n * 0.90), n - 1)]
        p95_ros = sorted_ros[min(int(n * 0.95), n - 1)]
    else:
        median_ros = mean_ros = p90_ros = p95_ros = None

    # Coverage metrics
    observations = [r.n_observations for r in valid_results if r.n_observations > 0]
    total_observations = sum(observations) if observations else 0
    mean_observations = statistics.mean(observations) if observations else None
    median_observations = int(statistics.median(observations)) if observations else None

    # MAE aggregates
    valid_mae = [float(r.mae) for r in valid_results if r.mae is not None]
    if valid_mae:
        median_mae = statistics.median(valid_mae)
        mean_mae = statistics.mean(valid_mae)
    else:
        median_mae = mean_mae = None

    # Statistical test summary
    t_significant = sum(
        1 for r in valid_results if r.t_pvalue is not None and float(r.t_pvalue) < 0.05
    )
    t_total = sum(1 for r in valid_results if r.t_pvalue is not None)
    t_test_significance_rate = (t_significant / t_total * 100) if t_total > 0 else None

    normal_count = sum(
        1
        for r in valid_results
        if r.normality_pvalue is not None and float(r.normality_pvalue) >= 0.05
    )
    normal_total = sum(1 for r in valid_results if r.normality_pvalue is not None)
    normality_rate = (normal_count / normal_total * 100) if normal_total > 0 else None

    valid_z = [
        float(r.mean_abs_z_score)
        for r in valid_results
        if r.mean_abs_z_score is not None
    ]
    median_z_score = statistics.median(valid_z) if valid_z else None

    # Asset class breakdown
    asset_class_breakdown = {}
    for r in results:
        ac = r.asset_class
        if ac not in asset_class_breakdown:
            asset_class_breakdown[ac] = {"pass": 0, "fail": 0, "error": 0}
        if r.error:
            asset_class_breakdown[ac]["error"] += 1
        elif r.passes:
            asset_class_breakdown[ac]["pass"] += 1
        else:
            asset_class_breakdown[ac]["fail"] += 1

    # Extended hours summary (US equities only)
    us_equity_results = [
        r for r in valid_results if r.asset_class in ("us-equities", "equity-us")
    ]
    extended_hours_summary = None
    if us_equity_results:
        pm_results = [
            r for r in us_equity_results if r.premarket_n_observations is not None
        ]
        ah_results = [
            r for r in us_equity_results if r.afterhours_n_observations is not None
        ]

        if pm_results or ah_results:
            extended_hours_summary = {}

            if pm_results:
                pm_pass = sum(
                    1
                    for r in pm_results
                    if r.premarket_passes and not r.premarket_error
                )
                pm_fail = sum(
                    1
                    for r in pm_results
                    if not r.premarket_passes and not r.premarket_error
                )
                pm_error = sum(1 for r in pm_results if r.premarket_error)
                pm_nrmse = [
                    float(r.premarket_nrmse)
                    for r in pm_results
                    if r.premarket_nrmse is not None and not r.premarket_error
                ]
                pm_hr = [
                    float(r.premarket_hit_rate)
                    for r in pm_results
                    if r.premarket_hit_rate is not None and not r.premarket_error
                ]

                extended_hours_summary["premarket_total_feeds"] = len(pm_results)
                extended_hours_summary["premarket_pass_count"] = pm_pass
                extended_hours_summary["premarket_fail_count"] = pm_fail
                extended_hours_summary["premarket_error_count"] = pm_error
                extended_hours_summary["premarket_pass_rate_pct"] = (
                    (pm_pass / len(pm_results) * 100) if pm_results else 0
                )
                extended_hours_summary["premarket_median_nrmse"] = (
                    statistics.median(pm_nrmse) if pm_nrmse else None
                )
                extended_hours_summary["premarket_median_hit_rate"] = (
                    statistics.median(pm_hr) if pm_hr else None
                )

            if ah_results:
                ah_pass = sum(
                    1
                    for r in ah_results
                    if r.afterhours_passes and not r.afterhours_error
                )
                ah_fail = sum(
                    1
                    for r in ah_results
                    if not r.afterhours_passes and not r.afterhours_error
                )
                ah_error = sum(1 for r in ah_results if r.afterhours_error)
                ah_nrmse = [
                    float(r.afterhours_nrmse)
                    for r in ah_results
                    if r.afterhours_nrmse is not None and not r.afterhours_error
                ]
                ah_hr = [
                    float(r.afterhours_hit_rate)
                    for r in ah_results
                    if r.afterhours_hit_rate is not None and not r.afterhours_error
                ]

                extended_hours_summary["afterhours_total_feeds"] = len(ah_results)
                extended_hours_summary["afterhours_pass_count"] = ah_pass
                extended_hours_summary["afterhours_fail_count"] = ah_fail
                extended_hours_summary["afterhours_error_count"] = ah_error
                extended_hours_summary["afterhours_pass_rate_pct"] = (
                    (ah_pass / len(ah_results) * 100) if ah_results else 0
                )
                extended_hours_summary["afterhours_median_nrmse"] = (
                    statistics.median(ah_nrmse) if ah_nrmse else None
                )
                extended_hours_summary["afterhours_median_hit_rate"] = (
                    statistics.median(ah_hr) if ah_hr else None
                )

    # Insert/update summary
    stmt = insert(PublisherDailySummary).values(
        publisher_id=publisher_id,
        summary_date=target_date,
        total_feeds=total_feeds,
        pass_count=pass_count,
        fail_count=fail_count,
        error_count=error_count,
        pass_rate_pct=pass_rate_pct,
        pass_by_nrmse_alone=pass_by_nrmse_alone,
        pass_by_nrmse_and_hit_rate=pass_by_nrmse_and_hit_rate,
        median_nrmse=median_nrmse,
        mean_nrmse=mean_nrmse,
        p90_nrmse=p90_nrmse,
        p95_nrmse=p95_nrmse,
        min_nrmse=min_nrmse,
        max_nrmse=max_nrmse,
        median_hit_rate=median_hit_rate,
        mean_hit_rate=mean_hit_rate,
        min_hit_rate=min_hit_rate,
        max_hit_rate=max_hit_rate,
        median_rmse_over_spread=median_ros,
        mean_rmse_over_spread=mean_ros,
        p90_rmse_over_spread=p90_ros,
        p95_rmse_over_spread=p95_ros,
        total_observations=total_observations,
        mean_observations_per_feed=mean_observations,
        median_observations_per_feed=median_observations,
        median_mae=median_mae,
        mean_mae=mean_mae,
        t_test_significance_rate=t_test_significance_rate,
        normality_rate=normality_rate,
        median_z_score=median_z_score,
        asset_class_breakdown=asset_class_breakdown,
        extended_hours_summary=extended_hours_summary,
        batch_duration_sec=batch_duration_sec,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_summary_publisher_date",
        set_={
            "total_feeds": total_feeds,
            "pass_count": pass_count,
            "fail_count": fail_count,
            "error_count": error_count,
            "pass_rate_pct": pass_rate_pct,
            "pass_by_nrmse_alone": pass_by_nrmse_alone,
            "pass_by_nrmse_and_hit_rate": pass_by_nrmse_and_hit_rate,
            "median_nrmse": median_nrmse,
            "mean_nrmse": mean_nrmse,
            "p90_nrmse": p90_nrmse,
            "p95_nrmse": p95_nrmse,
            "min_nrmse": min_nrmse,
            "max_nrmse": max_nrmse,
            "median_hit_rate": median_hit_rate,
            "mean_hit_rate": mean_hit_rate,
            "min_hit_rate": min_hit_rate,
            "max_hit_rate": max_hit_rate,
            "median_rmse_over_spread": median_ros,
            "mean_rmse_over_spread": mean_ros,
            "p90_rmse_over_spread": p90_ros,
            "p95_rmse_over_spread": p95_ros,
            "total_observations": total_observations,
            "mean_observations_per_feed": mean_observations,
            "median_observations_per_feed": median_observations,
            "median_mae": median_mae,
            "mean_mae": mean_mae,
            "t_test_significance_rate": t_test_significance_rate,
            "normality_rate": normality_rate,
            "median_z_score": median_z_score,
            "asset_class_breakdown": asset_class_breakdown,
            "extended_hours_summary": extended_hours_summary,
            "batch_duration_sec": batch_duration_sec,
        },
    )
    session.execute(stmt)
    session.commit()

    nrmse_str = f"{median_nrmse:.6f}" if median_nrmse else "N/A"
    logger.info(
        f"  Summary: {pass_count}/{total_feeds} pass ({pass_rate_pct:.1f}%), "
        f"median_nrmse={nrmse_str}"
    )


def process_publisher(
    publisher_id: int,
    target_date: date,
    session,
    workers: int = 16,
    include_extended_hours: bool = True,
    include_overnight: bool = False,
    dry_run: bool = False,
    skip_scipy_tests: bool = False,
    feeds_csv: Optional[Path] = None,
) -> tuple[int, int, int]:
    """
    Process a single publisher: generate feeds, run benchmark, store results.

    Args:
        publisher_id: Publisher ID to process
        target_date: Date for benchmark
        session: SQLAlchemy session
        workers: Number of parallel workers
        include_extended_hours: Whether to evaluate extended hours
        include_overnight: Whether to evaluate overnight session (US equities only)
        dry_run: If True, don't store results
        skip_scipy_tests: Whether to skip scipy statistical tests for faster execution
        feeds_csv: Pre-discovered feeds CSV path (skip discovery if provided)

    Returns:
        Tuple of (pass_count, fail_count, error_count)
    """
    start_time = time.time()
    logger.info(f"Processing publisher {publisher_id} for {target_date}...")

    with tempfile.TemporaryDirectory() as tmpdir:
        # Use pre-discovered feeds if provided, otherwise discover now
        if feeds_csv is None:
            feeds_csv = Path(tmpdir) / f"publisher_{publisher_id}_feeds.csv"
            # Step 1: Generate feeds CSV
            logger.info(f"  Generating feeds list...")
            if not run_publisher_feeds(
                publisher_id, feeds_csv, date_offset=1, time_window=60
            ):
                logger.error(f"  Failed to generate feeds for publisher {publisher_id}")
                return (0, 0, 1)
        else:
            logger.info(f"  Using pre-discovered feeds: {feeds_csv}")

        results_csv = Path(tmpdir) / f"publisher_{publisher_id}_results.csv"

        # Check if feeds file has content
        if not feeds_csv.exists() or feeds_csv.stat().st_size == 0:
            logger.warning(f"  No feeds found for publisher {publisher_id}")
            return (0, 0, 0)

        # Step 2: Run benchmark
        logger.info(f"  Running benchmark...")
        if not run_publisher_benchmark(
            feeds_csv,
            results_csv,
            publisher_id,
            workers=workers,
            include_extended_hours=include_extended_hours,
            include_overnight=include_overnight,
            skip_scipy_tests=skip_scipy_tests,
        ):
            logger.error(f"  Benchmark failed for publisher {publisher_id}")
            return (0, 0, 1)

        # Step 3: Parse results
        logger.info(f"  Parsing results...")
        results = []
        for parsed_result in parse_benchmark_csv(results_csv):
            results.append(result_to_dict(parsed_result))

        if not results:
            logger.warning(f"  No benchmark results for publisher {publisher_id}")
            return (0, 0, 0)

        # Count pass/fail/error
        pass_count = sum(1 for r in results if r["passes"] and not r["error"])
        fail_count = sum(1 for r in results if not r["passes"] and not r["error"])
        error_count = sum(1 for r in results if r["error"])

        if dry_run:
            logger.info(f"  [DRY RUN] Would store {len(results)} results")
            return (pass_count, fail_count, error_count)

        # Step 4: Store results
        logger.info(f"  Storing {len(results)} results...")
        update_publisher_registry(session, publisher_id)
        update_feed_registry(session, results)
        store_results(session, results, publisher_id)

        # Step 5: Compute uptime (session-aware)
        logger.info("  Computing uptime...")
        try:
            uptime_count = compute_and_store_uptime_for_publisher(
                publisher_id=publisher_id,
                target_date=target_date,
                feeds_csv=feeds_csv,
                session=session,
            )
            logger.info(f"  Stored {uptime_count} uptime records")

            # Step 5b: Compute uptime summary
            logger.info("  Computing uptime summary...")
            compute_daily_uptime_summary(session, publisher_id, target_date)

        except Exception as e:
            logger.error(
                f"  Uptime calculation failed for publisher {publisher_id}: {e}"
            )

        # Step 6: Compute summary
        batch_duration = time.time() - start_time
        compute_daily_summary(session, publisher_id, target_date, batch_duration)

        # Step 7: Link uptime to benchmark summary
        try:
            link_uptime_to_benchmark_summary(session, publisher_id, target_date)
        except Exception as e:
            logger.error(f"  Failed to link uptime to benchmark summary: {e}")

        logger.info(
            f"  Completed in {batch_duration:.1f}s: "
            f"{pass_count} pass, {fail_count} fail, {error_count} error"
        )

        return (pass_count, fail_count, error_count)


def main():
    parser = argparse.ArgumentParser(
        description="Daily batch job to run benchmarks for all active publishers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--date",
        type=str,
        help="Target date for benchmark (YYYY-MM-DD). Default: yesterday",
    )
    parser.add_argument(
        "--publisher-id",
        type=int,
        help="Run for a specific publisher only",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=settings.batch_workers,
        help=f"Number of parallel workers (default: {settings.batch_workers})",
    )
    parser.add_argument(
        "--no-extended-hours",
        action="store_true",
        help="Skip extended hours evaluation for US equities",
    )
    parser.add_argument(
        "--overnight",
        action="store_true",
        help="Include overnight session evaluation for US equities (8 PM - 4 AM EST). "
        "Uses publisher 32 as reference.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run without storing results in database",
    )
    parser.add_argument(
        "--time-window",
        type=int,
        default=60,
        help="Time window in minutes to discover active publishers (default: 60)",
    )
    parser.add_argument(
        "--skip-scipy-tests",
        action="store_true",
        help="Skip scipy statistical tests (t-test, Wilcoxon, normality) for faster execution. "
        "Pass/fail is determined by nrmse and hit_rate only. Reduces processing time by ~40%%.",
    )
    parser.add_argument(
        "--discovery-workers",
        type=int,
        default=8,
        help="Number of parallel workers for feed discovery (default: 8). "
        "Higher values speed up the discovery phase but increase ClickHouse load.",
    )

    args = parser.parse_args()

    # Determine target date
    if args.date:
        target_date = date.fromisoformat(args.date)
    else:
        target_date = date.today() - timedelta(days=1)

    logger.info(f"Starting daily benchmark batch for {target_date}")
    logger.info(
        f"Workers: {args.workers}, Discovery workers: {args.discovery_workers}, Extended hours: {not args.no_extended_hours}, Overnight: {args.overnight}, Skip scipy: {args.skip_scipy_tests}"
    )

    if args.dry_run:
        logger.info("DRY RUN MODE - no results will be stored")

    total_start = time.time()

    # Get publishers to process
    if args.publisher_id:
        publishers = [args.publisher_id]
        logger.info(f"Processing single publisher: {args.publisher_id}")
    else:
        logger.info(
            f"Discovering active publishers (last {args.time_window} minutes)..."
        )
        try:
            client = get_clickhouse_client()
            publishers = get_active_publishers(client, args.time_window)
            logger.info(f"Found {len(publishers)} active publishers")
        except Exception as e:
            logger.error(f"Failed to connect to ClickHouse: {e}")
            sys.exit(1)

    if not publishers:
        logger.warning("No publishers to process")
        sys.exit(0)

    # Phase 1: Parallel feed discovery (when processing multiple publishers)
    pre_discovered_feeds: dict[int, Optional[Path]] = {}
    discovery_temp_dir: Optional[str] = None

    if len(publishers) > 1 and args.discovery_workers > 0:
        logger.info(
            f"Starting parallel feed discovery with {args.discovery_workers} workers..."
        )
        pre_discovered_feeds, discovery_temp_dir = discover_feeds_parallel(
            publishers,
            max_workers=args.discovery_workers,
            date_offset=1,
            time_window=args.time_window,
        )

    # Phase 2: Process each publisher (benchmark evaluation)
    session = get_session()
    total_pass = 0
    total_fail = 0
    total_error = 0
    processed = 0
    failed_publishers = []

    try:
        for publisher_id in publishers:
            try:
                # Use pre-discovered feeds if available
                feeds_csv = pre_discovered_feeds.get(publisher_id)

                pass_count, fail_count, error_count = process_publisher(
                    publisher_id,
                    target_date,
                    session,
                    workers=args.workers,
                    include_extended_hours=not args.no_extended_hours,
                    include_overnight=args.overnight,
                    dry_run=args.dry_run,
                    skip_scipy_tests=args.skip_scipy_tests,
                    feeds_csv=feeds_csv,
                )
                total_pass += pass_count
                total_fail += fail_count
                total_error += error_count
                processed += 1
            except Exception as e:
                logger.error(f"Failed to process publisher {publisher_id}: {e}")
                failed_publishers.append(publisher_id)

    finally:
        session.close()
        # Clean up parallel discovery temp directory
        if discovery_temp_dir:
            try:
                shutil.rmtree(discovery_temp_dir, ignore_errors=True)
                logger.debug(
                    f"Cleaned up discovery temp directory: {discovery_temp_dir}"
                )
            except Exception as e:
                logger.warning(
                    f"Failed to clean up temp directory {discovery_temp_dir}: {e}"
                )

    # Summary
    total_time = time.time() - total_start
    logger.info("=" * 60)
    logger.info("BATCH COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Date: {target_date}")
    logger.info(f"Publishers processed: {processed}/{len(publishers)}")
    logger.info(f"Total feeds: {total_pass + total_fail + total_error}")
    logger.info(f"  Pass: {total_pass}")
    logger.info(f"  Fail: {total_fail}")
    logger.info(f"  Error: {total_error}")
    logger.info(f"Total time: {total_time:.1f}s")

    if failed_publishers:
        logger.warning(f"Failed publishers: {failed_publishers}")
        sys.exit(1)

    sys.exit(0)


if __name__ == "__main__":
    main()
