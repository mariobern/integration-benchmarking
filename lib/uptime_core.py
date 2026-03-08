"""Core uptime evaluation logic for Pyth Lazer feeds.

Extracted from feed_uptime.py to enable reuse across scripts
(feed_uptime.py, feed_readiness.py) without circular imports.

Functions:
    discover_publishers_for_feed  - Find publishers for a feed on a date
    get_feed_symbol               - Lookup feed symbol from metadata
    compute_uptime_1s_window      - 1-second window uptime calculation
    compute_uptime_200ms_gap      - Gap-based uptime calculation
    filter_sessions               - Filter session windows by CLI flags
    evaluate_feed_uptime          - Per-publisher uptime for one feed/date/mode
    process_work_items            - Parallel execution of feed/date/mode tuples
    process_csv                   - CSV parsing + parallel execution
    compute_publisher_summary     - Cross-date publisher consistency summary
"""

from __future__ import annotations

import csv
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from typing import Optional

from lib.config import get_lazer_client, load_config, normalize_asset_class
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


def batch_compute_uptime_1s_window(
    client,
    publisher_ids: list[int],
    feed_id: int,
    start_utc: datetime,
    end_utc: datetime,
) -> dict[int, dict]:
    """
    Compute uptime using 1-second window method for multiple publishers in one query.

    Returns a dict keyed by publisher_id, each value matching the structure of
    compute_uptime_1s_window output. Publishers with no data get zero-uptime entries.
    """
    if not publisher_ids:
        return {}

    start_str = start_utc.strftime("%Y-%m-%d %H:%M:%S")
    end_str = end_utc.strftime("%Y-%m-%d %H:%M:%S")
    total_seconds = int((end_utc - start_utc).total_seconds())
    pub_list = ", ".join(str(pid) for pid in publisher_ids)

    query = f"""
        WITH
            parseDateTimeBestEffort('{start_str}') AS start_time,
            parseDateTimeBestEffort('{end_str}') AS end_time,
            dateDiff('second', start_time, end_time) AS total_seconds,
            per_second AS (
                SELECT
                    publisher_id,
                    toStartOfSecond(publish_time) AS second_start,
                    count() AS update_count
                FROM publisher_updates
                PREWHERE price_feed_id = {feed_id}
                    AND publisher_id IN ({pub_list})
                WHERE publish_time >= start_time
                    AND publish_time < end_time
                GROUP BY publisher_id, second_start
            )
        SELECT
            publisher_id,
            sum(update_count) AS updates_total,
            count() AS seconds_with_data,
            total_seconds,
            if(total_seconds = 0, 0, updates_total / total_seconds) AS updates_per_second,
            if(total_seconds = 0, 0, seconds_with_data * 100.0 / total_seconds) AS uptime_pct
        FROM per_second
        GROUP BY publisher_id, total_seconds
        ORDER BY publisher_id
    """
    result = client.query(query)

    results: dict[int, dict] = {}
    for row in result.result_rows:
        pid = int(row[0])
        results[pid] = {
            "uptime_pct": float(row[5] or 0),
            "seconds_with_data": int(row[2] or 0),
            "total_seconds": int(row[3] or 0),
            "updates_total": int(row[1] or 0),
            "updates_per_second": float(row[4] or 0),
        }

    # Fill in zero-uptime entries for publishers not in the query result
    for pid in publisher_ids:
        if pid not in results:
            results[pid] = {
                "uptime_pct": 0.0,
                "seconds_with_data": 0,
                "total_seconds": max(0, total_seconds),
                "updates_total": 0,
                "updates_per_second": 0.0,
            }

    return results


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


