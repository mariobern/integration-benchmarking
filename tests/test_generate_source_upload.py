"""Tests for generate_source_upload.py — RIC resolution and source upload CSV generation."""

import csv
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from generate_source_upload import (
    ClickHouseLookup,
    NasdaqTraderSource,
    SourceUploadRow,
    TickerInfo,
    USStockSymbolsSource,
    build_rows,
    classify_asset,
    parse_tickers_from_file,
    parse_tickers_from_string,
    resolve_tickers,
    ticker_to_ric_base,
    validate_ric,
    validate_ticker,
    write_csv,
)


# --- ticker_to_ric_base ---


class TestTickerToRicBase:
    def test_simple_ticker(self) -> None:
        assert ticker_to_ric_base("AAPL") == "AAPL"

    def test_single_char_ticker(self) -> None:
        assert ticker_to_ric_base("A") == "A"

    def test_dotted_share_class_b(self) -> None:
        assert ticker_to_ric_base("BRK.B") == "BRKb"

    def test_dotted_share_class_a(self) -> None:
        assert ticker_to_ric_base("BRK.A") == "BRKa"

    def test_dotted_bf_b(self) -> None:
        assert ticker_to_ric_base("BF.B") == "BFb"

    def test_lowercase_input(self) -> None:
        assert ticker_to_ric_base("brk.b") == "BRKb"

    def test_no_dot(self) -> None:
        assert ticker_to_ric_base("MSFT") == "MSFT"

    def test_multi_char_after_dot_unchanged(self) -> None:
        """Multi-character suffix after dot is not a share class."""
        assert ticker_to_ric_base("BRK.BA") == "BRK.BA"

    def test_numeric_after_dot_unchanged(self) -> None:
        assert ticker_to_ric_base("TEST.1") == "TEST.1"


# --- validate_ticker ---


class TestValidateTicker:
    def test_valid_simple(self) -> None:
        assert validate_ticker("AAPL") is True

    def test_valid_single_letter(self) -> None:
        assert validate_ticker("A") is True

    def test_valid_five_letters(self) -> None:
        assert validate_ticker("GOOGL") is True

    def test_valid_dotted(self) -> None:
        assert validate_ticker("BRK.B") is True

    def test_invalid_too_long(self) -> None:
        assert validate_ticker("TOOLONG") is False

    def test_invalid_numeric(self) -> None:
        assert validate_ticker("123") is False

    def test_invalid_empty(self) -> None:
        assert validate_ticker("") is False

    def test_invalid_multi_char_class(self) -> None:
        assert validate_ticker("BRK.BA") is False

    def test_lowercase_accepted(self) -> None:
        assert validate_ticker("aapl") is True


# --- validate_ric ---


class TestValidateRic:
    def test_valid_nyse(self) -> None:
        assert validate_ric("AAPL.N") is True

    def test_valid_nasdaq(self) -> None:
        assert validate_ric("AAPL.O") is True

    def test_valid_nasdaq_oq(self) -> None:
        assert validate_ric("MSFT.OQ") is True

    def test_valid_arca(self) -> None:
        assert validate_ric("SPY.P") is True

    def test_valid_bats(self) -> None:
        assert validate_ric("IBM.Z") is True

    def test_valid_dotted_share_class(self) -> None:
        assert validate_ric("BRKb.N") is True

    def test_valid_pk(self) -> None:
        assert validate_ric("GLCNF.PK") is True

    def test_valid_toronto(self) -> None:
        assert validate_ric("SHOP.TO") is True

    def test_invalid_no_dot(self) -> None:
        assert validate_ric("AAPL") is False

    def test_invalid_empty(self) -> None:
        assert validate_ric("") is False

    def test_invalid_wrong_suffix(self) -> None:
        assert validate_ric("AAPL.X") is False

    def test_invalid_numeric_base(self) -> None:
        assert validate_ric("123.N") is False

    def test_invalid_too_long_base(self) -> None:
        assert validate_ric("TOOLONGX.N") is False


# --- classify_asset ---


class TestClassifyAsset:
    def test_plain_equity(self) -> None:
        assert classify_asset("Apple Inc.") == "Equity"

    def test_adr_keyword_depositary(self) -> None:
        assert (
            classify_asset("Taiwan Semiconductor American Depositary Shares")
            == "American Depositary Shares"
        )

    def test_adr_keyword_ads(self) -> None:
        assert (
            classify_asset("Alibaba Group Holding Limited ADS")
            == "American Depositary Shares"
        )

    def test_non_us_country(self) -> None:
        assert (
            classify_asset("Some Company", country="United Kingdom")
            == "American Depositary Shares"
        )

    def test_us_country(self) -> None:
        assert classify_asset("Some Company", country="United States") == "Equity"

    def test_empty_country_is_equity(self) -> None:
        assert classify_asset("Some Company", country="") == "Equity"

    def test_case_insensitive_keyword(self) -> None:
        assert (
            classify_asset("AMERICAN DEPOSITARY SHARES") == "American Depositary Shares"
        )


