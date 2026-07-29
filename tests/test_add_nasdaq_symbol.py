"""Tests for add_nasdaq_symbol.py."""

import json
from pathlib import Path

import pytest

from add_nasdaq_symbol import (
    ASIAN_MARKET_PREFIXES,
    Change,
    Skip,
    build_changes,
    plan_change,
    apply_changes,
    main,
    VerificationError,
    verify_feed_metadata,
    verify_on_disk,
)
from rename_numeric_feed_names import dump_config, write_config


def _feed(
    feed_id=100,
    symbol="Equity.CN.688825/CNY",
    name="688825",
    nasdaq_symbol=None,
):
    """Build a minimal feed dict shaped like a lazer_jpkr.json entry."""
    metadata = {
        "asset_type": "equity",
        "description": "CHANGXIN MEMORY TECHNOLOGIES / CHINESE YUAN",
        "name": name,
        "quote_currency": "CNY",
    }
    if nasdaq_symbol is not None:
        metadata["nasdaq_symbol"] = nasdaq_symbol
    return {
        "feedId": feed_id,
        "symbol": symbol,
        "state": "STABLE",
        "metadata": metadata,
    }


class TestAsianMarketPrefixes:
    def test_includes_all_five_markets(self):
        assert ASIAN_MARKET_PREFIXES == (
            "Equity.HK.",
            "Equity.CN.",
            "Equity.JP.",
            "Equity.KR.",
            "Equity.IN.",
        )


class TestPlanChange:
    def test_numeric_name_becomes_change(self):
        change, skip = plan_change(_feed())
        assert skip is None
        assert change == Change(
            feed_id=100, symbol="Equity.CN.688825/CNY", name="688825"
        )

    def test_alphanumeric_code_becomes_change(self):
        change, skip = plan_change(
            _feed(symbol="Equity.IN.NIFTYBEES/INR", name="NIFTYBEES")
        )
        assert skip is None
        assert change.name == "NIFTYBEES"

    def test_hyphenated_code_becomes_change(self):
        change, skip = plan_change(
            _feed(symbol="Equity.JP.1321-JP/JPY", name="1321-JP")
        )
        assert skip is None
        assert change.name == "1321-JP"

    def test_already_set_is_skipped(self):
        change, skip = plan_change(_feed(nasdaq_symbol="688825"))
        assert change is None
        assert skip == Skip(
            feed_id=100,
            symbol="Equity.CN.688825/CNY",
            reason="nasdaq_symbol already set",
        )

    def test_already_set_is_skipped_even_if_stale(self):
        # Even a mismatched existing value is left alone -- idempotent, not "fix on rerun".
        change, skip = plan_change(_feed(nasdaq_symbol="WRONG"))
        assert change is None
        assert skip.reason == "nasdaq_symbol already set"

    def test_empty_name_is_skipped(self):
        change, skip = plan_change(_feed(name=""))
        assert change is None
        assert "metadata.name is empty" in skip.reason

    def test_name_with_space_is_skipped(self):
        change, skip = plan_change(_feed(name="CHANGXIN MEMORY TECHNOLOGIES"))
        assert change is None
        assert "does not match symbol code" in skip.reason

    def test_name_with_internal_space_is_skipped(self):
        change, skip = plan_change(_feed(name="GIGADEVICE SEMICONDUCTOR INC (CN)"))
        assert change is None
        assert "does not match symbol code" in skip.reason

    def test_single_word_display_name_is_still_skipped(self):
        # Regression: a whitespace-only check would wrongly accept this.
        change, skip = plan_change(_feed(symbol="Equity.JP.6501/JPY", name="HITACHI"))
        assert change is None
        assert "does not match symbol code" in skip.reason


class TestBuildChanges:
    def test_in_scope_cn_feed_produces_change(self):
        changes, skips = build_changes([_feed(feed_id=3520)])
        assert skips == []
        assert changes == [
            Change(feed_id=3520, symbol="Equity.CN.688825/CNY", name="688825")
        ]

    def test_default_scope_includes_india(self):
        feed = _feed(feed_id=3363, symbol="Equity.IN.NIFTYBEES/INR", name="NIFTYBEES")
        changes, skips = build_changes([feed])
        assert skips == []
        assert changes == [
            Change(feed_id=3363, symbol="Equity.IN.NIFTYBEES/INR", name="NIFTYBEES")
        ]

    def test_out_of_scope_feed_untouched(self):
        feeds = [_feed(feed_id=922, symbol="Equity.US.AAPL/USD", name="AAPL")]
        changes, skips = build_changes(feeds)
        assert changes == []
        assert skips == []

    def test_custom_prefixes_narrow_scope(self):
        feeds = [
            _feed(feed_id=3520),
            _feed(feed_id=884, symbol="Equity.HK.0002/HKD", name="0002"),
        ]
        changes, _ = build_changes(feeds, prefixes=("Equity.HK.",))
        assert [c.feed_id for c in changes] == [884]

    def test_mixed_changes_and_skips(self):
        feeds = [
            _feed(feed_id=3520),
            _feed(feed_id=3521, name="ALREADY MULTI WORD"),
        ]
        changes, skips = build_changes(feeds)
        assert [c.feed_id for c in changes] == [3520]
        assert [s.feed_id for s in skips] == [3521]


