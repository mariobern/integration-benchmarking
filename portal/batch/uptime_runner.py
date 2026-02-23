#!/usr/bin/env python3
"""
Compute session-aware uptime for a publisher's feeds and store in Postgres.

Low-risk implementation:
- Uses time-of-day sessions per asset class
- No holiday calendars
- Uses a simple window-based uptime calculation
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

import clickhouse_connect
from sqlalchemy.dialects.postgresql import insert

from portal.batch.uptime_sessions import SessionWindow, get_session_windows
from portal.config import settings
from portal.models import PublisherFeedDailyUptime


DEFAULT_WINDOW_MS = 1000


@dataclass(frozen=True)
class FeedEntry:
    feed_id: int
    asset_class: str


def get_clickhouse_client():
    config = settings.get_clickhouse_lazer_config()
    return clickhouse_connect.get_client(**config)


def parse_feeds_csv(csv_path: Path) -> list[FeedEntry]:
    feeds: list[FeedEntry] = []
    for line in csv_path.read_text().splitlines():
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) < 3:
            continue
        feed_id = int(parts[0])
        asset_class = parts[2]
        feeds.append(FeedEntry(feed_id=feed_id, asset_class=asset_class))
    return feeds


def _build_uptime_query(
    publisher_id: int,
    feed_ids: Iterable[int],
    start: datetime,
    end: datetime,
    window_ms: int,
) -> str:
    feed_id_list = ", ".join(str(fid) for fid in feed_ids)
    return f"""
        WITH
            parseDateTimeBestEffort('{start.strftime("%Y-%m-%d %H:%M:%S")}') AS start_ts,
            parseDateTimeBestEffort('{end.strftime("%Y-%m-%d %H:%M:%S")}') AS end_ts
        , intervals AS (
            SELECT
                price_feed_id,
                toStartOfInterval(publish_time, INTERVAL {window_ms} MILLISECOND) AS interval_start,
                count() AS updates_count
            FROM publisher_updates
            PREWHERE publisher_id = {publisher_id}
                AND price_feed_id IN ({feed_id_list})
            WHERE publish_time >= start_ts
                AND publish_time < end_ts
            GROUP BY price_feed_id, interval_start
        )
        SELECT
            price_feed_id,
            count(DISTINCT interval_start) AS windows_with_updates,
            sum(updates_count) AS updates_total
        FROM intervals
        GROUP BY price_feed_id
        ORDER BY price_feed_id
    """


def query_uptime_windows(
    client,
    publisher_id: int,
    feed_ids: list[int],
    window: SessionWindow,
    window_ms: int,
) -> dict[int, dict]:
    if not feed_ids:
        return {}

    query = _build_uptime_query(
        publisher_id, feed_ids, window.start_utc, window.end_utc, window_ms
    )
    result = client.query(query)
    rows = result.result_rows

    by_feed: dict[int, dict] = {}
    for feed_id, windows_with_updates, updates_total in rows:
        by_feed[int(feed_id)] = {
            "windows_with_updates": int(windows_with_updates),
            "updates_total": int(updates_total or 0),
        }
    return by_feed


def compute_session_uptime(
    publisher_id: int,
    feeds: list[FeedEntry],
    target_date: date,
    client,
    window_ms: int = DEFAULT_WINDOW_MS,
) -> list[dict]:
    """
    Compute session-aware uptime for all feeds.
    Returns list of rows suitable for upsert.
    """
    rows: list[dict] = []
    feeds_by_asset: dict[str, list[FeedEntry]] = {}
    for feed in feeds:
        feeds_by_asset.setdefault(feed.asset_class, []).append(feed)

    for asset_class, asset_feeds in feeds_by_asset.items():
        windows = get_session_windows(asset_class, target_date)
        if not windows:
            continue

        feed_ids = [f.feed_id for f in asset_feeds]
        # Aggregate per session name
        sessions = {}
        for window in windows:
            per_window = query_uptime_windows(
                client, publisher_id, feed_ids, window, window_ms
            )
            period_length_ms = int(
                (window.end_utc - window.start_utc).total_seconds() * 1000
            )
            total_windows = period_length_ms // window_ms if period_length_ms > 0 else 0

            for feed in asset_feeds:
                key = (feed.feed_id, window.session)
                sessions.setdefault(
                    key,
                    {
                        "publisher_id": publisher_id,
                        "feed_id": feed.feed_id,
                        "uptime_date": target_date,
                        "asset_class": asset_class,
                        "session": window.session,
                        "period_length_ms": 0,
                        "windows_with_updates": 0,
                    },
                )
                sessions[key]["period_length_ms"] += period_length_ms
                if total_windows <= 0:
                    continue
                entry = per_window.get(feed.feed_id)
                if entry:
                    sessions[key]["windows_with_updates"] += entry[
                        "windows_with_updates"
                    ]

        for (feed_id, session), data in sessions.items():
            period_length_ms = data["period_length_ms"]
            total_windows = period_length_ms // window_ms if period_length_ms > 0 else 0
            windows_with_updates = data["windows_with_updates"]
            if total_windows <= 0:
                uptime = 0.0
                downtime_ms = period_length_ms
            else:
                uptime = windows_with_updates / total_windows
                downtime_ms = int(
                    max(0, total_windows - windows_with_updates) * window_ms
                )

            rows.append(
                {
                    "publisher_id": publisher_id,
                    "feed_id": feed_id,
                    "uptime_date": target_date,
                    "asset_class": data["asset_class"],
                    "session": session,
                    "uptime_pct": round(uptime * 100, 4),
                    "downtime_ms": downtime_ms,
                    "period_length_ms": period_length_ms,
                }
            )

    return rows


def store_uptime_rows(session, rows: list[dict]) -> int:
    if not rows:
        return 0
    count = 0
    for row in rows:
        stmt = insert(PublisherFeedDailyUptime).values(**row)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_uptime_publisher_feed_date_session",
            set_={
                "uptime_pct": stmt.excluded.uptime_pct,
                "downtime_ms": stmt.excluded.downtime_ms,
                "period_length_ms": stmt.excluded.period_length_ms,
                "asset_class": stmt.excluded.asset_class,
            },
        )
        session.execute(stmt)
        count += 1
    session.commit()
    return count


def compute_and_store_uptime_for_publisher(
    publisher_id: int,
    target_date: date,
    feeds_csv: Path,
    session,
    window_ms: int = DEFAULT_WINDOW_MS,
) -> int:
    feeds = parse_feeds_csv(feeds_csv)
    if not feeds:
        return 0

    client = get_clickhouse_client()
    rows = compute_session_uptime(
        publisher_id=publisher_id,
        feeds=feeds,
        target_date=target_date,
        client=client,
        window_ms=window_ms,
    )
    return store_uptime_rows(session, rows)
