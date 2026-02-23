#!/usr/bin/env python3
"""
Uptime verification script that compares multiple calculation methods.

This script validates uptime by running both:
1. 1-second window method (coarse - what the dashboard uses)
2. 200ms gap-based method (accurate - detects sub-second gaps)

Usage:
    python verify_uptime.py --publisher-id 55 --date 2026-01-28

    # Compare specific feeds
    python verify_uptime.py --publisher-id 55 --date 2026-01-28 --feed-id 100 101

    # Include extended hours
    python verify_uptime.py --publisher-id 55 --date 2026-01-28 --extended-hours
"""

import argparse
from dataclasses import dataclass
from datetime import datetime, date, timedelta
from typing import Optional
import sys

import clickhouse_connect
import yaml
from pathlib import Path

CONFIG_FILE = Path("config.yaml")


@dataclass(frozen=True)
class UptimeComparison:
    """Comparison of uptime using different calculation methods."""

    feed_id: int
    symbol: str
    session: str
    start_time: datetime
    end_time: datetime

    # 1-second window method (dashboard method)
    uptime_1s_pct: float
    seconds_with_data: int
    total_seconds: int
    updates_total: int
    updates_per_second: float

    # 200ms gap-based method (accurate method)
    uptime_200ms_pct: Optional[float]
    total_downtime_ms: Optional[int]
    max_gap_ms: Optional[int]
    gaps_over_threshold: Optional[int]  # gaps > 200ms
    gaps_over_500ms: Optional[int]
    gaps_over_1000ms: Optional[int]


def load_config():
    """Load ClickHouse configuration."""
    with open(CONFIG_FILE) as f:
        config = yaml.safe_load(f)
    return config["lazer_clickhouse_prod"]


def get_client(config: dict):
    """Create ClickHouse client."""
    # clickhouse_connect uses HTTP protocol, not native
    # Native port 9440 maps to HTTP port 8443
    http_port = 8443
    return clickhouse_connect.get_client(
        host=config["host"],
        port=http_port,
        username=config["user"],
        password=config["password"],
        secure=True,
    )


def get_publisher_feeds(
    client,
    publisher_id: int,
    target_date: date,
    feed_ids: Optional[list[int]] = None,
) -> list[dict]:
    """Get list of feeds for a publisher on a given date."""
    feed_filter = ""
    if feed_ids:
        feed_list = ", ".join(str(f) for f in feed_ids)
        feed_filter = f"AND price_feed_id IN ({feed_list})"

    # Get feeds from publisher_updates
    query = f"""
        SELECT DISTINCT price_feed_id
        FROM publisher_updates
        WHERE publisher_id = {publisher_id}
          AND toDate(publish_time) = '{target_date}'
          {feed_filter}
        ORDER BY price_feed_id
    """
    result = client.query(query)

    feeds = [
        {"feed_id": row[0], "symbol": f"feed_{row[0]}"} for row in result.result_rows
    ]

    # Try to get symbols from price_feeds if it exists
    if feeds:
        feed_ids_str = ", ".join(str(f["feed_id"]) for f in feeds)
        try:
            # Try different possible column names
            symbol_query = f"""
                SELECT price_feed_id, symbol
                FROM price_feeds
                WHERE price_feed_id IN ({feed_ids_str})
            """
            symbol_result = client.query(symbol_query)
            symbol_map = {row[0]: row[1] for row in symbol_result.result_rows}

            for feed in feeds:
                if feed["feed_id"] in symbol_map:
                    feed["symbol"] = symbol_map[feed["feed_id"]]
        except Exception:
            # Symbol lookup failed, use feed_id as symbol
            pass

    return feeds


