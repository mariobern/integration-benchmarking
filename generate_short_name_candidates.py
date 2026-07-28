#!/usr/bin/env python3
"""Propose shorter display names for HK/JP/KR/CN equity feeds.

HK and KR have official exchange-published English short names, reachable via
Yahoo Finance's `shortName` field (yfinance, already a repo dependency). JP and
CN have no equivalent public standard, so a legal-suffix-stripping heuristic is
applied to the existing description-derived name instead.

This script never writes to any Lazer config file. It writes a review CSV
(default `name_override_candidates.csv`) for a human to curate into the
existing, version-controlled `feed_name_overrides.csv`, which then flows
through `rename_numeric_feed_names.py --apply --name-overrides ...` unchanged.

See docs/superpowers/specs/2026-07-28-short-name-candidates-design.md.
"""

import argparse
import csv
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

from rename_numeric_feed_names import MARKET_PREFIXES, derive_name, in_scope

SUFFIX_WORDS = frozenset(
    {
        "CORP",
        "CORPORATION",
        "LTD",
        "LIMITED",
        "INC",
        "CO",
        "COMPANY",
        "HOLDINGS",
        "HLDGS",
        "PLC",
        "KAISHA",
        "KABUSHIKI",
    }
)


def extract_exchange_code(symbol: str) -> str:
    """Pull the numeric exchange code out of e.g. 'Equity.HK.9901/HKD' -> '9901'.

    Reads `symbol`, which `rename_numeric_feed_names.py` never modifies, so this
    works whether or not `metadata.name` has already been renamed.
    """
    root = symbol.split("/", 1)[0]
    return root.rsplit(".", 1)[1]


def strip_corporate_suffix(name: str) -> str:
    """Iteratively remove trailing legal-entity words/`&` from `name`.

    Returns `name` unchanged if nothing in the vocabulary matched. Never strips
    a name down to fewer than one token.
    """
    tokens = name.split()
    while len(tokens) > 1:
        last = tokens[-1].rstrip(".,").upper()
        if last in SUFFIX_WORDS or last == "&":
            tokens.pop()
        else:
            break
    return " ".join(tokens)


_CAMEL_BOUNDARY_RE = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_PUNCTUATION_RE = re.compile(r"[.,]")
_WHITESPACE_RE = re.compile(r"\s+")


def normalize_yahoo_name(raw: str) -> str:
    """Normalize a Yahoo Finance `shortName` for display consistency.

    Yahoo stores some short names camelCase-merged with no spaces (e.g.
    'HyundaiMtr', 'SKTelecom'); blindly uppercasing those collapses them into
    unreadable blobs ('HYUNDAIMTR'). This inserts a space at camelCase word
    boundaries first, then strips stray punctuation ('CO.,LTD.' -> 'CO LTD',
    not 'COLTD'), before uppercasing.
    """
    spaced = _CAMEL_BOUNDARY_RE.sub(" ", raw)
    spaced = _PUNCTUATION_RE.sub(" ", spaced)
    collapsed = _WHITESPACE_RE.sub(" ", spaced).strip()
    return collapsed.upper()


_SHARE_CLASS_SUFFIX_RE = re.compile(r"-[A-Z]{1,3}$")


@dataclass(frozen=True)
class Candidate:
    """One proposed shorter name, awaiting human review."""

    feed_id: int
    symbol: str
    current_name: str
    proposed_name: str
    source: str  # "yahoo_shortname" or "suffix_stripped"
    notes: str = ""


@dataclass(frozen=True)
class SkipReason:
    """A feed that produced no candidate, with the reason why."""

    feed_id: int
    symbol: str
    reason: str


def yahoo_tickers(market: str, code: str) -> list[str]:
    """Ordered Yahoo Finance ticker candidates to try for a given market/code.

    KR tries KOSPI (.KS) before KOSDAQ (.KQ) since there is no way to tell
    which board a code belongs to without querying.
    """
    if market == "HK":
        return [f"{code.zfill(4)}.HK"]
    if market == "KR":
        return [f"{code}.KS", f"{code}.KQ"]
    raise ValueError(f"unsupported market for Yahoo lookup: {market}")


def _fetch_yahoo_short_name(ticker: str) -> str | None:
    """Return `info['shortName']` for `ticker`, or None on any failure."""
    import yfinance as yf

    try:
        info = yf.Ticker(ticker).info
    except (
        ValueError,
        KeyError,
        AttributeError,
        ConnectionError,
        OSError,
        yf.exceptions.YFException,
    ):
        return None
    short_name = info.get("shortName") if info else None
    return short_name or None


def suggest_from_yahoo(feed: dict) -> tuple[Candidate | None, SkipReason | None]:
    """Propose a name for an HK/KR feed from Yahoo Finance's `shortName`."""
    feed_id = feed["feedId"]
    symbol = feed.get("symbol", "")
    current_name = str(feed.get("metadata", {}).get("name", ""))
    market = symbol.split(".")[1]
    code = extract_exchange_code(symbol)
    tickers = yahoo_tickers(market, code)

    for ticker in tickers:
        raw_short_name = _fetch_yahoo_short_name(ticker)
        if not raw_short_name:
            continue
        proposed = normalize_yahoo_name(raw_short_name)
        if proposed == current_name:
            return None, SkipReason(
                feed_id, symbol, f"Yahoo shortName matches current name ({ticker})"
            )
        notes = (
            "share_class_suffix_retained"
            if _SHARE_CLASS_SUFFIX_RE.search(proposed)
            else ""
        )
        return (
            Candidate(
                feed_id, symbol, current_name, proposed, "yahoo_shortname", notes
            ),
            None,
        )

    return None, SkipReason(
        feed_id, symbol, f"no Yahoo shortName found for tickers {tickers}"
    )


def suggest_from_suffix_strip(feed: dict) -> tuple[Candidate | None, SkipReason | None]:
    """Propose a name for a JP/CN feed by stripping trailing corporate words
    off the description-derived name. No network call."""
    feed_id = feed["feedId"]
    symbol = feed.get("symbol", "")
    current_name = str(feed.get("metadata", {}).get("name", ""))

    base_name, reason = derive_name(feed)
    if base_name is None:
        return None, SkipReason(feed_id, symbol, reason)

    stripped = strip_corporate_suffix(base_name)
    if stripped == base_name:
        return None, SkipReason(feed_id, symbol, "no corporate suffix matched")

    return Candidate(feed_id, symbol, current_name, stripped, "suffix_stripped"), None


def build_candidates(
    feeds: list[dict], prefixes: tuple[str, ...] = MARKET_PREFIXES
) -> tuple[list[Candidate], list[SkipReason]]:
    """Plan name-shortening candidates over every in-scope feed.

    Runs regardless of whether a feed's current `metadata.name` is still
    numeric or already renamed — both strategies derive the base name from
    fields `rename_numeric_feed_names.py` never modifies (`symbol`,
    `description`).
    """
    candidates: list[Candidate] = []
    skips: list[SkipReason] = []
    for feed in feeds:
        if not in_scope(feed, prefixes):
            continue
        market = feed.get("symbol", "").split(".")[1]
        if market in ("HK", "KR"):
            candidate, skip = suggest_from_yahoo(feed)
        elif market in ("JP", "CN"):
            candidate, skip = suggest_from_suffix_strip(feed)
        else:
            continue
        if candidate is not None:
            candidates.append(candidate)
        if skip is not None:
            skips.append(skip)
    return candidates, skips
