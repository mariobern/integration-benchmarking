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


def main() -> None:
    print(
        f"WTIK6 deviation check — feed {FEED_ID}, window {WINDOW_START} .. {WINDOW_END}"
    )
    config = load_config()
    lazer = get_lazer_client(config)
    analytics = get_analytics_client(config)
    print("Connected to lazer + analytics clickhouse.")
    # Further wiring added in Task 10.


if __name__ == "__main__":
    main()
