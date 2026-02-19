#!/usr/bin/env python3
"""
Feed-centric uptime measurement script.

Default mode uses a 1-second window uptime method. Use --precise to switch to
gap-based uptime (default 200ms threshold).
"""

import argparse
import csv
import statistics
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import clickhouse_connect
import yaml

from date_utils import expand_date_args, validate_date_args
from portal.batch.uptime_sessions import SessionWindow, get_session_windows


# Asset class normalization mapping (CSV value -> canonical value)
ASSET_CLASS_ALIASES = {
    "metal": "metals",
    "metals": "metals",
    "equity-us": "us-equities",
    "us-equities": "us-equities",
    "fx": "fx",
    "commodity": "commodity",
    "crypto": "crypto",
    "crypto-redemption-rate": "crypto-redemption-rate",
    "funding-rate": "funding-rate",
    "rates": "us-treasuries",
    "nav": "nav",
    "us-treasuries": "us-treasuries",
    "treasuries": "us-treasuries",
}

DEFAULT_GAP_THRESHOLD_MS = 200
DEFAULT_UPTIME_THRESHOLD_PCT = 95.0
SESSION_ORDER = ["regular", "premarket", "afterhours", "overnight"]


@dataclass(frozen=True)
class PublisherSessionUptime:
    publisher_id: int
    session: str
    uptime_pct: float
    passes: bool
    seconds_with_data: int
    total_seconds: int
    updates_total: int
    updates_per_second: float
    downtime_ms: Optional[int]
    period_length_ms: Optional[int]
    max_gap_ms: Optional[int]
    gaps_over_threshold: Optional[int]


@dataclass(frozen=True)
class FeedUptimeResult:
    feed_id: int
    date: str
    mode: str
    symbol: Optional[str]
    publisher_count: int
    publisher_uptimes: list[PublisherSessionUptime]
    error: Optional[str]
    execution_time_ms: int


def load_config() -> dict:
    """Load database configuration from config.yaml."""

    config_path = Path("config.yaml")
    if not config_path.exists():
        raise FileNotFoundError(
            "config.yaml not found. Copy config.yaml.sample to config.yaml and fill in credentials."
        )
    with open(config_path) as f:
        return yaml.safe_load(f)


def get_lazer_client(config: dict):
    """Create ClickHouse client for Lazer database."""

    lazer_cfg = config["lazer_clickhouse_prod"]
    connect_timeout = 60
    send_receive_timeout = 300

    return clickhouse_connect.get_client(
        host=lazer_cfg["host"],
        username=lazer_cfg["user"],
        password=lazer_cfg["password"],
        secure=True,
        connect_timeout=connect_timeout,
        send_receive_timeout=send_receive_timeout,
    )


def normalize_asset_class(asset_class: str) -> str:
    """Normalize asset class name to canonical form."""

    return ASSET_CLASS_ALIASES.get(asset_class.lower(), asset_class.lower())


def list_asset_classes_in_csv(csv_path: Path) -> dict[str, int]:
    """Scan CSV and return asset class (mode) counts."""

    asset_class_counts: Counter[str] = Counter()
    with open(csv_path) as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or not row[0].strip():
                continue
            if len(row) < 3:
                continue
            mode = row[2].strip()
            asset_class_counts[mode] += 1
    return dict(asset_class_counts)


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
        ((total_time_ms - total_downtime_ms) / total_time_ms * 100.0) if total_time_ms > 0 else 0.0
    )
    updates_per_second = (updates_total / (total_time_ms / 1000.0)) if total_time_ms > 0 else 0.0

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
        filtered_sessions = filter_sessions(sessions, include_extended_hours, include_overnight)

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
                    total_seconds = int((session_window.end_utc - session_window.start_utc).total_seconds())
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
        start_time = time.time()
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
                execution_time_ms=int((time.time() - start_time) * 1000),
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

    return sorted(results, key=lambda r: (r.date, r.feed_id, normalize_asset_class(r.mode)))


