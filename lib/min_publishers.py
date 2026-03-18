"""
Enforce minimum minPublishers values in after.json based on publisher count.

Rule engine:
  0-1 publishers  -> NEEDS_ATTENTION (no change)
  2-4 publishers  -> no change (below floor)
  5-6 publishers  -> minPublishers = 2
  7+  publishers  -> minPublishers = 3

Boundaries configurable via floor and cutoff parameters.
"""

import csv as csv_module
import re
from collections import Counter
from dataclasses import dataclass

# Default exclusion list: non-benchmarkable asset types
DEFAULT_EXCLUDED_ASSET_TYPES = frozenset(
    {
        "funding-rate",
        "crypto-redemption-rate",
        "nav",
        "custom",
        "crypto-index",
        "kalshi",
    }
)

# Extended session names that indicate extended-hours equities
_EXTENDED_SESSIONS = frozenset({"PRE_MARKET", "POST_MARKET", "OVER_NIGHT"})

# Default thresholds
DEFAULT_FLOOR = 5
DEFAULT_CUTOFF = 7


def compute_target_min_publishers(
    publisher_count: int,
    floor: int = DEFAULT_FLOOR,
    cutoff: int = DEFAULT_CUTOFF,
) -> int | None:
    """Compute target minPublishers based on publisher count.

    Returns target value, or None if no change should be made
    (publisher count below floor or needs attention).
    """
    if publisher_count < floor:
        return None
    if publisher_count < cutoff:
        return 2
    return 3


@dataclass
class FeedChange:
    """Represents the evaluation result for a single feed."""

    feed_id: int
    symbol: str
    asset_type: str
    old_min_publishers: int
    new_min_publishers: int | None
    allowed_publisher_count: int
    status: str  # UPDATED, SKIPPED_LOW_PUBLISHERS, SKIPPED_EQUAL, SKIPPED_HIGHER, NEEDS_ATTENTION


def is_extended_hours(feed: dict) -> bool:
    """Check if a feed has extended-hours sessions (PRE_MARKET/POST_MARKET/OVER_NIGHT)."""
    for schedule in feed.get("marketSchedules", []):
        if schedule.get("session") in _EXTENDED_SESSIONS:
            return True
    return False


def evaluate_feeds(
    feeds: list[dict],
    floor: int = DEFAULT_FLOOR,
    cutoff: int = DEFAULT_CUTOFF,
    asset_classes: list[str] | None = None,
    excluded_asset_types: frozenset[str] = DEFAULT_EXCLUDED_ASSET_TYPES,
) -> list[FeedChange]:
    """Evaluate all feeds and return list of FeedChange results.

    Only processes STABLE, non-extended, non-excluded feeds.
    Returns results for feeds that pass eligibility (including skips).
    """
    changes: list[FeedChange] = []

    for feed in feeds:
        # Filter: state
        if feed.get("state") != "STABLE":
            continue

        # Filter: asset type
        asset_type = feed.get("metadata", {}).get("asset_type", "")
        if asset_classes is not None:
            if asset_type not in asset_classes:
                continue
        elif asset_type in excluded_asset_types:
            continue

        # Filter: extended-hours
        if is_extended_hours(feed):
            continue

        feed_id = feed["feedId"]
        symbol = feed.get("symbol", "")
        old_min = feed.get("minPublishers", 0)
        pub_ids = feed.get("allowedPublisherIds", [])
        pub_count = len(pub_ids)

        # NEEDS_ATTENTION: <2 publishers
        if pub_count < 2:
            changes.append(
                FeedChange(
                    feed_id=feed_id,
                    symbol=symbol,
                    asset_type=asset_type,
                    old_min_publishers=old_min,
                    new_min_publishers=None,
                    allowed_publisher_count=pub_count,
                    status="NEEDS_ATTENTION",
                )
            )
            continue

        target = compute_target_min_publishers(pub_count, floor=floor, cutoff=cutoff)

        # Below floor: SKIPPED_LOW_PUBLISHERS
        if target is None:
            changes.append(
                FeedChange(
                    feed_id=feed_id,
                    symbol=symbol,
                    asset_type=asset_type,
                    old_min_publishers=old_min,
                    new_min_publishers=None,
                    allowed_publisher_count=pub_count,
                    status="SKIPPED_LOW_PUBLISHERS",
                )
            )
            continue

        # No-downgrade comparison
        if old_min > target:
            status = "SKIPPED_HIGHER"
            new_min = None
        elif old_min == target:
            status = "SKIPPED_EQUAL"
            new_min = None
        else:
            status = "UPDATED"
            new_min = target

        changes.append(
            FeedChange(
                feed_id=feed_id,
                symbol=symbol,
                asset_type=asset_type,
                old_min_publishers=old_min,
                new_min_publishers=new_min,
                allowed_publisher_count=pub_count,
                status=status,
            )
        )

    return changes


