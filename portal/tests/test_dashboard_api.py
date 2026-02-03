"""
Tests for the dashboard API endpoints.
"""

from datetime import date, timedelta

import pytest


class TestHealthEndpoint:
    """Tests for the health check endpoint."""

    def test_health_check(self, client):
        """Test the health check endpoint returns OK."""
        response = client.get("/health")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] in ("healthy", "degraded")
        assert "version" in data


class TestPublisherDashboard:
    """Tests for the publisher dashboard endpoint."""

    def test_dashboard_publisher_not_found(self, client):
        """Test dashboard returns 404 for non-existent publisher."""
        response = client.get("/publishers/99999/dashboard")
        assert response.status_code == 404

    def test_dashboard_no_data(self, client, sample_publisher):
        """Test dashboard with publisher but no data."""
        response = client.get(f"/publishers/{sample_publisher.publisher_id}/dashboard")
        assert response.status_code == 200

        data = response.json()
        assert data["publisher_id"] == sample_publisher.publisher_id
        assert data["latest_date"] is None
        assert data["benchmark"]["total_feeds"] == 0

    def test_dashboard_with_data(
        self, client, sample_publisher, sample_daily_summary, sample_uptime_summary
    ):
        """Test dashboard with benchmark and uptime data."""
        response = client.get(f"/publishers/{sample_publisher.publisher_id}/dashboard")
        assert response.status_code == 200

        data = response.json()
        assert data["publisher_id"] == sample_publisher.publisher_id
        assert data["publisher_name"] == sample_publisher.name

        # Benchmark metrics
        assert data["benchmark"]["pass_rate_pct"] == 80.0
        assert data["benchmark"]["total_feeds"] == 10

        # Uptime metrics
        assert data["uptime"]["overall_median_uptime_pct"] == 99.90

    def test_dashboard_with_specific_date(
        self, client, sample_publisher, sample_daily_summary
    ):
        """Test dashboard with specific date parameter."""
        target_date = sample_daily_summary.summary_date

        response = client.get(
            f"/publishers/{sample_publisher.publisher_id}/dashboard",
            params={"target_date": str(target_date)},
        )
        assert response.status_code == 200

        data = response.json()
        assert data["latest_date"] == str(target_date)


class TestBenchmarkTrend:
    """Tests for the benchmark trend endpoint."""

    def test_trend_no_data(self, client, sample_publisher):
        """Test trend returns empty list when no data."""
        response = client.get(
            "/benchmarks/trend/benchmark",
            params={"publisher_id": sample_publisher.publisher_id, "days": 30},
        )
        assert response.status_code == 200
        assert response.json() == []

    def test_trend_with_data(self, client, sample_publisher, sample_daily_summary):
        """Test trend returns data points."""
        response = client.get(
            "/benchmarks/trend/benchmark",
            params={
                "publisher_id": sample_publisher.publisher_id,
                "days": 30,
                "metric": "pass_rate_pct",
            },
        )
        assert response.status_code == 200

        data = response.json()
        assert len(data) == 1
        assert data[0]["value"] == 80.0

    def test_trend_invalid_metric(self, client, sample_publisher):
        """Test trend returns error for invalid metric."""
        response = client.get(
            "/benchmarks/trend/benchmark",
            params={
                "publisher_id": sample_publisher.publisher_id,
                "metric": "invalid_metric",
            },
        )
        assert response.status_code == 400


class TestUptimeTrend:
    """Tests for the uptime trend endpoint."""

    def test_uptime_trend_no_data(self, client, sample_publisher):
        """Test uptime trend returns empty list when no data."""
        response = client.get(
            "/benchmarks/trend/uptime",
            params={"publisher_id": sample_publisher.publisher_id, "days": 30},
        )
        assert response.status_code == 200
        assert response.json() == []

    def test_uptime_trend_with_data(
        self, client, sample_publisher, sample_uptime_summary
    ):
        """Test uptime trend returns data points."""
        response = client.get(
            "/benchmarks/trend/uptime",
            params={
                "publisher_id": sample_publisher.publisher_id,
                "days": 30,
                "session": "regular",
            },
        )
        assert response.status_code == 200

        data = response.json()
        assert len(data) == 1
        assert data[0]["session"] == "regular"
        assert data[0]["value"] == 99.95

    def test_uptime_trend_invalid_session(self, client, sample_publisher):
        """Test uptime trend returns error for invalid session."""
        response = client.get(
            "/benchmarks/trend/uptime",
            params={
                "publisher_id": sample_publisher.publisher_id,
                "session": "invalid_session",
            },
        )
        assert response.status_code == 400


