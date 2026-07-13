# lazer_dq/qualify_candidates.py
"""Stage 2 of the min_pub pipeline: qualify candidate publishers.

Reads the Stage-1 audit CSV, and for each CRITICAL/WARN (feed, session):
  1. discovers candidates — production-key publishers already submitting to
     the feed (ACCEPTED or REJECTED/UNAUTHORIZED) but not in the session's
     allowedPublisherIds and not excluded (publisher 0, publishers.md
     ".Test" entries, --exclude-publisher);
  2. Gate 1 (activity): active >= --min-activity share of open minutes;
  3. Gate 2 (quality): Datascope engine run for supported modes, else peer
     comparison vs the feed's aggregate (lazer_dq/peer_benchmark.py);
  4. selects passers (best quality first) until the projected worst-minute
     active count reaches min_pub + --target-margin.

Run:
    python3 -m lazer_dq.qualify_candidates --config lazer_to_modify.json \
        --audit-csv output_csv/min_pub_audit_2026-07-06_2026-07-13.csv \
        --start-date 2026-07-06 --end-date 2026-07-13 --cluster lazer-prod

Note: AGGREGATE_QUERY aliases its output column `price` (via `argMax(...) AS
price`) while also filtering `price IS NOT NULL` in the WHERE clause on the
same (unqualified) name. Against the real ClickHouse Cloud server this raises
`Code: 184 ILLEGAL_AGGREGATION` — ClickHouse resolves the unqualified WHERE
identifier against the SELECT-level alias (which wraps an aggregate) instead
of the underlying table column. Fixed by aliasing the table (`price_feeds AS
pf`) and qualifying every WHERE column (`pf.price_feed_id`, `pf.publish_time`,
`pf.price`, `pf.channel`), which keeps the WHERE clause resolving against the
real table columns instead of the SELECT alias.
"""
from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from lazer_dq.evaluate_feeds_bulk import compute_times_from_mode
from lazer_dq.market_schedule import open_minutes_mask, parse_market_schedule
from lazer_dq.min_pub_common import FeedSession, iter_stable_sessions
from lazer_dq.peer_benchmark import PeerThresholds, evaluate_peer
from lazer_dq.summarize_feeds import (
    ASSET_CLASS_CONFIG,
    load_excluded_publishers,
    load_stats,
)
from lib.thresholds import passes_benchmark

FLAG_REASONS = (
    "no_candidates",
    "candidates_fail_activity",
    "candidates_fail_quality",
    "still_below_target",
    "no_benchmark_data",
)

CANDIDATE_COLUMNS = [
    "feed_id",
    "symbol",
    "session",
    "classification",
    "candidate_publisher_id",
    "activity_pct",
    "gate1_pass",
    "quality_path",
    "engine_mode",
    "benchmark_date",
    "rmse_over_spread",
    "hit_rate",
    "n_obs",
    "nrmse",
    "gate2_pass",
    "selected",
    "selection_rank",
]
SUMMARY_COLUMNS = [
    "feed_id",
    "symbol",
    "session",
    "classification",
    "effective_min_pub",
    "target",
    "worst_minute_before",
    "n_candidates",
    "n_gate1",
    "n_gate2",
    "n_selected",
    "projected_worst_after",
    "met_target",
]

ACTIVITY_QUERY = """
    SELECT
        toStartOfMinute(pu.publish_time) AS minute,
        pu.publisher_id AS publisher_id,
        count() AS n_updates
    FROM publisher_updates pu
    PREWHERE pu.price_feed_id = {feed_id:UInt64}
    WHERE pu.publish_time >= {start:String}
      AND pu.publish_time < {end:String}
      AND (
        pu.status = 'ACCEPTED'
        OR (pu.status = 'REJECTED' AND pu.status_reason = 'UNAUTHORIZED')
      )
      AND pu.price IS NOT NULL
    GROUP BY minute, publisher_id
"""

