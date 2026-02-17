"""Tests for publisher_report.py health classification and output."""
import pytest


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
