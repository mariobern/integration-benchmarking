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
    try:
        df = pd.read_csv(summary_path, usecols=["feed_id"])
    except pd.errors.EmptyDataError:
        return set()
    return set(df["feed_id"].astype(int))


def prune_orphan_rows(path: Path, done_feed_ids: set) -> int:
    """Drop rows from an existing CSV whose feed_id is not in done_feed_ids.

    Rows with a blank/non-numeric feed_id are kept defensively. Rewrites the
    file in place. Missing or empty file is a no-op returning 0.
    """
    path = Path(path)
    if not path.exists():
        return 0
    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError:
        return 0
    if df.empty or "feed_id" not in df.columns:
        return 0

    def _keep(value) -> bool:
        try:
            return int(value) in done_feed_ids
        except (TypeError, ValueError):
            return True  # blank/non-numeric feed_id: keep defensively

    keep_mask = df["feed_id"].map(_keep)
    dropped = int((~keep_mask).sum())
    if dropped:
        df.loc[keep_mask].to_csv(path, index=False)
    return dropped


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


def _score_engine(rows, fs, mode, args):
    """Datascope path: one engine run per feed/date serves every publisher."""
    stats, used_date = None, None
    for date in candidate_dates(args.start_utc, args.end_utc):
        if run_engine(fs.feed_id, date, mode, args.cluster, args.reports_dir) == "ok":
            stats = load_stats(args.reports_dir, args.cluster, mode, fs.feed_id, date)
            if stats:
                used_date = date
                break
    if not stats:
        for row in rows:
            row.update({"verdict": "NO_BENCHMARK", "reason": "no_engine_data"})
        return
    stats_by_pid = {}
    for r in stats:
        try:
            stats_by_pid[int(float(r["publisher_id"]))] = r
        except (KeyError, ValueError):
            continue
    for row in rows:
        srow = stats_by_pid.get(row["publisher_id"])
        verdict, reason = verdict_from_engine(srow, mode, args.min_obs)
        row["benchmark_date"] = used_date
        if srow is not None:
            row.update(
                {
                    "rmse_over_spread": srow.get("rmse_over_spread", ""),
                    "hit_rate": srow.get("hit_rate_0.1pct", ""),
                    "nrmse": srow.get("nrmse", ""),
                    "n_obs": srow.get("n_observations", ""),
                }
            )
        row.update({"verdict": verdict, "reason": reason})


def _score_peer(client, rows, fs, mask, thresholds, args):
    """Peer path: each publisher vs the price_feeds aggregate."""
    window = peer_windows(mask, args.peer_days)
    if window is None:
        for row in rows:
            row.update({"verdict": "NO_BENCHMARK", "reason": "no_open_minutes"})
        return
    pstart, pend = window
    agg_df = restrict_to_mask(fetch_aggregate(client, fs.feed_id, pstart, pend), mask)
    if agg_df.empty:
        for row in rows:
            row.update({"verdict": "NO_BENCHMARK", "reason": "no_aggregate_data"})
        return
    pids = [row["publisher_id"] for row in rows]
    if pids:
        pub_all = client.query_df(
            PER_SECOND_PRICES_QUERY,
            parameters={
                "feed_id": fs.feed_id,
                "start": pstart,
                "end": pend,
                "publisher_ids": pids,
            },
        )
        pub_all = restrict_to_mask(pub_all, mask)
    else:
        pub_all = pd.DataFrame(columns=["ts", "publisher_id", "price"])
    for row in rows:
        if len(pub_all):
            pub_df = pub_all[pub_all["publisher_id"] == row["publisher_id"]][
                ["ts", "price"]
            ]
        else:
            pub_df = pd.DataFrame(columns=["ts", "price"])
        result = evaluate_peer(pub_df, agg_df[["ts", "price"]], thresholds)
        verdict, reason = verdict_from_peer(result)
        row.update(
            {
                "benchmark_date": f"{pstart}..{pend}",
                "nrmse": round(result["nrmse"], 6)
                if result["nrmse"] == result["nrmse"]
                else "",
                "hit_rate": round(result["hit_rate_pct"], 2)
                if result["hit_rate_pct"] == result["hit_rate_pct"]
                else "",
                "n_obs": result["n_observations"],
                "verdict": verdict,
                "reason": reason,
            }
        )


