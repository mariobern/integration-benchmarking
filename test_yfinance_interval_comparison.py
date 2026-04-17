#!/usr/bin/env python3
"""Compare yfinance 1m vs 5m vs 1d volume data for extended hours accuracy.

Tests whether 1-minute bars with prepost=True give accurate per-session volume,
potentially replacing the current daily_vol - regular_vol estimation approach.
"""

from __future__ import annotations

import sys
from datetime import date, timedelta

import pandas as pd
import yfinance as yf

TICKERS = ["AAPL", "MSFT", "NVDA", "TSLA", "AMD"]


def fetch_all_intervals(tickers: list[str], d: date) -> dict[str, pd.DataFrame]:
    """Download 1m, 5m, and 1d data for the given date."""
    start = d.isoformat()
    end = (d + timedelta(days=1)).isoformat()

    print(f"Downloading data for {d} ...", file=sys.stderr)

    data_1m = yf.download(
        tickers=tickers,
        start=start,
        end=end,
        interval="1m",
        prepost=True,
        progress=False,
    )
    data_5m = yf.download(
        tickers=tickers,
        start=start,
        end=end,
        interval="5m",
        prepost=True,
        progress=False,
    )
    data_1d = yf.download(
        tickers=tickers,
        start=start,
        end=end,
        interval="1d",
        progress=False,
    )

    return {"1m": data_1m, "5m": data_5m, "1d": data_1d}


def bucket_volume(df: pd.DataFrame, ticker: str, is_multi: bool) -> dict[str, int]:
    """Sum volume per session from intraday bars."""
    try:
        if is_multi:
            tdf = df.xs(ticker, level=1, axis=1)
        else:
            tdf = df
    except KeyError:
        return {"pre_market": 0, "regular": 0, "after_hours": 0, "total": 0}

    if tdf.empty:
        return {"pre_market": 0, "regular": 0, "after_hours": 0, "total": 0}

    idx = tdf.index
    if idx.tz is None:
        idx = idx.tz_localize("America/New_York")
    else:
        idx = idx.tz_convert("America/New_York")
    tdf = tdf.copy()
    tdf.index = idx

    pre = tdf.between_time("04:00", "09:29")
    regular = tdf.between_time("09:30", "15:59")
    after = tdf.between_time("16:00", "19:59")

    pre_vol = int(pre["Volume"].sum()) if not pre.empty else 0
    reg_vol = int(regular["Volume"].sum()) if not regular.empty else 0
    ah_vol = int(after["Volume"].sum()) if not after.empty else 0

    return {
        "pre_market": pre_vol,
        "regular": reg_vol,
        "after_hours": ah_vol,
        "total": pre_vol + reg_vol + ah_vol,
    }


def get_1d_volume(data_1d: pd.DataFrame, ticker: str, is_multi: bool) -> int:
    """Extract daily volume from 1d bars."""
    try:
        if is_multi:
            tdf = data_1d.xs(ticker, level=1, axis=1)
        else:
            tdf = data_1d
        if not tdf.empty:
            return int(tdf["Volume"].iloc[0])
    except (KeyError, IndexError):
        pass
    return 0


def current_approach_volumes(vol_5m: dict[str, int], daily_vol: int) -> dict[str, int]:
    """Replicate the current volume_profile.py estimation logic.

    regular_vol from 5m bars; extended = daily - regular, split evenly.
    """
    reg = vol_5m["regular"]
    extended = max(0, daily_vol - reg)
    # Simplified: split 50/50 (actual code uses active bar ratio)
    pre = extended // 2
    ah = extended - pre
    return {
        "pre_market": pre,
        "regular": reg,
        "after_hours": ah,
        "total": pre + reg + ah,
    }


def fmt_vol(v: int) -> str:
    return f"{v:>12,}"


def fmt_pct(part: int, total: int) -> str:
    if total == 0:
        return "   N/A"
    return f"{part / total * 100:5.1f}%"


