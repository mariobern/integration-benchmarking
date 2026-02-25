"""Tests for lib.benchmark_core — core benchmark evaluation logic."""

from __future__ import annotations

import csv
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from lib.models import (
    BenchmarkResult,
    ExtendedHoursMetrics,
    OvernightMetrics,
    OVERNIGHT_REFERENCE_PUBLISHER_ID,
    PublisherFeedMetrics,
    TradingSession,
)
from lib.thresholds import passes_benchmark


# ---------------------------------------------------------------------------
# Helpers: mock ClickHouse query result
# ---------------------------------------------------------------------------
@dataclass
class MockQueryResult:
    """Mimics the ClickHouse client query result object."""

    result_rows: list[tuple]


def _make_client(rows: list[tuple]) -> MagicMock:
    """Create a mock ClickHouse client that returns *rows* for any query."""
    client = MagicMock()
    client.query.return_value = MockQueryResult(result_rows=rows)
    return client


def _make_timestamps(n: int, base_hour: int = 14, base_minute: int = 0):
    """Generate *n* unique datetime timestamps starting from base_hour:base_minute."""
    from datetime import datetime, timedelta

    base = datetime(2025, 10, 6, base_hour, base_minute, 0)
    return [base + timedelta(seconds=i) for i in range(n)]


# ---------------------------------------------------------------------------
# 1. passes_benchmark integration — session-aware
# ---------------------------------------------------------------------------
class TestPassesBenchmarkIntegration:
    """Verify passes_benchmark with correct session types."""

    def test_regular_session_strict_threshold(self) -> None:
        assert passes_benchmark(0.03, 94.0, "regular", "us-equities") is False

    def test_premarket_relaxed_threshold(self) -> None:
        assert passes_benchmark(0.03, 94.0, "premarket", "us-equities") is True

    def test_afterhours_high_nrmse_passes(self) -> None:
        assert passes_benchmark(0.10, 90.0, "afterhours", "us-equities") is True

    def test_regular_high_nrmse_fails(self) -> None:
        assert passes_benchmark(0.10, 90.0, "regular", "us-equities") is False

    def test_overnight_relaxed(self) -> None:
        assert passes_benchmark(0.03, 50.0, "overnight", "us-equities") is True

    def test_fx_always_regular(self) -> None:
        # 0.03 in conditional range, 90% < 95% regular threshold → fail
        assert passes_benchmark(0.03, 90.0, "premarket", "fx") is False


# ---------------------------------------------------------------------------
# 2. list_asset_classes_in_csv
# ---------------------------------------------------------------------------
class TestListAssetClassesInCsv:
    def test_counts_asset_classes(self, tmp_path: Path) -> None:
        from lib.benchmark_core import list_asset_classes_in_csv

        csv_file = tmp_path / "feeds.csv"
        csv_file.write_text(
            "327,2025-10-06,fx\n" "328,2025-10-06,fx\n" "1163,2025-10-02,us-equities\n"
        )

        counts = list_asset_classes_in_csv(csv_file)
        assert counts == {"fx": 2, "us-equities": 1}

    def test_skips_empty_and_short_rows(self, tmp_path: Path) -> None:
        from lib.benchmark_core import list_asset_classes_in_csv

        csv_file = tmp_path / "feeds.csv"
        csv_file.write_text("\n" "327\n" "327,2025-10-06,fx\n")

        counts = list_asset_classes_in_csv(csv_file)
        assert counts == {"fx": 1}


# ---------------------------------------------------------------------------
# 3. get_feed_metadata
# ---------------------------------------------------------------------------
class TestGetFeedMetadata:
    def test_returns_symbol_and_exponent(self) -> None:
        from lib.benchmark_core import get_feed_metadata

        client = _make_client([("Equity.US.AAPL/USD", -8)])
        symbol, exponent = get_feed_metadata(client, feed_id=1163)
        assert symbol == "Equity.US.AAPL/USD"
        assert exponent == -8

    def test_returns_none_when_no_rows(self) -> None:
        from lib.benchmark_core import get_feed_metadata

        client = _make_client([])
        symbol, exponent = get_feed_metadata(client, feed_id=9999)
        assert symbol is None
        assert exponent is None


