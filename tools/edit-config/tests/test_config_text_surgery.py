import pytest
from lib.config_text_surgery import find_matching_close


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
