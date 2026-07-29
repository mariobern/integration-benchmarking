"""Adapter: active_min_pub BREACH/CRITICAL feed-sessions -> Stage 2/3 audit CSV.

Filters an active_min_pub.py summary CSV down to feed-sessions whose verdict is
BREACH or CRITICAL (WARN too, with --include-warn) and whose effective_min_pub
is >= --min-pub-floor (default 2) -- min_pub == 1 feed-sessions are structurally
single-source (no second publisher to qualify against) and are written to a
separate excluded CSV instead of being silently dropped.

The flagged output is a drop-in --audit-csv for the existing, unmodified
qualify_candidates.py (Stage 2): that script only ever reads feed_id, session,
and classification from its --audit-csv, so any CSV carrying those three
columns with classification in {"CRITICAL", "WARN"} works unchanged.

Run:
    python3 -m lazer_dq.active_min_pub_to_audit \\
        --active-min-pub-csv output_csv/active_min_pub_2026-07-14_2026-07-22.csv \\
        [--min-pub-floor 2] [--include-warn] [--output-dir output_csv]
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
from collections import Counter
from pathlib import Path

FLAGGED_COLUMNS = [
    "feed_id",
    "symbol",
    "session",
    "classification",
    "source_verdict",
    "asset_type",
    "effective_min_pub",
    "pct_below_par",
    "pct_at_par",
    "pct_at_floor",
    "pct_at_floor_1",
    "min",
    "median",
    "n_updates",
]

EXCLUDED_COLUMNS = [
    "feed_id",
    "symbol",
    "session",
    "source_verdict",
    "effective_min_pub",
    "pct_at_floor",
    "reason",
]

_BASE_TARGET_VERDICTS = frozenset({"BREACH", "CRITICAL"})

_FILENAME_RE = re.compile(r"active_min_pub_(\d{4}-\d{2}-\d{2}_\d{4}-\d{2}-\d{2})\.csv")


def target_verdicts(include_warn: bool) -> frozenset:
    """Verdicts this adapter routes forward, before the min_pub_floor split."""
    return _BASE_TARGET_VERDICTS | ({"WARN"} if include_warn else frozenset())


def bucket_for_row(row: dict, min_pub_floor: int, include_warn: bool) -> str:
    """'flagged' (-> Stage 2), 'excluded' (surfaced, not routed), or 'drop'."""
    if row["verdict"] not in target_verdicts(include_warn):
        return "drop"
    if int(row["effective_min_pub"]) >= min_pub_floor:
        return "flagged"
    return "excluded"


def to_flagged_row(row: dict) -> dict:
    """Shape a source active_min_pub row into a Stage-2-compatible flagged row.

    classification collapses BREACH and CRITICAL to the literal "CRITICAL" that
    qualify_candidates.py expects; the original verdict survives in
    source_verdict for human traceability.
    """
    classification = "WARN" if row["verdict"] == "WARN" else "CRITICAL"
    return {
        "feed_id": row["feed_id"],
        "symbol": row["symbol"],
        "session": row["session"],
        "classification": classification,
        "source_verdict": row["verdict"],
        "asset_type": row["asset_type"],
        "effective_min_pub": row["effective_min_pub"],
        "pct_below_par": row["pct_below_par"],
        "pct_at_par": row["pct_at_par"],
        "pct_at_floor": row["pct_at_floor"],
        "pct_at_floor_1": row["pct_at_floor_1"],
        "min": row["min"],
        "median": row["median"],
        "n_updates": row["n_updates"],
    }


def to_excluded_row(row: dict, reason: str) -> dict:
    return {
        "feed_id": row["feed_id"],
        "symbol": row["symbol"],
        "session": row["session"],
        "source_verdict": row["verdict"],
        "effective_min_pub": row["effective_min_pub"],
        "pct_at_floor": row["pct_at_floor"],
        "reason": reason,
    }


def parse_window_from_filename(path: Path) -> str:
    """Extract '<start>_<end>' from an active_min_pub_<start>_<end>.csv name.

    Raises ValueError (with the offending filename in the message) for any
    other name, including the hand-curated active_min_pub_CRITICAL_<date>.csv
    snapshot format, which this script does not consume.
    """
    m = _FILENAME_RE.fullmatch(path.name)
    if not m:
        raise ValueError(
            f"{path.name} doesn't match active_min_pub_<start>_<end>.csv -- pass "
            "a standard active_min_pub.py summary CSV, not a hand-curated snapshot"
        )
    return m.group(1)


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--active-min-pub-csv", required=True)
    p.add_argument("--min-pub-floor", type=int, default=2)
    p.add_argument("--include-warn", action="store_true")
    p.add_argument("--output-dir", default="output_csv")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    in_path = Path(args.active_min_pub_csv)
    try:
        stamp = parse_window_from_filename(in_path)
    except ValueError as e:
        print(f"ERROR: {e}")
        return 1

    with open(in_path, newline="") as f:
        rows = list(csv.DictReader(f))

    verdict_tally = Counter(r["verdict"] for r in rows)
    warn_skipped = verdict_tally.get("WARN", 0) if not args.include_warn else 0

    flagged, excluded = [], []
    for row in rows:
        bucket = bucket_for_row(row, args.min_pub_floor, args.include_warn)
        if bucket == "flagged":
            flagged.append(to_flagged_row(row))
        elif bucket == "excluded":
            excluded.append(to_excluded_row(row, "min_pub_floor_1"))

    flagged.sort(key=lambda r: -float(r["pct_at_floor"]))

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    flagged_path = out_dir / f"active_min_pub_flagged_{stamp}.csv"
    excluded_path = out_dir / f"active_min_pub_excluded_{stamp}.csv"

    with open(flagged_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FLAGGED_COLUMNS)
        writer.writeheader()
        writer.writerows(flagged)

    with open(excluded_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=EXCLUDED_COLUMNS)
        writer.writeheader()
        writer.writerows(excluded)

    print(f"Read {len(rows)} rows from {in_path}")
    for verdict, n in sorted(verdict_tally.items(), key=lambda kv: -kv[1]):
        print(f"  {verdict:12} {n}")
    print(f"\nFlagged {len(flagged)} feed-sessions -> {flagged_path}")
    print(
        f"Excluded {len(excluded)} feed-sessions (min_pub_floor={args.min_pub_floor}) "
        f"-> {excluded_path}"
    )
    if not args.include_warn and warn_skipped:
        print(f"Skipped {warn_skipped} WARN rows (pass --include-warn to include them)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
