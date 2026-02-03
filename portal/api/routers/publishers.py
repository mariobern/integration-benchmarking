"""
Publisher endpoints for the Publisher Performance Portal.

Provides endpoints to list publishers, get details, summaries, and feed results.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc, func, Integer, select
from sqlalchemy.orm import Session

from portal.api.dependencies import AssetFilter, DateRange, DbSession, Pagination
from portal.api.schemas import (
    AlertItem,
    AssetClassBreakdown,
    BenchmarkMetrics,
    DashboardAlerts,
    MetricsSummary,
    PaginatedResponse,
    PublisherDashboardResponse,
    TrendData,
    TrendPoint,
    UptimeMetrics,
)
from portal.models import (
    BenchmarkResult,
    BenchmarkResultListItem,
    BenchmarkResultResponse,
    Publisher,
    PublisherDailySummary,
    PublisherDailyUptimeSummary,
    PublisherFeedDailyUptime,
    PublisherListItem,
    PublisherResponse,
    PublisherSummaryDetail,
    PublisherSummaryResponse,
    PublisherWithStats,
)

# Threshold constants for alerts
NRMSE_CRITICAL_THRESHOLD = 0.05  # NRMSE above this is critical
UPTIME_LOW_THRESHOLD = 99.0  # Uptime below this is considered "low"
UPTIME_CRITICAL_THRESHOLD = 95.0  # Uptime below this is critical
MAX_ALERT_ISSUES = 10  # Maximum issues to show in dashboard

router = APIRouter(prefix="/publishers", tags=["publishers"])


@router.get("/", response_model=list[PublisherWithStats])
async def list_publishers(
    db: DbSession,
    has_results: bool = Query(True, description="Only publishers with benchmark results"),
    is_active: bool = Query(True, description="Only active publishers"),
):
    """
    List all publishers with their latest summary statistics.

    Returns publishers sorted by pass rate (descending).
    """
    # Get latest summary date
    latest_date_query = select(func.max(PublisherDailySummary.summary_date))
    latest_date = db.execute(latest_date_query).scalar()

    if not latest_date and has_results:
        return []

    # Build query
    query = select(Publisher)

    if is_active:
        query = query.where(Publisher.is_active == True)

    publishers = db.execute(query.order_by(Publisher.publisher_id)).scalars().all()

    # Get summaries for latest date
    summaries = {}
    if latest_date:
        summary_query = (
            select(PublisherDailySummary)
            .where(PublisherDailySummary.summary_date == latest_date)
        )
        for summary in db.execute(summary_query).scalars().all():
            summaries[summary.publisher_id] = summary

    result = []
    for pub in publishers:
        summary = summaries.get(pub.publisher_id)

        # Skip publishers without results if requested
        if has_results and not summary:
            continue

        result.append(
            PublisherWithStats(
                publisher_id=pub.publisher_id,
                name=pub.name,
                is_active=pub.is_active,
                last_seen_at=pub.last_seen_at,
                latest_date=str(latest_date) if latest_date else None,
                pass_rate_pct=float(summary.pass_rate_pct) if summary and summary.pass_rate_pct else None,
                total_feeds=summary.total_feeds if summary else None,
                median_nrmse=float(summary.median_nrmse) if summary and summary.median_nrmse else None,
                median_hit_rate=float(summary.median_hit_rate) if summary and summary.median_hit_rate else None,
            )
        )

    # Sort by pass rate descending
    result.sort(key=lambda x: (x.pass_rate_pct or 0), reverse=True)

    return result


@router.get("/{publisher_id}", response_model=PublisherResponse)
async def get_publisher(publisher_id: int, db: DbSession):
    """Get publisher details."""
    publisher = db.get(Publisher, publisher_id)
    if not publisher:
        raise HTTPException(status_code=404, detail=f"Publisher {publisher_id} not found")

    return PublisherResponse.model_validate(publisher)


@router.get("/{publisher_id}/summary", response_model=PublisherSummaryDetail)
async def get_publisher_summary(
    publisher_id: int,
    db: DbSession,
    target_date: Optional[date] = Query(None, description="Specific date (default: latest)"),
):
    """
    Get detailed summary statistics for a publisher.

    Returns the latest summary if no date is specified.
    """
    # Check publisher exists
    publisher = db.get(Publisher, publisher_id)
    if not publisher:
        raise HTTPException(status_code=404, detail=f"Publisher {publisher_id} not found")

    # Build query
    query = select(PublisherDailySummary).where(
        PublisherDailySummary.publisher_id == publisher_id
    )

    if target_date:
        query = query.where(PublisherDailySummary.summary_date == target_date)
    else:
        query = query.order_by(desc(PublisherDailySummary.summary_date)).limit(1)

    summary = db.execute(query).scalar()

    if not summary:
        raise HTTPException(
            status_code=404,
            detail=f"No summary found for publisher {publisher_id}" +
                   (f" on {target_date}" if target_date else ""),
        )

    return PublisherSummaryDetail.model_validate(summary)


@router.get("/{publisher_id}/summary/history", response_model=list[PublisherSummaryResponse])
async def get_publisher_summary_history(
    publisher_id: int,
    db: DbSession,
    date_range: DateRange,
    pagination: Pagination,
):
    """
    Get historical daily summaries for a publisher.

    Returns summaries within the date range, ordered by date descending.
    """
    # Check publisher exists
    publisher = db.get(Publisher, publisher_id)
    if not publisher:
        raise HTTPException(status_code=404, detail=f"Publisher {publisher_id} not found")

    query = (
        select(PublisherDailySummary)
        .where(PublisherDailySummary.publisher_id == publisher_id)
        .where(PublisherDailySummary.summary_date >= date_range.start_date)
        .where(PublisherDailySummary.summary_date <= date_range.end_date)
        .order_by(desc(PublisherDailySummary.summary_date))
        .offset(pagination.skip)
        .limit(pagination.limit)
    )

    summaries = db.execute(query).scalars().all()

    return [PublisherSummaryResponse.model_validate(s) for s in summaries]


@router.get("/{publisher_id}/trends", response_model=list[TrendData])
async def get_publisher_trends(
    publisher_id: int,
    db: DbSession,
    date_range: DateRange,
    metrics: list[str] = Query(
        ["pass_rate_pct", "median_nrmse", "median_hit_rate"],
        description="Metrics to include in trends",
    ),
):
    """
    Get trend data for a publisher's metrics over time.

    Returns time series data for the requested metrics.
    """
    # Check publisher exists
    publisher = db.get(Publisher, publisher_id)
    if not publisher:
        raise HTTPException(status_code=404, detail=f"Publisher {publisher_id} not found")

    # Get summaries in date range
    query = (
        select(PublisherDailySummary)
        .where(PublisherDailySummary.publisher_id == publisher_id)
        .where(PublisherDailySummary.summary_date >= date_range.start_date)
        .where(PublisherDailySummary.summary_date <= date_range.end_date)
        .order_by(PublisherDailySummary.summary_date)
    )

    summaries = db.execute(query).scalars().all()

    # Metric configurations
    metric_config = {
        "pass_rate_pct": {"unit": "%", "attr": "pass_rate_pct"},
        "median_nrmse": {"unit": "ratio", "attr": "median_nrmse"},
        "median_hit_rate": {"unit": "%", "attr": "median_hit_rate"},
        "total_feeds": {"unit": "count", "attr": "total_feeds"},
        "total_observations": {"unit": "count", "attr": "total_observations"},
        "median_mae": {"unit": "price", "attr": "median_mae"},
    }

    result = []
    for metric in metrics:
        if metric not in metric_config:
            continue

        config = metric_config[metric]
        data = []

        for summary in summaries:
            value = getattr(summary, config["attr"], None)
            data.append(
                TrendPoint(
                    date=summary.summary_date,
                    value=float(value) if value is not None else None,
                )
            )

        result.append(
            TrendData(
                metric=metric,
                unit=config["unit"],
                data=data,
            )
        )

    return result


@router.get("/{publisher_id}/feeds", response_model=PaginatedResponse[BenchmarkResultListItem])
async def get_publisher_feeds(
    publisher_id: int,
    db: DbSession,
    pagination: Pagination,
    asset_filter: AssetFilter,
    target_date: Optional[date] = Query(None, description="Specific date (default: latest)"),
    passes: Optional[bool] = Query(None, description="Filter by pass/fail status"),
    has_error: Optional[bool] = Query(None, description="Filter by error status"),
):
    """
    Get benchmark results for all feeds of a publisher.

    Returns feed results for the specified date, with filtering options.
    """
    # Check publisher exists
    publisher = db.get(Publisher, publisher_id)
    if not publisher:
        raise HTTPException(status_code=404, detail=f"Publisher {publisher_id} not found")

    # Determine target date
    if target_date is None:
        latest_date_query = (
            select(func.max(BenchmarkResult.benchmark_date))
            .where(BenchmarkResult.publisher_id == publisher_id)
        )
        target_date = db.execute(latest_date_query).scalar()

        if not target_date:
            return PaginatedResponse(
                items=[],
                total=0,
                skip=pagination.skip,
                limit=pagination.limit,
                has_more=False,
            )

    # Build query
    query = (
        select(BenchmarkResult)
        .where(BenchmarkResult.publisher_id == publisher_id)
        .where(BenchmarkResult.benchmark_date == target_date)
    )

    # Apply filters
    if asset_filter.asset_class:
        query = query.where(BenchmarkResult.asset_class == asset_filter.asset_class)

    if passes is not None:
        query = query.where(BenchmarkResult.passes == passes)

    if has_error is True:
        query = query.where(BenchmarkResult.error.isnot(None))
    elif has_error is False:
        query = query.where(BenchmarkResult.error.is_(None))

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = db.execute(count_query).scalar() or 0

    # Get paginated results
    query = (
        query
        .order_by(BenchmarkResult.passes, BenchmarkResult.feed_id)
        .offset(pagination.skip)
        .limit(pagination.limit)
    )

    results = db.execute(query).scalars().all()

    items = [
        BenchmarkResultListItem(
            feed_id=r.feed_id,
            symbol=r.symbol,
            asset_class=r.asset_class,
            passes=r.passes,
            n_observations=r.n_observations,
            nrmse=float(r.nrmse) if r.nrmse else None,
            hit_rate=float(r.hit_rate) if r.hit_rate else None,
            error=r.error,
        )
        for r in results
    ]

    return PaginatedResponse(
        items=items,
        total=total,
        skip=pagination.skip,
        limit=pagination.limit,
        has_more=(pagination.skip + len(items)) < total,
    )


@router.get("/{publisher_id}/feeds/{feed_id}", response_model=BenchmarkResultResponse)
async def get_publisher_feed_result(
    publisher_id: int,
    feed_id: int,
    db: DbSession,
    target_date: Optional[date] = Query(None, description="Specific date (default: latest)"),
):
    """
    Get detailed benchmark result for a specific feed and publisher.
    """
    # Determine target date
    if target_date is None:
        latest_date_query = (
            select(func.max(BenchmarkResult.benchmark_date))
            .where(BenchmarkResult.publisher_id == publisher_id)
            .where(BenchmarkResult.feed_id == feed_id)
        )
        target_date = db.execute(latest_date_query).scalar()

        if not target_date:
            raise HTTPException(
                status_code=404,
                detail=f"No results found for publisher {publisher_id}, feed {feed_id}",
            )

    # Get result
    query = (
        select(BenchmarkResult)
        .where(BenchmarkResult.publisher_id == publisher_id)
        .where(BenchmarkResult.feed_id == feed_id)
        .where(BenchmarkResult.benchmark_date == target_date)
    )

    result = db.execute(query).scalar()

    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"No result found for publisher {publisher_id}, feed {feed_id} on {target_date}",
        )

    return BenchmarkResultResponse.model_validate(result)


@router.get("/{publisher_id}/asset-classes", response_model=list[AssetClassBreakdown])
async def get_publisher_asset_class_breakdown(
    publisher_id: int,
    db: DbSession,
    target_date: Optional[date] = Query(None, description="Specific date (default: latest)"),
):
    """
    Get breakdown of results by asset class for a publisher.
    """
    # Check publisher exists
    publisher = db.get(Publisher, publisher_id)
    if not publisher:
        raise HTTPException(status_code=404, detail=f"Publisher {publisher_id} not found")

    # Determine target date
    if target_date is None:
        latest_date_query = (
            select(func.max(BenchmarkResult.benchmark_date))
            .where(BenchmarkResult.publisher_id == publisher_id)
        )
        target_date = db.execute(latest_date_query).scalar()

        if not target_date:
            return []

    # Query aggregated results
    query = (
        select(
            BenchmarkResult.asset_class,
            func.count().label("total"),
            func.sum(func.cast(BenchmarkResult.passes, Integer)).label("pass_count"),
            func.sum(func.cast(BenchmarkResult.error.isnot(None), Integer)).label("error_count"),
        )
        .where(BenchmarkResult.publisher_id == publisher_id)
        .where(BenchmarkResult.benchmark_date == target_date)
        .group_by(BenchmarkResult.asset_class)
        .order_by(BenchmarkResult.asset_class)
    )

    results = db.execute(query).all()

    breakdown = []
    for row in results:
        total = row.total or 0
        pass_count = row.pass_count or 0
        error_count = row.error_count or 0
        fail_count = total - pass_count - error_count

        breakdown.append(
            AssetClassBreakdown(
                asset_class=row.asset_class,
                pass_count=pass_count,
                fail_count=fail_count,
                error_count=error_count,
                total=total,
                pass_rate_pct=(pass_count / total * 100) if total > 0 else None,
            )
        )

    return breakdown


@router.get("/{publisher_id}/dashboard", response_model=PublisherDashboardResponse)
async def get_publisher_dashboard(
    publisher_id: int,
    db: DbSession,
    target_date: Optional[date] = Query(None, description="Date (default: latest)"),
):
    """
    Get combined dashboard with benchmark + uptime metrics.

    This is the main endpoint for the publisher dashboard, providing
    a unified view of benchmark and uptime metrics.
    """
    # Check publisher exists
    publisher = db.get(Publisher, publisher_id)
    if not publisher:
        raise HTTPException(status_code=404, detail=f"Publisher {publisher_id} not found")

    # Determine target date from benchmark summary
    if target_date is None:
        latest_date_query = (
            select(func.max(PublisherDailySummary.summary_date))
            .where(PublisherDailySummary.publisher_id == publisher_id)
        )
        target_date = db.execute(latest_date_query).scalar()

    # Get benchmark summary
    benchmark_summary = None
    if target_date:
        benchmark_query = (
            select(PublisherDailySummary)
            .where(PublisherDailySummary.publisher_id == publisher_id)
            .where(PublisherDailySummary.summary_date == target_date)
        )
        benchmark_summary = db.execute(benchmark_query).scalar()

    # Get uptime summary
    uptime_summary = None
    if target_date:
        uptime_query = (
            select(PublisherDailyUptimeSummary)
            .where(PublisherDailyUptimeSummary.publisher_id == publisher_id)
            .where(PublisherDailyUptimeSummary.summary_date == target_date)
        )
        uptime_summary = db.execute(uptime_query).scalar()

    # Build benchmark metrics
    benchmark_metrics = BenchmarkMetrics(
        pass_rate_pct=float(benchmark_summary.pass_rate_pct) if benchmark_summary and benchmark_summary.pass_rate_pct else None,
        median_nrmse=float(benchmark_summary.median_nrmse) if benchmark_summary and benchmark_summary.median_nrmse else None,
        median_hit_rate=float(benchmark_summary.median_hit_rate) if benchmark_summary and benchmark_summary.median_hit_rate else None,
        total_feeds=benchmark_summary.total_feeds if benchmark_summary else 0,
        pass_count=benchmark_summary.pass_count if benchmark_summary else 0,
        fail_count=benchmark_summary.fail_count if benchmark_summary else 0,
        error_count=benchmark_summary.error_count if benchmark_summary else 0,
    )

    # Build uptime metrics
    uptime_metrics = UptimeMetrics(
        overall_median_uptime_pct=float(uptime_summary.overall_median_uptime_pct) if uptime_summary and uptime_summary.overall_median_uptime_pct else None,
        regular_median_uptime_pct=float(uptime_summary.regular_median_uptime_pct) if uptime_summary and uptime_summary.regular_median_uptime_pct else None,
        premarket_median_uptime_pct=float(uptime_summary.premarket_median_uptime_pct) if uptime_summary and uptime_summary.premarket_median_uptime_pct else None,
        afterhours_median_uptime_pct=float(uptime_summary.afterhours_median_uptime_pct) if uptime_summary and uptime_summary.afterhours_median_uptime_pct else None,
        overnight_median_uptime_pct=float(uptime_summary.overnight_median_uptime_pct) if uptime_summary and uptime_summary.overnight_median_uptime_pct else None,
    )

    # Build alerts
    alerts = _build_dashboard_alerts(db, publisher_id, target_date, benchmark_summary)

    return PublisherDashboardResponse(
        publisher_id=publisher_id,
        publisher_name=publisher.name,
        latest_date=target_date,
        benchmark=benchmark_metrics,
        uptime=uptime_metrics,
        alerts=alerts,
    )


def _build_dashboard_alerts(
    db: Session,
    publisher_id: int,
    target_date: Optional[date],
    benchmark_summary,
) -> DashboardAlerts:
    """Build alerts for the dashboard."""
    failing_feeds_count = 0
    low_uptime_feeds_count = 0
    top_issues: list[AlertItem] = []

    if not target_date:
        return DashboardAlerts(
            failing_feeds_count=0,
            low_uptime_feeds_count=0,
            top_issues=[],
        )

    # Count failing feeds
    if benchmark_summary:
        failing_feeds_count = benchmark_summary.fail_count or 0

    # Get top failing feeds (by worst NRMSE)
    failing_query = (
        select(BenchmarkResult)
        .where(BenchmarkResult.publisher_id == publisher_id)
        .where(BenchmarkResult.benchmark_date == target_date)
        .where(BenchmarkResult.passes == False)
        .where(BenchmarkResult.error.is_(None))
        .order_by(desc(BenchmarkResult.nrmse))
        .limit(5)
    )
    failing_results = db.execute(failing_query).scalars().all()

    for result in failing_results:
        nrmse_str = f"{float(result.nrmse):.4f}" if result.nrmse else "N/A"
        is_critical = result.nrmse and float(result.nrmse) > NRMSE_CRITICAL_THRESHOLD
        top_issues.append(
            AlertItem(
                severity="critical" if is_critical else "warning",
                message=f"Feed {result.symbol or result.feed_id} failing with NRMSE {nrmse_str}",
                feed_id=result.feed_id,
                symbol=result.symbol,
            )
        )

    # Get feeds with errors
    error_query = (
        select(BenchmarkResult)
        .where(BenchmarkResult.publisher_id == publisher_id)
        .where(BenchmarkResult.benchmark_date == target_date)
        .where(BenchmarkResult.error.isnot(None))
        .limit(3)
    )
    error_results = db.execute(error_query).scalars().all()

    for result in error_results:
        top_issues.append(
            AlertItem(
                severity="warning",
                message=f"Feed {result.symbol or result.feed_id}: {result.error[:50]}..." if result.error and len(result.error) > 50 else f"Feed {result.symbol or result.feed_id}: {result.error}",
                feed_id=result.feed_id,
                symbol=result.symbol,
            )
        )

    # Count low uptime feeds
    low_uptime_query = (
        select(func.count())
        .select_from(PublisherFeedDailyUptime)
        .where(PublisherFeedDailyUptime.publisher_id == publisher_id)
        .where(PublisherFeedDailyUptime.uptime_date == target_date)
        .where(PublisherFeedDailyUptime.session == "regular")
        .where(PublisherFeedDailyUptime.uptime_pct < UPTIME_LOW_THRESHOLD)
    )
    low_uptime_feeds_count = db.execute(low_uptime_query).scalar() or 0

    # Get top low uptime feeds
    low_uptime_feeds_query = (
        select(PublisherFeedDailyUptime)
        .where(PublisherFeedDailyUptime.publisher_id == publisher_id)
        .where(PublisherFeedDailyUptime.uptime_date == target_date)
        .where(PublisherFeedDailyUptime.session == "regular")
        .where(PublisherFeedDailyUptime.uptime_pct < UPTIME_LOW_THRESHOLD)
        .order_by(PublisherFeedDailyUptime.uptime_pct)
        .limit(3)
    )
    low_uptime_feeds = db.execute(low_uptime_feeds_query).scalars().all()

    for uptime_row in low_uptime_feeds:
        is_critical = float(uptime_row.uptime_pct) < UPTIME_CRITICAL_THRESHOLD
        top_issues.append(
            AlertItem(
                severity="critical" if is_critical else "warning",
                message=f"Feed {uptime_row.feed_id} has {float(uptime_row.uptime_pct):.2f}% uptime",
                feed_id=uptime_row.feed_id,
                symbol=None,
            )
        )

    return DashboardAlerts(
        failing_feeds_count=failing_feeds_count,
        low_uptime_feeds_count=low_uptime_feeds_count,
        top_issues=top_issues[:MAX_ALERT_ISSUES],
    )
