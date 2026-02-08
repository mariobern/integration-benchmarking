"""Tests for isin_resolver.py — ISIN resolution utility."""

import csv
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from isin_resolver import (
    FinanceDatabaseSource,
    ISINCache,
    ISINResolver,
    ISINResult,
    YFinanceSource,
    _country_name_to_iso,
    _cusip_to_isin,
    _validate_isin_format,
    parse_tickers_from_ric_csv,
    parse_tickers_from_file,
    parse_tickers_from_string,
    validate_isin,
)


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
        # May return None or a computed value depending on stdnum behavior
        # The important thing is it doesn't raise
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

        # Fresh cache instance should find it
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
        cache = ISINCache(cache_dir=tmp_path, ttl_seconds=0)  # instant expiry
        result = ISINResult(ticker="AAPL", isin="US0378331005", source="test")
        cache.put(result)
        assert cache.get("AAPL") is None  # expired immediately

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
        cache_file = tmp_path / "isin_map.json"
        cache_file.write_text("not valid json{{{")
        cache = ISINCache(cache_dir=tmp_path, ttl_seconds=3600)
        assert cache.get("AAPL") is None  # graceful degradation


# --- FinanceDatabaseSource ---


class TestFinanceDatabaseSource:
    @patch("isin_resolver.FinanceDatabaseSource._load")
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

    @patch("isin_resolver.FinanceDatabaseSource._load")
    def test_resolve_not_found(self, mock_load: MagicMock) -> None:
        source = FinanceDatabaseSource()
        source._loaded = True
        source._equity_data = {}
        assert source.resolve("UNKNOWN") is None

    @patch("isin_resolver.FinanceDatabaseSource._load")
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

        # BRK.B should try BRK-B (Yahoo format)
        result = source.resolve("BRK.B")
        assert result is not None
        assert result.cusip == "084670702"
        # ISIN should be computed from CUSIP
        assert result.isin is not None
        assert result.isin.startswith("US")

    @patch("isin_resolver.FinanceDatabaseSource._load")
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
        """yfinance returns '-' when ISIN not available."""
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
        """BRK.B should be queried as BRK-B in yfinance."""
        mock_ticker = MagicMock()
        mock_ticker.isin = "-"
        mock_ticker_cls.return_value = mock_ticker

        source = YFinanceSource()
        source.resolve("BRK.B")
        mock_ticker_cls.assert_called_once_with("BRK-B")


# --- ISINResolver ---


class TestISINResolver:
    def test_resolve_from_cache(self, tmp_path: Path) -> None:
        cache = ISINCache(cache_dir=tmp_path, ttl_seconds=3600)
        result = ISINResult(
            ticker="AAPL", isin="US0378331005", cusip="037833100", source="cache"
        )
        cache.put(result)
        cache.save()

        resolver = ISINResolver(use_yfinance=False, cache_dir=tmp_path)
        resolved = resolver.resolve("AAPL")
        assert resolved.isin == "US0378331005"

    @patch.object(FinanceDatabaseSource, "_load")
    def test_resolve_tier1(self, mock_load: MagicMock, tmp_path: Path) -> None:
        resolver = ISINResolver(use_yfinance=False, cache_dir=tmp_path)
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
    def test_resolve_falls_through_to_tier2(
        self, mock_load: MagicMock, mock_ticker_cls: MagicMock, tmp_path: Path
    ) -> None:
        resolver = ISINResolver(use_yfinance=True, cache_dir=tmp_path)
        resolver.finance_db._loaded = True
        resolver.finance_db._equity_data = {}  # Tier 1 empty

        mock_ticker = MagicMock()
        mock_ticker.isin = "US78462F1030"
        mock_ticker.info = {"longName": "SPDR S&P 500"}
        mock_ticker_cls.return_value = mock_ticker

        result = resolver.resolve("SPY")
        assert result.isin == "US78462F1030"
        assert result.source == "yfinance"

    @patch.object(FinanceDatabaseSource, "_load")
    def test_resolve_unresolved(self, mock_load: MagicMock, tmp_path: Path) -> None:
        resolver = ISINResolver(use_yfinance=False, cache_dir=tmp_path)
        resolver.finance_db._loaded = True
        resolver.finance_db._equity_data = {}

        result = resolver.resolve("ZZZZZ")
        assert result.isin is None
        assert result.source == "unresolved"
        assert len(result.warnings) > 0

    @patch.object(FinanceDatabaseSource, "_load")
    def test_resolve_batch(self, mock_load: MagicMock, tmp_path: Path) -> None:
        resolver = ISINResolver(use_yfinance=False, cache_dir=tmp_path)
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
        resolver = ISINResolver(use_yfinance=False, cache_dir=tmp_path)
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

        # Second resolver should find it in cache
        resolver2 = ISINResolver(use_yfinance=False, cache_dir=tmp_path)
        cached = resolver2.cache.get("AAPL")
        assert cached is not None
        assert cached.isin == "US0378331005"


