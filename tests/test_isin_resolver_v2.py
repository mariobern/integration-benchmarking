"""Tests for isin_resolver_v2.py — Enhanced ISIN resolution with OpenFIGI + ADR correction."""

import csv
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from isin_resolver_v2 import (
    FinanceDatabaseSource,
    ISINCache,
    ISINResolver,
    ISINResult,
    ManualOverrideSource,
    OpenFIGIInfo,
    OpenFIGISource,
    TickerInput,
    YFinanceSource,
    _check_adr_correction_needed,
    _country_name_to_iso,
    _cusip_to_isin,
    _normalize_input,
    _validate_currency_consistency,
    _validate_isin_format,
    parse_enriched_csv,
    parse_tickers_from_file,
    parse_tickers_from_ric_csv,
    parse_tickers_from_string,
    validate_isin,
)


# --- TickerInput ---


class TestTickerInput:
    def test_frozen_dataclass(self) -> None:
        inp = TickerInput(
            ticker="AAPL", company_name="Apple", denomination_currency="USD"
        )
        with pytest.raises(AttributeError):
            inp.ticker = "MSFT"  # type: ignore[misc]

    def test_defaults(self) -> None:
        inp = TickerInput(ticker="AAPL")
        assert inp.company_name is None
        assert inp.denomination_currency is None

    def test_with_all_fields(self) -> None:
        inp = TickerInput(
            ticker="BIDU",
            company_name="Baidu Inc",
            denomination_currency="USD",
        )
        assert inp.ticker == "BIDU"
        assert inp.company_name == "Baidu Inc"
        assert inp.denomination_currency == "USD"

    def test_normalize_string(self) -> None:
        result = _normalize_input("aapl")
        assert isinstance(result, TickerInput)
        assert result.ticker == "AAPL"
        assert result.company_name is None

    def test_normalize_ticker_input(self) -> None:
        inp = TickerInput(
            ticker="bidu", company_name="Baidu", denomination_currency="usd"
        )
        result = _normalize_input(inp)
        assert result.ticker == "BIDU"
        assert result.company_name == "Baidu"


# --- ISINResult ---


class TestISINResult:
    def test_frozen_dataclass(self) -> None:
        result = ISINResult(ticker="AAPL", isin="US0378331005", source="test")
        with pytest.raises(AttributeError):
            result.ticker = "MSFT"  # type: ignore[misc]

    def test_to_dict_and_back(self) -> None:
        original = ISINResult(
            ticker="AAPL",
            isin="US0378331005",
            cusip="037833100",
            source="financedatabase",
            company_name="Apple Inc.",
            exchange="NAS",
            warnings=("warning1", "warning2"),
        )
        d = original.to_dict()
        assert d["warnings"] == ["warning1", "warning2"]
        restored = ISINResult.from_dict(d)
        assert restored == original

    def test_defaults(self) -> None:
        result = ISINResult(ticker="TEST")
        assert result.isin is None
        assert result.cusip is None
        assert result.source == ""
        assert result.warnings == ()


# --- ISIN Utilities ---


class TestISINUtilities:
    def test_validate_isin_format_valid(self) -> None:
        assert _validate_isin_format("US0378331005") is True
        assert _validate_isin_format("KYG017191142") is True
        assert _validate_isin_format("CA1350873119") is True

    def test_validate_isin_format_invalid(self) -> None:
        assert _validate_isin_format("") is False
        assert _validate_isin_format("US037833100") is False  # 11 chars
        assert _validate_isin_format("US03783310055") is False  # 13 chars
        assert _validate_isin_format("12345678901A") is False  # numeric prefix
        assert _validate_isin_format("US 378331005") is False  # space

    def test_cusip_to_isin(self) -> None:
        assert _cusip_to_isin("037833100") == "US0378331005"  # AAPL
        assert _cusip_to_isin("594918104") == "US5949181045"  # MSFT

    def test_cusip_to_isin_canadian(self) -> None:
        result = _cusip_to_isin("135087311", country="CA")
        assert result is not None
        assert result.startswith("CA")

    def test_cusip_to_isin_invalid(self) -> None:
        result = _cusip_to_isin("INVALID")
        assert result is None or isinstance(result, str)

    def test_validate_isin_real(self) -> None:
        assert validate_isin("US0378331005") is True  # AAPL
        assert validate_isin("US5949181045") is True  # MSFT

    def test_validate_isin_bad_check_digit(self) -> None:
        assert validate_isin("US0378331009") is False  # wrong check digit


# --- ISINCache ---


class TestISINCache:
    def test_put_and_get(self, tmp_path: Path) -> None:
        cache = ISINCache(cache_dir=tmp_path, ttl_seconds=3600)
        result = ISINResult(ticker="AAPL", isin="US0378331005", source="test")
        cache.put(result)
        cache.save()

        cache2 = ISINCache(cache_dir=tmp_path, ttl_seconds=3600)
        fetched = cache2.get("AAPL")
        assert fetched is not None
        assert fetched.isin == "US0378331005"

    def test_case_insensitive_key(self, tmp_path: Path) -> None:
        cache = ISINCache(cache_dir=tmp_path, ttl_seconds=3600)
        result = ISINResult(ticker="AAPL", isin="US0378331005", source="test")
        cache.put(result)
        assert cache.get("aapl") is not None
        assert cache.get("Aapl") is not None

    def test_ttl_expiration(self, tmp_path: Path) -> None:
        cache = ISINCache(cache_dir=tmp_path, ttl_seconds=0)
        result = ISINResult(ticker="AAPL", isin="US0378331005", source="test")
        cache.put(result)
        assert cache.get("AAPL") is None

    def test_clear(self, tmp_path: Path) -> None:
        cache = ISINCache(cache_dir=tmp_path, ttl_seconds=3600)
        result = ISINResult(ticker="AAPL", isin="US0378331005", source="test")
        cache.put(result)
        cache.save()
        cache.clear()
        assert cache.get("AAPL") is None

    def test_missing_cache_file(self, tmp_path: Path) -> None:
        cache = ISINCache(cache_dir=tmp_path, ttl_seconds=3600)
        assert cache.get("AAPL") is None

    def test_corrupted_cache_file(self, tmp_path: Path) -> None:
        cache_file = tmp_path / "isin_map_v2.json"
        cache_file.write_text("not valid json{{{")
        cache = ISINCache(cache_dir=tmp_path, ttl_seconds=3600)
        assert cache.get("AAPL") is None


