"""
Tests for the UptimeCalculator module.

Tests the 200ms gap-based uptime calculation method.
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from portal.batch.uptime_calculator import (
    DEFAULT_GAP_THRESHOLD_MS,
    UptimeCalculator,
    UptimeResult,
)


class TestUptimeResult:
    """Tests for UptimeResult dataclass."""

    def test_uptime_result_creation(self):
        """Test creating an UptimeResult."""
        result = UptimeResult(
            uptime_pct=99.95,
            downtime_ms=1800000,
            period_length_ms=36000000,
            updates_total=35000,
            updates_per_second=0.97,
            max_gap_ms=450,
            gaps_over_threshold=125,
        )

        assert result.uptime_pct == 99.95
        assert result.downtime_ms == 1800000
        assert result.period_length_ms == 36000000
        assert result.updates_total == 35000
        assert result.updates_per_second == 0.97
        assert result.max_gap_ms == 450
        assert result.gaps_over_threshold == 125

    def test_uptime_result_defaults(self):
        """Test UptimeResult with default values."""
        result = UptimeResult(
            uptime_pct=99.0,
            downtime_ms=1000,
            period_length_ms=100000,
            updates_total=1000,
            updates_per_second=10.0,
        )

        assert result.max_gap_ms is None
        assert result.gaps_over_threshold == 0

    def test_uptime_result_is_frozen(self):
        """Test that UptimeResult is immutable."""
        result = UptimeResult(
            uptime_pct=99.95,
            downtime_ms=1800000,
            period_length_ms=36000000,
            updates_total=35000,
            updates_per_second=0.97,
        )

        with pytest.raises(AttributeError):
            result.uptime_pct = 100.0


class TestUptimeCalculator:
    """Tests for UptimeCalculator class."""

    @pytest.fixture
    def mock_client(self):
        """Create a mock ClickHouse client."""
        return MagicMock()

    def test_calculator_initialization(self, mock_client):
        """Test calculator initialization with default gap threshold."""
        calc = UptimeCalculator(client=mock_client)
        assert calc._client is mock_client
        assert calc._gap_threshold_ms == DEFAULT_GAP_THRESHOLD_MS

    def test_calculator_custom_threshold(self, mock_client):
        """Test calculator initialization with custom gap threshold."""
        calc = UptimeCalculator(client=mock_client, gap_threshold_ms=100)
        assert calc._gap_threshold_ms == 100

    def test_calculator_lazy_client(self):
        """Test that client is lazily initialized."""
        with patch("portal.batch.uptime_calculator.settings") as mock_settings:
            mock_settings.get_clickhouse_lazer_config.return_value = {}
            with patch("portal.batch.uptime_calculator.clickhouse_connect") as mock_ch:
                mock_ch.get_client.return_value = MagicMock()

                calc = UptimeCalculator()
                assert calc._client is None

                # Accessing client triggers initialization
                _ = calc.client
                mock_ch.get_client.assert_called_once()

    def test_compute_feed_uptime_gap_based(self, mock_client):
        """Test uptime computation using gap-based method."""
        calc = UptimeCalculator(client=mock_client)

        # Mock the gap-based query result
        # Columns: updates_total, max_gap_ms, gaps_over_threshold, consecutive_downtime,
        #          start_gap_ms, end_gap_ms, total_time_ms, total_downtime_ms
        gap_result = MagicMock()
        gap_result.result_rows = [(35000, 450, 125, 50000, 0, 0, 21600000, 50000)]
        mock_client.query.return_value = gap_result

        start = datetime(2026, 1, 28, 14, 30, 0)
        end = datetime(2026, 1, 28, 20, 30, 0)

        result = calc.compute_feed_uptime(
            publisher_id=55,
            feed_id=327,
            start_utc=start,
            end_utc=end,
        )

        assert isinstance(result, UptimeResult)
        assert result.updates_total == 35000
        assert result.max_gap_ms == 450
        assert result.gaps_over_threshold == 125
        assert result.downtime_ms == 50000

    def test_compute_feed_uptime_no_data(self, mock_client):
        """Test uptime computation when no data is found."""
        calc = UptimeCalculator(client=mock_client)

        # Mock empty result
        mock_client.query.return_value.result_rows = []

        start = datetime(2026, 1, 28, 14, 30, 0)
        end = datetime(2026, 1, 28, 20, 30, 0)

        result = calc.compute_feed_uptime(
            publisher_id=55,
            feed_id=327,
            start_utc=start,
            end_utc=end,
        )

        assert result.uptime_pct == 0.0
        assert result.updates_total == 0
        assert result.max_gap_ms is None
        assert result.gaps_over_threshold == 0

    def test_compute_feed_uptime_zero_updates(self, mock_client):
        """Test uptime computation when updates_total is 0."""
        calc = UptimeCalculator(client=mock_client)

        # Mock result with 0 updates
        gap_result = MagicMock()
        gap_result.result_rows = [(0, None, 0, 0, 0, 0, 21600000, 21600000)]
        mock_client.query.return_value = gap_result

        start = datetime(2026, 1, 28, 14, 30, 0)
        end = datetime(2026, 1, 28, 20, 30, 0)

        result = calc.compute_feed_uptime(
            publisher_id=55,
            feed_id=327,
            start_utc=start,
            end_utc=end,
        )

        assert result.uptime_pct == 0.0
        assert result.updates_total == 0

    def test_compute_batch_uptime_empty(self, mock_client):
        """Test batch uptime computation with empty feed list."""
        calc = UptimeCalculator(client=mock_client)

        start = datetime(2026, 1, 28, 14, 30, 0)
        end = datetime(2026, 1, 28, 20, 30, 0)

        result = calc.compute_batch_uptime(
            publisher_id=55,
            feed_ids=[],
            start_utc=start,
            end_utc=end,
        )

        assert result == {}
        mock_client.query.assert_not_called()

    def test_compute_batch_uptime_gap_based(self, mock_client):
        """Test batch uptime computation using gap-based method."""
        calc = UptimeCalculator(client=mock_client)

        # Mock the batch gap-based query result
        # Columns: feed_id, updates_total, max_gap_ms, gaps_over_threshold,
        #          consecutive_downtime, start_gap_ms, end_gap_ms, total_time_ms, total_downtime_ms
        batch_result = MagicMock()
        batch_result.result_rows = [
            (327, 35000, 300, 50, 10000, 0, 0, 21600000, 10000),
            (1163, 25000, 800, 200, 100000, 0, 0, 21600000, 100000),
        ]
        mock_client.query.return_value = batch_result

        start = datetime(2026, 1, 28, 14, 30, 0)
        end = datetime(2026, 1, 28, 20, 30, 0)

        result = calc.compute_batch_uptime(
            publisher_id=55,
            feed_ids=[327, 1163, 500],  # 500 won't have data
            start_utc=start,
            end_utc=end,
        )

        assert 327 in result
        assert 1163 in result
        assert 500 in result  # Should have zero uptime

        assert result[327].updates_total == 35000
        assert result[327].max_gap_ms == 300
        assert result[327].gaps_over_threshold == 50

        assert result[1163].updates_total == 25000
        assert result[1163].max_gap_ms == 800
        assert result[1163].gaps_over_threshold == 200

        assert result[500].uptime_pct == 0.0
        assert result[500].updates_total == 0


class TestUptimeCalculatorIntegration:
    """Integration-style tests for UptimeCalculator (mocked ClickHouse)."""

    def test_full_uptime_calculation_flow(self):
        """Test the full flow of gap-based uptime calculation."""
        mock_client = MagicMock()

        calc = UptimeCalculator(client=mock_client, gap_threshold_ms=200)

        # Mock gap-based query result
        gap_result = MagicMock()
        gap_result.result_rows = [(25000, 500, 150, 75000, 100, 200, 21600000, 75300)]
        mock_client.query.return_value = gap_result

        start = datetime(2026, 1, 28, 14, 30, 0)
        end = datetime(2026, 1, 28, 20, 30, 0)

        result = calc.compute_feed_uptime(
            publisher_id=55,
            feed_id=327,
            start_utc=start,
            end_utc=end,
        )

        assert isinstance(result, UptimeResult)
        assert result.period_length_ms > 0
        assert result.updates_total == 25000
        assert result.max_gap_ms == 500
        assert result.gaps_over_threshold == 150
        assert result.downtime_ms == 75300

    def test_high_uptime_scenario(self):
        """Test scenario with high uptime (small gaps)."""
        mock_client = MagicMock()
        calc = UptimeCalculator(client=mock_client, gap_threshold_ms=200)

        # Very few gaps over threshold, minimal downtime
        gap_result = MagicMock()
        gap_result.result_rows = [(100000, 180, 5, 500, 0, 0, 21600000, 500)]
        mock_client.query.return_value = gap_result

        start = datetime(2026, 1, 28, 14, 30, 0)
        end = datetime(2026, 1, 28, 20, 30, 0)

        result = calc.compute_feed_uptime(
            publisher_id=55,
            feed_id=327,
            start_utc=start,
            end_utc=end,
        )

        # 500ms downtime out of 21600000ms = ~99.998% uptime
        assert result.uptime_pct > 99.99
        assert result.max_gap_ms == 180  # Below threshold
        assert result.gaps_over_threshold == 5

    def test_low_uptime_scenario(self):
        """Test scenario with low uptime (many large gaps)."""
        mock_client = MagicMock()
        calc = UptimeCalculator(client=mock_client, gap_threshold_ms=200)

        # Many gaps, significant downtime
        gap_result = MagicMock()
        gap_result.result_rows = [
            (5000, 5000, 1000, 10000000, 100000, 100000, 21600000, 10200000)
        ]
        mock_client.query.return_value = gap_result

        start = datetime(2026, 1, 28, 14, 30, 0)
        end = datetime(2026, 1, 28, 20, 30, 0)

        result = calc.compute_feed_uptime(
            publisher_id=55,
            feed_id=327,
            start_utc=start,
            end_utc=end,
        )

        # 10.2s downtime out of 21.6s = ~52.8% uptime
        assert result.uptime_pct < 55
        assert result.max_gap_ms == 5000  # 5 second gap
        assert result.gaps_over_threshold == 1000


class TestInputValidation:
    """Tests for input validation."""

    @pytest.fixture
    def mock_client(self):
        return MagicMock()

    def test_invalid_publisher_id(self, mock_client):
        """Test that invalid publisher_id raises error."""
        calc = UptimeCalculator(client=mock_client)

        start = datetime(2026, 1, 28, 14, 30, 0)
        end = datetime(2026, 1, 28, 20, 30, 0)

        with pytest.raises(ValueError, match="publisher_id"):
            calc.compute_feed_uptime(
                publisher_id=-1,
                feed_id=327,
                start_utc=start,
                end_utc=end,
            )

    def test_invalid_feed_id(self, mock_client):
        """Test that invalid feed_id raises error."""
        calc = UptimeCalculator(client=mock_client)

        start = datetime(2026, 1, 28, 14, 30, 0)
        end = datetime(2026, 1, 28, 20, 30, 0)

        with pytest.raises(ValueError, match="feed_id"):
            calc.compute_feed_uptime(
                publisher_id=55,
                feed_id="abc",  # type: ignore
                start_utc=start,
                end_utc=end,
            )

    def test_invalid_feed_id_in_batch(self, mock_client):
        """Test that invalid feed_id in batch raises error."""
        calc = UptimeCalculator(client=mock_client)

        start = datetime(2026, 1, 28, 14, 30, 0)
        end = datetime(2026, 1, 28, 20, 30, 0)

        with pytest.raises(ValueError, match="feed_id"):
            calc.compute_batch_uptime(
                publisher_id=55,
                feed_ids=[327, -1, 500],
                start_utc=start,
                end_utc=end,
            )