def _find_feed_block(raw: str, feed_id: int) -> tuple[int, int] | None:
    """Find the start/end positions of a feed entry by feedId in the raw JSON.

    Uses the same algorithm as update_config_from_summary.py and
    update_lazer_symbols.py: regex match on feedId, then bracket-depth
    scanning with string-awareness.
    """
    pattern = rf'"feedId":\s*{feed_id}\s*[,\n}}]'
    match = re.search(pattern, raw)
    if not match:
        return None

    pos = match.start()

    # Scan backward for opening {
    depth = 0
    start = pos - 1
    while start >= 0:
        c = raw[start]
        if c == '"':
            start -= 1
            while start >= 0 and raw[start] != '"':
                if raw[start] == "\\" and start > 0:
                    start -= 1
                start -= 1
        elif c == "}":
            depth += 1
        elif c == "{":
            if depth == 0:
                break
            depth -= 1
        start -= 1

    # Scan forward for matching }
    depth = 1
    end = start + 1
    in_string = False
    while end < len(raw) and depth > 0:
        c = raw[end]
        if c == '"' and (end == 0 or raw[end - 1] != "\\"):
            in_string = not in_string
        elif not in_string:
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
        end += 1

    return (start, end)


def _find_market_schedules_end(block: str) -> int | None:
    """Find the position after the closing ] of marketSchedules in a feed block.

    Returns the index immediately after the ']' that closes the
    marketSchedules array, or None if no marketSchedules key exists.
    """
    ms_match = re.search(r'"marketSchedules":\s*\[', block)
    if not ms_match:
        return None

    pos = ms_match.end()
    depth = 1
    in_string = False
    while pos < len(block) and depth > 0:
        c = block[pos]
        if c == '"' and (pos == 0 or block[pos - 1] != "\\"):
            in_string = not in_string
        elif not in_string:
            if c == "[":
                depth += 1
            elif c == "]":
                depth -= 1
        pos += 1

    return pos  # position right after closing ]


def modify_config(
    config_path: str,
    dry_run: bool = False,
    floor: int = DEFAULT_FLOOR,
    cutoff: int = DEFAULT_CUTOFF,
    asset_classes: list[str] | None = None,
    excluded_asset_types: frozenset[str] = DEFAULT_EXCLUDED_ASSET_TYPES,
) -> dict:
    """Evaluate feeds and apply minPublishers changes to config file.

    Returns summary dict with counts and change list.
    """
    import json
    import shutil

    with open(config_path) as f:
        raw = f.read()

    data = json.loads(raw)
    feeds = data["feeds"]

    # Evaluate all feeds
    changes = evaluate_feeds(
        feeds,
        floor=floor,
        cutoff=cutoff,
        asset_classes=asset_classes,
        excluded_asset_types=excluded_asset_types,
    )

    # Apply UPDATED changes to raw JSON
    updates_to_apply = [c for c in changes if c.status == "UPDATED"]

    for change in updates_to_apply:
        bounds = _find_feed_block(raw, change.feed_id)
        if not bounds:
            continue

        start, end = bounds
        block = raw[start:end]

        # Find where marketSchedules ends to target top-level minPublishers
        ms_end = _find_market_schedules_end(block)
        if ms_end is not None:
            # Only apply regex to text after marketSchedules
            before = block[:ms_end]
            after = block[ms_end:]
            after = re.sub(
                r'"minPublishers": \d+',
                f'"minPublishers": {change.new_min_publishers}',
                after,
                count=1,
            )
            block = before + after
        else:
            # No marketSchedules — apply to entire block
            block = re.sub(
                r'"minPublishers": \d+',
                f'"minPublishers": {change.new_min_publishers}',
                block,
                count=1,
            )

        raw = raw[:start] + block + raw[end:]

    # Write if not dry run and there are changes
    if not dry_run and updates_to_apply:
        backup_path = config_path + ".bak"
        shutil.copy2(config_path, backup_path)
        with open(config_path, "w") as f:
            f.write(raw)

    # Build summary
    return {
        "updated": sum(1 for c in changes if c.status == "UPDATED"),
        "skipped_low_publishers": sum(
            1 for c in changes if c.status == "SKIPPED_LOW_PUBLISHERS"
        ),
        "skipped_equal": sum(1 for c in changes if c.status == "SKIPPED_EQUAL"),
        "skipped_higher": sum(1 for c in changes if c.status == "SKIPPED_HIGHER"),
        "needs_attention": sum(1 for c in changes if c.status == "NEEDS_ATTENTION"),
        "changes": changes,
    }


