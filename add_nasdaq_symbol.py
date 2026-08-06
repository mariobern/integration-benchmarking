#!/usr/bin/env python3
"""Backfill metadata.nasdaq_symbol for HK/CN/JP/KR/IN equity feeds.

These markets carry the exchange-facing identifier downstream users read
prices by in `metadata.name` -- a numeric code for HK/CN/JP/KR, or the raw
ticker for the few already-alphabetic names. `rename_numeric_feed_names.py`
later overwrites `metadata.name` with a human-readable company name, so this
script copies the original identifier into `metadata.nasdaq_symbol` first,
verbatim, while it still holds the original code.

See docs/superpowers/specs/2026-07-29-add-nasdaq-symbol-design.md.
"""

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path

from rename_numeric_feed_names import dump_config, in_scope, write_config

ASIAN_MARKET_PREFIXES = (
    "Equity.HK.",
    "Equity.CN.",
    "Equity.JP.",
    "Equity.KR.",
    "Equity.IN.",
)


def _symbol_code(symbol: str) -> str:
    """Extract the exchange code/ticker segment from `symbol`.

    E.g. 'Equity.HK.0002/HKD' -> '0002', 'Equity.JP.1321-JP/JPY' -> '1321-JP'.
    This segment is never touched by rename_numeric_feed_names.py, unlike
    metadata.name, so comparing against it is an exact check for whether a
    feed has already been renamed -- not a heuristic.
    """
    root = symbol.split("/", 1)[0]
    return root.rsplit(".", 1)[-1]


@dataclass(frozen=True)
class Change:
    """One planned `metadata.nasdaq_symbol` addition."""

    feed_id: int
    symbol: str
    name: str  # value to copy into nasdaq_symbol


@dataclass(frozen=True)
class Skip:
    """A feed that was not touched, with the reason why."""

    feed_id: int
    symbol: str
    reason: str


def plan_change(feed: dict) -> tuple[Change | None, Skip | None]:
    """Decide what to do with one in-scope feed.

    Skips (never overwrites) a feed that already has `nasdaq_symbol` set, so
    a second run is a no-op. Compares metadata.name against the code embedded
    in symbol, which rename_numeric_feed_names.py never touches -- an exact
    check for whether this feed has already been renamed, rather than a
    heuristic. A mismatch (not just a name containing whitespace) triggers
    the skip, since some already-renamed display names are a single word
    (e.g. `HITACHI`, `CNOOC`) and would slip past a whitespace-only check.
    """
    feed_id = feed["feedId"]
    symbol = feed.get("symbol", "")
    metadata = feed.get("metadata", {})

    if "nasdaq_symbol" in metadata:
        return None, Skip(feed_id, symbol, "nasdaq_symbol already set")

    name = str(metadata.get("name") or "")
    if not name:
        return None, Skip(feed_id, symbol, "metadata.name is empty")

    code = _symbol_code(symbol)
    if name != code:
        return None, Skip(
            feed_id,
            symbol,
            f"metadata.name {name!r} does not match symbol code {code!r} (already renamed?)",
        )

    return Change(feed_id, symbol, name), None


def build_changes(
    feeds: list[dict], prefixes: tuple[str, ...] = ASIAN_MARKET_PREFIXES
) -> tuple[list[Change], list[Skip]]:
    """Plan the nasdaq_symbol backfill over every in-scope feed."""
    changes: list[Change] = []
    skips: list[Skip] = []
    for feed in feeds:
        if not in_scope(feed, prefixes):
            continue
        change, skip = plan_change(feed)
        if change is not None:
            changes.append(change)
        if skip is not None:
            skips.append(skip)
    return changes, skips


def _with_sorted_keys(metadata: dict, key: str, value: str) -> dict:
    """Return a new dict with `key` set to `value`, all keys alphabetically sorted.

    Every metadata dict in this config is already alphabetically sorted (verified
    against both HK and US-equity feeds), and on US feeds `nasdaq_symbol` already
    sits between `name` and `quote_currency`. This keeps newly-touched feeds
    consistent with that existing convention instead of appending the new key
    at the end via plain dict assignment.
    """
    merged = {**metadata, key: value}
    return dict(sorted(merged.items()))


def apply_changes(data: dict, changes: list[Change]) -> None:
    """Write the planned nasdaq_symbol values into the in-memory document."""
    by_id = {f["feedId"]: f for f in data["feeds"]}
    for change in changes:
        feed = by_id[change.feed_id]
        feed["metadata"] = _with_sorted_keys(
            feed["metadata"], "nasdaq_symbol", change.name
        )


class VerificationError(Exception):
    """Raised when the rewritten config differs in unexpected ways."""


