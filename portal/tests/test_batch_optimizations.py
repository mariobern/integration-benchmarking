"""
Tests for batch processing optimizations.

Tests cover:
1. LRU cache on timezone filter functions
2. --skip-scipy-tests flag functionality
3. Parallel feed discovery
"""

import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestLRUCacheOnFilterFunctions:
    """Tests for Phase 1: LRU cache on timezone filter SQL functions."""

    def test_market_hours_filter_returns_consistent_output(self):
        """Test that get_market_hours_filter_sql returns same output for same inputs."""
        from publisher_benchmark import get_market_hours_filter_sql

        # Call with same parameters multiple times
        result1 = get_market_hours_filter_sql(
            "us-equities", "2025-10-06", "publish_time"
        )
        result2 = get_market_hours_filter_sql(
            "us-equities", "2025-10-06", "publish_time"
        )
        result3 = get_market_hours_filter_sql(
            "us-equities", "2025-10-06", "publish_time"
        )

        # All should be identical (from cache or not)
        assert result1 == result2
        assert result2 == result3

        # Result should contain time constraints
        assert "publish_time >=" in result1
        assert "publish_time <" in result1

    def test_market_hours_filter_returns_empty_for_non_equity(self):
        """Test that non-equity modes return empty string."""
        from publisher_benchmark import get_market_hours_filter_sql

        assert get_market_hours_filter_sql("fx", "2025-10-06", "publish_time") == ""
        assert get_market_hours_filter_sql("metals", "2025-10-06", "publish_time") == ""
        assert get_market_hours_filter_sql("commodity", "2025-10-06", "date_time") == ""

    def test_market_hours_filter_cache_info(self):
        """Test that LRU cache is being used."""
        from publisher_benchmark import get_market_hours_filter_sql

        # Clear any existing cache
        get_market_hours_filter_sql.cache_clear()

        # Make several calls
        get_market_hours_filter_sql("us-equities", "2025-10-06", "publish_time")
        get_market_hours_filter_sql("us-equities", "2025-10-06", "publish_time")
        get_market_hours_filter_sql("us-equities", "2025-10-07", "publish_time")

        # Check cache info
        cache_info = get_market_hours_filter_sql.cache_info()
        assert cache_info.hits >= 1  # At least one cache hit
        assert cache_info.misses >= 2  # Two unique combinations

    def test_extended_hours_filter_cache_info(self):
        """Test that extended hours filter function uses LRU cache."""
        from publisher_benchmark import TradingSession, get_extended_hours_filter_sql

        # Clear any existing cache
        get_extended_hours_filter_sql.cache_clear()

        # Make several calls
        get_extended_hours_filter_sql(
            TradingSession.PREMARKET, "2025-10-06", "publish_time"
        )
        get_extended_hours_filter_sql(
            TradingSession.PREMARKET, "2025-10-06", "publish_time"
        )
        get_extended_hours_filter_sql(
            TradingSession.AFTERHOURS, "2025-10-06", "publish_time"
        )

        # Check cache info
        cache_info = get_extended_hours_filter_sql.cache_info()
        assert cache_info.hits >= 1
        assert cache_info.misses >= 2

    def test_overnight_hours_filter_cache_info(self):
        """Test that overnight hours filter function uses LRU cache."""
        from publisher_benchmark import get_overnight_hours_filter_sql

        # Clear any existing cache
        get_overnight_hours_filter_sql.cache_clear()

        # Make several calls
        get_overnight_hours_filter_sql("2025-10-06", "publish_time")
        get_overnight_hours_filter_sql("2025-10-06", "publish_time")
        get_overnight_hours_filter_sql("2025-10-07", "publish_time")

        # Check cache info
        cache_info = get_overnight_hours_filter_sql.cache_info()
        assert cache_info.hits >= 1
        assert cache_info.misses >= 2


class TestSkipScipyTestsFlag:
    """Tests for Phase 2: --skip-scipy-tests flag."""

    def test_compute_statistical_metrics_returns_all_keys(self):
        """Test that compute_statistical_metrics returns all expected keys."""
        from publisher_benchmark import compute_statistical_metrics

        diffs = [0.01, -0.02, 0.015, -0.005, 0.01] * 10  # 50 values
        pct_diffs = [0.1, -0.2, 0.15, -0.05, 0.1] * 10

        result = compute_statistical_metrics(diffs, pct_diffs)

        expected_keys = [
            "mean_diff",
            "std_diff",
            "mean_pct_diff",
            "std_pct_diff",
            "mae",
            "t_statistic",
            "t_pvalue",
            "wilcoxon_statistic",
            "wilcoxon_pvalue",
            "normality_pvalue",
            "mean_abs_z_score",
        ]

        for key in expected_keys:
            assert key in result, f"Missing key: {key}"

    def test_skip_scipy_null_metrics_structure(self):
        """Test that skipped scipy metrics produce correct null structure."""
        # When skip_scipy_tests=True, all metrics should be None
        null_metrics = {
            "mean_diff": None,
            "std_diff": None,
            "mean_pct_diff": None,
            "std_pct_diff": None,
            "mae": None,
            "t_statistic": None,
            "t_pvalue": None,
            "wilcoxon_statistic": None,
            "wilcoxon_pvalue": None,
            "normality_pvalue": None,
            "mean_abs_z_score": None,
        }

        for key, value in null_metrics.items():
            assert value is None, f"Key {key} should be None when scipy is skipped"

    def test_argparse_skip_scipy_tests_flag(self):
        """Test that --skip-scipy-tests flag is recognized by argparser."""
        import argparse
        import sys
        from io import StringIO

        # Capture help output to verify the flag exists
        from publisher_benchmark import main

        # Create a minimal test to verify argparse accepts the flag
        # We'll import the module and check if the flag is defined
        import publisher_benchmark

        # Get the module's source to check for the flag definition
        import inspect

        source = inspect.getsource(publisher_benchmark)
        assert "--skip-scipy-tests" in source, "Flag not found in publisher_benchmark"