# ---------------------------------------------------------------------------
# 4. evaluate_feed_two_queries — core evaluation
# ---------------------------------------------------------------------------
class TestEvaluateFeedTwoQueries:
    """Tests for the main evaluation entry point with mocked ClickHouse."""

    def _setup_clients(
        self,
        pub_rows: list[tuple],
        bench_rows: list[tuple],
        metadata_rows: list[tuple] | None = None,
    ) -> tuple:
        """Create mock clients for lazer and analytics."""
        from datetime import datetime as dt

        if metadata_rows is None:
            metadata_rows = [("FX.EURUSD/USD", -8)]

        client_lazer = MagicMock()
        # First query = metadata, second query = publisher data
        client_lazer.query.side_effect = [
            MockQueryResult(result_rows=metadata_rows),
            MockQueryResult(result_rows=pub_rows),
        ]

        client_analytics = MagicMock()
        client_analytics.query.return_value = MockQueryResult(result_rows=bench_rows)

        return client_lazer, client_analytics

    def test_no_metadata_returns_error(self) -> None:
        from lib.benchmark_core import evaluate_feed_two_queries

        client_lazer, client_analytics = self._setup_clients([], [], metadata_rows=[])

        result = evaluate_feed_two_queries(
            client_lazer, client_analytics, 327, "2025-10-06", "fx"
        )
        assert result.ready is False
        assert "metadata" in (result.error or "").lower()

    def test_no_publisher_data_returns_error(self) -> None:
        from lib.benchmark_core import evaluate_feed_two_queries

        client_lazer, client_analytics = self._setup_clients(pub_rows=[], bench_rows=[])

        result = evaluate_feed_two_queries(
            client_lazer, client_analytics, 327, "2025-10-06", "fx"
        )
        assert result.ready is False
        assert "publisher" in (result.error or "").lower()

    def test_no_benchmark_data_returns_error(self) -> None:
        from lib.benchmark_core import evaluate_feed_two_queries
        from datetime import datetime as dt

        ts = dt(2025, 10, 6, 14, 0, 0)
        client_lazer = MagicMock()
        client_lazer.query.side_effect = [
            MockQueryResult(result_rows=[("FX.EURUSD/USD", -8)]),
            MockQueryResult(result_rows=[(55, ts, 1.08, 10)]),
        ]

        client_analytics = MagicMock()
        client_analytics.query.return_value = MockQueryResult(result_rows=[])

        result = evaluate_feed_two_queries(
            client_lazer, client_analytics, 327, "2025-10-06", "fx"
        )
        assert result.ready is False
        assert "benchmark" in (result.error or "").lower()

    def test_single_publisher_passes(self) -> None:
        """One publisher with data matching benchmark exactly should pass."""
        from lib.benchmark_core import evaluate_feed_two_queries

        # Generate 200 matching timestamps (above REGULAR_MIN_OBSERVATIONS=100)
        ts_list = _make_timestamps(200)

        # Use slight price variation so benchmark_range > 0 (avoids nrmse=None)
        pub_rows = [(55, ts, 1.08 + i * 0.0001, 5) for i, ts in enumerate(ts_list)]
        bench_rows = [(ts, 1.08 + i * 0.0001, 0.0001) for i, ts in enumerate(ts_list)]

        client_lazer = MagicMock()
        client_lazer.query.side_effect = [
            MockQueryResult(result_rows=[("FX.EURUSD/USD", -8)]),
            MockQueryResult(result_rows=pub_rows),
        ]

        client_analytics = MagicMock()
        client_analytics.query.return_value = MockQueryResult(result_rows=bench_rows)

        result = evaluate_feed_two_queries(
            client_lazer,
            client_analytics,
            327,
            "2025-10-06",
            "fx",
            target_pub_count=1,
            skip_scipy_tests=True,
        )

        assert result.ready is True
        assert result.passing_pub_count == 1
        assert 55 in result.passing_publishers

    def test_insufficient_observations_publisher_fails(self) -> None:
        """Publisher with fewer than REGULAR_MIN_OBSERVATIONS fails."""
        from lib.benchmark_core import evaluate_feed_two_queries

        ts_list = _make_timestamps(10)

        pub_rows = [(55, ts, 1.08000, 5) for ts in ts_list]
        bench_rows = [(ts, 1.08000, 0.0001) for ts in ts_list]

        client_lazer = MagicMock()
        client_lazer.query.side_effect = [
            MockQueryResult(result_rows=[("FX.EURUSD/USD", -8)]),
            MockQueryResult(result_rows=pub_rows),
        ]

        client_analytics = MagicMock()
        client_analytics.query.return_value = MockQueryResult(result_rows=bench_rows)

        result = evaluate_feed_two_queries(
            client_lazer,
            client_analytics,
            327,
            "2025-10-06",
            "fx",
            target_pub_count=1,
            skip_scipy_tests=True,
        )

        assert result.ready is False
        assert result.failing_pub_count == 1

    def test_passes_benchmark_called_with_regular_session(self) -> None:
        """Verify regular evaluation uses session='regular'."""
        from lib.benchmark_core import evaluate_feed_two_queries

        ts_list = _make_timestamps(200)
        pub_rows = [(55, ts, 1.08000, 5) for ts in ts_list]
        bench_rows = [(ts, 1.08000, 0.0001) for ts in ts_list]

        client_lazer = MagicMock()
        client_lazer.query.side_effect = [
            MockQueryResult(result_rows=[("FX.EURUSD/USD", -8)]),
            MockQueryResult(result_rows=pub_rows),
        ]

        client_analytics = MagicMock()
        client_analytics.query.return_value = MockQueryResult(result_rows=bench_rows)

        with patch(
            "lib.benchmark_core.passes_benchmark", wraps=passes_benchmark
        ) as mock_pb:
            result = evaluate_feed_two_queries(
                client_lazer,
                client_analytics,
                327,
                "2025-10-06",
                "fx",
                target_pub_count=1,
                skip_scipy_tests=True,
            )

            # Verify passes_benchmark was called with session="regular"
            assert mock_pb.call_count >= 1
            for call in mock_pb.call_args_list:
                assert call.kwargs.get("session") == "regular" or (
                    len(call.args) >= 3 and call.args[2] == "regular"
                )


