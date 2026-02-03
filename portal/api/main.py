"""
Publisher Performance Portal - FastAPI Application.

This is the main entry point for the REST API.

Run with:
    uvicorn portal.api.main:app --reload
    uvicorn portal.api.main:app --host 0.0.0.0 --port 8000
"""

from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from portal.api.middleware.auth import OptionalApiKeyMiddleware
from portal.api.routers import benchmarks, feeds, leaderboard, publishers
from portal.api.schemas import ErrorResponse, HealthResponse
from portal.config import settings
from portal.db import SessionLocal


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler for startup/shutdown events."""
    # Startup
    print("Starting Publisher Performance Portal API...")
    yield
    # Shutdown
    print("Shutting down Publisher Performance Portal API...")


app = FastAPI(
    title="Publisher Performance Portal",
    description="""
Self-service benchmark monitoring for Pyth Lazer publishers.

## Overview

This API provides access to benchmark results comparing publisher data quality
against Datascope reference data.

## Key Concepts

- **NRMSE**: Normalized Root Mean Square Error - lower is better
- **Hit Rate**: Percentage of prices within 10 basis points - higher is better
- **Pass Criteria**: `nrmse < 0.01` OR `(nrmse < 0.05 AND hit_rate >= 98%)`

## Available Endpoints

- `/publishers` - List and query publishers
- `/feeds` - Feed information and history
- `/leaderboard` - Ranked publisher performance
- `/benchmarks` - On-demand benchmark jobs
    """,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# Static UI (lightweight)
frontend_dir = Path(__file__).parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/ui", StaticFiles(directory=frontend_dir), name="ui")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Optional API key authentication middleware (disabled by default)
app.add_middleware(OptionalApiKeyMiddleware)


# Exception handlers
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Handle uncaught exceptions."""
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            detail=str(exc) if settings.debug else "Internal server error",
            error_code="INTERNAL_ERROR",
        ).model_dump(),
    )


# Include routers
app.include_router(publishers.router)
app.include_router(feeds.router)
app.include_router(leaderboard.router)
app.include_router(benchmarks.router)


# Health and info endpoints
@app.get("/", include_in_schema=False)
async def root():
    """Root endpoint - redirects to docs."""
    return {
        "name": "Publisher Performance Portal",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health",
        "ui": {
            "dashboard": "/ui/dashboard.html",
            "uptime": "/ui/uptime.html",
        },
    }


@app.get("/health", response_model=HealthResponse, tags=["system"])
async def health_check():
    """
    Health check endpoint.

    Returns the current health status of the API and database connection.
    """
    db_status = "connected"

    try:
        # Test database connection
        db = SessionLocal()
        try:
            db.execute(text("SELECT 1"))
        finally:
            db.close()
    except Exception as e:
        db_status = f"error: {str(e)[:50]}"

    return HealthResponse(
        status="healthy" if db_status == "connected" else "degraded",
        timestamp=datetime.utcnow(),
        database=db_status,
        version="1.0.0",
    )


@app.get("/stats", tags=["system"])
async def get_stats():
    """
    Get database statistics.

    Returns counts of publishers, feeds, and results.
    """
    from sqlalchemy import func, select

    from portal.models import BenchmarkResult, Feed, Publisher, PublisherDailySummary

    db = SessionLocal()
    try:
        publisher_count = db.execute(select(func.count(Publisher.publisher_id))).scalar() or 0
        feed_count = db.execute(select(func.count(Feed.feed_id))).scalar() or 0
        result_count = db.execute(select(func.count(BenchmarkResult.id))).scalar() or 0
        summary_count = db.execute(select(func.count(PublisherDailySummary.id))).scalar() or 0

        latest_date = db.execute(
            select(func.max(BenchmarkResult.benchmark_date))
        ).scalar()

        earliest_date = db.execute(
            select(func.min(BenchmarkResult.benchmark_date))
        ).scalar()

        return {
            "publishers": publisher_count,
            "feeds": feed_count,
            "benchmark_results": result_count,
            "daily_summaries": summary_count,
            "date_range": {
                "earliest": str(earliest_date) if earliest_date else None,
                "latest": str(latest_date) if latest_date else None,
            },
        }
    finally:
        db.close()


# Development server
if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "portal.api.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug,
    )
