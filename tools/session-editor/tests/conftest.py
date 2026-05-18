"""Shared pytest fixtures and path setup."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

# Add the tool root to sys.path so `session_editor_lib` imports work.
TOOL_ROOT = Path(__file__).resolve().parent.parent
if str(TOOL_ROOT) not in sys.path:
    sys.path.insert(0, str(TOOL_ROOT))

FIXTURE_PATH = TOOL_ROOT / "tests" / "fixtures" / "sample_after.json"


@pytest.fixture
def sample_feeds() -> list[dict]:
    """Fresh deep copy of the sample feeds list, safe to mutate per test."""
    data = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    return copy.deepcopy(data["feeds"])


@pytest.fixture
def aapl_feed(sample_feeds) -> dict:
    return next(f for f in sample_feeds if f["feedId"] == 922)


@pytest.fixture
def abnb_feed(sample_feeds) -> dict:
    """feedId 924 — STABLE US equity missing OVER_NIGHT."""
    return next(f for f in sample_feeds if f["feedId"] == 924)


@pytest.fixture
def equity_a_feed(sample_feeds) -> dict:
    """feedId 921 — STABLE US equity, REGULAR-only."""
    return next(f for f in sample_feeds if f["feedId"] == 921)


@pytest.fixture
def btc_feed(sample_feeds) -> dict:
    """feedId 1 — crypto, NOT a US-equity feed."""
    return next(f for f in sample_feeds if f["feedId"] == 1)


@pytest.fixture
def fixture_path() -> Path:
    return FIXTURE_PATH


@pytest.fixture
def tool_root() -> Path:
    return TOOL_ROOT