def _skip_session(base, fs, reason, detail):
    summary = {
        **base,
        "quality_path": "none",
        "n_incumbents": len(fs.allowed),
        "n_pass": 0,
        "n_fail": 0,
        "n_no_data": 0,
        "n_no_benchmark": 0,
        "all_pass": False,
        "n_candidates": 0,
        "n_candidates_pass": 0,
    }
    flagged = {
        **base,
        "publisher_id": "",
        "publisher_role": "",
        "verdict": "",
        "reason": reason,
        "detail": detail,
    }
    return summary, flagged


def evaluate_feed(client, fs_list, args, excluded, production_pubs):
    """Sweep all sessions of one feed. Returns (report, summary, flagged) row lists."""
    feed_id = fs_list[0].feed_id
    start_s = args.start_utc.strftime("%Y-%m-%d %H:%M:%S")
    end_s = args.end_utc.strftime("%Y-%m-%d %H:%M:%S")
    matrix = client.query_df(
        ACTIVITY_QUERY,
        parameters={"feed_id": feed_id, "start": start_s, "end": end_s},
    )
    if len(matrix):
        matrix["minute"] = pd.to_datetime(matrix["minute"], utc=True)
    else:
        matrix = pd.DataFrame(columns=["minute", "publisher_id", "n_updates"])
    matrix_pubs = set(matrix["publisher_id"].astype(int)) if len(matrix) else set()

    thresholds = PeerThresholds(
        nrmse_auto=args.peer_nrmse_auto,
        nrmse_cond=args.peer_nrmse_cond,
        min_hit_rate_pct=args.peer_hit_rate,
        min_obs=args.min_obs,
    )
    report_rows, summary_rows, flagged_rows = [], [], []

    for fs in fs_list:
        base = {
            "feed_id": fs.feed_id,
            "symbol": fs.symbol,
            "session": fs.session,
            "asset_type": fs.asset_type,
        }
        if fs.schedule_str is None:
            s, f = _skip_session(
                base, fs, "no_schedule", "market schedule unresolvable"
            )
            summary_rows.append(s)
            flagged_rows.append(f)
            continue
        try:
            schedule = parse_market_schedule(fs.schedule_str)
        except ValueError:
            s, f = _skip_session(base, fs, "no_schedule", "market schedule unparsable")
            summary_rows.append(s)
            flagged_rows.append(f)
            continue
        mask = open_minutes_mask(schedule, args.start_utc, args.end_utc)

        pubs = [("incumbent", pid) for pid in sorted(fs.allowed)]
        if args.include_candidates:
            pubs += [
                ("candidate", pid)
                for pid in discover_candidates(
                    matrix_pubs, production_pubs, fs.allowed, excluded
                )
            ]
        mode = engine_mode_for(fs)
        quality_path = "engine" if mode else "peer"
        rows = [
            {
                **base,
                "publisher_id": pid,
                "publisher_role": role,
                "quality_path": quality_path,
                "engine_mode": mode or "",
                "benchmark_date": "",
                "activity_pct": round(activity_pct(matrix, mask, pid), 4),
                "rmse_over_spread": "",
                "hit_rate": "",
                "nrmse": "",
                "n_obs": "",
            }
            for role, pid in pubs
        ]
        if mode:
            _score_engine(rows, fs, mode, args)
        else:
            _score_peer(client, rows, fs, mask, thresholds, args)

        report_rows.extend(rows)
        summary_rows.append(
            {**base, "quality_path": quality_path, **summarize_session(rows)}
        )
        for row in rows:
            failing_incumbent = (
                row["publisher_role"] == "incumbent" and row["verdict"] != "PASS"
            )
            failing_candidate = (
                row["publisher_role"] == "candidate" and row["verdict"] == "FAIL"
            )
            if failing_incumbent or failing_candidate:
                flagged_rows.append(
                    {
                        **{
                            k: row[k]
                            for k in (
                                "feed_id",
                                "symbol",
                                "session",
                                "publisher_id",
                                "publisher_role",
                                "verdict",
                                "reason",
                            )
                        },
                        "detail": (
                            f"activity={row['activity_pct']}, nrmse={row['nrmse']}, "
                            f"hit={row['hit_rate']}, n_obs={row['n_obs']}"
                        ),
                    }
                )
    return report_rows, summary_rows, flagged_rows