def compute_publisher_summary(
    results: list[FeedUptimeResult],
) -> tuple[list[str], list[str], list[dict[str, object]]]:
    """Compute publisher pass/fail consistency summary across dates."""

    unique_dates = sorted({result.date for result in results})
    if not unique_dates:
        return [], [], []

    publisher_dates: dict[int, set[str]] = defaultdict(set)
    publisher_session_date_statuses: dict[int, dict[str, dict[str, list[bool]]]] = defaultdict(
        lambda: defaultdict(lambda: defaultdict(list))
    )

    for result in results:
        for uptime in result.publisher_uptimes:
            publisher_dates[uptime.publisher_id].add(result.date)
            publisher_session_date_statuses[uptime.publisher_id][uptime.session][result.date].append(
                uptime.passes
            )

    all_sessions = set()
    for session_map in publisher_session_date_statuses.values():
        all_sessions.update(session_map.keys())
    session_names = [session for session in SESSION_ORDER if session in all_sessions]
    session_names.extend(sorted(session for session in all_sessions if session not in SESSION_ORDER))

    summary_rows: list[dict[str, object]] = []
    for publisher_id in sorted(publisher_session_date_statuses):
        session_summary: dict[str, dict[str, object]] = {}
        for session_name in session_names:
            date_map = publisher_session_date_statuses[publisher_id].get(session_name, {})
            statuses_by_date: list[tuple[str, bool]] = []
            for date_str in unique_dates:
                statuses = date_map.get(date_str)
                if not statuses:
                    continue
                statuses_by_date.append((date_str, all(statuses)))

            pass_dates = sum(1 for _, status in statuses_by_date if status)
            fail_dates = sum(1 for _, status in statuses_by_date if not status)
            evaluated_dates = pass_dates + fail_dates
            pass_rate = (pass_dates * 100.0 / evaluated_dates) if evaluated_dates > 0 else None
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


def write_results_csv(
    results: list[FeedUptimeResult],
    output_path: Path,
    precise: bool = False,
):
    """Write long-format per-publisher rows and optional publisher summary matrix."""

    output_path.parent.mkdir(parents=True, exist_ok=True)

    if precise:
        detail_header = [
            "feed_id",
            "date",
            "mode",
            "symbol",
            "publisher_id",
            "session",
            "uptime_pct",
            "passes",
            "downtime_ms",
            "period_length_ms",
            "updates_total",
            "updates_per_second",
            "max_gap_ms",
            "gaps_over_threshold",
        ]
    else:
        detail_header = [
            "feed_id",
            "date",
            "mode",
            "symbol",
            "publisher_id",
            "session",
            "uptime_pct",
            "passes",
            "seconds_with_data",
            "total_seconds",
            "updates_total",
            "updates_per_second",
        ]

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(detail_header)

        for result in sorted(results, key=lambda r: (r.date, r.feed_id, normalize_asset_class(r.mode))):
            sorted_uptimes = sorted(result.publisher_uptimes, key=lambda u: (u.publisher_id, u.session))
            for uptime in sorted_uptimes:
                if precise:
                    writer.writerow(
                        [
                            result.feed_id,
                            result.date,
                            result.mode,
                            result.symbol or "",
                            uptime.publisher_id,
                            uptime.session,
                            f"{uptime.uptime_pct:.4f}",
                            uptime.passes,
                            uptime.downtime_ms if uptime.downtime_ms is not None else "",
                            uptime.period_length_ms if uptime.period_length_ms is not None else "",
                            uptime.updates_total,
                            f"{uptime.updates_per_second:.6f}",
                            uptime.max_gap_ms if uptime.max_gap_ms is not None else "",
                            uptime.gaps_over_threshold if uptime.gaps_over_threshold is not None else "",
                        ]
                    )
                else:
                    writer.writerow(
                        [
                            result.feed_id,
                            result.date,
                            result.mode,
                            result.symbol or "",
                            uptime.publisher_id,
                            uptime.session,
                            f"{uptime.uptime_pct:.4f}",
                            uptime.passes,
                            uptime.seconds_with_data,
                            uptime.total_seconds,
                            uptime.updates_total,
                            f"{uptime.updates_per_second:.6f}",
                        ]
                    )

        unique_dates, session_names, summary_rows = compute_publisher_summary(results)
        if len(unique_dates) > 1 and summary_rows:
            header = ["publisher_id", "dates_seen"]
            for session_name in session_names:
                header.extend(
                    [
                        f"{session_name}_pass_dates",
                        f"{session_name}_fail_dates",
                        f"{session_name}_pass_rate",
                        f"{session_name}_results",
                    ]
                )

            writer.writerow([])
            writer.writerow(["PUBLISHER SUMMARY"])
            writer.writerow(header)

            for row in summary_rows:
                output_row = [row["publisher_id"], row["dates_seen"]]
                sessions = row["sessions"]
                for session_name in session_names:
                    stats = sessions.get(session_name, {})
                    pass_dates = stats.get("pass_dates", 0)
                    fail_dates = stats.get("fail_dates", 0)
                    pass_rate = stats.get("pass_rate")
                    results_str = stats.get("results", "")
                    output_row.extend(
                        [
                            pass_dates,
                            fail_dates,
                            f"{pass_rate:.2f}%" if pass_rate is not None else "",
                            results_str,
                        ]
                    )
                writer.writerow(output_row)

            writer.writerow([])
            writer.writerow(["PUBLISHER CLASSIFICATIONS"])

            for session_name in session_names:
                always_passing = []
                always_failing = []
                intermittent = []
                for row in summary_rows:
                    stats = row["sessions"].get(session_name, {})
                    pass_dates = stats.get("pass_dates", 0)
                    fail_dates = stats.get("fail_dates", 0)
                    if pass_dates + fail_dates == 0:
                        continue
                    pid = int(row["publisher_id"])
                    if pass_dates > 0 and fail_dates == 0:
                        always_passing.append(pid)
                    elif fail_dates > 0 and pass_dates == 0:
                        always_failing.append(pid)
                    else:
                        intermittent.append(pid)

                _fmt = lambda ids: ";".join(str(x) for x in ids) if ids else ""
                writer.writerow([f"{session_name}_always_passing", _fmt(always_passing)])
                writer.writerow([f"{session_name}_always_failing", _fmt(always_failing)])
                writer.writerow([f"{session_name}_intermittent", _fmt(intermittent)])


