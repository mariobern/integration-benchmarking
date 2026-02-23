"""
Tests for the uptime summary computation module.
"""

from datetime import date, timedelta

import pytest

from portal.batch.uptime_summary import (
    compute_daily_uptime_summary,
    link_uptime_to_benchmark_summary,
)


class TestComputeDailyUptimeSummary:
    """Tests for compute_daily_uptime_summary function."""

    def test_no_records(self, db_session, sample_publisher):
        """Test with no uptime records."""
        target_date = date.today() - timedelta(days=1)

        result = compute_daily_uptime_summary(
            db_session,
            sample_publisher.publisher_id,
            target_date,
        )

        assert result is None

    def test_single_session(self, db_session, sample_publisher, sample_uptime_record):
        """Test with single session uptime record."""
        result = compute_daily_uptime_summary(
            db_session,
            sample_publisher.publisher_id,
            sample_uptime_record.uptime_date,
        )

        assert result is not None
        assert result["publisher_id"] == sample_publisher.publisher_id
        assert result["regular_median_uptime_pct"] == 99.95
        assert result["regular_total_feeds"] == 1
        assert result["overall_median_uptime_pct"] == 99.95

    def test_multiple_sessions(self, db_session, sample_publisher, sample_feed):
        """Test with multiple session uptime records."""
        from portal.models import PublisherFeedDailyUptime

        target_date = date.today() - timedelta(days=1)

        # Create multiple session records
        sessions = [
            ("regular", 99.95),
            ("premarket", 99.50),
            ("afterhours", 99.80),
        ]

        for session, uptime_pct in sessions:
            record = PublisherFeedDailyUptime(
                publisher_id=sample_publisher.publisher_id,
                feed_id=sample_feed.feed_id,
                uptime_date=target_date,
                asset_class=sample_feed.asset_class,
                session=session,
                uptime_pct=uptime_pct,
                downtime_ms=1000,
                period_length_ms=100000,
            )
            db_session.add(record)
        db_session.commit()

        result = compute_daily_uptime_summary(
            db_session,
            sample_publisher.publisher_id,
            target_date,
        )

        assert result is not None
        assert result["regular_median_uptime_pct"] == 99.95
        assert result["premarket_median_uptime_pct"] == 99.50
        assert result["afterhours_median_uptime_pct"] == 99.80
        assert result["total_feeds"] == 3

    def test_asset_class_breakdown(self, db_session, sample_publisher):
        """Test asset class breakdown in summary."""
        from portal.models import PublisherFeedDailyUptime

        target_date = date.today() - timedelta(days=1)

        # Create records for different asset classes
        asset_classes = [
            (327, "fx", 99.95),
            (1163, "us-equities", 99.80),
            (346, "metals", 99.90),
        ]

        for feed_id, asset_class, uptime_pct in asset_classes:
            record = PublisherFeedDailyUptime(
                publisher_id=sample_publisher.publisher_id,
                feed_id=feed_id,
                uptime_date=target_date,
                asset_class=asset_class,
                session="regular",
                uptime_pct=uptime_pct,
                downtime_ms=1000,
                period_length_ms=100000,
            )
            db_session.add(record)
        db_session.commit()

        result = compute_daily_uptime_summary(
            db_session,
            sample_publisher.publisher_id,
            target_date,
        )

        assert result is not None
        assert "asset_class_uptime" in result
        assert "fx" in result["asset_class_uptime"]
        assert "us-equities" in result["asset_class_uptime"]
        assert "metals" in result["asset_class_uptime"]
        assert result["asset_class_uptime"]["fx"]["median_uptime_pct"] == 99.95

    def test_upsert_behavior(self, db_session, sample_publisher, sample_uptime_record):
        """Test that summary is upserted correctly."""
        from portal.models import PublisherDailyUptimeSummary

        target_date = sample_uptime_record.uptime_date

        # First computation
        result1 = compute_daily_uptime_summary(
            db_session,
            sample_publisher.publisher_id,
            target_date,
        )

        # Verify record was created
        summary = (
            db_session.query(PublisherDailyUptimeSummary)
            .filter(
                PublisherDailyUptimeSummary.publisher_id
                == sample_publisher.publisher_id,
                PublisherDailyUptimeSummary.summary_date == target_date,
            )
            .first()
        )
        assert summary is not None
        original_id = summary.id

        # Second computation should update, not create new
        result2 = compute_daily_uptime_summary(
            db_session,
            sample_publisher.publisher_id,
            target_date,
        )

        # Should still be only one record
        count = (
            db_session.query(PublisherDailyUptimeSummary)
            .filter(
                PublisherDailyUptimeSummary.publisher_id
                == sample_publisher.publisher_id,
                PublisherDailyUptimeSummary.summary_date == target_date,
            )
            .count()
        )
        assert count == 1


class TestLinkUptimeToBenchmarkSummary:
    """Tests for link_uptime_to_benchmark_summary function."""

    def test_no_uptime_summary(
        self, db_session, sample_publisher, sample_daily_summary
    ):
        """Test when no uptime summary exists."""
        # Should not raise error
        link_uptime_to_benchmark_summary(
            db_session,
            sample_publisher.publisher_id,
            sample_daily_summary.summary_date,
        )

        # Benchmark summary should be unchanged
        db_session.refresh(sample_daily_summary)
        assert sample_daily_summary.overall_median_uptime_pct is None

    def test_no_benchmark_summary(
        self, db_session, sample_publisher, sample_uptime_summary
    ):
        """Test when no benchmark summary exists."""
        # Should not raise error
        link_uptime_to_benchmark_summary(
            db_session,
            sample_publisher.publisher_id,
            sample_uptime_summary.summary_date,
        )

    def test_link_successful(
        self, db_session, sample_publisher, sample_daily_summary, sample_uptime_summary
    ):
        """Test successful linking of uptime to benchmark summary."""
        # Ensure both summaries are for the same date
        sample_uptime_summary.summary_date = sample_daily_summary.summary_date
        db_session.commit()

        link_uptime_to_benchmark_summary(
            db_session,
            sample_publisher.publisher_id,
            sample_daily_summary.summary_date,
        )

        # Verify benchmark summary was updated
        db_session.refresh(sample_daily_summary)
        assert float(sample_daily_summary.overall_median_uptime_pct) == 99.90
        assert float(sample_daily_summary.regular_median_uptime_pct) == 99.95
