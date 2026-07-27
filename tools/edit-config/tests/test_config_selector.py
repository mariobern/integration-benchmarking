import io
from unittest.mock import patch

import pytest
from edit_config_lib.config_selector import (
    parse_selector_text,
    read_selector_file,
    SelectorError,
)


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


class TestReadSelectorFile:
    def test_reads_file(self, tmp_path):
        from edit_config_lib.config_selector import read_selector_file

        f = tmp_path / "feeds.txt"
        f.write_text("100-102\n205\n# trailing\n208\n", encoding="utf-8")
        assert read_selector_file(f) == {100, 101, 102, 205, 208}

    def test_reads_stdin_when_dash(self):
        from edit_config_lib.config_selector import read_selector_file

        with patch("sys.stdin", io.StringIO("1,2,3\n4-6\n")):
            assert read_selector_file("-") == {1, 2, 3, 4, 5, 6}

    def test_missing_file_raises(self, tmp_path):
        from edit_config_lib.config_selector import read_selector_file

        with pytest.raises(FileNotFoundError):
            read_selector_file(tmp_path / "does_not_exist.txt")

    def test_invalid_token_includes_line_number(self, tmp_path):
        from edit_config_lib.config_selector import read_selector_file, SelectorError

        f = tmp_path / "feeds.txt"
        f.write_text("100\nbad\n200", encoding="utf-8")
        with pytest.raises(SelectorError, match="line 2"):
            read_selector_file(f)


class TestReadSelectorFileCsv:
    def test_csv_reads_first_column_only(self, tmp_path):
        # The shape of jp_kr.csv: feed_id, date, mode
        p = tmp_path / "jp_kr.csv"
        p.write_text(
            "1990, 2026-07-24, jp-equities\n"
            "2023, 2026-07-24, jp-equities\n"
            "2166, 2026-07-24, kr-equities\n",
            encoding="utf-8",
        )
        assert read_selector_file(p) == {1990, 2023, 2166}

    def test_csv_skips_header_row(self, tmp_path):
        p = tmp_path / "feeds.csv"
        p.write_text(
            "feed_id,date,mode\n1990,2026-07-24,jp-equities\n", encoding="utf-8"
        )
        assert read_selector_file(p) == {1990}

    def test_csv_supports_ranges_in_column_one(self, tmp_path):
        p = tmp_path / "feeds.csv"
        p.write_text("100-102,2026-07-24,fx\n205,2026-07-24,fx\n", encoding="utf-8")
        assert read_selector_file(p) == {100, 101, 102, 205}

    def test_csv_ignores_blank_lines_and_comments(self, tmp_path):
        p = tmp_path / "feeds.csv"
        p.write_text(
            "# jp/kr batch\n\n1990, 2026-07-24, jp-equities\n\n", encoding="utf-8"
        )
        assert read_selector_file(p) == {1990}

    def test_non_csv_path_stays_strict(self, tmp_path):
        p = tmp_path / "ids.txt"
        p.write_text("1990, 2026-07-24, jp-equities\n", encoding="utf-8")
        with pytest.raises(SelectorError):
            read_selector_file(p)

    def test_plain_id_csv_still_works(self, tmp_path):
        p = tmp_path / "ids.csv"
        p.write_text("1990\n2023\n", encoding="utf-8")
        assert read_selector_file(p) == {1990, 2023}
