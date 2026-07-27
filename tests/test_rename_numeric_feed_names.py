"""Tests for rename_numeric_feed_names.py."""

import json
from pathlib import Path

import pytest

from rename_numeric_feed_names import (
    Change,
    OverrideError,
    VerificationError,
    apply_changes,
    build_changes,
    derive_name,
    dump_config,
    find_duplicate_names,
    in_scope,
    is_candidate,
    load_overrides,
    main,
    verify_feed_names,
    verify_on_disk,
    verify_text,
    validate_overrides,
    write_config,
)


def _feed(
    feed_id=100,
    symbol="Equity.CN.688825/CNY",
    name="688825",
    description="CHANGXIN MEMORY TECHNOLOGIES / CHINESE YUAN",
    quote_currency="CNY",
):
    """Build a minimal feed dict shaped like a lazer-state.json entry."""
    return {
        "feedId": feed_id,
        "symbol": symbol,
        "state": "STABLE",
        "metadata": {
            "asset_type": "equity",
            "description": description,
            "name": name,
            "quote_currency": quote_currency,
        },
    }


class TestInScope:
    def test_cn_prefix_in_scope(self):
        assert in_scope(_feed()) is True

    def test_us_prefix_out_of_scope(self):
        assert in_scope(_feed(symbol="Equity.US.AAPL/USD")) is False

    def test_custom_prefixes_respected(self):
        assert in_scope(_feed(), prefixes=("Equity.JP.",)) is False


class TestIsCandidate:
    def test_numeric_name_is_candidate(self):
        assert is_candidate(_feed()) is True

    def test_numeric_with_trailing_letter_is_candidate(self):
        assert is_candidate(_feed(name="0700A")) is True

    def test_already_renamed_is_not_candidate(self):
        assert is_candidate(_feed(name="CHANGXIN MEMORY TECHNOLOGIES")) is False

    def test_alphanumeric_futures_code_is_not_candidate(self):
        assert is_candidate(_feed(symbol="Equity.KR.KSM6/KRW", name="KSM6")) is False

    def test_out_of_scope_never_candidate(self):
        assert is_candidate(_feed(symbol="Equity.US.AAPL/USD", name="123")) is False


class TestDeriveName:
    def test_happy_path(self):
        name, reason = derive_name(_feed())
        assert name == "CHANGXIN MEMORY TECHNOLOGIES"
        assert reason is None

    def test_strips_trailing_whitespace(self):
        feed = _feed(
            symbol="Equity.KR.001040/KRW",
            description="CJ CORP  / SOUTH KOREAN WON",
            quote_currency="KRW",
        )
        name, reason = derive_name(feed)
        assert name == "CJ CORP"
        assert reason is None

    def test_splits_on_last_separator(self):
        feed = _feed(description="FOO / BAR CORP / CHINESE YUAN")
        name, reason = derive_name(feed)
        assert name == "FOO / BAR CORP"
        assert reason is None

    def test_currency_mismatch_is_skipped(self):
        feed = _feed(description="SOME CORP / US DOLLAR")
        name, reason = derive_name(feed)
        assert name is None
        assert "does not match expected" in reason

    def test_unmapped_currency_is_skipped(self):
        feed = _feed(
            symbol="Equity.TW.2330/TWD",
            description="TSMC / TAIWAN DOLLAR",
            quote_currency="TWD",
        )
        name, reason = derive_name(feed)
        assert name is None
        assert "no currency name mapped" in reason

    def test_missing_separator_is_skipped(self):
        feed = _feed(description="CHANGXIN MEMORY TECHNOLOGIES")
        name, reason = derive_name(feed)
        assert name is None
        assert "separator" in reason

    def test_empty_derived_name_is_skipped(self):
        feed = _feed(description=" / CHINESE YUAN")
        name, reason = derive_name(feed)
        assert name is None
        assert "empty" in reason


def _write_csv(tmp_path, text):
    path = tmp_path / "overrides.csv"
    path.write_text(text, encoding="utf-8")
    return path