def compute_uptime_1s_window(
    client,
    publisher_id: int,
    feed_id: int,
    start_utc: datetime,
    end_utc: datetime,
) -> dict:
    """
    Compute uptime using 1-second window method.

    This is what the dashboard currently uses.
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
            updates_total / total_seconds AS updates_per_second,
            (seconds_with_data * 100.0 / total_seconds) AS uptime_pct
        FROM per_second
    """

    result = client.query(query)

    if not result.result_rows or result.result_rows[0][0] is None:
        total_seconds = int((end_utc - start_utc).total_seconds())
        return {
            "uptime_pct": 0.0,
            "seconds_with_data": 0,
            "total_seconds": total_seconds,
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
    gap_threshold_ms: int = 200,
) -> dict:
    """
    Compute uptime using accurate gap-based method.

    Any gap between consecutive updates > gap_threshold_ms is counted as downtime.
    This is the accurate method from the research repo.
    """
    start_str = start_utc.strftime("%Y-%m-%d %H:%M:%S")
    end_str = end_utc.strftime("%Y-%m-%d %H:%M:%S")

    query = f"""
        WITH
            parseDateTimeBestEffort('{start_str}') AS start_time,
            parseDateTimeBestEffort('{end_str}') AS end_time,
            dateDiff('millisecond', start_time, end_time) AS total_time_ms,

            -- Get ordered updates with lag
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

            -- Calculate gaps
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
                    countIf(gap_ms > {gap_threshold_ms}) AS gaps_over_threshold,
                    countIf(gap_ms > 500) AS gaps_over_500ms,
                    countIf(gap_ms > 1000) AS gaps_over_1000ms,
                    sum(greatest(0, gap_ms - {gap_threshold_ms})) AS consecutive_downtime_ms
                FROM gaps
            )

        SELECT
            total_updates,
            max_gap_ms,
            gaps_over_threshold,
            gaps_over_500ms,
            gaps_over_1000ms,
            consecutive_downtime_ms,
            -- Downtime from start to first update
            greatest(0, dateDiff('millisecond', start_time, first_update) - {gap_threshold_ms}) AS start_gap_ms,
            -- Downtime from last update to end
            greatest(0, dateDiff('millisecond', last_update, end_time) - {gap_threshold_ms}) AS end_gap_ms,
            total_time_ms,
            -- Total downtime
            least(
                consecutive_downtime_ms +
                greatest(0, dateDiff('millisecond', start_time, first_update) - {gap_threshold_ms}) +
                greatest(0, dateDiff('millisecond', last_update, end_time) - {gap_threshold_ms}),
                total_time_ms
            ) AS total_downtime_ms
        FROM gap_stats
    """

    result = client.query(query)

    if not result.result_rows or result.result_rows[0][0] is None:
        total_ms = int((end_utc - start_utc).total_seconds() * 1000)
        return {
            "uptime_pct": 0.0,
            "total_downtime_ms": total_ms,
            "max_gap_ms": None,
            "gaps_over_threshold": 0,
            "gaps_over_500ms": 0,
            "gaps_over_1000ms": 0,
        }

    row = result.result_rows[0]
    total_time_ms = int(row[8] or 0)
    total_downtime_ms = int(row[9] or 0)

    uptime_pct = (
        ((total_time_ms - total_downtime_ms) / total_time_ms * 100)
        if total_time_ms > 0
        else 0.0
    )

    return {
        "uptime_pct": uptime_pct,
        "total_downtime_ms": total_downtime_ms,
        "max_gap_ms": int(row[1]) if row[1] else None,
        "gaps_over_threshold": int(row[2] or 0),
        "gaps_over_500ms": int(row[3] or 0),
        "gaps_over_1000ms": int(row[4] or 0),
    }


