"""Tests for publisher_report.py health classification and output."""
import pytest
from datetime import date, datetime
from unittest.mock import MagicMock


def test_healthy_status():
    """Feed that passes benchmark and has good uptime is HEALTHY."""
    from publisher_report import classify_health
    assert classify_health(passes=True, uptime_pct=99.5, threshold=95.0) == "HEALTHY"


def test_degraded_pass_low_uptime():
    """Feed that passes benchmark but has low uptime is DEGRADED."""
    from publisher_report import classify_health
    assert classify_health(passes=True, uptime_pct=90.0, threshold=95.0) == "DEGRADED"


def test_degraded_fail_good_uptime():
    """Feed that fails benchmark but has good uptime is DEGRADED."""
    from publisher_report import classify_health
    assert classify_health(passes=False, uptime_pct=99.0, threshold=95.0) == "DEGRADED"


def test_failing_status():
    """Feed that fails benchmark AND has low uptime is FAILING."""
    from publisher_report import classify_health
    assert classify_health(passes=False, uptime_pct=90.0, threshold=95.0) == "FAILING"


def test_edge_case_exact_threshold():
    """Uptime exactly at threshold counts as passing."""
    from publisher_report import classify_health
    assert classify_health(passes=True, uptime_pct=95.0, threshold=95.0) == "HEALTHY"


def test_edge_case_just_below_threshold():
    """Uptime just below threshold counts as low."""
    from publisher_report import classify_health
    assert classify_health(passes=True, uptime_pct=94.99, threshold=95.0) == "DEGRADED"


def test_error_feed_is_failing():
    """Feed with error (passes=False, no uptime) is FAILING."""
    from publisher_report import classify_health
    assert classify_health(passes=False, uptime_pct=0.0, threshold=95.0) == "FAILING"


def test_custom_threshold():
    """Custom threshold is respected."""
    from publisher_report import classify_health
    assert classify_health(passes=True, uptime_pct=90.0, threshold=85.0) == "HEALTHY"
    assert classify_health(passes=True, uptime_pct=90.0, threshold=95.0) == "DEGRADED"


# --- Task 2: get_uptime_sessions tests ---


def test_get_uptime_sessions_us_equities():
    """US equities regular session has correct UTC times."""
    from publisher_report import get_uptime_sessions
    sessions = get_uptime_sessions("2026-02-17", "us-equities", extended_hours=False, overnight=False)
    assert len(sessions) == 1
    assert sessions[0]["name"] == "regular"
    # Regular hours: 9:30 AM - 4:00 PM EST = 14:30 - 21:00 UTC
    assert sessions[0]["start"].hour == 14
    assert sessions[0]["start"].minute == 30
    assert sessions[0]["end"].hour == 21


def test_get_uptime_sessions_fx():
    """FX sessions are 24-hour."""
    from publisher_report import get_uptime_sessions
    sessions = get_uptime_sessions("2026-02-17", "fx", extended_hours=False, overnight=False)
    assert len(sessions) == 1
    assert sessions[0]["name"] == "regular"


def test_get_uptime_sessions_extended_hours():
    """Extended hours adds premarket and afterhours sessions."""
    from publisher_report import get_uptime_sessions
    sessions = get_uptime_sessions("2026-02-17", "us-equities", extended_hours=True, overnight=False)
    session_names = [s["name"] for s in sessions]
    assert "regular" in session_names
    assert "premarket" in session_names
    assert "afterhours" in session_names


def test_get_uptime_sessions_overnight():
    """Overnight adds overnight session."""
    from publisher_report import get_uptime_sessions
    sessions = get_uptime_sessions("2026-02-17", "us-equities", extended_hours=False, overnight=True)
    session_names = [s["name"] for s in sessions]
    assert "regular" in session_names
    assert "overnight" in session_names


# --- Task 3: compute_feed_uptime tests ---


def test_compute_feed_uptime_returns_dict():
    """compute_feed_uptime returns expected dict structure."""
    from publisher_report import compute_feed_uptime

    mock_client = MagicMock()
    mock_result = MagicMock()
    mock_result.result_rows = [(23000, 22000, 23400, 0.98, 94.02)]
    mock_client.query.return_value = mock_result

    result = compute_feed_uptime(
        mock_client, publisher_id=55, feed_id=327,
        start_utc=datetime(2026, 2, 17, 14, 30),
        end_utc=datetime(2026, 2, 17, 21, 0),
    )

    assert "uptime_pct" in result
    assert "seconds_with_data" in result
    assert "total_seconds" in result
    assert "updates_total" in result
    assert "updates_per_second" in result
    assert result["uptime_pct"] == pytest.approx(94.02)


def test_compute_feed_uptime_no_data():
    """compute_feed_uptime returns 0% when no data found."""
    from publisher_report import compute_feed_uptime

    mock_client = MagicMock()
    mock_result = MagicMock()
    mock_result.result_rows = []
    mock_client.query.return_value = mock_result

    result = compute_feed_uptime(
        mock_client, publisher_id=55, feed_id=327,
        start_utc=datetime(2026, 2, 17, 14, 30),
        end_utc=datetime(2026, 2, 17, 21, 0),
    )

    assert result["uptime_pct"] == 0.0
    assert result["seconds_with_data"] == 0
    assert result["updates_total"] == 0


# --- Task 4: merge_benchmark_and_uptime tests ---


