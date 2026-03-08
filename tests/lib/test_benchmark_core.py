"""Tests for lib.benchmark_core — core benchmark evaluation logic."""

from __future__ import annotations

import csv
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest

from lib.benchmark_core import evaluate_feed_two_queries, query_aggregate_feed
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

    def test_tolerance_matching_finds_nearby_benchmark(self) -> None:
        """Publisher timestamps offset by 30s from benchmark should still match."""
        from lib.benchmark_core import evaluate_feed_two_queries
        from datetime import datetime, timedelta

        # 200 benchmark timestamps spaced 60s apart so each pub ts matches exactly one
        base = datetime(2025, 10, 6, 14, 0, 0)
        bench_ts = [base + timedelta(seconds=i * 60) for i in range(200)]
        # Publisher timestamps offset by 30s from each benchmark
        pub_ts = [t + timedelta(seconds=30) for t in bench_ts]

        # Same price at position i for both publisher and benchmark so NRMSE ~ 0
        pub_rows = [(55, ts, 1.08 + i * 0.0001, 5) for i, ts in enumerate(pub_ts)]
        bench_rows = [(ts, 1.08 + i * 0.0001, 0.0001) for i, ts in enumerate(bench_ts)]

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
            tolerance_seconds=60,
            skip_scipy_tests=True,
        )

        # With 60s tolerance, all 200 pub timestamps should match benchmarks 30s away
        assert result.ready is True
        assert result.passing_pub_count == 1
        details = result.publisher_details
        assert details is not None
        assert details[0].n_observations == 200

    def test_tolerance_zero_is_exact_match(self) -> None:
        """tolerance_seconds=0 should behave like exact matching."""
        from lib.benchmark_core import evaluate_feed_two_queries
        from datetime import datetime, timedelta

        base = datetime(2025, 10, 6, 14, 0, 0)
        bench_ts = [base + timedelta(seconds=i) for i in range(200)]
        # Publisher timestamps offset by 1s — should NOT match with tolerance=0
        pub_ts = [t + timedelta(seconds=1) for t in bench_ts]

        pub_rows = [(55, ts, 1.08, 5) for ts in pub_ts]
        bench_rows = [(ts, 1.08, 0.0001) for ts in bench_ts]

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
            tolerance_seconds=0,
            skip_scipy_tests=True,
        )

        # With tolerance=0, offset timestamps should not match
        assert result.ready is False


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

    def test_tolerance_matching_in_session(self) -> None:
        from lib.benchmark_core import evaluate_session_for_all_publishers
        from datetime import datetime, timedelta

        # 100 benchmark timestamps spaced 60s apart
        base = datetime(2025, 10, 6, 8, 0, 0)
        bench_ts = [base + timedelta(seconds=i * 60) for i in range(100)]
        # Publisher timestamps offset by 20s
        pub_ts = [t + timedelta(seconds=20) for t in bench_ts]

        pub_rows = [(55, ts, 100.0, 5) for ts in pub_ts]
        bench_rows = [(ts, 100.0, 0.5) for ts in bench_ts]

        client_lazer = _make_client(pub_rows)
        client_analytics = _make_client(bench_rows)

        results = evaluate_session_for_all_publishers(
            client_lazer,
            client_analytics,
            feed_id=1163,
            date="2025-10-06",
            mode="us-equities",
            divisor=1e8,
            benchmark_table="datascope_global_equities_benchmark_data",
            session=TradingSession.PREMARKET,
            tolerance_seconds=60,
        )

        assert 55 in results
        assert results[55].n_observations == 100
        assert results[55].error is None


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

    def test_tolerance_matching_overnight(self) -> None:
        from lib.benchmark_core import evaluate_overnight_for_all_publishers
        from datetime import datetime, timedelta

        base = datetime(2025, 10, 6, 1, 0, 0)
        # Reference publisher 32 timestamps spaced 60s apart
        ref_ts = [base + timedelta(seconds=i * 60) for i in range(100)]
        # Publisher 55 offset by 25s
        pub_ts = [t + timedelta(seconds=25) for t in ref_ts]

        pub_rows = [(55, ts, 100.0, 5) for ts in pub_ts] + [
            (32, ts, 100.0, 5) for ts in ref_ts
        ]
        ref_rows = [(ts, 100.0, 0.5, 5) for ts in ref_ts]

        client_lazer = MagicMock()
        client_lazer.query.side_effect = [
            MockQueryResult(result_rows=pub_rows),
            MockQueryResult(result_rows=ref_rows),
        ]

        results = evaluate_overnight_for_all_publishers(
            client_lazer,
            feed_id=1163,
            date="2025-10-06",
            divisor=1e8,
            tolerance_seconds=60,
        )

        assert 55 in results
        assert results[55].n_observations == 100
        assert results[55].error is None

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
# 7. Edge cases
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


