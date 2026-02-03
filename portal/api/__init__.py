"""
FastAPI application module for Publisher Performance Portal.

This module provides the REST API for accessing benchmark results.
"""

from portal.api.dependencies import (
    AssetFilter,
    DateRange,
    DbSession,
    Pagination,
)
from portal.api.schemas import (
    AssetClassBreakdown,
    ErrorResponse,
    HealthResponse,
    MetricsSummary,
    PaginatedResponse,
    TrendData,
    TrendPoint,
)

__all__ = [
    # Dependencies
    "DbSession",
    "Pagination",
    "DateRange",
    "AssetFilter",
    # Schemas
    "PaginatedResponse",
    "HealthResponse",
    "ErrorResponse",
    "MetricsSummary",
    "TrendData",
    "TrendPoint",
    "AssetClassBreakdown",
]
