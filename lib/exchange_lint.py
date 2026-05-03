"""Exchange-aware lint rules: E019, E020, E021, E022, E023, E024, E025,
W010, W011.

Public entry point: check_exchanges(feeds, exchanges) -> list[LintFinding].
"""

from __future__ import annotations

from typing import Any

from lib.config_lint import LintFinding


# Enum allowlists (per Exchange_Configuration_Guide.md).
_ASSET_CLASS = frozenset(
    {
        "EXCHANGE_ASSET_CLASS_UNSPECIFIED",
        "EXCHANGE_ASSET_CLASS_EQUITY",
        "EXCHANGE_ASSET_CLASS_FUTURE",
    }
)
_ASSET_SUBCLASS = frozenset(
    {
        "EXCHANGE_ASSET_SUBCLASS_UNSPECIFIED",
        "EXCHANGE_ASSET_SUBCLASS_COMMON_STOCK",
        "EXCHANGE_ASSET_SUBCLASS_ETF",
        "EXCHANGE_ASSET_SUBCLASS_ENERGY",
        "EXCHANGE_ASSET_SUBCLASS_METALS",
        "EXCHANGE_ASSET_SUBCLASS_EQUITY",
        "EXCHANGE_ASSET_SUBCLASS_FIXED_INCOME",
        "EXCHANGE_ASSET_SUBCLASS_FX",
        "EXCHANGE_ASSET_SUBCLASS_AGRICULTURAL",
    }
)
_ASSET_SECTOR = frozenset(
    {
        "EXCHANGE_ASSET_SECTOR_UNSPECIFIED",
        "EXCHANGE_ASSET_SECTOR_TECHNOLOGY",
        "EXCHANGE_ASSET_SECTOR_FINANCIALS",
        "EXCHANGE_ASSET_SECTOR_BROAD_MARKET",
        "EXCHANGE_ASSET_SECTOR_OIL",
        "EXCHANGE_ASSET_SECTOR_METALS",
        "EXCHANGE_ASSET_SECTOR_INDEX",
        "EXCHANGE_ASSET_SECTOR_RATES",
        "EXCHANGE_ASSET_SECTOR_FX",
        "EXCHANGE_ASSET_SECTOR_AGRICULTURAL",
    }
)

_DEFAULT_CLASS = "EXCHANGE_ASSET_CLASS_UNSPECIFIED"
_DEFAULT_SUBCLASS = "EXCHANGE_ASSET_SUBCLASS_UNSPECIFIED"
_DEFAULT_SECTOR = "EXCHANGE_ASSET_SECTOR_UNSPECIFIED"


def _is_well_formed(entry: dict) -> bool:
    """An entry is well-formed iff exchangeId is non-null AND name is a
    non-empty string. E021/E023/E025 only consider well-formed entries.
    Entries with empty/missing sessions are still well-formed for those
    rules (E020 handles the inheritance consequence per affected feed)."""
    if not isinstance(entry, dict):
        return False
    if entry.get("exchangeId") is None:
        return False
    name = entry.get("name")
    if not isinstance(name, str) or not name:
        return False
    return True


def _build_index(
    exchanges: list[dict],
) -> tuple[dict[Any, dict], dict[Any, set[str]]]:
    """Build (exchange_by_id, session_set_by_id) from well-formed entries.

    On duplicate id, first-write-wins (deterministic by iteration order)
    — the first entry encountered is canonical. E023 reports the duplicate
    group; downstream rules (E019/E020/W010/W011) use the canonical entry.
    """
    by_id: dict[Any, dict] = {}
    sessions_by_id: dict[Any, set[str]] = {}
    for e in exchanges:
        if not _is_well_formed(e):
            continue
        eid = e["exchangeId"]
        try:
            if eid not in by_id:
                by_id[eid] = e
        except TypeError:
            # Unhashable id (e.g. list/dict) — well-formed allows any non-null
            # id, so we get here for non-hashable values. Skip them; E019
            # will report the consuming feed as dangling.
            continue
        if eid not in sessions_by_id:
            sessions_by_id[eid] = {
                s.get("session")
                for s in (e.get("sessions") or [])
                if isinstance(s, dict) and s.get("session")
            }
    return by_id, sessions_by_id


def check_exchanges(
    feeds: list[dict],
    exchanges: Any,
) -> list[LintFinding]:
    """Run E019, E020, E021, E022, E023, E024, E025, W010, W011.

    `exchanges` is defensively coerced to [] if not a list.
    """
    if not isinstance(exchanges, list):
        exchanges = []

    findings: list[LintFinding] = []
    # Subsequent tasks add: check_e024, check_e023, check_e021, check_e025,
    # check_e019_e020_w010_w011, check_e022.
    return findings
