"""
Leaderboard endpoints for the Publisher Performance Portal.

Provides ranked publisher lists and comparison views.
"""

from datetime import date
from enum import Enum
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import desc, func, select

from portal.api.dependencies import DbSession
from portal.models import (
    LeaderboardEntry,
    LeaderboardResponse,
    Publisher,
    PublisherDailySummary,
)

router = APIRouter(prefix="/leaderboard", tags=["leaderboard"])


class SortBy(str, Enum):
    """Sorting options for leaderboard."""

    PASS_RATE = "pass_rate"
    NRMSE = "nrmse"
    HIT_RATE = "hit_rate"
    TOTAL_FEEDS = "total_feeds"


@router.get("/", response_model=LeaderboardResponse)
async def get_leaderboard(
    db: DbSession,
    target_date: Optional[date] = Query(
        None, description="Date for leaderboard (default: latest)"
    ),
    asset_class: Optional[str] = Query(None, description="Filter by asset class"),
    sort_by: SortBy = Query(SortBy.PASS_RATE, description="Sort metric"),
    limit: int = Query(50, ge=1, le=100, description="Maximum entries to return"),
):
    """
    Get publisher leaderboard ranked by performance.

    Returns publishers sorted by the chosen metric.
    """
    # Determine target date
    if target_date is None:
        latest_date_query = select(func.max(PublisherDailySummary.summary_date))
        target_date = db.execute(latest_date_query).scalar()

        if not target_date:
            return LeaderboardResponse(
                date=date.today(),
                total_publishers=0,
                entries=[],
            )

    # Get all summaries for the date
    query = select(PublisherDailySummary).where(
        PublisherDailySummary.summary_date == target_date
    )

    summaries = db.execute(query).scalars().all()

    if not summaries:
        return LeaderboardResponse(
            date=target_date,
            total_publishers=0,
            entries=[],
        )

    # Filter by asset class if specified
    if asset_class:
        filtered_summaries = []
        for s in summaries:
            if s.asset_class_breakdown and asset_class in s.asset_class_breakdown:
                filtered_summaries.append(s)
        summaries = filtered_summaries

    # Get publisher names
    publisher_ids = [s.publisher_id for s in summaries]
    publishers_query = select(Publisher).where(
        Publisher.publisher_id.in_(publisher_ids)
    )
    publishers = {
        p.publisher_id: p for p in db.execute(publishers_query).scalars().all()
    }

    # Build entries with metrics
    entries = []
    for summary in summaries:
        publisher = publishers.get(summary.publisher_id)

        # If filtering by asset class, calculate metrics from breakdown
        if asset_class and summary.asset_class_breakdown:
            breakdown = summary.asset_class_breakdown.get(asset_class, {})
            pass_count = breakdown.get("pass", 0)
            fail_count = breakdown.get("fail", 0)
            total = pass_count + fail_count + breakdown.get("error", 0)
            pass_rate = (pass_count / total * 100) if total > 0 else None
        else:
            pass_rate = float(summary.pass_rate_pct) if summary.pass_rate_pct else None
            total = summary.total_feeds

        entries.append(
            {
                "publisher_id": summary.publisher_id,
                "publisher_name": publisher.name
                if publisher
                else f"Publisher {summary.publisher_id}",
                "pass_rate_pct": pass_rate,
                "median_nrmse": float(summary.median_nrmse)
                if summary.median_nrmse
                else None,
                "median_hit_rate": float(summary.median_hit_rate)
                if summary.median_hit_rate
                else None,
                "total_feeds": total,
            }
        )

    # Sort entries
    if sort_by == SortBy.PASS_RATE:
        entries.sort(key=lambda x: (x["pass_rate_pct"] or 0), reverse=True)
    elif sort_by == SortBy.NRMSE:
        # Lower NRMSE is better, so sort ascending (None values at end)
        entries.sort(
            key=lambda x: (x["median_nrmse"] is None, x["median_nrmse"] or float("inf"))
        )
    elif sort_by == SortBy.HIT_RATE:
        entries.sort(key=lambda x: (x["median_hit_rate"] or 0), reverse=True)
    elif sort_by == SortBy.TOTAL_FEEDS:
        entries.sort(key=lambda x: x["total_feeds"], reverse=True)

    # Add ranks
    entries = entries[:limit]

    # Calculate ranks for different metrics
    pass_rate_sorted = sorted(
        entries, key=lambda x: (x["pass_rate_pct"] or 0), reverse=True
    )
    nrmse_sorted = sorted(
        entries,
        key=lambda x: (x["median_nrmse"] is None, x["median_nrmse"] or float("inf")),
    )
    hit_rate_sorted = sorted(
        entries, key=lambda x: (x["median_hit_rate"] or 0), reverse=True
    )

    pass_rate_ranks = {e["publisher_id"]: i + 1 for i, e in enumerate(pass_rate_sorted)}
    nrmse_ranks = {e["publisher_id"]: i + 1 for i, e in enumerate(nrmse_sorted)}
    hit_rate_ranks = {e["publisher_id"]: i + 1 for i, e in enumerate(hit_rate_sorted)}

    leaderboard_entries = []
    for rank, entry in enumerate(entries, 1):
        leaderboard_entries.append(
            LeaderboardEntry(
                rank=rank,
                publisher_id=entry["publisher_id"],
                publisher_name=entry["publisher_name"],
                pass_rate_pct=entry["pass_rate_pct"],
                median_nrmse=entry["median_nrmse"],
                median_hit_rate=entry["median_hit_rate"],
                total_feeds=entry["total_feeds"],
                rank_by_pass_rate=pass_rate_ranks.get(entry["publisher_id"]),
                rank_by_nrmse=nrmse_ranks.get(entry["publisher_id"]),
                rank_by_hit_rate=hit_rate_ranks.get(entry["publisher_id"]),
            )
        )

    return LeaderboardResponse(
        date=target_date,
        total_publishers=len(summaries),
        entries=leaderboard_entries,
    )


