"""Tests for publisher 0 (aggregate feed) in merge_results()."""

from lib.models import (
    BenchmarkResult,
    FeedUptimeResult,
    PublisherFeedMetrics,
    PublisherSessionUptime,
)
from lib.readiness_core import merge_results


def _make_publisher_session_uptime(
    publisher_id: int,
    session: str = "regular",
    uptime_pct: float = 99.97,
    passes: bool = True,
) -> PublisherSessionUptime:
    """Build a PublisherSessionUptime with sensible defaults for testing."""
    return PublisherSessionUptime(
        publisher_id=publisher_id,
        session=session,
        uptime_pct=uptime_pct,
        passes=passes,
        seconds_with_data=23400,
        total_seconds=23400,
        updates_total=46800,
        updates_per_second=2.0,
        downtime_ms=0 if passes else 50000,
        period_length_ms=23400000,
        max_gap_ms=100 if passes else 60000,
        gaps_over_threshold=0 if passes else 5,
    )


def _make_benchmark_result(include_pub0=True):
    """Build a BenchmarkResult with publishers 0, 10, 20."""
    pub0_detail = PublisherFeedMetrics(
        publisher_id=0,
        n_observations=23400,
        passes=True,
        nrmse=0.008,
        hit_rate=96.5,
        rmse=0.01,
        mean_spread=0.02,
    )
    pub10_detail = PublisherFeedMetrics(
        publisher_id=10,
        n_observations=23400,
        passes=True,
        nrmse=0.009,
        hit_rate=95.0,
        rmse=0.012,
        mean_spread=0.02,
    )
    pub20_detail = PublisherFeedMetrics(
        publisher_id=20,
        n_observations=23400,
        passes=False,
        nrmse=0.06,
        hit_rate=80.0,
        rmse=0.05,
        mean_spread=0.02,
    )
    details = [pub10_detail, pub20_detail]
    if include_pub0:
        details.insert(0, pub0_detail)
    return BenchmarkResult(
        feed_id=100,
        date="2026-03-05",
        mode="us-equities",
        symbol="Equity.US.TEST/USD",
        ready=True,
        target_pub_count=1,
        passing_pub_count=1,
        failing_pub_count=1,
        passing_publishers=[10],
        failing_publishers=[20],
        publisher_details=details,
        agg_metrics=pub0_detail if include_pub0 else None,
    )


def _make_uptime_result():
    """Build a FeedUptimeResult with publishers 10 and 20."""
    return FeedUptimeResult(
        feed_id=100,
        date="2026-03-05",
        mode="us-equities",
        symbol="Equity.US.TEST/USD",
        publisher_count=2,
        publisher_uptimes=[
            _make_publisher_session_uptime(
                publisher_id=10,
                session="regular",
                uptime_pct=99.97,
                passes=True,
            ),
            _make_publisher_session_uptime(
                publisher_id=20,
                session="regular",
                uptime_pct=50.0,
                passes=False,
            ),
        ],
        error=None,
        execution_time_ms=0,
    )


class TestPublisher0InMergeResults:
    """Publisher 0 should appear in details but not in readiness counts."""

    def test_pub0_appears_in_publisher_details(self):
        result = merge_results(
            _make_benchmark_result(),
            _make_uptime_result(),
            target_pub_count=1,
            include_detailed=True,
        )
        pub_ids = [d.publisher_id for d in result.publisher_details]
        assert 0 in pub_ids

    def test_pub0_has_benchmark_metrics(self):
        result = merge_results(
            _make_benchmark_result(),
            _make_uptime_result(),
            target_pub_count=1,
            include_detailed=True,
        )
        pub0 = next(d for d in result.publisher_details if d.publisher_id == 0)
        assert pub0.benchmark_nrmse == 0.008
        assert pub0.benchmark_hit_rate == 96.5
        assert pub0.benchmark_n_observations == 23400
        assert pub0.benchmark_passes is True

    def test_pub0_has_no_uptime(self):
        result = merge_results(
            _make_benchmark_result(),
            _make_uptime_result(),
            target_pub_count=1,
            include_detailed=True,
        )
        pub0 = next(d for d in result.publisher_details if d.publisher_id == 0)
        assert pub0.uptime_pct is None
        assert pub0.uptime_passes is False
        assert pub0.fully_passes is False

    def test_pub0_excluded_from_readiness_counts(self):
        result = merge_results(
            _make_benchmark_result(),
            _make_uptime_result(),
            target_pub_count=1,
            include_detailed=True,
        )
        assert 0 not in result.fully_passing_publishers
        assert 0 not in result.benchmark_only_publishers
        assert 0 not in result.uptime_only_publishers
        assert 0 not in result.both_failing_publishers

    def test_pub0_excluded_from_total_publisher_count(self):
        result = merge_results(
            _make_benchmark_result(),
            _make_uptime_result(),
            target_pub_count=1,
            include_detailed=True,
        )
        # Only publishers 10 and 20 should be counted
        assert result.total_publisher_count == 2

    def test_pub0_sorts_first_in_details(self):
        result = merge_results(
            _make_benchmark_result(),
            _make_uptime_result(),
            target_pub_count=1,
            include_detailed=True,
        )
        # Details are appended in sorted order (0, 10, 20)
        assert result.publisher_details[0].publisher_id == 0

    def test_without_pub0_counts_unchanged(self):
        result = merge_results(
            _make_benchmark_result(include_pub0=False),
            _make_uptime_result(),
            target_pub_count=1,
            include_detailed=True,
        )
        assert result.total_publisher_count == 2
        pub_ids = [d.publisher_id for d in result.publisher_details]
        assert 0 not in pub_ids
