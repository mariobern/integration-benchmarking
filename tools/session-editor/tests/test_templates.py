"""Templates module — schedule strings + .BLUE rewrite."""

from __future__ import annotations

import pytest

from session_editor_lib.templates import (
    ADDABLE_SESSIONS,
    CANONICAL_ORDER,
    OVER_NIGHT_SCHEDULE,
    POST_MARKET_SCHEDULE,
    PRE_MARKET_SCHEDULE,
    SCHEDULE_BY_SESSION,
    VALID_SESSIONS,
    overnight_identifier,
)


class TestScheduleConstants:
    def test_canonical_order(self):
        assert CANONICAL_ORDER == (
            "REGULAR",
            "PRE_MARKET",
            "POST_MARKET",
            "OVER_NIGHT",
        )

    def test_valid_sessions_includes_regular(self):
        assert "REGULAR" in VALID_SESSIONS
        assert set(VALID_SESSIONS) == set(CANONICAL_ORDER)

    def test_addable_excludes_regular(self):
        assert "REGULAR" not in ADDABLE_SESSIONS
        assert set(ADDABLE_SESSIONS) == {"PRE_MARKET", "POST_MARKET", "OVER_NIGHT"}

    def test_schedule_by_session_keys(self):
        assert set(SCHEDULE_BY_SESSION) == set(ADDABLE_SESSIONS)

    def test_pre_market_starts_at_0400(self):
        assert "0400-0930" in PRE_MARKET_SCHEDULE

    def test_post_market_ends_at_2000(self):
        assert "1600-2000" in POST_MARKET_SCHEDULE

    def test_overnight_has_split_session(self):
        assert "0000-0400&2000-2400" in OVER_NIGHT_SCHEDULE


class TestTemplatesMatchAAPL:
    """Templates must equal the live AAPL/922 schedule strings byte-for-byte."""

    def test_pre_market_matches_aapl(self, aapl_feed):
        live = next(
            s["marketSchedule"]
            for s in aapl_feed["marketSchedules"]
            if s["session"] == "PRE_MARKET"
        )
        assert live == PRE_MARKET_SCHEDULE

    def test_post_market_matches_aapl(self, aapl_feed):
        live = next(
            s["marketSchedule"]
            for s in aapl_feed["marketSchedules"]
            if s["session"] == "POST_MARKET"
        )
        assert live == POST_MARKET_SCHEDULE

    def test_overnight_matches_aapl(self, aapl_feed):
        live = next(
            s["marketSchedule"]
            for s in aapl_feed["marketSchedules"]
            if s["session"] == "OVER_NIGHT"
        )
        assert live == OVER_NIGHT_SCHEDULE


class TestOvernightIdentifier:
    @pytest.mark.parametrize(
        "src,want",
        [
            ("AAPL.O", "AAPL.BLUE"),
            ("IBM.N", "IBM.BLUE"),
            ("BRKb.N", "BRKb.BLUE"),
            ("BAC.A", "BAC.BLUE"),
            ("UEEC.K", "UEEC.BLUE"),
        ],
    )
    def test_known_suffixes_rewritten(self, src, want):
        assert overnight_identifier(src) == want

    def test_unknown_suffix_passes_through(self):
        # No US-equity exchange suffix → no change. Tool should never invoke
        # this path because non-US-equity feeds are filtered out, but the
        # function itself must be safe.
        assert overnight_identifier("WEIRD.XYZ") == "WEIRD.XYZ"

    def test_no_suffix_passes_through(self):
        assert overnight_identifier("AAPL") == "AAPL"