def verify_feed_metadata(
    before_data: dict, after_data: dict, changes: list[Change]
) -> None:
    """Raise VerificationError unless exactly the planned nasdaq_symbol values changed.

    Confirms every feed outside the change set has a byte-identical `metadata`
    dict to before (no leak beyond the plan), and every feed in the change set
    gained exactly the planned `nasdaq_symbol` value with every other field
    unchanged.
    """
    before_by_id = {f["feedId"]: f for f in before_data["feeds"]}
    after_by_id = {f["feedId"]: f for f in after_data["feeds"]}
    if before_by_id.keys() != after_by_id.keys():
        raise VerificationError("feed id set changed")

    planned = {c.feed_id: c.name for c in changes}
    for feed_id, before_feed in before_by_id.items():
        before_metadata = before_feed.get("metadata", {})
        after_metadata = after_by_id[feed_id].get("metadata", {})

        if feed_id not in planned:
            if before_metadata != after_metadata:
                raise VerificationError(
                    f"feed {feed_id} metadata changed but had no planned change: "
                    f"before={before_metadata}, after={after_metadata}"
                )
            continue

        expected = dict(
            sorted({**before_metadata, "nasdaq_symbol": planned[feed_id]}.items())
        )
        if after_metadata != expected:
            raise VerificationError(
                f"feed {feed_id} metadata does not match the plan: "
                f"expected={expected}, actual={after_metadata}"
            )


def verify_on_disk(path: Path, before_text: str, changes: list[Change]) -> None:
    """Re-read the written config and confirm it parses and changed only as planned."""
    after_text = path.read_text(encoding="utf-8")
    try:
        after_data = json.loads(after_text)
    except json.JSONDecodeError as exc:
        raise VerificationError(f"written config does not parse: {exc}") from exc
    before_data = json.loads(before_text)
    if len(after_data["feeds"]) != len(before_data["feeds"]):
        raise VerificationError(
            f"feed count changed: {len(before_data['feeds'])} -> {len(after_data['feeds'])}"
        )
    verify_feed_metadata(before_data, after_data, changes)


def print_report(changes: list[Change], skips: list[Skip]) -> None:
    """Print the change table, skip list, and summary."""
    if changes:
        width = max(len(c.symbol) for c in changes)
        print(f"\nChanges ({len(changes)}):")
        for change in changes:
            print(
                f"  {change.feed_id:5d}  {change.symbol:<{width}}  "
                f"nasdaq_symbol -> {change.name!r}"
            )
    if skips:
        print(f"\nSkipped ({len(skips)}):")
        for skip in skips:
            print(f"  {skip.feed_id:5d}  {skip.symbol}  {skip.reason}")
    print(f"\nSummary: {len(changes)} change(s), {len(skips)} skip(s).")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="Path to the config")
    parser.add_argument(
        "--symbol-prefix",
        action="append",
        dest="symbol_prefixes",
        help=(
            "Symbol namespace to process; repeatable. Defaults to "
            f"{', '.join(ASIAN_MARKET_PREFIXES)}"
        ),
    )
    parser.add_argument("--apply", action="store_true", help="Write changes")
    parser.add_argument("--no-backup", action="store_true", help="Skip the .bak copy")
    args = parser.parse_args(argv)

    prefixes = (
        tuple(args.symbol_prefixes) if args.symbol_prefixes else ASIAN_MARKET_PREFIXES
    )

    if not args.config.exists():
        print(f"ERROR: Config file not found: {args.config}", file=sys.stderr)
        return 1

    before_text = args.config.read_text(encoding="utf-8")
    data = json.loads(before_text)
    feeds = data["feeds"]
    print(f"Reading {args.config} ({len(feeds)} feeds)...")

    changes, skips = build_changes(feeds, prefixes)
    print_report(changes, skips)

    if not changes:
        print("\nNo changes. Nothing to do.")
        return 0

    apply_changes(data, changes)
    trailing = before_text[len(before_text.rstrip("\n")) :]
    after_text = dump_config(data) + trailing

    # Verification runs before the write, so a dry run catches problems too.
    try:
        verify_feed_metadata(json.loads(before_text), data, changes)
    except VerificationError as exc:
        print(f"\nERROR: verification failed: {exc}", file=sys.stderr)
        return 1

    if not args.apply:
        print("\n[DRY RUN] No changes written. Re-run with --apply to write.")
        return 0

    write_config(args.config, after_text, backup=not args.no_backup)
    try:
        verify_on_disk(args.config, before_text, changes)
    except VerificationError as exc:
        print(f"\nERROR: post-write verification failed: {exc}", file=sys.stderr)
        return 1
    print(f"\nWrote {len(changes)} change(s) to {args.config}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
