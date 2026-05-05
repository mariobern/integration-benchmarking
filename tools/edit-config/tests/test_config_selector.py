import pytest
from lib.config_selector import parse_selector_text, SelectorError


class TestParseSelectorText:
    def test_single_id(self):
        assert parse_selector_text("922") == {922}

    def test_comma_list(self):
        assert parse_selector_text("1,2,3") == {1, 2, 3}

    def test_inclusive_range(self):
        assert parse_selector_text("100-103") == {100, 101, 102, 103}

    def test_mixed(self):
        result = parse_selector_text("100-102,205,208,300-301")
        assert result == {100, 101, 102, 205, 208, 300, 301}

    def test_whitespace_separators(self):
        assert parse_selector_text("1 2  3\n4\t5") == {1, 2, 3, 4, 5}

    def test_mixed_separators(self):
        assert parse_selector_text("1, 2\n3,4 5") == {1, 2, 3, 4, 5}

    def test_strips_line_comments(self):
        text = "100-102  # the contig run\n205 # one off\n208"
        assert parse_selector_text(text) == {100, 101, 102, 205, 208}

    def test_blank_lines_ignored(self):
        assert parse_selector_text("\n\n100\n\n200\n") == {100, 200}

    def test_dedup(self):
        assert parse_selector_text("1,1,2,2,1") == {1, 2}

    def test_overlapping_ranges_dedup(self):
        assert parse_selector_text("100-105,103-107") == {
            100,
            101,
            102,
            103,
            104,
            105,
            106,
            107,
        }

    def test_empty_input_returns_empty_set(self):
        assert parse_selector_text("") == set()
        assert parse_selector_text("   \n  ") == set()
        assert parse_selector_text("# only comments\n# more comments") == set()

    def test_invalid_token_raises(self):
        with pytest.raises(SelectorError, match="invalid token"):
            parse_selector_text("1,abc,3")

    def test_invalid_range_descending(self):
        with pytest.raises(SelectorError, match="range bounds"):
            parse_selector_text("200-100")

    def test_invalid_negative(self):
        with pytest.raises(SelectorError, match="invalid token"):
            parse_selector_text("-5")

    def test_error_includes_position(self):
        with pytest.raises(SelectorError, match="line 2"):
            parse_selector_text("100\nbadtoken\n200")