def get_trading_sessions(
    target_date: date, asset_class: str = "us-equities"
) -> list[dict]:
    """Get trading sessions for a given date and asset class."""
    sessions = []

    if asset_class in ("fx", "metals"):
        # 24-hour trading with maintenance window
        sessions.append(
            {
                "name": "regular",
                "start": datetime.combine(target_date, datetime.min.time()),
                "end": datetime.combine(
                    target_date + timedelta(days=1), datetime.min.time()
                ),
            }
        )
    else:
        # US Equities sessions (times in UTC, adjust from EST)
        # Regular: 9:30 AM - 4:00 PM EST = 14:30 - 21:00 UTC
        sessions.append(
            {
                "name": "regular",
                "start": datetime.combine(
                    target_date, datetime.min.time().replace(hour=14, minute=30)
                ),
                "end": datetime.combine(
                    target_date, datetime.min.time().replace(hour=21, minute=0)
                ),
            }
        )

        # Pre-market: 4:00 AM - 9:30 AM EST = 09:00 - 14:30 UTC
        sessions.append(
            {
                "name": "premarket",
                "start": datetime.combine(
                    target_date, datetime.min.time().replace(hour=9, minute=0)
                ),
                "end": datetime.combine(
                    target_date, datetime.min.time().replace(hour=14, minute=30)
                ),
            }
        )

        # After-hours: 4:00 PM - 8:00 PM EST = 21:00 - 01:00 UTC (next day)
        sessions.append(
            {
                "name": "afterhours",
                "start": datetime.combine(
                    target_date, datetime.min.time().replace(hour=21, minute=0)
                ),
                "end": datetime.combine(
                    target_date + timedelta(days=1),
                    datetime.min.time().replace(hour=1, minute=0),
                ),
            }
        )

        # Overnight: 8:00 PM - 4:00 AM EST = 01:00 - 09:00 UTC
        sessions.append(
            {
                "name": "overnight",
                "start": datetime.combine(
                    target_date, datetime.min.time().replace(hour=1, minute=0)
                ),
                "end": datetime.combine(
                    target_date, datetime.min.time().replace(hour=9, minute=0)
                ),
            }
        )

    return sessions


def verify_uptime(
    client,
    publisher_id: int,
    target_date: date,
    feed_ids: Optional[list[int]] = None,
    extended_hours: bool = False,
    asset_class: str = "us-equities",
) -> list[UptimeComparison]:
    """Verify uptime using multiple calculation methods."""

    feeds = get_publisher_feeds(client, publisher_id, target_date, feed_ids)

    if not feeds:
        print(f"No feeds found for publisher {publisher_id} on {target_date}")
        return []

    sessions = get_trading_sessions(target_date, asset_class)

    # Filter sessions based on flags
    if not extended_hours:
        sessions = [s for s in sessions if s["name"] == "regular"]

    results = []

    for feed in feeds:
        for session in sessions:
            # 1-second window method
            uptime_1s = compute_uptime_1s_window(
                client,
                publisher_id,
                feed["feed_id"],
                session["start"],
                session["end"],
            )

            # 200ms gap-based method
            uptime_200ms = compute_uptime_200ms_gap(
                client,
                publisher_id,
                feed["feed_id"],
                session["start"],
                session["end"],
            )

            results.append(
                UptimeComparison(
                    feed_id=feed["feed_id"],
                    symbol=feed["symbol"],
                    session=session["name"],
                    start_time=session["start"],
                    end_time=session["end"],
                    uptime_1s_pct=uptime_1s["uptime_pct"],
                    seconds_with_data=uptime_1s["seconds_with_data"],
                    total_seconds=uptime_1s["total_seconds"],
                    updates_total=uptime_1s["updates_total"],
                    updates_per_second=uptime_1s["updates_per_second"],
                    uptime_200ms_pct=uptime_200ms["uptime_pct"],
                    total_downtime_ms=uptime_200ms["total_downtime_ms"],
                    max_gap_ms=uptime_200ms["max_gap_ms"],
                    gaps_over_threshold=uptime_200ms["gaps_over_threshold"],
                    gaps_over_500ms=uptime_200ms["gaps_over_500ms"],
                    gaps_over_1000ms=uptime_200ms["gaps_over_1000ms"],
                )
            )

    return results