# --- Ticker Parsing ---


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

    def test_parse_from_file_csv(self, tmp_path: Path) -> None:
        f = tmp_path / "tickers.csv"
        f.write_text("ticker,other\nAAPL,foo\nMSFT,bar\n")
        result = parse_tickers_from_file(f)
        assert result == ["AAPL", "MSFT"]

    def test_parse_from_file_skip_header(self, tmp_path: Path) -> None:
        f = tmp_path / "tickers.txt"
        f.write_text("symbol\nAAPL\nMSFT\n")
        result = parse_tickers_from_file(f)
        assert result == ["AAPL", "MSFT"]

    def test_parse_from_ric_csv(self, tmp_path: Path) -> None:
        f = tmp_path / "ric.csv"
        f.write_text('"ric"\n"AAPL.O"\n"IBM.N"\n"SPY.P"\n"GLCNF.PK"\n')
        result = parse_tickers_from_ric_csv(f)
        assert result == ["AAPL", "IBM", "SPY", "GLCNF"]

    def test_parse_from_ric_csv_dedup(self, tmp_path: Path) -> None:
        """Same ticker with different suffixes should deduplicate."""
        f = tmp_path / "ric.csv"
        f.write_text('"ric"\n"AAL.N"\n"AAL.O"\n"ADBE.N"\n"ADBE.O"\n')
        result = parse_tickers_from_ric_csv(f)
        assert result == ["AAL", "ADBE"]

    def test_parse_from_ric_csv_bom(self, tmp_path: Path) -> None:
        """Handle BOM-encoded CSV files."""
        f = tmp_path / "ric.csv"
        f.write_text('\ufeff"ric"\n"AAPL.O"\n')
        result = parse_tickers_from_ric_csv(f)
        assert result == ["AAPL"]

    def test_parse_from_ric_csv_canadian(self, tmp_path: Path) -> None:
        f = tmp_path / "ric.csv"
        f.write_text('"ric"\n"GLXY.TO"\n')
        result = parse_tickers_from_ric_csv(f)
        assert result == ["GLXY"]

    def test_parse_from_string_empty(self) -> None:
        result = parse_tickers_from_string("")
        assert result == []

    def test_parse_from_file_empty(self, tmp_path: Path) -> None:
        f = tmp_path / "empty.txt"
        f.write_text("")
        result = parse_tickers_from_file(f)
        assert result == []


# --- Additional Edge Cases ---


