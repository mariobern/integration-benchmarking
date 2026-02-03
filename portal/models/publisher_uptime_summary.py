"""
Publisher daily uptime summary model and schemas.

Pre-aggregated daily uptime statistics per publisher for fast dashboard queries.
"""

from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, Date, DateTime, Integer, JSON, Numeric, UniqueConstraint

from portal.models.base import Base


class PublisherDailyUptimeSummary(Base):
    """SQLAlchemy model for publisher_daily_uptime_summary table."""

    __tablename__ = "publisher_daily_uptime_summary"
    __table_args__ = (
        UniqueConstraint("publisher_id", "summary_date", name="uq_uptime_summary_publisher_date"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Identifiers
    publisher_id = Column(Integer, nullable=False, index=True)
    summary_date = Column(Date, nullable=False, index=True)

    # Per-session aggregates - Regular
    regular_median_uptime_pct = Column(Numeric(6, 4), nullable=True)
    regular_mean_uptime_pct = Column(Numeric(6, 4), nullable=True)
    regular_min_uptime_pct = Column(Numeric(6, 4), nullable=True)
    regular_total_feeds = Column(Integer, default=0)

    # Per-session aggregates - Premarket
    premarket_median_uptime_pct = Column(Numeric(6, 4), nullable=True)
    premarket_mean_uptime_pct = Column(Numeric(6, 4), nullable=True)
    premarket_min_uptime_pct = Column(Numeric(6, 4), nullable=True)
    premarket_total_feeds = Column(Integer, default=0)

    # Per-session aggregates - Afterhours
    afterhours_median_uptime_pct = Column(Numeric(6, 4), nullable=True)
    afterhours_mean_uptime_pct = Column(Numeric(6, 4), nullable=True)
    afterhours_min_uptime_pct = Column(Numeric(6, 4), nullable=True)
    afterhours_total_feeds = Column(Integer, default=0)

    # Per-session aggregates - Overnight
    overnight_median_uptime_pct = Column(Numeric(6, 4), nullable=True)
    overnight_mean_uptime_pct = Column(Numeric(6, 4), nullable=True)
    overnight_min_uptime_pct = Column(Numeric(6, 4), nullable=True)
    overnight_total_feeds = Column(Integer, default=0)

    # Overall aggregates
    overall_median_uptime_pct = Column(Numeric(6, 4), nullable=True)
    overall_mean_uptime_pct = Column(Numeric(6, 4), nullable=True)
    total_feeds = Column(Integer, default=0)

    # Asset class breakdown (JSON)
    asset_class_uptime = Column(JSON, nullable=True)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return (
            f"<PublisherDailyUptimeSummary(pub={self.publisher_id}, "
            f"date={self.summary_date}, overall={self.overall_median_uptime_pct})>"
        )


# Pydantic Schemas


class SessionUptimeStats(BaseModel):
    """Uptime statistics for a single session."""

    median_uptime_pct: Optional[float] = None
    mean_uptime_pct: Optional[float] = None
    min_uptime_pct: Optional[float] = None
    total_feeds: int = 0


class AssetClassUptimeStats(BaseModel):
    """Uptime statistics for a single asset class."""

    asset_class: str
    median_uptime_pct: Optional[float] = None
    mean_uptime_pct: Optional[float] = None
    min_uptime_pct: Optional[float] = None
    total_feeds: int = 0


class PublisherUptimeSummaryBase(BaseModel):
    """Base schema for publisher uptime summary."""

    publisher_id: int
    summary_date: date

    # Overall
    overall_median_uptime_pct: Optional[float] = None
    overall_mean_uptime_pct: Optional[float] = None
    total_feeds: int = 0


class PublisherUptimeSummaryCreate(PublisherUptimeSummaryBase):
    """Schema for creating a publisher uptime summary."""

    # Per-session aggregates - Regular
    regular_median_uptime_pct: Optional[float] = None
    regular_mean_uptime_pct: Optional[float] = None
    regular_min_uptime_pct: Optional[float] = None
    regular_total_feeds: int = 0

    # Per-session aggregates - Premarket
    premarket_median_uptime_pct: Optional[float] = None
    premarket_mean_uptime_pct: Optional[float] = None
    premarket_min_uptime_pct: Optional[float] = None
    premarket_total_feeds: int = 0

    # Per-session aggregates - Afterhours
    afterhours_median_uptime_pct: Optional[float] = None
    afterhours_mean_uptime_pct: Optional[float] = None
    afterhours_min_uptime_pct: Optional[float] = None
    afterhours_total_feeds: int = 0

    # Per-session aggregates - Overnight
    overnight_median_uptime_pct: Optional[float] = None
    overnight_mean_uptime_pct: Optional[float] = None
    overnight_min_uptime_pct: Optional[float] = None
    overnight_total_feeds: int = 0

    # Asset class breakdown (JSON)
    asset_class_uptime: Optional[dict[str, Any]] = None


class PublisherUptimeSummaryResponse(PublisherUptimeSummaryBase):
    """Schema for uptime summary API response (basic)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    regular_median_uptime_pct: Optional[float] = None
    premarket_median_uptime_pct: Optional[float] = None
    afterhours_median_uptime_pct: Optional[float] = None
    overnight_median_uptime_pct: Optional[float] = None
    created_at: datetime


class PublisherUptimeSummaryDetail(PublisherUptimeSummaryResponse):
    """Schema for uptime summary with all metrics."""

    # Regular session
    regular_mean_uptime_pct: Optional[float] = None
    regular_min_uptime_pct: Optional[float] = None
    regular_total_feeds: int = 0

    # Premarket session
    premarket_mean_uptime_pct: Optional[float] = None
    premarket_min_uptime_pct: Optional[float] = None
    premarket_total_feeds: int = 0

    # Afterhours session
    afterhours_mean_uptime_pct: Optional[float] = None
    afterhours_min_uptime_pct: Optional[float] = None
    afterhours_total_feeds: int = 0

    # Overnight session
    overnight_mean_uptime_pct: Optional[float] = None
    overnight_min_uptime_pct: Optional[float] = None
    overnight_total_feeds: int = 0

    # Overall
    overall_mean_uptime_pct: Optional[float] = None

    # Asset class breakdown
    asset_class_uptime: Optional[dict[str, AssetClassUptimeStats]] = None


class UptimeDashboardMetrics(BaseModel):
    """Uptime metrics for dashboard display."""

    overall_median_uptime_pct: Optional[float] = Field(None, description="Overall median uptime %")
    regular_median_uptime_pct: Optional[float] = Field(None, description="Regular hours median uptime %")
    premarket_median_uptime_pct: Optional[float] = Field(None, description="Pre-market median uptime %")
    afterhours_median_uptime_pct: Optional[float] = Field(None, description="After-hours median uptime %")
    overnight_median_uptime_pct: Optional[float] = Field(None, description="Overnight median uptime %")
