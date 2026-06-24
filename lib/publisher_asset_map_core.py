"""Pure helpers for publisher_asset_map: day windows and rollups."""

import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from lib.asset_class import categorize_asset_class
from lib import sql_filters as _sf

_ET = ZoneInfo("America/New_York")
_UTC = ZoneInfo("UTC")


@dataclass
class PublisherFeedRow:
    """One (publisher, feed, session) contribution on the analyzed date."""

    publisher_id: int
    publisher_name: str
    feed_id: int
    symbol: str
    asset_class: str
    sampled_update_count: int
    session: str = "all"


@dataclass
class ProbeWindow:
    """A short [start_utc, end_utc) sampling window, labeled by its ET session."""

    session: str
    start_utc: str
    end_utc: str


def _session_for_et_minute(minute_of_day: int) -> str:
    """Map an ET minute-of-day (0..1439) to its trading-session label."""
    pre = _sf.US_EQUITY_PREMARKET_OPEN_HOUR * 60 + _sf.US_EQUITY_PREMARKET_OPEN_MINUTE
    reg = _sf.US_EQUITY_MARKET_OPEN_HOUR * 60 + _sf.US_EQUITY_MARKET_OPEN_MINUTE
    aft = _sf.US_EQUITY_MARKET_CLOSE_HOUR * 60 + _sf.US_EQUITY_MARKET_CLOSE_MINUTE
    ovn = _sf.US_EQUITY_OVERNIGHT_START_HOUR * 60 + _sf.US_EQUITY_OVERNIGHT_START_MINUTE
    m = minute_of_day
    if m >= ovn or m < pre:
        return "overnight"
    if m < reg:
        return "premarket"
    if m < aft:
        return "regular"
    return "afterhours"


def session_probe_windows(
    date_str: str, interval_min: int = 30, width_min: int = 2
) -> list[ProbeWindow]:
    """Uniform 24h grid of probe windows from 04:00 ET, each labeled by ET session."""
    d = date.fromisoformat(date_str)
    pre_min = (
        _sf.US_EQUITY_PREMARKET_OPEN_HOUR * 60 + _sf.US_EQUITY_PREMARKET_OPEN_MINUTE
    )
    day_start_et = datetime(d.year, d.month, d.day, tzinfo=_ET) + timedelta(
        minutes=pre_min
    )
    n = 1440 // interval_min
    windows: list[ProbeWindow] = []
    for k in range(n):
        start_et = day_start_et + timedelta(minutes=interval_min * k)
        end_et = start_et + timedelta(minutes=width_min)
        session = _session_for_et_minute(start_et.hour * 60 + start_et.minute)
        windows.append(
            ProbeWindow(
                session=session,
                start_utc=start_et.astimezone(_UTC).strftime("%Y-%m-%d %H:%M:%S"),
                end_utc=end_et.astimezone(_UTC).strftime("%Y-%m-%d %H:%M:%S"),
            )
        )
    return windows


def day_window(date_str: str) -> tuple[str, str]:
    """Return [start, end) ClickHouse DateTime strings for the full UTC day."""
    start = date.fromisoformat(date_str)
    end = start + timedelta(days=1)
    return (f"{start.isoformat()} 00:00:00", f"{end.isoformat()} 00:00:00")


def _et_session_bounds() -> tuple[int, int, int, int]:
    """ET session boundaries as minutes-from-midnight, from sql_filters constants.

    Returns (premarket_start, regular_start, afterhours_start, overnight_start).
    """
    return (
        _sf.US_EQUITY_PREMARKET_OPEN_HOUR * 60 + _sf.US_EQUITY_PREMARKET_OPEN_MINUTE,
        _sf.US_EQUITY_MARKET_OPEN_HOUR * 60 + _sf.US_EQUITY_MARKET_OPEN_MINUTE,
        _sf.US_EQUITY_MARKET_CLOSE_HOUR * 60 + _sf.US_EQUITY_MARKET_CLOSE_MINUTE,
        _sf.US_EQUITY_OVERNIGHT_START_HOUR * 60 + _sf.US_EQUITY_OVERNIGHT_START_MINUTE,
    )


def session_case_sql(time_column: str, symbol_column: str) -> str:
    """Build a ClickHouse expression bucketing each row into a trading session.

    Non-US-equity symbols (not matching 'Equity.US.%') yield 'all'. US-equity
    rows are bucketed by ET wall-clock minute-of-day into the four sessions,
    which tile the 24h clock with no gaps.
    """
    pre, reg, aft, ovn = _et_session_bounds()
    et = f"toTimeZone({time_column}, 'America/New_York')"
    m = f"(toHour({et}) * 60 + toMinute({et}))"
    return (
        "multiIf("
        f"{symbol_column} NOT LIKE 'Equity.US.%', 'all', "
        f"{m} >= {ovn} OR {m} < {pre}, 'overnight', "
        f"{m} < {reg}, 'premarket', "
        f"{m} < {aft}, 'regular', "
        "'afterhours')"
    )


def feeds_by_asset_class(rows: list[PublisherFeedRow]) -> dict[str, int]:
    """Distinct feed count per asset class across all publishers."""
    feeds: dict[str, set] = defaultdict(set)
    for r in rows:
        feeds[r.asset_class].add(r.feed_id)
    return {cls: len(feed_ids) for cls, feed_ids in sorted(feeds.items())}


_SESSION_ORDER = ("premarket", "regular", "afterhours", "overnight")


def feeds_by_session(rows: list[PublisherFeedRow]) -> dict[str, int]:
    """Distinct US-equity feed count per session, in canonical session order."""
    feeds: dict[str, set] = defaultdict(set)
    for r in rows:
        if r.asset_class == "equity-us":
            feeds[r.session].add(r.feed_id)
    return {s: len(feeds[s]) for s in _SESSION_ORDER if s in feeds}