def _config(*feeds):
    return {"feeds": list(feeds)}


class TestApplyChanges:
    def test_sets_nasdaq_symbol(self):
        data = _config(_feed(feed_id=3520))
        changes, _ = build_changes(data["feeds"])
        apply_changes(data, changes)
        assert data["feeds"][0]["metadata"]["nasdaq_symbol"] == "688825"

    def test_other_fields_untouched(self):
        data = _config(_feed(feed_id=3520))
        changes, _ = build_changes(data["feeds"])
        apply_changes(data, changes)
        metadata = data["feeds"][0]["metadata"]
        assert metadata["name"] == "688825"
        assert metadata["description"] == "CHANGXIN MEMORY TECHNOLOGIES / CHINESE YUAN"
        assert metadata["quote_currency"] == "CNY"

    def test_symbol_untouched(self):
        data = _config(_feed(feed_id=3520))
        changes, _ = build_changes(data["feeds"])
        apply_changes(data, changes)
        assert data["feeds"][0]["symbol"] == "Equity.CN.688825/CNY"

    def test_metadata_keys_are_alphabetically_sorted(self):
        data = _config(_feed(feed_id=3520))
        changes, _ = build_changes(data["feeds"])
        apply_changes(data, changes)
        keys = list(data["feeds"][0]["metadata"].keys())
        assert keys == sorted(keys)
        assert keys == [
            "asset_type",
            "description",
            "name",
            "nasdaq_symbol",
            "quote_currency",
        ]

    def test_untouched_feed_not_mutated(self):
        data = _config(
            _feed(feed_id=3520),
            _feed(feed_id=922, symbol="Equity.US.AAPL/USD", name="AAPL"),
        )
        changes, _ = build_changes(data["feeds"])
        apply_changes(data, changes)
        assert "nasdaq_symbol" not in data["feeds"][1]["metadata"]


class TestVerifyFeedMetadata:
    def test_passes_on_planned_change(self):
        before_data = _config(_feed(feed_id=3520))
        after_data = _config(_feed(feed_id=3520))
        changes, _ = build_changes(before_data["feeds"])
        apply_changes(after_data, changes)
        verify_feed_metadata(before_data, after_data, changes)

    def test_rejects_feed_id_set_change(self):
        before_data = _config(
            _feed(feed_id=3520),
            _feed(feed_id=884, symbol="Equity.HK.0002/HKD", name="0002"),
        )
        after_data = _config(_feed(feed_id=3520))
        with pytest.raises(VerificationError, match="feed id set changed"):
            verify_feed_metadata(before_data, after_data, changes=[])

    def test_rejects_unplanned_metadata_change(self):
        before_data = _config(_feed(feed_id=3520))
        after_data = _config(_feed(feed_id=3520))
        after_data["feeds"][0]["metadata"]["name"] = "TAMPERED"
        with pytest.raises(VerificationError, match="had no planned change"):
            verify_feed_metadata(before_data, after_data, changes=[])

    def test_rejects_wrong_nasdaq_symbol_value(self):
        before_data = _config(_feed(feed_id=3520))
        after_data = _config(_feed(feed_id=3520, nasdaq_symbol="WRONG"))
        changes, _ = build_changes(before_data["feeds"])
        with pytest.raises(VerificationError, match="does not match the plan"):
            verify_feed_metadata(before_data, after_data, changes)

    def test_rejects_change_leaking_to_unplanned_feed(self):
        before_data = _config(
            _feed(feed_id=3520),
            _feed(feed_id=884, symbol="Equity.HK.0002/HKD", name="0002"),
        )
        after_data = _config(
            # feed 3520 correctly matches the plan, so it isn't what trips the check.
            _feed(feed_id=3520, nasdaq_symbol="688825"),
            _feed(
                feed_id=884,
                symbol="Equity.HK.0002/HKD",
                name="0002",
                nasdaq_symbol="0002",
            ),
        )
        # Plan only covers CN, so the HK feed gaining nasdaq_symbol is unplanned.
        changes, _ = build_changes(before_data["feeds"], prefixes=("Equity.CN.",))
        with pytest.raises(VerificationError, match="had no planned change"):
            verify_feed_metadata(before_data, after_data, changes)


class TestVerifyOnDisk:
    def test_passes_after_real_write(self, tmp_path):
        data = _config(_feed(feed_id=3520))
        before_text = dump_config(data)
        path = tmp_path / "cfg.json"
        path.write_text(before_text, encoding="utf-8")
        changes, _ = build_changes(data["feeds"])
        apply_changes(data, changes)
        write_config(path, dump_config(data), backup=False)
        verify_on_disk(path, before_text, changes)

    def test_rejects_unparseable_file(self, tmp_path):
        path = tmp_path / "cfg.json"
        path.write_text("{not json", encoding="utf-8")
        before_text = dump_config(_config(_feed(feed_id=3520)))
        with pytest.raises(VerificationError, match="does not parse"):
            verify_on_disk(path, before_text, [])

    def test_rejects_feed_count_change(self, tmp_path):
        before_data = _config(
            _feed(feed_id=3520),
            _feed(feed_id=884, symbol="Equity.HK.0002/HKD", name="0002"),
        )
        before_text = dump_config(before_data)
        path = tmp_path / "cfg.json"
        path.write_text(dump_config(_config(_feed(feed_id=3520))), encoding="utf-8")
        with pytest.raises(VerificationError, match="feed count changed"):
            verify_on_disk(path, before_text, [])


