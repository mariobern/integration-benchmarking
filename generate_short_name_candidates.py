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