def batch_compute_uptime_200ms_gap(
    client,
    publisher_ids: list[int],
    feed_id: int,
    start_utc: datetime,
    end_utc: datetime,
    gap_threshold_ms: int = DEFAULT_GAP_THRESHOLD_MS,
) -> dict[int, dict]:
    """
    Compute uptime using gap-based method for multiple publishers in one query.

    Returns a dict keyed by publisher_id, each value matching the structure of
    compute_uptime_200ms_gap output. Publishers with no data get zero-uptime entries.
    """
    if not publisher_ids:
        return {}

    start_str = start_utc.strftime("%Y-%m-%d %H:%M:%S")
    end_str = end_utc.strftime("%Y-%m-%d %H:%M:%S")
    total_ms = int((end_utc - start_utc).total_seconds() * 1000)
    pub_list = ", ".join(str(pid) for pid in publisher_ids)

    query = f"""
        WITH
            parseDateTimeBestEffort('{start_str}') AS start_time,
            parseDateTimeBestEffort('{end_str}') AS end_time,
            dateDiff('millisecond', start_time, end_time) AS total_time_ms,
            updates AS (
                SELECT
                    publisher_id,
                    publish_time,
                    lagInFrame(publish_time, 1) OVER (
                        PARTITION BY publisher_id ORDER BY publish_time
                    ) AS prev_time
                FROM publisher_updates
                PREWHERE price_feed_id = {feed_id}
                    AND publisher_id IN ({pub_list})
                WHERE publish_time >= start_time
                    AND publish_time <= end_time
            ),
            gaps AS (
                SELECT
                    publisher_id,
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
                    publisher_id,
                    count() AS total_updates,
                    min(publish_time) AS first_update,
                    max(publish_time) AS last_update,
                    max(gap_ms) AS max_gap_ms,
                    countIf(gap_ms > {gap_threshold_ms}) AS gaps_over_threshold,
                    sum(greatest(0, gap_ms - {gap_threshold_ms})) AS consecutive_downtime_ms
                FROM gaps
                GROUP BY publisher_id
            )
        SELECT
            publisher_id,
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
        ORDER BY publisher_id
    """
    result = client.query(query)

    results: dict[int, dict] = {}
    for row in result.result_rows:
        pid = int(row[0])
        updates_total = int(row[1] or 0)
        max_gap_ms = int(row[2]) if row[2] is not None else None
        gaps_over_threshold = int(row[3] or 0)
        total_time_ms = int(row[7] or 0)

        if updates_total == 0:
            total_downtime_ms = total_time_ms
        else:
            total_downtime_ms = int(row[8] or 0)

        uptime_pct = (
            ((total_time_ms - total_downtime_ms) / total_time_ms * 100.0)
            if total_time_ms > 0
            else 0.0
        )
        updates_per_second = (
            (updates_total / (total_time_ms / 1000.0)) if total_time_ms > 0 else 0.0
        )

        results[pid] = {
            "uptime_pct": uptime_pct,
            "total_downtime_ms": total_downtime_ms,
            "period_length_ms": total_time_ms,
            "updates_total": updates_total,
            "updates_per_second": updates_per_second,
            "max_gap_ms": max_gap_ms,
            "gaps_over_threshold": gaps_over_threshold,
        }

    # Fill in zero-uptime entries for publishers not in the query result
    for pid in publisher_ids:
        if pid not in results:
            results[pid] = {
                "uptime_pct": 0.0,
                "total_downtime_ms": total_ms,
                "period_length_ms": total_ms,
                "updates_total": 0,
                "updates_per_second": 0.0,
                "max_gap_ms": None,
                "gaps_over_threshold": 0,
            }

    return results


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


def process_work_items(
    work_items: list[tuple[int, str, str]],
    max_workers: int,
    include_extended_hours: bool = False,
    include_overnight: bool = False,
    precise: bool = False,
    gap_threshold_ms: int = DEFAULT_GAP_THRESHOLD_MS,
    uptime_threshold_pct: float = DEFAULT_UPTIME_THRESHOLD_PCT,
) -> list[FeedUptimeResult]:
    """Evaluate a list of feed/date/mode tuples in parallel."""

    if not work_items:
        print("Warning: No feeds to process")
        return []

    config = load_config()
    worker_count = max(1, min(max_workers, len(work_items)))
    print(f"Processing {len(work_items)} feeds with {worker_count} workers...")

    def evaluate_single(item: tuple[int, str, str]) -> FeedUptimeResult:
        feed_id, date, mode = item
        start_time_ts = time.time()
        try:
            client = get_lazer_client(config)
            return evaluate_feed_uptime(
                client=client,
                feed_id=feed_id,
                date=date,
                mode=mode,
                include_extended_hours=include_extended_hours,
                include_overnight=include_overnight,
                precise=precise,
                gap_threshold_ms=gap_threshold_ms,
                uptime_threshold_pct=uptime_threshold_pct,
            )
        except Exception as e:
            return FeedUptimeResult(
                feed_id=feed_id,
                date=date,
                mode=mode,
                symbol=None,
                publisher_count=0,
                publisher_uptimes=[],
                error=str(e),
                execution_time_ms=int((time.time() - start_time_ts) * 1000),
            )

    results: list[FeedUptimeResult] = []
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = {executor.submit(evaluate_single, item): item for item in work_items}

        for future in as_completed(futures):
            feed_id, date, mode = futures[future]
            try:
                result = future.result()
            except Exception as e:
                result = FeedUptimeResult(
                    feed_id=feed_id,
                    date=date,
                    mode=mode,
                    symbol=None,
                    publisher_count=0,
                    publisher_uptimes=[],
                    error=str(e),
                    execution_time_ms=0,
                )
            results.append(result)

            if result.error:
                print(
                    f"  [{result.execution_time_ms:>5}ms] Feed {result.feed_id} "
                    f"({result.date}, {result.mode}): ERROR - {result.error[:80]}"
                )
                continue

            pass_count = sum(1 for u in result.publisher_uptimes if u.passes)
            fail_count = len(result.publisher_uptimes) - pass_count
            print(
                f"  [{result.execution_time_ms:>5}ms] Feed {result.feed_id} "
                f"({result.date}, {result.mode}): {result.publisher_count} publishers, "
                f"{pass_count} pass rows, {fail_count} fail rows"
            )

    return sorted(
        results, key=lambda r: (r.date, r.feed_id, normalize_asset_class(r.mode))
    )


