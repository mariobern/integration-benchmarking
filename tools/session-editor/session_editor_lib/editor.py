"""Plan → simulate → render → apply orchestrator for session edits."""

from __future__ import annotations

import copy
import fnmatch
from dataclasses import dataclass, field
from typing import Any, Iterable

from .feed_filter import is_us_equity
from .ops import AddSession, OpOutcome, RemoveSession


Op = AddSession | RemoveSession


@dataclass
class PlanItem:
    op: Op
    feed_ids: set[int] | None = None  # None means "all eligible"
    symbol_pattern: str | None = None
    state: str | None = None
    force_non_us: bool = False


@dataclass
class SimulationResult:
    after_feeds: list[dict[str, Any]]
    outcomes: list[list[OpOutcome]] = field(default_factory=list)

    @property
    def changed_count(self) -> int:
        seen: set[int] = set()
        for op_outcomes in self.outcomes:
            for o in op_outcomes:
                if o.action in ("added", "removed"):
                    seen.add(o.feed_id)
        return len(seen)


def _feed_matches(feed: dict, item: PlanItem) -> bool:
    fid = feed.get("feedId")
    if item.feed_ids is not None and fid not in item.feed_ids:
        return False
    if item.symbol_pattern and not fnmatch.fnmatchcase(
        feed.get("symbol", ""), item.symbol_pattern
    ):
        return False
    if item.state and feed.get("state") != item.state:
        return False
    if not item.force_non_us and not is_us_equity(feed):
        # Defense in depth: ops also enforce this, but pre-filtering saves
        # noisy "skipped" outcomes when targeting by feed-id range.
        return False
    return True


def simulate(plan: Iterable[PlanItem], feeds: list[dict]) -> SimulationResult:
    after = copy.deepcopy(feeds)
    outcomes: list[list[OpOutcome]] = []
    for item in plan:
        op_outcomes: list[OpOutcome] = []
        for feed in after:
            if not _feed_matches(feed, item):
                continue
            op_outcomes.append(item.op.apply(feed))
        outcomes.append(op_outcomes)
    return SimulationResult(after_feeds=after, outcomes=outcomes)
