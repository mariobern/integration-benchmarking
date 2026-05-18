"""Selector grammar."""

import pytest

from session_editor_lib.selector import parse_selector, parse_selector_lines


def test_single():
    assert parse_selector("922") == {922}


def test_range_inclusive():
    assert parse_selector("100-103") == {100, 101, 102, 103}


def test_mixed():
    assert parse_selector("1,5-7,10") == {1, 5, 6, 7, 10}


def test_whitespace():
    assert parse_selector(" 1 , 2 , 5-6 ") == {1, 2, 5, 6}


def test_empty_string():
    assert parse_selector("") == set()


def test_inverted_range_raises():
    with pytest.raises(ValueError, match="lo > hi"):
        parse_selector("10-5")


def test_lines_with_comments():
    text = """
    # leading comment
    1,2
    922   # inline comment
    1000-1002
    """
    assert parse_selector_lines(text) == {1, 2, 922, 1000, 1001, 1002}


def test_realistic_txt_file_shape():
    """The shape session-editor accepts via --feed-ids-from (mirrors edit-config)."""
    text = """\
# stable-missing-overnight.txt
921      # Equity.US.A/USD
923-925  # ABBV, ABNB, ABT
2031
2057-2059
"""
    assert parse_selector_lines(text) == {921, 923, 924, 925, 2031, 2057, 2058, 2059}