PRODUCTION_PUBLISHERS_QUERY = """
    SELECT DISTINCT publisher_id
    FROM publishers_metadata_latest
    WHERE key_type IN ('production', 'Production')
"""

PER_SECOND_PRICES_QUERY = """
    SELECT
        toStartOfSecond(pu.publish_time) AS ts,
        pu.publisher_id AS publisher_id,
        argMax(pu.price, pu.publish_time) AS price
    FROM publisher_updates pu
    INNER JOIN publishers_metadata_latest pml
        ON pu.publisher_id = pml.publisher_id
    PREWHERE pu.price_feed_id = {feed_id:UInt64}
    WHERE pu.publish_time >= {start:String}
      AND pu.publish_time < {end:String}
      AND (
        pu.status = 'ACCEPTED'
        OR (pu.status = 'REJECTED' AND pu.status_reason = 'UNAUTHORIZED')
      )
      AND pu.price IS NOT NULL
      AND pu.publisher_id IN {publisher_ids:Array(UInt64)}
      AND pml.key_type IN ('production', 'Production')
    GROUP BY ts, publisher_id
    ORDER BY ts
"""

AGGREGATE_QUERY = """
    SELECT
        toStartOfSecond(publish_time) AS ts,
        argMax(price, publish_time) AS price
    FROM price_feeds AS pf
    WHERE pf.price_feed_id = {feed_id:UInt64}
      AND pf.publish_time >= {start:String}
      AND pf.publish_time < {end:String}
      AND pf.price IS NOT NULL
      AND pf.channel = {channel:UInt8}
    GROUP BY ts
    ORDER BY ts
"""

US_EQUITY_SESSION_MODES = {
    "REGULAR": "us-equities",
    "PRE_MARKET": "us-equities-pre",
    "POST_MARKET": "us-equities-post",
    "OVER_NIGHT": "us-equities-overnight",
}

ENGINE_MODE_THRESHOLDS = {}
for _ac in ASSET_CLASS_CONFIG.values():
    for _m in _ac["modes"]:
        ENGINE_MODE_THRESHOLDS[_m] = (
            _ac["default_max_ros"][_m],
            _ac["default_min_hit"][_m],
        )


def engine_mode_for(fs: FeedSession):
    """DQ-engine mode for this (feed, session), or None -> peer path."""
    if fs.asset_type == "fx":
        return "fx"
    if fs.asset_type == "metal":
        return "metals"
    if fs.asset_type == "commodity":
        return "commodity"
    if fs.asset_type == "rates":
        return "us-treasuries-yield"
    if fs.asset_type == "equity":
        if fs.symbol.startswith("Equity.US."):
            return US_EQUITY_SESSION_MODES.get(fs.session)
        if fs.symbol.startswith("Equity.HK.") and fs.session == "REGULAR":
            return "hk-equities"
        # TODO(#287): once jp/kr/in-equities modes land in
        # summarize_feeds.ASSET_CLASS_CONFIG, add Equity.JP./Equity.KR./
        # Equity.IN. prefix checks here (mirroring the Equity.HK. case
        # above) — otherwise those feeds keep routing to the peer path.
    return None


# Modes not covered by ENGINE_MODE_THRESHOLDS (i.e. not in
# summarize_feeds.ASSET_CLASS_CONFIG) but for which the repo defines a
# per-tier pass/fail bar in lib/thresholds.py. Gate 2 uses that bar instead
# of the engine's hardcoded (stricter) pass_fail so candidates are held to
# the same tier their feed's existing publishers are evaluated against.
TIER_GATED_MODES = {"fx", "metals", "commodity", "us-treasuries-yield"}


