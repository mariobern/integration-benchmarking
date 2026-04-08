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


def main() -> None:
    print(
        f"WTIK6 deviation check — feed {FEED_ID}, window {WINDOW_START} .. {WINDOW_END}"
    )
    config = load_config()
    lazer = get_lazer_client(config)
    analytics = get_analytics_client(config)

    symbol, exponent, divisor = resolve_divisor(lazer)
    print(f"Feed metadata: symbol={symbol}, exponent={exponent}, divisor={divisor}")
    # Further wiring added in later tasks.


if __name__ == "__main__":
    main()