def main() -> None:
    d = date.today() - timedelta(days=1)
    # Skip weekends
    while d.weekday() >= 5:
        d -= timedelta(days=1)

    data = fetch_all_intervals(TICKERS, d)

    is_multi_1m = isinstance(data["1m"].columns, pd.MultiIndex)
    is_multi_5m = isinstance(data["5m"].columns, pd.MultiIndex)
    is_multi_1d = (
        isinstance(data["1d"].columns, pd.MultiIndex) if not data["1d"].empty else False
    )

    print(f"\n{'=' * 90}")
    print(f"  yfinance Volume Comparison — {d}")
    print(f"{'=' * 90}")

    rows = []

    for ticker in TICKERS:
        vol_1m = bucket_volume(data["1m"], ticker, is_multi_1m)
        vol_5m = bucket_volume(data["5m"], ticker, is_multi_5m)
        daily_vol = get_1d_volume(data["1d"], ticker, is_multi_1d)
        est = current_approach_volumes(vol_5m, daily_vol)

        rows.append(
            {
                "ticker": ticker,
                "daily_1d": daily_vol,
                "total_1m": vol_1m["total"],
                "total_5m": vol_5m["total"],
                "match_1m_pct": vol_1m["total"] / daily_vol * 100 if daily_vol else 0,
                "match_5m_pct": vol_5m["total"] / daily_vol * 100 if daily_vol else 0,
                "pre_1m": vol_1m["pre_market"],
                "pre_5m": vol_5m["pre_market"],
                "pre_est": est["pre_market"],
                "reg_1m": vol_1m["regular"],
                "reg_5m": vol_5m["regular"],
                "reg_est": est["regular"],
                "ah_1m": vol_1m["after_hours"],
                "ah_5m": vol_5m["after_hours"],
                "ah_est": est["after_hours"],
            }
        )

    # --- Table 1: Total volume comparison ---
    print(f"\n  1. TOTAL VOLUME: Do intraday bars match the 1-day total?")
    print(
        f"  {'Ticker':<8} {'1d Total':>12} {'1m Total':>12} {'1m %':>7} {'5m Total':>12} {'5m %':>7}"
    )
    print(f"  {'-'*8} {'-'*12} {'-'*12} {'-'*7} {'-'*12} {'-'*7}")
    for r in rows:
        print(
            f"  {r['ticker']:<8}"
            f" {fmt_vol(r['daily_1d'])}"
            f" {fmt_vol(r['total_1m'])}"
            f" {r['match_1m_pct']:6.1f}%"
            f" {fmt_vol(r['total_5m'])}"
            f" {r['match_5m_pct']:6.1f}%"
        )

    # --- Table 2: Per-session comparison ---
    print(f"\n  2. PER-SESSION VOLUME: 1m direct vs 5m direct vs current estimation")
    print(f"  {'Ticker':<8} {'':8} {'Pre-Mkt':>12} {'Regular':>12} {'After-Hrs':>12}")
    print(f"  {'-'*8} {'-'*8} {'-'*12} {'-'*12} {'-'*12}")
    for r in rows:
        print(
            f"  {r['ticker']:<8} {'1m bars':8}{fmt_vol(r['pre_1m'])}{fmt_vol(r['reg_1m'])}{fmt_vol(r['ah_1m'])}"
        )
        print(
            f"  {'':8} {'5m bars':8}{fmt_vol(r['pre_5m'])}{fmt_vol(r['reg_5m'])}{fmt_vol(r['ah_5m'])}"
        )
        print(
            f"  {'':8} {'est.':8}{fmt_vol(r['pre_est'])}{fmt_vol(r['reg_est'])}{fmt_vol(r['ah_est'])}"
        )
        print()

    # --- Summary ---
    avg_1m = sum(r["match_1m_pct"] for r in rows) / len(rows)
    avg_5m = sum(r["match_5m_pct"] for r in rows) / len(rows)
    print(f"  SUMMARY")
    print(f"  Avg 1m coverage of 1d total: {avg_1m:.1f}%")
    print(f"  Avg 5m coverage of 1d total: {avg_5m:.1f}%")

    if avg_1m > 98:
        print(
            f"\n  CONCLUSION: 1m bars capture ~all daily volume. Safe to use direct session sums."
        )
    elif avg_1m > 90:
        print(
            f"\n  CONCLUSION: 1m bars capture most volume but ~{100-avg_1m:.0f}% is missing. Investigate."
        )
    else:
        print(
            f"\n  CONCLUSION: 1m bars miss significant volume ({100-avg_1m:.0f}%). Stick with current approach."
        )

    print(f"{'=' * 90}\n")


if __name__ == "__main__":
    main()
