#!/usr/bin/env python3
"""
Test script for the Publisher Performance Portal API.

This script:
1. Creates an in-memory SQLite database with test data
2. Starts the FastAPI server
3. Provides instructions for testing

Usage:
    python portal/test_api.py

Then visit: http://localhost:8000/docs
"""

import sys
from datetime import date, datetime, timedelta
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

# Override database URL BEFORE importing anything else
import os

os.environ["DATABASE_URL"] = "sqlite:///./test_benchmark.db"

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from portal.models.base import Base
from portal.models import (
    Publisher,
    Feed,
    BenchmarkResult,
    PublisherDailySummary,
)


def create_test_database():
    """Create SQLite database with test data."""
    print("Creating test database...")

    # Create engine with SQLite
    engine = create_engine(
        "sqlite:///./test_benchmark.db",
        connect_args={"check_same_thread": False},
        echo=False,
    )

    # Enable foreign keys for SQLite
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    # Create all tables
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    Session = sessionmaker(bind=engine)
    session = Session()

    try:
        # Create test publishers
        publishers = [
            Publisher(publisher_id=11, name="Acme Data Co", is_active=True),
            Publisher(publisher_id=32, name="Global Markets Inc", is_active=True),
            Publisher(publisher_id=55, name="Prime Feeds Ltd", is_active=True),
            Publisher(publisher_id=99, name="DataStream Pro", is_active=True),
        ]
        for p in publishers:
            session.add(p)

        # Create test feeds
        feeds = [
            Feed(feed_id=100, symbol="EUR/USD", asset_class="fx", exponent=-8),
            Feed(feed_id=101, symbol="GBP/USD", asset_class="fx", exponent=-8),
            Feed(feed_id=200, symbol="XAU/USD", asset_class="metals", exponent=-8),
            Feed(feed_id=300, symbol="AAPL", asset_class="us-equities", exponent=-8),
            Feed(feed_id=301, symbol="MSFT", asset_class="us-equities", exponent=-8),
            Feed(feed_id=302, symbol="GOOGL", asset_class="us-equities", exponent=-8),
        ]
        for f in feeds:
            session.add(f)

        # Create test benchmark results for last 7 days
        today = date.today()

        for days_ago in range(7):
            benchmark_date = today - timedelta(days=days_ago + 1)

            for pub in publishers:
                for feed in feeds:
                    # Generate semi-random but realistic results
                    import random

                    random.seed(pub.publisher_id * 1000 + feed.feed_id + days_ago)

                    base_nrmse = 0.002 + (pub.publisher_id % 10) * 0.001
                    nrmse = base_nrmse + random.uniform(-0.001, 0.003)
                    hit_rate = (
                        99.5 - (pub.publisher_id % 10) * 0.3 + random.uniform(-0.5, 0.5)
                    )

                    passes = nrmse < 0.01 or (nrmse < 0.05 and hit_rate >= 98)

                    result = BenchmarkResult(
                        publisher_id=pub.publisher_id,
                        feed_id=feed.feed_id,
                        benchmark_date=benchmark_date,
                        asset_class=feed.asset_class,
                        symbol=feed.symbol,
                        passes=passes,
                        n_observations=random.randint(5000, 20000),
                        nrmse=nrmse,
                        hit_rate=hit_rate,
                        benchmark_price_range=random.uniform(0.5, 5.0),
                        rmse=nrmse * random.uniform(0.8, 1.2),
                        mean_spread=random.uniform(0.0001, 0.001),
                        rmse_over_spread=random.uniform(0.3, 1.5),
                        mean_diff=random.uniform(-0.0001, 0.0001),
                        std_diff=random.uniform(0.0001, 0.001),
                        mae=random.uniform(0.0001, 0.0005),
                        execution_time_ms=random.randint(100, 500),
                    )
                    session.add(result)

            # Create daily summaries
            for pub in publishers:
                pub_results = [
                    r
                    for r in session.query(BenchmarkResult)
                    .filter(
                        BenchmarkResult.publisher_id == pub.publisher_id,
                        BenchmarkResult.benchmark_date == benchmark_date,
                    )
                    .all()
                ]

                if pub_results:
                    pass_count = sum(1 for r in pub_results if r.passes)
                    total = len(pub_results)

                    nrmse_values = [float(r.nrmse) for r in pub_results if r.nrmse]
                    hit_rate_values = [
                        float(r.hit_rate) for r in pub_results if r.hit_rate
                    ]

                    summary = PublisherDailySummary(
                        publisher_id=pub.publisher_id,
                        summary_date=benchmark_date,
                        total_feeds=total,
                        pass_count=pass_count,
                        fail_count=total - pass_count,
                        error_count=0,
                        pass_rate_pct=(pass_count / total * 100) if total > 0 else 0,
                        median_nrmse=sorted(nrmse_values)[len(nrmse_values) // 2]
                        if nrmse_values
                        else None,
                        mean_nrmse=sum(nrmse_values) / len(nrmse_values)
                        if nrmse_values
                        else None,
                        median_hit_rate=sorted(hit_rate_values)[
                            len(hit_rate_values) // 2
                        ]
                        if hit_rate_values
                        else None,
                        mean_hit_rate=sum(hit_rate_values) / len(hit_rate_values)
                        if hit_rate_values
                        else None,
                        total_observations=sum(r.n_observations for r in pub_results),
                        asset_class_breakdown={
                            "fx": {"pass": 2, "fail": 0, "error": 0},
                            "metals": {"pass": 1, "fail": 0, "error": 0},
                            "us-equities": {"pass": 2, "fail": 1, "error": 0},
                        },
                    )
                    session.add(summary)

        session.commit()
        print(f"Created {len(publishers)} publishers")
        print(f"Created {len(feeds)} feeds")
        print(f"Created {7 * len(publishers) * len(feeds)} benchmark results")
        print(f"Created {7 * len(publishers)} daily summaries")

    finally:
        session.close()

    return engine


def patch_database_session(engine):
    """Patch the database session to use our test database."""
    from sqlalchemy.orm import sessionmaker

    TestSession = sessionmaker(bind=engine)

    # Patch the get_db dependency
    import portal.db.session as db_module
    import portal.api.dependencies as dep_module

    def get_test_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    # Override the session factory
    db_module.SessionLocal = TestSession
    db_module.engine = engine


def main():
    """Main entry point."""
    print("=" * 60)
    print("Publisher Performance Portal - API Test Server")
    print("=" * 60)
    print()

    # Create test database
    engine = create_test_database()
    patch_database_session(engine)

    print()
    print("Starting API server...")
    print()
    print("=" * 60)
    print("API is running at: http://localhost:8000")
    print("=" * 60)
    print()
    print("Try these endpoints:")
    print()
    print("  Interactive docs:  http://localhost:8000/docs")
    print("  Health check:      http://localhost:8000/health")
    print("  Stats:             http://localhost:8000/stats")
    print("  Publishers:        http://localhost:8000/publishers/")
    print("  Leaderboard:       http://localhost:8000/leaderboard/")
    print("  Feeds:             http://localhost:8000/feeds/")
    print()
    print("Example curl commands:")
    print()
    print("  curl http://localhost:8000/health")
    print("  curl http://localhost:8000/publishers/")
    print("  curl http://localhost:8000/publishers/55/summary")
    print("  curl http://localhost:8000/leaderboard/")
    print('  curl "http://localhost:8000/publishers/55/feeds?passes=false"')
    print()
    print("Press Ctrl+C to stop the server")
    print("=" * 60)
    print()

    # Import and run the app
    import uvicorn
    from portal.api.main import app

    uvicorn.run(app, host="127.0.0.1", port=8000, log_level="info")


if __name__ == "__main__":
    main()
