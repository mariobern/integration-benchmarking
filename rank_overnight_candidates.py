#!/usr/bin/env python3
"""Rank overnight candidates by volume profile for BlueOcean.

Joins volume_profile.py output with the candidate metadata from
extract_overnight_candidates.py, sorts descending by after-hours dollar volume,
and writes a ranked CSV. No tiering or cutoffs -- raw metrics for a human to
draw the line. Candidates with no volume data are reported as unresolved.

See docs/superpowers/specs/2026-06-12-overnight-candidates-design.md.
"""

import argparse
import sys
from pathlib import Path

import pandas as pd

OUTPUT_COLUMNS = [
    "ticker",
    "feedId",
    "state",
    "overnight_configured",
    "liquidity_tier",
    "total_dollar_vol",
    "regular_dollar_vol",
    "after_hours_dollar_vol",
    "after_hours_pct",
    "pre_market_dollar_vol",
]


def coerce_bool(value) -> bool:
    """Robustly read a bool that may have round-tripped through CSV as a string."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "yes")


def load_meta(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["overnight_configured"] = df["overnight_configured"].map(coerce_bool)
    return df


def split_resolved(volume: pd.DataFrame, meta: pd.DataFrame):
    """Return (resolved_meta, sorted_unresolved_tickers)."""
    vol_tickers = set(volume["ticker"])
    resolved = meta[meta["ticker"].isin(vol_tickers)]
    unresolved = sorted(meta.loc[~meta["ticker"].isin(vol_tickers), "ticker"])
    return resolved, unresolved


def join_and_rank(volume: pd.DataFrame, meta: pd.DataFrame) -> pd.DataFrame:
    """Inner-join on ticker, sort desc by after-hours dollar volume."""
    merged = meta.merge(volume, on="ticker", how="inner")
    merged = merged.sort_values(
        "after_hours_dollar_vol", ascending=False, na_position="last"
    ).reset_index(drop=True)
    result = merged[OUTPUT_COLUMNS].copy()
    # Ensure overnight_configured is native Python bool (not numpy.bool_) so that
    # identity checks (`is True`) work correctly in callers and tests.  Assigning
    # a plain list/Series of bools back into a DataFrame column causes pandas to
    # coerce to numpy bool dtype, so we must use pd.array with dtype=object.
    result["overnight_configured"] = pd.array(
        [coerce_bool(v) for v in result["overnight_configured"]], dtype=object
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--volume-csv",
        type=Path,
        required=True,
        help="Output CSV from volume_profile.py",
    )
    parser.add_argument(
        "--meta",
        type=Path,
        default=Path("overnight_candidates_meta.csv"),
        help="Candidate metadata CSV from extract_overnight_candidates.py",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("overnight_candidates_for_blueocean.csv"),
    )
    args = parser.parse_args()

    volume = pd.read_csv(args.volume_csv)
    if volume.empty:
        print(f"ERROR: {args.volume_csv} has no rows.", file=sys.stderr)
        sys.exit(1)

    meta = load_meta(args.meta)
    resolved, unresolved = split_resolved(volume, meta)
    ranked = join_and_rank(volume, meta)
    ranked.to_csv(args.output, index=False)

    net_new = int((~ranked["overnight_configured"].astype(bool)).sum())
    configured = len(ranked) - net_new
    print(
        f"Ranked {len(ranked)} candidates "
        f"({net_new} net-new, {configured} already-configured) -> {args.output}",
        file=sys.stderr,
    )
    print(f"Unresolved (no volume data): {len(unresolved)}", file=sys.stderr)
    if unresolved:
        print("  " + ", ".join(unresolved), file=sys.stderr)
    print("Top 10 by after-hours dollar volume:", file=sys.stderr)
    for _, row in ranked.head(10).iterrows():
        print(
            f"  {row['ticker']:8s} ${row['after_hours_dollar_vol']:>14,.0f} "
            f"[{row['liquidity_tier']}] "
            f"{'configured' if row['overnight_configured'] else 'net-new'}",
            file=sys.stderr,
        )


if __name__ == "__main__":
    main()
