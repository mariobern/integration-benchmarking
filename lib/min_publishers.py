"""
Enforce minimum minPublishers values in after.json based on publisher count.

Rule engine:
  0-1 publishers  -> NEEDS_ATTENTION (no change)
  2-4 publishers  -> no change (below floor)
  5-6 publishers  -> minPublishers = 2
  7+  publishers  -> minPublishers = 3

Boundaries configurable via floor and cutoff parameters.
"""

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