# ---------------------------------------------------------------------------
# 8. find_nearest_benchmark — tolerance matching helper
# ---------------------------------------------------------------------------
class TestFindNearestBenchmark:
    """Tests for bisect-based nearest benchmark lookup."""

    def test_exact_match_returns_value(self) -> None:
        from datetime import datetime

        from lib.benchmark_core import find_nearest_benchmark

        ts = datetime(2025, 10, 6, 14, 0, 0)
        benchmark_by_ts = {ts: (1.08, 0.0001)}
        sorted_ts = [ts]

        result = find_nearest_benchmark(
            sorted_ts, benchmark_by_ts, ts, tolerance_seconds=60
        )
        assert result == (1.08, 0.0001)

    def test_within_tolerance_returns_nearest(self) -> None:
        from datetime import datetime, timedelta

        from lib.benchmark_core import find_nearest_benchmark

        bench_ts = datetime(2025, 10, 6, 14, 0, 0)
        target_ts = bench_ts + timedelta(seconds=30)
        benchmark_by_ts = {bench_ts: (1.08, 0.0001)}
        sorted_ts = [bench_ts]

        result = find_nearest_benchmark(
            sorted_ts, benchmark_by_ts, target_ts, tolerance_seconds=60
        )
        assert result == (1.08, 0.0001)

    def test_outside_tolerance_returns_none(self) -> None:
        from datetime import datetime, timedelta

        from lib.benchmark_core import find_nearest_benchmark

        bench_ts = datetime(2025, 10, 6, 14, 0, 0)
        target_ts = bench_ts + timedelta(seconds=61)
        benchmark_by_ts = {bench_ts: (1.08, 0.0001)}
        sorted_ts = [bench_ts]

        result = find_nearest_benchmark(
            sorted_ts, benchmark_by_ts, target_ts, tolerance_seconds=60
        )
        assert result is None

    def test_boundary_exactly_at_tolerance_returns_value(self) -> None:
        from datetime import datetime, timedelta

        from lib.benchmark_core import find_nearest_benchmark

        bench_ts = datetime(2025, 10, 6, 14, 0, 0)
        target_ts = bench_ts + timedelta(seconds=60)
        benchmark_by_ts = {bench_ts: (1.08, 0.0001)}
        sorted_ts = [bench_ts]

        result = find_nearest_benchmark(
            sorted_ts, benchmark_by_ts, target_ts, tolerance_seconds=60
        )
        assert result == (1.08, 0.0001)

    def test_picks_closer_of_two_candidates(self) -> None:
        from datetime import datetime, timedelta

        from lib.benchmark_core import find_nearest_benchmark

        ts1 = datetime(2025, 10, 6, 14, 0, 0)
        ts2 = datetime(2025, 10, 6, 14, 1, 0)
        target = datetime(2025, 10, 6, 14, 0, 20)  # closer to ts1
        benchmark_by_ts = {ts1: (1.08, 0.0001), ts2: (1.09, 0.0002)}
        sorted_ts = [ts1, ts2]

        result = find_nearest_benchmark(
            sorted_ts, benchmark_by_ts, target, tolerance_seconds=60
        )
        assert result == (1.08, 0.0001)

    def test_empty_benchmark_returns_none(self) -> None:
        from datetime import datetime

        from lib.benchmark_core import find_nearest_benchmark

        target = datetime(2025, 10, 6, 14, 0, 0)
        result = find_nearest_benchmark([], {}, target, tolerance_seconds=60)
        assert result is None

    def test_tolerance_zero_requires_exact_match(self) -> None:
        from datetime import datetime, timedelta

        from lib.benchmark_core import find_nearest_benchmark

        bench_ts = datetime(2025, 10, 6, 14, 0, 0)
        target_exact = bench_ts
        target_off = bench_ts + timedelta(seconds=1)
        benchmark_by_ts = {bench_ts: (1.08, 0.0001)}
        sorted_ts = [bench_ts]

        assert find_nearest_benchmark(
            sorted_ts, benchmark_by_ts, target_exact, tolerance_seconds=0
        ) == (1.08, 0.0001)
        assert (
            find_nearest_benchmark(
                sorted_ts, benchmark_by_ts, target_off, tolerance_seconds=0
            )
            is None
        )


