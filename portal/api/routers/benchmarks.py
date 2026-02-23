"""
Benchmark job endpoints for the Publisher Performance Portal.

Provides on-demand benchmark job creation and status tracking.
"""

import subprocess
import sys
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, HTTPException, Query, Request
import statistics
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from portal.api.dependencies import DbSession, Pagination
from portal.api.schemas import (
    PaginatedResponse,
    TrendData,
    TrendPoint,
    UptimeSummaryItem,
    UptimeTrendPoint,
)
from portal.batch.result_parser import parse_benchmark_csv, result_to_dict
from portal.config import settings
from portal.db import get_session
from portal.models import (
    BenchmarkJob,
    BenchmarkJobCreate,
    BenchmarkJobListItem,
    BenchmarkJobResponse,
    BenchmarkJobStatus,
    BenchmarkResult,
    JobStatus,
    JobType,
    Publisher,
    PublisherDailySummary,
    PublisherDailyUptimeSummary,
    PublisherFeedDailyUptime,
    PublisherFeedUptimeResponse,
)

router = APIRouter(prefix="/benchmarks", tags=["benchmarks"])

# Path to benchmark scripts
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
PUBLISHER_FEEDS_SCRIPT = PROJECT_ROOT / "publisher_feeds.py"
PUBLISHER_BENCHMARK_SCRIPT = PROJECT_ROOT / "publisher_benchmark.py"


def run_benchmark_job(job_id: UUID) -> None:
    """
    Background task to run a benchmark job.

    This runs the benchmark and stores results in the database.
    """
    session = get_session()

    try:
        # Get job
        job = session.get(BenchmarkJob, job_id)
        if not job:
            return

        # Update status to running
        job.status = JobStatus.RUNNING.value
        job.started_at = datetime.utcnow()
        session.commit()

        with tempfile.TemporaryDirectory() as tmpdir:
            feeds_csv = Path(tmpdir) / f"publisher_{job.publisher_id}_feeds.csv"
            results_csv = Path(tmpdir) / f"publisher_{job.publisher_id}_results.csv"

            # Generate feeds CSV
            feeds_cmd = [
                sys.executable,
                str(PUBLISHER_FEEDS_SCRIPT),
                "--publisher-id",
                str(job.publisher_id),
                "--output",
                str(feeds_csv),
                "--date-offset",
                "1",
                "--time-window",
                "5",
            ]

            result = subprocess.run(
                feeds_cmd,
                capture_output=True,
                text=True,
                timeout=300,
                cwd=str(PROJECT_ROOT),
            )

            if result.returncode != 0:
                job.status = JobStatus.FAILED.value
                job.error = f"Failed to generate feeds: {result.stderr[:500]}"
                job.completed_at = datetime.utcnow()
                session.commit()
                return

            if not feeds_csv.exists() or feeds_csv.stat().st_size == 0:
                job.status = JobStatus.FAILED.value
                job.error = "No feeds found for publisher"
                job.completed_at = datetime.utcnow()
                session.commit()
                return

            # Run benchmark
            benchmark_cmd = [
                sys.executable,
                str(PUBLISHER_BENCHMARK_SCRIPT),
                "--csv",
                str(feeds_csv),
                "--publisher-id",
                str(job.publisher_id),
                "--output",
                str(results_csv),
                "--workers",
                str(settings.batch_workers),
                "--include-asset-class",
                "fx",
                "metals",
                "us-equities",
                "commodity",
                "us-treasuries",
            ]

            if job.include_extended_hours:
                benchmark_cmd.append("--extended-hours")

            result = subprocess.run(
                benchmark_cmd,
                capture_output=True,
                text=True,
                timeout=1800,
                cwd=str(PROJECT_ROOT),
            )

            if result.returncode != 0:
                job.status = JobStatus.FAILED.value
                job.error = f"Benchmark failed: {result.stderr[:500]}"
                job.completed_at = datetime.utcnow()
                session.commit()
                return

            # Parse and store results
            results = []
            for parsed_result in parse_benchmark_csv(results_csv):
                result_dict = result_to_dict(parsed_result)
                results.append(result_dict)

                # Upsert result
                from sqlalchemy.dialects.postgresql import insert

                stmt = insert(BenchmarkResult).values(**result_dict)
                stmt = stmt.on_conflict_do_update(
                    constraint="uq_results_publisher_feed_date",
                    set_={
                        k: v
                        for k, v in result_dict.items()
                        if k not in ("publisher_id", "feed_id", "benchmark_date")
                    },
                )
                session.execute(stmt)

            session.commit()

            # Update job status
            pass_count = sum(1 for r in results if r["passes"] and not r["error"])
            fail_count = sum(1 for r in results if not r["passes"] and not r["error"])
            error_count = sum(1 for r in results if r["error"])

            job.status = JobStatus.COMPLETED.value
            job.completed_at = datetime.utcnow()
            job.results_count = len(results)
            job.pass_count = pass_count
            job.fail_count = fail_count
            job.error_count = error_count
            session.commit()

    except subprocess.TimeoutExpired:
        job = session.get(BenchmarkJob, job_id)
        if job:
            job.status = JobStatus.FAILED.value
            job.error = "Benchmark timed out"
            job.completed_at = datetime.utcnow()
            session.commit()

    except Exception as e:
        job = session.get(BenchmarkJob, job_id)
        if job:
            job.status = JobStatus.FAILED.value
            job.error = str(e)[:500]
            job.completed_at = datetime.utcnow()
            session.commit()

    finally:
        session.close()


