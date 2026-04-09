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


# --- Merge + derive ----------------------------------------------------------


def build_merged(hermes: pd.DataFrame, lazer: pd.DataFrame) -> pd.DataFrame:
    """Inner-join Hermes and Lazer on second-resolution timestamp.

    Asserts both inputs already align with the expected 3601-second
    [WINDOW_START, WINDOW_END] inclusive index. Returns a frame with
    columns:
        hermes_price, hermes_conf,
        lazer_price, lazer_conf, lazer_bid, lazer_ask,
        deviation_abs, deviation_pct,
        lazer_spread, lazer_price_step, lazer_stuck
    """
    full_index = pd.date_range(
        start=WINDOW_START,
        end=WINDOW_END,
        freq="1s",
        tz="UTC",
        inclusive="both",
    )
    if len(full_index) != EXPECTED_ROWS:
        raise RuntimeError(
            f"Expected {EXPECTED_ROWS} index rows, got {len(full_index)}"
        )
    if not hermes.index.equals(full_index):
        raise RuntimeError(
            "Hermes timestamps do not align with the expected per-second index"
        )
    if not lazer.index.equals(full_index):
        raise RuntimeError(
            "Lazer timestamps do not align with the expected per-second index"
        )

    merged = hermes.join(lazer, how="inner")
    if len(merged) != EXPECTED_ROWS:
        raise RuntimeError(
            f"Merged frame has {len(merged)} rows, expected {EXPECTED_ROWS}"
        )

    merged["deviation_abs"] = merged["lazer_price"] - merged["hermes_price"]
    merged["deviation_pct"] = (
        (merged["lazer_price"] - merged["hermes_price"]) / merged["hermes_price"] * 100
    )
    merged["lazer_spread"] = merged["lazer_ask"] - merged["lazer_bid"]
    merged["lazer_price_step"] = merged["lazer_price"].diff().abs()
    merged["lazer_stuck"] = merged["lazer_price_step"] < STUCKNESS_THRESHOLD_USD
    return merged


def compute_summary(merged: pd.DataFrame) -> dict:
    """Compute the report summary stats from the merged frame."""
    abs_dev_pct = merged["deviation_pct"].abs()
    abs_dev_usd = merged["deviation_abs"].abs()
    return {
        "max_abs_dev_pct": float(abs_dev_pct.max()),
        "min_abs_dev_pct": float(abs_dev_pct.min()),
        "mean_abs_dev_pct": float(abs_dev_pct.mean()),
        "max_abs_dev_usd": float(abs_dev_usd.max()),
        "min_abs_dev_usd": float(abs_dev_usd.min()),
        "mean_abs_dev_usd": float(abs_dev_usd.mean()),
        "max_dev_pct_ts": abs_dev_pct.idxmax(),
        "mean_lazer_spread_usd": float(merged["lazer_spread"].mean()),
        "mean_lazer_conf_usd": float(merged["lazer_conf"].mean()),
        "mean_hermes_conf_usd": float(merged["hermes_conf"].mean()),
        "stuck_seconds_pct": float(
            merged["lazer_stuck"].sum() / (len(merged) - 1) * 100
        ),
        "hermes_price_first": float(merged["hermes_price"].iloc[0]),
        "hermes_price_last": float(merged["hermes_price"].iloc[-1]),
        "lazer_price_first": float(merged["lazer_price"].iloc[0]),
        "lazer_price_last": float(merged["lazer_price"].iloc[-1]),
        "mean_deviation_pct": float(merged["deviation_pct"].mean()),
        "mean_deviation_usd": float(merged["deviation_abs"].mean()),
    }


# --- Outputs -----------------------------------------------------------------


def write_csv(merged: pd.DataFrame) -> Path:
    """Write the per-second comparison table under OUTPUT_DIR."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{OUTPUT_PREFIX}.csv"
    columns = [
        "hermes_price",
        "hermes_conf",
        "lazer_price",
        "lazer_conf",
        "lazer_bid",
        "lazer_ask",
        "deviation_abs",
        "deviation_pct",
        "lazer_spread",
        "lazer_price_step",
        "lazer_stuck",
    ]
    merged[columns].to_csv(out_path, index_label="ts", float_format="%.6f")
    return out_path


# --- Entry point -------------------------------------------------------------


def main() -> None:
    print(f"Loading {HERMES_CSV} ...")
    hermes = load_hermes()
    print(f"  -> {len(hermes)} rows")

    print(f"Loading {LAZER_CSV} ...")
    lazer = load_lazer()
    print(f"  -> {len(lazer)} rows")

    print("Merging frames ...")
    merged = build_merged(hermes, lazer)
    print(f"  -> {len(merged)} rows, columns={list(merged.columns)}")

    print("Computing summary ...")
    summary = compute_summary(merged)
    for k, v in summary.items():
        print(f"  {k}: {v}")

    print("Writing CSV ...")
    csv_path = write_csv(merged)
    print(f"  -> {csv_path}")


if __name__ == "__main__":
    main()
