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


import yaml


_OP_REQUIRED_FIELDS = {
    "add_publisher": {"publisher_id"},
    "remove_publisher": {"publisher_id"},
    "set_min_publishers": {"value"},
    "bump_min_publishers": {"delta"},
    "set_state": {"value"},
}

_TARGETING_KEYS = {
    "feed_id",
    "symbol_pattern",
    "asset_class",
    "state",
}

_SCOPE_KEYS = {"session"}


def _parse_feed_id_field(value) -> set[int]:
    """Accept int, range-string, or list of int/range-strings."""
    if isinstance(value, int):
        return {value}
    if isinstance(value, str):
        return parse_selector_text(value)
    if isinstance(value, list):
        ids: set[int] = set()
        for item in value:
            if isinstance(item, int):
                ids.add(item)
            elif isinstance(item, str):
                ids.update(parse_selector_text(item))
            else:
                raise ValueError(
                    f"feed_id list entries must be int or range-string; got {item!r}"
                )
        return ids
    raise ValueError(
        f"feed_id must be int, range-string, or list; got {type(value).__name__}"
    )


def _filters_from_yaml_entry(entry: dict) -> FilterSet:
    feed_ids: set[int] | None = None
    if "feed_id" in entry:
        feed_ids = _parse_feed_id_field(entry["feed_id"])
    states_raw = entry.get("state")
    if isinstance(states_raw, str):
        states = {states_raw}
    elif isinstance(states_raw, list):
        states = set(states_raw)
    elif states_raw is None:
        states = None
    else:
        raise ValueError(
            f"state must be string or list; got {type(states_raw).__name__}"
        )
    f = FilterSet(
        feed_ids=feed_ids,
        symbol_pattern=entry.get("symbol_pattern"),
        asset_class=entry.get("asset_class"),
        states=states,
    )
    f.validate()
    return f


def _validate_keys(entry: dict, op_name: str) -> None:
    allowed = {"op"} | _TARGETING_KEYS | _SCOPE_KEYS | _OP_REQUIRED_FIELDS[op_name]
    extras = set(entry.keys()) - allowed
    if extras:
        raise ValueError(f"unknown key(s) in op {op_name!r}: {sorted(extras)}")


def _build_op_from_yaml_entry(entry: dict):
    op_name = entry["op"]
    if op_name not in _OP_REQUIRED_FIELDS:
        raise ValueError(f"unknown op {op_name!r}")
    missing = _OP_REQUIRED_FIELDS[op_name] - set(entry.keys())
    if missing:
        raise ValueError(f"op {op_name!r} missing required field(s): {sorted(missing)}")
    _validate_keys(entry, op_name)

    session = entry.get("session")

    if op_name == "add_publisher":
        return AddPublisher(publisher_id=entry["publisher_id"], session=session)
    if op_name == "remove_publisher":
        return RemovePublisher(publisher_id=entry["publisher_id"], session=session)
    if op_name == "set_min_publishers":
        return SetMinPublishers(value=entry["value"], session=session)
    if op_name == "bump_min_publishers":
        return BumpMinPublishers(delta=entry["delta"], session=session)
    if op_name == "set_state":
        return SetState(value=entry["value"])
    raise AssertionError(f"unhandled op {op_name}")


def parse_yaml_spec(path: str) -> list[PlannedOp]:
    """Load a YAML spec file and produce a list of PlannedOp."""
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    if not isinstance(data, dict):
        raise ValueError("YAML root must be a mapping")
    version = data.get("version", 1)
    if not isinstance(version, int) or version > 1:
        raise ValueError(f"unsupported spec version {version!r}")
    if "operations" not in data or not isinstance(data["operations"], list):
        raise ValueError("YAML spec must contain a top-level `operations` list")

    planned: list[PlannedOp] = []
    for i, entry in enumerate(data["operations"]):
        if not isinstance(entry, dict):
            raise ValueError(f"operation #{i + 1}: must be a mapping")
        if "op" not in entry:
            raise ValueError(f"operation #{i + 1}: missing 'op' field")
        op = _build_op_from_yaml_entry(entry)
        filters = _filters_from_yaml_entry(entry)
        planned.append(PlannedOp(op=op, filters=filters))

    return planned


from copy import deepcopy

from lib.config_ops import Change, OpError, Warning


@dataclass
class SimulationResult:
    plan: list["PlannedOp"]
    matched_counts: list[int]  # one per op
    changes: list[Change]
    warnings: list[Warning]
    errors: list[str]
    simulated_feeds: list[dict]  # working copy after all ops; useful for tests


def simulate_plan(plan: list[PlannedOp], feeds: list[dict]) -> SimulationResult:
    """Apply each op against a working copy and collect results.

    Operations are applied in spec order; later ops see earlier ops'
    effects. Errors do not stop simulation — they're collected so the
    user sees every problem in one pass.
    """
    work = deepcopy(feeds)
    all_changes: list[Change] = []
    all_warnings: list[Warning] = []
    all_errors: list[str] = []
    matched_counts: list[int] = []

    for idx, planned in enumerate(plan, start=1):
        targets = resolve_targets(planned.filters, work)
        matched_counts.append(len(targets))
        if not targets:
            all_errors.append(
                f"operation #{idx} ({type(planned.op).__name__}): "
                f"no feeds matched the filter"
            )
            continue
        for feed in targets:
            try:
                changes, warns = planned.op.apply(feed)
            except OpError as e:
                all_errors.append(f"operation #{idx} feed {feed['feedId']}: {e}")
                continue
            all_changes.extend(changes)
            all_warnings.extend(warns)

    return SimulationResult(
        plan=plan,
        matched_counts=matched_counts,
        changes=all_changes,
        warnings=all_warnings,
        errors=all_errors,
        simulated_feeds=work,
    )