def engine_gate(stats_row: dict, mode: str, min_obs: int) -> bool:
    """Gate 2 (quality) pass/fail for one candidate's engine stats row.

    Three cases, in priority order:
      1. mode in ENGINE_MODE_THRESHOLDS (us-equities*/hk-equities, sourced
         from summarize_feeds.ASSET_CLASS_CONFIG): rmse_over_spread and
         hit_rate_0.1pct vs the per-mode configured thresholds.
      2. mode in TIER_GATED_MODES (fx, metals, commodity,
         us-treasuries-yield): nrmse and hit_rate_0.1pct vs the matching
         per-tier SessionThresholds from lib/thresholds.py (regular tier for
         fx and us-treasuries-yield; relaxed tier for metals/commodity) via
         lib.thresholds.passes_benchmark — the same bar used to evaluate the
         feed's current publishers, rather than the engine's stricter
         hardcoded pass_fail fallback.
      3. Any other/unknown mode: falls back to the stats row's own
         `pass_fail` column (engine's hardcoded nrmse<0.01, or nrmse<0.05
         with hit_rate>=98).

    `n_observations >= min_obs` is enforced first in all cases.
    """
    try:
        n_obs = int(float(stats_row["n_observations"]))
    except (KeyError, ValueError):
        return False
    if n_obs < min_obs:
        return False
    if mode in ENGINE_MODE_THRESHOLDS:
        max_ros, min_hit = ENGINE_MODE_THRESHOLDS[mode]
        try:
            return (
                float(stats_row["rmse_over_spread"]) <= max_ros
                and float(stats_row["hit_rate_0.1pct"]) >= min_hit
            )
        except (KeyError, ValueError):
            return False
    if mode in TIER_GATED_MODES:
        try:
            nrmse = float(stats_row["nrmse"])
            hit_rate = float(stats_row["hit_rate_0.1pct"])
        except (KeyError, ValueError):
            return False
        return passes_benchmark(nrmse, hit_rate, mode=mode)
    return stats_row.get("pass_fail") == "pass"


def _warn_if_worst_minute_diverges_from_audit(fs, audit_row, before: int) -> None:
    """Print a warning if Stage 2's worst_minute_before disagrees with Stage 1.

    Both are the worst-minute active-allowed-publisher count over the same
    window, so they should normally match. Coerce defensively (the audit
    value round-trips through a CSV and may be a string/float, or absent for
    NO_SCHEDULE-era rows) and skip silently when it can't be compared. This
    never fails the run — mask/data differences between the audit and
    qualify runs (e.g. re-audited window, updated schedule) can explain
    small deltas.
    """
    audited_raw = audit_row.get("worst_minute_active")
    if audited_raw is None:
        return
    try:
        audited_val = float(audited_raw)
    except (TypeError, ValueError):
        return
    if audited_val != audited_val:  # NaN
        return
    audited_val = int(audited_val)
    if audited_val != before:
        print(
            f"  warning: feed {fs.feed_id} session {fs.session} worst_minute_before="
            f"{before} differs from audit worst_minute_active={audited_val} "
            "(both computed over the same window; mask/data differences "
            "between the audit and qualify runs can explain small deltas)"
        )


def _open_minute_set(mask: pd.Series) -> set:
    return set(mask.index[mask.to_numpy()])


def activity_pct(matrix_df: pd.DataFrame, mask: pd.Series, publisher_id: int) -> float:
    open_minutes = _open_minute_set(mask)
    if not open_minutes:
        return 0.0
    pub_minutes = set(
        matrix_df.loc[matrix_df["publisher_id"] == publisher_id, "minute"]
    )
    return len(pub_minutes & open_minutes) / len(open_minutes)


def projected_worst_minute(
    matrix_df: pd.DataFrame, mask: pd.Series, publisher_ids
) -> int:
    """Worst per-open-minute count of the given publishers (missing minute = 0)."""
    open_minutes = mask.index[mask.to_numpy()]
    if len(open_minutes) == 0:
        return 0
    sub = matrix_df[matrix_df["publisher_id"].isin(publisher_ids)]
    per_minute = sub.groupby("minute")["publisher_id"].nunique()
    counts = per_minute.reindex(open_minutes, fill_value=0)
    return int(counts.min())


