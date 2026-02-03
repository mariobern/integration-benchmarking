"""
Feed model and schemas.

Represents a price feed in the Pyth Lazer network.
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict
from sqlalchemy import Boolean, Column, DateTime, Integer, String

from portal.models.base import Base


class Feed(Base):
    """SQLAlchemy model for feeds table."""

    __tablename__ = "feeds"

    feed_id = Column(Integer, primary_key=True)
    symbol = Column(String(255), nullable=True)
    asset_class = Column(String(50), nullable=True)
    exponent = Column(Integer, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    first_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_seen_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    def __repr__(self) -> str:
        return f"<Feed(id={self.feed_id}, symbol={self.symbol})>"


# Pydantic Schemas


class FeedBase(BaseModel):
    """Base schema for feed data."""

    feed_id: int
    symbol: Optional[str] = None
    asset_class: Optional[str] = None
    exponent: Optional[int] = None
    is_active: bool = True


class FeedCreate(FeedBase):
    """Schema for creating a feed."""

    pass


class FeedResponse(FeedBase):
    """Schema for feed API response."""

    model_config = ConfigDict(from_attributes=True)

    first_seen_at: datetime
    last_seen_at: datetime
    created_at: datetime
    updated_at: datetime


class FeedListItem(BaseModel):
    """Schema for feed in list responses (minimal fields)."""

    model_config = ConfigDict(from_attributes=True)

    feed_id: int
    symbol: Optional[str] = None
    asset_class: Optional[str] = None
    is_active: bool


class FeedWithLatestResult(FeedListItem):
    """Feed with latest benchmark result."""

    latest_date: Optional[str] = None
    passes: Optional[bool] = None
    nrmse: Optional[float] = None
    hit_rate: Optional[float] = None
    n_observations: Optional[int] = None
    error: Optional[str] = None