from collections import defaultdict

from lib.config_text_surgery import (
    find_feed_block,
    find_session_block,
    find_publisher_array_span,
    find_int_field_span,
    find_string_field_span,
    find_matching_close,
)


def _format_publisher_list(ids: list[int]) -> str:
    if not ids:
        return "[ ]"
    return "[ " + ", ".join(str(i) for i in ids) + " ]"


def _apply_changes_to_feed_block(block: str, changes: list[Change]) -> str:
    """Apply all changes for a single feed to its raw text block.

    Strategy: collect (start, end, replacement) tuples relative to the
    feed block, sort by descending start offset, splice them in order
    so prior splices don't shift later offsets.
    """
    edits: list[tuple[int, int, str]] = []

    # Compute marketSchedules array span up-front (used to scope top-level int
    # field lookups so we don't accidentally hit a session's minPublishers).
    ms_match = None
    ms_idx = block.find('"marketSchedules":')
    if ms_idx >= 0:
        ms_open = block.find("[", ms_idx)
        if ms_open >= 0:
            ms_close = find_matching_close(block, ms_open)
            if ms_close is not None:
                ms_match = (ms_open, ms_close + 1)

    for change in changes:
        if change.location == "top_level":
            scope_block, scope_offset = block, 0
            # For top-level int fields, scope the lookup to the tail after marketSchedules.
            if change.field == "minPublishers" and ms_match is not None:
                tail_start = ms_match[1]
                scope_block = block[tail_start:]
                scope_offset = tail_start
        else:
            sb = find_session_block(block, change.location)
            if sb is None:
                raise RuntimeError(
                    f"session block {change.location!r} not found in feed block"
                )
            scope_block = block[sb[0] : sb[1]]
            scope_offset = sb[0]

        if change.field == "allowedPublisherIds":
            span = find_publisher_array_span(scope_block)
            if span is None:
                raise RuntimeError(
                    f"allowedPublisherIds not found in {change.location}"
                )
            replacement = _format_publisher_list(change.after)
        elif change.field == "minPublishers":
            span = find_int_field_span(scope_block, "minPublishers")
            if span is None:
                raise RuntimeError(f"minPublishers not found in {change.location}")
            replacement = str(change.after)
        elif change.field == "state":
            span = find_string_field_span(scope_block, "state")
            if span is None:
                raise RuntimeError(f"state field not found in {change.location}")
            replacement = f'"{change.after}"'
        else:
            raise RuntimeError(f"unsupported field {change.field!r}")

        abs_start = scope_offset + span[0]
        abs_end = scope_offset + span[1]
        edits.append((abs_start, abs_end, replacement))

    # Apply in reverse offset order so earlier spans aren't disturbed.
    for start, end, replacement in sorted(edits, key=lambda e: -e[0]):
        block = block[:start] + replacement + block[end:]
    return block


def apply_changes(raw: str, changes: list[Change]) -> str:
    """Apply all changes to the raw JSON text, preserving formatting.

    Groups changes by feedId, locates each feed block once, applies all
    changes for that feed, then splices back. This avoids byte-offset
    drift across the larger document.
    """
    if not changes:
        return raw

    by_feed: dict[int, list[Change]] = defaultdict(list)
    for c in changes:
        by_feed[c.feed_id].append(c)

    # Apply per-feed in reverse feedId-block order so absolute offsets are stable.
    feed_bounds = {}
    for feed_id in by_feed:
        bounds = find_feed_block(raw, feed_id)
        if bounds is None:
            raise RuntimeError(f"feed {feed_id} not found in raw text")
        feed_bounds[feed_id] = bounds

    for feed_id in sorted(by_feed.keys(), key=lambda fid: -feed_bounds[fid][0]):
        start, end = feed_bounds[feed_id]
        block = raw[start:end]
        new_block = _apply_changes_to_feed_block(block, by_feed[feed_id])
        raw = raw[:start] + new_block + raw[end:]

    return raw


import shutil
import subprocess
from pathlib import Path


_LINTER_PATH = str(
    Path(__file__).resolve().parents[3] / "tools" / "config-linter" / "config_linter.py"
)


def write_with_backup(path: str, new_text: str, no_backup: bool = False) -> None:
    """Write `new_text` to `path`, optionally writing a `.bak` copy first."""
    target = Path(path)
    if not no_backup:
        backup = target.with_suffix(target.suffix + ".bak")
        if target.exists():
            shutil.copy2(target, backup)
    target.write_text(new_text, encoding="utf-8")


def run_linter(config_path: str) -> tuple[int, str]:
    """Run tools/config-linter on `config_path`. Returns (rc, output)."""
    if not Path(_LINTER_PATH).exists():
        return 1, f"linter script not found at {_LINTER_PATH}"
    try:
        proc = subprocess.run(
            ["python3", _LINTER_PATH, "--config", config_path],
            capture_output=True,
            text=True,
            check=False,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return 1, "linter timed out"
    return proc.returncode, proc.stdout + proc.stderr