class TestLoadOverrides:
    def test_parses_rows(self, tmp_path):
        path = _write_csv(tmp_path, "feed_id,name\n3520,CXMT\n3360,GIGA (HK)\n")
        assert load_overrides(path) == {3520: "CXMT", 3360: "GIGA (HK)"}

    def test_strips_whitespace(self, tmp_path):
        path = _write_csv(tmp_path, "feed_id,name\n 3520 , CXMT \n")
        assert load_overrides(path) == {3520: "CXMT"}

    def test_skips_fully_blank_rows(self, tmp_path):
        path = _write_csv(tmp_path, "feed_id,name\n3520,CXMT\n,\n")
        assert load_overrides(path) == {3520: "CXMT"}

    def test_missing_file_is_error(self, tmp_path):
        with pytest.raises(OverrideError, match="not found"):
            load_overrides(tmp_path / "nope.csv")

    def test_missing_column_is_error(self, tmp_path):
        path = _write_csv(tmp_path, "feed_id\n3520\n")
        with pytest.raises(OverrideError, match="missing required column"):
            load_overrides(path)

    def test_non_integer_feed_id_is_error(self, tmp_path):
        path = _write_csv(tmp_path, "feed_id,name\nabc,CXMT\n")
        with pytest.raises(OverrideError, match="not an integer"):
            load_overrides(path)

    def test_empty_name_is_error(self, tmp_path):
        path = _write_csv(tmp_path, "feed_id,name\n3520,\n")
        with pytest.raises(OverrideError, match="name is empty"):
            load_overrides(path)

    def test_duplicate_feed_id_is_error(self, tmp_path):
        path = _write_csv(tmp_path, "feed_id,name\n3520,CXMT\n3520,OTHER\n")
        with pytest.raises(OverrideError, match="duplicate feed_id"):
            load_overrides(path)


class TestValidateOverrides:
    def test_in_scope_feed_accepted(self):
        feeds = [_feed(feed_id=3520)]
        validate_overrides({3520: "CXMT"}, feeds)

    def test_already_renamed_feed_accepted(self):
        feeds = [_feed(feed_id=3520, name="CHANGXIN MEMORY TECHNOLOGIES")]
        validate_overrides({3520: "CXMT"}, feeds)

    def test_unknown_feed_id_is_error(self):
        with pytest.raises(OverrideError, match="not found in config"):
            validate_overrides({999: "X"}, [_feed(feed_id=3520)])

    def test_out_of_prefix_feed_is_error(self):
        feeds = [_feed(feed_id=922, symbol="Equity.US.AAPL/USD")]
        with pytest.raises(OverrideError, match="outside the configured"):
            validate_overrides({922: "APPLE"}, feeds)


class TestBuildChanges:
    def test_derives_name_for_candidate(self):
        changes, skips = build_changes([_feed(feed_id=3520)])
        assert skips == []
        assert changes == [
            Change(
                feed_id=3520,
                symbol="Equity.CN.688825/CNY",
                before="688825",
                after="CHANGXIN MEMORY TECHNOLOGIES",
                source="rule",
            )
        ]

    def test_out_of_scope_feed_untouched(self):
        feeds = [_feed(feed_id=922, symbol="Equity.US.AAPL/USD", name="AAPL")]
        changes, skips = build_changes(feeds)
        assert changes == []
        assert skips == []

    def test_already_renamed_feed_is_noop(self):
        feeds = [_feed(feed_id=3520, name="CHANGXIN MEMORY TECHNOLOGIES")]
        changes, skips = build_changes(feeds)
        assert changes == []
        assert skips == []

    def test_idempotent_second_pass(self):
        feeds = [_feed(feed_id=3520)]
        changes, _ = build_changes(feeds)
        feeds[0]["metadata"]["name"] = changes[0].after
        changes_again, skips_again = build_changes(feeds)
        assert changes_again == []
        assert skips_again == []

    def test_undeliverable_description_is_skipped(self):
        feeds = [_feed(feed_id=3520, description="SOME CORP / US DOLLAR")]
        changes, skips = build_changes(feeds)
        assert changes == []
        assert len(skips) == 1
        assert skips[0].feed_id == 3520

    def test_override_beats_derived_name(self):
        changes, skips = build_changes([_feed(feed_id=3520)], overrides={3520: "CXMT"})
        assert skips == []
        assert changes[0].after == "CXMT"
        assert changes[0].source == "override"

    def test_override_applies_to_already_renamed_feed(self):
        feeds = [_feed(feed_id=3520, name="CHANGXIN MEMORY TECHNOLOGIES")]
        changes, _ = build_changes(feeds, overrides={3520: "CXMT"})
        assert changes[0].before == "CHANGXIN MEMORY TECHNOLOGIES"
        assert changes[0].after == "CXMT"

    def test_override_matching_current_name_is_noop(self):
        changes, _ = build_changes([_feed(feed_id=3520)], overrides={3520: "688825"})
        assert changes == []

    def test_override_skips_currency_validation(self):
        feeds = [_feed(feed_id=3520, description="BROKEN DESCRIPTION")]
        changes, skips = build_changes(feeds, overrides={3520: "CXMT"})
        assert skips == []
        assert changes[0].after == "CXMT"