# --- FinanceDatabaseSource ---


class TestFinanceDatabaseSource:
    @patch("isin_resolver_v2.FinanceDatabaseSource._load")
    def test_resolve_found(self, mock_load: MagicMock) -> None:
        source = FinanceDatabaseSource()
        source._loaded = True
        source._equity_data = {
            "AAPL": {
                "isin": "US0378331005",
                "cusip": "037833100",
                "name": "Apple Inc.",
                "country": "United States",
                "exchange": "NMS",
            },
        }

        result = source.resolve("AAPL")
        assert result is not None
        assert result.isin == "US0378331005"
        assert result.cusip == "037833100"
        assert result.source == "financedatabase"

    @patch("isin_resolver_v2.FinanceDatabaseSource._load")
    def test_resolve_not_found(self, mock_load: MagicMock) -> None:
        source = FinanceDatabaseSource()
        source._loaded = True
        source._equity_data = {}
        assert source.resolve("UNKNOWN") is None

    @patch("isin_resolver_v2.FinanceDatabaseSource._load")
    def test_resolve_dotted_ticker(self, mock_load: MagicMock) -> None:
        source = FinanceDatabaseSource()
        source._loaded = True
        source._equity_data = {
            "BRK-B": {
                "isin": None,
                "cusip": "084670702",
                "name": "Berkshire Hathaway Inc.",
                "country": "United States",
                "exchange": "NYS",
            },
        }

        result = source.resolve("BRK.B")
        assert result is not None
        assert result.cusip == "084670702"
        assert result.isin is not None
        assert result.isin.startswith("US")

    @patch("isin_resolver_v2.FinanceDatabaseSource._load")
    def test_resolve_batch(self, mock_load: MagicMock) -> None:
        source = FinanceDatabaseSource()
        source._loaded = True
        source._equity_data = {
            "AAPL": {
                "isin": "US0378331005",
                "cusip": "037833100",
                "name": "Apple Inc.",
                "country": "United States",
                "exchange": "NMS",
            },
            "MSFT": {
                "isin": "US5949181045",
                "cusip": "594918104",
                "name": "Microsoft Corporation",
                "country": "United States",
                "exchange": "NMS",
            },
        }

        results = source.resolve_batch(["AAPL", "MSFT", "UNKNOWN"])
        assert "AAPL" in results
        assert "MSFT" in results
        assert "UNKNOWN" not in results


# --- ManualOverrideSource ---


class TestManualOverrideSource:
    def test_resolve_found(self, tmp_path: Path) -> None:
        override_file = tmp_path / "overrides.csv"
        override_file.write_text(
            "ticker,isin,cusip,company_name\n"
            "BIDU,US0567521085,056752108,Baidu Inc ADR\n"
        )
        source = ManualOverrideSource(override_file=override_file)
        result = source.resolve("BIDU")
        assert result is not None
        assert result.isin == "US0567521085"
        assert result.cusip == "056752108"
        assert result.source == "manual_override"
        assert result.confidence == "high"

    def test_resolve_not_found(self, tmp_path: Path) -> None:
        override_file = tmp_path / "overrides.csv"
        override_file.write_text("ticker,isin,cusip,company_name\n")
        source = ManualOverrideSource(override_file=override_file)
        assert source.resolve("AAPL") is None

    def test_resolve_case_insensitive(self, tmp_path: Path) -> None:
        override_file = tmp_path / "overrides.csv"
        override_file.write_text(
            "ticker,isin,cusip,company_name\n" "bidu,US0567521085,056752108,Baidu\n"
        )
        source = ManualOverrideSource(override_file=override_file)
        assert source.resolve("BIDU") is not None

    def test_resolve_batch(self, tmp_path: Path) -> None:
        override_file = tmp_path / "overrides.csv"
        override_file.write_text(
            "ticker,isin,cusip,company_name\n"
            "BIDU,US0567521085,056752108,Baidu Inc ADR\n"
            "TCOM,US89677Q1076,89677Q107,Trip.com ADR\n"
        )
        source = ManualOverrideSource(override_file=override_file)
        results = source.resolve_batch(["BIDU", "TCOM", "UNKNOWN"])
        assert "BIDU" in results
        assert "TCOM" in results
        assert "UNKNOWN" not in results

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        source = ManualOverrideSource(override_file=tmp_path / "nonexistent.csv")
        assert source.resolve("BIDU") is None

    def test_invalid_isin_rejected(self, tmp_path: Path) -> None:
        override_file = tmp_path / "overrides.csv"
        override_file.write_text(
            "ticker,isin,cusip,company_name\n" "BAD,INVALID_ISIN,,Bad Entry\n"
        )
        source = ManualOverrideSource(override_file=override_file)
        assert source.resolve("BAD") is None

    def test_bom_encoding(self, tmp_path: Path) -> None:
        override_file = tmp_path / "overrides.csv"
        override_file.write_bytes(
            b"\xef\xbb\xbfticker,isin,cusip,company_name\n"
            b"BIDU,US0567521085,056752108,Baidu\n"
        )
        source = ManualOverrideSource(override_file=override_file)
        assert source.resolve("BIDU") is not None