def process_csv(
    csv_path: Path,
    max_workers: int,
    include_asset_classes: Optional[list[str]] = None,
    exclude_asset_classes: Optional[list[str]] = None,
    include_extended_hours: bool = False,
    include_overnight: bool = False,
    feed_id_filter: Optional[set[int]] = None,
    precise: bool = False,
    gap_threshold_ms: int = DEFAULT_GAP_THRESHOLD_MS,
    uptime_threshold_pct: float = DEFAULT_UPTIME_THRESHOLD_PCT,
) -> list[FeedUptimeResult]:
    """Process feed/date/mode tuples from CSV with parallel execution."""

    include_normalized = None
    if include_asset_classes:
        include_normalized = {normalize_asset_class(ac) for ac in include_asset_classes}

    exclude_normalized: set[str] = set()
    if exclude_asset_classes:
        exclude_normalized = {normalize_asset_class(ac) for ac in exclude_asset_classes}

    work_items: list[tuple[int, str, str]] = []
    skipped_by_asset_class = 0
    with open(csv_path) as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or not row[0].strip():
                continue
            if len(row) < 3:
                print(f"Warning: Skipping incomplete row: {row}")
                continue

            feed_id_str, date, mode = row[0].strip(), row[1].strip(), row[2].strip()
            normalized_mode = normalize_asset_class(mode)

            if include_normalized and normalized_mode not in include_normalized:
                skipped_by_asset_class += 1
                continue
            if normalized_mode in exclude_normalized:
                skipped_by_asset_class += 1
                continue

            try:
                feed_id = int(feed_id_str)
                datetime.strptime(date, "%Y-%m-%d")
            except ValueError:
                print(f"Warning: Skipping invalid row: {row}")
                continue

            work_items.append((feed_id, date, mode))

    if skipped_by_asset_class > 0:
        print(f"Filtered out {skipped_by_asset_class} feeds by asset class")

    skipped_by_feed_id = 0
    if feed_id_filter is not None:
        filtered_work_items = []
        for feed_id, date, mode in work_items:
            if feed_id in feed_id_filter:
                filtered_work_items.append((feed_id, date, mode))
            else:
                skipped_by_feed_id += 1
        work_items = filtered_work_items

    if skipped_by_feed_id > 0:
        keep_ids = ", ".join(str(x) for x in sorted(feed_id_filter))
        print(
            f"Filtered out {skipped_by_feed_id} feeds by feed ID "
            f"(kept {len(work_items)} matching: {keep_ids})"
        )

    return process_work_items(
        work_items=work_items,
        max_workers=max_workers,
        include_extended_hours=include_extended_hours,
        include_overnight=include_overnight,
        precise=precise,
        gap_threshold_ms=gap_threshold_ms,
        uptime_threshold_pct=uptime_threshold_pct,
    )


def compute_publisher_summary(
    results: list[FeedUptimeResult],
) -> tuple[list[str], list[str], list[dict[str, object]]]:
    """Compute publisher pass/fail consistency summary across dates."""

    unique_dates = sorted({result.date for result in results})
    if not unique_dates:
        return [], [], []

    publisher_dates: dict[int, set[str]] = defaultdict(set)
    publisher_session_date_statuses: dict[
        int, dict[str, dict[str, list[bool]]]
    ] = defaultdict(lambda: defaultdict(lambda: defaultdict(list)))

    for result in results:
        for uptime in result.publisher_uptimes:
            publisher_dates[uptime.publisher_id].add(result.date)
            publisher_session_date_statuses[uptime.publisher_id][uptime.session][
                result.date
            ].append(uptime.passes)

    all_sessions = set()
    for session_map in publisher_session_date_statuses.values():
        all_sessions.update(session_map.keys())
    session_names = [session for session in SESSION_ORDER if session in all_sessions]
    session_names.extend(
        sorted(session for session in all_sessions if session not in SESSION_ORDER)
    )

    summary_rows: list[dict[str, object]] = []
    for publisher_id in sorted(publisher_session_date_statuses):
        session_summary: dict[str, dict[str, object]] = {}
        for session_name in session_names:
            date_map = publisher_session_date_statuses[publisher_id].get(
                session_name, {}
            )
            statuses_by_date: list[tuple[str, bool]] = []
            for date_str in unique_dates:
                statuses = date_map.get(date_str)
                if not statuses:
                    continue
                statuses_by_date.append((date_str, all(statuses)))

            pass_dates = sum(1 for _, status in statuses_by_date if status)
            fail_dates = sum(1 for _, status in statuses_by_date if not status)
            evaluated_dates = pass_dates + fail_dates
            pass_rate = (
                (pass_dates * 100.0 / evaluated_dates) if evaluated_dates > 0 else None
            )
            results_str = ";".join(
                f"{date_str[5:]}:{'PASS' if status else 'FAIL'}"
                for date_str, status in statuses_by_date
            )
            session_summary[session_name] = {
                "pass_dates": pass_dates,
                "fail_dates": fail_dates,
                "evaluated_dates": evaluated_dates,
                "pass_rate": pass_rate,
                "results": results_str,
            }

        summary_rows.append(
            {
                "publisher_id": publisher_id,
                "dates_seen": len(publisher_dates[publisher_id]),
                "sessions": session_summary,
            }
        )

    return unique_dates, session_names, summary_rows