# --- NasdaqTraderSource ---


class TestNasdaqTraderSource:
    def _make_source_with_data(self) -> NasdaqTraderSource:
        """Create a NasdaqTraderSource with pre-loaded test data."""
        source = NasdaqTraderSource()
        source._loaded = True
        source._nasdaq_tickers = {
            "AAPL": "Apple Inc. - Common Stock",
            "MSFT": "Microsoft Corporation - Common Stock",
            "GOOGL": "Alphabet Inc. - Class A Common Stock",
        }
        source._other_tickers = {
            "IBM": ("N", "International Business Machines Corp"),
            "BRK.B": ("N", "Berkshire Hathaway Inc. - Class B"),
            "SPY": ("P", "SPDR S&P 500 ETF Trust"),
            "GE": ("N", "General Electric Company"),
            "TSM": ("N", "Taiwan Semiconductor"),
        }
        return source

    def test_resolve_nasdaq_ticker(self) -> None:
        source = self._make_source_with_data()
        result = source.resolve("AAPL")
        assert result is not None
        ric, name = result
        assert ric == "AAPL.O"
        assert "Apple" in name

    def test_resolve_nyse_ticker(self) -> None:
        source = self._make_source_with_data()
        result = source.resolve("IBM")
        assert result is not None
        ric, name = result
        assert ric == "IBM.N"

    def test_resolve_arca_ticker(self) -> None:
        source = self._make_source_with_data()
        result = source.resolve("SPY")
        assert result is not None
        ric, name = result
        assert ric == "SPY.P"

    def test_resolve_dotted_ticker(self) -> None:
        source = self._make_source_with_data()
        result = source.resolve("BRK.B")
        assert result is not None
        ric, name = result
        assert ric == "BRKb.N"
        assert "Berkshire" in name

    def test_resolve_not_found(self) -> None:
        source = self._make_source_with_data()
        assert source.resolve("ZZZZZZ") is None

    def test_resolve_case_insensitive(self) -> None:
        source = self._make_source_with_data()
        result = source.resolve("aapl")
        assert result is not None
        assert result[0] == "AAPL.O"

    def test_get_exchange_suffix_nasdaq(self) -> None:
        source = self._make_source_with_data()
        assert source.get_exchange_suffix("AAPL") == ".O"

    def test_get_exchange_suffix_nyse(self) -> None:
        source = self._make_source_with_data()
        assert source.get_exchange_suffix("IBM") == ".N"

    def test_get_exchange_suffix_arca(self) -> None:
        source = self._make_source_with_data()
        assert source.get_exchange_suffix("SPY") == ".P"

    def test_get_exchange_suffix_not_found(self) -> None:
        source = self._make_source_with_data()
        assert source.get_exchange_suffix("UNKNOWN") is None


# --- parse_tickers ---


class TestParseTickers:
    def test_parse_from_string_basic(self) -> None:
        result = parse_tickers_from_string("AAPL,MSFT,TSM")
        assert result == ["AAPL", "MSFT", "TSM"]

    def test_parse_from_string_dedup(self) -> None:
        result = parse_tickers_from_string("AAPL,MSFT,AAPL")
        assert result == ["AAPL", "MSFT"]

    def test_parse_from_string_strips_whitespace(self) -> None:
        result = parse_tickers_from_string(" AAPL , MSFT ")
        assert result == ["AAPL", "MSFT"]

    def test_parse_from_string_skips_invalid(
        self, capsys: pytest.CaptureFixture[str]
    ) -> None:
        result = parse_tickers_from_string("AAPL,123,MSFT")
        assert result == ["AAPL", "MSFT"]

    def test_parse_from_file_basic(self, tmp_path: Path) -> None:
        f = tmp_path / "tickers.txt"
        f.write_text("AAPL\nMSFT\n# comment\nTSM\n")
        result = parse_tickers_from_file(f)
        assert result == ["AAPL", "MSFT", "TSM"]

    def test_parse_from_file_skips_header(self, tmp_path: Path) -> None:
        f = tmp_path / "tickers.csv"
        f.write_text("ticker,extra\nAAPL,foo\nMSFT,bar\n")
        result = parse_tickers_from_file(f)
        assert result == ["AAPL", "MSFT"]

    def test_parse_from_file_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.txt"
        f.write_text("")
        result = parse_tickers_from_file(f)
        assert result == []


# --- resolve_tickers ---


