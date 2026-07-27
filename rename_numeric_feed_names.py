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

import re

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
