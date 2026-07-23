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


PRICE_FEEDS_QUERY = """
    SELECT publish_time, publisher_count
    FROM price_feeds
    WHERE price_feed_id = {feed_id:UInt64}
      AND channel = {channel:UInt8}
      AND publish_time >= {start:String}
      AND publish_time < {end:String}
    ORDER BY publish_time
"""


def fetch_feed_rows(client, feed_id, start_utc, end_utc, channels=(1, 2, 3)) -> list:
    """(publish_time, publisher_count) rows from the lowest channel with data."""
    for channel in channels:
        result = client.query(
            PRICE_FEEDS_QUERY,
            parameters={
                "feed_id": feed_id,
                "channel": channel,
                "start": start_utc.strftime("%Y-%m-%d %H:%M:%S"),
                "end": end_utc.strftime("%Y-%m-%d %H:%M:%S"),
            },
        )
        if result.result_rows:
            return list(result.result_rows)
    return []


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


def masked_counts(rows, schedule_str, start_utc, end_utc) -> np.ndarray:
    """Per-update publisher_count values whose minute is open per the schedule.

    rows: (publish_time_naive_utc, publisher_count) tuples from ClickHouse.
    Raises ValueError on a malformed schedule string (caller handles).
    """
    if not rows:
        return np.array([], dtype=int)
    schedule = parse_market_schedule(schedule_str)
    mask = open_minutes_mask(schedule, start_utc, end_utc)
    open_minutes = set(mask.index[mask.to_numpy()])
    out = []
    for ts, count in rows:
        minute = pd.Timestamp(ts, tz="UTC").floor("min")
        if minute in open_minutes:
            out.append(count)
    return np.array(out, dtype=int)


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


def _base_row(fs) -> dict:
    return {
        "feed_id": fs.feed_id,
        "symbol": fs.symbol,
        "asset_type": fs.asset_type,
        "session": fs.session,
        "effective_min_pub": fs.effective_min_pub,
    }


def _zeroed_stats() -> dict:
    return {
        "n_updates": 0,
        "min": 0,
        "p1": 0.0,
        "p5": 0.0,
        "median": 0.0,
        "pct_at_floor": 0.0,
        "pct_at_floor_1": 0.0,
    }


def analyze_feed(
    client, feed_sessions, start_utc, end_utc, critical_pct, warn_pct, min_updates
) -> list:
    """One price_feeds query for the feed; one result row per session."""
    rows = fetch_feed_rows(client, feed_sessions[0].feed_id, start_utc, end_utc)
    out = []
    for fs in feed_sessions:
        base = _base_row(fs)
        if not fs.schedule_str:
            out.append({**base, **_zeroed_stats(), "verdict": "NO_SCHEDULE"})
            continue
        try:
            counts = masked_counts(rows, fs.schedule_str, start_utc, end_utc)
        except ValueError:
            out.append({**base, **_zeroed_stats(), "verdict": "NO_SCHEDULE"})
            continue
        stats = distribution_stats(counts, fs.effective_min_pub)
        verdict = classify(stats, critical_pct, warn_pct, min_updates)
        out.append({**base, **stats, "verdict": verdict})
    return out


def default_window():
    """Last 7 full UTC days: [today-7 00:00, today 00:00)."""
    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return end - timedelta(days=7), end


def summarize(rows) -> dict:
    tally: dict = {}
    for r in rows:
        tally[r["verdict"]] = tally.get(r["verdict"], 0) + 1
    return tally


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True)
    p.add_argument("--start-date", help="UTC start date YYYY-MM-DD (inclusive)")
    p.add_argument("--end-date", help="UTC end date YYYY-MM-DD (exclusive)")
    p.add_argument("--critical-pct", type=float, default=1.0)
    p.add_argument("--warn-pct", type=float, default=5.0)
    p.add_argument("--min-updates", type=int, default=100)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--feed-id", type=int, nargs="*", help="restrict to these feeds")
    p.add_argument("--output-dir", default="output_csv")
    return p.parse_args(argv)


_VERDICT_ORDER = ["NO_DATA", "LOW_SAMPLE", "CRITICAL", "WARN", "OK", "NO_SCHEDULE"]


def main(argv=None) -> int:
    args = parse_args(argv)
    if bool(args.start_date) != bool(args.end_date):
        print("ERROR: pass both --start-date and --end-date, or neither")
        return 1
    if args.start_date:
        start_utc = datetime.strptime(args.start_date, "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
        end_utc = datetime.strptime(args.end_date, "%Y-%m-%d").replace(
            tzinfo=timezone.utc
        )
    else:
        start_utc, end_utc = default_window()

    config = json.loads(Path(args.config).read_text())
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    by_feed: dict = {}
    for fs in iter_stable_sessions(config):
        if args.feed_id and fs.feed_id not in args.feed_id:
            continue
        by_feed.setdefault(fs.feed_id, []).append(fs)

    out_path = out_dir / (f"active_min_pub_{start_utc:%Y-%m-%d}_{end_utc:%Y-%m-%d}.csv")
    print(
        f"Analyzing {len(by_feed)} feeds ({start_utc:%Y-%m-%d} .. {end_utc:%Y-%m-%d})"
    )

    from lib.config import ThreadLocalClients, load_config

    write_lock = threading.Lock()
    all_rows: list = []
    csv_file = open(out_path, "w", newline="")
    writer = csv.DictWriter(csv_file, fieldnames=RESULT_COLUMNS, extrasaction="ignore")
    writer.writeheader()

    failures = 0
    with ThreadLocalClients(load_config(), lazer_only=True) as pool:

        def run_one(feed_sessions):
            client = pool.get_lazer_client()
            return analyze_feed(
                client,
                feed_sessions,
                start_utc,
                end_utc,
                args.critical_pct,
                args.warn_pct,
                args.min_updates,
            )

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {
                executor.submit(run_one, fss): fid for fid, fss in by_feed.items()
            }
            for i, future in enumerate(as_completed(futures), 1):
                fid = futures[future]
                try:
                    rows = future.result()
                except Exception as e:  # soft-fail, continue
                    failures += 1
                    print(f"  [{i}/{len(by_feed)}] feed {fid} FAILED: {e}")
                    continue
                with write_lock:
                    writer.writerows(rows)
                    csv_file.flush()
                    all_rows.extend(rows)
    csv_file.close()

    tally = summarize(all_rows)
    print(f"\nAnalysis written to {out_path} ({failures} feed failures)")
    for v in _VERDICT_ORDER:
        if v in tally:
            print(f"  {v:12} {tally[v]}")

    critical = sorted(
        (r for r in all_rows if r["verdict"] == "CRITICAL"),
        key=lambda r: r["pct_at_floor"],
        reverse=True,
    )
    if critical:
        print(f"\nCRITICAL feed-sessions ({len(critical)}):")
        for r in critical:
            print(
                f"  feed {r['feed_id']:>5} {r['symbol']:24} {r['session']:11} "
                f"min_pub={r['effective_min_pub']} pct_at_floor={r['pct_at_floor']:.2f}%"
            )
    return 0


if __name__ == "__main__":
    sys.exit(main())