def write_csv_report(changes: list[FeedChange], output_path: str) -> None:
    """Write the change report CSV."""
    fieldnames = [
        "feed_id",
        "symbol",
        "asset_type",
        "old_min_publishers",
        "new_min_publishers",
        "allowed_publisher_count",
        "status",
    ]
    with open(output_path, "w", newline="") as f:
        writer = csv_module.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for change in changes:
            writer.writerow(
                {
                    "feed_id": change.feed_id,
                    "symbol": change.symbol,
                    "asset_type": change.asset_type,
                    "old_min_publishers": change.old_min_publishers,
                    "new_min_publishers": (
                        change.new_min_publishers
                        if change.new_min_publishers is not None
                        else ""
                    ),
                    "allowed_publisher_count": change.allowed_publisher_count,
                    "status": change.status,
                }
            )


def print_summary(
    changes: list[FeedChange],
    stats: dict,
    dry_run: bool = False,
) -> None:
    """Print human-readable summary to console."""
    print("Scanning after.json...")
    print(f"  STABLE feeds: {stats['stable_count']}")

    # Excluded by type
    exc_type = stats["excluded_type_count"]
    breakdown = stats["excluded_type_breakdown"]
    if breakdown:
        parts = ", ".join(f"{k}: {v}" for k, v in sorted(breakdown.items()))
        print(f"  Excluded (asset type): {exc_type} ({parts})")
    else:
        print(f"  Excluded (asset type): {exc_type}")

    print(f"  Excluded (extended-hours): {stats['excluded_extended_count']}")

    # Count statuses
    needs_attention = [c for c in changes if c.status == "NEEDS_ATTENTION"]
    low_pub = [c for c in changes if c.status == "SKIPPED_LOW_PUBLISHERS"]
    updated = [c for c in changes if c.status == "UPDATED"]
    skipped = [c for c in changes if c.status in ("SKIPPED_EQUAL", "SKIPPED_HIGHER")]

    print(f"  Needs attention (<2 publishers): {len(needs_attention)}")
    if needs_attention:
        for c in needs_attention:
            print(
                f"    - {c.symbol} (feedId={c.feed_id},"
                f" publishers={c.allowed_publisher_count})"
            )

    print(f"  Skipped (2-4 publishers): {len(low_pub)}")
    eligible = len(updated) + len(skipped)
    print(f"  Eligible for rule evaluation: {eligible}")

    print()
    print("Changes:")

    # Group updates by transition
    transitions: Counter[str] = Counter()
    for c in updated:
        key = f"{c.old_min_publishers} -> {c.new_min_publishers}"
        transitions[key] += 1

    for transition, count in sorted(transitions.items()):
        print(f"  {count} feeds: minPublishers {transition}")

    print(f"  {len(skipped)} feeds: skipped (already >= target)")

    if dry_run:
        print()
        print("[DRY RUN] No changes written.")