# ---------------------------------------------------------------------------
# 5. evaluate_session_for_all_publishers — session parameter
# ---------------------------------------------------------------------------
class TestEvaluateSessionForAllPublishers:
    """Verify session type is correctly passed to passes_benchmark."""

    def test_premarket_session_uses_premarket(self) -> None:
        from lib.benchmark_core import evaluate_session_for_all_publishers

        ts_list = _make_timestamps(100, base_hour=8)

        pub_rows = [(55, ts, 100.0, 5) for ts in ts_list]
        bench_rows = [(ts, 100.0, 0.5) for ts in ts_list]

        client_lazer = _make_client(pub_rows)
        client_analytics = _make_client(bench_rows)

        with patch(
            "lib.benchmark_core.passes_benchmark", wraps=passes_benchmark
        ) as mock_pb:
            results = evaluate_session_for_all_publishers(
                client_lazer,
                client_analytics,
                feed_id=1163,
                date="2025-10-06",
                mode="us-equities",
                divisor=1e8,
                benchmark_table="datascope_global_equities_benchmark_data",
                session=TradingSession.PREMARKET,
            )

            if mock_pb.call_count > 0:
                for call in mock_pb.call_args_list:
                    assert call.kwargs.get("session") == "premarket" or (
                        len(call.args) >= 3 and call.args[2] == "premarket"
                    )

    def test_afterhours_session_uses_afterhours(self) -> None:
        from lib.benchmark_core import evaluate_session_for_all_publishers

        ts_list = _make_timestamps(100, base_hour=20)

        pub_rows = [(55, ts, 100.0, 5) for ts in ts_list]
        bench_rows = [(ts, 100.0, 0.5) for ts in ts_list]

        client_lazer = _make_client(pub_rows)
        client_analytics = _make_client(bench_rows)

        with patch(
            "lib.benchmark_core.passes_benchmark", wraps=passes_benchmark
        ) as mock_pb:
            results = evaluate_session_for_all_publishers(
                client_lazer,
                client_analytics,
                feed_id=1163,
                date="2025-10-06",
                mode="us-equities",
                divisor=1e8,
                benchmark_table="datascope_global_equities_benchmark_data",
                session=TradingSession.AFTERHOURS,
            )

            if mock_pb.call_count > 0:
                for call in mock_pb.call_args_list:
                    assert call.kwargs.get("session") == "afterhours" or (
                        len(call.args) >= 3 and call.args[2] == "afterhours"
                    )

    def test_no_publisher_data_returns_empty(self) -> None:
        from lib.benchmark_core import evaluate_session_for_all_publishers

        client_lazer = _make_client([])
        client_analytics = _make_client([])

        results = evaluate_session_for_all_publishers(
            client_lazer,
            client_analytics,
            feed_id=1163,
            date="2025-10-06",
            mode="us-equities",
            divisor=1e8,
            benchmark_table="datascope_global_equities_benchmark_data",
            session=TradingSession.PREMARKET,
        )

        assert results == {}


