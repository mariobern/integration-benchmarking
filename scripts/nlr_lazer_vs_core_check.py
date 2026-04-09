"""One-off analysis: Pyth Lazer (Pro) vs Pyth Core (Hermes) for NLR.PRE.

Window: 2026-04-08 08:00:00 to 09:00:00 UTC, inclusive on both ends.
Reads two pre-exported CSVs at the repo root and writes a per-second CSV,
three matplotlib charts, and a markdown report under output_csv/.

See docs/superpowers/specs/2026-04-09-nlr-lazer-vs-core-check-design.md
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import pandas as pd

# --- Analysis constants ------------------------------------------------------

LAZER_FEED_ID = 2928
HERMES_SYMBOL = "Equity.US.NLR/USD.PRE"
WINDOW_START = "2026-04-08 08:00:00"
WINDOW_END = "2026-04-08 09:00:00"  # inclusive — matches the exported CSVs
EXPECTED_ROWS = 3601  # 60 * 60 + 1, since both endpoints are inclusive
EXPECTED_EXPO = -5
STUCKNESS_THRESHOLD_USD = 0.01

HERMES_CSV = Path("hermes_price_export.csv")
LAZER_CSV = Path("lazer_price_export.csv")
OUTPUT_DIR = Path("output_csv")
OUTPUT_PREFIX = "2928_nlr_pre_20260408_0800-0900"

# --- Loaders -----------------------------------------------------------------


def load_hermes() -> pd.DataFrame:
    """Load Pyth Core export, validate, and convert to USD floats.

    Returns a DataFrame indexed by UTC timestamp with columns
    [hermes_price, hermes_conf]. Raises RuntimeError on any data-shape
    violation rather than silently mis-scaling.
    """
    df = pd.read_csv(HERMES_CSV)

    expected_cols = {"symbol", "intervalTime", "price", "confidence", "expo"}
    missing = expected_cols - set(df.columns)
    if missing:
        raise RuntimeError(f"Hermes CSV missing columns: {sorted(missing)}")

    bad_symbols = set(df["symbol"].unique()) - {HERMES_SYMBOL}
    if bad_symbols:
        raise RuntimeError(
            f"Hermes CSV contains unexpected symbols: {sorted(bad_symbols)}"
        )

    bad_expos = set(df["expo"].unique()) - {EXPECTED_EXPO}
    if bad_expos:
        raise RuntimeError(
            f"Hermes CSV has unexpected expo values: {sorted(bad_expos)} "
            f"(expected only {EXPECTED_EXPO})"
        )

    if len(df) != EXPECTED_ROWS:
        raise RuntimeError(f"Hermes CSV has {len(df)} rows, expected {EXPECTED_ROWS}")

    scale = 10**EXPECTED_EXPO  # = 1e-5
    out = pd.DataFrame(
        {
            "ts": pd.to_datetime(df["intervalTime"], utc=True),
            "hermes_price": df["price"] * scale,
            "hermes_conf": df["confidence"] * scale,
        }
    )
    return out.set_index("ts")


def load_lazer() -> pd.DataFrame:
    """Load Pyth Lazer export, validate, and convert to USD floats.

    Returns a DataFrame indexed by UTC timestamp with columns
    [lazer_price, lazer_conf, lazer_bid, lazer_ask].
    """
    df = pd.read_csv(LAZER_CSV)

    expected_cols = {
        "price_feed_id",
        "interval_price",
        "price",
        "confidence",
        "best_bid_price",
        "best_ask_price",
        "exponent",
    }
    missing = expected_cols - set(df.columns)
    if missing:
        raise RuntimeError(f"Lazer CSV missing columns: {sorted(missing)}")

    bad_ids = set(df["price_feed_id"].unique()) - {LAZER_FEED_ID}
    if bad_ids:
        raise RuntimeError(
            f"Lazer CSV contains unexpected price_feed_ids: {sorted(bad_ids)}"
        )

    bad_expos = set(df["exponent"].unique()) - {EXPECTED_EXPO}
    if bad_expos:
        raise RuntimeError(
            f"Lazer CSV has unexpected exponent values: {sorted(bad_expos)} "
            f"(expected only {EXPECTED_EXPO})"
        )

    if len(df) != EXPECTED_ROWS:
        raise RuntimeError(f"Lazer CSV has {len(df)} rows, expected {EXPECTED_ROWS}")

    scale = 10**EXPECTED_EXPO
    out = pd.DataFrame(
        {
            "ts": pd.to_datetime(df["interval_price"], utc=True),
            "lazer_price": df["price"] * scale,
            "lazer_conf": df["confidence"] * scale,
            "lazer_bid": df["best_bid_price"] * scale,
            "lazer_ask": df["best_ask_price"] * scale,
        }
    )
    return out.set_index("ts")


# --- Entry point -------------------------------------------------------------


def main() -> None:
    print(f"Loading {HERMES_CSV} ...")
    hermes = load_hermes()
    print(f"  -> {len(hermes)} rows, columns={list(hermes.columns)}")
    print(f"  first ts: {hermes.index[0]}, last ts: {hermes.index[-1]}")
    print(f"  first hermes_price: {hermes['hermes_price'].iloc[0]:.4f}")
    print(f"  last hermes_price:  {hermes['hermes_price'].iloc[-1]:.4f}")

    print(f"Loading {LAZER_CSV} ...")
    lazer = load_lazer()
    print(f"  -> {len(lazer)} rows, columns={list(lazer.columns)}")
    print(f"  first ts: {lazer.index[0]}, last ts: {lazer.index[-1]}")
    print(f"  first lazer_price: {lazer['lazer_price'].iloc[0]:.4f}")
    print(f"  last lazer_price:  {lazer['lazer_price'].iloc[-1]:.4f}")


if __name__ == "__main__":
    main()
