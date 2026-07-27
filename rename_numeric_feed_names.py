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

import argparse
import csv
import json
import re
import shutil
import sys
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


class VerificationError(Exception):
    """Raised when the rewritten config differs in unexpected ways."""


def dump_config(data: dict) -> str:
    """Serialize exactly as the config is stored on disk.

    2-space indent, raw UTF-8, no trailing newline. Verified byte-identical
    against an unmodified `lazer-state.json`, so the only difference between
    input and output is the lines this script deliberately changes.
    """
    return json.dumps(data, indent=2, ensure_ascii=False)


def apply_changes(data: dict, changes: list[Change]) -> None:
    """Write the planned names into the in-memory document."""
    by_id = {f["feedId"]: f for f in data["feeds"]}
    for change in changes:
        by_id[change.feed_id]["metadata"]["name"] = change.after


def _parse_name_line(line: str) -> str:
    """Extract the value from a `"name": "..."` line, comma or not."""
    return json.loads("{" + line.strip().rstrip(",") + "}")["name"]


def verify_text(before_text: str, after_text: str, changes: list[Change]) -> None:
    """Raise VerificationError unless every differing line is an expected name.

    Proves at the line level that no line outside the expected "name": lines moved.
    Textual only: cannot distinguish a feed's metadata.name from exchanges[].name or
    detect value swaps between changed feeds. Use verify_feed_names for JSON-aware checks.
    """
    before_lines = before_text.split("\n")
    after_lines = after_text.split("\n")
    if len(before_lines) != len(after_lines):
        raise VerificationError(
            f"line count changed: {len(before_lines)} -> {len(after_lines)}"
        )
    differing = [
        (lineno, before, after)
        for lineno, (before, after) in enumerate(
            zip(before_lines, after_lines), start=1
        )
        if before != after
    ]
    if len(differing) != len(changes):
        raise VerificationError(
            f"expected {len(changes)} changed line(s), found {len(differing)}"
        )
    for lineno, before_line, _after_line in differing:
        if not before_line.strip().startswith('"name":'):
            raise VerificationError(
                f"line {lineno} is not a name field: {before_line.strip()!r}"
            )
    expected = sorted(c.after for c in changes)
    found = sorted(_parse_name_line(after) for _, _, after in differing)
    if expected != found:
        raise VerificationError("changed name values do not match the plan")


def verify_feed_names(
    before_data: dict, after_data: dict, changes: list[Change]
) -> None:
    """Raise VerificationError unless exactly the planned feed names changed.

    The line-level check in `verify_text` proves no other line moved, but it is
    textual: it cannot tell a feed's `metadata.name` from an `exchanges[].name`,
    and its multiset comparison would accept two feeds having their new names
    swapped. This check is JSON-path-aware and pins each new name to its feed.
    """
    before_names = {
        f["feedId"]: str(f.get("metadata", {}).get("name", ""))
        for f in before_data["feeds"]
    }
    after_names = {
        f["feedId"]: str(f.get("metadata", {}).get("name", ""))
        for f in after_data["feeds"]
    }
    if before_names.keys() != after_names.keys():
        raise VerificationError("feed id set changed")
    actual = {
        feed_id: after_names[feed_id]
        for feed_id in before_names
        if before_names[feed_id] != after_names[feed_id]
    }
    expected = {c.feed_id: c.after for c in changes}
    if actual != expected:
        only_actual = {k: v for k, v in actual.items() if expected.get(k) != v}
        only_expected = {k: v for k, v in expected.items() if actual.get(k) != v}
        raise VerificationError(
            f"feed name changes do not match the plan; unexpected={only_actual}, "
            f"missing={only_expected}"
        )


def verify_on_disk(path: Path, before_text: str, changes: list[Change]) -> None:
    """Re-read the written config and confirm it parses and changed only names."""
    after_text = path.read_text(encoding="utf-8")
    try:
        data = json.loads(after_text)
    except json.JSONDecodeError as exc:
        raise VerificationError(f"written config does not parse: {exc}") from exc
    expected_feeds = len(json.loads(before_text)["feeds"])
    if len(data["feeds"]) != expected_feeds:
        raise VerificationError(
            f"feed count changed: {expected_feeds} -> {len(data['feeds'])}"
        )
    verify_text(before_text, after_text, changes)
    verify_feed_names(json.loads(before_text), data, changes)


def write_config(path: Path, text: str, backup: bool = True) -> None:
    """Back up (unless suppressed) then overwrite the config."""
    if backup:
        shutil.copy2(path, path.with_suffix(path.suffix + ".bak"))
    path.write_text(text, encoding="utf-8")


def print_report(
    changes: list[Change],
    skips: list[Skip],
    duplicates: list[tuple[str, list[tuple[int, str]]]],
) -> None:
    """Print the change table, skip list, and duplicate-name warnings."""
    if changes:
        width = max(len(c.symbol) for c in changes)
        print(f"\nChanges ({len(changes)}):")
        for change in changes:
            print(
                f"  {change.feed_id:5d}  {change.symbol:<{width}}  "
                f"{change.before!r} -> {change.after!r}  [{change.source}]"
            )
    if skips:
        print(f"\nSkipped ({len(skips)}):")
        for skip in skips:
            print(f"  {skip.feed_id:5d}  {skip.symbol}  {skip.reason}")
    for name, members in duplicates:
        print(f"\nWARNING  duplicate name {name!r}")
        for feed_id, symbol in members:
            print(f"           {feed_id:5d}  {symbol}")
    print(
        f"\nSummary: {len(changes)} change(s), {len(skips)} skip(s), "
        f"{len(duplicates)} duplicate-name warning(s)."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True, help="Path to the config")
    parser.add_argument(
        "--symbol-prefix",
        action="append",
        dest="symbol_prefixes",
        help=(
            "Symbol namespace to process; repeatable. Defaults to "
            f"{', '.join(MARKET_PREFIXES)}"
        ),
    )
    parser.add_argument(
        "--name-overrides",
        type=Path,
        help="CSV of hand-curated names (columns: feed_id,name)",
    )
    parser.add_argument("--apply", action="store_true", help="Write changes")
    parser.add_argument("--no-backup", action="store_true", help="Skip the .bak copy")
    args = parser.parse_args(argv)

    prefixes = tuple(args.symbol_prefixes) if args.symbol_prefixes else MARKET_PREFIXES

    if not args.config.exists():
        print(f"ERROR: Config file not found: {args.config}", file=sys.stderr)
        return 1

    before_text = args.config.read_text(encoding="utf-8")
    data = json.loads(before_text)
    feeds = data["feeds"]
    print(f"Reading {args.config} ({len(feeds)} feeds)...")

    overrides: dict[int, str] = {}
    if args.name_overrides:
        try:
            overrides = load_overrides(args.name_overrides)
            validate_overrides(overrides, feeds, prefixes)
        except OverrideError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 1
        print(f"Loaded {len(overrides)} override(s) from {args.name_overrides}")

    changes, skips = build_changes(feeds, prefixes, overrides)
    duplicates = find_duplicate_names(feeds, changes)
    print_report(changes, skips, duplicates)

    if not changes:
        print("\nNo changes. Nothing to do.")
        return 0

    apply_changes(data, changes)
    trailing = before_text[len(before_text.rstrip("\n")) :]
    after_text = dump_config(data) + trailing
    # Verification runs before the write, so a dry run catches problems too.
    try:
        verify_text(before_text, after_text, changes)
        verify_feed_names(json.loads(before_text), data, changes)
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
