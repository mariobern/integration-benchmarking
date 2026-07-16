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
import pandas as pd

from lazer_dq.market_schedule import open_minutes_mask, parse_market_schedule
from lazer_dq.min_pub_common import FeedSession


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


SUMMARY_COLUMNS = [
    "feed_id",
    "symbol",
    "asset_type",
    "session",
    "note",
    "effective_min_pub",
    "allowed_count",
    "active_pub_count",
    "never_published_count",
    "unlisted_active_count",
    "open_minutes",
    "total_accepted_updates",
    "pct_minutes_le_min",
    "pct_minutes_le_min_plus_1",
    "p10_active",
    "median_active",
    "p90_active",
    "worst_minute_active",
    "active_hist",
    "effective_publishers",
    "top1_share_pct",
    "top3_share_pct",
]

DETAIL_COLUMNS = [
    "feed_id",
    "symbol",
    "session",
    "publisher_id",
    "accepted_updates",
    "update_share_pct",
    "minutes_active",
    "pct_open_minutes_active",
    "rank",
]


def fetch_per_minute_counts(client, feed_id, start_utc, end_utc):
    """Placeholder; defined with the query in the CLI section (Task 3)."""
    raise NotImplementedError


def _base(fs: FeedSession) -> dict:
    return {
        "feed_id": fs.feed_id,
        "symbol": fs.symbol,
        "asset_type": fs.asset_type,
        "session": fs.session,
        "note": "",
        "effective_min_pub": fs.effective_min_pub,
        "allowed_count": len(fs.allowed),
    }


def session_rows(fs, per_minute, mask):
    """(summary_row, detail_rows) for one feed-session.

    per_minute: dict UTC-minute pd.Timestamp -> {publisher_id: accepted_count}.
    Only allowed publishers count toward metrics; others feed
    unlisted_active_count (config snapshot drift sanity flag).
    """
    base = _base(fs)
    open_minutes = mask.index[mask.to_numpy()]
    if len(open_minutes) == 0:
        return {**base, "note": "ZERO_OPEN_MINUTES"}, []

    totals = {p: 0 for p in fs.allowed}
    minutes_active = {p: 0 for p in fs.allowed}
    counts = np.zeros(len(open_minutes), dtype=int)
    unlisted = set()
    for i, m in enumerate(open_minutes):
        for pub, n_updates in per_minute.get(m, {}).items():
            if pub in totals:
                totals[pub] += n_updates
                minutes_active[pub] += 1
                counts[i] += 1
            else:
                unlisted.add(pub)

    total_updates = int(sum(totals.values()))
    summary = {
        **base,
        "active_pub_count": sum(1 for u in totals.values() if u > 0),
        "never_published_count": sum(1 for u in totals.values() if u == 0),
        "unlisted_active_count": len(unlisted),
        "total_accepted_updates": total_updates,
        "active_hist": encode_hist(histogram_pcts(counts)),
        **skew_metrics(counts, fs.effective_min_pub),
        **concentration_metrics(totals),
    }

    n_open = len(open_minutes)
    ordered = sorted(fs.allowed, key=lambda p: (-totals[p], p))
    details = [
        {
            "feed_id": fs.feed_id,
            "symbol": fs.symbol,
            "session": fs.session,
            "publisher_id": p,
            "accepted_updates": totals[p],
            "update_share_pct": round(100.0 * totals[p] / total_updates, 2)
            if total_updates
            else 0.0,
            "minutes_active": minutes_active[p],
            "pct_open_minutes_active": round(100.0 * minutes_active[p] / n_open, 2),
            "rank": rank,
        }
        for rank, p in enumerate(ordered, 1)
    ]
    return summary, details


def process_feed(client, feed_sessions, start_utc, end_utc):
    """All sessions of one feed from a single ClickHouse query."""
    per_minute = fetch_per_minute_counts(
        client, feed_sessions[0].feed_id, start_utc, end_utc
    )
    summaries, details = [], []
    for fs in feed_sessions:
        if fs.schedule_str is None:
            summaries.append({**_base(fs), "note": "NO_SCHEDULE"})
            continue
        try:
            schedule = parse_market_schedule(fs.schedule_str)
        except ValueError:
            summaries.append({**_base(fs), "note": "NO_SCHEDULE"})
            continue
        mask = open_minutes_mask(schedule, start_utc, end_utc)
        s, d = session_rows(fs, per_minute, mask)
        summaries.append(s)
        details.extend(d)
    return summaries, details