def build_summary(rows: list[PublisherFeedRow]) -> list[dict]:
    """One row per (publisher_id, asset_class, session) with counts."""
    feed_count: dict[tuple[int, str, str], int] = defaultdict(int)
    total_updates: dict[tuple[int, str, str], int] = defaultdict(int)
    names: dict[int, str] = {}
    for r in rows:
        key = (r.publisher_id, r.asset_class, r.session)
        feed_count[key] += 1
        total_updates[key] += r.sampled_update_count
        names[r.publisher_id] = r.publisher_name

    out = [
        {
            "publisher_id": pub_id,
            "publisher_name": names[pub_id],
            "asset_class": asset_class,
            "session": session,
            "feed_count": feed_count[(pub_id, asset_class, session)],
            "sampled_total_updates": total_updates[(pub_id, asset_class, session)],
        }
        for (pub_id, asset_class, session) in feed_count
    ]
    out.sort(key=lambda r: (r["publisher_id"], r["asset_class"], r["session"]))
    return out


def build_matrix(rows: list[PublisherFeedRow]) -> tuple[list[str], list[dict]]:
    """Wide pivot: publisher rows, one column per asset class (distinct feed counts).

    Session-agnostic: a feed published across multiple sessions counts once.
    """
    classes = sorted({r.asset_class for r in rows})
    feeds: dict[int, dict[str, set]] = defaultdict(lambda: defaultdict(set))
    names: dict[int, str] = {}
    for r in rows:
        feeds[r.publisher_id][r.asset_class].add(r.feed_id)
        names[r.publisher_id] = r.publisher_name

    matrix = []
    for pub_id in sorted(feeds):
        row = {"publisher_id": pub_id, "publisher_name": names[pub_id]}
        for cls in classes:
            row[cls] = len(feeds[pub_id].get(cls, set()))
        matrix.append(row)
    return classes, matrix


def fetch_publisher_names(client) -> dict[int, str]:
    """Map publisher_id -> name from publishers_metadata_latest (live)."""
    query = """
        SELECT publisher_id, publisher_name
        FROM publishers_metadata_latest
        FINAL
    """
    result = client.query(query)
    return {int(row[0]): (row[1] or "") for row in result.result_rows}


def fetch_publisher_feeds(
    client,
    date_str: str,
    asset_class_filter: Optional[str] = None,
) -> list[PublisherFeedRow]:
    """Query one UTC day of publisher_updates, grouped per (publisher, feed)."""
    start, end = day_window(date_str)
    names = fetch_publisher_names(client)

    session_expr = session_case_sql("pu.publish_time", "fm.symbol")
    query = """
        SELECT
            pu.publisher_id AS publisher_id,
            pu.price_feed_id AS feed_id,
            count() AS update_count,
            fm.asset_type AS asset_type,
            fm.symbol AS symbol,
            __SESSION_CASE__ AS session
        FROM publisher_updates pu
        LEFT JOIN feeds_metadata_latest fm ON pu.price_feed_id = fm.pyth_lazer_id
        WHERE pu.publish_time >= {start:DateTime}
          AND pu.publish_time <  {end:DateTime}
        GROUP BY pu.publisher_id, pu.price_feed_id, fm.asset_type, fm.symbol, session
        ORDER BY pu.publisher_id, fm.asset_type, pu.price_feed_id, session
    """.replace(
        "__SESSION_CASE__", session_expr
    )
    result = client.query(query, parameters={"start": start, "end": end})

    rows: list[PublisherFeedRow] = []
    for (
        publisher_id,
        feed_id,
        update_count,
        asset_type,
        symbol,
        session,
    ) in result.result_rows:
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
                sampled_update_count=int(update_count),
                session=session or "all",
            )
        )
    return rows


def write_outputs(
    rows: list[PublisherFeedRow],
    date_str: str,
    output_dir: Path,
) -> list[Path]:
    """Write detail, summary, and matrix CSVs. Returns their paths in order."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    detail_path = output_dir / f"publisher_asset_map_{date_str}.csv"
    summary_path = output_dir / f"publisher_asset_map_summary_{date_str}.csv"
    matrix_path = output_dir / f"publisher_asset_map_matrix_{date_str}.csv"

    sorted_rows = sorted(
        rows, key=lambda r: (r.publisher_id, r.asset_class, r.feed_id, r.session)
    )
    with open(detail_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "publisher_id",
                "publisher_name",
                "feed_id",
                "symbol",
                "asset_class",
                "session",
                "sampled_update_count",
            ]
        )
        for r in sorted_rows:
            writer.writerow(
                [
                    r.publisher_id,
                    r.publisher_name,
                    r.feed_id,
                    r.symbol,
                    r.asset_class,
                    r.session,
                    r.sampled_update_count,
                ]
            )

    summary = build_summary(rows)
    with open(summary_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "publisher_id",
                "publisher_name",
                "asset_class",
                "session",
                "feed_count",
                "sampled_total_updates",
            ]
        )
        for s in summary:
            writer.writerow(
                [
                    s["publisher_id"],
                    s["publisher_name"],
                    s["asset_class"],
                    s["session"],
                    s["feed_count"],
                    s["sampled_total_updates"],
                ]
            )

    classes, matrix = build_matrix(rows)
    with open(matrix_path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["publisher_id", "publisher_name", *classes])
        for m in matrix:
            writer.writerow(
                [m["publisher_id"], m["publisher_name"], *[m[c] for c in classes]]
            )

    return [detail_path, summary_path, matrix_path]