def select_candidates(passers, matrix_df, mask, allowed, min_pub, target_margin):
    """Greedy best-quality-first selection until worst-minute target is met.

    passers: list of {"candidate_publisher_id": int, "sort_metric": float}.
    Returns (selected_ids_in_order, projected_worst_after).
    """
    target = min_pub + target_margin
    chosen: list = []
    current = set(allowed)
    projected = projected_worst_minute(matrix_df, mask, current)
    for row in sorted(passers, key=lambda r: r["sort_metric"]):
        if projected >= target:
            break
        pid = row["candidate_publisher_id"]
        current.add(pid)
        chosen.append(pid)
        projected = projected_worst_minute(matrix_df, mask, current)
    return chosen, projected


def candidate_dates(start_utc, end_utc, max_dates=3):
    """Most recent weekdays in [start, end), newest first."""
    dates = []
    d = (end_utc - timedelta(days=1)).date()
    while d >= start_utc.date() and len(dates) < max_dates:
        if d.weekday() <= 4:
            dates.append(d.strftime("%Y-%m-%d"))
        d -= timedelta(days=1)
    return dates


def run_engine(feed_id, date, mode, cluster, reports_dir):
    """Subprocess-run the DQ engine unless stats.csv already exists.

    Returns "ok", "skipped" (exit 2 / missing stats), or "failed".
    """
    stats_path = Path(reports_dir) / cluster / mode / str(feed_id) / date / "stats.csv"
    if stats_path.exists():
        return "ok"
    start_time, end_time = compute_times_from_mode(date, mode)
    argv = [
        sys.executable,
        "-m",
        "lazer_dq.evaluate_feed_standalone",
        "--feed-id",
        str(feed_id),
        "--date",
        date,
        "--mode",
        mode,
        "--cluster",
        cluster,
        "--start-time",
        start_time,
        "--end-time",
        end_time,
        "--output-path",
        str(reports_dir),
    ]
    result = subprocess.run(argv, check=False)
    if result.returncode == 0:
        return "ok"
    return "skipped" if result.returncode == 2 else "failed"


def peer_windows(mask: pd.Series, peer_days: int):
    """(start, end) UTC strings covering the last `peer_days` days of the mask."""
    open_minutes = mask.index[mask.to_numpy()]
    if len(open_minutes) == 0:
        return None
    end = open_minutes[-1] + pd.Timedelta(minutes=1)
    start = max(open_minutes[0], end - pd.Timedelta(days=peer_days))
    return start.strftime("%Y-%m-%d %H:%M:%S"), end.strftime("%Y-%m-%d %H:%M:%S")


def fetch_production_publisher_ids(client) -> set:
    """Production-key publisher_ids, queried once per run.

    Candidate discovery requires production keys (see qualify_feed); the
    activity matrix itself is no longer joined against
    publishers_metadata_latest so it covers every submitting publisher,
    matching the Stage-1 audit.
    """
    df = client.query_df(PRODUCTION_PUBLISHERS_QUERY)
    if not len(df):
        return set()
    return set(df["publisher_id"].astype(int))


def fetch_aggregate(client, feed_id, start, end):
    """price_feeds per-second series; tries channels 1..3 (engine pattern)."""
    for channel in (1, 2, 3):
        df = client.query_df(
            AGGREGATE_QUERY,
            parameters={
                "feed_id": feed_id,
                "start": start,
                "end": end,
                "channel": channel,
            },
        )
        if len(df):
            return df
    return pd.DataFrame(columns=["ts", "price"])


def _restrict_to_mask(df: pd.DataFrame, mask: pd.Series) -> pd.DataFrame:
    if df.empty:
        return df
    ts = pd.to_datetime(df["ts"], utc=True)
    minutes = ts.dt.floor("1min")
    open_minutes = _open_minute_set(mask)
    return df[minutes.isin(open_minutes)].assign(ts=ts)