class TestFindDuplicateNames:
    def test_reports_dual_listing(self):
        feeds = [
            _feed(
                feed_id=3339,
                symbol="Equity.CN.603986/CNY",
                name="603986",
                description="GIGADEVICE SEMICONDUCTOR INC / CHINESE YUAN",
            ),
            _feed(
                feed_id=3360,
                symbol="Equity.HK.3986/HKD",
                name="3986",
                description="GIGADEVICE SEMICONDUCTOR INC / HONG KONG DOLLAR",
                quote_currency="HKD",
            ),
        ]
        changes, _ = build_changes(feeds)
        duplicates = find_duplicate_names(feeds, changes)
        assert duplicates == [
            (
                "GIGADEVICE SEMICONDUCTOR INC",
                [(3339, "Equity.CN.603986/CNY"), (3360, "Equity.HK.3986/HKD")],
            )
        ]

    def test_overrides_clear_the_duplicate(self):
        feeds = [
            _feed(
                feed_id=3339,
                symbol="Equity.CN.603986/CNY",
                name="603986",
                description="GIGADEVICE SEMICONDUCTOR INC / CHINESE YUAN",
            ),
            _feed(
                feed_id=3360,
                symbol="Equity.HK.3986/HKD",
                name="3986",
                description="GIGADEVICE SEMICONDUCTOR INC / HONG KONG DOLLAR",
                quote_currency="HKD",
            ),
        ]
        overrides = {
            3339: "GIGADEVICE SEMICONDUCTOR INC (CN)",
            3360: "GIGADEVICE SEMICONDUCTOR INC (HK)",
        }
        changes, _ = build_changes(feeds, overrides=overrides)
        assert find_duplicate_names(feeds, changes) == []

    def test_preexisting_duplicate_not_reported_when_untouched(self):
        feeds = [
            _feed(feed_id=979, symbol="Equity.US.BA/USD", name="BA"),
            _feed(feed_id=790, symbol="Equity.GB.BA/GBP", name="BA"),
        ]
        assert find_duplicate_names(feeds, changes=[]) == []

    def test_collision_with_untouched_feed_is_reported(self):
        feeds = [
            _feed(feed_id=3520),
            _feed(
                feed_id=3293,
                symbol="Equity.US.CXMT/USD",
                name="CHANGXIN MEMORY TECHNOLOGIES",
            ),
        ]
        changes, _ = build_changes(feeds)
        duplicates = find_duplicate_names(feeds, changes)
        assert len(duplicates) == 1
        assert duplicates[0][0] == "CHANGXIN MEMORY TECHNOLOGIES"


def _config(*feeds):
    return {"feeds": list(feeds)}


class TestDumpConfig:
    def test_round_trip_is_byte_identical(self, tmp_path):
        data = _config(_feed(feed_id=3520))
        text = dump_config(data)
        assert dump_config(json.loads(text)) == text

    def test_no_trailing_newline(self):
        assert not dump_config(_config(_feed())).endswith("\n")

    def test_non_ascii_is_not_escaped(self):
        data = _config(_feed(description="COSTA RICAN COLÓN / CHINESE YUAN"))
        assert "COLÓN" in dump_config(data)
        assert "\\u00d3" not in dump_config(data).lower()


class TestApplyChanges:
    def test_sets_name_and_leaves_description(self):
        data = _config(_feed(feed_id=3520))
        changes, _ = build_changes(data["feeds"])
        apply_changes(data, changes)
        metadata = data["feeds"][0]["metadata"]
        assert metadata["name"] == "CHANGXIN MEMORY TECHNOLOGIES"
        assert metadata["description"] == "CHANGXIN MEMORY TECHNOLOGIES / CHINESE YUAN"

    def test_symbol_untouched(self):
        data = _config(_feed(feed_id=3520))
        changes, _ = build_changes(data["feeds"])
        apply_changes(data, changes)
        assert data["feeds"][0]["symbol"] == "Equity.CN.688825/CNY"