def _format_uptime_stats(values: list[float]) -> str:
    return (
        f"Median uptime: {statistics.median(values):.2f}% | "
        f"Mean: {statistics.fmean(values):.2f}% | "
        f"Min: {min(values):.2f}% | "
        f"Max: {max(values):.2f}%"
    )


def _format_id_list(values: list[int]) -> str:
    if not values:
        return "None"
    return ", ".join(str(v) for v in values)


def print_publisher_consistency(results: list[FeedUptimeResult]):
    """Print cross-date publisher pass/fail consistency matrix."""

    unique_dates, session_names, summary_rows = compute_publisher_summary(results)
    if len(unique_dates) <= 1 or not summary_rows:
        return

    print()
    print("=" * 70)
    print(f"PUBLISHER CONSISTENCY (across {len(unique_dates)} dates)")
    print("=" * 70)

    for session_name in session_names:
        print()
        print(f"{session_name.upper()} SESSION:")
        print("  Publisher  Pass  Fail  Rate    Results")

        always_passing: list[int] = []
        always_failing: list[int] = []
        intermittent: list[int] = []

        for row in summary_rows:
            publisher_id = int(row["publisher_id"])
            stats = row["sessions"].get(session_name, {})
            evaluated_dates = int(stats.get("evaluated_dates", 0))
            if evaluated_dates == 0:
                continue

            pass_dates = int(stats.get("pass_dates", 0))
            fail_dates = int(stats.get("fail_dates", 0))
            pass_rate = stats.get("pass_rate")
            results_str = str(stats.get("results", "")).replace(";", " ")
            rate_str = f"{pass_rate:.1f}%" if pass_rate is not None else "N/A"

            print(
                f"  {publisher_id:<9} {pass_dates:<5} {fail_dates:<5} {rate_str:<7}  {results_str}"
            )

            if pass_dates > 0 and fail_dates == 0:
                always_passing.append(publisher_id)
            elif fail_dates > 0 and pass_dates == 0:
                always_failing.append(publisher_id)
            else:
                intermittent.append(publisher_id)

        print()
        print(f"  Always passing: {_format_id_list(always_passing)}")
        print(f"  Always failing: {_format_id_list(always_failing)}")
        print(f"  Intermittent: {_format_id_list(intermittent)}")