def main(argv=None) -> int:
    args = parse_args(argv)
    args.start_utc = datetime.strptime(args.start_date, "%Y-%m-%d").replace(
        tzinfo=timezone.utc
    )
    args.end_utc = datetime.strptime(args.end_date, "%Y-%m-%d").replace(
        tzinfo=timezone.utc
    )

    config = json.loads(Path(args.config).read_text())
    ensure_new_format(config)

    audit_cls = load_audit_classifications(args.audit_csv) if args.audit_csv else {}
    excluded = load_excluded_publishers(args.publishers_md) | set(
        args.exclude_publisher
    )

    by_feed = {}
    for fs in iter_stable_sessions(config):
        if args.feed_id and fs.feed_id not in args.feed_id:
            continue
        by_feed.setdefault(fs.feed_id, []).append(fs)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "incumbent_report.csv"
    summary_path = out_dir / "incumbent_quality_summary.csv"
    flagged_path = out_dir / "flagged_incumbents.csv"

    done = resume_done_feed_ids(summary_path) if args.resume else set()
    if done:
        print(f"Resume: skipping {len(done)} already-swept feeds")
    todo = {fid: fss for fid, fss in by_feed.items() if fid not in done}
    print(
        f"Sweeping {len(todo)} feeds "
        f"({args.start_utc:%Y-%m-%d} .. {args.end_utc:%Y-%m-%d}, "
        f"candidates={'on' if args.include_candidates else 'off'})"
    )

    from lib.config import ThreadLocalClients, load_config

    resuming = args.resume and summary_path.exists()
    if resuming:
        for path in (report_path, flagged_path):
            n_pruned = prune_orphan_rows(path, done)
            if n_pruned:
                print(f"Resume: pruned {n_pruned} orphan rows from {path}")

    new_file = not resuming
    file_mode = "w" if new_file else "a"
    report_f = open(report_path, file_mode, newline="")
    summary_f = open(summary_path, file_mode, newline="")
    flagged_f = open(flagged_path, file_mode, newline="")
    report_w = csv.DictWriter(
        report_f, fieldnames=REPORT_COLUMNS, extrasaction="ignore"
    )
    summary_w = csv.DictWriter(
        summary_f, fieldnames=SUMMARY_COLUMNS, extrasaction="ignore"
    )
    flagged_w = csv.DictWriter(
        flagged_f, fieldnames=FLAGGED_COLUMNS, extrasaction="ignore"
    )
    if new_file:
        for w in (report_w, summary_w, flagged_w):
            w.writeheader()
        for f in (report_f, summary_f, flagged_f):
            f.flush()

    write_lock = threading.Lock()
    failures = 0
    with ThreadLocalClients(load_config(), lazer_only=True) as pool:
        production_pubs = (
            fetch_production_publisher_ids(pool.get_lazer_client())
            if args.include_candidates
            else set()
        )
        if args.include_candidates:
            print(f"{len(production_pubs)} production-key publishers")

        def run_one(fss):
            client = pool.get_lazer_client()
            return evaluate_feed(client, fss, args, excluded, production_pubs)

        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            futures = {executor.submit(run_one, fss): fid for fid, fss in todo.items()}
            for i, future in enumerate(as_completed(futures), 1):
                fid = futures[future]
                try:
                    report_rows, summary_rows, flagged_rows = future.result()
                except Exception as e:  # soft-fail per feed (bulk-runner pattern)
                    failures += 1
                    print(f"  [{i}/{len(todo)}] feed {fid} FAILED: {e}")
                    continue
                for row in summary_rows:
                    row["audit_classification"] = audit_cls.get(
                        (row["feed_id"], row["session"]), ""
                    )
                with write_lock:
                    report_w.writerows(report_rows)
                    summary_w.writerows(summary_rows)
                    flagged_w.writerows(flagged_rows)
                    # Flush order is intentional: summary is the resume marker
                    # (resume_done_feed_ids reads it), so it must be made
                    # durable last. A crash between report/flagged flush and
                    # summary flush leaves orphan report/flagged rows for a
                    # feed --resume will safely re-sweep and prune next run;
                    # the reverse order could mark a feed done whose report
                    # rows never landed.
                    report_f.flush()
                    flagged_f.flush()
                    summary_f.flush()
                n_fail = sum(r["n_fail"] for r in summary_rows)
                print(
                    f"  [{i}/{len(todo)}] feed {fid}: "
                    f"{len(report_rows)} publishers, {n_fail} failing incumbents"
                )
    for f in (report_f, summary_f, flagged_f):
        f.close()
    print(
        f"Done ({failures} feed failures) -> "
        f"{report_path}, {summary_path}, {flagged_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