class TestVerifyText:
    def _before_after(self):
        data = _config(
            _feed(feed_id=3520), _feed(feed_id=3521, symbol="Equity.US.X/USD")
        )
        before_text = dump_config(data)
        changes, _ = build_changes(data["feeds"])
        apply_changes(data, changes)
        return before_text, dump_config(data), changes

    def test_passes_on_name_only_diff(self):
        before_text, after_text, changes = self._before_after()
        verify_text(before_text, after_text, changes)

    def test_untouched_feed_lines_are_identical(self):
        before_text, after_text, changes = self._before_after()
        differing = [
            b for b, a in zip(before_text.split("\n"), after_text.split("\n")) if b != a
        ]
        assert len(differing) == 1
        assert differing[0].strip().startswith('"name":')

    def test_rejects_unexpected_field_change(self):
        # Apply 1 name change to create after_text, but then replace that name change
        # with a description change. Count passes (1 diff line = 1 change), but branch catches it.
        data = _config(_feed(feed_id=3520))
        before_text = dump_config(data)
        changes, _ = build_changes(data["feeds"])
        apply_changes(data, changes)
        after_text = dump_config(data)
        # In after_text, undo the name change and modify the description instead.
        lines_after = list(after_text.split("\n"))
        name_found = False
        desc_found = False
        for i, line in enumerate(lines_after):
            if not name_found and '"name":' in line:
                # Undo the name change
                lines_after[i] = line.replace("CHANGXIN MEMORY TECHNOLOGIES", "688825")
                name_found = True
            elif not desc_found and '"description":' in line:
                # Change the description
                lines_after[i] = line.replace(
                    "CHANGXIN MEMORY TECHNOLOGIES",
                    "CORRUPTED NAME CHANGE",
                )
                desc_found = True
            if name_found and desc_found:
                break
        tampered = "\n".join(lines_after)
        with pytest.raises(VerificationError, match="is not a name field"):
            verify_text(before_text, tampered, changes)

    def test_rejects_line_count_change(self):
        before_text, after_text, changes = self._before_after()
        with pytest.raises(VerificationError, match="line count changed"):
            verify_text(before_text, after_text + "\n", changes)

    def test_rejects_wrong_change_count(self):
        before_text, after_text, changes = self._before_after()
        with pytest.raises(VerificationError, match="changed line"):
            verify_text(before_text, after_text, [])


class TestVerifyFeedNames:
    def test_verify_feed_names_passes_on_planned_change(self):
        before_data = _config(_feed(feed_id=3520))
        after_data = _config(_feed(feed_id=3520))
        changes, _ = build_changes(before_data["feeds"])
        apply_changes(after_data, changes)
        verify_feed_names(before_data, after_data, changes)

    def test_verify_feed_names_rejects_swapped_values(self):
        before_data = _config(
            _feed(feed_id=3520),
            _feed(
                feed_id=3521,
                symbol="Equity.JP.1234/JPY",
                name="1234",
                description="NIKKEI INC / JAPANESE YEN",
                quote_currency="JPY",
            ),
        )
        after_data = _config(
            _feed(feed_id=3520),
            _feed(
                feed_id=3521,
                symbol="Equity.JP.1234/JPY",
                name="1234",
                description="NIKKEI INC / JAPANESE YEN",
                quote_currency="JPY",
            ),
        )
        changes, _ = build_changes(before_data["feeds"])
        apply_changes(after_data, changes)
        # Swap the two new names between the two feeds
        after_data["feeds"][0]["metadata"]["name"] = changes[1].after
        after_data["feeds"][1]["metadata"]["name"] = changes[0].after
        with pytest.raises(VerificationError, match="do not match the plan"):
            verify_feed_names(before_data, after_data, changes)

    def test_verify_feed_names_rejects_unplanned_rename(self):
        before_data = _config(_feed(feed_id=3520))
        after_data = _config(_feed(feed_id=3520))
        changes, _ = build_changes(before_data["feeds"])
        apply_changes(after_data, changes)
        # Rename to something unexpected
        after_data["feeds"][0]["metadata"]["name"] = "WRONG_NAME"
        with pytest.raises(VerificationError, match="do not match the plan"):
            verify_feed_names(before_data, after_data, changes)

    def test_verify_feed_names_rejects_missing_rename(self):
        before_data = _config(_feed(feed_id=3520))
        after_data = _config(_feed(feed_id=3520))
        changes, _ = build_changes(before_data["feeds"])
        # Don't apply changes, so the name stays the same
        with pytest.raises(VerificationError, match="do not match the plan"):
            verify_feed_names(before_data, after_data, changes)

    def test_verify_on_disk_rejects_swapped_values(self, tmp_path):
        before_data = _config(
            _feed(feed_id=3520),
            _feed(
                feed_id=3521,
                symbol="Equity.JP.1234/JPY",
                name="1234",
                description="NIKKEI INC / JAPANESE YEN",
                quote_currency="JPY",
            ),
        )
        before_text = dump_config(before_data)
        path = tmp_path / "cfg.json"
        path.write_text(before_text, encoding="utf-8")
        changes, _ = build_changes(before_data["feeds"])
        after_data = _config(
            _feed(feed_id=3520),
            _feed(
                feed_id=3521,
                symbol="Equity.JP.1234/JPY",
                name="1234",
                description="NIKKEI INC / JAPANESE YEN",
                quote_currency="JPY",
            ),
        )
        apply_changes(after_data, changes)
        # Swap the two new names between the two feeds
        after_data["feeds"][0]["metadata"]["name"] = changes[1].after
        after_data["feeds"][1]["metadata"]["name"] = changes[0].after
        write_config(path, dump_config(after_data), backup=False)
        with pytest.raises(VerificationError, match="do not match the plan"):
            verify_on_disk(path, before_text, changes)