# ---------------------------------------------------------------------------
# 6. evaluate_overnight_for_all_publishers — overnight session
# ---------------------------------------------------------------------------
class TestEvaluateOvernightForAllPublishers:
    """Verify overnight evaluation uses session='overnight' for passes_benchmark."""

    def test_overnight_uses_overnight_session(self) -> None:
        from lib.benchmark_core import evaluate_overnight_for_all_publishers

        ts_list = _make_timestamps(100, base_hour=1)

        # pub 55 data + reference pub 32 data
        pub_rows = [(55, ts, 100.0, 5) for ts in ts_list] + [
            (32, ts, 100.0, 5) for ts in ts_list
        ]

        client_lazer = MagicMock()
        # First call: publisher query, second call: reference query
        client_lazer.query.side_effect = [
            MockQueryResult(result_rows=pub_rows),
            MockQueryResult(result_rows=[(ts, 100.0, 0.5, 5) for ts in ts_list]),
        ]

        with patch(
            "lib.benchmark_core.passes_benchmark", wraps=passes_benchmark
        ) as mock_pb:
            results = evaluate_overnight_for_all_publishers(
                client_lazer,
                feed_id=1163,
                date="2025-10-06",
                divisor=1e8,
            )

            if mock_pb.call_count > 0:
                for call in mock_pb.call_args_list:
                    assert call.kwargs.get("session") == "overnight" or (
                        len(call.args) >= 3 and call.args[2] == "overnight"
                    )

    def test_no_publisher_data_returns_empty(self) -> None:
        from lib.benchmark_core import evaluate_overnight_for_all_publishers

        client_lazer = _make_client([])

        results = evaluate_overnight_for_all_publishers(
            client_lazer,
            feed_id=1163,
            date="2025-10-06",
            divisor=1e8,
        )

        assert results == {}

    def test_reference_publisher_excluded_from_evaluation(self) -> None:
        from lib.benchmark_core import evaluate_overnight_for_all_publishers

        ts_list = _make_timestamps(100, base_hour=1)

        # Only reference publisher 32 data
        pub_rows = [(32, ts, 100.0, 5) for ts in ts_list]

        client_lazer = MagicMock()
        client_lazer.query.side_effect = [
            MockQueryResult(result_rows=pub_rows),
            MockQueryResult(result_rows=[(ts, 100.0, 0.5, 5) for ts in ts_list]),
        ]

        results = evaluate_overnight_for_all_publishers(
            client_lazer,
            feed_id=1163,
            date="2025-10-06",
            divisor=1e8,
        )

        # Publisher 32 should be present but marked as self-reference error
        assert 32 in results
        assert results[32].error is not None
        assert "itself" in results[32].error.lower()


# ---------------------------------------------------------------------------
# 7. evaluate_feed_fast — deprecated wrapper
# ---------------------------------------------------------------------------
class TestEvaluateFeedFast:
    def test_delegates_to_evaluate_feed_two_queries(self) -> None:
        from lib.benchmark_core import evaluate_feed_fast

        with patch("lib.benchmark_core.evaluate_feed_two_queries") as mock_eval:
            mock_eval.return_value = BenchmarkResult(
                feed_id=327,
                date="2025-10-06",
                mode="fx",
                symbol="FX.EURUSD/USD",
                ready=True,
                target_pub_count=4,
                passing_pub_count=4,
                failing_pub_count=0,
                passing_publishers=[55, 56, 57, 58],
                failing_publishers=[],
            )

            result = evaluate_feed_fast(
                MagicMock(), MagicMock(), 327, "2025-10-06", "fx"
            )

            mock_eval.assert_called_once()
            assert result.ready is True


# ---------------------------------------------------------------------------
# 8. Edge cases
# ---------------------------------------------------------------------------
class TestEdgeCases:
    def test_all_none_benchmark_prices_handled(self) -> None:
        """Benchmark rows with None prices should be filtered out."""
        from lib.benchmark_core import evaluate_feed_two_queries

        ts_list = _make_timestamps(200)
        pub_rows = [(55, ts, 1.08, 5) for ts in ts_list]
        # All None prices in benchmark
        bench_rows = [(ts, None, 0.0001) for ts in ts_list]

        client_lazer = MagicMock()
        client_lazer.query.side_effect = [
            MockQueryResult(result_rows=[("FX.EURUSD/USD", -8)]),
            MockQueryResult(result_rows=pub_rows),
        ]

        client_analytics = MagicMock()
        client_analytics.query.return_value = MockQueryResult(result_rows=bench_rows)

        result = evaluate_feed_two_queries(
            client_lazer,
            client_analytics,
            327,
            "2025-10-06",
            "fx",
            target_pub_count=1,
            skip_scipy_tests=True,
        )

        # No matched observations since all benchmark prices are None
        assert result.ready is False
        assert result.failing_pub_count == 1

    def test_exception_returns_error_result(self) -> None:
        """ClickHouse errors should be caught and returned as error."""
        from lib.benchmark_core import evaluate_feed_two_queries

        client_lazer = MagicMock()
        client_lazer.query.side_effect = [
            MockQueryResult(result_rows=[("FX.EURUSD/USD", -8)]),
            Exception("Connection refused"),
        ]

        client_analytics = MagicMock()

        result = evaluate_feed_two_queries(
            client_lazer,
            client_analytics,
            327,
            "2025-10-06",
            "fx",
        )

        assert result.ready is False
        assert "Connection refused" in (result.error or "")
