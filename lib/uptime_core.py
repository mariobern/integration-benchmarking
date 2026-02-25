"""Core uptime evaluation logic for Pyth Lazer feeds.

Extracted from feed_uptime.py to enable reuse across scripts
(feed_uptime.py, feed_readiness.py) without circular imports.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Optional

from lib.models import FeedUptimeResult, PublisherSessionUptime
from portal.batch.uptime_sessions import SessionWindow, get_session_windows

DEFAULT_GAP_THRESHOLD_MS = 200
DEFAULT_UPTIME_THRESHOLD_PCT = 95.0
SESSION_ORDER = ["regular", "premarket", "afterhours", "overnight"]


def discover_publishers_for_feed(client, feed_id: int, target_date: str) -> list[int]:
    """Discover distinct publishers that updated a feed on target date."""

    query = f"""
        SELECT DISTINCT publisher_id
        FROM publisher_updates
        WHERE price_feed_id = {feed_id}
          AND toDate(publish_time) = '{target_date}'
        ORDER BY publisher_id
    """
    result = client.query(query)
    return [int(row[0]) for row in result.result_rows]


def get_feed_symbol(client, feed_id: int) -> Optional[str]:
    """Lookup latest feed symbol from feeds_metadata_latest."""

    try:
        query = f"""
            SELECT symbol
            FROM feeds_metadata_latest
            FINAL
            WHERE pyth_lazer_id = {feed_id}
            ORDER BY updated_at DESC
            LIMIT 1
        """
        result = client.query(query)
        if result.result_rows:
            return result.result_rows[0][0]
    except Exception:
        return None
    return None


def compute_uptime_1s_window(
    client,
    publisher_id: int,
    feed_id: int,
    start_utc: datetime,
    end_utc: datetime,
) -> dict:
    """
    Compute uptime using 1-second window method.

    Uptime is the percentage of seconds containing at least one update.
    """
    start_str = start_utc.strftime("%Y-%m-%d %H:%M:%S")
    end_str = end_utc.strftime("%Y-%m-%d %H:%M:%S")

    query = f"""
        WITH
            parseDateTimeBestEffort('{start_str}') AS start_time,
            parseDateTimeBestEffort('{end_str}') AS end_time,
            dateDiff('second', start_time, end_time) AS total_seconds,
            per_second AS (
                SELECT
                    toStartOfSecond(publish_time) AS second_start,
                    count() AS update_count
                FROM publisher_updates
                PREWHERE price_feed_id = {feed_id}
                    AND publisher_id = {publisher_id}
                WHERE publish_time >= start_time
                    AND publish_time < end_time
                GROUP BY second_start
            )
        SELECT
            sum(update_count) AS updates_total,
            count() AS seconds_with_data,
            total_seconds,
            if(total_seconds = 0, 0, updates_total / total_seconds) AS updates_per_second,
            if(total_seconds = 0, 0, seconds_with_data * 100.0 / total_seconds) AS uptime_pct
        FROM per_second
    """
    result = client.query(query)

    total_seconds = int((end_utc - start_utc).total_seconds())
    if not result.result_rows or result.result_rows[0][0] is None:
        return {
            "uptime_pct": 0.0,
            "seconds_with_data": 0,
            "total_seconds": max(0, total_seconds),
            "updates_total": 0,
            "updates_per_second": 0.0,
        }

    row = result.result_rows[0]
    return {
        "uptime_pct": float(row[4] or 0),
        "seconds_with_data": int(row[1] or 0),
        "total_seconds": int(row[2] or 0),
        "updates_total": int(row[0] or 0),
        "updates_per_second": float(row[3] or 0),
    }


def compute_uptime_200ms_gap(
    client,
    publisher_id: int,
    feed_id: int,
    start_utc: datetime,
    end_utc: datetime,
    gap_threshold_ms: int = DEFAULT_GAP_THRESHOLD_MS,
) -> dict:
    """
    Compute uptime using accurate gap-based method.

    Any gap between consecutive updates > gap_threshold_ms is counted as downtime.
    """
    start_str = start_utc.strftime("%Y-%m-%d %H:%M:%S")
    end_str = end_utc.strftime("%Y-%m-%d %H:%M:%S")

    query = f"""
        WITH
            parseDateTimeBestEffort('{start_str}') AS start_time,
            parseDateTimeBestEffort('{end_str}') AS end_time,
            dateDiff('millisecond', start_time, end_time) AS total_time_ms,
            updates AS (
                SELECT
                    publish_time,
                    lagInFrame(publish_time, 1) OVER (ORDER BY publish_time) AS prev_time
                FROM publisher_updates
                PREWHERE price_feed_id = {feed_id}
                    AND publisher_id = {publisher_id}
                WHERE publish_time >= start_time
                    AND publish_time <= end_time
            ),
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
            gap_stats AS (
                SELECT
                    count() AS total_updates,
                    min(publish_time) AS first_update,
                    max(publish_time) AS last_update,
                    max(gap_ms) AS max_gap_ms,
                    countIf(gap_ms > {gap_threshold_ms}) AS gaps_over_threshold,
                    sum(greatest(0, gap_ms - {gap_threshold_ms})) AS consecutive_downtime_ms
                FROM gaps
            )
        SELECT
            total_updates,
            max_gap_ms,
            gaps_over_threshold,
            consecutive_downtime_ms,
            if(
                total_updates = 0,
                total_time_ms,
                greatest(0, dateDiff('millisecond', start_time, first_update) - {gap_threshold_ms})
            ) AS start_gap_ms,
            if(
                total_updates = 0,
                0,
                greatest(0, dateDiff('millisecond', last_update, end_time) - {gap_threshold_ms})
            ) AS end_gap_ms,
            total_time_ms,
            least(
                consecutive_downtime_ms +
                if(
                    total_updates = 0,
                    total_time_ms,
                    greatest(0, dateDiff('millisecond', start_time, first_update) - {gap_threshold_ms})
                ) +
                if(
                    total_updates = 0,
                    0,
                    greatest(0, dateDiff('millisecond', last_update, end_time) - {gap_threshold_ms})
                ),
                total_time_ms
            ) AS total_downtime_ms
        FROM gap_stats
    """
    result = client.query(query)

    if not result.result_rows:
        total_ms = int((end_utc - start_utc).total_seconds() * 1000)
        return {
            "uptime_pct": 0.0,
            "total_downtime_ms": total_ms,
            "period_length_ms": total_ms,
            "updates_total": 0,
            "updates_per_second": 0.0,
            "max_gap_ms": None,
            "gaps_over_threshold": 0,
        }

    row = result.result_rows[0]
    updates_total = int(row[0] or 0)
    max_gap_ms = int(row[1]) if row[1] is not None else None
    gaps_over_threshold = int(row[2] or 0)
    total_time_ms = int(row[6] or 0)

    if updates_total == 0:
        total_downtime_ms = total_time_ms
    else:
        total_downtime_ms = int(row[7] or 0)

    uptime_pct = (
        ((total_time_ms - total_downtime_ms) / total_time_ms * 100.0)
        if total_time_ms > 0
        else 0.0
    )
    updates_per_second = (
        (updates_total / (total_time_ms / 1000.0)) if total_time_ms > 0 else 0.0
    )

    return {
        "uptime_pct": uptime_pct,
        "total_downtime_ms": total_downtime_ms,
        "period_length_ms": total_time_ms,
        "updates_total": updates_total,
        "updates_per_second": updates_per_second,
        "max_gap_ms": max_gap_ms,
        "gaps_over_threshold": gaps_over_threshold,
    }


def filter_sessions(
    sessions: list[SessionWindow],
    include_extended_hours: bool,
    include_overnight: bool,
) -> list[SessionWindow]:
    """Filter session windows based on CLI flags."""

    filtered_sessions: list[SessionWindow] = []
    for window in sessions:
        if window.session in {"premarket", "afterhours"} and not include_extended_hours:
            continue
        if window.session == "overnight" and not include_overnight:
            continue
        filtered_sessions.append(window)
    return filtered_sessions


def evaluate_feed_uptime(
    client,
    feed_id: int,
    date: str,
    mode: str,
    include_extended_hours: bool = False,
    include_overnight: bool = False,
    precise: bool = False,
    gap_threshold_ms: int = DEFAULT_GAP_THRESHOLD_MS,
    uptime_threshold_pct: float = DEFAULT_UPTIME_THRESHOLD_PCT,
) -> FeedUptimeResult:
    """Evaluate per-publisher uptime for a single feed/date/mode."""

    start_time = time.time()
    symbol: Optional[str] = None

    try:
        target_date = datetime.strptime(date, "%Y-%m-%d").date()
        sessions = get_session_windows(mode, target_date)
        filtered_sessions = filter_sessions(
            sessions, include_extended_hours, include_overnight
        )

        if not filtered_sessions:
            return FeedUptimeResult(
                feed_id=feed_id,
                date=date,
                mode=mode,
                symbol=None,
                publisher_count=0,
                publisher_uptimes=[],
                error="No trading sessions for date",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        symbol = get_feed_symbol(client, feed_id)
        publishers = discover_publishers_for_feed(client, feed_id, date)
        if not publishers:
            return FeedUptimeResult(
                feed_id=feed_id,
                date=date,
                mode=mode,
                symbol=symbol,
                publisher_count=0,
                publisher_uptimes=[],
                error="No publishers found",
                execution_time_ms=int((time.time() - start_time) * 1000),
            )

        publisher_uptimes: list[PublisherSessionUptime] = []
        for publisher_id in publishers:
            for session_window in filtered_sessions:
                if precise:
                    uptime = compute_uptime_200ms_gap(
                        client=client,
                        publisher_id=publisher_id,
                        feed_id=feed_id,
                        start_utc=session_window.start_utc,
                        end_utc=session_window.end_utc,
                        gap_threshold_ms=gap_threshold_ms,
                    )
                    uptime_pct = uptime["uptime_pct"]
                    passes = uptime_pct >= uptime_threshold_pct
                    total_seconds = int(
                        (
                            session_window.end_utc - session_window.start_utc
                        ).total_seconds()
                    )
                    publisher_uptimes.append(
                        PublisherSessionUptime(
                            publisher_id=publisher_id,
                            session=session_window.session,
                            uptime_pct=uptime_pct,
                            passes=passes,
                            seconds_with_data=0,
                            total_seconds=total_seconds,
                            updates_total=uptime["updates_total"],
                            updates_per_second=uptime["updates_per_second"],
                            downtime_ms=uptime["total_downtime_ms"],
                            period_length_ms=uptime["period_length_ms"],
                            max_gap_ms=uptime["max_gap_ms"],
                            gaps_over_threshold=uptime["gaps_over_threshold"],
                        )
                    )
                else:
                    uptime = compute_uptime_1s_window(
                        client=client,
                        publisher_id=publisher_id,
                        feed_id=feed_id,
                        start_utc=session_window.start_utc,
                        end_utc=session_window.end_utc,
                    )
                    uptime_pct = uptime["uptime_pct"]
                    passes = uptime_pct >= uptime_threshold_pct
                    publisher_uptimes.append(
                        PublisherSessionUptime(
                            publisher_id=publisher_id,
                            session=session_window.session,
                            uptime_pct=uptime_pct,
                            passes=passes,
                            seconds_with_data=uptime["seconds_with_data"],
                            total_seconds=uptime["total_seconds"],
                            updates_total=uptime["updates_total"],
                            updates_per_second=uptime["updates_per_second"],
                            downtime_ms=None,
                            period_length_ms=None,
                            max_gap_ms=None,
                            gaps_over_threshold=None,
                        )
                    )

        return FeedUptimeResult(
            feed_id=feed_id,
            date=date,
            mode=mode,
            symbol=symbol,
            publisher_count=len(publishers),
            publisher_uptimes=publisher_uptimes,
            error=None,
            execution_time_ms=int((time.time() - start_time) * 1000),
        )
    except Exception as e:
        return FeedUptimeResult(
            feed_id=feed_id,
            date=date,
            mode=mode,
            symbol=symbol,
            publisher_count=0,
            publisher_uptimes=[],
            error=str(e),
            execution_time_ms=int((time.time() - start_time) * 1000),
        )