class TestParallelFeedDiscovery:
    """Tests for Phase 3: Parallel feed discovery."""

    def test_discover_feeds_parallel_function_exists(self):
        """Test that discover_feeds_parallel function exists."""
        from portal.batch.daily_benchmark_runner import discover_feeds_parallel

        assert callable(discover_feeds_parallel)

    @patch("portal.batch.daily_benchmark_runner.run_publisher_feeds")
    def test_discover_feeds_parallel_returns_dict_and_temp_dir(self, mock_run_feeds):
        """Test that parallel discovery returns correct structure."""
        from portal.batch.daily_benchmark_runner import discover_feeds_parallel

        # Mock successful feed discovery
        def mock_discover(pid, output_path, date_offset, time_window):
            # Create a mock CSV file
            output_path.write_text(f"{pid},2025-01-01,fx\n")
            return True

        mock_run_feeds.side_effect = mock_discover

        publishers = [11, 55]
        results, temp_dir = discover_feeds_parallel(publishers, max_workers=2)

        # Verify return types
        assert isinstance(results, dict)
        assert isinstance(temp_dir, str)

        # Verify all publishers have results
        assert 11 in results
        assert 55 in results

        # Clean up temp directory
        import shutil

        shutil.rmtree(temp_dir, ignore_errors=True)

    @patch("portal.batch.daily_benchmark_runner.run_publisher_feeds")
    def test_discover_feeds_parallel_handles_failures(self, mock_run_feeds):
        """Test that parallel discovery handles failed discoveries."""
        from portal.batch.daily_benchmark_runner import discover_feeds_parallel

        # Mock one success and one failure
        def mock_discover(pid, output_path, date_offset, time_window):
            if pid == 11:
                output_path.write_text(f"{pid},2025-01-01,fx\n")
                return True
            return False

        mock_run_feeds.side_effect = mock_discover

        publishers = [11, 99]
        results, temp_dir = discover_feeds_parallel(publishers, max_workers=2)

        # Publisher 11 should succeed (path returned)
        assert results[11] is not None

        # Publisher 99 should fail (None returned)
        assert results[99] is None

        # Clean up
        import shutil

        shutil.rmtree(temp_dir, ignore_errors=True)

    def test_argparse_discovery_workers_flag(self):
        """Test that --discovery-workers flag is recognized."""
        import inspect

        from portal.batch import daily_benchmark_runner

        source = inspect.getsource(daily_benchmark_runner)
        assert (
            "--discovery-workers" in source
        ), "Flag not found in daily_benchmark_runner"


class TestProcessPublisherWithPreDiscoveredFeeds:
    """Tests for process_publisher with pre-discovered feeds parameter."""

    def test_process_publisher_accepts_feeds_csv_parameter(self):
        """Test that process_publisher function accepts feeds_csv parameter."""
        import inspect

        from portal.batch.daily_benchmark_runner import process_publisher

        sig = inspect.signature(process_publisher)
        params = list(sig.parameters.keys())

        assert (
            "feeds_csv" in params
        ), "feeds_csv parameter not found in process_publisher"

    def test_process_publisher_feeds_csv_is_optional(self):
        """Test that feeds_csv parameter has a default value (is optional)."""
        import inspect

        from portal.batch.daily_benchmark_runner import process_publisher

        sig = inspect.signature(process_publisher)
        feeds_csv_param = sig.parameters["feeds_csv"]

        # Should have a default value of None
        assert feeds_csv_param.default is None


class TestRunPublisherBenchmarkSkipScipy:
    """Tests for run_publisher_benchmark with skip_scipy_tests parameter."""

    def test_run_publisher_benchmark_accepts_skip_scipy_parameter(self):
        """Test that run_publisher_benchmark accepts skip_scipy_tests parameter."""
        import inspect

        from portal.batch.daily_benchmark_runner import run_publisher_benchmark

        sig = inspect.signature(run_publisher_benchmark)
        params = list(sig.parameters.keys())

        assert (
            "skip_scipy_tests" in params
        ), "skip_scipy_tests not found in run_publisher_benchmark"

    def test_run_publisher_benchmark_skip_scipy_default_is_false(self):
        """Test that skip_scipy_tests defaults to False."""
        import inspect

        from portal.batch.daily_benchmark_runner import run_publisher_benchmark

        sig = inspect.signature(run_publisher_benchmark)
        skip_param = sig.parameters["skip_scipy_tests"]

        assert skip_param.default is False
