"""
FastAPI dependencies for the Publisher Performance Portal.

Provides dependency injection for database sessions, pagination, and common parameters.
"""

from datetime import date, timedelta
from typing import Annotated, Optional

from fastapi import Depends, Query
from sqlalchemy.orm import Session

from portal.db import get_db


# Type alias for database session dependency
DbSession = Annotated[Session, Depends(get_db)]


class PaginationParams:
    """Common pagination parameters."""

    def __init__(
        self,
        skip: int = Query(0, ge=0, description="Number of records to skip"),
        limit: int = Query(50, ge=1, le=100, description="Maximum records to return"),
    ):
        self.skip = skip
        self.limit = limit


class DateRangeParams:
    """Common date range parameters."""

    def __init__(
        self,
        start_date: Optional[date] = Query(None, description="Start date (inclusive)"),
        end_date: Optional[date] = Query(None, description="End date (inclusive)"),
    ):
        self.start_date = start_date
        self.end_date = end_date

        # Default to last 30 days if no dates provided
        if self.start_date is None and self.end_date is None:
            self.end_date = date.today()
            self.start_date = self.end_date - timedelta(days=30)


class AssetClassFilter:
    """Asset class filter parameter."""

    def __init__(
        self,
        asset_class: Optional[str] = Query(
            None,
            description="Filter by asset class (fx, metals, us-equities, commodity, us-treasuries)",
        ),
    ):
        self.asset_class = asset_class


# Dependency type aliases
Pagination = Annotated[PaginationParams, Depends()]
DateRange = Annotated[DateRangeParams, Depends()]
AssetFilter = Annotated[AssetClassFilter, Depends()]
