"""
Publisher daily summary model and schemas.

Pre-aggregated daily statistics per publisher for fast leaderboard queries.
"""

from datetime import date, datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import BigInteger, Column, Date, DateTime, Integer, JSON, Numeric, UniqueConstraint

from portal.models.base import Base


class PublisherDailySummary(Base):
    """SQLAlchemy model for publisher_daily_summary table."""

    __tablename__ = "publisher_daily_summary"
    __table_args__ = (
        UniqueConstraint("publisher_id", "summary_date", name="uq_summary_publisher_date"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Identifiers
    publisher_id = Column(Integer, nullable=False, index=True)
    summary_date = Column(Date, nullable=False, index=True)

    # Counts
    total_feeds = Column(Integer, nullable=False, default=0)
    pass_count = Column(Integer, nullable=False, default=0)
    fail_count = Column(Integer, nullable=False, default=0)
    error_count = Column(Integer, nullable=False, default=0)
    pass_rate_pct = Column(Numeric(5, 2), nullable=True)

    # Pass criteria breakdown
    pass_by_nrmse_alone = Column(Integer, default=0)
    pass_by_nrmse_and_hit_rate = Column(Integer, default=0)

    # NRMSE aggregates
    median_nrmse = Column(Numeric(12, 8), nullable=True)
    mean_nrmse = Column(Numeric(12, 8), nullable=True)
    p90_nrmse = Column(Numeric(12, 8), nullable=True)
    p95_nrmse = Column(Numeric(12, 8), nullable=True)
    min_nrmse = Column(Numeric(12, 8), nullable=True)
    max_nrmse = Column(Numeric(12, 8), nullable=True)

    # Hit rate aggregates
    median_hit_rate = Column(Numeric(8, 4), nullable=True)
    mean_hit_rate = Column(Numeric(8, 4), nullable=True)
    min_hit_rate = Column(Numeric(8, 4), nullable=True)
    max_hit_rate = Column(Numeric(8, 4), nullable=True)

    # RMSE/Spread aggregates
    median_rmse_over_spread = Column(Numeric(12, 6), nullable=True)
    mean_rmse_over_spread = Column(Numeric(12, 6), nullable=True)
    p90_rmse_over_spread = Column(Numeric(12, 6), nullable=True)
    p95_rmse_over_spread = Column(Numeric(12, 6), nullable=True)

    # Coverage metrics
    total_observations = Column(BigInteger, default=0)
    mean_observations_per_feed = Column(Numeric(10, 1), nullable=True)
    median_observations_per_feed = Column(Integer, nullable=True)

    # Statistical summary
    median_mae = Column(Numeric(18, 10), nullable=True)
    mean_mae = Column(Numeric(18, 10), nullable=True)
    t_test_significance_rate = Column(Numeric(5, 2), nullable=True)
    normality_rate = Column(Numeric(5, 2), nullable=True)
    median_z_score = Column(Numeric(12, 6), nullable=True)

    # JSON breakdowns
    asset_class_breakdown = Column(JSON, nullable=True)
    extended_hours_summary = Column(JSON, nullable=True)

    # Timing
    batch_duration_sec = Column(Numeric(10, 2), nullable=True)

    # Uptime metrics (linked from PublisherDailyUptimeSummary)
    overall_median_uptime_pct = Column(Numeric(6, 4), nullable=True)
    regular_median_uptime_pct = Column(Numeric(6, 4), nullable=True)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<PublisherDailySummary(pub={self.publisher_id}, date={self.summary_date}, pass_rate={self.pass_rate_pct})>"


# Pydantic Schemas


class AssetClassStats(BaseModel):
    """Statistics for a single asset class."""

    pass_count: int = 0
    fail_count: int = 0
    error_count: int = 0
    pass_rate_pct: Optional[float] = None


class ExtendedHoursSummary(BaseModel):
    """Summary statistics for extended hours trading."""

    premarket_total_feeds: int = 0
    premarket_pass_count: int = 0
    premarket_fail_count: int = 0
    premarket_error_count: int = 0
    premarket_pass_rate_pct: Optional[float] = None
    premarket_median_nrmse: Optional[float] = None
    premarket_median_hit_rate: Optional[float] = None

    afterhours_total_feeds: int = 0
    afterhours_pass_count: int = 0
    afterhours_fail_count: int = 0
    afterhours_error_count: int = 0
    afterhours_pass_rate_pct: Optional[float] = None
    afterhours_median_nrmse: Optional[float] = None
    afterhours_median_hit_rate: Optional[float] = None


class PublisherSummaryBase(BaseModel):
    """Base schema for publisher summary data."""

    publisher_id: int
    summary_date: date

    # Counts
    total_feeds: int = 0
    pass_count: int = 0
    fail_count: int = 0
    error_count: int = 0
    pass_rate_pct: Optional[float] = None

    # Pass criteria breakdown
    pass_by_nrmse_alone: Optional[int] = 0
    pass_by_nrmse_and_hit_rate: Optional[int] = 0


class PublisherSummaryCreate(PublisherSummaryBase):
    """Schema for creating a publisher summary."""

    # Uptime metrics (linked)
    overall_median_uptime_pct: Optional[float] = None
    regular_median_uptime_pct: Optional[float] = None

    # NRMSE aggregates
    median_nrmse: Optional[float] = None
    mean_nrmse: Optional[float] = None
    p90_nrmse: Optional[float] = None
    p95_nrmse: Optional[float] = None
    min_nrmse: Optional[float] = None
    max_nrmse: Optional[float] = None

    # Hit rate aggregates
    median_hit_rate: Optional[float] = None
    mean_hit_rate: Optional[float] = None
    min_hit_rate: Optional[float] = None
    max_hit_rate: Optional[float] = None

    # RMSE/Spread aggregates
    median_rmse_over_spread: Optional[float] = None
    mean_rmse_over_spread: Optional[float] = None
    p90_rmse_over_spread: Optional[float] = None
    p95_rmse_over_spread: Optional[float] = None

    # Coverage
    total_observations: Optional[int] = 0
    mean_observations_per_feed: Optional[float] = None
    median_observations_per_feed: Optional[int] = None

    # Statistical
    median_mae: Optional[float] = None
    mean_mae: Optional[float] = None
    t_test_significance_rate: Optional[float] = None
    normality_rate: Optional[float] = None
    median_z_score: Optional[float] = None

    # JSON
    asset_class_breakdown: Optional[dict[str, Any]] = None
    extended_hours_summary: Optional[dict[str, Any]] = None

    # Timing
    batch_duration_sec: Optional[float] = None


class PublisherSummaryResponse(PublisherSummaryBase):
    """Schema for publisher summary API response (basic)."""

    model_config = ConfigDict(from_attributes=True)

    id: int

    # Key metrics
    median_nrmse: Optional[float] = None
    median_hit_rate: Optional[float] = None
    total_observations: Optional[int] = None

    # Uptime metrics (linked)
    overall_median_uptime_pct: Optional[float] = None
    regular_median_uptime_pct: Optional[float] = None

    created_at: datetime


class PublisherSummaryDetail(PublisherSummaryResponse):
    """Schema for publisher summary with all metrics."""

    # NRMSE aggregates
    mean_nrmse: Optional[float] = None
    p90_nrmse: Optional[float] = None
    p95_nrmse: Optional[float] = None
    min_nrmse: Optional[float] = None
    max_nrmse: Optional[float] = None

    # Hit rate aggregates
    mean_hit_rate: Optional[float] = None
    min_hit_rate: Optional[float] = None
    max_hit_rate: Optional[float] = None

    # RMSE/Spread aggregates
    median_rmse_over_spread: Optional[float] = None
    mean_rmse_over_spread: Optional[float] = None
    p90_rmse_over_spread: Optional[float] = None
    p95_rmse_over_spread: Optional[float] = None

    # Coverage
    mean_observations_per_feed: Optional[float] = None
    median_observations_per_feed: Optional[int] = None

    # Statistical
    median_mae: Optional[float] = None
    mean_mae: Optional[float] = None
    t_test_significance_rate: Optional[float] = None
    normality_rate: Optional[float] = None
    median_z_score: Optional[float] = None

    # Breakdowns
    asset_class_breakdown: Optional[dict[str, AssetClassStats]] = None
    extended_hours_summary: Optional[ExtendedHoursSummary] = None

    # Timing
    batch_duration_sec: Optional[float] = None


class LeaderboardEntry(BaseModel):
    """Schema for leaderboard entry."""

    model_config = ConfigDict(from_attributes=True)

    rank: int
    publisher_id: int
    publisher_name: Optional[str] = None

    # Key metrics
    pass_rate_pct: Optional[float] = None
    median_nrmse: Optional[float] = None
    median_hit_rate: Optional[float] = None
    total_feeds: int = 0

    # Ranks by different metrics
    rank_by_pass_rate: Optional[int] = None
    rank_by_nrmse: Optional[int] = None
    rank_by_hit_rate: Optional[int] = None


class LeaderboardResponse(BaseModel):
    """Schema for leaderboard API response."""

    date: date
    total_publishers: int
    entries: list[LeaderboardEntry]
