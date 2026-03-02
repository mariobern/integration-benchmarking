"""Per-session and per-asset-class pass/fail thresholds for benchmark evaluation.

Three threshold tiers:
- REGULAR: fx, us-equities (regular session), us-treasuries
- RELAXED: commodity, metals (lower liquidity, wider spreads)
- EXTENDED: us-equities pre-market, after-hours, overnight
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class SessionThresholds:
    """Pass/fail thresholds for a benchmark session."""

    nrmse_auto_pass: float
    nrmse_conditional: float
    hit_rate_threshold: float


REGULAR_THRESHOLDS = SessionThresholds(
    nrmse_auto_pass=0.01,
    nrmse_conditional=0.05,
    hit_rate_threshold=95,
)

EXTENDED_THRESHOLDS = SessionThresholds(
    nrmse_auto_pass=0.05,
    nrmse_conditional=0.15,
    hit_rate_threshold=85,
)

_EXTENDED_SESSIONS = {"premarket", "afterhours", "overnight"}

RELAXED_THRESHOLDS = SessionThresholds(
    nrmse_auto_pass=0.05,
    nrmse_conditional=0.15,
    hit_rate_threshold=85,
)

_RELAXED_ASSET_CLASSES = {"commodity", "metals", "metal"}


def get_session_thresholds(
    session: str,
    mode: str,
    hit_rate_override: Optional[float] = None,
) -> SessionThresholds:
    """Look up the correct thresholds for a session + asset class.

    Priority:
        1. US equities extended sessions -> EXTENDED_THRESHOLDS (fixed)
        2. Commodity / metals -> RELAXED_THRESHOLDS
        3. CLI hit_rate_override -> regular or relaxed NRMSE with custom hit rate
        4. Everything else -> REGULAR_THRESHOLDS

    Args:
        session: One of "regular", "premarket", "afterhours", "overnight".
        mode: Asset class identifier (e.g. "us-equities", "fx", "metals").
        hit_rate_override: Optional CLI override for the hit rate threshold.
            Applies to regular and relaxed tiers. Ignored for extended sessions.

    Returns:
        The applicable ``SessionThresholds`` for the given combination.
    """
    is_us_equities = mode in ("us-equities", "equity-us")

    if is_us_equities and session in _EXTENDED_SESSIONS:
        return EXTENDED_THRESHOLDS

    if mode in _RELAXED_ASSET_CLASSES:
        if hit_rate_override is not None:
            return SessionThresholds(
                nrmse_auto_pass=RELAXED_THRESHOLDS.nrmse_auto_pass,
                nrmse_conditional=RELAXED_THRESHOLDS.nrmse_conditional,
                hit_rate_threshold=hit_rate_override,
            )
        return RELAXED_THRESHOLDS

    if hit_rate_override is not None:
        return SessionThresholds(
            nrmse_auto_pass=REGULAR_THRESHOLDS.nrmse_auto_pass,
            nrmse_conditional=REGULAR_THRESHOLDS.nrmse_conditional,
            hit_rate_threshold=hit_rate_override,
        )

    return REGULAR_THRESHOLDS


def passes_benchmark(
    nrmse: Optional[float],
    hit_rate: float,
    session: str = "regular",
    mode: str = "us-equities",
    hit_rate_override: Optional[float] = None,
) -> bool:
    """Evaluate whether a publisher passes the benchmark for a given session.

    A publisher **auto-passes** if its NRMSE is strictly below the auto-pass
    threshold. Otherwise it can **conditionally pass** if its NRMSE is below
    the conditional threshold *and* its hit rate meets or exceeds the hit rate
    threshold.

    Args:
        nrmse: Normalised RMSE value, or ``None`` if unavailable.
        hit_rate: Hit rate percentage (0-100).
        session: Trading session name.
        mode: Asset class identifier.
        hit_rate_override: Optional CLI override (regular session only).

    Returns:
        ``True`` if the publisher passes, ``False`` otherwise.
    """
    if nrmse is None:
        return False

    t = get_session_thresholds(session, mode, hit_rate_override)
    return nrmse < t.nrmse_auto_pass or (
        nrmse < t.nrmse_conditional and hit_rate >= t.hit_rate_threshold
    )


def get_threshold_description(mode: str) -> str:
    """Return human-readable pass criteria string for the given asset class.

    Used by output modules to display the correct thresholds dynamically
    instead of hardcoding threshold values.

    Args:
        mode: Asset class identifier (e.g. "us-equities", "commodity").

    Returns:
        Formatted string like "nrmse < 0.01 OR (nrmse < 0.05 AND hit_rate >= 95%)".
    """
    t = get_session_thresholds("regular", mode)
    return (
        f"nrmse < {t.nrmse_auto_pass} OR "
        f"(nrmse < {t.nrmse_conditional} AND hit_rate >= {t.hit_rate_threshold}%)"
    )