def qualify_feed(
    client, fs_list, audit_by_key, args, excluded, activity_dir, production_pubs
):
    """Qualify one feed's flagged sessions. Returns (candidate_rows, summary_rows, flag_rows)."""
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
    activity_dir.mkdir(parents=True, exist_ok=True)
    matrix.to_csv(activity_dir / f"feed_{feed_id}.csv.gz", index=False)

    candidate_rows, summary_rows, flag_rows = [], [], []
    peer_thresholds = PeerThresholds(
        nrmse_auto=args.peer_nrmse_auto,
        nrmse_cond=args.peer_nrmse_cond,
        min_hit_rate_pct=args.peer_hit_rate,
        min_obs=args.min_obs,
    )

    for fs in fs_list:
        audit_row = audit_by_key[(fs.feed_id, fs.session)]
        mask = open_minutes_mask(
            parse_market_schedule(fs.schedule_str), args.start_utc, args.end_utc
        )
        base = {
            "feed_id": fs.feed_id,
            "symbol": fs.symbol,
            "session": fs.session,
            "classification": audit_row["classification"],
        }

        def flag(reason, detail=""):
            flag_rows.append({**base, "reason": reason, "detail": detail})

        before = projected_worst_minute(matrix, mask, set(fs.allowed))
        _warn_if_worst_minute_diverges_from_audit(fs, audit_row, before)

        all_pubs = set(matrix["publisher_id"].astype(int)) if len(matrix) else set()
        candidates = sorted((all_pubs & production_pubs) - set(fs.allowed) - excluded)
        if not candidates:
            flag("no_candidates", f"{len(all_pubs)} submitting, all allowed/excluded")
            summary_rows.append(_summary(base, fs, args, mask, matrix, [], 0, 0, 0))
            continue

        # Gate 1 — activity
        gate1 = []
        for pid in candidates:
            pct = activity_pct(matrix, mask, pid)
            candidate_rows.append(
                {
                    **base,
                    "candidate_publisher_id": pid,
                    "activity_pct": round(pct, 4),
                    "gate1_pass": pct >= args.min_activity,
                }
            )
            if pct >= args.min_activity:
                gate1.append(pid)
        if not gate1:
            flag(
                "candidates_fail_activity",
                f"{len(candidates)} candidates all below {args.min_activity}",
            )
            summary_rows.append(
                _summary(base, fs, args, mask, matrix, candidates, 0, 0, 0)
            )
            continue

        # Gate 2 — quality
        mode = engine_mode_for(fs)
        passers = []
        rows_by_pid = {
            r["candidate_publisher_id"]: r
            for r in candidate_rows
            if r["feed_id"] == fs.feed_id and r["session"] == fs.session
        }
        if mode is not None:
            stats, used_date = None, None
            for date in candidate_dates(args.start_utc, args.end_utc):
                outcome = run_engine(
                    fs.feed_id, date, mode, args.cluster, args.reports_dir
                )
                if outcome == "ok":
                    stats = load_stats(
                        args.reports_dir, args.cluster, mode, fs.feed_id, date
                    )
                    if stats:
                        used_date = date
                        break
            if stats is None:
                flag("no_benchmark_data", f"mode={mode}, no engine data in window")
                summary_rows.append(
                    _summary(base, fs, args, mask, matrix, candidates, len(gate1), 0, 0)
                )
                continue
            stats_by_pid = {}
            for r in stats:
                try:
                    stats_by_pid[int(float(r["publisher_id"]))] = r
                except (KeyError, ValueError):
                    continue
            for pid in gate1:
                row = rows_by_pid[pid]
                row.update(
                    {
                        "quality_path": "engine",
                        "engine_mode": mode,
                        "benchmark_date": used_date,
                    }
                )
                srow = stats_by_pid.get(pid)
                if srow is None:
                    row["gate2_pass"] = False
                    continue
                row.update(
                    {
                        "rmse_over_spread": srow.get("rmse_over_spread"),
                        "hit_rate": srow.get("hit_rate_0.1pct"),
                        "n_obs": srow.get("n_observations"),
                        "nrmse": srow.get("nrmse"),
                    }
                )
                if engine_gate(srow, mode, args.min_obs):
                    row["gate2_pass"] = True
                    passers.append(
                        {
                            "candidate_publisher_id": pid,
                            "sort_metric": float(srow["rmse_over_spread"]),
                        }
                    )
                else:
                    row["gate2_pass"] = False
        else:
            window = peer_windows(mask, args.peer_days)
            if window is None:
                flag("no_benchmark_data", "no open minutes in window")
                summary_rows.append(
                    _summary(base, fs, args, mask, matrix, candidates, len(gate1), 0, 0)
                )
                continue
            pstart, pend = window
            agg_df = fetch_aggregate(client, fs.feed_id, pstart, pend)
            agg_df = _restrict_to_mask(agg_df, mask)
            if agg_df.empty:
                flag("no_benchmark_data", "no aggregate (price_feeds) data")
                summary_rows.append(
                    _summary(base, fs, args, mask, matrix, candidates, len(gate1), 0, 0)
                )
                continue
            pub_all = client.query_df(
                PER_SECOND_PRICES_QUERY,
                parameters={
                    "feed_id": fs.feed_id,
                    "start": pstart,
                    "end": pend,
                    "publisher_ids": list(gate1),
                },
            )
            pub_all = _restrict_to_mask(pub_all, mask)
            for pid in gate1:
                row = rows_by_pid[pid]
                row.update(
                    {"quality_path": "peer", "benchmark_date": f"{pstart}..{pend}"}
                )
                pub_df = pub_all[pub_all["publisher_id"] == pid][["ts", "price"]]
                result = evaluate_peer(pub_df, agg_df[["ts", "price"]], peer_thresholds)
                row.update(
                    {
                        "nrmse": round(result["nrmse"], 6)
                        if result["nrmse"] == result["nrmse"]
                        else "",
                        "hit_rate": round(result["hit_rate_pct"], 2)
                        if result["hit_rate_pct"] == result["hit_rate_pct"]
                        else "",
                        "n_obs": result["n_observations"],
                        "gate2_pass": result["passed"],
                    }
                )
                if result["passed"]:
                    passers.append(
                        {"candidate_publisher_id": pid, "sort_metric": result["nrmse"]}
                    )

        if not passers:
            flag(
                "candidates_fail_quality",
                f"{len(gate1)} active candidates, 0 passed quality",
            )
            summary_rows.append(
                _summary(base, fs, args, mask, matrix, candidates, len(gate1), 0, 0)
            )
            continue

        selected, projected = select_candidates(
            passers, matrix, mask, fs.allowed, fs.effective_min_pub, args.target_margin
        )
        for rank, pid in enumerate(selected, 1):
            rows_by_pid[pid]["selected"] = True
            rows_by_pid[pid]["selection_rank"] = rank
        target = fs.effective_min_pub + args.target_margin
        if projected < target:
            flag(
                "still_below_target",
                f"projected worst {projected} < target {target} after adding {selected}",
            )
        summary_rows.append(
            _summary(
                base,
                fs,
                args,
                mask,
                matrix,
                candidates,
                len(gate1),
                len(passers),
                len(selected),
                projected,
            )
        )
    return candidate_rows, summary_rows, flag_rows


