"""Tests for feed_readiness.py -- publisher consistency & classifications."""
import csv
import io
from typing import Optional

import pytest

from feed_readiness import (
    FeedReadinessResult,
    PublisherReadinessDetail,
    compute_publisher_consistency,
    write_publisher_consistency_csv,
    print_publisher_consistency,
    _regular_status,
    _premarket_status,
    _afterhours_status,
    _overnight_status,
)


def make_detail(
    publisher_id: int,
    fully_passes: bool = False,
    benchmark_passes: bool = False,
    uptime_passes: bool = False,
    benchmark_error: Optional[str] = None,
    uptime_error: Optional[str] = None,
    premarket_benchmark_passes: Optional[bool] = None,
    premarket_uptime_passes: Optional[bool] = None,
    premarket_uptime_pct: Optional[float] = None,
    afterhours_benchmark_passes: Optional[bool] = None,
    afterhours_uptime_passes: Optional[bool] = None,
    afterhours_uptime_pct: Optional[float] = None,
    overnight_benchmark_passes: Optional[bool] = None,
    overnight_uptime_passes: Optional[bool] = None,
    overnight_uptime_pct: Optional[float] = None,
) -> PublisherReadinessDetail:
    return PublisherReadinessDetail(
        publisher_id=publisher_id,
        benchmark_passes=benchmark_passes,
        benchmark_nrmse=0.01 if benchmark_passes else None,
        benchmark_hit_rate=98.0 if benchmark_passes else None,
        benchmark_n_observations=100,
        benchmark_error=benchmark_error,
        uptime_passes=uptime_passes,
        uptime_pct=99.0 if uptime_passes else 50.0,
        uptime_error=uptime_error,
        fully_passes=fully_passes,
        premarket_benchmark_passes=premarket_benchmark_passes,
        premarket_uptime_passes=premarket_uptime_passes,
        premarket_uptime_pct=premarket_uptime_pct,
        afterhours_benchmark_passes=afterhours_benchmark_passes,
        afterhours_uptime_passes=afterhours_uptime_passes,
        afterhours_uptime_pct=afterhours_uptime_pct,
        overnight_benchmark_passes=overnight_benchmark_passes,
        overnight_uptime_passes=overnight_uptime_passes,
        overnight_uptime_pct=overnight_uptime_pct,
    )


def make_result(
    feed_id: int,
    date: str,
    details: list[PublisherReadinessDetail],
) -> FeedReadinessResult:
    passing = [d for d in details if d.fully_passes]
    return FeedReadinessResult(
        feed_id=feed_id,
        date=date,
        mode="us-equities",
        symbol="Equity.US.TEST/USD",
        ready=len(passing) >= 4,
        benchmark_ready=len(passing) >= 4,
        uptime_ready=len(passing) >= 4,
        target_pub_count=4,
        fully_passing_count=len(passing),
        benchmark_only_passing_count=0,
        uptime_only_passing_count=0,
        both_failing_count=len(details) - len(passing),
        total_publisher_count=len(details),
        benchmark_passing_count=len(passing),
        benchmark_failing_count=len(details) - len(passing),
        median_nrmse=0.01,
        median_hit_rate=98.0,
        uptime_passing_count=len(passing),
        uptime_failing_count=len(details) - len(passing),
        median_uptime_pct=99.0,
        fully_passing_publishers=[d.publisher_id for d in passing],
        benchmark_only_publishers=[],
        uptime_only_publishers=[],
        both_failing_publishers=[d.publisher_id for d in details if not d.fully_passes],
        publisher_details=details,
    )


# ---------------------------------------------------------------------------
# Session status extractor tests
# ---------------------------------------------------------------------------


class TestRegularStatus:
    def test_pass(self):
        detail = make_detail(publisher_id=1, fully_passes=True, benchmark_passes=True, uptime_passes=True)
        assert _regular_status(detail) == "PASS"

    def test_fail(self):
        detail = make_detail(publisher_id=1, fully_passes=False)
        assert _regular_status(detail) == "FAIL"

    def test_error_benchmark(self):
        detail = make_detail(publisher_id=1, benchmark_error="No data")
        assert _regular_status(detail) == "ERROR"

    def test_error_uptime(self):
        detail = make_detail(publisher_id=1, uptime_error="Timeout")
        assert _regular_status(detail) == "ERROR"


class TestPremarketStatus:
    def test_pass(self):
        detail = make_detail(
            publisher_id=1,
            premarket_benchmark_passes=True,
            premarket_uptime_passes=True,
            premarket_uptime_pct=99.0,
        )
        assert _premarket_status(detail) == "PASS"

    def test_fail_benchmark(self):
        detail = make_detail(
            publisher_id=1,
            premarket_benchmark_passes=False,
            premarket_uptime_passes=True,
            premarket_uptime_pct=99.0,
        )
        assert _premarket_status(detail) == "FAIL"

    def test_fail_uptime(self):
        detail = make_detail(
            publisher_id=1,
            premarket_benchmark_passes=True,
            premarket_uptime_passes=False,
            premarket_uptime_pct=80.0,
        )
        assert _premarket_status(detail) == "FAIL"

    def test_no_data_none_uptime(self):
        detail = make_detail(publisher_id=1, premarket_uptime_pct=None)
        assert _premarket_status(detail) is None

    def test_no_data_zero_uptime(self):
        detail = make_detail(publisher_id=1, premarket_uptime_pct=0.0)
        assert _premarket_status(detail) is None

    def test_error_benchmark_none(self):
        detail = make_detail(
            publisher_id=1,
            premarket_benchmark_passes=None,
            premarket_uptime_passes=True,
            premarket_uptime_pct=99.0,
        )
        assert _premarket_status(detail) == "ERROR"


class TestAfterhoursStatus:
    def test_pass(self):
        detail = make_detail(
            publisher_id=1,
            afterhours_benchmark_passes=True,
            afterhours_uptime_passes=True,
            afterhours_uptime_pct=99.0,
        )
        assert _afterhours_status(detail) == "PASS"

    def test_no_data(self):
        detail = make_detail(publisher_id=1, afterhours_uptime_pct=None)
        assert _afterhours_status(detail) is None

    def test_fail(self):
        detail = make_detail(
            publisher_id=1,
            afterhours_benchmark_passes=False,
            afterhours_uptime_passes=True,
            afterhours_uptime_pct=99.0,
        )
        assert _afterhours_status(detail) == "FAIL"


class TestOvernightStatus:
    def test_pass(self):
        detail = make_detail(
            publisher_id=1,
            overnight_benchmark_passes=True,
            overnight_uptime_passes=True,
            overnight_uptime_pct=99.0,
        )
        assert _overnight_status(detail) == "PASS"

    def test_no_data(self):
        detail = make_detail(publisher_id=1, overnight_uptime_pct=None)
        assert _overnight_status(detail) is None

    def test_error(self):
        detail = make_detail(
            publisher_id=1,
            overnight_benchmark_passes=None,
            overnight_uptime_passes=True,
            overnight_uptime_pct=99.0,
        )
        assert _overnight_status(detail) == "ERROR"