@router.get("/dates")
async def get_available_dates(
    db: DbSession,
    limit: int = Query(
        30, ge=1, le=100, description="Number of recent dates to return"
    ),
):
    """
    Get list of dates with leaderboard data.

    Returns most recent dates first.
    """
    query = (
        select(PublisherDailySummary.summary_date)
        .distinct()
        .order_by(desc(PublisherDailySummary.summary_date))
        .limit(limit)
    )

    dates = db.execute(query).scalars().all()

    return {
        "dates": [str(d) for d in dates],
        "latest": str(dates[0]) if dates else None,
        "earliest": str(dates[-1]) if dates else None,
        "count": len(dates),
    }


@router.get("/publisher/{publisher_id}/rank")
async def get_publisher_rank(
    publisher_id: int,
    db: DbSession,
    target_date: Optional[date] = Query(
        None, description="Date for ranking (default: latest)"
    ),
):
    """
    Get a specific publisher's rank in the leaderboard.

    Returns ranks by different metrics.
    """
    # Determine target date
    if target_date is None:
        latest_date_query = select(func.max(PublisherDailySummary.summary_date))
        target_date = db.execute(latest_date_query).scalar()

        if not target_date:
            raise HTTPException(status_code=404, detail="No leaderboard data available")

    # Get target publisher summary
    publisher_summary = db.execute(
        select(PublisherDailySummary)
        .where(PublisherDailySummary.publisher_id == publisher_id)
        .where(PublisherDailySummary.summary_date == target_date)
    ).scalar()

    if not publisher_summary:
        raise HTTPException(
            status_code=404,
            detail=f"No data for publisher {publisher_id} on {target_date}",
        )

    # Get all summaries for ranking
    all_summaries = (
        db.execute(
            select(PublisherDailySummary).where(
                PublisherDailySummary.summary_date == target_date
            )
        )
        .scalars()
        .all()
    )

    total_publishers = len(all_summaries)

    # Calculate ranks
    pass_rate_sorted = sorted(
        all_summaries,
        key=lambda x: (float(x.pass_rate_pct) if x.pass_rate_pct else 0),
        reverse=True,
    )
    nrmse_sorted = sorted(
        all_summaries,
        key=lambda x: (
            x.median_nrmse is None,
            float(x.median_nrmse) if x.median_nrmse else float("inf"),
        ),
    )
    hit_rate_sorted = sorted(
        all_summaries,
        key=lambda x: (float(x.median_hit_rate) if x.median_hit_rate else 0),
        reverse=True,
    )

    rank_by_pass_rate = next(
        (
            i + 1
            for i, s in enumerate(pass_rate_sorted)
            if s.publisher_id == publisher_id
        ),
        None,
    )
    rank_by_nrmse = next(
        (i + 1 for i, s in enumerate(nrmse_sorted) if s.publisher_id == publisher_id),
        None,
    )
    rank_by_hit_rate = next(
        (
            i + 1
            for i, s in enumerate(hit_rate_sorted)
            if s.publisher_id == publisher_id
        ),
        None,
    )

    return {
        "publisher_id": publisher_id,
        "date": str(target_date),
        "total_publishers": total_publishers,
        "ranks": {
            "by_pass_rate": rank_by_pass_rate,
            "by_nrmse": rank_by_nrmse,
            "by_hit_rate": rank_by_hit_rate,
        },
        "percentiles": {
            "by_pass_rate": round(
                (total_publishers - rank_by_pass_rate + 1) / total_publishers * 100, 1
            )
            if rank_by_pass_rate
            else None,
            "by_nrmse": round(
                (total_publishers - rank_by_nrmse + 1) / total_publishers * 100, 1
            )
            if rank_by_nrmse
            else None,
            "by_hit_rate": round(
                (total_publishers - rank_by_hit_rate + 1) / total_publishers * 100, 1
            )
            if rank_by_hit_rate
            else None,
        },
        "metrics": {
            "pass_rate_pct": float(publisher_summary.pass_rate_pct)
            if publisher_summary.pass_rate_pct
            else None,
            "median_nrmse": float(publisher_summary.median_nrmse)
            if publisher_summary.median_nrmse
            else None,
            "median_hit_rate": float(publisher_summary.median_hit_rate)
            if publisher_summary.median_hit_rate
            else None,
            "total_feeds": publisher_summary.total_feeds,
        },
    }