def _summary(
    base,
    fs,
    args,
    mask,
    matrix,
    candidates,
    n_gate1,
    n_gate2,
    n_selected,
    projected=None,
):
    before = projected_worst_minute(matrix, mask, set(fs.allowed))
    target = fs.effective_min_pub + args.target_margin
    if projected is None:
        projected = before
    return {
        **base,
        "effective_min_pub": fs.effective_min_pub,
        "target": target,
        "worst_minute_before": before,
        "n_candidates": len(candidates),
        "n_gate1": n_gate1,
        "n_gate2": n_gate2,
        "n_selected": n_selected,
        "projected_worst_after": projected,
        "met_target": projected >= target,
    }


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True)
    p.add_argument("--audit-csv", required=True)
    p.add_argument("--start-date", required=True)
    p.add_argument("--end-date", required=True)
    p.add_argument("--cluster", default="lazer-prod")
    p.add_argument("--exclude-publisher", type=int, action="append", default=[])
    p.add_argument("--min-activity", type=float, default=0.90)
    p.add_argument("--target-margin", type=int, default=2)
    p.add_argument("--peer-nrmse-auto", type=float, default=0.05)
    p.add_argument("--peer-nrmse-cond", type=float, default=0.15)
    p.add_argument("--peer-hit-rate", type=float, default=85.0)
    p.add_argument("--min-obs", type=int, default=1000)
    p.add_argument("--peer-days", type=int, default=2)
    p.add_argument("--reports-dir", default="dq_reports")
    p.add_argument("--output-dir", default="output_csv")
    p.add_argument("--publishers-md", default="publishers.md")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    args.start_utc = datetime.strptime(args.start_date, "%Y-%m-%d").replace(
        tzinfo=timezone.utc
    )
    args.end_utc = datetime.strptime(args.end_date, "%Y-%m-%d").replace(
        tzinfo=timezone.utc
    )

    config = json.loads(Path(args.config).read_text())
    audit = pd.read_csv(args.audit_csv)
    flagged = audit[audit["classification"].isin(["CRITICAL", "WARN"])]
    flagged_keys = {
        (int(r.feed_id), r.session): r._asdict() for r in flagged.itertuples()
    }
    print(f"{len(flagged_keys)} flagged (feed, session) pairs from {args.audit_csv}")

    excluded = load_excluded_publishers(args.publishers_md) | set(
        args.exclude_publisher
    )
    by_feed = {}
    for fs in iter_stable_sessions(config):
        if (fs.feed_id, fs.session) in flagged_keys and fs.schedule_str is not None:
            by_feed.setdefault(fs.feed_id, []).append(fs)

    covered_keys = {
        (fs.feed_id, fs.session) for fs_list in by_feed.values() for fs in fs_list
    }
    dropped_keys = sorted(set(flagged_keys.keys()) - covered_keys)
    for feed_id, session in dropped_keys:
        print(
            f"  warning: flagged feed {feed_id} session {session} dropped — "
            "not found among STABLE sessions or schedule unresolvable"
        )

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    activity_dir = out_dir / "min_pub_activity"

    from lib.config import get_lazer_client, load_config

    client = get_lazer_client(load_config())
    production_pubs = fetch_production_publisher_ids(client)
    print(f"{len(production_pubs)} production-key publishers")
    all_candidates, all_summaries, all_flags = [], [], []
    for i, (feed_id, fs_list) in enumerate(sorted(by_feed.items()), 1):
        print(f"[{i}/{len(by_feed)}] qualifying feed {feed_id} ({fs_list[0].symbol})")
        try:
            c, s, f = qualify_feed(
                client,
                fs_list,
                flagged_keys,
                args,
                excluded,
                activity_dir,
                production_pubs,
            )
        except Exception as e:  # soft-fail per feed
            print(f"  feed {feed_id} FAILED: {e}")
            all_flags.append(
                {
                    "feed_id": feed_id,
                    "symbol": fs_list[0].symbol,
                    "session": "",
                    "reason": "no_benchmark_data",
                    "detail": f"error: {e}",
                }
            )
            continue
        all_candidates += c
        all_summaries += s
        all_flags += f

    for name, rows, columns in (
        ("candidates_report.csv", all_candidates, CANDIDATE_COLUMNS),
        ("qualification_summary.csv", all_summaries, SUMMARY_COLUMNS),
        (
            "flagged_feeds.csv",
            all_flags,
            ["feed_id", "symbol", "session", "classification", "reason", "detail"],
        ),
    ):
        path = out_dir / name
        with open(path, "w", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(rows)
        print(f"Wrote {len(rows)} rows -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
