"""Generate price_id_list.csv from feed IDs and lazer_symbols.json.

Resolves each feed's asset class from lazer_symbols.json and pairs it with
the requested date(s) to produce a CSV compatible with quick_benchmark.py,
feed_readiness.py, and other batch-processing scripts.

Usage:
    python3 generate_price_list.py --feed-id 327 340 346 --date 2026-02-27
    python3 generate_price_list.py --feed-ids-file feeds.txt --start-date 2026-02-24 --end-date 2026-02-27
"""

from __future__ import annotations

import csv
import json
from datetime import date, timedelta
from pathlib import Path

from lib.config import BENCHMARKABLE_ASSET_CLASSES, normalize_asset_class


def resolve_feed_mode(entry: dict) -> str | None:
    """Map a lazer_symbols.json entry to its CSV mode value.

    Returns None if the feed is not benchmarkable (crypto, nav, non-US equity, etc.).
    """
    asset_type = entry.get("asset_type", "")
    symbol = entry.get("symbol", "")

    # Equities require US region check
    if asset_type == "equity":
        if not symbol.startswith("Equity.US."):
            return None
        return "us-equities"

    mode = normalize_asset_class(asset_type)
    if mode not in BENCHMARKABLE_ASSET_CLASSES:
        return None
    return mode


def load_symbols(path: Path) -> list[dict]:
    """Load symbols from a lazer_symbols.json file."""
    if not path.exists():
        raise FileNotFoundError(f"Symbols file not found: {path}")
    with open(path) as f:
        return json.load(f)


def build_lookup(symbols: list[dict]) -> dict[int, dict]:
    """Build a {pyth_lazer_id: entry} lookup dict."""
    return {entry["pyth_lazer_id"]: entry for entry in symbols}


def resolve_feeds(
    feed_ids: list[int], lookup: dict[int, dict]
) -> tuple[dict[int, str], list[str]]:
    """Resolve feed IDs to their CSV mode values.

    Returns:
        resolved: {feed_id: mode} for benchmarkable feeds
        skipped: list of warning messages for skipped feeds
    """
    resolved: dict[int, str] = {}
    skipped: list[str] = []

    for fid in feed_ids:
        if fid not in lookup:
            skipped.append(f"Feed {fid}: not found in symbols file")
            continue

        entry = lookup[fid]
        mode = resolve_feed_mode(entry)

        if mode is None:
            asset_type = entry.get("asset_type", "unknown")
            symbol = entry.get("symbol", "")
            if asset_type == "equity":
                skipped.append(
                    f"Feed {fid} ({symbol}): non-US equity, not benchmarkable"
                )
            else:
                skipped.append(
                    f"Feed {fid} ({symbol}): {asset_type} is not benchmarkable"
                )
            continue

        resolved[fid] = mode

    return resolved, skipped


def expand_dates(start: date, end: date) -> list[date]:
    """Expand a date range into a list of individual dates (inclusive)."""
    if start > end:
        raise ValueError(f"start date {start} is after end date {end}")
    dates = []
    current = start
    while current <= end:
        dates.append(current)
        current += timedelta(days=1)
    return dates


def write_csv(resolved: dict[int, str], dates: list[date], output: Path) -> int:
    """Write price_id_list CSV (no header). Returns row count."""
    output.parent.mkdir(parents=True, exist_ok=True)
    row_count = 0
    with open(output, "w", newline="") as f:
        writer = csv.writer(f)
        for feed_id in sorted(resolved):
            mode = resolved[feed_id]
            for d in dates:
                writer.writerow([feed_id, d.isoformat(), mode])
                row_count += 1
    return row_count


def parse_feed_ids_file(path: Path) -> list[int]:
    """Parse feed IDs from a text file (one per line, # comments allowed)."""
    if not path.exists():
        raise FileNotFoundError(f"Feed IDs file not found: {path}")
    feed_ids = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            feed_ids.append(int(line))
    return feed_ids
