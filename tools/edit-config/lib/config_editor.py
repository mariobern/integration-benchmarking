"""Orchestrator: parse spec, resolve targets, simulate, apply."""

import fnmatch
from dataclasses import dataclass, field


@dataclass
class FilterSet:
    feed_ids: set[int] | None = None
    symbol_pattern: str | None = None
    asset_class: str | None = None
    states: set[str] | None = None  # plural — supports YAML list

    def validate(self) -> None:
        if not any((self.feed_ids, self.symbol_pattern, self.asset_class, self.states)):
            raise ValueError(
                "at least one targeting filter is required "
                "(feed_id/feed-ids-from, symbol_pattern, asset_class, or state)"
            )

    def matches(self, feed: dict) -> bool:
        if self.feed_ids is not None and feed["feedId"] not in self.feed_ids:
            return False
        if self.symbol_pattern is not None:
            symbol = feed.get("symbol", "")
            if not fnmatch.fnmatchcase(symbol, self.symbol_pattern):
                return False
        if self.asset_class is not None:
            asset = feed.get("metadata", {}).get("asset_type", "")
            if asset != self.asset_class:
                return False
        if self.states is not None and feed.get("state") not in self.states:
            return False
        return True


def resolve_targets(filters: FilterSet, feeds: list[dict]) -> list[dict]:
    """Return the subset of feeds matching all filters (AND)."""
    return [f for f in feeds if filters.matches(f)]
