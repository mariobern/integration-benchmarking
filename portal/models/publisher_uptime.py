"""
Publisher feed daily uptime model and schemas.

Stores session-aware uptime metrics per publisher/feed/date.
"""

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import (
    Column,
    Date,
    DateTime,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.sql.sqltypes import BigInteger

from portal.models.base import Base


class PublisherFeedDailyUptime(Base):
    """SQLAlchemy model for publisher_feed_daily_uptime table."""

    __tablename__ = "publisher_feed_daily_uptime"
    __table_args__ = (
        UniqueConstraint(
            "publisher_id",
            "feed_id",
            "uptime_date",
            "session",
            name="uq_uptime_publisher_feed_date_session",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Identifiers
    publisher_id = Column(Integer, nullable=False, index=True)
    feed_id = Column(Integer, nullable=False, index=True)
    uptime_date = Column(Date, nullable=False, index=True)
    asset_class = Column(String(50), nullable=True, index=True)
    session = Column(String(32), nullable=False, index=True)

    # Metrics
    uptime_pct = Column(Numeric(6, 4), nullable=False)
    downtime_ms = Column(BigInteger, nullable=False)
    period_length_ms = Column(BigInteger, nullable=False)

    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return (
            f"<PublisherFeedDailyUptime(pub={self.publisher_id}, feed={self.feed_id}, "
            f"date={self.uptime_date}, session={self.session}, uptime={self.uptime_pct})>"
        )


class PublisherFeedUptimeBase(BaseModel):
    """Base schema for publisher feed uptime."""

    publisher_id: int
    feed_id: int
    uptime_date: date
    asset_class: Optional[str] = None
    session: str
    uptime_pct: float
    downtime_ms: int
    period_length_ms: int


class PublisherFeedUptimeResponse(PublisherFeedUptimeBase):
    """Schema for uptime API response."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    created_at: datetime