class TestWriteConfig:
    def test_writes_and_backs_up(self, tmp_path):
        path = tmp_path / "cfg.json"
        path.write_text("original", encoding="utf-8")
        write_config(path, "updated")
        assert path.read_text(encoding="utf-8") == "updated"
        assert (tmp_path / "cfg.json.bak").read_text(encoding="utf-8") == "original"

    def test_no_backup_flag(self, tmp_path):
        path = tmp_path / "cfg.json"
        path.write_text("original", encoding="utf-8")
        write_config(path, "updated", backup=False)
        assert not (tmp_path / "cfg.json.bak").exists()


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
        with pytest.raises(VerificationError, match="does not parse"):
            verify_on_disk(path, dump_config(_config(_feed())), [])

    def test_rejects_feed_count_change(self, tmp_path):
        before_data = _config(
            _feed(feed_id=3520), _feed(feed_id=3521, symbol="Equity.US.X/USD")
        )
        before_text = dump_config(before_data)
        path = tmp_path / "cfg.json"
        # Written file is missing one feed relative to before_text.
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
        assert written["feeds"][0]["metadata"]["name"] == "CHANGXIN MEMORY TECHNOLOGIES"
        assert (tmp_path / "cfg.json.bak").exists()

    def test_second_run_is_a_noop(self, tmp_path, capsys):
        path = _write_config(tmp_path, _feed(feed_id=3520))
        main(["--config", str(path), "--apply"])
        capsys.readouterr()
        assert main(["--config", str(path), "--apply"]) == 0
        assert "No changes" in capsys.readouterr().out

    def test_override_applied(self, tmp_path):
        path = _write_config(tmp_path, _feed(feed_id=3520))
        overrides = tmp_path / "ov.csv"
        overrides.write_text("feed_id,name\n3520,CXMT\n", encoding="utf-8")
        args = ["--config", str(path), "--name-overrides", str(overrides), "--apply"]
        assert main(args) == 0
        written = json.loads(path.read_text(encoding="utf-8"))
        assert written["feeds"][0]["metadata"]["name"] == "CXMT"

    def test_bad_override_exits_one_without_writing(self, tmp_path):
        path = _write_config(tmp_path, _feed(feed_id=3520))
        original = path.read_text(encoding="utf-8")
        overrides = tmp_path / "ov.csv"
        overrides.write_text("feed_id,name\n999,NOPE\n", encoding="utf-8")
        args = ["--config", str(path), "--name-overrides", str(overrides), "--apply"]
        assert main(args) == 1
        assert path.read_text(encoding="utf-8") == original

    def test_symbol_prefix_narrows_scope(self, tmp_path):
        path = _write_config(
            tmp_path,
            _feed(feed_id=3520),
            _feed(
                feed_id=884,
                symbol="Equity.HK.0002/HKD",
                name="0002",
                description="CLP HOLDINGS / HONG KONG DOLLAR",
                quote_currency="HKD",
            ),
        )
        assert (
            main(["--config", str(path), "--symbol-prefix", "Equity.HK.", "--apply"])
            == 0
        )
        written = json.loads(path.read_text(encoding="utf-8"))
        assert written["feeds"][0]["metadata"]["name"] == "688825"
        assert written["feeds"][1]["metadata"]["name"] == "CLP HOLDINGS"

    def test_missing_config_file_errors_cleanly(self, tmp_path, capsys):
        missing = tmp_path / "nope.json"
        assert main(["--config", str(missing)]) == 1
        err = capsys.readouterr().err
        assert "ERROR: Config file not found" in err
        assert str(missing) in err

    def test_trailing_newline_in_input_round_trips(self, tmp_path):
        path = tmp_path / "cfg.json"
        data = _config(_feed(feed_id=3520))
        path.write_text(dump_config(data) + "\n", encoding="utf-8")
        assert main(["--config", str(path), "--apply"]) == 0
        written_text = path.read_text(encoding="utf-8")
        assert written_text.endswith("\n")
        assert not written_text.endswith("\n\n")
        written = json.loads(written_text)
        assert written["feeds"][0]["metadata"]["name"] == "CHANGXIN MEMORY TECHNOLOGIES"

    def test_pre_write_verification_failure_writes_nothing(self, tmp_path, monkeypatch):
        path = _write_config(tmp_path, _feed(feed_id=3520))
        original = path.read_text(encoding="utf-8")

        def _boom(*args, **kwargs):
            raise VerificationError("boom")

        monkeypatch.setattr("rename_numeric_feed_names.verify_text", _boom)
        assert main(["--config", str(path), "--apply"]) == 1
        assert path.read_text(encoding="utf-8") == original
        assert not (tmp_path / "cfg.json.bak").exists()

    def test_post_write_verification_failure_leaves_backup(self, tmp_path, monkeypatch):
        path = _write_config(tmp_path, _feed(feed_id=3520))
        original = path.read_text(encoding="utf-8")

        def _boom(*args, **kwargs):
            raise VerificationError("boom")

        monkeypatch.setattr("rename_numeric_feed_names.verify_on_disk", _boom)
        assert main(["--config", str(path), "--apply"]) == 1
        assert (tmp_path / "cfg.json.bak").exists()
        assert (tmp_path / "cfg.json.bak").read_text(encoding="utf-8") == original

    def test_duplicate_warning_printed(self, tmp_path, capsys):
        path = _write_config(
            tmp_path,
            _feed(
                feed_id=3339,
                symbol="Equity.CN.603986/CNY",
                name="603986",
                description="GIGADEVICE SEMICONDUCTOR INC / CHINESE YUAN",
            ),
            _feed(
                feed_id=3360,
                symbol="Equity.HK.3986/HKD",
                name="3986",
                description="GIGADEVICE SEMICONDUCTOR INC / HONG KONG DOLLAR",
                quote_currency="HKD",
            ),
        )
        assert main(["--config", str(path), "--apply"]) == 0
        out = capsys.readouterr().out
        assert "WARNING" in out
        assert "GIGADEVICE SEMICONDUCTOR INC" in out


