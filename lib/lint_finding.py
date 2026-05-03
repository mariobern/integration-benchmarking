"""Shared LintFinding dataclass used by config_lint and exchange_lint."""

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
