"""Pure helpers for publisher_asset_map: day windows and rollups."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from lib.asset_class import categorize_asset_class


@dataclass
class PublisherFeedRow:
    """One (publisher, feed) contribution on the analyzed date."""

    publisher_id: int
    publisher_name: str
    feed_id: int
    symbol: str
    asset_class: str
    update_count: int


def day_window(date_str: str) -> tuple[str, str]:
    """Return [start, end) ClickHouse DateTime strings for the full UTC day."""
    start = date.fromisoformat(date_str)
    end = start + timedelta(days=1)
    return (f"{start.isoformat()} 00:00:00", f"{end.isoformat()} 00:00:00")


def build_summary(rows: list[PublisherFeedRow]) -> list[dict]:
    """One row per (publisher_id, asset_class) with feed_count and total_updates."""
    feed_count: dict[tuple[int, str], int] = defaultdict(int)
    total_updates: dict[tuple[int, str], int] = defaultdict(int)
    names: dict[int, str] = {}
    for r in rows:
        key = (r.publisher_id, r.asset_class)
        feed_count[key] += 1
        total_updates[key] += r.update_count
        names[r.publisher_id] = r.publisher_name

    out = [
        {
            "publisher_id": pub_id,
            "publisher_name": names[pub_id],
            "asset_class": asset_class,
            "feed_count": feed_count[(pub_id, asset_class)],
            "total_updates": total_updates[(pub_id, asset_class)],
        }
        for (pub_id, asset_class) in feed_count
    ]
    out.sort(key=lambda r: (r["publisher_id"], r["asset_class"]))
    return out


def build_matrix(rows: list[PublisherFeedRow]) -> tuple[list[str], list[dict]]:
    """Wide pivot: publisher rows, one column per asset class (feed counts)."""
    classes = sorted({r.asset_class for r in rows})
    counts: dict[int, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    names: dict[int, str] = {}
    for r in rows:
        counts[r.publisher_id][r.asset_class] += 1
        names[r.publisher_id] = r.publisher_name

    matrix = []
    for pub_id in sorted(counts):
        row = {"publisher_id": pub_id, "publisher_name": names[pub_id]}
        for cls in classes:
            row[cls] = counts[pub_id].get(cls, 0)
        matrix.append(row)
    return classes, matrix


def fetch_publisher_names(client) -> dict[int, str]:
    """Map publisher_id -> name from publishers_metadata_latest (live)."""
    query = """
        SELECT publisher_id, name
        FROM publishers_metadata_latest
        FINAL
    """
    result = client.query(query)
    return {int(row[0]): row[1] for row in result.result_rows}


def fetch_publisher_feeds(
    client,
    date_str: str,
    asset_class_filter: Optional[str] = None,
) -> list[PublisherFeedRow]:
    """Query one UTC day of publisher_updates, grouped per (publisher, feed)."""
    start, end = day_window(date_str)
    names = fetch_publisher_names(client)

    query = """
        SELECT
            pu.publisher_id AS publisher_id,
            pu.price_feed_id AS feed_id,
            count() AS update_count,
            fm.asset_type AS asset_type,
            fm.symbol AS symbol
        FROM publisher_updates pu
        LEFT JOIN feeds_metadata_latest fm ON pu.price_feed_id = fm.pyth_lazer_id
        WHERE pu.publish_time >= {start:DateTime}
          AND pu.publish_time <  {end:DateTime}
        GROUP BY pu.publisher_id, pu.price_feed_id, fm.asset_type, fm.symbol
        ORDER BY pu.publisher_id, fm.asset_type, pu.price_feed_id
    """
    result = client.query(query, parameters={"start": start, "end": end})

    rows: list[PublisherFeedRow] = []
    for publisher_id, feed_id, update_count, asset_type, symbol in result.result_rows:
        asset_type = asset_type or "unknown"
        symbol = symbol or ""
        asset_class = categorize_asset_class(asset_type, symbol)

        if asset_class_filter and asset_class != asset_class_filter:
            continue

        rows.append(
            PublisherFeedRow(
                publisher_id=int(publisher_id),
                publisher_name=names.get(int(publisher_id), ""),
                feed_id=int(feed_id),
                symbol=symbol,
                asset_class=asset_class,
                update_count=int(update_count),
            )
        )
    return rows
