"""
Enforce minimum minPublishers values in after.json based on publisher count.

Usage:
    python3 update_min_publishers.py --config after.json --dry-run
    python3 update_min_publishers.py --config after.json --output-csv changes.csv
    python3 update_min_publishers.py --config after.json --asset-classes fx commodity
"""

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from lib.min_publishers import (
    DEFAULT_CUTOFF,
    DEFAULT_EXCLUDED_ASSET_TYPES,
    DEFAULT_FLOOR,
    is_extended_hours,
    modify_config,
    print_summary,
    write_csv_report,
)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Enforce minimum minPublishers values in after.json"
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to after.json config file",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview changes without writing to file",
    )
    parser.add_argument(
        "--output-csv",
        default="min_publishers_changes.csv",
        help="Path for the change report CSV (default: min_publishers_changes.csv)",
    )
    parser.add_argument(
        "--asset-classes",
        nargs="+",
        default=None,
        help="Explicit allowlist of asset types to process (overrides default exclusions)",
    )
    parser.add_argument(
        "--min-publisher-floor",
        type=int,
        default=DEFAULT_FLOOR,
        help=f"Minimum publisher count to start enforcing (default: {DEFAULT_FLOOR})",
    )
    parser.add_argument(
        "--publisher-tier-cutoff",
        type=int,
        default=DEFAULT_CUTOFF,
        help=f"Publisher count boundary for tier 2 vs tier 3 (default: {DEFAULT_CUTOFF})",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"ERROR: Config file not found: {config_path}")
        sys.exit(1)

    # Load feeds for stats computation
    with open(config_path) as f:
        data = json.load(f)

    feeds = data["feeds"]

    # Compute stats for console output
    stable_feeds = [f for f in feeds if f.get("state") == "STABLE"]
    stable_count = len(stable_feeds)

    excluded_type_breakdown: Counter[str] = Counter()
    excluded_extended_count = 0
    for feed in stable_feeds:
        asset_type = feed.get("metadata", {}).get("asset_type", "")
        if args.asset_classes is not None:
            if asset_type not in args.asset_classes:
                excluded_type_breakdown[asset_type] += 1
        elif asset_type in DEFAULT_EXCLUDED_ASSET_TYPES:
            excluded_type_breakdown[asset_type] += 1

    for feed in stable_feeds:
        asset_type = feed.get("metadata", {}).get("asset_type", "")
        if args.asset_classes is not None:
            if asset_type not in args.asset_classes:
                continue
        elif asset_type in DEFAULT_EXCLUDED_ASSET_TYPES:
            continue
        if is_extended_hours(feed):
            excluded_extended_count += 1

    stats = {
        "stable_count": stable_count,
        "excluded_type_count": sum(excluded_type_breakdown.values()),
        "excluded_type_breakdown": dict(excluded_type_breakdown),
        "excluded_extended_count": excluded_extended_count,
    }

    # Run modify_config (handles evaluate + apply)
    result = modify_config(
        str(config_path),
        dry_run=args.dry_run,
        floor=args.min_publisher_floor,
        cutoff=args.publisher_tier_cutoff,
        asset_classes=args.asset_classes,
    )

    changes = result["changes"]

    # Print summary
    print_summary(changes, stats, dry_run=args.dry_run)

    # Write CSV report
    write_csv_report(changes, args.output_csv)
    print(f"Report: {args.output_csv}")

    if not args.dry_run and result["updated"] > 0:
        print(f"Backup: {args.config}.bak")
        print(f"Updated {result['updated']} feeds in {args.config}")


if __name__ == "__main__":
    main()
