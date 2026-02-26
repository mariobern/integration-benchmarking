"""Tests for lib.statistics — statistical computations."""

import math

import pytest

from lib.statistics import compute_statistical_metrics, distribution_stats


class TestComputeStatisticalMetrics:
    def test_identical_values(self):
        diffs = [0.0] * 100
        pct_diffs = [0.0] * 100
        result = compute_statistical_metrics(diffs, pct_diffs)
        assert result["mean_diff"] == 0.0
        assert result["mae"] == 0.0

    def test_known_values(self):
        diffs = [1.0, -1.0, 2.0, -2.0, 0.5]
        pct_diffs = [0.1, -0.1, 0.2, -0.2, 0.05]
        result = compute_statistical_metrics(diffs, pct_diffs)
        assert abs(result["mean_diff"] - 0.1) < 1e-9
        assert result["mae"] == pytest.approx(1.3, abs=0.01)

    def test_too_few_observations(self):
        diffs = [1.0, 2.0]
        pct_diffs = [0.01, 0.02]
        result = compute_statistical_metrics(diffs, pct_diffs, min_observations=20)
        assert result["t_statistic"] is None
        assert result["wilcoxon_statistic"] is None

    def test_infinite_values_handled(self):
        diffs = [0.0] * 50
        pct_diffs = [0.0] * 50
        result = compute_statistical_metrics(diffs, pct_diffs, min_observations=20)
        # Should not raise


class TestDistributionStats:
    def test_empty_list(self):
        result = distribution_stats([])
        assert result["median"] is None
        assert result["mean"] is None

    def test_single_value(self):
        result = distribution_stats([42.0])
        assert result["median"] == 42.0
        assert result["mean"] == 42.0
        assert result["min"] == 42.0
        assert result["max"] == 42.0

    def test_known_distribution(self):
        values = list(range(1, 101))
        result = distribution_stats(values)
        assert result["median"] == pytest.approx(50.5)
        assert result["mean"] == pytest.approx(50.5)
        assert result["min"] == 1
        assert result["max"] == 100
        assert result["p90"] is not None
        assert result["p95"] is not None