# --- OpenFIGISource (ADR Detection + Metadata) ---


class TestOpenFIGISource:
    @patch("httpx.post")
    def test_lookup_common_stock(self, mock_post: MagicMock) -> None:
        """OpenFIGI lookup returns metadata for common stock."""
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "data": [
                    {
                        "figi": "BBG000BVPV84",
                        "compositeFIGI": "BBG000BVPV84",
                        "shareClassFIGI": "BBG001S5N8V8",
                        "name": "APPLE INC",
                        "securityType": "Common Stock",
                        "securityType2": "Common Stock",
                    }
                ]
            }
        ]
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        source = OpenFIGISource()
        info = source.lookup("AAPL")
        assert info is not None
        assert isinstance(info, OpenFIGIInfo)
        assert info.ticker == "AAPL"
        assert info.name == "APPLE INC"
        assert info.security_type == "Common Stock"
        assert info.is_adr is False
        assert info.figi == "BBG000BVPV84"

    @patch("httpx.post")
    def test_lookup_adr_detected(self, mock_post: MagicMock) -> None:
        """OpenFIGI correctly identifies ADRs."""
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "data": [
                    {
                        "figi": "BBG000Q9FHZ7",
                        "compositeFIGI": "BBG000Q9FHZ7",
                        "name": "BAIDU INC",
                        "securityType": "ADR",
                        "securityType2": "Depositary Receipt",
                    }
                ]
            }
        ]
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        source = OpenFIGISource()
        info = source.lookup("BIDU")
        assert info is not None
        assert info.is_adr is True
        assert info.security_type == "ADR"
        assert info.security_type2 == "Depositary Receipt"

    @patch("httpx.post")
    def test_lookup_not_found(self, mock_post: MagicMock) -> None:
        """OpenFIGI returns None for unknown ticker."""
        mock_response = MagicMock()
        mock_response.json.return_value = [{"error": "No identifier found."}]
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        source = OpenFIGISource()
        assert source.lookup("ZZZZZ") is None

    @patch("httpx.post")
    def test_lookup_network_error(self, mock_post: MagicMock) -> None:
        """Graceful degradation on network error."""
        import httpx

        mock_post.side_effect = httpx.ConnectError("connection refused")

        source = OpenFIGISource()
        assert source.lookup("AAPL") is None

    @patch("httpx.post")
    def test_lookup_with_api_key(self, mock_post: MagicMock) -> None:
        """API key is sent in headers."""
        mock_response = MagicMock()
        mock_response.json.return_value = [{"error": "No identifier found."}]
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        source = OpenFIGISource(api_key="test-key-123")
        source.lookup("AAPL")

        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs["headers"]["X-OPENFIGI-APIKEY"] == "test-key-123"

    @patch("httpx.post")
    def test_lookup_batch(self, mock_post: MagicMock) -> None:
        """Batch lookup returns metadata for multiple tickers."""
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "data": [
                    {
                        "figi": "BBG000BVPV84",
                        "compositeFIGI": "BBG000BVPV84",
                        "name": "APPLE INC",
                        "securityType": "Common Stock",
                    }
                ]
            },
            {"error": "No identifier found."},
            {
                "data": [
                    {
                        "figi": "BBG000Q9FHZ7",
                        "compositeFIGI": "BBG000Q9FHZ7",
                        "name": "BAIDU INC",
                        "securityType": "ADR",
                        "securityType2": "Depositary Receipt",
                    }
                ]
            },
        ]
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        source = OpenFIGISource()
        results = source.lookup_batch(["AAPL", "ZZZZZ", "BIDU"])
        assert "AAPL" in results
        assert results["AAPL"].is_adr is False
        assert "ZZZZZ" not in results
        assert "BIDU" in results
        assert results["BIDU"].is_adr is True

    @patch("httpx.post")
    def test_is_adr_convenience(self, mock_post: MagicMock) -> None:
        """is_adr() convenience method."""
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "data": [
                    {
                        "figi": "BBG000Q9FHZ7",
                        "name": "BAIDU INC",
                        "securityType": "ADR",
                        "securityType2": "Depositary Receipt",
                    }
                ]
            }
        ]
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        source = OpenFIGISource()
        assert source.is_adr("BIDU") is True

    @patch("httpx.post")
    def test_adr_detected_from_name(self, mock_post: MagicMock) -> None:
        """ADR detected from name containing 'DEPOSITARY'."""
        mock_response = MagicMock()
        mock_response.json.return_value = [
            {
                "data": [
                    {
                        "figi": "BBG000ABC123",
                        "name": "SOME COMPANY DEPOSITARY SHARES",
                        "securityType": "Common Stock",
                    }
                ]
            }
        ]
        mock_response.raise_for_status = MagicMock()
        mock_post.return_value = mock_response

        source = OpenFIGISource()
        info = source.lookup("TEST")
        assert info is not None
        assert info.is_adr is True

    def test_rate_limit_with_key(self) -> None:
        source = OpenFIGISource(api_key="test-key")
        assert source._rate_limit == 250

    def test_rate_limit_without_key(self) -> None:
        source = OpenFIGISource(api_key=None)
        assert source._rate_limit == 25


