"""Pure helpers for publisher_asset_map: day windows and rollups."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, timedelta


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
