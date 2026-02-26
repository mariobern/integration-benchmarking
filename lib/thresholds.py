"""Per-session pass/fail thresholds for benchmark evaluation.

US Equities extended hours (pre-market, after-hours, overnight) use
relaxed thresholds due to lower liquidity and wider spreads.
All other asset classes use regular thresholds regardless of session.
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


def get_session_thresholds(
    session: str,
    mode: str,
    hit_rate_override: Optional[float] = None,
) -> SessionThresholds:
    """Look up the correct thresholds for a session + asset class.

    Args:
        session: One of "regular", "premarket", "afterhours", "overnight".
        mode: Asset class identifier (e.g. "us-equities", "fx", "metals").
        hit_rate_override: Optional CLI override for the regular session
            hit rate threshold. Ignored for extended sessions.

    Returns:
        The applicable ``SessionThresholds`` for the given combination.
    """
    is_us_equities = mode in ("us-equities", "equity-us")

    if is_us_equities and session in _EXTENDED_SESSIONS:
        return EXTENDED_THRESHOLDS

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