@router.post("/jobs", response_model=BenchmarkJobResponse)
async def create_benchmark_job(
    job_request: BenchmarkJobCreate,
    background_tasks: BackgroundTasks,
    request: Request,
    db: DbSession,
):
    """
    Create an on-demand benchmark job for a publisher.

    The job runs asynchronously. Use GET /benchmarks/jobs/{id} to check status.
    """
    # Validate publisher exists
    publisher = db.get(Publisher, job_request.publisher_id)
    if not publisher:
        raise HTTPException(
            status_code=404,
            detail=f"Publisher {job_request.publisher_id} not found",
        )

    # Check for existing pending/running job
    existing_job = db.execute(
        select(BenchmarkJob)
        .where(BenchmarkJob.publisher_id == job_request.publisher_id)
        .where(
            BenchmarkJob.status.in_([JobStatus.PENDING.value, JobStatus.RUNNING.value])
        )
    ).scalar()

    if existing_job:
        raise HTTPException(
            status_code=409,
            detail=f"Job already in progress for publisher {job_request.publisher_id}",
        )

    # Create job
    target_date = job_request.target_date or (date.today() - timedelta(days=1))

    job = BenchmarkJob(
        publisher_id=job_request.publisher_id,
        feed_ids=job_request.feed_ids,
        target_date=target_date,
        include_extended_hours=job_request.include_extended_hours,
        status=JobStatus.PENDING.value,
        job_type=JobType.ON_DEMAND.value,
        requested_by=request.client.host if request.client else None,
    )

    db.add(job)
    db.commit()
    db.refresh(job)

    # Queue background task
    background_tasks.add_task(run_benchmark_job, job.id)

    return BenchmarkJobResponse.model_validate(job)


@router.get("/jobs", response_model=PaginatedResponse[BenchmarkJobListItem])
async def list_benchmark_jobs(
    db: DbSession,
    pagination: Pagination,
    publisher_id: Optional[int] = Query(None, description="Filter by publisher"),
    status: Optional[JobStatus] = Query(None, description="Filter by status"),
):
    """
    List benchmark jobs with optional filtering.
    """
    query = select(BenchmarkJob)

    if publisher_id:
        query = query.where(BenchmarkJob.publisher_id == publisher_id)

    if status:
        query = query.where(BenchmarkJob.status == status.value)

    # Get total count
    from sqlalchemy import func

    count_query = select(func.count()).select_from(query.subquery())
    total = db.execute(count_query).scalar() or 0

    # Get paginated results
    query = (
        query.order_by(desc(BenchmarkJob.requested_at))
        .offset(pagination.skip)
        .limit(pagination.limit)
    )

    jobs = db.execute(query).scalars().all()

    items = [BenchmarkJobListItem.model_validate(j) for j in jobs]

    return PaginatedResponse(
        items=items,
        total=total,
        skip=pagination.skip,
        limit=pagination.limit,
        has_more=(pagination.skip + len(items)) < total,
    )