class TestResolveTickers:
    def _make_nasdaq_source(self) -> NasdaqTraderSource:
        source = NasdaqTraderSource()
        source._loaded = True
        source._nasdaq_tickers = {
            "AAPL": "Apple Inc.",
            "MSFT": "Microsoft Corporation",
        }
        source._other_tickers = {
            "IBM": ("N", "International Business Machines"),
            "TSM": ("N", "Taiwan Semiconductor"),
            "BRK.B": ("N", "Berkshire Hathaway Inc. - Class B"),
        }
        return source

    def test_tier1_datascope_single_ric(self) -> None:
        """When Datascope returns one RIC, use it with high confidence."""
        mock_ch = MagicMock(spec=ClickHouseLookup)
        mock_ch.lookup_datascope_rics.return_value = {"AAPL": ["AAPL.O"]}
        mock_ch.lookup_lazer_ids.return_value = {"AAPL": 922}
        nasdaq = self._make_nasdaq_source()

        results = resolve_tickers(["AAPL"], mock_ch, nasdaq, None)
        assert len(results) == 1
        assert results[0].ric == "AAPL.O"
        assert results[0].ric_source == "datascope"
        assert results[0].pyth_lazer_id == 922
        assert results[0].confidence == "high"

    def test_tier1_datascope_multiple_rics_uses_nasdaq_match(self) -> None:
        """When Datascope returns multiple RICs, prefer NASDAQ Trader exchange match."""
        mock_ch = MagicMock(spec=ClickHouseLookup)
        # TSM.Z has more rows (listed first) but TSM.N matches NASDAQ Trader
        mock_ch.lookup_datascope_rics.return_value = {"TSM": ["TSM.Z", "TSM.N"]}
        mock_ch.lookup_lazer_ids.return_value = {}
        nasdaq = self._make_nasdaq_source()

        results = resolve_tickers(["TSM"], mock_ch, nasdaq, None)
        assert len(results) == 1
        # Should pick TSM.N (matches NASDAQ Trader) over TSM.Z (higher row count)
        assert results[0].ric == "TSM.N"
        assert results[0].ric_source == "datascope"
        assert any("Multiple" in w for w in results[0].warnings)

    def test_tier1_datascope_multiple_rics_prefers_primary(self) -> None:
        """When no NASDAQ Trader match, prefer primary exchange."""
        mock_ch = MagicMock(spec=ClickHouseLookup)
        mock_ch.lookup_datascope_rics.return_value = {"XYZ": ["XYZ.Z", "XYZ.N"]}
        mock_ch.lookup_lazer_ids.return_value = {}
        # XYZ not in NASDAQ Trader
        nasdaq = NasdaqTraderSource()
        nasdaq._loaded = True
        nasdaq._nasdaq_tickers = {}
        nasdaq._other_tickers = {}

        results = resolve_tickers(["XYZ"], mock_ch, nasdaq, None)
        assert results[0].ric == "XYZ.N"  # primary exchange preferred

    def test_tier1_datascope_multiple_rics_row_count_tiebreaker(self) -> None:
        """When no NASDAQ Trader match and no primary exchange, use row count."""
        mock_ch = MagicMock(spec=ClickHouseLookup)
        mock_ch.lookup_datascope_rics.return_value = {"XYZ": ["XYZ.Z", "XYZ.K"]}
        mock_ch.lookup_lazer_ids.return_value = {}
        nasdaq = NasdaqTraderSource()
        nasdaq._loaded = True
        nasdaq._nasdaq_tickers = {}
        nasdaq._other_tickers = {}

        results = resolve_tickers(["XYZ"], mock_ch, nasdaq, None)
        assert results[0].ric == "XYZ.Z"  # first = highest row count

    def test_tier2_nasdaq_trader_fallback(self) -> None:
        """When Datascope has no result, fall back to NASDAQ Trader."""
        mock_ch = MagicMock(spec=ClickHouseLookup)
        mock_ch.lookup_datascope_rics.return_value = {}
        mock_ch.lookup_lazer_ids.return_value = {}
        nasdaq = self._make_nasdaq_source()

        results = resolve_tickers(["IBM"], mock_ch, nasdaq, None)
        assert len(results) == 1
        assert results[0].ric == "IBM.N"
        assert results[0].ric_source == "nasdaq_trader"
        assert results[0].confidence == "medium"

    def test_tier3_default_fallback(self) -> None:
        """When neither Datascope nor NASDAQ Trader has the ticker, default to .N."""
        mock_ch = MagicMock(spec=ClickHouseLookup)
        mock_ch.lookup_datascope_rics.return_value = {}
        mock_ch.lookup_lazer_ids.return_value = {}
        nasdaq = self._make_nasdaq_source()

        results = resolve_tickers(["ZZZZ"], mock_ch, nasdaq, None)
        assert len(results) == 1
        assert results[0].ric == "ZZZZ.N"
        assert results[0].ric_source == "default"
        assert results[0].confidence == "low"
        assert any("defaulting" in w for w in results[0].warnings)

    def test_no_clickhouse_mode(self) -> None:
        """When ClickHouse is None, skip Tier 1 entirely."""
        nasdaq = self._make_nasdaq_source()

        results = resolve_tickers(["AAPL"], None, nasdaq, None)
        assert len(results) == 1
        assert results[0].ric == "AAPL.O"
        assert results[0].ric_source == "nasdaq_trader"
        assert results[0].confidence == "medium"

    def test_dotted_ticker_ric_base(self) -> None:
        """BRK.B should produce BRKb.N via NASDAQ Trader."""
        nasdaq = self._make_nasdaq_source()
        results = resolve_tickers(["BRK.B"], None, nasdaq, None)
        assert len(results) == 1
        assert results[0].ric == "BRKb.N"

    def test_name_resolution_from_nasdaq(self) -> None:
        """Datascope doesn't provide names; should use NASDAQ Trader for name."""
        mock_ch = MagicMock(spec=ClickHouseLookup)
        mock_ch.lookup_datascope_rics.return_value = {"AAPL": ["AAPL.O"]}
        mock_ch.lookup_lazer_ids.return_value = {}
        nasdaq = self._make_nasdaq_source()

        results = resolve_tickers(["AAPL"], mock_ch, nasdaq, None)
        assert results[0].name == "Apple Inc."

    def test_confidence_manual_review_on_warnings(self) -> None:
        """Datascope with multiple RICs should get manual_review confidence."""
        mock_ch = MagicMock(spec=ClickHouseLookup)
        mock_ch.lookup_datascope_rics.return_value = {"TSM": ["TSM.N", "TSM.Z"]}
        mock_ch.lookup_lazer_ids.return_value = {}
        nasdaq = self._make_nasdaq_source()

        results = resolve_tickers(["TSM"], mock_ch, nasdaq, None)
        assert results[0].confidence == "manual_review"


