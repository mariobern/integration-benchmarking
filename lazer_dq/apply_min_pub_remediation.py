"""Stage 3 of the min_pub pipeline: apply selected publishers and verify.

Reads Stage-2 outputs, builds a batched edit_config YAML spec, runs
tools/edit-config/edit_config.py (dry-run by default; --apply to write),
then verifies the modified config:

  1. static_margin / selected_applied — every remediated (feed, session)
     contains exactly the selected publishers, no duplicates, and reaches
     allowed_count >= target where Stage 2 said the target was met;
  2. linter — tools/config-linter/config_linter.py error count does not
     increase vs the pre-apply baseline (best-effort: SKIPPED if the linter
     rejects the new format);
  3. projected_margin — worst-minute recomputation from the Stage-2
     activity matrices with the new allowed sets.

Run (dry-run, then apply):
    python3 -m lazer_dq.apply_min_pub_remediation --config lazer_to_modify.json \
        --start-date 2026-07-06 --end-date 2026-07-13
    python3 -m lazer_dq.apply_min_pub_remediation --config lazer_to_modify.json \
        --start-date 2026-07-06 --end-date 2026-07-13 --apply
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yaml

from lazer_dq.market_schedule import open_minutes_mask, parse_market_schedule
from lazer_dq.min_pub_common import iter_stable_sessions
from lazer_dq.qualify_candidates import projected_worst_minute

EDIT_CONFIG = Path("tools/edit-config/edit_config.py")
LINTER = Path("tools/config-linter/config_linter.py")


def build_spec(selected_df: pd.DataFrame) -> dict:
    """Batched edit_config YAML spec: one add_publisher op per (publisher, session)."""
    sel = selected_df[selected_df["selected"] == True]  # noqa: E712 (CSV bools)
    ops = []
    for (publisher_id, session), group in sorted(
        sel.groupby(["candidate_publisher_id", "session"])
    ):
        feed_ids = sorted(set(int(f) for f in group["feed_id"]))
        op = {
            "op": "add_publisher",
            "publisher_id": int(publisher_id),
            "feed_id": ",".join(str(f) for f in feed_ids),
        }
        if session != "REGULAR":
            op["session"] = session
        ops.append(op)
    return {"version": 1, "operations": ops}


def run_edit_config(config_path, spec_path, apply: bool) -> int:
    argv = [
        sys.executable,
        str(EDIT_CONFIG),
        "--config",
        str(config_path),
        "--from-spec",
        str(spec_path),
    ]
    if apply:
        argv.append("--apply")
    print(f"$ {' '.join(argv)}")
    return subprocess.run(argv, check=False).returncode


def _parse_linter_error_count(text: str, returncode: int) -> int | None:
    """Parse linter error count from JSON or text output.

    Args:
        text: Combined stdout + stderr from the linter.
        returncode: Exit code from the linter subprocess.

    Returns:
        Error count if found, 0 if linter ran cleanly with no errors,
        None if the linter failed or output format is unrecognized.
    """
    # Try JSON format first (most reliable).
    # JSON may span multiple lines, so extract the JSON object.
    json_match = re.search(r"\{[\s\S]*\}", text)
    if json_match:
        try:
            data = json.loads(json_match.group(0))
            if "findings" in data:
                errors = [f for f in data["findings"] if f.get("severity") == "ERROR"]
                return len(errors)
        except (json.JSONDecodeError, ValueError):
            pass

    # Fall back to Summary line regex parsing.
    match = re.search(r"Summary:\s*(\d+)\s+errors", text)
    if match:
        return int(match.group(1))

    # Summary line absent: check returncode to decide if linter failed.
    if returncode != 0:
        return None  # Linter itself failed (e.g., old-format assumption).
    return 0  # Linter ran successfully; no summary means no errors.


def count_linter_errors(config_path) -> int | None:
    """Linter error count, or None if the linter can't run on this config.

    Prefers JSON output (--format json) for reliable parsing.
    """
    try:
        result = subprocess.run(
            [
                sys.executable,
                str(LINTER),
                "--config",
                str(config_path),
                "--format",
                "json",
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except Exception:
        return None
    text = result.stdout + result.stderr
    return _parse_linter_error_count(text, result.returncode)


def _session_allowed(config: dict) -> dict:
    """{(feed_id, session): list allowedPublisherIds} for STABLE feeds."""
    return {(fs.feed_id, fs.session): fs for fs in iter_stable_sessions(config)}


def verify_static(config: dict, selected_df, summary_df) -> list:
    rows = []
    sessions = _session_allowed(config)
    sel = selected_df[selected_df["selected"] == True]  # noqa: E712
    raw_lists = {
        (f["feedId"], e.get("session", "REGULAR")): e.get("allowedPublisherIds", [])
        for f in config.get("feeds", [])
        for e in f.get("marketSchedules", [])
    }
    for (feed_id, session), group in sel.groupby(["feed_id", "session"]):
        key = (int(feed_id), session)
        fs = sessions.get(key)
        raw = raw_lists.get(key, [])
        # duplicates?
        if len(raw) != len(set(raw)):
            rows.append(
                {
                    "check": "static_margin",
                    "feed_id": feed_id,
                    "session": session,
                    "status": "FAIL",
                    "detail": "duplicate publisher ids in allowed list",
                }
            )
            continue
        missing = [
            int(p)
            for p in group["candidate_publisher_id"]
            if fs is None or int(p) not in fs.allowed
        ]
        rows.append(
            {
                "check": "selected_applied",
                "feed_id": feed_id,
                "session": session,
                "status": "FAIL" if missing else "PASS",
                "detail": f"missing {missing}" if missing else "",
            }
        )
        srow = summary_df[
            (summary_df["feed_id"] == int(feed_id)) & (summary_df["session"] == session)
        ]
        if fs is not None and len(srow) and bool(srow.iloc[0]["met_target"]):
            target = int(srow.iloc[0]["target"])
            ok = len(fs.allowed) >= target
            rows.append(
                {
                    "check": "static_margin",
                    "feed_id": feed_id,
                    "session": session,
                    "status": "PASS" if ok else "FAIL",
                    "detail": f"allowed {len(fs.allowed)} vs target {target}",
                }
            )
    return rows


def verify_projection(
    config, selected_df, summary_df, activity_dir, start_utc, end_utc
):
    rows = []
    sessions = _session_allowed(config)
    sel = selected_df[selected_df["selected"] == True]  # noqa: E712
    for (feed_id, session), _group in sel.groupby(["feed_id", "session"]):
        key = (int(feed_id), session)
        fs = sessions.get(key)
        matrix_path = Path(activity_dir) / f"feed_{int(feed_id)}.csv.gz"
        srow = summary_df[
            (summary_df["feed_id"] == int(feed_id)) & (summary_df["session"] == session)
        ]
        if (
            fs is None
            or fs.schedule_str is None
            or not matrix_path.exists()
            or not len(srow)
        ):
            rows.append(
                {
                    "check": "projected_margin",
                    "feed_id": feed_id,
                    "session": session,
                    "status": "SKIPPED",
                    "detail": "missing session/schedule/matrix/summary",
                }
            )
            continue
        matrix = pd.read_csv(matrix_path)
        matrix["minute"] = pd.to_datetime(matrix["minute"], utc=True)
        mask = open_minutes_mask(
            parse_market_schedule(fs.schedule_str), start_utc, end_utc
        )
        projected = projected_worst_minute(matrix, mask, set(fs.allowed))
        target = int(srow.iloc[0]["target"])
        met_target = bool(srow.iloc[0]["met_target"])
        ok = projected >= target or not met_target
        rows.append(
            {
                "check": "projected_margin",
                "feed_id": feed_id,
                "session": session,
                "status": "PASS" if ok else "FAIL",
                "detail": f"projected worst {projected} vs target {target}"
                + ("" if met_target else " (below target; feed is flagged)"),
            }
        )
    return rows


def parse_args(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", required=True)
    p.add_argument("--candidates-csv", default="output_csv/candidates_report.csv")
    p.add_argument("--summary-csv", default="output_csv/qualification_summary.csv")
    p.add_argument("--activity-dir", default="output_csv/min_pub_activity")
    p.add_argument("--start-date", required=True)
    p.add_argument("--end-date", required=True)
    p.add_argument("--apply", action="store_true")
    p.add_argument("--skip-linter", action="store_true")
    p.add_argument("--output-dir", default="output_csv")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    start_utc = datetime.strptime(args.start_date, "%Y-%m-%d").replace(
        tzinfo=timezone.utc
    )
    end_utc = datetime.strptime(args.end_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    candidates = pd.read_csv(args.candidates_csv)
    summary = pd.read_csv(args.summary_csv)
    spec = build_spec(candidates)
    if not spec["operations"]:
        print("Nothing selected — no operations to apply.")
        return 0
    spec_path = out_dir / "min_pub_remediation_spec.yaml"
    spec_path.write_text(yaml.safe_dump(spec, sort_keys=False))
    n_adds = int((candidates["selected"] == True).sum())  # noqa: E712
    print(
        f"Spec: {len(spec['operations'])} ops covering {n_adds} (feed, session, publisher) adds -> {spec_path}"
    )

    linter_baseline = None
    if args.apply and not args.skip_linter:
        linter_baseline = count_linter_errors(args.config)

    rc = run_edit_config(args.config, spec_path, apply=args.apply)
    if rc != 0:
        print(
            f"edit_config exited {rc} — aborting. Config was "
            + ("possibly modified; check git diff." if args.apply else "not modified.")
        )
        return 1
    if not args.apply:
        print("Dry-run complete. Re-run with --apply to write the config.")
        return 0

    # applied_changes.csv
    sel = candidates[candidates["selected"] == True]  # noqa: E712
    applied_path = out_dir / "applied_changes.csv"
    sel[
        [
            "feed_id",
            "symbol",
            "session",
            "candidate_publisher_id",
            "quality_path",
            "selection_rank",
        ]
    ].rename(columns={"candidate_publisher_id": "publisher_id"}).to_csv(
        applied_path, index=False
    )
    print(f"Applied changes -> {applied_path}")

    # Verification
    config = json.loads(Path(args.config).read_text())
    report = verify_static(config, candidates, summary)
    if args.skip_linter:
        report.append(
            {
                "check": "linter",
                "feed_id": "",
                "session": "",
                "status": "SKIPPED",
                "detail": "--skip-linter",
            }
        )
    else:
        after = count_linter_errors(args.config)
        if linter_baseline is None or after is None:
            report.append(
                {
                    "check": "linter",
                    "feed_id": "",
                    "session": "",
                    "status": "SKIPPED",
                    "detail": "linter unavailable on this config format",
                }
            )
        else:
            report.append(
                {
                    "check": "linter",
                    "feed_id": "",
                    "session": "",
                    "status": "PASS" if after <= linter_baseline else "FAIL",
                    "detail": f"errors before={linter_baseline} after={after}",
                }
            )
    report += verify_projection(
        config, candidates, summary, args.activity_dir, start_utc, end_utc
    )

    report_path = out_dir / "verification_report.csv"
    with open(report_path, "w", newline="") as fh:
        writer = csv.DictWriter(
            fh, fieldnames=["check", "feed_id", "session", "status", "detail"]
        )
        writer.writeheader()
        writer.writerows(report)
    failures = [r for r in report if r["status"] == "FAIL"]
    print(f"Verification: {len(report)} checks, {len(failures)} FAIL -> {report_path}")
    for r in failures:
        print(f"  FAIL {r['check']} feed {r['feed_id']}/{r['session']}: {r['detail']}")
    print("Review `git diff` on the config plus the CSVs before committing.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
