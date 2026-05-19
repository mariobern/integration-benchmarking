"""Tests for ric_csv module."""

from pathlib import Path

import pytest

from edit_config_lib.ric_csv import (
    RicEntry,
    load_ric_csv,
    derive_symbol_prefixes,
    build_prefix_index,
    LoadError,
)

FIXTURES = Path(__file__).parent / "fixtures"


def test_load_ric_csv_returns_entries():
    entries = load_ric_csv(str(FIXTURES / "hk-syms-sample.csv"))
    assert len(entries) == 3
    assert entries[0] == RicEntry(ticker="700", ric="0700.HK", exchange_code="HKG")
    assert entries[1].ric == "0883.HK"
    assert entries[2].ric == "1211.HK"


def test_load_ric_csv_raises_on_missing_file(tmp_path):
    with pytest.raises(LoadError, match="not found"):
        load_ric_csv(str(tmp_path / "nope.csv"))


def test_load_ric_csv_raises_on_empty(tmp_path):
    p = tmp_path / "empty.csv"
    p.write_text("Exchange Code,Ticker,RIC\n", encoding="utf-8")
    with pytest.raises(LoadError, match="no data rows"):
        load_ric_csv(str(p))


def test_load_ric_csv_raises_on_missing_columns(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("Ticker,Foo\n700,bar\n", encoding="utf-8")
    with pytest.raises(LoadError, match="missing required column"):
        load_ric_csv(str(p))


def test_load_ric_csv_raises_on_duplicate_ric(tmp_path):
    p = tmp_path / "dup.csv"
    p.write_text(
        "Exchange Code,Ticker,RIC\n" "HKG,700,0700.HK\n" "HKG,701,0700.HK\n",
        encoding="utf-8",
    )
    with pytest.raises(LoadError, match="duplicate RIC"):
        load_ric_csv(str(p))


def test_derive_symbol_prefixes_hk():
    assert derive_symbol_prefixes("0700.HK") == [
        "Equity.HK.0700-HK/",
        "Equity.HK.0700/",
    ]
    assert derive_symbol_prefixes("0002.HK") == [
        "Equity.HK.0002-HK/",
        "Equity.HK.0002/",
    ]


def test_derive_symbol_prefixes_unknown_suffix_returns_empty():
    assert derive_symbol_prefixes("AAPL.O") == []
    assert derive_symbol_prefixes("EUR=") == []


def test_build_prefix_index_hk():
    entries = [
        RicEntry(ticker="700", ric="0700.HK", exchange_code="HKG"),
        RicEntry(ticker="883", ric="0883.HK", exchange_code="HKG"),
    ]
    result = build_prefix_index(entries)
    assert result == {
        "Equity.HK.0700-HK/": "0700.HK",
        "Equity.HK.0700/": "0700.HK",
        "Equity.HK.0883-HK/": "0883.HK",
        "Equity.HK.0883/": "0883.HK",
    }


def test_build_prefix_index_filters_non_hk():
    entries = [
        RicEntry(ticker="700", ric="0700.HK", exchange_code="HKG"),
        RicEntry(ticker="AAPL", ric="AAPL.O", exchange_code="XNMS"),
    ]
    result = build_prefix_index(entries)
    assert result == {
        "Equity.HK.0700-HK/": "0700.HK",
        "Equity.HK.0700/": "0700.HK",
    }