@router.get("/publisher/{publisher_id}/history")
async def get_publisher_rank_history(
    publisher_id: int,
    db: DbSession,
    days: int = Query(30, ge=1, le=90, description="Number of days of history"),
):
    """
    Get a publisher's rank history over time.

    Shows how the publisher's position has changed.
    """
    # Get all dates with data
    dates_query = (
        select(PublisherDailySummary.summary_date)
        .distinct()
        .order_by(desc(PublisherDailySummary.summary_date))
        .limit(days)
    )
    dates = list(db.execute(dates_query).scalars().all())
    dates.reverse()  # Oldest first

    history = []

    for target_date in dates:
        # Get all summaries for this date
        all_summaries = (
            db.execute(
                select(PublisherDailySummary).where(
                    PublisherDailySummary.summary_date == target_date
                )
            )
            .scalars()
            .all()
        )

        # Find publisher's summary
        publisher_summary = next(
            (s for s in all_summaries if s.publisher_id == publisher_id),
            None,
        )

        if not publisher_summary:
            continue

        total_publishers = len(all_summaries)

        # Calculate pass rate rank
        pass_rate_sorted = sorted(
            all_summaries,
            key=lambda x: (float(x.pass_rate_pct) if x.pass_rate_pct else 0),
            reverse=True,
        )
        rank = next(
            (
                i + 1
                for i, s in enumerate(pass_rate_sorted)
                if s.publisher_id == publisher_id
            ),
            None,
        )

        history.append(
            {
                "date": str(target_date),
                "rank": rank,
                "total_publishers": total_publishers,
                "pass_rate_pct": float(publisher_summary.pass_rate_pct)
                if publisher_summary.pass_rate_pct
                else None,
                "median_nrmse": float(publisher_summary.median_nrmse)
                if publisher_summary.median_nrmse
                else None,
            }
        )

    return {
        "publisher_id": publisher_id,
        "history": history,
    }
