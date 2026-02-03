"""
Database models for publisher performance portal.

This module exports all SQLAlchemy ORM models and Pydantic schemas.
"""

# Base
from portal.models.base import Base, TimestampMixin

# SQLAlchemy Models
from portal.models.benchmark_job import BenchmarkJob, JobStatus, JobType
from portal.models.benchmark_result import BenchmarkResult
from portal.models.feed import Feed
from portal.models.publisher import Publisher
from portal.models.publisher_summary import PublisherDailySummary
from portal.models.publisher_uptime import PublisherFeedDailyUptime
from portal.models.publisher_uptime_summary import PublisherDailyUptimeSummary

# Pydantic Schemas - Publisher
from portal.models.publisher import (
    PublisherBase,
    PublisherCreate,
    PublisherListItem,
    PublisherResponse,
    PublisherWithStats,
)

# Pydantic Schemas - Feed
from portal.models.feed import (
    FeedBase,
    FeedCreate,
    FeedListItem,
    FeedResponse,
    FeedWithLatestResult,
)

# Pydantic Schemas - Benchmark Result
from portal.models.benchmark_result import (
    BenchmarkResultBase,
    BenchmarkResultCreate,
    BenchmarkResultDetail,
    BenchmarkResultListItem,
    BenchmarkResultResponse,
    ExtendedHoursMetrics,
)

# Pydantic Schemas - Publisher Summary
from portal.models.publisher_summary import (
    AssetClassStats,
    ExtendedHoursSummary,
    LeaderboardEntry,
    LeaderboardResponse,
    PublisherSummaryBase,
    PublisherSummaryCreate,
    PublisherSummaryDetail,
    PublisherSummaryResponse,
)
from portal.models.publisher_uptime import PublisherFeedUptimeBase, PublisherFeedUptimeResponse

# Pydantic Schemas - Publisher Uptime Summary
from portal.models.publisher_uptime_summary import (
    AssetClassUptimeStats,
    PublisherUptimeSummaryBase,
    PublisherUptimeSummaryCreate,
    PublisherUptimeSummaryDetail,
    PublisherUptimeSummaryResponse,
    SessionUptimeStats,
    UptimeDashboardMetrics,
)

# Pydantic Schemas - Benchmark Job
from portal.models.benchmark_job import (
    BenchmarkJobCreate,
    BenchmarkJobListItem,
    BenchmarkJobResponse,
    BenchmarkJobStatus,
)

__all__ = [
    # Base
    "Base",
    "TimestampMixin",
    # SQLAlchemy Models
    "Publisher",
    "Feed",
    "BenchmarkResult",
    "PublisherDailySummary",
    "PublisherFeedDailyUptime",
    "PublisherDailyUptimeSummary",
    "BenchmarkJob",
    "JobStatus",
    "JobType",
    # Publisher Schemas
    "PublisherBase",
    "PublisherCreate",
    "PublisherResponse",
    "PublisherListItem",
    "PublisherWithStats",
    # Feed Schemas
    "FeedBase",
    "FeedCreate",
    "FeedResponse",
    "FeedListItem",
    "FeedWithLatestResult",
    # Benchmark Result Schemas
    "BenchmarkResultBase",
    "BenchmarkResultCreate",
    "BenchmarkResultResponse",
    "BenchmarkResultDetail",
    "BenchmarkResultListItem",
    "ExtendedHoursMetrics",
    # Publisher Summary Schemas
    "PublisherSummaryBase",
    "PublisherSummaryCreate",
    "PublisherSummaryResponse",
    "PublisherSummaryDetail",
    "AssetClassStats",
    "ExtendedHoursSummary",
    "LeaderboardEntry",
    "LeaderboardResponse",
    "PublisherFeedUptimeBase",
    "PublisherFeedUptimeResponse",
    # Publisher Uptime Summary Schemas
    "PublisherUptimeSummaryBase",
    "PublisherUptimeSummaryCreate",
    "PublisherUptimeSummaryResponse",
    "PublisherUptimeSummaryDetail",
    "SessionUptimeStats",
    "AssetClassUptimeStats",
    "UptimeDashboardMetrics",
    # Benchmark Job Schemas
    "BenchmarkJobCreate",
    "BenchmarkJobResponse",
    "BenchmarkJobStatus",
    "BenchmarkJobListItem",
]