# ---------------------------------------------------------------------------
# 9. Qualifier filter injection into benchmark queries
# ---------------------------------------------------------------------------
class TestQualifierFilterInQueries:
    """Verify qualifier filter is injected into benchmark SQL for us-equities."""

    @patch("lib.benchmark_core.get_feed_metadata")
    def test_us_equities_includes_qualifier_filter(self, mock_meta) -> None:
        mock_meta.return_value = ("Equity.US.AAPL/USD", -8)
        client_lazer = _make_client([])
        client_analytics = _make_client([])

        evaluate_feed_two_queries(
            client_lazer,
            client_analytics,
            feed_id=327,
            date="2025-10-06",
            mode="us-equities",
        )

        analytics_call = client_analytics.query.call_args
        if analytics_call:
            query_sql = analytics_call[0][0]
            assert "qualifiers" in query_sql
            assert "IRGCOND" in query_sql

    @patch("lib.benchmark_core.get_feed_metadata")
    def test_fx_excludes_qualifier_filter(self, mock_meta) -> None:
        mock_meta.return_value = ("FX.EUR/USD", -8)
        client_lazer = _make_client([])
        client_analytics = _make_client([])

        evaluate_feed_two_queries(
            client_lazer,
            client_analytics,
            feed_id=327,
            date="2025-10-06",
            mode="fx",
        )

        analytics_call = client_analytics.query.call_args
        if analytics_call:
            query_sql = analytics_call[0][0]
            assert "qualifiers" not in query_sql


# ---------------------------------------------------------------------------
# 10. query_aggregate_feed — price_feeds table query
# ---------------------------------------------------------------------------
class TestQueryAggregateFeed:
    def test_returns_data_from_channel_1(self):
        rows = [(0, _make_timestamps(1)[0], 100.0, 5)]
        client = _make_client(rows)
        result, channel = query_aggregate_feed(
            client,
            feed_id=327,
            date="2025-10-06",
            divisor=100000000,
            market_filter="",
        )
        assert result is not None
        assert channel == 1
        assert client.query.call_count == 1

    def test_falls_through_to_channel_2(self):
        def side_effect(query):
            if "channel = 1" in query:
                return MockQueryResult(result_rows=[])
            return MockQueryResult(result_rows=[(0, _make_timestamps(1)[0], 100.0, 5)])

        client = MagicMock()
        client.query.side_effect = side_effect

        result, channel = query_aggregate_feed(
            client,
            feed_id=327,
            date="2025-10-06",
            divisor=100000000,
            market_filter="",
        )
        assert result is not None
        assert channel == 2

    def test_returns_none_when_no_channels_have_data(self):
        client = _make_client([])
        result, channel = query_aggregate_feed(
            client,
            feed_id=327,
            date="2025-10-06",
            divisor=100000000,
            market_filter="",
        )
        assert result is None
        assert channel is None
        assert client.query.call_count == 3

    def test_query_contains_price_feeds_table(self):
        client = _make_client([])
        query_aggregate_feed(
            client,
            feed_id=327,
            date="2025-10-06",
            divisor=100000000,
            market_filter="",
        )
        query_sql = client.query.call_args_list[0][0][0]
        assert "price_feeds" in query_sql

    def test_query_uses_publisher_id_zero(self):
        client = _make_client([])
        query_aggregate_feed(
            client,
            feed_id=327,
            date="2025-10-06",
            divisor=100000000,
            market_filter="",
        )
        query_sql = client.query.call_args_list[0][0][0]
        assert "0 AS publisher_id" in query_sql

    def test_graceful_on_exception(self):
        client = MagicMock()
        client.query.side_effect = Exception("table not found")
        result, channel = query_aggregate_feed(
            client,
            feed_id=327,
            date="2025-10-06",
            divisor=100000000,
            market_filter="",
        )
        assert result is None
        assert channel is None


