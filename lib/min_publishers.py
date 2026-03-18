"""
Enforce minimum minPublishers values in after.json based on publisher count.

Rule engine:
  0-1 publishers  -> NEEDS_ATTENTION (no change)
  2-4 publishers  -> no change (below floor)
  5-6 publishers  -> minPublishers = 2
  7+  publishers  -> minPublishers = 3

Boundaries configurable via floor and cutoff parameters.
"""

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
