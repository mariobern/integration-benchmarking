import pytest

from lib.min_publishers import compute_target_min_publishers


class TestComputeTargetMinPublishers:
    """Rule engine: publisher count -> target minPublishers."""

    def test_below_floor_returns_none(self):
        """2-4 publishers -> no change (None)."""
        assert compute_target_min_publishers(2) is None
        assert compute_target_min_publishers(3) is None
        assert compute_target_min_publishers(4) is None

    def test_needs_attention_returns_none(self):
        """0-1 publishers -> no change (None). NEEDS_ATTENTION handled elsewhere."""
        assert compute_target_min_publishers(0) is None
        assert compute_target_min_publishers(1) is None

    def test_mid_tier_returns_2(self):
        """5-6 publishers -> minPublishers=2."""
        assert compute_target_min_publishers(5) == 2
        assert compute_target_min_publishers(6) == 2

    def test_upper_tier_returns_3(self):
        """7+ publishers -> minPublishers=3."""
        assert compute_target_min_publishers(7) == 3
        assert compute_target_min_publishers(10) == 3
        assert compute_target_min_publishers(20) == 3

    def test_custom_floor(self):
        """--min-publisher-floor changes lower boundary."""
        assert compute_target_min_publishers(3, floor=3) == 2
        assert compute_target_min_publishers(2, floor=3) is None

    def test_custom_cutoff(self):
        """--publisher-tier-cutoff changes upper boundary."""
        assert compute_target_min_publishers(5, cutoff=5) == 3
        assert compute_target_min_publishers(6, cutoff=5) == 3
        assert compute_target_min_publishers(5, cutoff=6) == 2