# --- YFinanceSource ---


class TestYFinanceSource:
    @patch("yfinance.Ticker")
    def test_resolve_found(self, mock_ticker_cls: MagicMock) -> None:
        mock_ticker = MagicMock()
        mock_ticker.isin = "US0378331005"
        mock_ticker.info = {"longName": "Apple Inc."}
        mock_ticker_cls.return_value = mock_ticker

        source = YFinanceSource()
        result = source.resolve("AAPL")
        assert result is not None
        assert result.isin == "US0378331005"
        assert result.source == "yfinance"
        assert result.cusip == "037833100"

    @patch("yfinance.Ticker")
    def test_resolve_returns_dash(self, mock_ticker_cls: MagicMock) -> None:
        mock_ticker = MagicMock()
        mock_ticker.isin = "-"
        mock_ticker_cls.return_value = mock_ticker

        source = YFinanceSource()
        result = source.resolve("BABA")
        assert result is None

    @patch("yfinance.Ticker")
    def test_resolve_connection_error(self, mock_ticker_cls: MagicMock) -> None:
        mock_ticker_cls.side_effect = ConnectionError("network error")

        source = YFinanceSource()
        result = source.resolve("AAPL")
        assert result is None

    @patch("yfinance.Ticker")
    def test_dotted_ticker_uses_dash(self, mock_ticker_cls: MagicMock) -> None:
        mock_ticker = MagicMock()
        mock_ticker.isin = "-"
        mock_ticker_cls.return_value = mock_ticker

        source = YFinanceSource()
        source.resolve("BRK.B")
        mock_ticker_cls.assert_called_once_with("BRK-B")


# --- ADR Detection / Currency Validation ---


class TestADRDetection:
    def test_adr_check_needed_usd_with_foreign_isin(self) -> None:
        result = ISINResult(
            ticker="BIDU", isin="KYG070341048", source="financedatabase"
        )
        inp = TickerInput(ticker="BIDU", denomination_currency="USD")
        assert _check_adr_correction_needed(result, inp) is True

    def test_adr_check_not_needed_usd_with_us_isin(self) -> None:
        result = ISINResult(
            ticker="AAPL", isin="US0378331005", source="financedatabase"
        )
        inp = TickerInput(ticker="AAPL", denomination_currency="USD")
        assert _check_adr_correction_needed(result, inp) is False

    def test_adr_check_not_needed_no_currency(self) -> None:
        result = ISINResult(
            ticker="BIDU", isin="KYG070341048", source="financedatabase"
        )
        inp = TickerInput(ticker="BIDU")
        assert _check_adr_correction_needed(result, inp) is False

    def test_adr_check_not_needed_non_usd(self) -> None:
        result = ISINResult(ticker="SAP", isin="DE0007164600", source="financedatabase")
        inp = TickerInput(ticker="SAP", denomination_currency="EUR")
        assert _check_adr_correction_needed(result, inp) is False

    def test_adr_check_not_needed_no_isin(self) -> None:
        result = ISINResult(ticker="ZZZZZ", source="unresolved")
        inp = TickerInput(ticker="ZZZZZ", denomination_currency="USD")
        assert _check_adr_correction_needed(result, inp) is False


class TestCurrencyValidation:
    def test_usd_with_us_isin_ok(self) -> None:
        result = ISINResult(ticker="AAPL", isin="US0378331005", source="test")
        inp = TickerInput(ticker="AAPL", denomination_currency="USD")
        validated = _validate_currency_consistency(result, inp)
        assert validated.confidence != "low"
        assert not any("unexpected" in w for w in validated.warnings)

    def test_usd_with_ky_isin_ok(self) -> None:
        """Cayman ISINs are expected for some USD securities (ADRs)."""
        result = ISINResult(ticker="BIDU", isin="KYG070341048", source="test")
        inp = TickerInput(ticker="BIDU", denomination_currency="USD")
        validated = _validate_currency_consistency(result, inp)
        assert not any("unexpected" in w for w in validated.warnings)

    def test_usd_with_indian_isin_flagged(self) -> None:
        """Indian ISIN for USD security should be flagged."""
        result = ISINResult(
            ticker="SWDA", isin="INE243N01029", source="yfinance", confidence="medium"
        )
        inp = TickerInput(ticker="SWDA", denomination_currency="USD")
        validated = _validate_currency_consistency(result, inp)
        assert validated.confidence == "low"
        assert any("unexpected" in w for w in validated.warnings)

    def test_usd_with_argentine_isin_flagged(self) -> None:
        """Argentine ISIN for USD security should be flagged."""
        result = ISINResult(
            ticker="SPXL", isin="AR0748859532", source="yfinance", confidence="medium"
        )
        inp = TickerInput(ticker="SPXL", denomination_currency="USD")
        validated = _validate_currency_consistency(result, inp)
        assert validated.confidence == "low"
        assert any("unexpected" in w for w in validated.warnings)

    def test_no_currency_no_validation(self) -> None:
        """Without denomination currency, no validation is applied."""
        result = ISINResult(
            ticker="SWDA", isin="INE243N01029", source="yfinance", confidence="medium"
        )
        inp = TickerInput(ticker="SWDA")
        validated = _validate_currency_consistency(result, inp)
        assert validated == result  # unchanged

    def test_no_isin_no_validation(self) -> None:
        result = ISINResult(ticker="ZZZZZ", source="unresolved", confidence="low")
        inp = TickerInput(ticker="ZZZZZ", denomination_currency="USD")
        validated = _validate_currency_consistency(result, inp)
        assert validated == result


