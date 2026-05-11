#!/usr/bin/env python3
"""Bulk DQ runner — calls evaluate_feed_standalone.py once per CSV row.

Replaces the papermill-on-notebook flow in evaluate_feeds.py with subprocess
calls to the standalone engine. Same CSV format (feed_id, date, mode), same
outputs, no notebook artifacts.

Run:
    python3 -m lazer_dq.evaluate_feeds_bulk \\
        --csv MV_Mario_1.csv --cluster lazer-prod
"""
import argparse
import csv as csv_mod
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ENGINE_MODULE = "lazer_dq.evaluate_feed_standalone"


def compute_times_from_mode(date: str, mode: str) -> tuple[str, str]:
    """Resolve (start_utc, end_utc) HH:MM:SS strings from CSV mode + date.

    NY-time market windows are converted to UTC using zoneinfo, which handles
    EDT/EST automatically based on the date.
    """
    mode_lower = mode.lower()
    if mode_lower == "us-equities-pre":
        start_ny, end_ny = "08:30:00", "09:30:00"
    elif mode_lower == "us-equities-post":
        start_ny, end_ny = "16:30:00", "17:30:00"
    elif mode_lower == "us-equities-overnight":
        start_ny, end_ny = "20:00:00", "21:00:00"
    else:
        start_ny, end_ny = "09:30:00", "10:30:00"

    def _ny_to_utc(t: str) -> str:
        dt = datetime.strptime(f"{date} {t}", "%Y-%m-%d %H:%M:%S")
        dt_ny = dt.replace(tzinfo=ZoneInfo("America/New_York"))
        dt_utc = dt_ny.astimezone(ZoneInfo("UTC"))
        return dt_utc.strftime("%H:%M:%S")

    return _ny_to_utc(start_ny), _ny_to_utc(end_ny)


def run_standalone(
    feed_id: str,
    date: str,
    mode: str,
    cluster: str,
    start_time: str,
    end_time: str,
    output_path: str,
    target_pub_count: int,
) -> bool:
    """Subprocess-call the engine for a single feed-day. True iff returncode == 0.

    Stdio is inherited from the parent so the engine's progress logs stream live.
    Any non-zero exit is treated as a soft failure: the caller continues to the
    next CSV row.
    """
    argv = [
        sys.executable,
        "-m",
        ENGINE_MODULE,
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
        output_path,
        "--target-pub-count",
        str(target_pub_count),
    ]
    print(f"  Executing engine for {feed_id} (mode: {mode}, cluster: {cluster})...")
    try:
        result = subprocess.run(argv, check=False)
    except Exception as e:
        print(f"  Error: Engine invocation raised for {feed_id}: {e}")
        return False
    if result.returncode == 0:
        print(f"  Engine execution successful for {feed_id}.")
        return True
    print(f"  Error: Engine execution failed for {feed_id} (exit {result.returncode}).")
    return False


def process_csv(
    csv_file: Path,
    cluster: str,
    start_time_override: str | None,
    end_time_override: str | None,
    output_path: str,
    target_pub_count: int,
) -> tuple[int, int, list[str]]:
    """Iterate the CSV and run the engine per row. Returns (succeeded, failed, failed_descriptors).

    failed_descriptors is a list like ["1021@2026-05-04", ...] for the end-of-run summary.
    Per-row failures never abort the batch.
    """
    succeeded = 0
    failed = 0
    failed_list: list[str] = []

    print("Starting batch processing of price_ids...")
    try:
        with open(csv_file, "r") as f:
            reader = csv_mod.reader(f)
            for row in reader:
                if not row or not row[0].strip():
                    continue
                if len(row) < 3:
                    print(f"  Warning: Skipping incomplete row: {row}")
                    continue

                feed_id = row[0].strip()
                date = row[1].strip()
                mode = row[2].strip()
                if not feed_id:
                    continue

                print(
                    f"--- Processing feed_id: {feed_id}, date: {date}, "
                    f"mode: {mode}, cluster: {cluster} ---"
                )

                if start_time_override and end_time_override:
                    start_time = start_time_override
                    end_time = end_time_override
                else:
                    start_time, end_time = compute_times_from_mode(date, mode)

                ok = run_standalone(
                    feed_id=feed_id,
                    date=date,
                    mode=mode,
                    cluster=cluster,
                    start_time=start_time,
                    end_time=end_time,
                    output_path=output_path,
                    target_pub_count=target_pub_count,
                )
                if ok:
                    succeeded += 1
                else:
                    failed += 1
                    failed_list.append(f"{feed_id}@{date}")
    except FileNotFoundError:
        print(f"Error: CSV file '{csv_file}' not found.")
        sys.exit(1)

    print("Batch processing complete.")
    return succeeded, failed, failed_list


def main():
    parser = argparse.ArgumentParser(
        description="Bulk DQ evaluation: subprocess-call evaluate_feed_standalone.py for each CSV row.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""\
Examples:
  python3 -m lazer_dq.evaluate_feeds_bulk --cluster lazer-prod
  python3 -m lazer_dq.evaluate_feeds_bulk --csv MV_Mario_1.csv --cluster lazer-prod
""",
    )
    parser.add_argument(
        "--csv",
        default="price_id_list.csv",
        help="CSV: feed_id,date,mode per row (default: price_id_list.csv)",
    )
    parser.add_argument(
        "--cluster", required=True, help="Cluster name (e.g. lazer-prod)"
    )
    parser.add_argument(
        "--start-time",
        default=None,
        help="Override start time HH:MM:SS UTC (default: per-row from mode)",
    )
    parser.add_argument(
        "--end-time",
        default=None,
        help="Override end time HH:MM:SS UTC (default: per-row from mode)",
    )
    parser.add_argument(
        "--output-path",
        default="dq_reports",
        help="Base output dir (default: dq_reports)",
    )
    parser.add_argument(
        "--target-pub-count",
        type=int,
        default=4,
        help="Target publisher count (default: 4)",
    )

    args = parser.parse_args()

    csv_path = Path(args.csv)
    if not csv_path.exists():
        print(f"Error: CSV file '{csv_path}' not found.")
        sys.exit(1)

    succeeded, failed, failed_list = process_csv(
        csv_file=csv_path,
        cluster=args.cluster,
        start_time_override=args.start_time,
        end_time_override=args.end_time,
        output_path=args.output_path,
        target_pub_count=args.target_pub_count,
    )

    total = succeeded + failed
    print(f"Processed {total} feeds: {succeeded} succeeded, {failed} failed.")
    if failed_list:
        print(f"Failed: {failed_list}")
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    main()
