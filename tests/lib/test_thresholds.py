"""Tests for lib.thresholds — per-session pass/fail thresholds."""

import pytest

from lib.thresholds import (
    EXTENDED_THRESHOLDS,
    REGULAR_THRESHOLDS,
    RELAXED_THRESHOLDS,
    SessionThresholds,
    get_session_thresholds,
    get_threshold_description,
    passes_benchmark,
)


class TestSessionThresholds:
    """Verify constant values match the threshold table."""

    def test_regular_thresholds(self) -> None:
        assert REGULAR_THRESHOLDS.nrmse_auto_pass == 0.01
        assert REGULAR_THRESHOLDS.nrmse_conditional == 0.05
        assert REGULAR_THRESHOLDS.hit_rate_threshold == 95

    def test_extended_thresholds(self) -> None:
        assert EXTENDED_THRESHOLDS.nrmse_auto_pass == 0.05
        assert EXTENDED_THRESHOLDS.nrmse_conditional == 0.15
        assert EXTENDED_THRESHOLDS.hit_rate_threshold == 85


class TestRelaxedThresholds:
    """Verify RELAXED_THRESHOLDS constant values."""

    def test_relaxed_thresholds_values(self) -> None:
        assert RELAXED_THRESHOLDS.nrmse_auto_pass == 0.05
        assert RELAXED_THRESHOLDS.nrmse_conditional == 0.15
        assert RELAXED_THRESHOLDS.hit_rate_threshold == 85

    def test_relaxed_is_separate_from_extended(self) -> None:
        """RELAXED and EXTENDED have same values but are different objects."""
        assert RELAXED_THRESHOLDS == EXTENDED_THRESHOLDS
        assert RELAXED_THRESHOLDS is not EXTENDED_THRESHOLDS


class TestGetSessionThresholds:
    """Verify correct threshold selection for session + mode combos."""

    # Regular sessions — US equities
    def test_regular_us_equities(self) -> None:
        t = get_session_thresholds("regular", "us-equities")
        assert t == REGULAR_THRESHOLDS

    # Extended sessions — US equities should use relaxed thresholds
    def test_premarket_us_equities(self) -> None:
        t = get_session_thresholds("premarket", "us-equities")
        assert t == EXTENDED_THRESHOLDS

    def test_afterhours_us_equities(self) -> None:
        t = get_session_thresholds("afterhours", "us-equities")
        assert t == EXTENDED_THRESHOLDS

    def test_overnight_us_equities(self) -> None:
        t = get_session_thresholds("overnight", "us-equities")
        assert t == EXTENDED_THRESHOLDS

    # equity-us alias should behave identically
    def test_premarket_equity_us_alias(self) -> None:
        t = get_session_thresholds("premarket", "equity-us")
        assert t == EXTENDED_THRESHOLDS

    # Non-US-equity modes always get regular thresholds
    def test_fx_always_regular(self) -> None:
        for session in ("regular", "premarket", "afterhours", "overnight"):
            t = get_session_thresholds(session, "fx")
            assert t == REGULAR_THRESHOLDS, f"fx/{session} should use regular"

    def test_commodity_regular_uses_relaxed(self) -> None:
        t = get_session_thresholds("regular", "commodity")
        assert t == RELAXED_THRESHOLDS

    def test_metals_regular_uses_relaxed(self) -> None:
        t = get_session_thresholds("regular", "metals")
        assert t == RELAXED_THRESHOLDS

    def test_metal_alias_uses_relaxed(self) -> None:
        """The 'metal' alias (unnormalized) should also route to RELAXED."""
        t = get_session_thresholds("regular", "metal")
        assert t == RELAXED_THRESHOLDS

    def test_us_treasuries_always_regular(self) -> None:
        t = get_session_thresholds("regular", "us-treasuries")
        assert t == REGULAR_THRESHOLDS

    def test_custom_hit_rate_override_relaxed(self) -> None:
        """CLI --hit-rate-threshold applies to relaxed asset classes too."""
        t = get_session_thresholds("regular", "commodity", hit_rate_override=80.0)
        assert t.nrmse_auto_pass == RELAXED_THRESHOLDS.nrmse_auto_pass
        assert t.nrmse_conditional == RELAXED_THRESHOLDS.nrmse_conditional
        assert t.hit_rate_threshold == 80.0

    def test_custom_hit_rate_override_metals(self) -> None:
        t = get_session_thresholds("regular", "metals", hit_rate_override=80.0)
        assert t.nrmse_auto_pass == RELAXED_THRESHOLDS.nrmse_auto_pass
        assert t.nrmse_conditional == RELAXED_THRESHOLDS.nrmse_conditional
        assert t.hit_rate_threshold == 80.0

    # CLI override for hit rate
    def test_custom_hit_rate_override(self) -> None:
        t = get_session_thresholds("regular", "us-equities", hit_rate_override=90.0)
        assert t.nrmse_auto_pass == REGULAR_THRESHOLDS.nrmse_auto_pass
        assert t.nrmse_conditional == REGULAR_THRESHOLDS.nrmse_conditional
        assert t.hit_rate_threshold == 90.0

    def test_custom_hit_rate_does_not_affect_extended(self) -> None:
        """CLI --hit-rate-threshold only affects regular session, not extended."""
        t = get_session_thresholds("premarket", "us-equities", hit_rate_override=90.0)
        assert t == EXTENDED_THRESHOLDS