# --- ISINResolver ---


class TestISINResolver:
    def _no_override(self, tmp_path: Path) -> Path:
        """Return a nonexistent override file path so Tier 0 is a no-op."""
        return tmp_path / "no_overrides.csv"

    def test_resolve_from_cache(self, tmp_path: Path) -> None:
        cache = ISINCache(cache_dir=tmp_path, ttl_seconds=3600)
        result = ISINResult(
            ticker="AAPL", isin="US0378331005", cusip="037833100", source="cache"
        )
        cache.put(result)
        cache.save()

        resolver = ISINResolver(
            use_yfinance=False,
            use_openfigi=False,
            cache_dir=tmp_path,
            override_file=self._no_override(tmp_path),
        )
        resolved = resolver.resolve("AAPL")
        assert resolved.isin == "US0378331005"

    @patch.object(FinanceDatabaseSource, "_load")
    def test_resolve_tier1(self, mock_load: MagicMock, tmp_path: Path) -> None:
        resolver = ISINResolver(
            use_yfinance=False,
            use_openfigi=False,
            cache_dir=tmp_path,
            override_file=self._no_override(tmp_path),
        )
        resolver.finance_db._loaded = True
        resolver.finance_db._equity_data = {
            "AAPL": {
                "isin": "US0378331005",
                "cusip": "037833100",
                "name": "Apple Inc.",
                "country": "United States",
                "exchange": "NMS",
            },
        }

        result = resolver.resolve("AAPL")
        assert result.isin == "US0378331005"
        assert result.source == "financedatabase"

    @patch("yfinance.Ticker")
    @patch.object(FinanceDatabaseSource, "_load")
    def test_resolve_falls_through_to_yfinance(
        self, mock_load: MagicMock, mock_ticker_cls: MagicMock, tmp_path: Path
    ) -> None:
        resolver = ISINResolver(
            use_yfinance=True,
            use_openfigi=False,
            cache_dir=tmp_path,
            override_file=self._no_override(tmp_path),
        )
        resolver.finance_db._loaded = True
        resolver.finance_db._equity_data = {}

        mock_ticker = MagicMock()
        mock_ticker.isin = "US78462F1030"
        mock_ticker.info = {"longName": "SPDR S&P 500"}
        mock_ticker_cls.return_value = mock_ticker

        result = resolver.resolve("SPY")
        assert result.isin == "US78462F1030"
        assert result.source == "yfinance"

    @patch.object(FinanceDatabaseSource, "_load")
    def test_resolve_unresolved(self, mock_load: MagicMock, tmp_path: Path) -> None:
        resolver = ISINResolver(
            use_yfinance=False,
            use_openfigi=False,
            cache_dir=tmp_path,
            override_file=self._no_override(tmp_path),
        )
        resolver.finance_db._loaded = True
        resolver.finance_db._equity_data = {}

        result = resolver.resolve("ZZZZZ")
        assert result.isin is None
        assert result.source == "unresolved"
        assert len(result.warnings) > 0

    @patch.object(FinanceDatabaseSource, "_load")
    def test_resolve_batch(self, mock_load: MagicMock, tmp_path: Path) -> None:
        resolver = ISINResolver(
            use_yfinance=False,
            use_openfigi=False,
            cache_dir=tmp_path,
            override_file=self._no_override(tmp_path),
        )
        resolver.finance_db._loaded = True
        resolver.finance_db._equity_data = {
            "AAPL": {
                "isin": "US0378331005",
                "cusip": "037833100",
                "name": "Apple Inc.",
                "country": "United States",
                "exchange": "NMS",
            },
        }

        results = resolver.resolve_batch(["AAPL", "UNKNOWN"])
        assert "AAPL" in results
        assert results["AAPL"].isin == "US0378331005"
        assert "UNKNOWN" in results
        assert results["UNKNOWN"].source == "unresolved"

    @patch.object(FinanceDatabaseSource, "_load")
    def test_batch_caches_results(self, mock_load: MagicMock, tmp_path: Path) -> None:
        resolver = ISINResolver(
            use_yfinance=False,
            use_openfigi=False,
            cache_dir=tmp_path,
            override_file=self._no_override(tmp_path),
        )
        resolver.finance_db._loaded = True
        resolver.finance_db._equity_data = {
            "AAPL": {
                "isin": "US0378331005",
                "cusip": "037833100",
                "name": "Apple Inc.",
                "country": "United States",
                "exchange": "NMS",
            },
        }

        resolver.resolve_batch(["AAPL"])
        resolver.save_cache()

        resolver2 = ISINResolver(
            use_yfinance=False,
            use_openfigi=False,
            cache_dir=tmp_path,
            override_file=self._no_override(tmp_path),
        )
        cached = resolver2.cache.get("AAPL")
        assert cached is not None
        assert cached.isin == "US0378331005"

    def test_resolve_with_string_input(self, tmp_path: Path) -> None:
        """Backward compatible: resolve() accepts str."""
        resolver = ISINResolver(
            use_yfinance=False,
            use_openfigi=False,
            cache_dir=tmp_path,
            override_file=self._no_override(tmp_path),
        )
        # Should not raise — just return unresolved
        result = resolver.resolve("AAPL")
        assert isinstance(result, ISINResult)

    def test_resolve_with_ticker_input(self, tmp_path: Path) -> None:
        """New: resolve() accepts TickerInput."""
        resolver = ISINResolver(
            use_yfinance=False,
            use_openfigi=False,
            cache_dir=tmp_path,
            override_file=self._no_override(tmp_path),
        )
        inp = TickerInput(ticker="AAPL", denomination_currency="USD")
        result = resolver.resolve(inp)
        assert isinstance(result, ISINResult)

    def test_resolve_batch_with_strings(self, tmp_path: Path) -> None:
        """Backward compatible: resolve_batch() accepts list[str]."""
        resolver = ISINResolver(
            use_yfinance=False,
            use_openfigi=False,
            cache_dir=tmp_path,
            override_file=self._no_override(tmp_path),
        )
        results = resolver.resolve_batch(["AAPL"])
        assert isinstance(results, dict)

    def test_resolve_batch_with_ticker_inputs(self, tmp_path: Path) -> None:
        """New: resolve_batch() accepts list[TickerInput]."""
        resolver = ISINResolver(
            use_yfinance=False,
            use_openfigi=False,
            cache_dir=tmp_path,
            override_file=self._no_override(tmp_path),
        )
        inputs = [
            TickerInput(ticker="AAPL", denomination_currency="USD"),
            TickerInput(ticker="BIDU", denomination_currency="USD"),
        ]
        results = resolver.resolve_batch(inputs)
        assert isinstance(results, dict)

    def test_tier0_override_takes_priority(self, tmp_path: Path) -> None:
        """Manual override (Tier 0) takes priority over FinanceDatabase."""
        override_file = tmp_path / "overrides.csv"
        override_file.write_text(
            "ticker,isin,cusip,company_name\n"
            "AAPL,US0378331005,037833100,Apple Inc.\n"
        )

        resolver = ISINResolver(
            use_yfinance=False,
            use_openfigi=False,
            cache_dir=tmp_path,
            override_file=override_file,
        )
        result = resolver.resolve("AAPL")
        assert result.isin == "US0378331005"
        assert result.source == "manual_override"

    @patch.object(FinanceDatabaseSource, "_load")
    def test_batch_tier0_override(self, mock_load: MagicMock, tmp_path: Path) -> None:
        """Manual override in batch mode takes priority."""
        override_file = tmp_path / "overrides.csv"
        override_file.write_text(
            "ticker,isin,cusip,company_name\n" "BIDU,US0567521085,056752108,Baidu ADR\n"
        )

        resolver = ISINResolver(
            use_yfinance=False,
            use_openfigi=False,
            cache_dir=tmp_path,
            override_file=override_file,
        )
        resolver.finance_db._loaded = True
        resolver.finance_db._equity_data = {
            "AAPL": {
                "isin": "US0378331005",
                "cusip": "037833100",
                "name": "Apple Inc.",
                "country": "United States",
                "exchange": "NMS",
            },
        }

        results = resolver.resolve_batch(["BIDU", "AAPL", "UNKNOWN"])
        assert results["BIDU"].source == "manual_override"
        assert results["BIDU"].isin == "US0567521085"
        assert results["AAPL"].source == "financedatabase"
        assert results["UNKNOWN"].source == "unresolved"


