"""
Feed endpoints for the Publisher Performance Portal.

Provides endpoints to get feed details, history, and compare publishers.
"""

from datetime import date
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc, func, select

from portal.api.dependencies import AssetFilter, DateRange, DbSession, Pagination
from portal.api.schemas import PaginatedResponse, TrendData, TrendPoint
from portal.models import (
    BenchmarkResult,
    BenchmarkResultDetail,
    BenchmarkResultResponse,
    Feed,
    FeedListItem,
    FeedResponse,
    FeedWithLatestResult,
)

router = APIRouter(prefix="/feeds", tags=["feeds"])


@router.get("/", response_model=PaginatedResponse[FeedWithLatestResult])
async def list_feeds(
    db: DbSession,
    pagination: Pagination,
    asset_filter: AssetFilter,
    is_active: bool = Query(True, description="Only active feeds"),
    has_results: bool = Query(True, description="Only feeds with benchmark results"),
):
    """
    List all feeds with their latest benchmark status.

    Optionally filter by asset class and active status.
    """
    # Get latest benchmark date
    latest_date_query = select(func.max(BenchmarkResult.benchmark_date))
    latest_date = db.execute(latest_date_query).scalar()

    # Build feeds query
    query = select(Feed)

    if is_active:
        query = query.where(Feed.is_active == True)

    if asset_filter.asset_class:
        query = query.where(Feed.asset_class == asset_filter.asset_class)

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = db.execute(count_query).scalar() or 0

    # Get paginated feeds
    query = (
        query.order_by(Feed.asset_class, Feed.feed_id)
        .offset(pagination.skip)
        .limit(pagination.limit)
    )

    feeds = db.execute(query).scalars().all()

    # Get latest results for these feeds (any publisher)
    feed_ids = [f.feed_id for f in feeds]
    latest_results = {}

    if feed_ids and latest_date:
        results_query = (
            select(BenchmarkResult)
            .where(BenchmarkResult.feed_id.in_(feed_ids))
            .where(BenchmarkResult.benchmark_date == latest_date)
            .where(BenchmarkResult.error.is_(None))
        )

        for result in db.execute(results_query).scalars().all():
            # Keep track of best result per feed (by pass status, then nrmse)
            existing = latest_results.get(result.feed_id)
            if existing is None:
                latest_results[result.feed_id] = result
            elif result.passes and not existing.passes:
                latest_results[result.feed_id] = result
            elif result.passes == existing.passes:
                if result.nrmse and existing.nrmse and result.nrmse < existing.nrmse:
                    latest_results[result.feed_id] = result

    items = []
    for feed in feeds:
        result = latest_results.get(feed.feed_id)

        if has_results and not result:
            continue

        items.append(
            FeedWithLatestResult(
                feed_id=feed.feed_id,
                symbol=feed.symbol,
                asset_class=feed.asset_class,
                is_active=feed.is_active,
                latest_date=str(latest_date) if latest_date else None,
                passes=result.passes if result else None,
                nrmse=float(result.nrmse) if result and result.nrmse else None,
                hit_rate=float(result.hit_rate) if result and result.hit_rate else None,
                n_observations=result.n_observations if result else None,
                error=result.error if result else None,
            )
        )

    return PaginatedResponse(
        items=items,
        total=len(items) if has_results else total,
        skip=pagination.skip,
        limit=pagination.limit,
        has_more=(pagination.skip + len(items)) < total,
    )


@router.get("/{feed_id}", response_model=FeedResponse)
async def get_feed(feed_id: int, db: DbSession):
    """Get feed details."""
    feed = db.get(Feed, feed_id)
    if not feed:
        raise HTTPException(status_code=404, detail=f"Feed {feed_id} not found")

    return FeedResponse.model_validate(feed)


@router.get("/{feed_id}/publishers")
async def get_feed_publishers(
    feed_id: int,
    db: DbSession,
    target_date: Optional[date] = Query(
        None, description="Specific date (default: latest)"
    ),
):
    """
    Get all publishers for a feed with their benchmark results.

    Useful for comparing how different publishers perform on the same feed.
    """
    # Check feed exists
    feed = db.get(Feed, feed_id)
    if not feed:
        raise HTTPException(status_code=404, detail=f"Feed {feed_id} not found")

    # Determine target date
    if target_date is None:
        latest_date_query = select(func.max(BenchmarkResult.benchmark_date)).where(
            BenchmarkResult.feed_id == feed_id
        )
        target_date = db.execute(latest_date_query).scalar()

        if not target_date:
            return {
                "feed_id": feed_id,
                "symbol": feed.symbol,
                "asset_class": feed.asset_class,
                "date": None,
                "publishers": [],
            }

    # Get all results for this feed
    query = (
        select(BenchmarkResult)
        .where(BenchmarkResult.feed_id == feed_id)
        .where(BenchmarkResult.benchmark_date == target_date)
        .order_by(BenchmarkResult.passes.desc(), BenchmarkResult.nrmse.asc())
    )

    results = db.execute(query).scalars().all()

    publishers = [
        {
            "publisher_id": r.publisher_id,
            "passes": r.passes,
            "n_observations": r.n_observations,
            "nrmse": float(r.nrmse) if r.nrmse else None,
            "hit_rate": float(r.hit_rate) if r.hit_rate else None,
            "rmse_over_spread": float(r.rmse_over_spread)
            if r.rmse_over_spread
            else None,
            "error": r.error,
        }
        for r in results
    ]

    return {
        "feed_id": feed_id,
        "symbol": feed.symbol,
        "asset_class": feed.asset_class,
        "date": str(target_date),
        "total_publishers": len(publishers),
        "passing_publishers": sum(
            1 for p in publishers if p["passes"] and not p["error"]
        ),
        "publishers": publishers,
    }