def print_comparison_report(
    results: list[UptimeComparison], publisher_id: int, target_date: date
):
    """Print a comparison report."""
    print()
    print("=" * 100)
    print(f"UPTIME VERIFICATION REPORT - Publisher {publisher_id} - {target_date}")
    print("=" * 100)
    print()

    # Summary statistics
    uptime_1s_values = [r.uptime_1s_pct for r in results if r.uptime_1s_pct > 0]
    uptime_200ms_values = [
        r.uptime_200ms_pct
        for r in results
        if r.uptime_200ms_pct and r.uptime_200ms_pct > 0
    ]

    if uptime_1s_values:
        print("SUMMARY (across all feeds/sessions with data):")
        print("-" * 50)
        print(f"  1-second window method (dashboard):")
        print(f"    Mean:   {sum(uptime_1s_values) / len(uptime_1s_values):.2f}%")
        print(f"    Median: {sorted(uptime_1s_values)[len(uptime_1s_values)//2]:.2f}%")
        print(f"    Min:    {min(uptime_1s_values):.2f}%")
        print(f"    Max:    {max(uptime_1s_values):.2f}%")
        print()

    if uptime_200ms_values:
        print(f"  200ms gap-based method (accurate):")
        print(f"    Mean:   {sum(uptime_200ms_values) / len(uptime_200ms_values):.2f}%")
        print(
            f"    Median: {sorted(uptime_200ms_values)[len(uptime_200ms_values)//2]:.2f}%"
        )
        print(f"    Min:    {min(uptime_200ms_values):.2f}%")
        print(f"    Max:    {max(uptime_200ms_values):.2f}%")
        print()

    # Find significant discrepancies
    discrepancies = [
        r
        for r in results
        if r.uptime_200ms_pct and abs(r.uptime_1s_pct - r.uptime_200ms_pct) > 1.0
    ]

    if discrepancies:
        print()
        print("SIGNIFICANT DISCREPANCIES (>1% difference):")
        print("-" * 100)
        print(
            f"{'Feed':<10} {'Symbol':<20} {'Session':<12} {'1s Window':<12} {'200ms Gap':<12} {'Diff':<10} {'Max Gap':<12}"
        )
        print("-" * 100)

        for r in sorted(
            discrepancies,
            key=lambda x: (x.uptime_1s_pct - x.uptime_200ms_pct),
            reverse=True,
        ):
            diff = r.uptime_1s_pct - r.uptime_200ms_pct
            max_gap_str = f"{r.max_gap_ms}ms" if r.max_gap_ms else "N/A"
            print(
                f"{r.feed_id:<10} {r.symbol[:20]:<20} {r.session:<12} {r.uptime_1s_pct:>10.2f}% {r.uptime_200ms_pct:>10.2f}% {diff:>+8.2f}% {max_gap_str:>12}"
            )

    print()
    print()
    print("DETAILED RESULTS:")
    print("-" * 130)
    print(
        f"{'Feed':<8} {'Symbol':<18} {'Session':<10} {'1s %':<8} {'200ms %':<8} {'Upd/sec':<8} {'Max Gap':<10} {'Gaps>200ms':<10} {'Gaps>1s':<8}"
    )
    print("-" * 130)

    for r in results:
        max_gap_str = f"{r.max_gap_ms}ms" if r.max_gap_ms else "N/A"
        uptime_200ms_str = f"{r.uptime_200ms_pct:.2f}%" if r.uptime_200ms_pct else "N/A"

        # Highlight issues
        flag = ""
        if r.uptime_1s_pct >= 99.9 and r.uptime_200ms_pct and r.uptime_200ms_pct < 99.0:
            flag = " *** DISCREPANCY"
        elif r.gaps_over_1000ms and r.gaps_over_1000ms > 0:
            flag = " ** GAPS > 1s"
        elif r.max_gap_ms and r.max_gap_ms > 500:
            flag = " * HIGH MAX GAP"

        print(
            f"{r.feed_id:<8} {r.symbol[:18]:<18} {r.session:<10} {r.uptime_1s_pct:>6.2f}% {uptime_200ms_str:>8} {r.updates_per_second:>7.1f} {max_gap_str:>10} {r.gaps_over_threshold or 0:>10} {r.gaps_over_1000ms or 0:>8}{flag}"
        )

    print()
    print()
    print("LEGEND:")
    print("  1s %     = Uptime using 1-second window method (what dashboard shows)")
    print("  200ms %   = Uptime using 200ms gap-based method (accurate)")
    print("  Upd/sec  = Average updates per second")
    print("  Max Gap  = Maximum gap between consecutive updates")
    print("  Gaps>200ms = Count of gaps exceeding 200ms")
    print("  Gaps>1s  = Count of gaps exceeding 1 second")
    print()
    print("  *** DISCREPANCY = Dashboard shows ~100% but accurate method shows <99%")
    print("  ** GAPS > 1s    = Has gaps longer than 1 second (missed seconds)")
    print("  * HIGH MAX GAP  = Maximum gap > 500ms")
    print()


