"""Tests for lib.models — shared dataclasses."""

import pytest

from lib.models import (
    OVERNIGHT_REFERENCE_PUBLISHER_ID,
    BenchmarkResult,
    ExtendedHoursMetrics,
    FeedUptimeResult,
    OvernightMetrics,
    PublisherBenchmarkResult,
    PublisherFeedMetrics,
    PublisherSessionUptime,
    TradingSession,
)


class TestTradingSession:
    def test_values(self):
        assert TradingSession.REGULAR.value == "regular"
        assert TradingSession.PREMARKET.value == "premarket"
        assert TradingSession.AFTERHOURS.value == "afterhours"
        assert TradingSession.OVERNIGHT.value == "overnight"


class TestExtendedHoursMetrics:
    def test_all_fields(self):
        m = ExtendedHoursMetrics(
            session=TradingSession.PREMARKET,
            n_observations=500,
            rmse=0.001,
            mean_spread=0.05,
            rmse_over_spread=0.02,
            nrmse=0.003,
            hit_rate=96.5,
            benchmark_price_range=1.5,
            passes=True,
        )
        assert m.session == TradingSession.PREMARKET
        assert m.n_observations == 500
        assert m.passes is True
        assert m.error is None  # default

    def test_error_default(self):
        m = ExtendedHoursMetrics(
            session=TradingSession.AFTERHOURS,
            n_observations=0,
            rmse=None,
            mean_spread=None,
            rmse_over_spread=None,
            nrmse=None,
            hit_rate=None,
            benchmark_price_range=None,
            passes=False,
        )
        assert m.error is None

    def test_required_fields_enforced(self):
        with pytest.raises(TypeError):
            ExtendedHoursMetrics(session=TradingSession.PREMARKET)


class TestOvernightMetrics:
    def test_default_reference_publisher(self):
        m = OvernightMetrics(
            n_observations=100,
            n_reference_observations=200,
            rmse=0.001,
            mean_spread=0.05,
            rmse_over_spread=0.02,
            nrmse=0.003,
            hit_rate=97.0,
            reference_price_range=2.0,
            passes=True,
        )
        assert m.reference_publisher_id == OVERNIGHT_REFERENCE_PUBLISHER_ID
        assert m.reference_publisher_id == 32
        assert m.error is None

    def test_required_fields_enforced(self):
        with pytest.raises(TypeError):
            OvernightMetrics()


class TestPublisherFeedMetrics:
    def test_required_fields(self):
        m = PublisherFeedMetrics(publisher_id=55, n_observations=1000, passes=True)
        assert m.publisher_id == 55
        assert m.n_observations == 1000
        assert m.passes is True
        assert m.nrmse is None
        assert m.premarket_metrics is None

    def test_required_fields_enforced(self):
        with pytest.raises(TypeError):
            PublisherFeedMetrics(publisher_id=55)


class TestBenchmarkResult:
    def test_required_fields(self):
        r = BenchmarkResult(
            feed_id=327,
            date="2026-01-01",
            mode="fx",
            symbol="EURUSD",
            ready=True,
            target_pub_count=3,
            passing_pub_count=2,
            failing_pub_count=1,
            passing_publishers=[55, 60],
            failing_publishers=[71],
        )
        assert r.feed_id == 327
        assert r.ready is True
        assert r.passing_publishers == [55, 60]
        assert r.median_nrmse is None  # default

    def test_required_fields_enforced(self):
        with pytest.raises(TypeError):
            BenchmarkResult(feed_id=327, date="2026-01-01", mode="fx")


class TestPublisherBenchmarkResult:
    def test_required_fields(self):
        r = PublisherBenchmarkResult(
            publisher_id=55,
            feed_id=327,
            date="2026-01-01",
            mode="fx",
            symbol="EURUSD",
            passes=True,
            n_observations=1000,
            rmse=0.001,
            mean_spread=0.05,
            rmse_over_spread=0.02,
        )
        assert r.publisher_id == 55
        assert r.passes is True
        assert r.nrmse is None  # default

    def test_required_fields_enforced(self):
        with pytest.raises(TypeError):
            PublisherBenchmarkResult(publisher_id=55, feed_id=327)


class TestPublisherSessionUptime:
    def test_frozen(self):
        u = PublisherSessionUptime(
            publisher_id=55,
            session="regular",
            uptime_pct=99.5,
            passes=True,
            seconds_with_data=28800,
            total_seconds=28800,
            updates_total=100000,
            updates_per_second=3.47,
            downtime_ms=0,
            period_length_ms=28800000,
            max_gap_ms=0,
            gaps_over_threshold=0,
        )
        with pytest.raises(AttributeError):
            u.uptime_pct = 50.0


class TestFeedUptimeResult:
    def test_frozen(self):
        uptime = PublisherSessionUptime(
            publisher_id=55,
            session="regular",
            uptime_pct=99.5,
            passes=True,
            seconds_with_data=28800,
            total_seconds=28800,
            updates_total=100000,
            updates_per_second=3.47,
            downtime_ms=0,
            period_length_ms=28800000,
            max_gap_ms=0,
            gaps_over_threshold=0,
        )
        r = FeedUptimeResult(
            feed_id=327,
            date="2026-01-01",
            mode="fx",
            symbol="EURUSD",
            publisher_count=1,
            publisher_uptimes=[uptime],
            error=None,
            execution_time_ms=100,
        )
        assert r.feed_id == 327
        with pytest.raises(AttributeError):
            r.feed_id = 999
