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


def query_benchmark(analytics_client) -> pd.DataFrame:
    """Query per-second CLK26 benchmark price from datascope_futures_benchmark_data.

    Uses `lib.sql_filters.get_benchmark_columns("commodity")` to resolve the
    price/bid/ask column names (`price`, `bid_price`, `ask_price`).

    Returns df with columns [ts, bench_price, avg_spread, n_bench_ticks].
    """
    price_col, bid_col, ask_col = get_benchmark_columns(MODE)
    query = f"""
        SELECT
            toStartOfSecond(date_time) AS ts,
            avg(coalesce({price_col}, ({bid_col} + {ask_col}) / 2)) AS bench_price,
            avg(CASE
                    WHEN {ask_col} IS NOT NULL AND {bid_col} IS NOT NULL
                    THEN {ask_col} - {bid_col}
                END) AS avg_spread,
            count() AS n_bench_ticks
        FROM datascope_futures_benchmark_data
        WHERE pyth_lazer_id = {FEED_ID}
          AND date_time >= '{WINDOW_START}'
          AND date_time <  '{WINDOW_END}'
          AND ({price_col} IS NOT NULL
               OR ({bid_col} IS NOT NULL AND {ask_col} IS NOT NULL))
        GROUP BY ts
        ORDER BY ts
    """
    result = analytics_client.query(query)
    df = pd.DataFrame(
        result.result_rows,
        columns=["ts", "bench_price", "avg_spread", "n_bench_ticks"],
    )
    if not df.empty:
        df["ts"] = pd.to_datetime(df["ts"], utc=True)
    return df


def build_merged_frame(pyth_df: pd.DataFrame, bench_df: pd.DataFrame) -> pd.DataFrame:
    """Full-outer join Pyth + benchmark onto a complete 900-second UTC index.

    Raises RuntimeError if either input is empty — a silent empty merge would
    produce a 900-row all-NaN frame and a false "0 breaches" verdict.

    Returns a DataFrame indexed by ts with columns:
        agg_price, bench_price, avg_spread,
        n_pyth_updates, n_bench_ticks,
        deviation_abs, deviation_pct, abs_deviation_pct, breach,
        has_both
    """
    if pyth_df.empty:
        raise RuntimeError(
            "Pyth aggregate returned no rows — cannot compute deviation."
        )
    if bench_df.empty:
        raise RuntimeError(
            "CLK26 benchmark returned no rows — cannot compute deviation."
        )

    full_index = pd.date_range(
        start=WINDOW_START,
        end=WINDOW_END,
        freq="1s",
        tz="UTC",
        inclusive="left",  # exclusive end — matches WHERE clause
    )
    assert len(full_index) == 900, f"expected 900 seconds, got {len(full_index)}"

    pyth = pyth_df.set_index("ts")
    bench = bench_df.set_index("ts")

    merged = pd.DataFrame(index=full_index)
    merged.index.name = "ts"
    merged = merged.join(pyth, how="left").join(bench, how="left")

    merged["has_both"] = merged["agg_price"].notna() & merged["bench_price"].notna()
    merged["deviation_abs"] = merged["agg_price"] - merged["bench_price"]
    merged["deviation_pct"] = (
        (merged["agg_price"] - merged["bench_price"]) / merged["bench_price"] * 100
    )
    merged["abs_deviation_pct"] = merged["deviation_pct"].abs()
    merged["breach"] = merged["has_both"] & (
        merged["abs_deviation_pct"] > THRESHOLD_PCT
    )

    # Fill update/tick counts where no data was present
    merged["n_pyth_updates"] = merged["n_pyth_updates"].fillna(0).astype(int)
    merged["n_bench_ticks"] = merged["n_bench_ticks"].fillna(0).astype(int)
    return merged


def write_csv(merged: pd.DataFrame) -> Path:
    """Write the per-second comparison table under OUTPUT_DIR."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUTPUT_DIR / f"{OUTPUT_PREFIX}.csv"
    columns = [
        "agg_price",
        "bench_price",
        "deviation_abs",
        "deviation_pct",
        "abs_deviation_pct",
        "breach",
        "n_pyth_updates",
        "n_bench_ticks",
    ]
    merged[columns].to_csv(out_path, index_label="ts", float_format="%.6f")
    return out_path


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

    bench_df = query_benchmark(analytics)
    print(f"CLK26 benchmark: {len(bench_df)} rows")
    if not bench_df.empty:
        print(
            f"  first ts={bench_df['ts'].iloc[0]}, "
            f"last ts={bench_df['ts'].iloc[-1]}"
        )
        print(
            f"  price range: {bench_df['bench_price'].min():.4f} .. "
            f"{bench_df['bench_price'].max():.4f}"
        )

    merged = build_merged_frame(pyth_df, bench_df)
    both = merged["has_both"].sum()
    breaches = int(merged["breach"].sum())
    max_dev = merged.loc[merged["has_both"], "abs_deviation_pct"].max()
    print(
        f"Merged: {len(merged)} rows, joint-coverage={both}/900 "
        f"({both/900*100:.1f}%), breaches={breaches}, max_abs_dev={max_dev:.4f}%"
    )

    csv_path = write_csv(merged)
    print(f"Wrote {csv_path}")


if __name__ == "__main__":
    main()
