"""Aggregate publisher-count headroom sweep (min-pub distance, aggregate level).

For every STABLE (feed, session) in a new-format Lazer config, reads the
aggregate's own publisher_count per update from price_feeds (highest-frequency
channel = lowest-numbered channel with data), session-masks to open hours, and
reports the contributor-count distribution vs the session's minPublishers.

DISTINCT FROM audit_min_pub: that script counts per-MINUTE distinct ACCEPTED
publishers from publisher_updates (availability). This script uses the
per-AGGREGATE publisher_count from price_feeds (contributor headroom). Different
question; do not conflate.

Run:
    python3 -m lazer_dq.active_min_pub --config lazer_newest.json \
        --start-date 2026-07-14 --end-date 2026-07-22 --workers 8
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

from lazer_dq.market_schedule import open_minutes_mask, parse_market_schedule
from lazer_dq.min_pub_common import iter_stable_sessions

RESULT_COLUMNS = [
    "feed_id",
    "symbol",
    "asset_type",
    "session",
    "effective_min_pub",
    "n_updates",
    "min",
    "p1",
    "p5",
    "median",
    "pct_at_floor",
    "pct_at_floor_1",
    "verdict",
]


def distribution_stats(counts: np.ndarray, min_pub: int) -> dict:
    """Distribution of aggregate publisher_count vs the min-pub floor.

    counts: per-update contributor counts already masked to the session.
    Empty input -> n_updates=0 with zeroed stats.
    """
    n = int(len(counts))
    if n == 0:
        return {
            "n_updates": 0,
            "min": 0,
            "p1": 0.0,
            "p5": 0.0,
            "median": 0.0,
            "pct_at_floor": 0.0,
            "pct_at_floor_1": 0.0,
        }
    return {
        "n_updates": n,
        "min": int(counts.min()),
        "p1": float(np.percentile(counts, 1)),
        "p5": float(np.percentile(counts, 5)),
        "median": float(np.median(counts)),
        "pct_at_floor": float((counts <= min_pub).mean() * 100.0),
        "pct_at_floor_1": float((counts <= min_pub + 1).mean() * 100.0),
    }


def classify(
    stats: dict, critical_pct: float, warn_pct: float, min_updates: int
) -> str:
    """Verdict precedence: NO_DATA > LOW_SAMPLE > CRITICAL > WARN > OK."""
    if stats["n_updates"] == 0:
        return "NO_DATA"
    if stats["n_updates"] < min_updates:
        return "LOW_SAMPLE"
    if stats["pct_at_floor"] >= critical_pct:
        return "CRITICAL"
    if stats["pct_at_floor"] == 0.0 and stats["pct_at_floor_1"] >= warn_pct:
        return "WARN"
    return "OK"
