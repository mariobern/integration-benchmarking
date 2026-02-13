#!/usr/bin/env python3
"""
Feed-centric uptime measurement script.

This script evaluates uptime per publisher for each feed/date/mode tuple using
the 200ms gap-based method. It supports CSV batch mode and direct feed/date CLI
arguments using the same patterns as quick_benchmark.py.
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
ONE_SECOND_GAP_THRESHOLD_MS = 1000


@dataclass(frozen=True)
class PublisherSessionUptime:
    publisher_id: int
    session: str
    uptime_pct: float
    downtime_ms: int
    period_length_ms: int
    updates_total: int
    updates_per_second: float
    max_gap_ms: Optional[int]
    gaps_over_threshold: int


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


def compute_uptime_200ms_gap(
    client,
    publisher_id: int,
    feed_id: int,
    start_utc: datetime,
    end_utc: datetime,
    gap_threshold_ms: int = 200,
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
    gap_threshold_ms: int = 200,
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
                uptime = compute_uptime_200ms_gap(
                    client=client,
                    publisher_id=publisher_id,
                    feed_id=feed_id,
                    start_utc=session_window.start_utc,
                    end_utc=session_window.end_utc,
                    gap_threshold_ms=gap_threshold_ms,
                )
                publisher_uptimes.append(
                    PublisherSessionUptime(
                        publisher_id=publisher_id,
                        session=session_window.session,
                        uptime_pct=uptime["uptime_pct"],
                        downtime_ms=uptime["total_downtime_ms"],
                        period_length_ms=uptime["period_length_ms"],
                        updates_total=uptime["updates_total"],
                        updates_per_second=uptime["updates_per_second"],
                        max_gap_ms=uptime["max_gap_ms"],
                        gaps_over_threshold=uptime["gaps_over_threshold"],
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
    gap_threshold_ms: int = 200,
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
        gap_threshold_ms=gap_threshold_ms,
    )


def process_work_items(
    work_items: list[tuple[int, str, str]],
    max_workers: int,
    include_extended_hours: bool = False,
    include_overnight: bool = False,
    gap_threshold_ms: int = 200,
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
                gap_threshold_ms=gap_threshold_ms,
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

            session_rows = len(result.publisher_uptimes)
            print(
                f"  [{result.execution_time_ms:>5}ms] Feed {result.feed_id} "
                f"({result.date}, {result.mode}): {result.publisher_count} publishers, "
                f"{session_rows} publisher-session rows"
            )

    return sorted(results, key=lambda r: (r.date, r.feed_id, normalize_asset_class(r.mode)))


def build_feed_summary_rows(
    results: list[FeedUptimeResult],
) -> list[tuple[int, str, str, Optional[str], int, str, float, float, float, float]]:
    """Build per-feed, per-session summary rows."""

    summary_rows: list[tuple[int, str, str, Optional[str], int, str, float, float, float, float]] = []

    for result in sorted(results, key=lambda r: (r.date, r.feed_id, normalize_asset_class(r.mode))):
        by_session: dict[str, list[float]] = defaultdict(list)
        for item in result.publisher_uptimes:
            by_session[item.session].append(item.uptime_pct)

        for session, uptime_values in sorted(by_session.items()):
            if not uptime_values:
                continue
            summary_rows.append(
                (
                    result.feed_id,
                    result.date,
                    result.mode,
                    result.symbol,
                    result.publisher_count,
                    session,
                    statistics.median(uptime_values),
                    statistics.fmean(uptime_values),
                    min(uptime_values),
                    max(uptime_values),
                )
            )

    return summary_rows


def write_results_csv(results: list[FeedUptimeResult], output_path: Path):
    """Write long-format per-publisher rows and appended feed summary section."""

    output_path.parent.mkdir(parents=True, exist_ok=True)

    detail_header = [
        "feed_id",
        "date",
        "mode",
        "symbol",
        "publisher_id",
        "session",
        "uptime_pct",
        "downtime_ms",
        "period_length_ms",
        "updates_total",
        "updates_per_second",
        "max_gap_ms",
        "gaps_over_threshold",
    ]

    summary_header = [
        "feed_id",
        "date",
        "mode",
        "symbol",
        "publisher_count",
        "session",
        "median_uptime_pct",
        "mean_uptime_pct",
        "min_uptime_pct",
        "max_uptime_pct",
    ]

    with open(output_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(detail_header)

        for result in sorted(results, key=lambda r: (r.date, r.feed_id, normalize_asset_class(r.mode))):
            sorted_uptimes = sorted(
                result.publisher_uptimes,
                key=lambda u: (u.publisher_id, u.session),
            )
            for uptime in sorted_uptimes:
                writer.writerow(
                    [
                        result.feed_id,
                        result.date,
                        result.mode,
                        result.symbol or "",
                        uptime.publisher_id,
                        uptime.session,
                        f"{uptime.uptime_pct:.4f}",
                        uptime.downtime_ms,
                        uptime.period_length_ms,
                        uptime.updates_total,
                        f"{uptime.updates_per_second:.6f}",
                        uptime.max_gap_ms if uptime.max_gap_ms is not None else "",
                        uptime.gaps_over_threshold,
                    ]
                )

        writer.writerow([])
        writer.writerow(["FEED SUMMARY"])
        writer.writerow(summary_header)

        for row in build_feed_summary_rows(results):
            writer.writerow(
                [
                    row[0],
                    row[1],
                    row[2],
                    row[3] or "",
                    row[4],
                    row[5],
                    f"{row[6]:.4f}",
                    f"{row[7]:.4f}",
                    f"{row[8]:.4f}",
                    f"{row[9]:.4f}",
                ]
            )


def _session_stats(values: list[float]) -> str:
    if not values:
        return "No data"
    return (
        f"Median uptime: {statistics.median(values):.2f}% | "
        f"Mean: {statistics.fmean(values):.2f}% | "
        f"Min: {min(values):.2f}% | "
        f"Max: {max(values):.2f}%"
    )


def print_console_summary(
    results: list[FeedUptimeResult],
    total_time_seconds: float,
    gap_threshold_ms: int,
):
    """Print aggregated console summary."""

    all_uptimes = [
        (result, uptime)
        for result in results
        for uptime in result.publisher_uptimes
    ]
    errors = [result for result in results if result.error]

    publisher_feed_combos = {
        (result.feed_id, result.date, uptime.publisher_id)
        for result, uptime in all_uptimes
    }

    session_uptime_values: dict[str, list[float]] = defaultdict(list)
    session_feeds: dict[str, set[tuple[int, str]]] = defaultdict(set)
    mode_regular_values: dict[str, list[float]] = defaultdict(list)
    mode_regular_feeds: dict[str, set[tuple[int, str]]] = defaultdict(set)

    for result, uptime in all_uptimes:
        session_uptime_values[uptime.session].append(uptime.uptime_pct)
        session_feeds[uptime.session].add((result.feed_id, result.date))
        if uptime.session == "regular":
            normalized_mode = normalize_asset_class(result.mode)
            mode_regular_values[normalized_mode].append(uptime.uptime_pct)
            mode_regular_feeds[normalized_mode].add((result.feed_id, result.date))

    print()
    print("=" * 70)
    print("FEED UPTIME REPORT")
    print("=" * 70)
    print(
        f"Feeds evaluated: {len(results)} | Publisher-feed combos: {len(publisher_feed_combos)} "
        f"| Gap threshold: {gap_threshold_ms}ms"
    )
    if errors:
        print(f"Errors: {len(errors)}")

    session_order = ["regular", "premarket", "afterhours", "overnight"]
    extra_sessions = sorted(s for s in session_uptime_values if s not in session_order)
    for session in [*session_order, *extra_sessions]:
        values = session_uptime_values.get(session, [])
        if not values:
            continue
        print()
        print(f"{session.upper()} SESSION:")
        print(f"  {_session_stats(values)}")
        print(f"  Publishers below 99%: {sum(1 for value in values if value < 99.0)}")

        if session == "regular" and mode_regular_values:
            print()
            print("  Per-asset-class:")
            for mode, mode_values in sorted(mode_regular_values.items()):
                feed_count = len(mode_regular_feeds[mode])
                print(
                    f"    {mode:<15} feeds={feed_count:<3} "
                    f"median={statistics.median(mode_values):.2f}%"
                )

    avg_feed_ms = statistics.fmean([r.execution_time_ms for r in results]) if results else 0.0
    print()
    print(f"Timing: {total_time_seconds:.1f}s total, {avg_feed_ms:.0f}ms avg/feed")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(
        description="Feed-centric uptime measurement across publishers",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process feeds from CSV file
  python feed_uptime.py --csv price_id_list.csv

  # Process a single feed
  python feed_uptime.py --feed-id 327 --date 2025-10-06 --mode fx

  # Multiple feed IDs × multiple dates (cartesian product)
  python feed_uptime.py --feed-id 327 328 --date 2025-10-06 2025-10-07 --mode fx

  # Date range
  python feed_uptime.py --feed-id 327 --start-date 2025-10-01 --end-date 2025-10-06 --mode fx

  # Include pre-market + after-hours (US equities only)
  python feed_uptime.py --csv price_id_list.csv --extended-hours

  # Include overnight session (US equities only)
  python feed_uptime.py --csv price_id_list.csv --extended-hours --overnight

  # Filter by asset class and feed ID in CSV mode
  python feed_uptime.py --csv feeds.csv --include-asset-class us-equities fx --filter-feed-id 327 1163

  # Switch default gap threshold from 200ms to 1s
  python feed_uptime.py --csv price_id_list.csv --one-second-gap
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
        "--one-second-gap",
        action="store_true",
        help="Use 1000ms gap threshold instead of default 200ms",
    )
    parser.add_argument(
        "--gap-threshold",
        type=int,
        default=None,
        help=(
            "Gap threshold in milliseconds "
            "(default: 200, or 1000 when --one-second-gap is set)"
        ),
    )

    args = parser.parse_args()
    single_feed_dates: list[str] = []

    if args.one_second_gap and args.gap_threshold is not None:
        parser.error("Use either --one-second-gap or --gap-threshold, not both")
    if args.gap_threshold is not None and args.gap_threshold <= 0:
        parser.error("--gap-threshold must be a positive integer")
    if args.workers <= 0:
        parser.error("--workers must be a positive integer")

    if args.gap_threshold is not None:
        effective_gap_threshold_ms = args.gap_threshold
    else:
        effective_gap_threshold_ms = (
            ONE_SECOND_GAP_THRESHOLD_MS if args.one_second_gap else DEFAULT_GAP_THRESHOLD_MS
        )

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
            gap_threshold_ms=effective_gap_threshold_ms,
        )
    else:
        work_items = [(feed_id, date, args.mode) for feed_id in args.feed_id for date in single_feed_dates]
        results = process_work_items(
            work_items=work_items,
            max_workers=args.workers,
            include_extended_hours=args.extended_hours,
            include_overnight=args.overnight,
            gap_threshold_ms=effective_gap_threshold_ms,
        )

    write_results_csv(results, args.output)
    total_time = time.time() - total_start
    print_console_summary(results, total_time, effective_gap_threshold_ms)
    print(f"\nResults written to: {args.output}")


if __name__ == "__main__":
    main()