# --- build_rows ---


class TestBuildRows:
    def test_basic_row_building(self) -> None:
        infos = [
            TickerInfo(
                ticker="AAPL",
                ric="AAPL.O",
                name="Apple Inc.",
                pyth_lazer_id=922,
                confidence="high",
            ),
        ]
        rows = build_rows(infos)
        assert len(rows) == 1
        row = rows[0]
        assert row.source_value == "AAPL.O"
        assert row.source_type == "RIC"
        assert row.pyth_id == "equity.aapl"
        assert row.pythnet_id == "Equity.US.AAPL/USD"
        assert row.pyth_lazer_id == "922"
        assert row.ticker == "AAPL"
        assert row.asset_full_name == "Apple Inc."
        assert row.confidence == "high"

    def test_no_lazer_id(self) -> None:
        infos = [TickerInfo(ticker="TSM", ric="TSM.N", name="TSMC")]
        rows = build_rows(infos)
        assert rows[0].pyth_lazer_id == ""


# --- write_csv ---


class TestWriteCsv:
    def test_output_format(self, tmp_path: Path) -> None:
        rows = [
            SourceUploadRow(
                source_value="AAPL.O",
                pyth_id="equity.aapl",
                pythnet_id="Equity.US.AAPL/USD",
                pyth_lazer_id="922",
                ticker="AAPL",
                asset_full_name="Apple Inc.",
                asset_class="Equity",
                confidence="high",
            ),
        ]
        output = tmp_path / "test_output.csv"
        write_csv(rows, output)

        assert output.exists()
        lines = output.read_text().splitlines()
        # Header has spaces after commas
        assert lines[0].startswith("source_value, source_type,")
        assert "confidence" in lines[0]
        # Data rows have no spaces after commas
        assert "AAPL.O,RIC," in lines[1]
        assert "high" in lines[1]

    def test_all_fields_present(self, tmp_path: Path) -> None:
        rows = [
            SourceUploadRow(
                source_value="TSM.N",
                pyth_id="equity.tsm",
                pythnet_id="Equity.US.TSM/USD",
                pyth_lazer_id="1436",
                ticker="TSM",
                asset_full_name="TSMC",
                asset_class="American Depositary Shares",
                confidence="medium",
            ),
        ]
        output = tmp_path / "test_output.csv"
        write_csv(rows, output)

        with open(output) as f:
            lines = f.readlines()
        data_line = lines[1].strip()
        fields = data_line.split(",")
        assert len(fields) == 11  # 10 original + confidence
        assert fields[0] == "TSM.N"  # source_value
        assert fields[1] == "RIC"  # source_type

    def test_empty_rows(self, tmp_path: Path) -> None:
        output = tmp_path / "empty.csv"
        write_csv([], output)
        assert output.exists()
        lines = output.read_text().splitlines()
        assert len(lines) == 1  # header only