class TestPassesBenchmark:
    """Verify pass/fail logic across sessions, modes, and edge cases."""

    # ---- Regular session ----
    def test_auto_pass_very_low_nrmse(self) -> None:
        """NRMSE below auto-pass threshold passes regardless of hit rate."""
        assert passes_benchmark(nrmse=0.005, hit_rate=50.0) is True

    def test_conditional_pass(self) -> None:
        """NRMSE between auto-pass and conditional, with sufficient hit rate."""
        assert passes_benchmark(nrmse=0.03, hit_rate=96.0, session="regular") is True

    def test_conditional_fail_low_hit_rate(self) -> None:
        """NRMSE in conditional range but hit rate too low."""
        assert passes_benchmark(nrmse=0.03, hit_rate=90.0, session="regular") is False

    def test_fail_high_nrmse(self) -> None:
        """NRMSE above conditional threshold always fails."""
        assert passes_benchmark(nrmse=0.06, hit_rate=99.0, session="regular") is False

    # ---- Extended sessions ----
    def test_premarket_auto_pass(self) -> None:
        assert passes_benchmark(nrmse=0.03, hit_rate=50.0, session="premarket") is True

    def test_premarket_conditional_pass(self) -> None:
        assert passes_benchmark(nrmse=0.10, hit_rate=90.0, session="premarket") is True

    def test_premarket_conditional_fail(self) -> None:
        assert passes_benchmark(nrmse=0.10, hit_rate=80.0, session="premarket") is False

    def test_premarket_fail_high_nrmse(self) -> None:
        assert passes_benchmark(nrmse=0.20, hit_rate=99.0, session="premarket") is False

    def test_overnight_uses_extended(self) -> None:
        # 0.03 is above regular auto-pass (0.01) but below extended auto-pass (0.05)
        assert passes_benchmark(nrmse=0.03, hit_rate=50.0, session="overnight") is True

    def test_afterhours_uses_extended(self) -> None:
        assert passes_benchmark(nrmse=0.03, hit_rate=50.0, session="afterhours") is True

    # ---- Non-US-equity uses regular thresholds even for extended session names ----
    def test_fx_premarket_uses_regular(self) -> None:
        # 0.03 is above regular auto-pass (0.01), needs hit_rate >= 95
        assert (
            passes_benchmark(nrmse=0.03, hit_rate=90.0, session="premarket", mode="fx")
            is False
        )

    # ---- Edge cases ----
    def test_nrmse_none_fails(self) -> None:
        assert passes_benchmark(nrmse=None, hit_rate=99.0) is False

    def test_boundary_nrmse_0_01_regular(self) -> None:
        """Exactly 0.01 does NOT auto-pass (strict <)."""
        # Must rely on conditional: 0.01 < 0.05 and hit_rate >= 95
        assert passes_benchmark(nrmse=0.01, hit_rate=95.0, session="regular") is True
        assert passes_benchmark(nrmse=0.01, hit_rate=94.9, session="regular") is False

    def test_boundary_nrmse_0_05_extended(self) -> None:
        """Exactly 0.05 does NOT auto-pass extended (strict <)."""
        # Must rely on conditional: 0.05 < 0.15 and hit_rate >= 85
        assert passes_benchmark(nrmse=0.05, hit_rate=85.0, session="premarket") is True
        assert passes_benchmark(nrmse=0.05, hit_rate=84.9, session="premarket") is False

    def test_boundary_hit_rate_85_extended(self) -> None:
        """Exactly 85% hit rate passes extended conditional (>=)."""
        assert passes_benchmark(nrmse=0.10, hit_rate=85.0, session="premarket") is True

    def test_boundary_hit_rate_95_regular(self) -> None:
        """Exactly 95% hit rate passes regular conditional (>=)."""
        assert passes_benchmark(nrmse=0.03, hit_rate=95.0, session="regular") is True

    # ---- Relaxed asset classes (commodity, metals) ----
    def test_commodity_auto_pass(self) -> None:
        """nrmse=0.04 auto-passes for commodity (< 0.05) but NOT for fx (>= 0.01)."""
        assert passes_benchmark(nrmse=0.04, hit_rate=50.0, mode="commodity") is True
        assert passes_benchmark(nrmse=0.04, hit_rate=50.0, mode="fx") is False

    def test_metals_auto_pass(self) -> None:
        assert passes_benchmark(nrmse=0.04, hit_rate=50.0, mode="metals") is True

    def test_commodity_conditional_pass(self) -> None:
        """nrmse=0.10 with hit_rate=90 passes commodity (< 0.15 AND >= 85)."""
        assert passes_benchmark(nrmse=0.10, hit_rate=90.0, mode="commodity") is True

    def test_commodity_conditional_fail_low_hit_rate(self) -> None:
        """nrmse=0.10 with hit_rate=80 fails commodity (< 85)."""
        assert passes_benchmark(nrmse=0.10, hit_rate=80.0, mode="commodity") is False

    def test_commodity_fail_high_nrmse(self) -> None:
        """nrmse=0.20 fails commodity (>= 0.15)."""
        assert passes_benchmark(nrmse=0.20, hit_rate=99.0, mode="commodity") is False

    def test_metals_conditional_pass(self) -> None:
        assert passes_benchmark(nrmse=0.10, hit_rate=85.0, mode="metals") is True

    def test_boundary_nrmse_0_05_relaxed(self) -> None:
        """Exactly 0.05 does NOT auto-pass relaxed (strict <)."""
        assert passes_benchmark(nrmse=0.05, hit_rate=85.0, mode="commodity") is True
        assert passes_benchmark(nrmse=0.05, hit_rate=84.9, mode="commodity") is False


class TestGetThresholdDescription:
    """Verify the human-readable threshold description strings."""

    def test_regular_description(self) -> None:
        desc = get_threshold_description("fx")
        assert "0.01" in desc
        assert "0.05" in desc
        assert "95" in desc

    def test_relaxed_description(self) -> None:
        desc = get_threshold_description("commodity")
        assert "0.05" in desc
        assert "0.15" in desc
        assert "85" in desc

    def test_metals_description(self) -> None:
        desc = get_threshold_description("metals")
        assert "0.15" in desc
        assert "85" in desc

    def test_us_equities_regular_description(self) -> None:
        desc = get_threshold_description("us-equities")
        assert "0.01" in desc
        assert "0.05" in desc
        assert "95" in desc
