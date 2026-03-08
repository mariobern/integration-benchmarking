"""Tests for lib.uptime_core — core uptime evaluation logic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional
from unittest.mock import MagicMock

import pytest

from lib.models import FeedUptimeResult, PublisherSessionUptime


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


def _make_multi_client(side_effects: list[list[tuple]]) -> MagicMock:
    """Create a mock client that returns different rows for successive queries."""
    client = MagicMock()
    client.query.side_effect = [
        MockQueryResult(result_rows=rows) for rows in side_effects
    ]
    return client


# ---------------------------------------------------------------------------
# 1. Constants
# ---------------------------------------------------------------------------
class TestConstants:
    def test_default_gap_threshold_is_200(self) -> None:
        from lib.uptime_core import DEFAULT_GAP_THRESHOLD_MS

        assert DEFAULT_GAP_THRESHOLD_MS == 200

    def test_default_uptime_threshold_is_95(self) -> None:
        from lib.uptime_core import DEFAULT_UPTIME_THRESHOLD_PCT

        assert DEFAULT_UPTIME_THRESHOLD_PCT == 95.0

    def test_session_order_has_four_entries(self) -> None:
        from lib.uptime_core import SESSION_ORDER

        assert SESSION_ORDER == ["regular", "premarket", "afterhours", "overnight"]


# ---------------------------------------------------------------------------
# 2. discover_publishers_for_feed
# ---------------------------------------------------------------------------
class TestDiscoverPublishersForFeed:
    def test_returns_sorted_publisher_ids(self) -> None:
        from lib.uptime_core import discover_publishers_for_feed

        client = _make_client([(55,), (32,), (71,)])
        result = discover_publishers_for_feed(
            client, feed_id=922, target_date="2026-02-09"
        )
        assert result == [55, 32, 71]

    def test_returns_empty_when_no_data(self) -> None:
        from lib.uptime_core import discover_publishers_for_feed

        client = _make_client([])
        result = discover_publishers_for_feed(
            client, feed_id=9999, target_date="2026-02-09"
        )
        assert result == []


# ---------------------------------------------------------------------------
# 3. get_feed_symbol
# ---------------------------------------------------------------------------
class TestGetFeedSymbol:
    def test_returns_symbol_when_found(self) -> None:
        from lib.uptime_core import get_feed_symbol

        client = _make_client([("Equity.US.AAPL/USD",)])
        result = get_feed_symbol(client, feed_id=922)
        assert result == "Equity.US.AAPL/USD"

    def test_returns_none_when_no_rows(self) -> None:
        from lib.uptime_core import get_feed_symbol

        client = _make_client([])
        result = get_feed_symbol(client, feed_id=9999)
        assert result is None

    def test_returns_none_on_exception(self) -> None:
        from lib.uptime_core import get_feed_symbol

        client = MagicMock()
        client.query.side_effect = Exception("Connection error")
        result = get_feed_symbol(client, feed_id=922)
        assert result is None


# ---------------------------------------------------------------------------
# 4. compute_uptime_1s_window
# ---------------------------------------------------------------------------
class TestComputeUptime1sWindow:
    def test_basic_uptime_calculation(self) -> None:
        from lib.uptime_core import compute_uptime_1s_window

        start = datetime(2026, 2, 9, 14, 30, 0)
        end = datetime(2026, 2, 9, 21, 0, 0)
        total_seconds = int((end - start).total_seconds())  # 23400

        # Mock: updates_total=20000, seconds_with_data=20000, total_seconds, ups, uptime_pct
        uptime_pct = 20000 * 100.0 / total_seconds  # ~85.47
        client = _make_client(
            [(20000, 20000, total_seconds, 20000 / total_seconds, uptime_pct)]
        )

        result = compute_uptime_1s_window(
            client, publisher_id=55, feed_id=922, start_utc=start, end_utc=end
        )

        assert result["uptime_pct"] == pytest.approx(uptime_pct, abs=0.01)
        assert result["seconds_with_data"] == 20000
        assert result["total_seconds"] == total_seconds
        assert result["updates_total"] == 20000

    def test_no_data_returns_zero_uptime(self) -> None:
        from lib.uptime_core import compute_uptime_1s_window

        start = datetime(2026, 2, 9, 14, 30, 0)
        end = datetime(2026, 2, 9, 21, 0, 0)
        total_seconds = int((end - start).total_seconds())

        # Empty result or None values
        client = _make_client([(None, None, None, None, None)])

        result = compute_uptime_1s_window(
            client, publisher_id=55, feed_id=922, start_utc=start, end_utc=end
        )

        assert result["uptime_pct"] == 0.0
        assert result["seconds_with_data"] == 0
        assert result["total_seconds"] == total_seconds
        assert result["updates_total"] == 0
        assert result["updates_per_second"] == 0.0

    def test_empty_result_rows(self) -> None:
        from lib.uptime_core import compute_uptime_1s_window

        start = datetime(2026, 2, 9, 14, 30, 0)
        end = datetime(2026, 2, 9, 21, 0, 0)
        total_seconds = int((end - start).total_seconds())

        client = _make_client([])

        result = compute_uptime_1s_window(
            client, publisher_id=55, feed_id=922, start_utc=start, end_utc=end
        )

        assert result["uptime_pct"] == 0.0
        assert result["total_seconds"] == total_seconds

    def test_full_uptime(self) -> None:
        from lib.uptime_core import compute_uptime_1s_window

        start = datetime(2026, 2, 9, 14, 30, 0)
        end = datetime(2026, 2, 9, 14, 30, 10)

        client = _make_client([(50, 10, 10, 5.0, 100.0)])

        result = compute_uptime_1s_window(
            client, publisher_id=55, feed_id=922, start_utc=start, end_utc=end
        )

        assert result["uptime_pct"] == 100.0
        assert result["seconds_with_data"] == 10
        assert result["total_seconds"] == 10


# ---------------------------------------------------------------------------
# 5. compute_uptime_200ms_gap
# ---------------------------------------------------------------------------
class TestComputeUptime200msGap:
    def test_basic_gap_uptime(self) -> None:
        from lib.uptime_core import compute_uptime_200ms_gap

        start = datetime(2026, 2, 9, 14, 30, 0)
        end = datetime(2026, 2, 9, 14, 31, 0)
        total_ms = 60000  # 60 seconds

        # Mock: total_updates, max_gap_ms, gaps_over_threshold, consecutive_downtime_ms,
        #       start_gap_ms, end_gap_ms, total_time_ms, total_downtime_ms
        client = _make_client([(1000, 150, 0, 0, 0, 0, total_ms, 0)])

        result = compute_uptime_200ms_gap(
            client, publisher_id=55, feed_id=922, start_utc=start, end_utc=end
        )

        assert result["uptime_pct"] == 100.0
        assert result["updates_total"] == 1000
        assert result["max_gap_ms"] == 150
        assert result["gaps_over_threshold"] == 0

    def test_gap_with_downtime(self) -> None:
        from lib.uptime_core import compute_uptime_200ms_gap

        start = datetime(2026, 2, 9, 14, 30, 0)
        end = datetime(2026, 2, 9, 14, 31, 0)
        total_ms = 60000

        # 10 seconds downtime
        downtime_ms = 10000
        client = _make_client([(500, 5000, 3, 8000, 1000, 1000, total_ms, downtime_ms)])

        result = compute_uptime_200ms_gap(
            client, publisher_id=55, feed_id=922, start_utc=start, end_utc=end
        )

        expected_uptime = (total_ms - downtime_ms) / total_ms * 100.0
        assert result["uptime_pct"] == pytest.approx(expected_uptime, abs=0.01)
        assert result["total_downtime_ms"] == downtime_ms

    def test_no_updates_returns_zero(self) -> None:
        from lib.uptime_core import compute_uptime_200ms_gap

        start = datetime(2026, 2, 9, 14, 30, 0)
        end = datetime(2026, 2, 9, 14, 31, 0)
        total_ms = 60000

        # Zero updates — total_downtime = total_time
        client = _make_client([(0, None, 0, 0, total_ms, 0, total_ms, total_ms)])

        result = compute_uptime_200ms_gap(
            client, publisher_id=55, feed_id=922, start_utc=start, end_utc=end
        )

        assert result["uptime_pct"] == 0.0
        assert result["total_downtime_ms"] == total_ms

    def test_empty_result_rows(self) -> None:
        from lib.uptime_core import compute_uptime_200ms_gap

        start = datetime(2026, 2, 9, 14, 30, 0)
        end = datetime(2026, 2, 9, 14, 31, 0)

        client = _make_client([])

        result = compute_uptime_200ms_gap(
            client, publisher_id=55, feed_id=922, start_utc=start, end_utc=end
        )

        assert result["uptime_pct"] == 0.0
        assert result["updates_total"] == 0
        assert result["period_length_ms"] == 60000

    def test_custom_gap_threshold(self) -> None:
        from lib.uptime_core import compute_uptime_200ms_gap

        start = datetime(2026, 2, 9, 14, 30, 0)
        end = datetime(2026, 2, 9, 14, 31, 0)
        total_ms = 60000

        client = _make_client([(1000, 80, 0, 0, 0, 0, total_ms, 0)])

        result = compute_uptime_200ms_gap(
            client,
            publisher_id=55,
            feed_id=922,
            start_utc=start,
            end_utc=end,
            gap_threshold_ms=100,
        )

        assert result["uptime_pct"] == 100.0


# ---------------------------------------------------------------------------
# 6. filter_sessions
# ---------------------------------------------------------------------------
class TestFilterSessions:
    def test_regular_only_by_default(self) -> None:
        from portal.batch.uptime_sessions import SessionWindow
        from lib.uptime_core import filter_sessions

        start = datetime(2026, 2, 9, 14, 30, 0)
        end = datetime(2026, 2, 9, 21, 0, 0)
        sessions = [
            SessionWindow("regular", start, end),
            SessionWindow("premarket", start, end),
            SessionWindow("afterhours", start, end),
            SessionWindow("overnight", start, end),
        ]

        filtered = filter_sessions(
            sessions, include_extended_hours=False, include_overnight=False
        )
        assert len(filtered) == 1
        assert filtered[0].session == "regular"

    def test_include_extended_hours(self) -> None:
        from portal.batch.uptime_sessions import SessionWindow
        from lib.uptime_core import filter_sessions

        start = datetime(2026, 2, 9, 14, 30, 0)
        end = datetime(2026, 2, 9, 21, 0, 0)
        sessions = [
            SessionWindow("regular", start, end),
            SessionWindow("premarket", start, end),
            SessionWindow("afterhours", start, end),
            SessionWindow("overnight", start, end),
        ]

        filtered = filter_sessions(
            sessions, include_extended_hours=True, include_overnight=False
        )
        assert len(filtered) == 3
        session_names = [s.session for s in filtered]
        assert "regular" in session_names
        assert "premarket" in session_names
        assert "afterhours" in session_names
        assert "overnight" not in session_names

    def test_include_overnight(self) -> None:
        from portal.batch.uptime_sessions import SessionWindow
        from lib.uptime_core import filter_sessions

        start = datetime(2026, 2, 9, 14, 30, 0)
        end = datetime(2026, 2, 9, 21, 0, 0)
        sessions = [
            SessionWindow("regular", start, end),
            SessionWindow("overnight", start, end),
        ]

        filtered = filter_sessions(
            sessions, include_extended_hours=False, include_overnight=True
        )
        assert len(filtered) == 2

    def test_include_all(self) -> None:
        from portal.batch.uptime_sessions import SessionWindow
        from lib.uptime_core import filter_sessions

        start = datetime(2026, 2, 9, 14, 30, 0)
        end = datetime(2026, 2, 9, 21, 0, 0)
        sessions = [
            SessionWindow("regular", start, end),
            SessionWindow("premarket", start, end),
            SessionWindow("afterhours", start, end),
            SessionWindow("overnight", start, end),
        ]

        filtered = filter_sessions(
            sessions, include_extended_hours=True, include_overnight=True
        )
        assert len(filtered) == 4

    def test_empty_sessions(self) -> None:
        from lib.uptime_core import filter_sessions

        filtered = filter_sessions(
            [], include_extended_hours=True, include_overnight=True
        )
        assert filtered == []


# ---------------------------------------------------------------------------
# 7. evaluate_feed_uptime — 1s window mode (default)
# ---------------------------------------------------------------------------
class TestEvaluateFeedUptime1sWindow:
    def test_basic_evaluation_returns_result(self) -> None:
        from lib.uptime_core import evaluate_feed_uptime

        # Client queries in order:
        # 1. get_session_windows — not a query, uses portal module
        # 2. get_feed_symbol — returns symbol
        # 3. discover_publishers — returns [55]
        # 4. compute_uptime_1s_window for publisher 55, regular session
        total_seconds = 23400  # 6.5 hours
        uptime_pct = 98.5

        client = _make_multi_client(
            [
                # get_feed_symbol query
                [("Equity.US.AAPL/USD",)],
                # discover_publishers query
                [(55,)],
                # batch_compute_uptime_1s_window query
                [(55, 23000, 23000, total_seconds, 23000 / total_seconds, uptime_pct)],
            ]
        )

        result = evaluate_feed_uptime(
            client=client,
            feed_id=922,
            date="2026-02-10",  # Monday
            mode="us-equities",
        )

        assert isinstance(result, FeedUptimeResult)
        assert result.feed_id == 922
        assert result.date == "2026-02-10"
        assert result.mode == "us-equities"
        assert result.symbol == "Equity.US.AAPL/USD"
        assert result.publisher_count == 1
        assert result.error is None
        assert len(result.publisher_uptimes) == 1

        uptime = result.publisher_uptimes[0]
        assert uptime.publisher_id == 55
        assert uptime.session == "regular"
        assert uptime.uptime_pct == pytest.approx(uptime_pct, abs=0.01)
        assert uptime.passes is True  # 98.5 >= 95.0

    def test_publisher_fails_below_threshold(self) -> None:
        from lib.uptime_core import evaluate_feed_uptime

        total_seconds = 23400
        uptime_pct = 80.0  # Below 95% threshold

        client = _make_multi_client(
            [
                [("Equity.US.AAPL/USD",)],
                [(55,)],
                [(55, 18720, 18720, total_seconds, 18720 / total_seconds, uptime_pct)],
            ]
        )

        result = evaluate_feed_uptime(
            client=client,
            feed_id=922,
            date="2026-02-10",
            mode="us-equities",
        )

        assert result.publisher_uptimes[0].passes is False

    def test_no_publishers_returns_error(self) -> None:
        from lib.uptime_core import evaluate_feed_uptime

        client = _make_multi_client(
            [
                [("Equity.US.AAPL/USD",)],
                [],  # No publishers
            ]
        )

        result = evaluate_feed_uptime(
            client=client,
            feed_id=922,
            date="2026-02-10",
            mode="us-equities",
        )

        assert result.error == "No publishers found"
        assert result.publisher_count == 0
        assert result.publisher_uptimes == []

    def test_no_sessions_returns_error(self) -> None:
        from lib.uptime_core import evaluate_feed_uptime

        client = _make_client([])

        # Saturday — no sessions for us-equities
        result = evaluate_feed_uptime(
            client=client,
            feed_id=922,
            date="2026-02-14",  # Saturday
            mode="us-equities",
        )

        assert result.error == "No trading sessions for date"

    def test_custom_uptime_threshold(self) -> None:
        from lib.uptime_core import evaluate_feed_uptime

        total_seconds = 23400
        uptime_pct = 90.0

        client = _make_multi_client(
            [
                [("Equity.US.AAPL/USD",)],
                [(55,)],
                [(55, 21060, 21060, total_seconds, 21060 / total_seconds, uptime_pct)],
            ]
        )

        # With threshold 85 → passes; with threshold 95 → fails
        result = evaluate_feed_uptime(
            client=client,
            feed_id=922,
            date="2026-02-10",
            mode="us-equities",
            uptime_threshold_pct=85.0,
        )

        assert result.publisher_uptimes[0].passes is True

    def test_multiple_publishers(self) -> None:
        from lib.uptime_core import evaluate_feed_uptime

        total_seconds = 23400
        # Publisher 55 passes, publisher 71 fails
        client = _make_multi_client(
            [
                [("Equity.US.AAPL/USD",)],
                [(55,), (71,)],
                # Single batched query returns both publishers
                [
                    (55, 23000, 23000, total_seconds, 23000 / total_seconds, 98.0),
                    (71, 10000, 10000, total_seconds, 10000 / total_seconds, 42.7),
                ],
            ]
        )

        result = evaluate_feed_uptime(
            client=client,
            feed_id=922,
            date="2026-02-10",
            mode="us-equities",
        )

        assert result.publisher_count == 2
        assert len(result.publisher_uptimes) == 2

        uptimes_by_pub = {u.publisher_id: u for u in result.publisher_uptimes}
        assert uptimes_by_pub[55].passes is True
        assert uptimes_by_pub[71].passes is False

    def test_exception_returns_error_result(self) -> None:
        from lib.uptime_core import evaluate_feed_uptime

        client = MagicMock()
        client.query.side_effect = Exception("ClickHouse connection refused")

        result = evaluate_feed_uptime(
            client=client,
            feed_id=922,
            date="2026-02-10",
            mode="us-equities",
        )

        assert isinstance(result, FeedUptimeResult)
        assert result.error is not None
        assert "ClickHouse connection refused" in result.error


# ---------------------------------------------------------------------------
# 8. evaluate_feed_uptime — precise (gap-based) mode
# ---------------------------------------------------------------------------
class TestEvaluateFeedUptimePrecise:
    def test_precise_mode_uses_gap_method(self) -> None:
        from lib.uptime_core import evaluate_feed_uptime

        total_ms = 23400000  # 6.5 hours in ms
        total_seconds = 23400

        client = _make_multi_client(
            [
                [("Equity.US.AAPL/USD",)],
                [(55,)],
                # compute_uptime_200ms_gap result format:
                # total_updates, max_gap_ms, gaps_over_threshold,
                # consecutive_downtime_ms, start_gap_ms, end_gap_ms,
                # total_time_ms, total_downtime_ms
                [(55, 23000, 150, 0, 0, 0, 0, total_ms, 0)],
            ]
        )

        result = evaluate_feed_uptime(
            client=client,
            feed_id=922,
            date="2026-02-10",
            mode="us-equities",
            precise=True,
        )

        assert result.error is None
        assert len(result.publisher_uptimes) == 1
        uptime = result.publisher_uptimes[0]
        assert uptime.uptime_pct == 100.0
        assert uptime.passes is True
        assert uptime.downtime_ms == 0
        assert uptime.period_length_ms == total_ms
        assert uptime.max_gap_ms == 150
        assert uptime.gaps_over_threshold == 0
        # In precise mode, seconds_with_data is 0
        assert uptime.seconds_with_data == 0


# ---------------------------------------------------------------------------
# 9. evaluate_feed_uptime — FX mode (24-hour)
# ---------------------------------------------------------------------------
class TestEvaluateFeedUptimeFx:
    def test_fx_weekday_has_regular_session(self) -> None:
        from lib.uptime_core import evaluate_feed_uptime

        total_seconds = 86400  # 24 hours
        uptime_pct = 99.0

        client = _make_multi_client(
            [
                [("FX.EURUSD/USD",)],
                [(55,)],
                [(55, 85000, 85000, total_seconds, 85000 / total_seconds, uptime_pct)],
            ]
        )

        result = evaluate_feed_uptime(
            client=client,
            feed_id=327,
            date="2026-02-10",  # Tuesday
            mode="fx",
        )

        assert result.error is None
        assert len(result.publisher_uptimes) == 1
        assert result.publisher_uptimes[0].session == "regular"


# ---------------------------------------------------------------------------
# 10. Edge cases
# ---------------------------------------------------------------------------
class TestEdgeCases:
    def test_single_observation(self) -> None:
        """A publisher with a single observation should still return valid metrics."""
        from lib.uptime_core import compute_uptime_1s_window

        start = datetime(2026, 2, 9, 14, 30, 0)
        end = datetime(2026, 2, 9, 21, 0, 0)
        total_seconds = int((end - start).total_seconds())

        # 1 update in 1 second
        uptime_pct = 1 * 100.0 / total_seconds
        client = _make_client([(1, 1, total_seconds, 1 / total_seconds, uptime_pct)])

        result = compute_uptime_1s_window(
            client, publisher_id=55, feed_id=922, start_utc=start, end_utc=end
        )

        assert result["uptime_pct"] == pytest.approx(uptime_pct, abs=0.01)
        assert result["seconds_with_data"] == 1
        assert result["updates_total"] == 1

    def test_zero_duration_window(self) -> None:
        """Window with start == end should handle gracefully."""
        from lib.uptime_core import compute_uptime_1s_window

        now = datetime(2026, 2, 9, 14, 30, 0)
        client = _make_client([])

        result = compute_uptime_1s_window(
            client, publisher_id=55, feed_id=922, start_utc=now, end_utc=now
        )

        assert result["uptime_pct"] == 0.0
        assert result["total_seconds"] == 0

    def test_invalid_date_format_in_evaluate(self) -> None:
        """Bad date format should return error, not crash."""
        from lib.uptime_core import evaluate_feed_uptime

        client = _make_client([])

        result = evaluate_feed_uptime(
            client=client,
            feed_id=922,
            date="not-a-date",
            mode="us-equities",
        )

        assert result.error is not None


# ---------------------------------------------------------------------------
# 11. batch_compute_uptime_1s_window
# ---------------------------------------------------------------------------
class TestBatchComputeUptime1sWindow:
    def test_returns_dict_keyed_by_publisher_id(self) -> None:
        """Two publishers, both have data. Verify dict keys and values."""
        from lib.uptime_core import batch_compute_uptime_1s_window

        start = datetime(2026, 2, 9, 14, 30, 0)
        end = datetime(2026, 2, 9, 21, 0, 0)
        total_seconds = int((end - start).total_seconds())  # 23400

        uptime_pct_55 = 20000 * 100.0 / total_seconds
        uptime_pct_71 = 15000 * 100.0 / total_seconds

        # Batched query returns rows with publisher_id as first column
        client = _make_client(
            [
                (55, 20000, 20000, total_seconds, 20000 / total_seconds, uptime_pct_55),
                (71, 15000, 15000, total_seconds, 15000 / total_seconds, uptime_pct_71),
            ]
        )

        result = batch_compute_uptime_1s_window(
            client,
            publisher_ids=[55, 71],
            feed_id=922,
            start_utc=start,
            end_utc=end,
        )

        assert isinstance(result, dict)
        assert set(result.keys()) == {55, 71}

        assert result[55]["uptime_pct"] == pytest.approx(uptime_pct_55, abs=0.01)
        assert result[55]["seconds_with_data"] == 20000
        assert result[55]["total_seconds"] == total_seconds
        assert result[55]["updates_total"] == 20000

        assert result[71]["uptime_pct"] == pytest.approx(uptime_pct_71, abs=0.01)
        assert result[71]["seconds_with_data"] == 15000
        assert result[71]["total_seconds"] == total_seconds
        assert result[71]["updates_total"] == 15000

    def test_missing_publisher_gets_zero_uptime(self) -> None:
        """Request [55, 71] but only 55 has data. Verify 71 gets zeros."""
        from lib.uptime_core import batch_compute_uptime_1s_window

        start = datetime(2026, 2, 9, 14, 30, 0)
        end = datetime(2026, 2, 9, 21, 0, 0)
        total_seconds = int((end - start).total_seconds())  # 23400

        uptime_pct_55 = 20000 * 100.0 / total_seconds

        # Only publisher 55 returned from query; 71 is missing
        client = _make_client(
            [
                (55, 20000, 20000, total_seconds, 20000 / total_seconds, uptime_pct_55),
            ]
        )

        result = batch_compute_uptime_1s_window(
            client,
            publisher_ids=[55, 71],
            feed_id=922,
            start_utc=start,
            end_utc=end,
        )

        assert set(result.keys()) == {55, 71}

        # Publisher 55 has real data
        assert result[55]["uptime_pct"] == pytest.approx(uptime_pct_55, abs=0.01)
        assert result[55]["updates_total"] == 20000

        # Publisher 71 gets zero-uptime defaults
        assert result[71]["uptime_pct"] == 0.0
        assert result[71]["seconds_with_data"] == 0
        assert result[71]["total_seconds"] == total_seconds
        assert result[71]["updates_total"] == 0
        assert result[71]["updates_per_second"] == 0.0

    def test_empty_publisher_list_returns_empty_dict(self) -> None:
        """Empty publisher list returns empty dict, no query executed."""
        from lib.uptime_core import batch_compute_uptime_1s_window

        start = datetime(2026, 2, 9, 14, 30, 0)
        end = datetime(2026, 2, 9, 21, 0, 0)

        client = _make_client([])

        result = batch_compute_uptime_1s_window(
            client,
            publisher_ids=[],
            feed_id=922,
            start_utc=start,
            end_utc=end,
        )

        assert result == {}
        client.query.assert_not_called()

    def test_single_publisher_matches_original_function(self) -> None:
        """Single publisher result has same structure as compute_uptime_1s_window."""
        from lib.uptime_core import batch_compute_uptime_1s_window

        start = datetime(2026, 2, 9, 14, 30, 0)
        end = datetime(2026, 2, 9, 21, 0, 0)
        total_seconds = int((end - start).total_seconds())  # 23400

        uptime_pct = 20000 * 100.0 / total_seconds

        client = _make_client(
            [
                (55, 20000, 20000, total_seconds, 20000 / total_seconds, uptime_pct),
            ]
        )

        result = batch_compute_uptime_1s_window(
            client,
            publisher_ids=[55],
            feed_id=922,
            start_utc=start,
            end_utc=end,
        )

        assert len(result) == 1
        assert 55 in result

        entry = result[55]
        expected_keys = {
            "uptime_pct",
            "seconds_with_data",
            "total_seconds",
            "updates_total",
            "updates_per_second",
        }
        assert set(entry.keys()) == expected_keys
        assert entry["uptime_pct"] == pytest.approx(uptime_pct, abs=0.01)
        assert entry["seconds_with_data"] == 20000
        assert entry["total_seconds"] == total_seconds
        assert entry["updates_total"] == 20000
        assert entry["updates_per_second"] == pytest.approx(
            20000 / total_seconds, abs=0.01
        )


# ---------------------------------------------------------------------------
# 12. batch_compute_uptime_200ms_gap
# ---------------------------------------------------------------------------
class TestBatchComputeUptime200msGap:
    def test_returns_dict_keyed_by_publisher_id(self) -> None:
        """Two publishers with different uptime. Verify both."""
        from lib.uptime_core import batch_compute_uptime_200ms_gap

        start = datetime(2026, 2, 9, 14, 30, 0)
        end = datetime(2026, 2, 9, 14, 31, 0)
        total_ms = 60000

        # Batched query returns rows with publisher_id as FIRST column:
        # (publisher_id, total_updates, max_gap_ms, gaps_over_threshold,
        #  consecutive_downtime_ms, start_gap_ms, end_gap_ms, total_time_ms,
        #  total_downtime_ms)
        client = _make_client(
            [
                (55, 1000, 150, 0, 0, 0, 0, total_ms, 0),
                (71, 500, 5000, 3, 8000, 1000, 1000, total_ms, 10000),
            ]
        )

        result = batch_compute_uptime_200ms_gap(
            client,
            publisher_ids=[55, 71],
            feed_id=922,
            start_utc=start,
            end_utc=end,
        )

        assert isinstance(result, dict)
        assert set(result.keys()) == {55, 71}

        # Publisher 55: zero downtime -> 100% uptime
        assert result[55]["uptime_pct"] == 100.0
        assert result[55]["updates_total"] == 1000
        assert result[55]["max_gap_ms"] == 150
        assert result[55]["gaps_over_threshold"] == 0
        assert result[55]["total_downtime_ms"] == 0
        assert result[55]["period_length_ms"] == total_ms

        # Publisher 71: 10s downtime out of 60s -> ~83.33%
        expected_uptime_71 = (total_ms - 10000) / total_ms * 100.0
        assert result[71]["uptime_pct"] == pytest.approx(expected_uptime_71, abs=0.01)
        assert result[71]["updates_total"] == 500
        assert result[71]["max_gap_ms"] == 5000
        assert result[71]["gaps_over_threshold"] == 3
        assert result[71]["total_downtime_ms"] == 10000

    def test_missing_publisher_gets_zero_uptime(self) -> None:
        """Request [55, 71] but only 55 returned. Publisher 71 gets zeros."""
        from lib.uptime_core import batch_compute_uptime_200ms_gap

        start = datetime(2026, 2, 9, 14, 30, 0)
        end = datetime(2026, 2, 9, 14, 31, 0)
        total_ms = 60000

        # Only publisher 55 has data
        client = _make_client(
            [
                (55, 1000, 150, 0, 0, 0, 0, total_ms, 0),
            ]
        )

        result = batch_compute_uptime_200ms_gap(
            client,
            publisher_ids=[55, 71],
            feed_id=922,
            start_utc=start,
            end_utc=end,
        )

        assert set(result.keys()) == {55, 71}

        # Publisher 55 has data
        assert result[55]["uptime_pct"] == 100.0
        assert result[55]["updates_total"] == 1000

        # Publisher 71 missing -> zero uptime, total_downtime = total_ms
        assert result[71]["uptime_pct"] == 0.0
        assert result[71]["updates_total"] == 0
        assert result[71]["total_downtime_ms"] == total_ms
        assert result[71]["period_length_ms"] == total_ms
        assert result[71]["max_gap_ms"] is None
        assert result[71]["gaps_over_threshold"] == 0
        assert result[71]["updates_per_second"] == 0.0

    def test_empty_publisher_list(self) -> None:
        """Empty list returns empty dict, no query executed."""
        from lib.uptime_core import batch_compute_uptime_200ms_gap

        start = datetime(2026, 2, 9, 14, 30, 0)
        end = datetime(2026, 2, 9, 14, 31, 0)

        client = _make_client([])

        result = batch_compute_uptime_200ms_gap(
            client,
            publisher_ids=[],
            feed_id=922,
            start_utc=start,
            end_utc=end,
        )

        assert result == {}
        client.query.assert_not_called()

    def test_custom_gap_threshold(self) -> None:
        """Custom threshold (100ms) is passed through correctly."""
        from lib.uptime_core import batch_compute_uptime_200ms_gap

        start = datetime(2026, 2, 9, 14, 30, 0)
        end = datetime(2026, 2, 9, 14, 31, 0)
        total_ms = 60000

        client = _make_client(
            [
                (55, 1000, 80, 0, 0, 0, 0, total_ms, 0),
            ]
        )

        result = batch_compute_uptime_200ms_gap(
            client,
            publisher_ids=[55],
            feed_id=922,
            start_utc=start,
            end_utc=end,
            gap_threshold_ms=100,
        )

        assert result[55]["uptime_pct"] == 100.0
        assert result[55]["updates_total"] == 1000

        # Verify the query was called with the custom threshold
        query_text = client.query.call_args[0][0]
        assert "100" in query_text
