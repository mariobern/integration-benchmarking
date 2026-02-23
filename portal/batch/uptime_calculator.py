"""
Uptime calculation using 200ms gap-based method.

This calculator measures uptime by detecting gaps between consecutive updates.
Any gap longer than 200ms contributes to downtime. This matches the methodology
used in the research repo's feed_reliability_tests.py (with 200ms threshold).

Gap-based calculation:
- Orders all updates by time
- Calculates gap between consecutive updates
- Gap > 200ms → downtime += (gap - 200ms)
- Also accounts for gaps at period start/end
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

import clickhouse_connect

from portal.config import settings


# Gap threshold in milliseconds - any gap larger than this is considered downtime
DEFAULT_GAP_THRESHOLD_MS = 200


def _validate_int(value: int, name: str) -> int:
    """Validate that a value is a non-negative integer to prevent injection."""
    if not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer, got {value!r}")
    return value


@dataclass(frozen=True)
class UptimeResult:
    """Result of uptime calculation for a single feed."""

    uptime_pct: float  # 0-100 percentage
    downtime_ms: int  # Total downtime in milliseconds
    period_length_ms: int  # Total period length in milliseconds
    updates_total: int  # Total update count
    updates_per_second: float  # Average update rate
    max_gap_ms: Optional[int] = None  # Maximum gap between updates
    gaps_over_threshold: int = 0  # Count of gaps exceeding threshold


class UptimeCalculator:
    """
    Uptime calculation using 200ms gap-based method.

    Measures actual gaps between consecutive updates. Any gap > 200ms
    contributes to downtime. This is more accurate than window-based
    methods which can show 100% even with significant sub-second gaps.
    """

    def __init__(self, client=None, gap_threshold_ms: int = DEFAULT_GAP_THRESHOLD_MS):
        """
        Initialize the uptime calculator.

        Args:
            client: Optional ClickHouse client. If not provided, creates one.
            gap_threshold_ms: Maximum allowed gap between updates (default: 200ms).
                             Gaps larger than this contribute to downtime.
        """
        self._client = client
        self._gap_threshold_ms = gap_threshold_ms

    @property
    def client(self):
        """Lazily initialize ClickHouse client."""
        if self._client is None:
            config = settings.get_clickhouse_lazer_config()
            self._client = clickhouse_connect.get_client(**config)
        return self._client

    def compute_feed_uptime(
        self,
        publisher_id: int,
        feed_id: int,
        start_utc: datetime,
        end_utc: datetime,
    ) -> UptimeResult:
        """
        Compute uptime for a single feed using gap-based method.

        Args:
            publisher_id: Publisher ID
            feed_id: Price feed ID
            start_utc: Start time (UTC)
            end_utc: End time (UTC)

        Returns:
            UptimeResult with uptime metrics
        """
        # Validate inputs to prevent injection
        _validate_int(publisher_id, "publisher_id")
        _validate_int(feed_id, "feed_id")

        return self._compute_gap_based(publisher_id, feed_id, start_utc, end_utc)

    def _compute_gap_based(
        self,
        publisher_id: int,
        feed_id: int,
        start_utc: datetime,
        end_utc: datetime,
    ) -> UptimeResult:
        """
        Compute uptime using accurate gap-based calculation.

        Any gap between consecutive updates > gap_threshold_ms is counted as downtime.
        """
        start_str = start_utc.strftime("%Y-%m-%d %H:%M:%S")
        end_str = end_utc.strftime("%Y-%m-%d %H:%M:%S")
        gap_threshold = self._gap_threshold_ms

        query = f"""
            WITH
                parseDateTimeBestEffort('{start_str}') AS start_time,
                parseDateTimeBestEffort('{end_str}') AS end_time,
                dateDiff('millisecond', start_time, end_time) AS total_time_ms,

                -- Get ordered updates with lag to calculate gaps
                updates AS (
                    SELECT
                        publish_time,
                        lagInFrame(publish_time, 1) OVER (ORDER BY publish_time) AS prev_time,
                        row_number() OVER (ORDER BY publish_time) AS rn
                    FROM publisher_updates
                    PREWHERE price_feed_id = {feed_id}
                        AND publisher_id = {publisher_id}
                    WHERE publish_time >= start_time
                        AND publish_time <= end_time
                ),

                -- Calculate gaps between consecutive updates
                gaps AS (
                    SELECT
                        publish_time,
                        prev_time,
                        CASE
                            WHEN prev_time IS NOT NULL THEN
                                dateDiff('millisecond',
                                    if(prev_time < start_time, start_time, prev_time),
                                    publish_time)
                            ELSE 0
                        END AS gap_ms
                    FROM updates
                ),

                -- Aggregate gap statistics
                gap_stats AS (
                    SELECT
                        count() AS total_updates,
                        min(publish_time) AS first_update,
                        max(publish_time) AS last_update,
                        max(gap_ms) AS max_gap_ms,
                        countIf(gap_ms > {gap_threshold}) AS gaps_over_threshold,
                        sum(greatest(0, gap_ms - {gap_threshold})) AS consecutive_downtime_ms
                    FROM gaps
                )

            SELECT
                total_updates,
                max_gap_ms,
                gaps_over_threshold,
                consecutive_downtime_ms,
                -- Downtime from start to first update
                greatest(0, dateDiff('millisecond', start_time, first_update) - {gap_threshold}) AS start_gap_ms,
                -- Downtime from last update to end
                greatest(0, dateDiff('millisecond', last_update, end_time) - {gap_threshold}) AS end_gap_ms,
                total_time_ms,
                -- Total downtime (capped at total period)
                least(
                    consecutive_downtime_ms +
                    greatest(0, dateDiff('millisecond', start_time, first_update) - {gap_threshold}) +
                    greatest(0, dateDiff('millisecond', last_update, end_time) - {gap_threshold}),
                    total_time_ms
                ) AS total_downtime_ms
            FROM gap_stats
        """

        result = self.client.query(query)
        rows = result.result_rows

        period_length_ms = int((end_utc - start_utc).total_seconds() * 1000)
        total_seconds = int((end_utc - start_utc).total_seconds())

        if not rows or rows[0][0] is None or rows[0][0] == 0:
            # No data found
            return UptimeResult(
                uptime_pct=0.0,
                downtime_ms=period_length_ms,
                period_length_ms=period_length_ms,
                updates_total=0,
                updates_per_second=0.0,
                max_gap_ms=None,
                gaps_over_threshold=0,
            )

        row = rows[0]
        updates_total = int(row[0] or 0)
        max_gap_ms = int(row[1]) if row[1] is not None else None
        gaps_over_threshold = int(row[2] or 0)
        total_downtime_ms = int(row[7] or 0)

        uptime_pct = (
            ((period_length_ms - total_downtime_ms) / period_length_ms * 100)
            if period_length_ms > 0
            else 0.0
        )

        return UptimeResult(
            uptime_pct=round(uptime_pct, 4),
            downtime_ms=total_downtime_ms,
            period_length_ms=period_length_ms,
            updates_total=updates_total,
            updates_per_second=round(updates_total / total_seconds, 2)
            if total_seconds > 0
            else 0.0,
            max_gap_ms=max_gap_ms,
            gaps_over_threshold=gaps_over_threshold,
        )

    def compute_batch_uptime(
        self,
        publisher_id: int,
        feed_ids: list[int],
        start_utc: datetime,
        end_utc: datetime,
    ) -> dict[int, UptimeResult]:
        """
        Compute uptime for multiple feeds using gap-based method.

        More efficient than calling compute_feed_uptime for each feed.

        Args:
            publisher_id: Publisher ID
            feed_ids: List of feed IDs
            start_utc: Start time (UTC)
            end_utc: End time (UTC)

        Returns:
            Dict mapping feed_id to UptimeResult
        """
        if not feed_ids:
            return {}

        # Validate inputs to prevent injection
        _validate_int(publisher_id, "publisher_id")
        for fid in feed_ids:
            _validate_int(fid, "feed_id")

        return self._compute_batch_gap_based(publisher_id, feed_ids, start_utc, end_utc)

    def _compute_batch_gap_based(
        self,
        publisher_id: int,
        feed_ids: list[int],
        start_utc: datetime,
        end_utc: datetime,
    ) -> dict[int, UptimeResult]:
        """Batch gap-based uptime computation."""
        start_str = start_utc.strftime("%Y-%m-%d %H:%M:%S")
        end_str = end_utc.strftime("%Y-%m-%d %H:%M:%S")
        feed_id_list = ", ".join(str(fid) for fid in feed_ids)
        gap_threshold = self._gap_threshold_ms

        query = f"""
            WITH
                parseDateTimeBestEffort('{start_str}') AS start_time,
                parseDateTimeBestEffort('{end_str}') AS end_time,
                dateDiff('millisecond', start_time, end_time) AS total_time_ms,

                -- Get ordered updates with lag, partitioned by feed
                updates AS (
                    SELECT
                        price_feed_id,
                        publish_time,
                        lagInFrame(publish_time, 1) OVER (
                            PARTITION BY price_feed_id
                            ORDER BY publish_time
                        ) AS prev_time
                    FROM publisher_updates
                    PREWHERE publisher_id = {publisher_id}
                        AND price_feed_id IN ({feed_id_list})
                    WHERE publish_time >= start_time
                        AND publish_time <= end_time
                ),

                -- Calculate gaps
                gaps AS (
                    SELECT
                        price_feed_id,
                        publish_time,
                        CASE
                            WHEN prev_time IS NOT NULL THEN
                                dateDiff('millisecond',
                                    if(prev_time < start_time, start_time, prev_time),
                                    publish_time)
                            ELSE 0
                        END AS gap_ms
                    FROM updates
                ),

                -- Aggregate per feed
                feed_stats AS (
                    SELECT
                        price_feed_id,
                        count() AS total_updates,
                        min(publish_time) AS first_update,
                        max(publish_time) AS last_update,
                        max(gap_ms) AS max_gap_ms,
                        countIf(gap_ms > {gap_threshold}) AS gaps_over_threshold,
                        sum(greatest(0, gap_ms - {gap_threshold})) AS consecutive_downtime_ms
                    FROM gaps
                    GROUP BY price_feed_id
                )

            SELECT
                price_feed_id,
                total_updates,
                max_gap_ms,
                gaps_over_threshold,
                consecutive_downtime_ms,
                greatest(0, dateDiff('millisecond', start_time, first_update) - {gap_threshold}) AS start_gap_ms,
                greatest(0, dateDiff('millisecond', last_update, end_time) - {gap_threshold}) AS end_gap_ms,
                total_time_ms,
                least(
                    consecutive_downtime_ms +
                    greatest(0, dateDiff('millisecond', start_time, first_update) - {gap_threshold}) +
                    greatest(0, dateDiff('millisecond', last_update, end_time) - {gap_threshold}),
                    total_time_ms
                ) AS total_downtime_ms
            FROM feed_stats
        """

        result = self.client.query(query)
        period_length_ms = int((end_utc - start_utc).total_seconds() * 1000)
        total_seconds = int((end_utc - start_utc).total_seconds())

        results: dict[int, UptimeResult] = {}

        # Initialize all feeds with zero uptime
        for feed_id in feed_ids:
            results[feed_id] = UptimeResult(
                uptime_pct=0.0,
                downtime_ms=period_length_ms,
                period_length_ms=period_length_ms,
                updates_total=0,
                updates_per_second=0.0,
                max_gap_ms=None,
                gaps_over_threshold=0,
            )

        # Update with actual data
        for row in result.result_rows:
            feed_id = int(row[0])
            updates_total = int(row[1] or 0)
            max_gap_ms = int(row[2]) if row[2] is not None else None
            gaps_over_threshold = int(row[3] or 0)
            total_downtime_ms = int(row[8] or 0)

            uptime_pct = (
                ((period_length_ms - total_downtime_ms) / period_length_ms * 100)
                if period_length_ms > 0
                else 0.0
            )

            results[feed_id] = UptimeResult(
                uptime_pct=round(uptime_pct, 4),
                downtime_ms=total_downtime_ms,
                period_length_ms=period_length_ms,
                updates_total=updates_total,
                updates_per_second=round(updates_total / total_seconds, 2)
                if total_seconds > 0
                else 0.0,
                max_gap_ms=max_gap_ms,
                gaps_over_threshold=gaps_over_threshold,
            )

        return results