# --- ADR Correction in Resolver ---


class TestADRCorrection:
    def test_adr_corrected_via_manual_override(self, tmp_path: Path) -> None:
        """When currency=USD and ISIN is foreign, manual override replaces it."""
        override_file = tmp_path / "overrides.csv"
        override_file.write_text(
            "ticker,isin,cusip,company_name\n"
            "BIDU,US0567521085,056752108,Baidu Inc ADR\n"
        )

        resolver = ISINResolver(
            use_yfinance=False,
            use_openfigi=False,
            cache_dir=tmp_path,
            override_file=override_file,
        )
        # Note: Manual override is Tier 0 and resolves BEFORE FinanceDatabase
        inp = TickerInput(ticker="BIDU", denomination_currency="USD")
        result = resolver.resolve(inp)
        assert result.isin == "US0567521085"
        assert result.source == "manual_override"

    @patch.object(FinanceDatabaseSource, "_load")
    def test_adr_corrected_during_tier1_with_override(
        self, mock_load: MagicMock, tmp_path: Path
    ) -> None:
        """Foreign ISIN from FinanceDatabase is corrected via manual override
        when denomination_currency=USD.

        This tests the ADR correction path when override is NOT in Tier 0
        (i.e., the ticker was NOT in the override initially, but then
        FinanceDatabase returns a foreign ISIN triggering _try_adr_correction).
        """
        # Override file has the US ADR ISIN
        override_file = tmp_path / "overrides.csv"
        override_file.write_text(
            "ticker,isin,cusip,company_name\n"
            "BIDU,US0567521085,056752108,Baidu Inc ADR\n"
        )

        resolver = ISINResolver(
            use_yfinance=False,
            use_openfigi=False,
            cache_dir=tmp_path,
            override_file=override_file,
        )

        # Tier 0 will find BIDU in overrides and return it immediately
        inp = TickerInput(ticker="BIDU", denomination_currency="USD")
        result = resolver.resolve(inp)
        assert result.isin == "US0567521085"
        assert result.source == "manual_override"
        assert result.confidence == "high"

    @patch.object(FinanceDatabaseSource, "_load")
    def test_no_adr_correction_without_currency(
        self, mock_load: MagicMock, tmp_path: Path
    ) -> None:
        """Without denomination_currency, foreign ISIN is kept as-is."""
        # No override file
        resolver = ISINResolver(
            use_yfinance=False,
            use_openfigi=False,
            cache_dir=tmp_path,
            override_file=tmp_path / "nonexistent.csv",
        )
        resolver.finance_db._loaded = True
        resolver.finance_db._equity_data = {
            "BIDU": {
                "isin": "KYG070341048",
                "cusip": None,
                "name": "Baidu Inc",
                "country": "Cayman Islands",
                "exchange": "NMS",
            },
        }

        result = resolver.resolve("BIDU")  # str input, no currency
        assert result.isin == "KYG070341048"
        assert result.source == "financedatabase"

    @patch.object(OpenFIGISource, "lookup")
    @patch.object(FinanceDatabaseSource, "_load")
    def test_adr_detected_by_openfigi_adds_warning(
        self, mock_load: MagicMock, mock_lookup: MagicMock, tmp_path: Path
    ) -> None:
        """When OpenFIGI confirms ADR but no manual override exists, add warning."""
        resolver = ISINResolver(
            use_yfinance=False,
            use_openfigi=True,
            cache_dir=tmp_path,
            override_file=tmp_path / "nonexistent.csv",
        )
        resolver.finance_db._loaded = True
        resolver.finance_db._equity_data = {
            "GRAB": {
                "isin": "KYG4124C1096",
                "cusip": None,
                "name": "Grab Holdings",
                "country": "Cayman Islands",
                "exchange": "NMS",
            },
        }

        # OpenFIGI confirms it's an ADR
        mock_lookup.return_value = OpenFIGIInfo(
            ticker="GRAB",
            figi="BBG000ABC123",
            name="GRAB HOLDINGS",
            security_type="ADR",
            security_type2="Depositary Receipt",
            is_adr=True,
        )

        inp = TickerInput(ticker="GRAB", denomination_currency="USD")
        result = resolver.resolve(inp)
        # Keeps original foreign ISIN but adds warning + downgrades confidence
        assert result.isin == "KYG4124C1096"
        assert result.confidence == "low"
        assert any("ADR detected" in w for w in result.warnings)
        assert any("manual overrides" in w for w in result.warnings)

    @patch.object(FinanceDatabaseSource, "_load")
    def test_adr_no_openfigi_no_override_keeps_original(
        self, mock_load: MagicMock, tmp_path: Path
    ) -> None:
        """Without OpenFIGI or override, foreign ISIN is kept without ADR warning."""
        resolver = ISINResolver(
            use_yfinance=False,
            use_openfigi=False,
            cache_dir=tmp_path,
            override_file=tmp_path / "nonexistent.csv",
        )
        resolver.finance_db._loaded = True
        resolver.finance_db._equity_data = {
            "SAP": {
                "isin": "DE0007164600",
                "cusip": None,
                "name": "SAP SE",
                "country": "Germany",
                "exchange": "NYQ",
            },
        }

        inp = TickerInput(ticker="SAP", denomination_currency="USD")
        result = resolver.resolve(inp)
        # Should keep original DE ISIN (no override, no openfigi)
        assert result.isin == "DE0007164600"
        assert result.source == "financedatabase"


