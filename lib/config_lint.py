"""Config linter rules for after.json validation.

Validates feed definitions, publisher references, schedule consistency,
and business rules. Pure stdlib — no external dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class LintFinding:
    """A single lint finding."""

    rule_id: str
    severity: str  # "ERROR" or "WARNING"
    message: str
    feed_id: Optional[int]
    symbol: Optional[str]


def check_duplicates(feeds: list[dict]) -> list[LintFinding]:
    """E001: duplicate feedId, E002: duplicate symbol (STABLE/COMING_SOON)."""
    findings: list[LintFinding] = []

    # E001: duplicate feedId (all feeds)
    id_counts: dict[int, list[int]] = {}
    for idx, feed in enumerate(feeds):
        fid = feed.get("feedId")
        if fid is not None:
            id_counts.setdefault(fid, []).append(idx)

    for fid, indices in id_counts.items():
        if len(indices) > 1:
            locs = ", ".join(f"feeds[{i}]" for i in indices)
            findings.append(
                LintFinding(
                    rule_id="E001",
                    severity="ERROR",
                    message=f"feedId {fid} is duplicated ({locs})",
                    feed_id=fid,
                    symbol=None,
                )
            )

    # E002: duplicate symbol within STABLE/COMING_SOON
    active_symbols: dict[str, list[dict]] = {}
    for feed in feeds:
        state = feed.get("state", "")
        if state in ("STABLE", "COMING_SOON"):
            sym = feed.get("symbol", "")
            active_symbols.setdefault(sym, []).append(feed)

    for sym, dupes in active_symbols.items():
        if len(dupes) > 1:
            ids = [str(f.get("feedId", "?")) for f in dupes]
            findings.append(
                LintFinding(
                    rule_id="E002",
                    severity="ERROR",
                    message=f"symbol '{sym}' duplicated in STABLE/COMING_SOON feeds (feedIds: {', '.join(ids)})",
                    feed_id=dupes[0].get("feedId"),
                    symbol=sym,
                )
            )

    return findings


# Required top-level fields on every feed
_REQUIRED_FIELDS = ("feedId", "symbol", "state", "kind")


def check_schema(feeds: list[dict]) -> list[LintFinding]:
    """E007: missing required fields."""
    findings: list[LintFinding] = []

    for feed in feeds:
        fid = feed.get("feedId")
        sym = feed.get("symbol")
        missing = [f for f in _REQUIRED_FIELDS if f not in feed]

        # Check metadata.asset_type separately
        metadata = feed.get("metadata")
        if metadata is None or "asset_type" not in metadata:
            missing.append("metadata.asset_type")

        if missing:
            findings.append(
                LintFinding(
                    rule_id="E007",
                    severity="ERROR",
                    message=f"missing required fields: {', '.join(missing)}",
                    feed_id=fid,
                    symbol=sym,
                )
            )

    return findings


def check_publishers(feeds: list[dict], publishers: list[dict]) -> list[LintFinding]:
    """Publisher validation rules."""
    # Placeholder — implemented in Task 4
    return []


def check_schedules(feeds: list[dict]) -> list[LintFinding]:
    """Schedule validation rules."""
    # Placeholder — implemented in Task 5
    return []


def lint_config(config: dict) -> list[LintFinding]:
    """Orchestrator. Takes the full parsed after.json root object."""
    feeds = config.get("feeds", [])
    publishers = config.get("publishers", [])

    findings: list[LintFinding] = []
    findings.extend(check_duplicates(feeds))
    findings.extend(check_schema(feeds))
    findings.extend(check_publishers(feeds, publishers))
    findings.extend(check_schedules(feeds))

    return findings
