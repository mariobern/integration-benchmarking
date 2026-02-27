"""Generate price_id_list.csv from feed IDs and lazer_symbols.json.

Resolves each feed's asset class from lazer_symbols.json and pairs it with
the requested date(s) to produce a CSV compatible with quick_benchmark.py,
feed_readiness.py, and other batch-processing scripts.

Usage:
    python3 generate_price_list.py --feed-id 327 340 346 --date 2026-02-27
    python3 generate_price_list.py --feed-ids-file feeds.txt --start-date 2026-02-24 --end-date 2026-02-27
"""

from __future__ import annotations

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
