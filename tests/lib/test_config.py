"""Tests for lib.config — config loading, client creation, asset class normalization."""

import pytest

from lib.config import (
    ASSET_CLASS_ALIASES,
    BENCHMARKABLE_ASSET_CLASSES,
    normalize_asset_class,
    load_config,
)


class TestNormalizeAssetClass:
    def test_canonical_names_unchanged(self):
        assert normalize_asset_class("fx") == "fx"
        assert normalize_asset_class("metals") == "metals"
        assert normalize_asset_class("us-equities") == "us-equities"
        assert normalize_asset_class("commodity") == "commodity"
        assert normalize_asset_class("us-treasuries") == "us-treasuries"

    def test_aliases_resolve(self):
        assert normalize_asset_class("metal") == "metals"
        assert normalize_asset_class("equity-us") == "us-equities"
        assert normalize_asset_class("rates") == "us-treasuries"
        assert normalize_asset_class("treasuries") == "us-treasuries"

    def test_case_insensitive(self):
        assert normalize_asset_class("FX") == "fx"
        assert normalize_asset_class("Metals") == "metals"
        assert normalize_asset_class("US-Equities") == "us-equities"

    def test_unknown_asset_class_passthrough(self):
        assert normalize_asset_class("unknown") == "unknown"
        assert normalize_asset_class("CRYPTO") == "crypto"


class TestAssetClassConstants:
    def test_benchmarkable_is_subset_of_aliases(self):
        for ac in BENCHMARKABLE_ASSET_CLASSES:
            assert ac in ASSET_CLASS_ALIASES.values()

    def test_non_benchmarkable_excluded(self):
        assert "crypto" not in BENCHMARKABLE_ASSET_CLASSES
        assert "nav" not in BENCHMARKABLE_ASSET_CLASSES
        assert "funding-rate" not in BENCHMARKABLE_ASSET_CLASSES


class TestLoadConfig:
    def test_missing_config_raises(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        with pytest.raises(FileNotFoundError):
            load_config()

    def test_valid_config_loads(self, tmp_path, monkeypatch):
        config_content = "lazer_clickhouse_prod:\n  host: localhost\n"
        config_file = tmp_path / "config.yaml"
        config_file.write_text(config_content)
        monkeypatch.chdir(tmp_path)
        config = load_config()
        assert config["lazer_clickhouse_prod"]["host"] == "localhost"