@router.get(
    "/{feed_id}/history", response_model=PaginatedResponse[BenchmarkResultResponse]
)
async def get_feed_history(
    feed_id: int,
    db: DbSession,
    date_range: DateRange,
    pagination: Pagination,
    publisher_id: Optional[int] = Query(None, description="Filter by publisher"),
):
    """
    Get historical benchmark results for a feed.

    Optionally filter by publisher to see a specific publisher's history.
    """
    # Check feed exists
    feed = db.get(Feed, feed_id)
    if not feed:
        raise HTTPException(status_code=404, detail=f"Feed {feed_id} not found")

    # Build query
    query = (
        select(BenchmarkResult)
        .where(BenchmarkResult.feed_id == feed_id)
        .where(BenchmarkResult.benchmark_date >= date_range.start_date)
        .where(BenchmarkResult.benchmark_date <= date_range.end_date)
    )

    if publisher_id:
        query = query.where(BenchmarkResult.publisher_id == publisher_id)

    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    total = db.execute(count_query).scalar() or 0

    # Get paginated results
    query = (
        query.order_by(
            desc(BenchmarkResult.benchmark_date), BenchmarkResult.publisher_id
        )
        .offset(pagination.skip)
        .limit(pagination.limit)
    )

    results = db.execute(query).scalars().all()

    items = [BenchmarkResultResponse.model_validate(r) for r in results]

    return PaginatedResponse(
        items=items,
        total=total,
        skip=pagination.skip,
        limit=pagination.limit,
        has_more=(pagination.skip + len(items)) < total,
    )


@router.get("/{feed_id}/trends", response_model=list[TrendData])
async def get_feed_trends(
    feed_id: int,
    db: DbSession,
    date_range: DateRange,
    publisher_id: int = Query(..., description="Publisher to get trends for"),
    metrics: list[str] = Query(
        ["nrmse", "hit_rate"],
        description="Metrics to include in trends",
    ),
):
    """
    Get trend data for a feed's metrics over time for a specific publisher.
    """
    # Check feed exists
    feed = db.get(Feed, feed_id)
    if not feed:
        raise HTTPException(status_code=404, detail=f"Feed {feed_id} not found")

    # Get results in date range
    query = (
        select(BenchmarkResult)
        .where(BenchmarkResult.feed_id == feed_id)
        .where(BenchmarkResult.publisher_id == publisher_id)
        .where(BenchmarkResult.benchmark_date >= date_range.start_date)
        .where(BenchmarkResult.benchmark_date <= date_range.end_date)
        .where(BenchmarkResult.error.is_(None))
        .order_by(BenchmarkResult.benchmark_date)
    )

    results = db.execute(query).scalars().all()

    # Metric configurations
    metric_config = {
        "nrmse": {"unit": "ratio", "attr": "nrmse"},
        "hit_rate": {"unit": "%", "attr": "hit_rate"},
        "rmse": {"unit": "price", "attr": "rmse"},
        "rmse_over_spread": {"unit": "ratio", "attr": "rmse_over_spread"},
        "n_observations": {"unit": "count", "attr": "n_observations"},
    }

    trend_data = []
    for metric in metrics:
        if metric not in metric_config:
            continue

        config = metric_config[metric]
        data = []

        for result in results:
            value = getattr(result, config["attr"], None)
            data.append(
                TrendPoint(
                    date=result.benchmark_date,
                    value=float(value) if value is not None else None,
                )
            )

        trend_data.append(
            TrendData(
                metric=metric,
                unit=config["unit"],
                data=data,
            )
        )

    return trend_data


@router.get("/{feed_id}/results/{publisher_id}", response_model=BenchmarkResultDetail)
async def get_feed_publisher_result(
    feed_id: int,
    publisher_id: int,
    db: DbSession,
    target_date: Optional[date] = Query(
        None, description="Specific date (default: latest)"
    ),
):
    """
    Get detailed benchmark result for a specific feed and publisher combination.

    Includes all statistical metrics and extended hours data if available.
    """
    # Determine target date
    if target_date is None:
        latest_date_query = (
            select(func.max(BenchmarkResult.benchmark_date))
            .where(BenchmarkResult.feed_id == feed_id)
            .where(BenchmarkResult.publisher_id == publisher_id)
        )
        target_date = db.execute(latest_date_query).scalar()

        if not target_date:
            raise HTTPException(
                status_code=404,
                detail=f"No results found for feed {feed_id}, publisher {publisher_id}",
            )

    # Get result
    query = (
        select(BenchmarkResult)
        .where(BenchmarkResult.feed_id == feed_id)
        .where(BenchmarkResult.publisher_id == publisher_id)
        .where(BenchmarkResult.benchmark_date == target_date)
    )

    result = db.execute(query).scalar()

    if not result:
        raise HTTPException(
            status_code=404,
            detail=f"No result found for feed {feed_id}, publisher {publisher_id} on {target_date}",
        )

    return BenchmarkResultDetail.from_orm_with_extended(result)
