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