def _write_config(tmp_path, *feeds):
    path = tmp_path / "cfg.json"
    path.write_text(dump_config(_config(*feeds)), encoding="utf-8")
    return path


class TestMain:
    def test_dry_run_writes_nothing(self, tmp_path, capsys):
        path = _write_config(tmp_path, _feed(feed_id=3520))
        original = path.read_text(encoding="utf-8")
        assert main(["--config", str(path)]) == 0
        assert path.read_text(encoding="utf-8") == original
        assert not (tmp_path / "cfg.json.bak").exists()
        assert "DRY RUN" in capsys.readouterr().out

    def test_apply_writes_and_backs_up(self, tmp_path):
        path = _write_config(tmp_path, _feed(feed_id=3520))
        assert main(["--config", str(path), "--apply"]) == 0
        written = json.loads(path.read_text(encoding="utf-8"))
        assert written["feeds"][0]["metadata"]["nasdaq_symbol"] == "688825"
        assert (tmp_path / "cfg.json.bak").exists()

    def test_second_run_is_a_noop(self, tmp_path, capsys):
        path = _write_config(tmp_path, _feed(feed_id=3520))
        main(["--config", str(path), "--apply"])
        capsys.readouterr()
        assert main(["--config", str(path), "--apply"]) == 0
        assert "No changes" in capsys.readouterr().out

    def test_symbol_prefix_narrows_scope(self, tmp_path):
        path = _write_config(
            tmp_path,
            _feed(feed_id=3520),
            _feed(feed_id=884, symbol="Equity.HK.0002/HKD", name="0002"),
        )
        assert (
            main(["--config", str(path), "--symbol-prefix", "Equity.HK.", "--apply"])
            == 0
        )
        written = json.loads(path.read_text(encoding="utf-8"))
        assert "nasdaq_symbol" not in written["feeds"][0]["metadata"]
        assert written["feeds"][1]["metadata"]["nasdaq_symbol"] == "0002"

    def test_missing_config_file_errors_cleanly(self, tmp_path, capsys):
        missing = tmp_path / "nope.json"
        assert main(["--config", str(missing)]) == 1
        err = capsys.readouterr().err
        assert "ERROR: Config file not found" in err
        assert str(missing) in err

    def test_no_backup_flag(self, tmp_path):
        path = _write_config(tmp_path, _feed(feed_id=3520))
        assert main(["--config", str(path), "--apply", "--no-backup"]) == 0
        assert not (tmp_path / "cfg.json.bak").exists()

    def test_skip_reasons_are_reported(self, tmp_path, capsys):
        path = _write_config(
            tmp_path,
            _feed(feed_id=3520, name="ALREADY MULTI WORD"),
        )
        assert main(["--config", str(path)]) == 0
        out = capsys.readouterr().out
        assert "Skipped (1)" in out
        assert "does not match symbol code" in out

    def test_pre_write_verification_failure_writes_nothing(self, tmp_path, monkeypatch):
        path = _write_config(tmp_path, _feed(feed_id=3520))
        original = path.read_text(encoding="utf-8")

        def _boom(*args, **kwargs):
            raise VerificationError("boom")

        monkeypatch.setattr("add_nasdaq_symbol.verify_feed_metadata", _boom)
        assert main(["--config", str(path), "--apply"]) == 1
        assert path.read_text(encoding="utf-8") == original
        assert not (tmp_path / "cfg.json.bak").exists()

    def test_post_write_verification_failure_leaves_backup(self, tmp_path, monkeypatch):
        path = _write_config(tmp_path, _feed(feed_id=3520))
        original = path.read_text(encoding="utf-8")

        def _boom(*args, **kwargs):
            raise VerificationError("boom")

        monkeypatch.setattr("add_nasdaq_symbol.verify_on_disk", _boom)
        assert main(["--config", str(path), "--apply"]) == 1
        assert (tmp_path / "cfg.json.bak").exists()
        assert (tmp_path / "cfg.json.bak").read_text(encoding="utf-8") == original


LIVE_CONFIG = Path("lazer_jpkr.json")


@pytest.mark.skipif(
    not LIVE_CONFIG.exists(),
    reason="lazer_jpkr.json is gitignored and not present in this checkout",
)
class TestLiveConfigSmoke:
    """Guards the measured expectations from the design doc.

    The config is gitignored, so these are skipped wherever it is absent.
    """

    def _feeds(self):
        return json.loads(LIVE_CONFIG.read_text(encoding="utf-8"))["feeds"]

    def test_465_changes_no_skips(self):
        changes, skips = build_changes(self._feeds())
        assert len(changes) == 465
        assert skips == []