def main():
    parser = argparse.ArgumentParser(
        description="Verify uptime using multiple calculation methods"
    )
    parser.add_argument(
        "--publisher-id",
        type=int,
        required=True,
        help="Publisher ID to verify",
    )
    parser.add_argument(
        "--date",
        type=str,
        required=True,
        help="Date to verify (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--feed-id",
        type=int,
        nargs="*",
        help="Specific feed IDs to verify (optional)",
    )
    parser.add_argument(
        "--extended-hours",
        action="store_true",
        help="Include extended hours sessions",
    )
    parser.add_argument(
        "--asset-class",
        type=str,
        default="us-equities",
        choices=["us-equities", "fx", "metals"],
        help="Asset class for session times",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="Output CSV file path",
    )

    args = parser.parse_args()

    try:
        target_date = date.fromisoformat(args.date)
    except ValueError:
        print(f"Invalid date format: {args.date}. Use YYYY-MM-DD.")
        sys.exit(1)

    print(f"Loading configuration from {CONFIG_FILE}...")
    config = load_config()

    print(f"Connecting to ClickHouse...")
    client = get_client(config)

    print(f"Verifying uptime for publisher {args.publisher_id} on {target_date}...")

    results = verify_uptime(
        client,
        args.publisher_id,
        target_date,
        args.feed_id,
        args.extended_hours,
        args.asset_class,
    )

    if not results:
        print("No data found.")
        sys.exit(0)

    print_comparison_report(results, args.publisher_id, target_date)

    # Export to CSV if requested
    if args.output:
        import csv

        with open(args.output, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(
                [
                    "feed_id",
                    "symbol",
                    "session",
                    "start_time",
                    "end_time",
                    "uptime_1s_pct",
                    "seconds_with_data",
                    "total_seconds",
                    "updates_total",
                    "updates_per_second",
                    "uptime_200ms_pct",
                    "total_downtime_ms",
                    "max_gap_ms",
                    "gaps_over_threshold",
                    "gaps_over_500ms",
                    "gaps_over_1000ms",
                ]
            )

            for r in results:
                writer.writerow(
                    [
                        r.feed_id,
                        r.symbol,
                        r.session,
                        r.start_time,
                        r.end_time,
                        r.uptime_1s_pct,
                        r.seconds_with_data,
                        r.total_seconds,
                        r.updates_total,
                        r.updates_per_second,
                        r.uptime_200ms_pct,
                        r.total_downtime_ms,
                        r.max_gap_ms,
                        r.gaps_over_threshold,
                        r.gaps_over_500ms,
                        r.gaps_over_1000ms,
                    ]
                )

        print(f"Results exported to {args.output}")


if __name__ == "__main__":
    main()
