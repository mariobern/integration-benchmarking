"""
Compute and store daily uptime summary aggregates.

This module computes aggregated uptime statistics per publisher/date
and stores them in the publisher_daily_uptime_summary table.
"""

from __future__ import annotations

import statistics
from datetime import date
from typing import Optional

from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import Engine

from portal.models import (
    PublisherDailyUptimeSummary,
    PublisherDailySummary,
    PublisherFeedDailyUptime,
)


def _get_dialect_name(session) -> str:
    """Get the database dialect name from the session."""
    bind = session.get_bind()
    if isinstance(bind, Engine):
        return bind.dialect.name
    return "postgresql"  # Default assumption


def _upsert_uptime_summary(session, data: dict) -> None:
    """
    Database-agnostic upsert for uptime summary.

    Uses PostgreSQL ON CONFLICT for PostgreSQL, and merge for SQLite.
    """
    dialect = _get_dialect_name(session)

    if dialect == "postgresql":
        stmt = postgresql.insert(PublisherDailyUptimeSummary).values(**data)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_uptime_summary_publisher_date",
            set_={
                k: v
                for k, v in data.items()
                if k not in ("publisher_id", "summary_date")
            },
        )
        session.execute(stmt)
    else:
        # SQLite fallback - use merge approach
        existing = (
            session.query(PublisherDailyUptimeSummary)
            .filter_by(
                publisher_id=data["publisher_id"],
                summary_date=data["summary_date"],
            )
            .first()
        )

        if existing:
            for k, v in data.items():
                if k not in ("publisher_id", "summary_date"):
                    setattr(existing, k, v)
        else:
            session.add(PublisherDailyUptimeSummary(**data))


def compute_daily_uptime_summary(
    session,
    publisher_id: int,
    target_date: date,
) -> Optional[dict]:
    """
    Compute and store daily uptime summary for a publisher.

    Aggregates uptime metrics by session and asset class.

    Args:
        session: SQLAlchemy session
        publisher_id: Publisher ID
        target_date: Date of the uptime data

    Returns:
        Summary dict if computed, None otherwise
    """
    # Query all uptime records for this publisher/date
    records = (
        session.query(PublisherFeedDailyUptime)
        .filter(
            PublisherFeedDailyUptime.publisher_id == publisher_id,
            PublisherFeedDailyUptime.uptime_date == target_date,
        )
        .all()
    )

    if not records:
        return None

    # Group by session
    sessions: dict[str, list[float]] = {}
    for r in records:
        sessions.setdefault(r.session, []).append(float(r.uptime_pct))

    # Group by asset class
    asset_classes: dict[str, list[float]] = {}
    for r in records:
        ac = r.asset_class or "unknown"
        asset_classes.setdefault(ac, []).append(float(r.uptime_pct))

    # Compute per-session stats
    def compute_stats(values: list[float]) -> dict:
        if not values:
            return {"median": None, "mean": None, "min": None, "total_feeds": 0}
        return {
            "median": round(statistics.median(values), 4),
            "mean": round(statistics.mean(values), 4),
            "min": round(min(values), 4),
            "total_feeds": len(values),
        }

    regular_stats = compute_stats(sessions.get("regular", []))
    premarket_stats = compute_stats(sessions.get("premarket", []))
    afterhours_stats = compute_stats(sessions.get("afterhours", []))
    overnight_stats = compute_stats(sessions.get("overnight", []))

    # Compute overall stats (across all sessions)
    all_values = [float(r.uptime_pct) for r in records]
    overall_stats = compute_stats(all_values)

    # Compute asset class breakdown
    asset_class_uptime = {}
    for ac, values in asset_classes.items():
        stats = compute_stats(values)
        asset_class_uptime[ac] = {
            "median_uptime_pct": stats["median"],
            "mean_uptime_pct": stats["mean"],
            "min_uptime_pct": stats["min"],
            "total_feeds": stats["total_feeds"],
        }

    # Prepare summary data
    summary_data = {
        "publisher_id": publisher_id,
        "summary_date": target_date,
        # Regular session
        "regular_median_uptime_pct": regular_stats["median"],
        "regular_mean_uptime_pct": regular_stats["mean"],
        "regular_min_uptime_pct": regular_stats["min"],
        "regular_total_feeds": regular_stats["total_feeds"],
        # Premarket session
        "premarket_median_uptime_pct": premarket_stats["median"],
        "premarket_mean_uptime_pct": premarket_stats["mean"],
        "premarket_min_uptime_pct": premarket_stats["min"],
        "premarket_total_feeds": premarket_stats["total_feeds"],
        # Afterhours session
        "afterhours_median_uptime_pct": afterhours_stats["median"],
        "afterhours_mean_uptime_pct": afterhours_stats["mean"],
        "afterhours_min_uptime_pct": afterhours_stats["min"],
        "afterhours_total_feeds": afterhours_stats["total_feeds"],
        # Overnight session
        "overnight_median_uptime_pct": overnight_stats["median"],
        "overnight_mean_uptime_pct": overnight_stats["mean"],
        "overnight_min_uptime_pct": overnight_stats["min"],
        "overnight_total_feeds": overnight_stats["total_feeds"],
        # Overall
        "overall_median_uptime_pct": overall_stats["median"],
        "overall_mean_uptime_pct": overall_stats["mean"],
        "total_feeds": overall_stats["total_feeds"],
        # Asset class breakdown
        "asset_class_uptime": asset_class_uptime,
    }

    # Upsert summary (database-agnostic)
    _upsert_uptime_summary(session, summary_data)
    session.commit()

    return summary_data


def link_uptime_to_benchmark_summary(
    session,
    publisher_id: int,
    target_date: date,
) -> None:
    """
    Link uptime metrics to the benchmark summary.

    Updates the publisher_daily_summary table with uptime data
    from publisher_daily_uptime_summary.

    Args:
        session: SQLAlchemy session
        publisher_id: Publisher ID
        target_date: Date of the data
    """
    # Get uptime summary
    uptime_summary = (
        session.query(PublisherDailyUptimeSummary)
        .filter(
            PublisherDailyUptimeSummary.publisher_id == publisher_id,
            PublisherDailyUptimeSummary.summary_date == target_date,
        )
        .first()
    )

    if not uptime_summary:
        return

    # Get benchmark summary
    benchmark_summary = (
        session.query(PublisherDailySummary)
        .filter(
            PublisherDailySummary.publisher_id == publisher_id,
            PublisherDailySummary.summary_date == target_date,
        )
        .first()
    )

    if not benchmark_summary:
        return

    # Update benchmark summary with uptime metrics
    benchmark_summary.overall_median_uptime_pct = (
        uptime_summary.overall_median_uptime_pct
    )
    benchmark_summary.regular_median_uptime_pct = (
        uptime_summary.regular_median_uptime_pct
    )

    session.commit()