def print_console_summary(
    results: list[FeedUptimeResult],
    total_time_seconds: float,
    precise: bool,
    gap_threshold_ms: int,
    uptime_threshold_pct: float,
):
    """Print aggregated console summary."""

    all_uptimes = [(result, uptime) for result in results for uptime in result.publisher_uptimes]
    errors = [result for result in results if result.error]
    publisher_feed_combos = {(result.feed_id, result.date, uptime.publisher_id) for result, uptime in all_uptimes}

    session_values: dict[str, list[float]] = defaultdict(list)
    session_passes: dict[str, int] = defaultdict(int)
    session_totals: dict[str, int] = defaultdict(int)
    for _, uptime in all_uptimes:
        session_values[uptime.session].append(uptime.uptime_pct)
        session_totals[uptime.session] += 1
        if uptime.passes:
            session_passes[uptime.session] += 1

    method_label = f"{gap_threshold_ms}ms gap-based" if precise else "1s window"
    print()
    print("=" * 70)
    print("FEED UPTIME REPORT")
    print("=" * 70)
    print(
        f"Feeds evaluated: {len(results)} | Publisher-feed combos: {len(publisher_feed_combos)} "
        f"| Method: {method_label} | Pass threshold: {uptime_threshold_pct:.1f}%"
    )
    if errors:
        print(f"Errors: {len(errors)}")

    ordered_sessions = [s for s in SESSION_ORDER if s in session_values]
    ordered_sessions.extend(sorted(s for s in session_values if s not in SESSION_ORDER))

    for session_name in ordered_sessions:
        values = session_values[session_name]
        if not values:
            continue
        pass_count = session_passes[session_name]
        fail_count = session_totals[session_name] - pass_count
        print()
        print(f"{session_name.upper()} SESSION:")
        print(f"  {_format_uptime_stats(values)}")
        print(
            f"  Publishers passing (>={uptime_threshold_pct:.1f}%): {pass_count} | "
            f"Failing: {fail_count}"
        )

    avg_feed_ms = statistics.fmean([r.execution_time_ms for r in results]) if results else 0.0
    print()
    print(f"Timing: {total_time_seconds:.1f}s total, {avg_feed_ms:.0f}ms avg/feed")
    print("=" * 70)

    print_publisher_consistency(results)


