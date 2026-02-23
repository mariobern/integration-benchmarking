"""
Publisher model and schemas.

Represents a data publisher in the Pyth Lazer network.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Boolean, Column, DateTime, Integer, String

from portal.models.base import Base


class Publisher(Base):
    """SQLAlchemy model for publishers table."""

    __tablename__ = "publishers"

    publisher_id = Column(Integer, primary_key=True)
    name = Column(String(255), nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    first_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )

    def __repr__(self) -> str:
        return f"<Publisher(id={self.publisher_id}, name={self.name})>"


# Pydantic Schemas


class PublisherBase(BaseModel):
    """Base schema for publisher data."""

    publisher_id: int
    name: Optional[str] = None
    is_active: bool = True


class PublisherCreate(PublisherBase):
    """Schema for creating a publisher."""

    pass


class PublisherResponse(PublisherBase):
    """Schema for publisher API response."""

    model_config = ConfigDict(from_attributes=True)

    first_seen_at: datetime
    last_seen_at: datetime
    created_at: datetime
    updated_at: datetime


class PublisherListItem(BaseModel):
    """Schema for publisher in list responses (minimal fields)."""

    model_config = ConfigDict(from_attributes=True)

    publisher_id: int
    name: Optional[str] = None
    is_active: bool
    last_seen_at: datetime


class PublisherWithStats(PublisherListItem):
    """Publisher with latest summary statistics."""

    latest_date: Optional[str] = None
    pass_rate_pct: Optional[float] = None
    total_feeds: Optional[int] = None
    median_nrmse: Optional[float] = None
    median_hit_rate: Optional[float] = None