class TestPublisherFeeds:
    """Tests for the publisher feeds endpoint."""

    def test_feeds_publisher_not_found(self, client):
        """Test feeds returns 404 for non-existent publisher."""
        response = client.get("/publishers/99999/feeds")
        assert response.status_code == 404

    def test_feeds_no_data(self, client, sample_publisher):
        """Test feeds returns empty response when no data."""
        response = client.get(f"/publishers/{sample_publisher.publisher_id}/feeds")
        assert response.status_code == 200

        data = response.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_feeds_with_data(
        self, client, sample_publisher, sample_feed, sample_benchmark_result
    ):
        """Test feeds returns benchmark results."""
        response = client.get(
            f"/publishers/{sample_publisher.publisher_id}/feeds",
            params={"target_date": str(sample_benchmark_result.benchmark_date)},
        )
        assert response.status_code == 200

        data = response.json()
        assert data["total"] == 1
        assert len(data["items"]) == 1
        assert data["items"][0]["feed_id"] == sample_feed.feed_id
        assert data["items"][0]["passes"] is True


class TestUptimeEndpoints:
    """Tests for the uptime endpoints."""

    def test_uptime_list(self, client, sample_publisher, sample_uptime_record):
        """Test uptime list endpoint."""
        response = client.get(
            "/benchmarks/uptime",
            params={
                "publisher_id": sample_publisher.publisher_id,
                "target_date": str(sample_uptime_record.uptime_date),
            },
        )
        assert response.status_code == 200

        data = response.json()
        assert len(data) == 1
        assert data[0]["uptime_pct"] == 99.95

    def test_uptime_summary(self, client, sample_publisher, sample_uptime_record):
        """Test uptime summary endpoint."""
        response = client.get(
            "/benchmarks/uptime/summary",
            params={
                "publisher_id": sample_publisher.publisher_id,
                "target_date": str(sample_uptime_record.uptime_date),
            },
        )
        assert response.status_code == 200

        data = response.json()
        assert len(data) == 1
        assert data[0]["session"] == "regular"


class TestPublisherList:
    """Tests for the publisher list endpoint."""

    def test_list_publishers(self, client, sample_publisher, sample_daily_summary):
        """Test listing publishers with stats."""
        response = client.get("/publishers/")
        assert response.status_code == 200

        data = response.json()
        assert len(data) == 1
        assert data[0]["publisher_id"] == sample_publisher.publisher_id
        assert data[0]["pass_rate_pct"] == 80.0

    def test_list_publishers_empty(self, client):
        """Test listing publishers when none exist."""
        response = client.get("/publishers/")
        assert response.status_code == 200
        assert response.json() == []


class TestAlerts:
    """Tests for the alerts in dashboard."""

    def test_dashboard_alerts_failing_feeds(
        self, client, db_session, sample_publisher, sample_feed
    ):
        """Test that failing feeds appear in alerts."""
        from portal.models import BenchmarkResult, PublisherDailySummary

        target_date = date.today() - timedelta(days=1)

        # Create a failing result
        failing_result = BenchmarkResult(
            publisher_id=sample_publisher.publisher_id,
            feed_id=sample_feed.feed_id,
            benchmark_date=target_date,
            symbol="EUR/USD",
            asset_class="fx",
            passes=False,
            n_observations=1000,
            nrmse=0.08,  # Failing NRMSE
            hit_rate=95.0,
        )
        db_session.add(failing_result)

        # Create summary
        summary = PublisherDailySummary(
            publisher_id=sample_publisher.publisher_id,
            summary_date=target_date,
            total_feeds=1,
            pass_count=0,
            fail_count=1,
            error_count=0,
            pass_rate_pct=0.0,
        )
        db_session.add(summary)
        db_session.commit()

        response = client.get(
            f"/publishers/{sample_publisher.publisher_id}/dashboard",
            params={"target_date": str(target_date)},
        )
        assert response.status_code == 200

        data = response.json()
        assert data["alerts"]["failing_feeds_count"] == 1
        assert len(data["alerts"]["top_issues"]) > 0
