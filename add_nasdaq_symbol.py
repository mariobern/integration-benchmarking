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
import re
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

_WHITESPACE_RE = re.compile(r"\s")


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
    a second run is a no-op. Skips a feed whose `metadata.name` contains
    whitespace, since every real exchange code/ticker observed in this
    config is a single whitespace-free token, while every name
    `rename_numeric_feed_names.py` produces is a multi-word company name --
    this catches the hazard of running against an already-renamed config.
    """
    feed_id = feed["feedId"]
    symbol = feed.get("symbol", "")
    metadata = feed.get("metadata", {})

    if "nasdaq_symbol" in metadata:
        return None, Skip(feed_id, symbol, "nasdaq_symbol already set")

    name = str(metadata.get("name", ""))
    if not name:
        return None, Skip(feed_id, symbol, "metadata.name is empty")

    if _WHITESPACE_RE.search(name):
        return None, Skip(
            feed_id,
            symbol,
            "metadata.name looks like a display name, not a code (contains whitespace)",
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
