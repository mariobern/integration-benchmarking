"""Load LSEG-style RIC CSVs and derive feed symbol prefixes.

The CSV contains one row per security with columns including `Ticker`,
`RIC`, and `Exchange Code`. For v1 we only know how to derive a feed
symbol prefix for HK rows (RIC ending in `.HK`).
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path


class LoadError(Exception):
    """Raised on malformed or missing CSV input."""


@dataclass(frozen=True)
class RicEntry:
    ticker: str
    ric: str
    exchange_code: str


_REQUIRED_COLUMNS = ("Ticker", "RIC", "Exchange Code")


def load_ric_csv(path: str) -> list[RicEntry]:
    """Parse the CSV at `path`. Raises LoadError on any structural problem."""
    p = Path(path)
    if not p.exists():
        raise LoadError(f"CSV not found: {path}")
    with p.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames is None:
            raise LoadError(f"{path}: no header row")
        missing = [c for c in _REQUIRED_COLUMNS if c not in reader.fieldnames]
        if missing:
            raise LoadError(f"{path}: missing required column(s): {', '.join(missing)}")
        entries: list[RicEntry] = []
        seen_rics: set[str] = set()
        for i, row in enumerate(reader, start=2):  # line 2 = first data row
            ric = (row.get("RIC") or "").strip()
            ticker = (row.get("Ticker") or "").strip()
            exchange = (row.get("Exchange Code") or "").strip()
            if not ric:
                continue
            if ric in seen_rics:
                raise LoadError(f"{path}: duplicate RIC {ric!r} (line {i})")
            seen_rics.add(ric)
            entries.append(RicEntry(ticker=ticker, ric=ric, exchange_code=exchange))
    if not entries:
        raise LoadError(f"{path}: no data rows")
    return entries


def derive_symbol_prefixes(ric: str) -> list[str]:
    """Map a RIC to the candidate Lazer feed symbol prefixes.

    v1 supports only HK equities: `NNNN.HK` -> both `Equity.HK.NNNN-HK/`
    (legacy form) and `Equity.HK.NNNN/` (current form).
    Returns [] for RICs we don't know how to map.
    """
    if ric.endswith(".HK"):
        head = ric[: -len(".HK")]
        if head.isdigit():
            return [f"Equity.HK.{head}-HK/", f"Equity.HK.{head}/"]
    return []


def build_prefix_index(entries: list[RicEntry]) -> dict[str, str]:
    """Build `{symbol_prefix: ric}` for entries with derivable prefix(es).

    An entry may contribute multiple prefixes (e.g. HK feeds support both
    `Equity.HK.NNNN-HK/` and `Equity.HK.NNNN/`); all map to the same RIC.
    """
    out: dict[str, str] = {}
    for e in entries:
        for prefix in derive_symbol_prefixes(e.ric):
            out[prefix] = e.ric
    return out
