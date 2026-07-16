"""Diagnostic: active-publisher distribution + update concentration.

For every STABLE (feed, session) in a new-format Lazer config, over a UTC
date window restricted to session open minutes:

  - histogram of per-minute active publisher counts (skew vs minPublishers);
    a publisher is active in a minute iff it has >=1 ACCEPTED update there
  - per-publisher ACCEPTED update totals and concentration
    (effective publishers = inverse HHI, top-1/top-3 shares)

Pure diagnostic: no config edits, no coupling to the min_pub Stage 1-3
pipeline. Render the CSVs with lazer_dq.render_active_pub_html.

Run:
    python3 -m lazer_dq.active_pub_distribution --config lazer_new.json \
        --start-date 2026-07-09 --end-date 2026-07-16 --workers 8
"""
from __future__ import annotations

import numpy as np


def histogram_pcts(active_counts: np.ndarray) -> dict[int, float]:
    """% of open minutes at each active-count k (2 dp). {} for empty input."""
    if len(active_counts) == 0:
        return {}
    values, counts = np.unique(active_counts, return_counts=True)
    n = len(active_counts)
    return {int(k): round(100.0 * c / n, 2) for k, c in zip(values, counts)}


def encode_hist(hist: dict[int, float]) -> str:
    """Compact CSV encoding: '3:12.50;4:25.00;5:62.50' (ascending k)."""
    return ";".join(f"{k}:{pct:.2f}" for k, pct in sorted(hist.items()))


def skew_metrics(active_counts: np.ndarray, min_pub: int) -> dict:
    """Skew of the active-count distribution vs min_pub. Caller ensures len > 0."""
    n = len(active_counts)
    return {
        "open_minutes": n,
        "pct_minutes_le_min": round(
            100.0 * int((active_counts <= min_pub).sum()) / n, 2
        ),
        "pct_minutes_le_min_plus_1": round(
            100.0 * int((active_counts <= min_pub + 1).sum()) / n, 2
        ),
        "p10_active": round(float(np.percentile(active_counts, 10)), 2),
        "median_active": round(float(np.median(active_counts)), 2),
        "p90_active": round(float(np.percentile(active_counts, 90)), 2),
        "worst_minute_active": int(active_counts.min()),
    }


def concentration_metrics(update_totals: dict[int, int]) -> dict:
    """Inverse-HHI effective publishers + top-1/top-3 shares of ACCEPTED updates."""
    total = sum(update_totals.values())
    if total == 0:
        return {
            "effective_publishers": 0.0,
            "top1_share_pct": 0.0,
            "top3_share_pct": 0.0,
        }
    shares = sorted((u / total for u in update_totals.values() if u > 0), reverse=True)
    hhi = sum(s * s for s in shares)
    return {
        "effective_publishers": round(1.0 / hhi, 2),
        "top1_share_pct": round(100.0 * shares[0], 2),
        "top3_share_pct": round(100.0 * sum(shares[:3]), 2),
    }