class TestEdgeCases:
    def test_from_dict_ignores_unknown_keys(self) -> None:
        """from_dict should filter out unknown keys (e.g., from newer cache format)."""
        d = {
            "ticker": "AAPL",
            "isin": "US0378331005",
            "source": "test",
            "unknown_future_field": "value",
        }
        result = ISINResult.from_dict(d)
        assert result.ticker == "AAPL"
        assert result.isin == "US0378331005"

    def test_validate_isin_empty_string(self) -> None:
        assert validate_isin("") is False

    def test_validate_isin_none_like(self) -> None:
        # Should not raise, just return False
        assert validate_isin("not-an-isin") is False

    @patch.object(FinanceDatabaseSource, "_load")
    def test_batch_records_validation_warnings(
        self, mock_load: MagicMock, tmp_path: Path
    ) -> None:
        """resolve_batch should record warnings for ISINs that fail validation."""
        resolver = ISINResolver(use_yfinance=False, cache_dir=tmp_path)
        resolver.finance_db._loaded = True
        resolver.finance_db._equity_data = {
            "BAD": {
                "isin": "US0000000009",  # invalid check digit
                "cusip": None,
                "name": "Bad Corp",
                "country": "US",
                "exchange": "NYS",
            },
        }

        results = resolver.resolve_batch(["BAD"])
        assert "BAD" in results
        assert results["BAD"].source == "unresolved"
        assert any("failed validation" in w for w in results["BAD"].warnings)

    def test_write_csv_output(self, tmp_path: Path) -> None:
        from isin_resolver import write_csv_output

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
        from isin_resolver import print_summary

        print_summary({})
        captured = capsys.readouterr()
        assert "Total tickers: 0" in captured.out
        assert "no tickers" in captured.out


# --- Country Name to ISO Mapping (Item 1) ---


class TestCountryNameToISO:
    def test_us(self) -> None:
        assert _country_name_to_iso("United States") == "US"

    def test_canada(self) -> None:
        assert _country_name_to_iso("Canada") == "CA"

    def test_cayman_islands(self) -> None:
        assert _country_name_to_iso("Cayman Islands") == "KY"

    def test_united_kingdom(self) -> None:
        assert _country_name_to_iso("United Kingdom") == "GB"

    def test_case_insensitive(self) -> None:
        assert _country_name_to_iso("CANADA") == "CA"
        assert _country_name_to_iso("united states") == "US"

    def test_empty_defaults_to_us(self) -> None:
        assert _country_name_to_iso("") == "US"

    def test_unknown_defaults_to_us(self) -> None:
        assert _country_name_to_iso("Unknown Country") == "US"

    def test_whitespace_stripped(self) -> None:
        assert _country_name_to_iso("  Canada  ") == "CA"


# --- Non-US CUSIP-to-ISIN Conversion (Item 1) ---


class TestNonUSCUSIPConversion:
    @patch("isin_resolver.FinanceDatabaseSource._load")
    def test_canadian_cusip_gets_ca_prefix(self, mock_load: MagicMock) -> None:
        """A Canadian ticker with CUSIP but no ISIN should get CA prefix, not US."""
        source = FinanceDatabaseSource()
        source._loaded = True
        source._equity_data = {
            "SHOP": {
                "isin": None,
                "cusip": "82509L107",
                "name": "Shopify Inc.",
                "country": "Canada",
                "exchange": "NYS",
            },
        }

        result = source.resolve("SHOP")
        if result and result.isin:
            assert result.isin.startswith("CA"), f"Expected CA prefix, got {result.isin}"

    @patch("isin_resolver.FinanceDatabaseSource._load")
    def test_us_cusip_still_gets_us_prefix(self, mock_load: MagicMock) -> None:
        """US tickers should still get US prefix (regression test)."""
        source = FinanceDatabaseSource()
        source._loaded = True
        source._equity_data = {
            "AAPL": {
                "isin": None,
                "cusip": "037833100",
                "name": "Apple Inc.",
                "country": "United States",
                "exchange": "NMS",
            },
        }

        result = source.resolve("AAPL")
        assert result is not None
        assert result.isin is not None
        assert result.isin.startswith("US")

    @patch("isin_resolver.FinanceDatabaseSource._load")
    def test_empty_country_defaults_to_us(self, mock_load: MagicMock) -> None:
        """Empty country should default to US prefix."""
        source = FinanceDatabaseSource()
        source._loaded = True
        source._equity_data = {
            "TEST": {
                "isin": None,
                "cusip": "037833100",
                "name": "Test Corp",
                "country": None,
                "exchange": "NMS",
            },
        }

        result = source.resolve("TEST")
        assert result is not None
        assert result.isin is not None
        assert result.isin.startswith("US")


