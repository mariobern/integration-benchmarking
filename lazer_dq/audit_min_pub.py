"""Stage 1 of the min_pub pipeline: audit active publishers vs minPublishers.

For every STABLE (feed, session) in a new-format Lazer config, counts
distinct ACCEPTED allowed publishers per minute over a UTC date window,
restricted to the session's open hours, and classifies:

  CRITICAL  any open minute with active <= min_pub
  WARN      never <= min_pub, but some minute at min_pub + 1
  OK        otherwise

Run:
    python3 -m lazer_dq.audit_min_pub --config lazer_to_modify.json \
        --start-date 2026-07-06 --end-date 2026-07-13 --workers 8
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
from lazer_dq.min_pub_common import (
    FeedSession,
    deprecated_stable_feeds,
    hygiene_rows,
    iter_stable_sessions,
)

AUDIT_COLUMNS = [
    "feed_id",
    "symbol",
    "asset_type",
    "session",
    "classification",
    "effective_min_pub",
    "allowed_count",
    "static_margin",
    "open_minutes",
    "minutes_below_min",
    "minutes_at_min",
    "minutes_at_min_plus_1",
    "longest_run_le_min",
    "longest_run_le_min_plus_1",
    "median_active",
    "worst_minute_active",
    "prolonged",
]

PER_MINUTE_QUERY = """
    SELECT
        toStartOfMinute(publish_time) AS minute,
        groupUniqArrayIf(publisher_id, status = 'ACCEPTED') AS active_pubs
    FROM publisher_updates
    PREWHERE price_feed_id = {feed_id:UInt64}
    WHERE publish_time >= {start:String}
      AND publish_time < {end:String}
    GROUP BY minute
    ORDER BY minute
"""


def fetch_per_minute_publishers(client, feed_id, start_utc, end_utc):
    """dict of UTC-minute Timestamp -> set of ACCEPTED publisher_ids."""
    result = client.query(
        PER_MINUTE_QUERY,
        parameters={
            "feed_id": feed_id,
            "start": start_utc.strftime("%Y-%m-%d %H:%M:%S"),
            "end": end_utc.strftime("%Y-%m-%d %H:%M:%S"),
        },
    )
    return {
        pd.Timestamp(minute, tz="UTC"): set(pubs) for minute, pubs in result.result_rows
    }


def active_counts_for_session(per_minute_pubs, mask, allowed):
    """Active-count array over the mask's open minutes; missing minutes = 0."""
    open_minutes = mask.index[mask.to_numpy()]
    return np.array(
        [len(per_minute_pubs.get(m, set()) & allowed) for m in open_minutes],
        dtype=int,
    )


def longest_true_run(values) -> int:
    best = current = 0
    for v in values:
        current = current + 1 if v else 0
        best = max(best, current)
    return best


def audit_metrics(active_counts, min_pub, prolonged_threshold):
    le_min = active_counts <= min_pub
    le_min_plus_1 = active_counts <= min_pub + 1
    return {
        "open_minutes": int(len(active_counts)),
        "minutes_below_min": int((active_counts < min_pub).sum()),
        "minutes_at_min": int((active_counts == min_pub).sum()),
        "minutes_at_min_plus_1": int((active_counts == min_pub + 1).sum()),
        "longest_run_le_min": longest_true_run(le_min),
        "longest_run_le_min_plus_1": longest_true_run(le_min_plus_1),
        "median_active": float(np.median(active_counts)) if len(active_counts) else 0.0,
        "worst_minute_active": int(active_counts.min()) if len(active_counts) else 0,
        "prolonged": bool(longest_true_run(le_min_plus_1) >= prolonged_threshold),
    }


def classify(metrics) -> str:
    if metrics["minutes_below_min"] + metrics["minutes_at_min"] > 0:
        return "CRITICAL"
    if metrics["minutes_at_min_plus_1"] > 0:
        return "WARN"
    return "OK"


def audit_feed(client, feed_sessions, start_utc, end_utc, prolonged_threshold):
    """Audit all sessions of one feed with a single ClickHouse query."""
    per_minute = fetch_per_minute_publishers(
        client, feed_sessions[0].feed_id, start_utc, end_utc
    )
    rows = []
    for fs in feed_sessions:
        base = {
            "feed_id": fs.feed_id,
            "symbol": fs.symbol,
            "asset_type": fs.asset_type,
            "session": fs.session,
            "effective_min_pub": fs.effective_min_pub,
            "allowed_count": len(fs.allowed),
            "static_margin": len(fs.allowed) - fs.effective_min_pub,
        }
        if fs.schedule_str is None:
            rows.append({**base, "classification": "NO_SCHEDULE"})
            continue
        mask = open_minutes_mask(
            parse_market_schedule(fs.schedule_str), start_utc, end_utc
        )
        counts = active_counts_for_session(per_minute, mask, fs.allowed)
        metrics = audit_metrics(counts, fs.effective_min_pub, prolonged_threshold)
        rows.append({**base, **metrics, "classification": classify(metrics)})
    return rows