LIVE_CONFIG = Path("lazer-state.json")


@pytest.mark.skipif(
    not LIVE_CONFIG.exists(),
    reason="lazer-state.json is gitignored and not present in this checkout",
)
class TestLiveConfigSmoke:
    """Guards the measured expectations from the design doc.

    The config is gitignored, so these are skipped wherever it is absent.
    """

    def _feeds(self):
        return json.loads(LIVE_CONFIG.read_text(encoding="utf-8"))["feeds"]

    def test_452_changes_no_skips(self):
        changes, skips = build_changes(self._feeds())
        assert len(changes) == 452
        assert skips == []

    def test_two_duplicate_warnings_without_overrides(self):
        feeds = self._feeds()
        changes, _ = build_changes(feeds)
        duplicates = find_duplicate_names(feeds, changes)
        assert [name for name, _ in duplicates] == [
            "GIGADEVICE SEMICONDUCTOR INC",
            "MONTAGE TECHNOLOGY CO LTD",
        ]

    def test_no_duplicates_with_committed_overrides(self):
        feeds = self._feeds()
        overrides = load_overrides(Path("feed_name_overrides.csv"))
        changes, _ = build_changes(feeds, overrides=overrides)
        assert find_duplicate_names(feeds, changes) == []

    def test_feed_3520_gets_company_name(self):
        changes, _ = build_changes(self._feeds())
        by_id = {c.feed_id: c for c in changes}
        assert by_id[3520].before == "688825"
        assert by_id[3520].after == "CHANGXIN MEMORY TECHNOLOGIES"
