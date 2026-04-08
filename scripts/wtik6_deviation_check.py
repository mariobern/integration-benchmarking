"""One-off analysis: Pyth aggregate vs CLK26 deviation for WTIK6 (feed 2694).

Window: 2026-04-06 00:45:00 to 01:00:00 UTC.
Writes CSV, two matplotlib charts, and a markdown report under output_csv/.

See docs/superpowers/specs/2026-04-08-wtik6-aggregate-deviation-design.md
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path

# Add repo root to sys.path so `lib` is importable when run as a script.
sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from lib.benchmark_core import get_feed_metadata
from lib.config import get_analytics_client, get_lazer_client, load_config
from lib.sql_filters import get_benchmark_columns

# --- Analysis constants ------------------------------------------------------

FEED_ID = 2694
SYMBOL_SHORT = "wtik6"
DATE = "2026-04-06"
WINDOW_START = "2026-04-06 00:45:00"
WINDOW_END = "2026-04-06 01:00:00"  # exclusive
THRESHOLD_PCT = 1.0  # breach if abs(deviation_pct) > 1.0
MODE = "commodity"  # for lib.sql_filters.get_benchmark_columns
OUTPUT_DIR = Path("output_csv")
OUTPUT_PREFIX = "2694_wtik6_20260406_0045-0100"

# --- Entry point -------------------------------------------------------------


def resolve_divisor(lazer_client) -> tuple[str, int, float]:
    """Return (symbol, exponent, divisor) for FEED_ID.

    `divisor = 10 ** abs(exponent)` — matches the convention in
    lib/benchmark_core.py where prices are stored as scaled integers.
    """
    symbol, exponent = get_feed_metadata(lazer_client, FEED_ID)
    if symbol is None or exponent is None:
        raise RuntimeError(
            f"Feed metadata not found for feed_id={FEED_ID}. "
            "Verify the feed exists in feeds_metadata_latest."
        )
    divisor = 10 ** abs(exponent)
    return symbol, exponent, divisor


def query_pyth_aggregate(lazer_client, divisor: float) -> tuple[pd.DataFrame, int]:
    """Query per-second Pyth aggregate price, trying channels 1 → 2 → 3.

    Returns (df, channel_used). df has columns [ts, agg_price, n_pyth_updates]
    with ts as UTC-aware datetime. Returns (empty df, -1) if all channels empty.
    """
    for channel in (1, 2, 3):
        query = f"""
            SELECT
                toStartOfSecond(publish_time) AS ts,
                avg(price) / {divisor} AS agg_price,
                count() AS n_pyth_updates
            FROM price_feeds
            WHERE price_feed_id = {FEED_ID}
              AND publish_time >= '{WINDOW_START}'
              AND publish_time <  '{WINDOW_END}'
              AND price IS NOT NULL
              AND channel = {channel}
            GROUP BY ts
            ORDER BY ts
        """
        result = lazer_client.query(query)
        if result.result_rows:
            df = pd.DataFrame(
                result.result_rows, columns=["ts", "agg_price", "n_pyth_updates"]
            )
            df["ts"] = pd.to_datetime(df["ts"], utc=True)
            return df, channel
    return pd.DataFrame(columns=["ts", "agg_price", "n_pyth_updates"]), -1


def main() -> None:
    print(
        f"WTIK6 deviation check — feed {FEED_ID}, window {WINDOW_START} .. {WINDOW_END}"
    )
    config = load_config()
    lazer = get_lazer_client(config)
    analytics = get_analytics_client(config)

    symbol, exponent, divisor = resolve_divisor(lazer)
    print(f"Feed metadata: symbol={symbol}, exponent={exponent}, divisor={divisor}")

    pyth_df, channel = query_pyth_aggregate(lazer, divisor)
    print(f"Pyth aggregate: {len(pyth_df)} rows, channel={channel}")
    if not pyth_df.empty:
        print(f"  first ts={pyth_df['ts'].iloc[0]}, last ts={pyth_df['ts'].iloc[-1]}")
        print(
            f"  price range: {pyth_df['agg_price'].min():.4f} .. "
            f"{pyth_df['agg_price'].max():.4f}"
        )


if __name__ == "__main__":
    main()