def main():
    parser = argparse.ArgumentParser(
        description="Feed-centric uptime measurement across publishers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process feeds from CSV file
  python feed_uptime.py --csv price_id_list.csv

  # Process a single feed
  python feed_uptime.py --feed-id 922 --date 2026-02-09 --mode us-equities

  # Multi-date range
  python feed_uptime.py --feed-id 922 --start-date 2026-02-09 --end-date 2026-02-12 --mode us-equities

  # Session flags for US equities
  python feed_uptime.py --feed-id 922 --date 2026-02-09 --mode us-equities --extended-hours --overnight

  # CSV filtering
  python feed_uptime.py --csv feeds.csv --include-asset-class us-equities fx
  python feed_uptime.py --csv feeds.csv --exclude-asset-class crypto
  python feed_uptime.py --csv feeds.csv --filter-feed-id 922 327

  # Threshold controls
  python feed_uptime.py --csv feeds.csv --uptime-threshold 95
  python feed_uptime.py --csv feeds.csv --precise --gap-threshold 100
""",
    )

    parser.add_argument("--csv", type=Path, help="CSV file containing feed_id,date,mode columns")
    parser.add_argument("--feed-id", type=int, nargs="+", metavar="ID", help="Feed ID(s) to evaluate")
    parser.add_argument(
        "--date",
        nargs="+",
        metavar="YYYY-MM-DD",
        help="Date(s) for single feed evaluation (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--start-date",
        help="Range start date (inclusive, YYYY-MM-DD) for single-feed mode",
    )
    parser.add_argument(
        "--end-date",
        help="Range end date (inclusive, YYYY-MM-DD) for single-feed mode",
    )
    parser.add_argument("--mode", type=str, help="Asset class for single feed mode")
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("feed_uptime_results.csv"),
        help="Output CSV path (default: feed_uptime_results.csv)",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of parallel workers (default: 4)",
    )
    parser.add_argument(
        "--include-asset-class",
        type=str,
        nargs="+",
        metavar="CLASS",
        help="Only process feeds with these asset classes (CSV mode)",
    )
    parser.add_argument(
        "--exclude-asset-class",
        type=str,
        nargs="+",
        metavar="CLASS",
        help="Exclude feeds with these asset classes (CSV mode)",
    )
    parser.add_argument(
        "--list-asset-classes",
        action="store_true",
        help="List unique asset classes in the CSV file and exit",
    )
    parser.add_argument(
        "--filter-feed-id",
        type=int,
        nargs="+",
        metavar="ID",
        help="Only process these feed IDs when using --csv",
    )
    parser.add_argument(
        "--extended-hours",
        action="store_true",
        help="Include premarket and after-hours sessions for US equities",
    )
    parser.add_argument(
        "--overnight",
        action="store_true",
        help="Include overnight session for US equities",
    )
    parser.add_argument(
        "--precise",
        action="store_true",
        help="Use 200ms gap-based method instead of default 1-second window",
    )
    parser.add_argument(
        "--gap-threshold",
        type=int,
        default=DEFAULT_GAP_THRESHOLD_MS,
        help="Gap threshold in milliseconds for --precise mode (default: 200)",
    )
    parser.add_argument(
        "--uptime-threshold",
        type=float,
        default=DEFAULT_UPTIME_THRESHOLD_PCT,
        help="Pass threshold percentage (default: 95.0)",
    )

    args = parser.parse_args()
    single_feed_dates: list[str] = []

    if args.workers <= 0:
        parser.error("--workers must be a positive integer")
    if args.gap_threshold <= 0:
        parser.error("--gap-threshold must be a positive integer")
    if not args.precise and args.gap_threshold != DEFAULT_GAP_THRESHOLD_MS:
        parser.error("--gap-threshold requires --precise")
    if args.uptime_threshold < 0 or args.uptime_threshold > 100:
        parser.error("--uptime-threshold must be between 0 and 100")

    if args.list_asset_classes:
        if not args.csv:
            parser.error("--list-asset-classes requires --csv")
    elif args.csv and (args.feed_id or args.date or args.start_date or args.end_date or args.mode):
        parser.error(
            "Use either --csv OR (--feed-id, --date/--start-date+--end-date, --mode), not both"
        )
    elif not args.csv and not (args.feed_id and args.mode):
        parser.error(
            "Either --csv or all of (--feed-id, --date/--start-date+--end-date, --mode) required"
        )

    if not args.csv:
        try:
            validate_date_args(args)
            single_feed_dates = expand_date_args(args.date, args.start_date, args.end_date)
        except ValueError as e:
            parser.error(str(e))
        if not single_feed_dates:
            parser.error("Single-feed mode requires --date or --start-date/--end-date")

    if not args.csv and (args.include_asset_class or args.exclude_asset_class):
        parser.error("--include-asset-class and --exclude-asset-class only apply to --csv mode")

    if not args.csv and args.filter_feed_id:
        parser.error("--filter-feed-id only applies to --csv mode")

    if args.include_asset_class and args.exclude_asset_class:
        include_set = {normalize_asset_class(ac) for ac in args.include_asset_class}
        exclude_set = {normalize_asset_class(ac) for ac in args.exclude_asset_class}
        overlap = include_set & exclude_set
        if overlap:
            parser.error(f"Asset classes cannot be both included and excluded: {overlap}")

    if args.csv and not args.csv.exists():
        print(f"Error: CSV file '{args.csv}' not found")
        sys.exit(1)

    if args.list_asset_classes:
        asset_classes = list_asset_classes_in_csv(args.csv)
        total_feeds = sum(asset_classes.values())

        print(f"\nAsset classes in {args.csv}:")
        print(f"{'=' * 50}")
        for asset_class, count in sorted(asset_classes.items(), key=lambda x: -x[1]):
            normalized = normalize_asset_class(asset_class)
            print(f"  {asset_class:<25} {count:>5} feeds  [normalized: {normalized}]")
        print(f"{'=' * 50}")
        print(f"  {'TOTAL':<25} {total_feeds:>5} feeds")
        sys.exit(0)

    total_start = time.time()
    results: list[FeedUptimeResult]
    if args.csv:
        feed_id_filter = set(args.filter_feed_id) if args.filter_feed_id else None
        results = process_csv(
            csv_path=args.csv,
            max_workers=args.workers,
            include_asset_classes=args.include_asset_class,
            exclude_asset_classes=args.exclude_asset_class,
            include_extended_hours=args.extended_hours,
            include_overnight=args.overnight,
            feed_id_filter=feed_id_filter,
            precise=args.precise,
            gap_threshold_ms=args.gap_threshold,
            uptime_threshold_pct=args.uptime_threshold,
        )
    else:
        work_items = [(feed_id, date, args.mode) for feed_id in args.feed_id for date in single_feed_dates]
        results = process_work_items(
            work_items=work_items,
            max_workers=args.workers,
            include_extended_hours=args.extended_hours,
            include_overnight=args.overnight,
            precise=args.precise,
            gap_threshold_ms=args.gap_threshold,
            uptime_threshold_pct=args.uptime_threshold,
        )

    write_results_csv(results, args.output, precise=args.precise)
    total_time = time.time() - total_start
    print_console_summary(
        results=results,
        total_time_seconds=total_time,
        precise=args.precise,
        gap_threshold_ms=args.gap_threshold,
        uptime_threshold_pct=args.uptime_threshold,
    )
    print(f"\nResults written to: {args.output}")


if __name__ == "__main__":
    main()