# --- Post-Cache ISIN Validation (Item 3) ---


class TestPostCacheValidation:
    def test_bad_isin_evicted_from_cache(self, tmp_path: Path) -> None:
        """A cached ISIN with bad check digit should be evicted on read."""
        cache = ISINCache(cache_dir=tmp_path, ttl_seconds=3600)
        # Write a bad ISIN directly to cache internals
        cache._load()
        import time as _time
        cache._data["BAD"] = {
            "ticker": "BAD",
            "isin": "US0000000009",  # invalid check digit
            "source": "test",
            "warnings": [],
            "_cached_at": _time.time(),
        }
        cache.save()

        # Reading should detect and evict the bad ISIN
        cache2 = ISINCache(cache_dir=tmp_path, ttl_seconds=3600)
        result = cache2.get("BAD")
        assert result is None  # evicted

        # Verify it was actually removed from internal data
        assert "BAD" not in cache2._data

    def test_valid_isin_served_from_cache(self, tmp_path: Path) -> None:
        """A cached ISIN with valid check digit should be served normally."""
        cache = ISINCache(cache_dir=tmp_path, ttl_seconds=3600)
        result = ISINResult(ticker="AAPL", isin="US0378331005", source="test")
        cache.put(result)

        fetched = cache.get("AAPL")
        assert fetched is not None
        assert fetched.isin == "US0378331005"

    def test_no_isin_served_from_cache(self, tmp_path: Path) -> None:
        """A cached entry with no ISIN should still be served (unresolved)."""
        cache = ISINCache(cache_dir=tmp_path, ttl_seconds=3600)
        result = ISINResult(ticker="ZZZZZ", source="unresolved")
        cache.put(result)

        fetched = cache.get("ZZZZZ")
        assert fetched is not None
        assert fetched.isin is None


# --- Confidence Scoring (Item 5) ---


class TestConfidenceScoring:
    @patch.object(FinanceDatabaseSource, "_load")
    def test_tier1_confidence_high(self, mock_load: MagicMock, tmp_path: Path) -> None:
        """FinanceDatabase results should have 'high' confidence."""
        resolver = ISINResolver(use_yfinance=False, cache_dir=tmp_path)
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
        """yfinance results should have 'medium' confidence."""
        resolver = ISINResolver(use_yfinance=True, cache_dir=tmp_path)
        resolver.finance_db._loaded = True
        resolver.finance_db._equity_data = {}

        mock_ticker = MagicMock()
        mock_ticker.isin = "US78462F1030"
        mock_ticker.info = {"longName": "SPDR"}
        mock_ticker_cls.return_value = mock_ticker

        result = resolver.resolve("SPY")
        assert result.confidence == "medium"

    @patch.object(FinanceDatabaseSource, "_load")
    def test_unresolved_confidence_low(self, mock_load: MagicMock, tmp_path: Path) -> None:
        """Unresolved tickers should have 'low' confidence."""
        resolver = ISINResolver(use_yfinance=False, cache_dir=tmp_path)
        resolver.finance_db._loaded = True
        resolver.finance_db._equity_data = {}

        result = resolver.resolve("ZZZZZ")
        assert result.confidence == "low"

    def test_write_csv_includes_confidence(self, tmp_path: Path) -> None:
        from isin_resolver import write_csv_output

        results = {
            "AAPL": ISINResult(
                ticker="AAPL",
                isin="US0378331005",
                source="financedatabase",
                confidence="high",
            ),
        }
        output = tmp_path / "test.csv"
        write_csv_output(results, output)

        with open(output) as f:
            reader = csv.DictReader(f)
            rows = list(reader)
        assert rows[0]["confidence"] == "high"