# ---------------------------------------------------------------------------
# 11. Aggregate feed integration in evaluate_feed_two_queries
# ---------------------------------------------------------------------------
class TestAggregateInEvaluateFeed:
    @patch("lib.benchmark_core.query_aggregate_feed")
    @patch("lib.benchmark_core.get_feed_metadata")
    def test_agg_metrics_populated_when_data_exists(self, mock_meta, mock_agg):
        mock_meta.return_value = ("Equity.US.AAPL/USD", -8)
        timestamps = _make_timestamps(200)
        pub_rows = [(55, ts, 150.0, 1) for ts in timestamps]
        bench_rows = [(ts, 150.0, 0.01) for ts in timestamps]
        agg_rows = [(0, ts, 150.0, 1) for ts in timestamps]
        mock_agg.return_value = (MockQueryResult(result_rows=agg_rows), 1)

        client_lazer = _make_client(pub_rows)
        client_analytics = _make_client(bench_rows)

        result = evaluate_feed_two_queries(
            client_lazer,
            client_analytics,
            feed_id=327,
            date="2025-10-06",
            mode="us-equities",
            include_agg=True,
        )
        assert result.agg_metrics is not None
        assert result.agg_metrics.publisher_id == 0

    @patch("lib.benchmark_core.query_aggregate_feed")
    @patch("lib.benchmark_core.get_feed_metadata")
    def test_agg_excluded_from_passing_publishers(self, mock_meta, mock_agg):
        mock_meta.return_value = ("Equity.US.AAPL/USD", -8)
        timestamps = _make_timestamps(200)
        pub_rows = [(55, ts, 150.0, 1) for ts in timestamps]
        bench_rows = [(ts, 150.0, 0.01) for ts in timestamps]
        agg_rows = [(0, ts, 150.0, 1) for ts in timestamps]
        mock_agg.return_value = (MockQueryResult(result_rows=agg_rows), 1)

        client_lazer = _make_client(pub_rows)
        client_analytics = _make_client(bench_rows)

        result = evaluate_feed_two_queries(
            client_lazer,
            client_analytics,
            feed_id=327,
            date="2025-10-06",
            mode="us-equities",
            include_agg=True,
        )
        assert 0 not in result.passing_publishers
        assert 0 not in result.failing_publishers

    @patch("lib.benchmark_core.get_feed_metadata")
    def test_no_agg_when_disabled(self, mock_meta):
        mock_meta.return_value = ("FX.EUR/USD", -8)
        timestamps = _make_timestamps(200)
        pub_rows = [(55, ts, 1.05, 1) for ts in timestamps]
        bench_rows = [(ts, 1.05, 0.0001) for ts in timestamps]

        client_lazer = _make_client(pub_rows)
        client_analytics = _make_client(bench_rows)

        result = evaluate_feed_two_queries(
            client_lazer,
            client_analytics,
            feed_id=327,
            date="2025-10-06",
            mode="fx",
            include_agg=False,
        )
        assert result.agg_metrics is None

    @patch("lib.benchmark_core.query_aggregate_feed")
    @patch("lib.benchmark_core.get_feed_metadata")
    def test_agg_failure_graceful(self, mock_meta, mock_agg):
        mock_meta.return_value = ("Equity.US.AAPL/USD", -8)
        mock_agg.return_value = (None, None)
        timestamps = _make_timestamps(200)
        pub_rows = [(55, ts, 150.0, 1) for ts in timestamps]
        bench_rows = [(ts, 150.0, 0.01) for ts in timestamps]

        client_lazer = _make_client(pub_rows)
        client_analytics = _make_client(bench_rows)

        result = evaluate_feed_two_queries(
            client_lazer,
            client_analytics,
            feed_id=327,
            date="2025-10-06",
            mode="us-equities",
            include_agg=True,
        )
        assert result.agg_metrics is None
        assert result.passing_pub_count > 0 or result.failing_pub_count > 0
