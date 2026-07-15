# lazer_dq/incumbent_quality.py
"""Quality sweep of incumbent (and optionally candidate) publishers.

For every session of every STABLE feed in a new-format Lazer config, score
each currently-allowed publisher's price quality with the same gates the
min_pub qualification pipeline applies to candidates:

  - Datascope path (engine_mode_for): DQ-engine per-publisher stats gated by
    engine_gate;
  - peer path (everything else): evaluate_peer vs the price_feeds aggregate
    (circularity accepted by design, as in qualify_candidates).

With --include-candidates, non-allowed production-key publishers submitting
in the window are scored too (publisher_role=candidate). Measure-only: no
activity gate, no selection, no config mutation.

Run:
    python3 -m lazer_dq.incumbent_quality --config lazer_new.json \
        --start-date 2026-07-08 --end-date 2026-07-15 \
        --include-candidates \
        --audit-csv output_csv/min_pub_audit_2026-07-06_2026-07-13.csv
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from lazer_dq.market_schedule import open_minutes_mask, parse_market_schedule
from lazer_dq.min_pub_common import iter_stable_sessions, restrict_to_mask
from lazer_dq.peer_benchmark import PeerThresholds, evaluate_peer
from lazer_dq.qualify_candidates import (
    ACTIVITY_QUERY,
    PER_SECOND_PRICES_QUERY,
    activity_pct,
    candidate_dates,
    engine_gate,
    engine_mode_for,
    fetch_aggregate,
    fetch_production_publisher_ids,
    peer_windows,
    run_engine,
)
from lazer_dq.summarize_feeds import load_excluded_publishers, load_stats

REPORT_COLUMNS = [
    "feed_id",
    "symbol",
    "session",
    "publisher_id",
    "publisher_role",
    "quality_path",
    "engine_mode",
    "benchmark_date",
    "activity_pct",
    "rmse_over_spread",
    "hit_rate",
    "nrmse",
    "n_obs",
    "verdict",
    "reason",
]
SUMMARY_COLUMNS = [
    "feed_id",
    "symbol",
    "session",
    "asset_type",
    "quality_path",
    "n_incumbents",
    "n_pass",
    "n_fail",
    "n_no_data",
    "n_no_benchmark",
    "all_pass",
    "n_candidates",
    "n_candidates_pass",
    "audit_classification",
]
FLAGGED_COLUMNS = [
    "feed_id",
    "symbol",
    "session",
    "publisher_id",
    "publisher_role",
    "verdict",
    "reason",
    "detail",
]


def ensure_new_format(config: dict) -> None:
    """Reject old-format configs (feed-level allowedPublisherIds)."""
    for feed in config.get("feeds", []):
        if "allowedPublisherIds" in feed:
            raise ValueError(
                f"old-format config: feed {feed.get('feedId')} has feed-level "
                "allowedPublisherIds; only session-only configs are supported"
            )


def discover_candidates(matrix_pubs, production_pubs, allowed, excluded):
    """Non-allowed production-key publishers submitting in the window."""
    return sorted(
        (set(matrix_pubs) & set(production_pubs)) - set(allowed) - set(excluded)
    )


def verdict_from_peer(result: dict) -> tuple:
    """Map an evaluate_peer result to (verdict, reason)."""
    if result["reason"] == "zero_range":
        return "NO_BENCHMARK", "zero_range"
    if result["reason"] == "insufficient_obs":
        if result["n_observations"] == 0:
            return "NO_DATA", "no_submissions"
        return "NO_DATA", "insufficient_obs"
    if result["passed"]:
        return "PASS", "pass"
    return "FAIL", "fail_quality"


def verdict_from_engine(srow, mode: str, min_obs: int) -> tuple:
    """Map a DQ-engine stats row (or its absence) to (verdict, reason)."""
    if srow is None:
        return "NO_DATA", "no_engine_row"
    try:
        n_obs = int(float(srow["n_observations"]))
    except (KeyError, ValueError):
        return "NO_DATA", "bad_stats_row"
    if n_obs < min_obs:
        return "NO_DATA", "insufficient_obs"
    if engine_gate(srow, mode, min_obs):
        return "PASS", "pass"
    return "FAIL", "fail_quality"


def summarize_session(rows) -> dict:
    """Per-role verdict counts for one feed-session's report rows."""
    inc = [r for r in rows if r["publisher_role"] == "incumbent"]
    cand = [r for r in rows if r["publisher_role"] == "candidate"]

    def count(rs, verdict):
        return sum(1 for r in rs if r["verdict"] == verdict)

    n_pass = count(inc, "PASS")
    return {
        "n_incumbents": len(inc),
        "n_pass": n_pass,
        "n_fail": count(inc, "FAIL"),
        "n_no_data": count(inc, "NO_DATA"),
        "n_no_benchmark": count(inc, "NO_BENCHMARK"),
        "all_pass": len(inc) > 0 and n_pass == len(inc),
        "n_candidates": len(cand),
        "n_candidates_pass": count(cand, "PASS"),
    }


def load_audit_classifications(path) -> dict:
    """(feed_id, session) -> classification from a Stage-1 min_pub audit CSV."""
    df = pd.read_csv(path)
    out = {}
    for r in df.itertuples():
        if r.session != r.session:  # NaN (e.g. SKIPPED_DEPRECATED rows)
            continue
        out[(int(r.feed_id), str(r.session))] = str(r.classification)
    return out


def resume_done_feed_ids(summary_path: Path) -> set:
    if not Path(summary_path).exists():
        return set()
    return set(pd.read_csv(summary_path, usecols=["feed_id"])["feed_id"].astype(int))


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True)
    p.add_argument("--start-date", required=True, help="UTC YYYY-MM-DD (inclusive)")
    p.add_argument("--end-date", required=True, help="UTC YYYY-MM-DD (exclusive)")
    p.add_argument("--include-candidates", action="store_true")
    p.add_argument("--audit-csv", help="Stage-1 audit CSV to join classification")
    p.add_argument("--cluster", default="lazer-prod")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--feed-id", type=int, nargs="*", help="restrict to these feeds")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--exclude-publisher", type=int, action="append", default=[])
    p.add_argument("--peer-nrmse-auto", type=float, default=0.05)
    p.add_argument("--peer-nrmse-cond", type=float, default=0.15)
    p.add_argument("--peer-hit-rate", type=float, default=85.0)
    p.add_argument("--min-obs", type=int, default=1000)
    p.add_argument("--peer-days", type=int, default=2)
    p.add_argument("--reports-dir", default="dq_reports")
    p.add_argument("--output-dir", default="output_csv")
    p.add_argument("--publishers-md", default="publishers.md")
    return p.parse_args(argv)