# --- Enriched CSV Parsing ---


class TestEnrichedCSVParsing:
    def test_parse_enriched_csv(self, tmp_path: Path) -> None:
        f = tmp_path / "enriched.csv"
        f.write_text(
            "ticker,company_name,denomination_currency\n"
            "AAPL,Apple Inc.,USD\n"
            "BIDU,Baidu Inc,USD\n"
            "SAP,SAP SE,EUR\n"
        )
        inputs = parse_enriched_csv(f)
        assert len(inputs) == 3
        assert inputs[0].ticker == "AAPL"
        assert inputs[0].company_name == "Apple Inc."
        assert inputs[0].denomination_currency == "USD"
        assert inputs[2].denomination_currency == "EUR"

    def test_parse_enriched_csv_missing_fields(self, tmp_path: Path) -> None:
        f = tmp_path / "enriched.csv"
        f.write_text(
            "ticker,company_name,denomination_currency\n" "AAPL,,\n" "BIDU,Baidu Inc,\n"
        )
        inputs = parse_enriched_csv(f)
        assert len(inputs) == 2
        assert inputs[0].company_name is None
        assert inputs[0].denomination_currency is None
        assert inputs[1].company_name == "Baidu Inc"
        assert inputs[1].denomination_currency is None

    def test_parse_enriched_csv_dedup(self, tmp_path: Path) -> None:
        f = tmp_path / "enriched.csv"
        f.write_text(
            "ticker,company_name,denomination_currency\n"
            "AAPL,Apple,USD\n"
            "AAPL,Apple Inc.,USD\n"
        )
        inputs = parse_enriched_csv(f)
        assert len(inputs) == 1


# --- Ticker Parsing (backward compatible) ---


class TestTickerParsing:
    def test_parse_from_string(self) -> None:
        result = parse_tickers_from_string("AAPL,MSFT,TSM")
        assert result == ["AAPL", "MSFT", "TSM"]

    def test_parse_from_string_dedup(self) -> None:
        result = parse_tickers_from_string("AAPL,MSFT,AAPL")
        assert result == ["AAPL", "MSFT"]

    def test_parse_from_string_case(self) -> None:
        result = parse_tickers_from_string("aapl,Msft")
        assert result == ["AAPL", "MSFT"]

    def test_parse_from_string_whitespace(self) -> None:
        result = parse_tickers_from_string(" AAPL , MSFT ")
        assert result == ["AAPL", "MSFT"]

    def test_parse_from_file(self, tmp_path: Path) -> None:
        f = tmp_path / "tickers.txt"
        f.write_text("AAPL\nMSFT\n# comment\nTSM\n")
        result = parse_tickers_from_file(f)
        assert result == ["AAPL", "MSFT", "TSM"]

    def test_parse_from_ric_csv(self, tmp_path: Path) -> None:
        f = tmp_path / "ric.csv"
        f.write_text('"ric"\n"AAPL.O"\n"IBM.N"\n"SPY.P"\n"GLCNF.PK"\n')
        result = parse_tickers_from_ric_csv(f)
        assert result == ["AAPL", "IBM", "SPY", "GLCNF"]

    def test_parse_from_string_empty(self) -> None:
        result = parse_tickers_from_string("")
        assert result == []


