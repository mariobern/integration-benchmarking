"""
Benchmark job model and schemas.

Tracks on-demand and batch benchmark job runs.
"""

import uuid
from datetime import date, datetime
from enum import Enum
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import Column, Date, DateTime, Integer, String, Text, Boolean, JSON
from sqlalchemy.types import TypeDecorator, CHAR

from portal.models.base import Base


class GUID(TypeDecorator):
    """Platform-independent GUID type.

    Uses CHAR(36) for SQLite and stores as string.
    """

    impl = CHAR
    cache_ok = True

    def load_dialect_impl(self, dialect):
        return dialect.type_descriptor(CHAR(36))

    def process_bind_param(self, value, dialect):
        if value is not None:
            if isinstance(value, uuid.UUID):
                return str(value)
            return str(value)
        return value

    def process_result_value(self, value, dialect):
        if value is not None:
            return uuid.UUID(value)
        return value


class JobStatus(str, Enum):
    """Benchmark job status."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class JobType(str, Enum):
    """Benchmark job type."""

    ON_DEMAND = "on_demand"
    DAILY_BATCH = "daily_batch"


class BenchmarkJob(Base):
    """SQLAlchemy model for benchmark_jobs table."""

    __tablename__ = "benchmark_jobs"

    id = Column(GUID(), primary_key=True, default=uuid.uuid4)

    # Job parameters
    publisher_id = Column(Integer, nullable=True, index=True)
    feed_ids = Column(JSON, nullable=True)  # List of integers stored as JSON
    target_date = Column(Date, nullable=False)
    include_extended_hours = Column(Boolean, default=False, nullable=False)

    # Job lifecycle
    status = Column(String(20), default=JobStatus.PENDING.value, nullable=False)
    requested_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)

    # Results summary
    results_count = Column(Integer, nullable=True)
    pass_count = Column(Integer, nullable=True)
    fail_count = Column(Integer, nullable=True)
    error_count = Column(Integer, nullable=True)

    # Error tracking
    error = Column(Text, nullable=True)

    # Metadata
    job_type = Column(String(20), default=JobType.ON_DEMAND.value, nullable=False)
    requested_by = Column(String(255), nullable=True)

    def __repr__(self) -> str:
        return f"<BenchmarkJob(id={self.id}, publisher={self.publisher_id}, status={self.status})>"

    @property
    def is_complete(self) -> bool:
        """Check if job is in a terminal state."""
        return self.status in (JobStatus.COMPLETED.value, JobStatus.FAILED.value)

    @property
    def duration_seconds(self) -> Optional[float]:
        """Calculate job duration in seconds."""
        if self.started_at and self.completed_at:
            return (self.completed_at - self.started_at).total_seconds()
        return None


# Pydantic Schemas


class BenchmarkJobCreate(BaseModel):
    """Schema for creating a benchmark job."""

    publisher_id: int
    feed_ids: Optional[list[int]] = None
    target_date: Optional[date] = None
    include_extended_hours: bool = False


class BenchmarkJobResponse(BaseModel):
    """Schema for benchmark job API response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    publisher_id: Optional[int] = None
    feed_ids: Optional[list[int]] = None
    target_date: date
    include_extended_hours: bool = False

    # Status
    status: JobStatus
    requested_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Results
    results_count: Optional[int] = None
    pass_count: Optional[int] = None
    fail_count: Optional[int] = None
    error_count: Optional[int] = None
    error: Optional[str] = None

    # Metadata
    job_type: JobType
    requested_by: Optional[str] = None


class BenchmarkJobStatus(BaseModel):
    """Schema for job status check response."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    status: JobStatus
    progress: Optional[int] = Field(None, description="Progress percentage (0-100)")

    # Timing
    requested_at: datetime
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_seconds: Optional[float] = None

    # Results summary (when complete)
    results_count: Optional[int] = None
    pass_count: Optional[int] = None
    fail_count: Optional[int] = None
    error_count: Optional[int] = None
    error: Optional[str] = None


class BenchmarkJobListItem(BaseModel):
    """Schema for job in list responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    publisher_id: Optional[int] = None
    target_date: date
    status: JobStatus
    job_type: JobType
    requested_at: datetime
    completed_at: Optional[datetime] = None
    results_count: Optional[int] = None
