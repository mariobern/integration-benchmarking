from pathlib import Path

import pytest
from lib.config_text_surgery import find_feed_block, find_matching_close

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "after_sample.json"


class TestFindMatchingClose:
    def test_simple_object(self):
        s = "{}"
        assert find_matching_close(s, 0) == 1

    def test_simple_array(self):
        s = "[]"
        assert find_matching_close(s, 0) == 1

    def test_nested_object(self):
        s = '{"a": {"b": 1}}'
        assert find_matching_close(s, 0) == len(s) - 1

    def test_nested_array(self):
        s = "[[1, 2], [3, 4]]"
        assert find_matching_close(s, 0) == len(s) - 1

    def test_string_with_close_brace(self):
        s = '{"a": "}"}'
        assert find_matching_close(s, 0) == len(s) - 1

    def test_string_with_close_bracket(self):
        s = '["]", "x"]'
        assert find_matching_close(s, 0) == len(s) - 1

    def test_string_with_escaped_quote(self):
        s = '{"a": "he said \\"hi\\""}'
        assert find_matching_close(s, 0) == len(s) - 1

    def test_string_with_escaped_backslash_then_quote(self):
        # "abc\\" — backslash is escaped, the quote then closes the string
        s = '{"a": "abc\\\\"}'
        assert find_matching_close(s, 0) == len(s) - 1

    def test_starts_at_inner_open(self):
        s = '{"a": {"b": 1}}'
        # Inner { starts at index 6 (after '"a": ')
        assert find_matching_close(s, 6) == 13

    def test_unbalanced_returns_none(self):
        assert find_matching_close("{[}", 0) is None
        assert find_matching_close("{", 0) is None

    def test_offset_not_on_open_returns_none(self):
        assert find_matching_close('{"a": 1}', 1) is None


class TestFindFeedBlock:
    def setup_method(self):
        self.raw = FIXTURE_PATH.read_text(encoding="utf-8")

    def test_finds_first_feed(self):
        bounds = find_feed_block(self.raw, 1)
        assert bounds is not None
        start, end = bounds
        block = self.raw[start:end]
        assert block.startswith("{")
        assert block.endswith("}")
        assert '"feedId": 1' in block

    def test_finds_feed_922(self):
        bounds = find_feed_block(self.raw, 922)
        assert bounds is not None
        start, end = bounds
        block = self.raw[start:end]
        assert '"feedId": 922' in block
        assert '"symbol": "Equity.US.AAPL/USD"' in block

    def test_missing_feed_returns_none(self):
        assert find_feed_block(self.raw, 99999) is None

    def test_does_not_match_substring_of_id(self):
        # feedId 100 should not be matched by a search for 10
        assert find_feed_block(self.raw, 10) is None
