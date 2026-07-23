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
    "pct_below_par",
    "pct_at_par",
    "pct_at_floor",
    "pct_at_floor_1",
    "verdict",
]

HISTOGRAM_COLUMNS = [
    "feed_id",
    "symbol",
    "asset_type",
    "session",
    "effective_min_pub",
    "publisher_count",
    "n_updates",
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
        return _zeroed_stats()
    return {
        "n_updates": n,
        "min": int(counts.min()),
        "p1": float(np.percentile(counts, 1)),
        "p5": float(np.percentile(counts, 5)),
        "median": float(np.median(counts)),
        # below par = strictly under the floor (a breach); at par = exactly the
        # floor (compliant but zero redundancy). Their sum is pct_at_floor.
        "pct_below_par": float((counts < min_pub).mean() * 100.0),
        "pct_at_par": float((counts == min_pub).mean() * 100.0),
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
    open_minutes = mask.index[mask.to_numpy()]
    times = pd.DatetimeIndex([r[0] for r in rows], tz="UTC").floor("min")
    counts = np.array([r[1] for r in rows], dtype=int)
    return counts[times.isin(open_minutes)]


def classify(
    stats: dict,
    breach_pct: float,
    critical_pct: float,
    warn_pct: float,
    min_updates: int,
) -> str:
    """Verdict precedence: NO_DATA > LOW_SAMPLE > BREACH > CRITICAL > WARN > OK.

    BREACH   = below par (publisher_count < minPublishers) >= breach_pct.
    CRITICAL = at or below the floor (<= minPublishers) >= critical_pct, but not
               a breach — in practice predominantly at par.
    """
    if stats["n_updates"] == 0:
        return "NO_DATA"
    if stats["n_updates"] < min_updates:
        return "LOW_SAMPLE"
    if stats["pct_below_par"] >= breach_pct:
        return "BREACH"
    if stats["pct_at_floor"] >= critical_pct:
        return "CRITICAL"
    if stats["pct_at_floor"] == 0.0 and stats["pct_at_floor_1"] >= warn_pct:
        return "WARN"
    return "OK"


# Non-consumer-facing feed families. Their symbols carry real asset_types
# (e.g. Pyth.BN.AAPL is tagged "equity"), so they dilute the true asset-class
# distributions unless separated. FundingRate.* is a real product, NOT internal.
_INTERNAL_PREFIXES = ("Pyth.", "Custom.", "Internal.", "FeedComponent.")


def is_internal(symbol) -> bool:
    """True for internal / non-consumer-facing feed families (see prefixes)."""
    return symbol.startswith(_INTERNAL_PREFIXES)


def derive_asset_type(symbol, asset_type) -> str:
    """Refine the raw config asset_type for cleaner class distributions.

    - Internal feeds (``Pyth.*``, ``Custom.*``, ``Internal.*``,
      ``FeedComponent.*``) collapse to ``internal`` — they carry real
      asset_types in the config but are not consumer-facing, so they would
      otherwise pollute equity/fx/commodity/etc.
    - Index feeds (symbol's second dotted segment is ``Index``:
      ``Equity.Index.NVDA/USD``, ``Commodities.Index.COPPER/USD``, ...) get
      ``<asset_type>-index`` so they don't dilute the underlying class. The
      config is inconsistent here (``Crypto.Index.*`` is already
      ``crypto-index`` but ``Equity.Index.*`` is plain ``equity``); the guard
      makes every ``.Index.`` feed uniform without double-suffixing.
    """
    if is_internal(symbol):
        return "internal"
    parts = symbol.split(".")
    if len(parts) >= 2 and parts[1] == "Index" and not asset_type.endswith("-index"):
        return f"{asset_type}-index"
    return asset_type


def _base_row(fs) -> dict:
    return {
        "feed_id": fs.feed_id,
        "symbol": fs.symbol,
        "asset_type": derive_asset_type(fs.symbol, fs.asset_type),
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
        "pct_below_par": 0.0,
        "pct_at_par": 0.0,
        "pct_at_floor": 0.0,
        "pct_at_floor_1": 0.0,
    }


def histogram_rows(fs, counts) -> list:
    """One row per distinct publisher_count value for this feed-session.

    The literal histogram: number of in-session aggregate updates at each
    observed contributor count. Empty counts -> no rows.
    """
    if len(counts) == 0:
        return []
    values, freqs = np.unique(counts, return_counts=True)
    asset_type = derive_asset_type(fs.symbol, fs.asset_type)
    return [
        {
            "feed_id": fs.feed_id,
            "symbol": fs.symbol,
            "asset_type": asset_type,
            "session": fs.session,
            "effective_min_pub": fs.effective_min_pub,
            "publisher_count": int(v),
            "n_updates": int(n),
        }
        for v, n in zip(values, freqs)
    ]


def analyze_feed(
    client, feed_sessions, start_utc, end_utc,
    breach_pct, critical_pct, warn_pct, min_updates,
) -> tuple:
    """One price_feeds query for the feed.

    Returns (summary_rows, histogram_rows): one summary row per session, plus
    the long-format histogram rows (one per distinct publisher_count) for every
    session that had in-session updates.
    """
    rows = fetch_feed_rows(client, feed_sessions[0].feed_id, start_utc, end_utc)
    summary_out = []
    hist_out = []
    for fs in feed_sessions:
        base = _base_row(fs)
        if fs.effective_min_pub is None:
            summary_out.append({**base, **_zeroed_stats(), "verdict": "NO_MIN_PUB"})
            continue
        if not fs.schedule_str:
            summary_out.append({**base, **_zeroed_stats(), "verdict": "NO_SCHEDULE"})
            continue
        try:
            counts = masked_counts(rows, fs.schedule_str, start_utc, end_utc)
        except ValueError:
            summary_out.append({**base, **_zeroed_stats(), "verdict": "NO_SCHEDULE"})
            continue
        stats = distribution_stats(counts, fs.effective_min_pub)
        verdict = classify(stats, breach_pct, critical_pct, warn_pct, min_updates)
        summary_out.append({**base, **stats, "verdict": verdict})
        hist_out.extend(histogram_rows(fs, counts))
    return summary_out, hist_out


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
    p.add_argument("--breach-pct", type=float, default=1.0)
    p.add_argument("--critical-pct", type=float, default=1.0)
    p.add_argument("--warn-pct", type=float, default=5.0)
    p.add_argument("--min-updates", type=int, default=100)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--feed-id", type=int, nargs="*", help="restrict to these feeds")
    p.add_argument(
        "--exclude-internal",
        action="store_true",
        help="drop internal (Pyth.*, Custom.*, Internal.*, FeedComponent.*) feeds",
    )
    p.add_argument("--output-dir", default="output_csv")
    return p.parse_args(argv)


_VERDICT_ORDER = [
    "NO_DATA",
    "LOW_SAMPLE",
    "BREACH",
    "CRITICAL",
    "WARN",
    "OK",
    "NO_SCHEDULE",
    "NO_MIN_PUB",
]

_CSV_SORT_ORDER = [
    "BREACH",
    "CRITICAL",
    "WARN",
    "OK",
    "LOW_SAMPLE",
    "NO_DATA",
    "NO_SCHEDULE",
    "NO_MIN_PUB",
]


def sort_rows(rows):
    """CSV order: action priority (CRITICAL first), then pct_at_floor desc."""

    def key(r):
        try:
            pri = _CSV_SORT_ORDER.index(r["verdict"])
        except ValueError:
            pri = len(_CSV_SORT_ORDER)
        return (pri, -r["pct_at_floor"])

    return sorted(rows, key=key)


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
    excluded_internal = 0
    for fs in iter_stable_sessions(config):
        if args.feed_id and fs.feed_id not in args.feed_id:
            continue
        if args.exclude_internal and is_internal(fs.symbol):
            excluded_internal += 1
            continue
        by_feed.setdefault(fs.feed_id, []).append(fs)
    if args.exclude_internal:
        print(f"Excluded {excluded_internal} internal feed-sessions")

    stamp = f"{start_utc:%Y-%m-%d}_{end_utc:%Y-%m-%d}"
    out_path = out_dir / f"active_min_pub_{stamp}.csv"
    hist_path = out_dir / f"active_min_pub_histogram_{stamp}.csv"
    print(
        f"Analyzing {len(by_feed)} feeds ({start_utc:%Y-%m-%d} .. {end_utc:%Y-%m-%d})"
    )

    from lib.config import ThreadLocalClients, load_config

    write_lock = threading.Lock()
    all_rows: list = []
    all_hist: list = []

    failures = 0
    with ThreadLocalClients(load_config(), lazer_only=True) as pool:

        def run_one(feed_sessions):
            client = pool.get_lazer_client()
            return analyze_feed(
                client,
                feed_sessions,
                start_utc,
                end_utc,
                args.breach_pct,
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
                    summary_rows, hist_rows = future.result()
                except Exception as e:  # soft-fail, continue
                    failures += 1
                    print(f"  [{i}/{len(by_feed)}] feed {fid} FAILED: {e}")
                    continue
                with write_lock:
                    all_rows.extend(summary_rows)
                    all_hist.extend(hist_rows)

    with open(out_path, "w", newline="") as csv_file:
        writer = csv.DictWriter(
            csv_file, fieldnames=RESULT_COLUMNS, extrasaction="ignore"
        )
        writer.writeheader()
        writer.writerows(sort_rows(all_rows))

    all_hist.sort(key=lambda r: (r["feed_id"], r["session"], r["publisher_count"]))
    with open(hist_path, "w", newline="") as hist_file:
        hist_writer = csv.DictWriter(
            hist_file, fieldnames=HISTOGRAM_COLUMNS, extrasaction="ignore"
        )
        hist_writer.writeheader()
        hist_writer.writerows(all_hist)

    tally = summarize(all_rows)
    print(f"\nAnalysis written to {out_path} ({failures} feed failures)")
    print(f"Histogram written to {hist_path} ({len(all_hist)} rows)")
    for v in _VERDICT_ORDER:
        if v in tally:
            print(f"  {v:12} {tally[v]}")

    breach = sorted(
        (r for r in all_rows if r["verdict"] == "BREACH"),
        key=lambda r: r["pct_below_par"],
        reverse=True,
    )
    if breach:
        print(f"\nBREACH feed-sessions ({len(breach)}) — below minPublishers:")
        for r in breach:
            print(
                f"  feed {r['feed_id']:>5} {r['symbol']:24} {r['session']:11} "
                f"min_pub={r['effective_min_pub']} pct_below_par={r['pct_below_par']:.2f}%"
            )

    critical = sorted(
        (r for r in all_rows if r["verdict"] == "CRITICAL"),
        key=lambda r: r["pct_at_par"],
        reverse=True,
    )
    if critical:
        print(f"\nCRITICAL feed-sessions ({len(critical)}) — at minPublishers:")
        for r in critical:
            print(
                f"  feed {r['feed_id']:>5} {r['symbol']:24} {r['session']:11} "
                f"min_pub={r['effective_min_pub']} pct_at_par={r['pct_at_par']:.2f}%"
            )

    for verdict_name in ("LOW_SAMPLE", "NO_DATA"):
        items = [r for r in all_rows if r["verdict"] == verdict_name]
        if items:
            print(f"\n{verdict_name} feed-sessions ({len(items)}):")
            for r in items:
                print(f"  feed {r['feed_id']:>5} {r['symbol']:24} {r['session']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