@router.get("/jobs/{job_id}", response_model=BenchmarkJobResponse)
async def get_benchmark_job(job_id: UUID, db: DbSession):
    """
    Get status and details of a benchmark job.
    """
    job = db.get(BenchmarkJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    return BenchmarkJobResponse.model_validate(job)


@router.get("/jobs/{job_id}/status", response_model=BenchmarkJobStatus)
async def get_benchmark_job_status(job_id: UUID, db: DbSession):
    """
    Get lightweight status of a benchmark job (for polling).
    """
    job = db.get(BenchmarkJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    # Calculate progress estimate based on typical job duration
    progress = None
    if job.status == JobStatus.RUNNING.value and job.started_at:
        elapsed = (datetime.utcnow() - job.started_at).total_seconds()
        # Estimate based on typical job duration of 5 minutes
        progress = min(int(elapsed / 300 * 100), 99)
    elif job.status == JobStatus.COMPLETED.value:
        progress = 100
    elif job.status == JobStatus.PENDING.value:
        progress = 0

    return BenchmarkJobStatus(
        id=job.id,
        status=JobStatus(job.status),
        progress=progress,
        requested_at=job.requested_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        duration_seconds=job.duration_seconds,
        results_count=job.results_count,
        pass_count=job.pass_count,
        fail_count=job.fail_count,
        error_count=job.error_count,
        error=job.error,
    )


@router.delete("/jobs/{job_id}")
async def cancel_benchmark_job(job_id: UUID, db: DbSession):
    """
    Cancel a pending benchmark job.

    Running jobs cannot be cancelled (they will complete or timeout).
    """
    job = db.get(BenchmarkJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    if job.status != JobStatus.PENDING.value:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot cancel job in status: {job.status}",
        )

    job.status = JobStatus.FAILED.value
    job.error = "Cancelled by user"
    job.completed_at = datetime.utcnow()
    db.commit()

    return {"message": f"Job {job_id} cancelled"}


@router.get("/uptime", response_model=list[PublisherFeedUptimeResponse])
async def get_publisher_uptime(
    db: DbSession,
    publisher_id: int = Query(..., description="Publisher ID"),
    target_date: date = Query(..., description="Uptime date (YYYY-MM-DD)"),
    session_name: Optional[str] = Query(
        None, alias="session", description="Session name"
    ),
    asset_class: Optional[str] = Query(None, description="Asset class filter"),
    feed_id: Optional[int] = Query(None, description="Feed ID filter"),
):
    """
    Get session-aware uptime for a publisher on a specific date.
    """
    query = (
        db.query(PublisherFeedDailyUptime)
        .filter(PublisherFeedDailyUptime.publisher_id == publisher_id)
        .filter(PublisherFeedDailyUptime.uptime_date == target_date)
    )

    if session_name:
        query = query.filter(PublisherFeedDailyUptime.session == session_name)
    if asset_class:
        query = query.filter(PublisherFeedDailyUptime.asset_class == asset_class)
    if feed_id:
        query = query.filter(PublisherFeedDailyUptime.feed_id == feed_id)

    return query.order_by(
        PublisherFeedDailyUptime.asset_class.asc(),
        PublisherFeedDailyUptime.feed_id.asc(),
        PublisherFeedDailyUptime.session.asc(),
    ).all()


@router.get("/uptime/summary", response_model=list[UptimeSummaryItem])
async def get_publisher_uptime_summary(
    db: DbSession,
    publisher_id: int = Query(..., description="Publisher ID"),
    target_date: date = Query(..., description="Uptime date (YYYY-MM-DD)"),
):
    """
    Get aggregated uptime summary by asset class and session.
    """
    rows = (
        db.query(PublisherFeedDailyUptime)
        .filter(PublisherFeedDailyUptime.publisher_id == publisher_id)
        .filter(PublisherFeedDailyUptime.uptime_date == target_date)
        .all()
    )

    buckets: dict[tuple[str, str], list[float]] = {}
    for row in rows:
        key = (row.asset_class or "", row.session)
        buckets.setdefault(key, []).append(float(row.uptime_pct))

    summaries: list[UptimeSummaryItem] = []
    for (asset_class, session), values in sorted(buckets.items()):
        if not values:
            continue
        summaries.append(
            UptimeSummaryItem(
                asset_class=asset_class or None,
                session=session,
                total_feeds=len(values),
                mean_uptime_pct=statistics.mean(values) if values else None,
                median_uptime_pct=statistics.median(values) if values else None,
                min_uptime_pct=min(values) if values else None,
                max_uptime_pct=max(values) if values else None,
            )
        )

    return summaries


@router.get("/jobs/{job_id}/results")
async def get_benchmark_job_results(
    job_id: UUID,
    db: DbSession,
    pagination: Pagination,
):
    """
    Get results from a completed benchmark job.
    """
    job = db.get(BenchmarkJob, job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} not found")

    if job.status != JobStatus.COMPLETED.value:
        raise HTTPException(
            status_code=400,
            detail=f"Job is not completed (status: {job.status})",
        )

    # Query results for this job's parameters
    query = (
        select(BenchmarkResult)
        .where(BenchmarkResult.publisher_id == job.publisher_id)
        .where(BenchmarkResult.benchmark_date == job.target_date)
    )

    if job.feed_ids:
        query = query.where(BenchmarkResult.feed_id.in_(job.feed_ids))

    # Get total count
    from sqlalchemy import func

    count_query = select(func.count()).select_from(query.subquery())
    total = db.execute(count_query).scalar() or 0

    # Get paginated results
    query = (
        query.order_by(BenchmarkResult.passes, BenchmarkResult.feed_id)
        .offset(pagination.skip)
        .limit(pagination.limit)
    )

    results = db.execute(query).scalars().all()

    items = [
        {
            "feed_id": r.feed_id,
            "symbol": r.symbol,
            "asset_class": r.asset_class,
            "passes": r.passes,
            "n_observations": r.n_observations,
            "nrmse": float(r.nrmse) if r.nrmse else None,
            "hit_rate": float(r.hit_rate) if r.hit_rate else None,
            "error": r.error,
        }
        for r in results
    ]

    return {
        "job_id": str(job_id),
        "publisher_id": job.publisher_id,
        "date": str(job.target_date),
        "total": total,
        "skip": pagination.skip,
        "limit": pagination.limit,
        "has_more": (pagination.skip + len(items)) < total,
        "summary": {
            "pass_count": job.pass_count,
            "fail_count": job.fail_count,
            "error_count": job.error_count,
        },
        "results": items,
    }


@router.get("/trend/benchmark", response_model=list[TrendPoint])
async def get_benchmark_trend(
    db: DbSession,
    publisher_id: int = Query(..., description="Publisher ID"),
    days: int = Query(30, ge=1, le=90, description="Number of days to include (1-90)"),
    metric: str = Query("pass_rate_pct", description="Metric to trend"),
):
    """
    Get historical benchmark metrics for trend analysis.

    Supported metrics: pass_rate_pct, median_nrmse, median_hit_rate,
    total_feeds, pass_count, fail_count
    """
    # Validate metric
    valid_metrics = {
        "pass_rate_pct",
        "median_nrmse",
        "median_hit_rate",
        "total_feeds",
        "pass_count",
        "fail_count",
        "error_count",
        "median_rmse_over_spread",
        "total_observations",
    }
    if metric not in valid_metrics:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid metric. Valid options: {', '.join(sorted(valid_metrics))}",
        )

    # Get summaries for the date range
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    query = (
        select(PublisherDailySummary)
        .where(PublisherDailySummary.publisher_id == publisher_id)
        .where(PublisherDailySummary.summary_date >= start_date)
        .where(PublisherDailySummary.summary_date <= end_date)
        .order_by(PublisherDailySummary.summary_date)
    )

    summaries = db.execute(query).scalars().all()

    trend_points = []
    for summary in summaries:
        value = getattr(summary, metric, None)
        trend_points.append(
            TrendPoint(
                date=summary.summary_date,
                value=float(value) if value is not None else None,
            )
        )

    return trend_points


@router.get("/trend/uptime", response_model=list[UptimeTrendPoint])
async def get_uptime_trend(
    db: DbSession,
    publisher_id: int = Query(..., description="Publisher ID"),
    days: int = Query(30, ge=1, le=90, description="Number of days to include (1-90)"),
    session_name: str = Query(
        "regular", alias="session", description="Session to trend"
    ),
):
    """
    Get historical uptime metrics for trend analysis.

    Sessions: regular, premarket, afterhours, overnight
    """
    # Validate session
    valid_sessions = {"regular", "premarket", "afterhours", "overnight", "overall"}
    if session_name not in valid_sessions:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid session. Valid options: {', '.join(sorted(valid_sessions))}",
        )

    # Get uptime summaries for the date range
    end_date = date.today()
    start_date = end_date - timedelta(days=days)

    query = (
        select(PublisherDailyUptimeSummary)
        .where(PublisherDailyUptimeSummary.publisher_id == publisher_id)
        .where(PublisherDailyUptimeSummary.summary_date >= start_date)
        .where(PublisherDailyUptimeSummary.summary_date <= end_date)
        .order_by(PublisherDailyUptimeSummary.summary_date)
    )

    summaries = db.execute(query).scalars().all()

    # Map session to column name
    session_col_map = {
        "regular": "regular_median_uptime_pct",
        "premarket": "premarket_median_uptime_pct",
        "afterhours": "afterhours_median_uptime_pct",
        "overnight": "overnight_median_uptime_pct",
        "overall": "overall_median_uptime_pct",
    }

    col_name = session_col_map.get(session_name, "regular_median_uptime_pct")

    trend_points = []
    for summary in summaries:
        value = getattr(summary, col_name, None)
        trend_points.append(
            UptimeTrendPoint(
                date=summary.summary_date,
                session=session_name,
                value=float(value) if value is not None else None,
            )
        )

    return trend_points
