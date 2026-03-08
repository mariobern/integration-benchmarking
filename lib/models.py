"""Shared dataclasses for Pyth Lazer benchmark scripts.

These models are used across quick_benchmark, publisher_benchmark,
feed_readiness, and feed_uptime scripts.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

# Reference publisher for overnight benchmark (Blue Ocean ATS)
OVERNIGHT_REFERENCE_PUBLISHER_ID = 32


class TradingSession(Enum):
    """Trading session types for US equities."""

    REGULAR = "regular"
    PREMARKET = "premarket"
    AFTERHOURS = "afterhours"
    OVERNIGHT = "overnight"


@dataclass
class ExtendedHoursMetrics:
    """Metrics for a single extended hours session (pre-market or after-hours)."""

    session: TradingSession
    n_observations: int
    rmse: Optional[float]
    mean_spread: Optional[float]
    rmse_over_spread: Optional[float]
    nrmse: Optional[float]
    hit_rate: Optional[float]
    benchmark_price_range: Optional[float]
    passes: bool
    error: Optional[str] = None


@dataclass
class OvernightMetrics:
    """Metrics for overnight session using publisher 32 as benchmark."""

    n_observations: int
    n_reference_observations: int
    rmse: Optional[float]
    mean_spread: Optional[float]
    rmse_over_spread: Optional[float]
    nrmse: Optional[float]
    hit_rate: Optional[float]
    reference_price_range: Optional[float]
    passes: bool
    reference_publisher_id: int = OVERNIGHT_REFERENCE_PUBLISHER_ID
    error: Optional[str] = None


@dataclass
class PublisherFeedMetrics:
    """Per-publisher metrics within a feed evaluation."""

    publisher_id: int
    n_observations: int
    passes: bool
    nrmse: Optional[float] = None
    hit_rate: Optional[float] = None
    rmse: Optional[float] = None
    mean_spread: Optional[float] = None
    rmse_over_spread: Optional[float] = None
    benchmark_price_range: Optional[float] = None
    mean_diff: Optional[float] = None
    std_diff: Optional[float] = None
    mean_pct_diff: Optional[float] = None
    std_pct_diff: Optional[float] = None
    mae: Optional[float] = None
    t_statistic: Optional[float] = None
    t_pvalue: Optional[float] = None
    wilcoxon_statistic: Optional[float] = None
    wilcoxon_pvalue: Optional[float] = None
    normality_pvalue: Optional[float] = None
    mean_abs_z_score: Optional[float] = None
    premarket_metrics: Optional[ExtendedHoursMetrics] = None
    afterhours_metrics: Optional[ExtendedHoursMetrics] = None
    overnight_metrics: Optional[OvernightMetrics] = None
    error: Optional[str] = None


@dataclass
class BenchmarkResult:
    """Result of a single feed benchmark evaluation."""

    feed_id: int
    date: str
    mode: str
    symbol: Optional[str]
    ready: bool
    target_pub_count: int
    passing_pub_count: int
    failing_pub_count: int
    passing_publishers: list[int]
    failing_publishers: list[int]
    median_nrmse: Optional[float] = None
    median_hit_rate: Optional[float] = None
    publisher_details: Optional[list[PublisherFeedMetrics]] = None
    premarket_passing_count: Optional[int] = None
    premarket_failing_count: Optional[int] = None
    afterhours_passing_count: Optional[int] = None
    afterhours_failing_count: Optional[int] = None
    overnight_passing_count: Optional[int] = None
    overnight_failing_count: Optional[int] = None
    overnight_reference_publisher_id: Optional[int] = None
    error: Optional[str] = None
    agg_metrics: Optional[PublisherFeedMetrics] = None
    execution_time_ms: int = 0


@dataclass
class PublisherBenchmarkResult:
    """Result of a single publisher's benchmark evaluation for one feed."""

    publisher_id: int
    feed_id: int
    date: str
    mode: str
    symbol: Optional[str]
    passes: bool
    n_observations: int
    rmse: Optional[float]
    mean_spread: Optional[float]
    rmse_over_spread: Optional[float]
    nrmse: Optional[float] = None
    hit_rate: Optional[float] = None
    benchmark_price_range: Optional[float] = None
    mean_diff: Optional[float] = None
    std_diff: Optional[float] = None
    mean_pct_diff: Optional[float] = None
    std_pct_diff: Optional[float] = None
    mae: Optional[float] = None
    t_statistic: Optional[float] = None
    t_pvalue: Optional[float] = None
    wilcoxon_statistic: Optional[float] = None
    wilcoxon_pvalue: Optional[float] = None
    normality_pvalue: Optional[float] = None
    mean_abs_z_score: Optional[float] = None
    premarket_metrics: Optional[ExtendedHoursMetrics] = None
    afterhours_metrics: Optional[ExtendedHoursMetrics] = None
    overnight_metrics: Optional[OvernightMetrics] = None
    error: Optional[str] = None
    execution_time_ms: int = 0


@dataclass(frozen=True)
class PublisherSessionUptime:
    """Uptime metrics for a single publisher in a single trading session."""

    publisher_id: int
    session: str
    uptime_pct: float
    passes: bool
    seconds_with_data: int
    total_seconds: int
    updates_total: int
    updates_per_second: float
    downtime_ms: Optional[int]
    period_length_ms: Optional[int]
    max_gap_ms: Optional[int]
    gaps_over_threshold: Optional[int]


@dataclass(frozen=True)
class FeedUptimeResult:
    """Uptime evaluation result for a single feed."""

    feed_id: int
    date: str
    mode: str
    symbol: Optional[str]
    publisher_count: int
    publisher_uptimes: list[PublisherSessionUptime]
    error: Optional[str]
    execution_time_ms: int
