#!/usr/bin/env python3
"""Replace numeric metadata.name values with human-readable company names.

Equities listed in Hong Kong, Japan, South Korea and mainland China carry a
purely numeric `metadata.name` (e.g. `688825`) because those exchanges issue
numeric instrument codes rather than alphabetic tickers. The company name is
already present in `metadata.description`, suffixed with the spelled-out quote
currency, so the name is derived by stripping that suffix.

The exchange code is never lost: it stays in `symbol` (`Equity.CN.688825/CNY`),
and `metadata.description` is never modified.

See docs/superpowers/specs/2026-07-28-numeric-feed-name-rename-design.md.
"""

import csv
import re
from dataclasses import dataclass
from pathlib import Path

MARKET_PREFIXES = ("Equity.HK.", "Equity.JP.", "Equity.KR.", "Equity.CN.")

CURRENCY_NAMES = {
    "CNY": "CHINESE YUAN",
    "HKD": "HONG KONG DOLLAR",
    "JPY": "JAPANESE YEN",
    "KRW": "SOUTH KOREAN WON",
}

SEPARATOR = " / "

NUMERIC_NAME_RE = re.compile(r"^[0-9]+[A-Za-z]?$")


def in_scope(feed: dict, prefixes: tuple[str, ...] = MARKET_PREFIXES) -> bool:
    """True iff the feed's symbol sits in one of the configured namespaces."""
    return feed.get("symbol", "").startswith(prefixes)


def is_candidate(feed: dict, prefixes: tuple[str, ...] = MARKET_PREFIXES) -> bool:
    """True iff the feed is in scope and still carries a numeric name.

    The numeric test is what makes the script idempotent: once renamed, a feed
    stops matching, so a second run is a no-op.
    """
    if not in_scope(feed, prefixes):
        return False
    name = str(feed.get("metadata", {}).get("name", ""))
    return bool(NUMERIC_NAME_RE.match(name))


def derive_name(feed: dict) -> tuple[str | None, str | None]:
    """Derive the company name from `metadata.description`.

    Returns `(name, None)` on success, or `(None, reason)` when the feed must be
    skipped. The description tail is validated against the feed's
    `quote_currency` so a malformed or unmapped description is reported rather
    than written into `name` as a mangled value.
    """
    metadata = feed.get("metadata", {})
    description = metadata.get("description") or ""
    head, separator, tail = description.rpartition(SEPARATOR)
    if not separator:
        return None, f"description has no {SEPARATOR!r} separator: {description!r}"

    currency = metadata.get("quote_currency")
    expected = CURRENCY_NAMES.get(currency)
    if expected is None:
        return None, f"no currency name mapped for quote_currency {currency!r}"
    if tail.strip() != expected:
        return None, (
            f"description tail {tail.strip()!r} does not match expected "
            f"{expected!r} for {currency}"
        )

    name = head.strip()
    if not name:
        return None, f"derived name is empty from description {description!r}"
    return name, None


class OverrideError(Exception):
    """Raised on a malformed or invalid override CSV."""


OVERRIDE_COLUMNS = ("feed_id", "name")


def load_overrides(path: Path) -> dict[int, str]:
    """Parse the override CSV into `{feed_id: name}`.

    Raises OverrideError on any structural problem. Rows that are entirely
    blank are skipped so a trailing newline is not an error.
    """
    if not path.exists():
        raise OverrideError(f"override CSV not found: {path}")
    overrides: dict[int, str] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            raise OverrideError(f"{path}: no header row")
        missing = [c for c in OVERRIDE_COLUMNS if c not in reader.fieldnames]
        if missing:
            raise OverrideError(
                f"{path}: missing required column(s): {', '.join(missing)}"
            )
        for lineno, row in enumerate(reader, start=2):  # line 2 = first data row
            raw_id = (row.get("feed_id") or "").strip()
            name = (row.get("name") or "").strip()
            if not raw_id and not name:
                continue
            try:
                feed_id = int(raw_id)
            except ValueError:
                raise OverrideError(
                    f"{path} line {lineno}: feed_id {raw_id!r} is not an integer"
                ) from None
            if not name:
                raise OverrideError(f"{path} line {lineno}: name is empty")
            if feed_id in overrides:
                raise OverrideError(
                    f"{path} line {lineno}: duplicate feed_id {feed_id}"
                )
            overrides[feed_id] = name
    return overrides


def validate_overrides(
    overrides: dict[int, str],
    feeds: list[dict],
    prefixes: tuple[str, ...] = MARKET_PREFIXES,
) -> None:
    """Raise OverrideError unless every override targets an in-scope feed.

    An override may target a feed that is no longer a candidate (already
    renamed), so a short code can be pinned after the bulk rename has run.
    """
    by_id = {f["feedId"]: f for f in feeds}
    for feed_id in sorted(overrides):
        feed = by_id.get(feed_id)
        if feed is None:
            raise OverrideError(f"override feed_id {feed_id} not found in config")
        if not in_scope(feed, prefixes):
            raise OverrideError(
                f"override feed_id {feed_id} ({feed.get('symbol')}) is outside "
                f"the configured symbol prefixes: {', '.join(prefixes)}"
            )


@dataclass(frozen=True)
class Change:
    """One planned `metadata.name` rewrite."""

    feed_id: int
    symbol: str
    before: str
    after: str
    source: str  # "rule" or "override"


@dataclass(frozen=True)
class Skip:
    """A candidate that could not be derived, with the reason why."""

    feed_id: int
    symbol: str
    reason: str


def build_changes(
    feeds: list[dict],
    prefixes: tuple[str, ...] = MARKET_PREFIXES,
    overrides: dict[int, str] | None = None,
) -> tuple[list[Change], list[Skip]]:
    """Plan the rename over every in-scope feed.

    Overrides take precedence over rule derivation and bypass the currency
    check, since the value is supplied by hand. A feed whose name already
    equals the target produces no change, which is what makes repeat runs
    no-ops.
    """
    overrides = overrides or {}
    changes: list[Change] = []
    skips: list[Skip] = []
    for feed in feeds:
        if not in_scope(feed, prefixes):
            continue
        feed_id = feed["feedId"]
        symbol = feed.get("symbol", "")
        before = str(feed.get("metadata", {}).get("name", ""))

        if feed_id in overrides:
            after, source = overrides[feed_id], "override"
        elif is_candidate(feed, prefixes):
            after, reason = derive_name(feed)
            if after is None:
                skips.append(Skip(feed_id, symbol, reason))
                continue
            source = "rule"
        else:
            continue

        if after != before:
            changes.append(Change(feed_id, symbol, before, after, source))
    return changes, skips


def find_duplicate_names(
    feeds: list[dict], changes: list[Change]
) -> list[tuple[str, list[tuple[int, str]]]]:
    """Names shared by two or more feeds after the rename.

    Only groups containing at least one changed feed are reported, which keeps
    pre-existing duplicates elsewhere in the config (`BA`, `AAL`) out of the
    output while still catching a derived name colliding with an untouched one.
    """
    new_names = {c.feed_id: c.after for c in changes}
    groups: dict[str, list[tuple[int, str]]] = {}
    for feed in feeds:
        feed_id = feed["feedId"]
        current = str(feed.get("metadata", {}).get("name", ""))
        name = new_names.get(feed_id, current)
        groups.setdefault(name, []).append((feed_id, feed.get("symbol", "")))
    return sorted(
        (name, members)
        for name, members in groups.items()
        if len(members) > 1 and any(fid in new_names for fid, _ in members)
    )
