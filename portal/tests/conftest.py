"""
Pytest fixtures for portal tests.
"""

import os
from datetime import date, datetime, timedelta, timezone
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

# Import all models to register them with Base.metadata
from portal.models import Base


# Use in-memory SQLite for tests with shared connection pool
# StaticPool ensures all connections use the same underlying connection
TEST_DATABASE_URL = "sqlite:///:memory:"


@pytest.fixture(scope="session")
def engine():
    """Create a test database engine with shared connection pool."""
    engine = create_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return engine


@pytest.fixture(scope="function")
def db_session(engine) -> Generator[Session, None, None]:
    """Create a test database session."""
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = TestingSessionLocal()

    # Clean up tables before each test
    for table in reversed(Base.metadata.sorted_tables):
        session.execute(table.delete())
    session.commit()

    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture(scope="function")
def client(db_session) -> Generator[TestClient, None, None]:
    """Create a test client with database override."""
    from portal.api.main import app
    from portal.db import get_db

    def override_get_db():
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def _utcnow():
    """Get current UTC time in a timezone-aware manner."""
    return datetime.now(timezone.utc)


@pytest.fixture
def sample_publisher(db_session):
    """Create a sample publisher."""
    from portal.models import Publisher

    publisher = Publisher(
        publisher_id=55,
        name="Test Publisher 55",
        is_active=True,
        first_seen_at=_utcnow(),
        last_seen_at=_utcnow(),
    )
    db_session.add(publisher)
    db_session.commit()
    return publisher


@pytest.fixture
def sample_feed(db_session):
    """Create a sample feed."""
    from portal.models import Feed

    feed = Feed(
        feed_id=327,
        symbol="EUR/USD",
        asset_class="fx",
        is_active=True,
        first_seen_at=_utcnow(),
        last_seen_at=_utcnow(),
    )
    db_session.add(feed)
    db_session.commit()
    return feed


@pytest.fixture
def sample_benchmark_result(db_session, sample_publisher, sample_feed):
    """Create a sample benchmark result."""
    from portal.models import BenchmarkResult

    result = BenchmarkResult(
        publisher_id=sample_publisher.publisher_id,
        feed_id=sample_feed.feed_id,
        benchmark_date=date.today() - timedelta(days=1),
        symbol=sample_feed.symbol,
        asset_class=sample_feed.asset_class,
        passes=True,
        n_observations=1000,
        nrmse=0.005,
        hit_rate=99.5,
        benchmark_price_range=0.0001,
        rmse=0.00005,
        mean_spread=0.0001,
        rmse_over_spread=0.5,
    )
    db_session.add(result)
    db_session.commit()
    return result


@pytest.fixture
def sample_daily_summary(db_session, sample_publisher):
    """Create a sample daily summary."""
    from portal.models import PublisherDailySummary

    summary = PublisherDailySummary(
        publisher_id=sample_publisher.publisher_id,
        summary_date=date.today() - timedelta(days=1),
        total_feeds=10,
        pass_count=8,
        fail_count=1,
        error_count=1,
        pass_rate_pct=80.0,
        median_nrmse=0.005,
        median_hit_rate=99.0,
    )
    db_session.add(summary)
    db_session.commit()
    return summary


@pytest.fixture
def sample_uptime_record(db_session, sample_publisher, sample_feed):
    """Create a sample uptime record."""
    from portal.models import PublisherFeedDailyUptime

    uptime = PublisherFeedDailyUptime(
        publisher_id=sample_publisher.publisher_id,
        feed_id=sample_feed.feed_id,
        uptime_date=date.today() - timedelta(days=1),
        asset_class=sample_feed.asset_class,
        session="regular",
        uptime_pct=99.95,
        downtime_ms=1800000,
        period_length_ms=36000000,
    )
    db_session.add(uptime)
    db_session.commit()
    return uptime


@pytest.fixture
def sample_uptime_summary(db_session, sample_publisher):
    """Create a sample uptime summary."""
    from portal.models import PublisherDailyUptimeSummary

    summary = PublisherDailyUptimeSummary(
        publisher_id=sample_publisher.publisher_id,
        summary_date=date.today() - timedelta(days=1),
        overall_median_uptime_pct=99.90,
        overall_mean_uptime_pct=99.85,
        regular_median_uptime_pct=99.95,
        regular_mean_uptime_pct=99.90,
        regular_min_uptime_pct=99.50,
        regular_total_feeds=10,
        total_feeds=10,
    )
    db_session.add(summary)
    db_session.commit()
    return summary