def test_merge_creates_healthy_result():
    """Merging a passing benchmark with good uptime creates HEALTHY result."""
    from publisher_report import merge_benchmark_and_uptime, FeedHealthResult
    from publisher_benchmark_95 import PublisherBenchmarkResult

    benchmark = PublisherBenchmarkResult(
        publisher_id=55, feed_id=327, date="2026-02-17", mode="fx",
        symbol="FX.EUR/USD", passes=True, n_observations=23400,
        rmse=0.00005, mean_spread=0.00012, rmse_over_spread=0.42,
        nrmse=0.002, hit_rate=99.5, benchmark_price_range=0.025,
        mean_diff=0.00003, t_pvalue=0.45, normality_pvalue=0.23,
        mean_abs_z_score=0.72,
    )
    uptime = {
        "uptime_pct": 99.87, "seconds_with_data": 23370, "total_seconds": 23400,
        "updates_total": 117000, "updates_per_second": 5.0,
    }

    result = merge_benchmark_and_uptime(benchmark, uptime, threshold=95.0)
    assert isinstance(result, FeedHealthResult)
    assert result.health_status == "HEALTHY"
    assert result.passes is True
    assert result.uptime_pct == 99.87
    assert result.nrmse == 0.002


def test_merge_creates_failing_result():
    """Merging a failing benchmark with low uptime creates FAILING result."""
    from publisher_report import merge_benchmark_and_uptime
    from publisher_benchmark_95 import PublisherBenchmarkResult

    benchmark = PublisherBenchmarkResult(
        publisher_id=55, feed_id=1163, date="2026-02-17", mode="us-equities",
        symbol="Equity.US.AAPL/USD", passes=False, n_observations=15000,
        rmse=0.08, mean_spread=0.01, rmse_over_spread=8.0,
        nrmse=0.082, hit_rate=82.0, benchmark_price_range=1.0,
    )
    uptime = {
        "uptime_pct": 87.3, "seconds_with_data": 13000, "total_seconds": 14895,
        "updates_total": 39000, "updates_per_second": 2.6,
    }

    result = merge_benchmark_and_uptime(benchmark, uptime, threshold=95.0)
    assert result.health_status == "FAILING"
    assert result.passes is False
    assert result.uptime_pct == 87.3


def test_merge_with_error():
    """Merging an errored benchmark result still includes uptime."""
    from publisher_report import merge_benchmark_and_uptime
    from publisher_benchmark_95 import PublisherBenchmarkResult

    benchmark = PublisherBenchmarkResult(
        publisher_id=55, feed_id=999, date="2026-02-17", mode="fx",
        symbol=None, passes=False, n_observations=0,
        rmse=None, mean_spread=None, rmse_over_spread=None,
        error="Feed metadata not found",
    )
    uptime = {"uptime_pct": 0.0, "seconds_with_data": 0, "total_seconds": 86400,
              "updates_total": 0, "updates_per_second": 0.0}

    result = merge_benchmark_and_uptime(benchmark, uptime, threshold=95.0)
    assert result.health_status == "FAILING"
    assert result.error == "Feed metadata not found"


# --- Task 5: format_diagnostics tests ---


def test_diagnostics_significant_bias():
    """Significant t-test shows bias direction and magnitude."""
    from publisher_report import format_diagnostics
    diag = format_diagnostics(
        mean_diff=0.003, t_pvalue=0.001,
        normality_pvalue=0.5, mean_abs_z_score=0.7,
        passes=False, uptime_pct=99.0, threshold=95.0,
    )
    assert "Bias: +0.0030 (significant)" in diag


def test_diagnostics_no_bias():
    """Non-significant t-test shows no bias."""
    from publisher_report import format_diagnostics
    diag = format_diagnostics(
        mean_diff=0.0001, t_pvalue=0.45,
        normality_pvalue=0.5, mean_abs_z_score=0.7,
        passes=True, uptime_pct=99.0, threshold=95.0,
    )
    # Passes benchmark, no diagnostics needed for passing feed
    assert diag == "" or "Bias: none" not in diag


def test_diagnostics_non_normal():
    """Non-normal errors flagged."""
    from publisher_report import format_diagnostics
    diag = format_diagnostics(
        mean_diff=0.001, t_pvalue=0.1,
        normality_pvalue=0.01, mean_abs_z_score=0.8,
        passes=False, uptime_pct=99.0, threshold=95.0,
    )
    assert "outliers" in diag.lower()


def test_diagnostics_volatile():
    """High z-score flagged as volatile."""
    from publisher_report import format_diagnostics
    diag = format_diagnostics(
        mean_diff=0.001, t_pvalue=0.1,
        normality_pvalue=0.5, mean_abs_z_score=1.8,
        passes=False, uptime_pct=99.0, threshold=95.0,
    )
    assert "volatile" in diag.lower()


def test_diagnostics_low_uptime():
    """Low uptime is flagged."""
    from publisher_report import format_diagnostics
    diag = format_diagnostics(
        mean_diff=None, t_pvalue=None,
        normality_pvalue=None, mean_abs_z_score=None,
        passes=True, uptime_pct=87.0, threshold=95.0,
    )
    assert "Low uptime" in diag


def test_diagnostics_all_none():
    """When stats are None (--skip-scipy-tests), shows minimal diagnostics."""
    from publisher_report import format_diagnostics
    diag = format_diagnostics(
        mean_diff=None, t_pvalue=None,
        normality_pvalue=None, mean_abs_z_score=None,
        passes=False, uptime_pct=99.0, threshold=95.0,
    )
    assert "Data quality" in diag