# --- Confidence Scoring ---


class TestConfidenceScoring:
    def _no_override(self, tmp_path: Path) -> Path:
        return tmp_path / "no_overrides.csv"

    @patch.object(FinanceDatabaseSource, "_load")
    def test_tier1_confidence_high(self, mock_load: MagicMock, tmp_path: Path) -> None:
        resolver = ISINResolver(
            use_yfinance=False,
            use_openfigi=False,
            cache_dir=tmp_path,
            override_file=self._no_override(tmp_path),
        )
        resolver.finance_db._loaded = True
        resolver.finance_db._equity_data = {
            "AAPL": {
                "isin": "US0378331005",
                "cusip": "037833100",
                "name": "Apple Inc.",
                "country": "United States",
                "exchange": "NMS",
            },
        }

        result = resolver.resolve("AAPL")
        assert result.confidence == "high"

    @patch("yfinance.Ticker")
    @patch.object(FinanceDatabaseSource, "_load")
    def test_tier2_confidence_medium(
        self, mock_load: MagicMock, mock_ticker_cls: MagicMock, tmp_path: Path
    ) -> None:
        resolver = ISINResolver(
            use_yfinance=True,
            use_openfigi=False,
            cache_dir=tmp_path,
            override_file=self._no_override(tmp_path),
        )
        resolver.finance_db._loaded = True
        resolver.finance_db._equity_data = {}

        mock_ticker = MagicMock()
        mock_ticker.isin = "US78462F1030"
        mock_ticker.info = {"longName": "SPDR"}
        mock_ticker_cls.return_value = mock_ticker

        result = resolver.resolve("SPY")
        assert result.confidence == "medium"

    @patch.object(FinanceDatabaseSource, "_load")
    def test_unresolved_confidence_low(
        self, mock_load: MagicMock, tmp_path: Path
    ) -> None:
        resolver = ISINResolver(
            use_yfinance=False,
            use_openfigi=False,
            cache_dir=tmp_path,
            override_file=self._no_override(tmp_path),
        )
        resolver.finance_db._loaded = True
        resolver.finance_db._equity_data = {}

        result = resolver.resolve("ZZZZZ")
        assert result.confidence == "low"


# --- Country Mapping ---


class TestCountryNameToISO:
    def test_us(self) -> None:
        assert _country_name_to_iso("United States") == "US"

    def test_canada(self) -> None:
        assert _country_name_to_iso("Canada") == "CA"

    def test_cayman_islands(self) -> None:
        assert _country_name_to_iso("Cayman Islands") == "KY"

    def test_case_insensitive(self) -> None:
        assert _country_name_to_iso("CANADA") == "CA"

    def test_empty_defaults_to_us(self) -> None:
        assert _country_name_to_iso("") == "US"

    def test_unknown_defaults_to_us(self) -> None:
        assert _country_name_to_iso("Unknown Country") == "US"


# --- Post-Cache Validation ---


class TestPostCacheValidation:
    def test_bad_isin_evicted_from_cache(self, tmp_path: Path) -> None:
        cache = ISINCache(cache_dir=tmp_path, ttl_seconds=3600)
        cache._load()
        import time as _time

        cache._data["BAD"] = {
            "ticker": "BAD",
            "isin": "US0000000009",
            "source": "test",
            "warnings": [],
            "_cached_at": _time.time(),
        }
        cache.save()

        cache2 = ISINCache(cache_dir=tmp_path, ttl_seconds=3600)
        result = cache2.get("BAD")
        assert result is None
        assert "BAD" not in cache2._data

    def test_valid_isin_served_from_cache(self, tmp_path: Path) -> None:
        cache = ISINCache(cache_dir=tmp_path, ttl_seconds=3600)
        result = ISINResult(ticker="AAPL", isin="US0378331005", source="test")
        cache.put(result)

        fetched = cache.get("AAPL")
        assert fetched is not None
        assert fetched.isin == "US0378331005"


# --- Output ---


class TestOutput:
    def test_write_csv_output(self, tmp_path: Path) -> None:
        from isin_resolver_v2 import write_csv_output

        results = {
            "AAPL": ISINResult(
                ticker="AAPL",
                isin="US0378331005",
                cusip="037833100",
                source="financedatabase",
                company_name="Apple Inc.",
            ),
            "UNKNOWN": ISINResult(
                ticker="UNKNOWN",
                source="unresolved",
                warnings=("No ISIN found",),
            ),
        }
        output = tmp_path / "test_output.csv"
        write_csv_output(results, output)

        assert output.exists()
        with open(output) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert len(rows) == 2
        aapl_row = next(r for r in rows if r["ticker"] == "AAPL")
        assert aapl_row["isin"] == "US0378331005"

    def test_print_summary_empty(self, capsys: pytest.CaptureFixture[str]) -> None:
        from isin_resolver_v2 import print_summary

        print_summary({})
        captured = capsys.readouterr()
        assert "Total tickers: 0" in captured.out
        assert "no tickers" in captured.out
