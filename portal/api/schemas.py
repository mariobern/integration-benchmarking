"""
Common API schemas for the Publisher Performance Portal.

Contains generic response wrappers and utility schemas.
"""

from datetime import date, datetime
from typing import Any, Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

# Generic type for paginated responses
T = TypeVar("T")


class PaginatedResponse(BaseModel, Generic[T]):
    """Generic paginated response wrapper."""

    items: list[T]
    total: int = Field(description="Total number of items")
    skip: int = Field(description="Number of items skipped")
    limit: int = Field(description="Maximum items per page")
    has_more: bool = Field(description="Whether there are more items")


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "healthy"
    timestamp: datetime = Field(default_factory=datetime.utcnow)
    database: str = "connected"
    version: str = "1.0.0"


class ErrorResponse(BaseModel):
    """Error response schema."""

    detail: str
    error_code: Optional[str] = None


class MetricsSummary(BaseModel):
    """Summary of key metrics for display."""

    model_config = ConfigDict(from_attributes=True)

    pass_rate_pct: Optional[float] = Field(None, description="Pass rate percentage")
    median_nrmse: Optional[float] = Field(None, description="Median NRMSE (lower is better)")
    median_hit_rate: Optional[float] = Field(None, description="Median hit rate percentage")
    total_feeds: int = Field(0, description="Total number of feeds")
    total_observations: Optional[int] = Field(None, description="Total observations")


class TrendPoint(BaseModel):
    """Single point in a time series trend."""

    date: date
    value: Optional[float] = None


class TrendData(BaseModel):
    """Time series trend data."""

    metric: str = Field(description="Name of the metric")
    unit: str = Field(description="Unit of measurement")
    data: list[TrendPoint]


class AssetClassBreakdown(BaseModel):
    """Breakdown of metrics by asset class."""

    asset_class: str
    pass_count: int = 0
    fail_count: int = 0
    error_count: int = 0
    total: int = 0
    pass_rate_pct: Optional[float] = None


class DateInfo(BaseModel):
    """Information about available dates."""

    latest_date: Optional[date] = Field(None, description="Most recent benchmark date")
    earliest_date: Optional[date] = Field(None, description="Earliest benchmark date")
    total_days: int = Field(0, description="Total days with data")


class UptimeSummaryItem(BaseModel):
    """Aggregated uptime metrics for a publisher/session/date."""

    asset_class: Optional[str] = None
    session: str
    total_feeds: int
    mean_uptime_pct: Optional[float] = None
    median_uptime_pct: Optional[float] = None
    min_uptime_pct: Optional[float] = None
    max_uptime_pct: Optional[float] = None


# Dashboard schemas


class BenchmarkMetrics(BaseModel):
    """Benchmark metrics for dashboard display."""

    pass_rate_pct: Optional[float] = Field(None, description="Pass rate percentage")
    median_nrmse: Optional[float] = Field(None, description="Median NRMSE")
    median_hit_rate: Optional[float] = Field(None, description="Median hit rate percentage")
    total_feeds: int = Field(0, description="Total number of feeds")
    pass_count: int = Field(0, description="Number of passing feeds")
    fail_count: int = Field(0, description="Number of failing feeds")
    error_count: int = Field(0, description="Number of feeds with errors")


class UptimeMetrics(BaseModel):
    """Uptime metrics for dashboard display."""

    overall_median_uptime_pct: Optional[float] = Field(None, description="Overall median uptime %")
    regular_median_uptime_pct: Optional[float] = Field(None, description="Regular hours median uptime %")
    premarket_median_uptime_pct: Optional[float] = Field(None, description="Pre-market median uptime %")
    afterhours_median_uptime_pct: Optional[float] = Field(None, description="After-hours median uptime %")
    overnight_median_uptime_pct: Optional[float] = Field(None, description="Overnight median uptime %")


class AlertItem(BaseModel):
    """Single alert/issue for dashboard."""

    severity: str = Field(description="Alert severity: critical, warning, info")
    message: str = Field(description="Alert message")
    feed_id: Optional[int] = Field(None, description="Related feed ID if applicable")
    symbol: Optional[str] = Field(None, description="Related symbol if applicable")


class DashboardAlerts(BaseModel):
    """Alerts summary for dashboard."""

    failing_feeds_count: int = Field(0, description="Number of failing feeds")
    low_uptime_feeds_count: int = Field(0, description="Number of feeds with low uptime")
    top_issues: list[AlertItem] = Field(default_factory=list, description="Top issues to address")


class PublisherDashboardResponse(BaseModel):
    """Combined dashboard response with benchmark + uptime metrics."""

    publisher_id: int
    publisher_name: Optional[str] = None
    latest_date: Optional[date] = None

    benchmark: BenchmarkMetrics
    uptime: UptimeMetrics
    alerts: DashboardAlerts


class UptimeTrendPoint(BaseModel):
    """Single point in uptime trend."""

    date: date
    session: str
    value: Optional[float] = None
