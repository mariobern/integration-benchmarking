"""
Benchmark result model and schemas.

Stores individual benchmark results for each publisher/feed/date combination.
"""

from datetime import date, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import (
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)

from portal.models.base import Base


class BenchmarkResult(Base):
    """SQLAlchemy model for benchmark_results table."""

    __tablename__ = "benchmark_results"
    __table_args__ = (
        UniqueConstraint("publisher_id", "feed_id", "benchmark_date", name="uq_results_publisher_feed_date"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Identifiers
    publisher_id = Column(Integer, nullable=False, index=True)
    feed_id = Column(Integer, nullable=False, index=True)
    benchmark_date = Column(Date, nullable=False, index=True)
    asset_class = Column(String(50), nullable=False, index=True)
    symbol = Column(String(255), nullable=True)

    # Pass/Fail status
    passes = Column(Boolean, nullable=False)

    # Primary metrics
    n_observations = Column(Integer, nullable=False, default=0)
    nrmse = Column(Numeric(12, 8), nullable=True)
    hit_rate = Column(Numeric(8, 4), nullable=True)
    benchmark_price_range = Column(Numeric(18, 8), nullable=True)

    # Secondary metrics
    rmse = Column(Numeric(18, 8), nullable=True)
    mean_spread = Column(Numeric(18, 8), nullable=True)
    rmse_over_spread = Column(Numeric(12, 6), nullable=True)

    # Statistical metrics - Basic
    mean_diff = Column(Numeric(18, 10), nullable=True)
    std_diff = Column(Numeric(18, 10), nullable=True)
    mean_pct_diff = Column(Numeric(12, 8), nullable=True)
    std_pct_diff = Column(Numeric(12, 8), nullable=True)
    mae = Column(Numeric(18, 10), nullable=True)

    # Statistical metrics - Hypothesis tests
    t_statistic = Column(Numeric(12, 6), nullable=True)
    t_pvalue = Column(Numeric(12, 8), nullable=True)
    wilcoxon_statistic = Column(Numeric(12, 6), nullable=True)
    wilcoxon_pvalue = Column(Numeric(12, 8), nullable=True)
    normality_pvalue = Column(Numeric(12, 8), nullable=True)
    mean_abs_z_score = Column(Numeric(12, 6), nullable=True)

    # Extended hours metrics (US equities only)
    premarket_n_observations = Column(Integer, nullable=True)
    premarket_nrmse = Column(Numeric(12, 8), nullable=True)
    premarket_hit_rate = Column(Numeric(8, 4), nullable=True)
    premarket_passes = Column(Boolean, nullable=True)
    premarket_error = Column(Text, nullable=True)

    afterhours_n_observations = Column(Integer, nullable=True)
    afterhours_nrmse = Column(Numeric(12, 8), nullable=True)
    afterhours_hit_rate = Column(Numeric(8, 4), nullable=True)
    afterhours_passes = Column(Boolean, nullable=True)
    afterhours_error = Column(Text, nullable=True)

    # Overnight session metrics (US equities only, uses publisher 32 as reference)
    overnight_n_observations = Column(Integer, nullable=True)
    overnight_n_reference_observations = Column(Integer, nullable=True)
    overnight_nrmse = Column(Numeric(12, 8), nullable=True)
    overnight_hit_rate = Column(Numeric(8, 4), nullable=True)
    overnight_passes = Column(Boolean, nullable=True)
    overnight_reference_publisher_id = Column(Integer, nullable=True)
    overnight_error = Column(Text, nullable=True)

    # Error tracking
    error = Column(Text, nullable=True)
    execution_time_ms = Column(Integer, nullable=True)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<BenchmarkResult(pub={self.publisher_id}, feed={self.feed_id}, date={self.benchmark_date}, passes={self.passes})>"


# Pydantic Schemas


class ExtendedHoursMetrics(BaseModel):
    """Schema for extended hours (pre-market/after-hours) metrics."""

    n_observations: Optional[int] = None
    nrmse: Optional[float] = None
    hit_rate: Optional[float] = None
    passes: Optional[bool] = None
    error: Optional[str] = None


class OvernightMetrics(BaseModel):
    """Schema for overnight session metrics (uses publisher 32 as reference)."""

    n_observations: Optional[int] = None
    n_reference_observations: Optional[int] = None
    nrmse: Optional[float] = None
    hit_rate: Optional[float] = None
    passes: Optional[bool] = None
    reference_publisher_id: Optional[int] = None
    error: Optional[str] = None


class BenchmarkResultBase(BaseModel):
    """Base schema for benchmark result data."""

    publisher_id: int
    feed_id: int
    benchmark_date: date
    asset_class: str
    symbol: Optional[str] = None
    passes: bool
    n_observations: int = 0

    # Primary metrics
    nrmse: Optional[float] = None
    hit_rate: Optional[float] = None
    benchmark_price_range: Optional[float] = None

    # Secondary metrics
    rmse: Optional[float] = None
    mean_spread: Optional[float] = None
    rmse_over_spread: Optional[float] = None

    # Error
    error: Optional[str] = None
    execution_time_ms: Optional[int] = None


class BenchmarkResultCreate(BenchmarkResultBase):
    """Schema for creating a benchmark result."""

    # Statistical metrics - Basic
    mean_diff: Optional[float] = None
    std_diff: Optional[float] = None
    mean_pct_diff: Optional[float] = None
    std_pct_diff: Optional[float] = None
    mae: Optional[float] = None

    # Statistical metrics - Hypothesis tests
    t_statistic: Optional[float] = None
    t_pvalue: Optional[float] = None
    wilcoxon_statistic: Optional[float] = None
    wilcoxon_pvalue: Optional[float] = None
    normality_pvalue: Optional[float] = None
    mean_abs_z_score: Optional[float] = None

    # Extended hours
    premarket_n_observations: Optional[int] = None
    premarket_nrmse: Optional[float] = None
    premarket_hit_rate: Optional[float] = None
    premarket_passes: Optional[bool] = None
    premarket_error: Optional[str] = None

    afterhours_n_observations: Optional[int] = None
    afterhours_nrmse: Optional[float] = None
    afterhours_hit_rate: Optional[float] = None
    afterhours_passes: Optional[bool] = None
    afterhours_error: Optional[str] = None

    # Overnight session
    overnight_n_observations: Optional[int] = None
    overnight_n_reference_observations: Optional[int] = None
    overnight_nrmse: Optional[float] = None
    overnight_hit_rate: Optional[float] = None
    overnight_passes: Optional[bool] = None
    overnight_reference_publisher_id: Optional[int] = None
    overnight_error: Optional[str] = None


class BenchmarkResultResponse(BenchmarkResultBase):
    """Schema for benchmark result API response (basic)."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime


class BenchmarkResultDetail(BenchmarkResultResponse):
    """Schema for benchmark result with all statistical metrics."""

    # Statistical metrics - Basic
    mean_diff: Optional[float] = None
    std_diff: Optional[float] = None
    mean_pct_diff: Optional[float] = None
    std_pct_diff: Optional[float] = None
    mae: Optional[float] = None

    # Statistical metrics - Hypothesis tests
    t_statistic: Optional[float] = None
    t_pvalue: Optional[float] = None
    wilcoxon_statistic: Optional[float] = None
    wilcoxon_pvalue: Optional[float] = None
    normality_pvalue: Optional[float] = None
    mean_abs_z_score: Optional[float] = None

    # Extended hours (nested)
    premarket: Optional[ExtendedHoursMetrics] = None
    afterhours: Optional[ExtendedHoursMetrics] = None
    overnight: Optional[OvernightMetrics] = None

    @classmethod
    def from_orm_with_extended(cls, obj: BenchmarkResult) -> "BenchmarkResultDetail":
        """Create response with nested extended hours metrics."""
        data = {
            "id": obj.id,
            "publisher_id": obj.publisher_id,
            "feed_id": obj.feed_id,
            "benchmark_date": obj.benchmark_date,
            "asset_class": obj.asset_class,
            "symbol": obj.symbol,
            "passes": obj.passes,
            "n_observations": obj.n_observations,
            "nrmse": float(obj.nrmse) if obj.nrmse else None,
            "hit_rate": float(obj.hit_rate) if obj.hit_rate else None,
            "benchmark_price_range": float(obj.benchmark_price_range) if obj.benchmark_price_range else None,
            "rmse": float(obj.rmse) if obj.rmse else None,
            "mean_spread": float(obj.mean_spread) if obj.mean_spread else None,
            "rmse_over_spread": float(obj.rmse_over_spread) if obj.rmse_over_spread else None,
            "mean_diff": float(obj.mean_diff) if obj.mean_diff else None,
            "std_diff": float(obj.std_diff) if obj.std_diff else None,
            "mean_pct_diff": float(obj.mean_pct_diff) if obj.mean_pct_diff else None,
            "std_pct_diff": float(obj.std_pct_diff) if obj.std_pct_diff else None,
            "mae": float(obj.mae) if obj.mae else None,
            "t_statistic": float(obj.t_statistic) if obj.t_statistic else None,
            "t_pvalue": float(obj.t_pvalue) if obj.t_pvalue else None,
            "wilcoxon_statistic": float(obj.wilcoxon_statistic) if obj.wilcoxon_statistic else None,
            "wilcoxon_pvalue": float(obj.wilcoxon_pvalue) if obj.wilcoxon_pvalue else None,
            "normality_pvalue": float(obj.normality_pvalue) if obj.normality_pvalue else None,
            "mean_abs_z_score": float(obj.mean_abs_z_score) if obj.mean_abs_z_score else None,
            "error": obj.error,
            "execution_time_ms": obj.execution_time_ms,
            "created_at": obj.created_at,
        }

        # Add nested extended hours
        if obj.premarket_n_observations is not None:
            data["premarket"] = ExtendedHoursMetrics(
                n_observations=obj.premarket_n_observations,
                nrmse=float(obj.premarket_nrmse) if obj.premarket_nrmse else None,
                hit_rate=float(obj.premarket_hit_rate) if obj.premarket_hit_rate else None,
                passes=obj.premarket_passes,
                error=obj.premarket_error,
            )

        if obj.afterhours_n_observations is not None:
            data["afterhours"] = ExtendedHoursMetrics(
                n_observations=obj.afterhours_n_observations,
                nrmse=float(obj.afterhours_nrmse) if obj.afterhours_nrmse else None,
                hit_rate=float(obj.afterhours_hit_rate) if obj.afterhours_hit_rate else None,
                passes=obj.afterhours_passes,
                error=obj.afterhours_error,
            )

        if obj.overnight_n_observations is not None:
            data["overnight"] = OvernightMetrics(
                n_observations=obj.overnight_n_observations,
                n_reference_observations=obj.overnight_n_reference_observations,
                nrmse=float(obj.overnight_nrmse) if obj.overnight_nrmse else None,
                hit_rate=float(obj.overnight_hit_rate) if obj.overnight_hit_rate else None,
                passes=obj.overnight_passes,
                reference_publisher_id=obj.overnight_reference_publisher_id,
                error=obj.overnight_error,
            )

        return cls(**data)


class BenchmarkResultListItem(BaseModel):
    """Schema for benchmark result in list responses (minimal fields)."""

    model_config = ConfigDict(from_attributes=True)

    feed_id: int
    symbol: Optional[str] = None
    asset_class: str
    passes: bool
    n_observations: int
    nrmse: Optional[float] = None
    hit_rate: Optional[float] = None
    error: Optional[str] = None
