"""Tests for the diagnostic RIC categorizer."""

from dataclasses import dataclass

import pytest

from check_benchmark_availability import categorize_equities


@dataclass
class FakeInstrument:
    ric: str


class TestCategorizeEquities:
    def test_nasdaq_dot_o(self):
        result = categorize_equities([FakeInstrument(ric="AAPL.O")])
        assert result == {"NASDAQ": 1}

    def test_nasdaq_dot_oq(self):
        result = categorize_equities([FakeInstrument(ric="MSFT.OQ")])
        assert result == {"NASDAQ": 1}

    def test_consolidated_dot_k(self):
        result = categorize_equities([FakeInstrument(ric="TWTR.K")])
        assert result == {"US Consolidated": 1}

    def test_consolidated_bare_three_char(self):
        result = categorize_equities([FakeInstrument(ric="IBM")])
        assert result == {"US Consolidated": 1}

    def test_consolidated_bare_with_lowercase_class_letter(self):
        # "BRKa" — dotted-class transform; no extension; treated as consolidated.
        result = categorize_equities([FakeInstrument(ric="BRKa")])
        assert result == {"US Consolidated": 1}

    def test_legacy_dot_n(self):
        result = categorize_equities([FakeInstrument(ric="JPM.N")])
        assert result == {"NYSE (legacy)": 1}

    def test_legacy_dot_a(self):
        result = categorize_equities([FakeInstrument(ric="LIVE.A")])
        assert result == {"NYSE Arca (legacy)": 1}

    def test_legacy_dot_z(self):
        result = categorize_equities([FakeInstrument(ric="CBOE.Z")])
        assert result == {"BATS (legacy)": 1}

    def test_non_equity_ric_falls_into_other(self):
        # FX-style RIC; not an equity.
        result = categorize_equities([FakeInstrument(ric="EUR=")])
        assert result == {"Other": 1}

    def test_mixed_counts(self):
        result = categorize_equities(
            [
                FakeInstrument(ric="AAPL.O"),
                FakeInstrument(ric="MSFT.O"),
                FakeInstrument(ric="TWTR.K"),
                FakeInstrument(ric="IBM"),
                FakeInstrument(ric="JPM.N"),
            ]
        )
        assert result["NASDAQ"] == 2
        assert result["US Consolidated"] == 2
        assert result["NYSE (legacy)"] == 1