def default_window():
    """Last 7 full UTC days: [today-7 00:00, today 00:00)."""
    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    return end - timedelta(days=7), end


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True)
    p.add_argument("--start-date", help="UTC start date YYYY-MM-DD (inclusive)")
    p.add_argument("--end-date", help="UTC end date YYYY-MM-DD (exclusive)")
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--feed-id", type=int, nargs="*", help="restrict to these feeds")
    p.add_argument("--resume", action="store_true")
    p.add_argument("--prolonged-threshold", type=int, default=30)
    p.add_argument("--output-dir", default="output_csv")
    return p.parse_args(argv)


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

    # Static hygiene report (all states) — no ClickHouse needed.
    hygiene = hygiene_rows(config)
    hygiene_path = out_dir / "hygiene_report.csv"
    with open(hygiene_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "feed_id",
                "symbol",
                "state",
                "feed_min_publishers",
                "allowed_union_count",
                "issue",
            ],
        )
        writer.writeheader()
        writer.writerows(hygiene)
    print(f"Hygiene report: {len(hygiene)} rows -> {hygiene_path}")

    # Group audit units by feed (one query per feed covers all its sessions).
    by_feed = {}
    for fs in iter_stable_sessions(config):
        if args.feed_id and fs.feed_id not in args.feed_id:
            continue
        by_feed.setdefault(fs.feed_id, []).append(fs)

    audit_path = out_dir / (
        f"min_pub_audit_{start_utc:%Y-%m-%d}_{end_utc:%Y-%m-%d}.csv"
    )
    done_feed_ids = set()
    if args.resume and audit_path.exists():
        done_feed_ids = set(
            pd.read_csv(audit_path, usecols=["feed_id"])["feed_id"].astype(int)
        )
        print(f"Resume: skipping {len(done_feed_ids)} already-audited feeds")
    todo = {fid: fss for fid, fss in by_feed.items() if fid not in done_feed_ids}
    print(f"Auditing {len(todo)} feeds ({start_utc:%Y-%m-%d} .. {end_utc:%Y-%m-%d})")

    from lib.config import ThreadLocalClients, load_config

    write_lock = threading.Lock()
    new_file = not (args.resume and audit_path.exists())
    csv_file = open(audit_path, "w" if new_file else "a", newline="")
    writer = csv.DictWriter(csv_file, fieldnames=AUDIT_COLUMNS, extrasaction="ignore")
    if new_file:
        writer.writeheader()
        # Deprecated STABLE feeds: reported once, no metrics.
        for row in deprecated_stable_feeds(config):
            writer.writerow(
                {
                    "feed_id": row["feed_id"],
                    "symbol": row["symbol"],
                    "classification": "SKIPPED_DEPRECATED",
                }
            )
        csv_file.flush()

    failures = 0
    with ThreadLocalClients(load_config(), lazer_only=True) as pool:

        def run_one(feed_sessions):
            client = pool.get_lazer_client()
            return audit_feed(
                client, feed_sessions, start_utc, end_utc, args.prolonged_threshold
            )

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(run_one, fss): fid for fid, fss in todo.items()}
            for i, future in enumerate(as_completed(futures), 1):
                fid = futures[future]
                try:
                    rows = future.result()
                except Exception as e:  # soft-fail, continue (bulk-runner pattern)
                    failures += 1
                    print(f"  [{i}/{len(todo)}] feed {fid} FAILED: {e}")
                    continue
                with write_lock:
                    writer.writerows(rows)
                    csv_file.flush()
                worst = min(
                    (r["classification"] for r in rows),
                    key=lambda c: ["CRITICAL", "WARN", "NO_SCHEDULE", "OK"].index(c)
                    if c in ("CRITICAL", "WARN", "NO_SCHEDULE", "OK")
                    else 99,
                )
                print(f"  [{i}/{len(todo)}] feed {fid}: {worst}")
    csv_file.close()
    print(f"Audit written to {audit_path} ({failures} feed failures)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
