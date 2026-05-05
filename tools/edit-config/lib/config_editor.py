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


from typing import Any

from lib.config_ops import (
    AddPublisher,
    RemovePublisher,
    SetMinPublishers,
    BumpMinPublishers,
    SetState,
)
from lib.config_selector import parse_selector_text, read_selector_file


@dataclass
class PlannedOp:
    op: Any  # one of the operation classes
    filters: FilterSet


_OP_FLAGS = (
    "add_publisher",
    "remove_publisher",
    "set_min_publishers",
    "bump_min_publishers",
    "set_state",
)


def _build_filters_from_args(args) -> FilterSet:
    feed_ids: set[int] | None = None
    if args.feed_id:
        feed_ids = parse_selector_text(args.feed_id)
    if args.feed_ids_from:
        from_file = read_selector_file(args.feed_ids_from)
        feed_ids = (feed_ids or set()) | from_file
    states = {args.state} if args.state else None
    f = FilterSet(
        feed_ids=feed_ids,
        symbol_pattern=args.symbol_pattern,
        asset_class=args.asset_class,
        states=states,
    )
    f.validate()
    return f


def _parse_signed_int(s: str) -> int:
    if not s:
        raise ValueError(f"empty bump value")
    if s[0] not in "+-" and not s.isdigit():
        raise ValueError(f"bump must be signed integer (+1 / -2); got {s!r}")
    return int(s)


def build_op_from_args(args) -> list[PlannedOp]:
    """Build a single-element PlannedOp list from argparse Namespace.

    Raises ValueError on missing/multiple operation flags, missing
    targeting, etc.
    """
    selected = [name for name in _OP_FLAGS if getattr(args, name) is not None]
    if not selected:
        raise ValueError(
            "no operation specified (use one of --add-publisher, "
            "--remove-publisher, --set-min-publishers, "
            "--bump-min-publishers, --set-state)"
        )
    if len(selected) > 1:
        raise ValueError(f"exactly one operation flag allowed; got {selected}")

    name = selected[0]
    filters = _build_filters_from_args(args)

    if name == "add_publisher":
        op = AddPublisher(publisher_id=args.add_publisher, session=args.session)
    elif name == "remove_publisher":
        op = RemovePublisher(publisher_id=args.remove_publisher, session=args.session)
    elif name == "set_min_publishers":
        op = SetMinPublishers(value=args.set_min_publishers, session=args.session)
    elif name == "bump_min_publishers":
        delta = _parse_signed_int(args.bump_min_publishers)
        op = BumpMinPublishers(delta=delta, session=args.session)
    elif name == "set_state":
        op = SetState(value=args.set_state)
    else:
        raise AssertionError(f"unhandled op {name}")

    return [PlannedOp(op=op, filters=filters)]
