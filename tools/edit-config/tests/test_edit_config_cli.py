import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = REPO_ROOT / "tools" / "edit-config" / "edit_config.py"
FIXTURE = Path(__file__).parent / "fixtures" / "after_sample.json"


def run_cli(args: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd or REPO_ROOT),
    )


def _regular_ids(feed: dict) -> list[int]:
    reg = next(s for s in feed["marketSchedules"] if s["session"] == "REGULAR")
    return reg.get("allowedPublisherIds", [])


@pytest.fixture
def config_copy(tmp_path):
    dst = tmp_path / "after.json"
    shutil.copy(FIXTURE, dst)
    return dst


class TestCli:
    def test_dry_run_default(self, config_copy):
        result = run_cli(
            [
                "--config",
                str(config_copy),
                "--add-publisher",
                "80",
                "--feed-id",
                "1",
            ]
        )
        assert result.returncode == 0, result.stderr
        # Config should be unchanged (dry run)
        assert "[DRY RUN]" in result.stdout
        data = json.loads(config_copy.read_text())
        f = next(x for x in data["feeds"] if x["feedId"] == 1)
        assert 80 not in _regular_ids(f)

    def test_apply_writes_changes(self, config_copy):
        result = run_cli(
            [
                "--config",
                str(config_copy),
                "--add-publisher",
                "80",
                "--feed-id",
                "1",
                "--apply",
            ]
        )
        assert result.returncode == 0, result.stderr
        data = json.loads(config_copy.read_text())
        f = next(x for x in data["feeds"] if x["feedId"] == 1)
        assert 80 in _regular_ids(f)

    def test_apply_writes_backup(self, config_copy):
        run_cli(
            [
                "--config",
                str(config_copy),
                "--add-publisher",
                "80",
                "--feed-id",
                "1",
                "--apply",
            ]
        )
        bak = config_copy.parent / "after.json.bak"
        assert bak.exists()
        # Backup matches original fixture
        assert json.loads(bak.read_text()) == json.loads(FIXTURE.read_text())

    def test_no_backup_flag_skips_bak(self, config_copy):
        run_cli(
            [
                "--config",
                str(config_copy),
                "--add-publisher",
                "80",
                "--feed-id",
                "1",
                "--apply",
                "--no-backup",
            ]
        )
        assert not (config_copy.parent / "after.json.bak").exists()

    def test_zero_match_exits_nonzero(self, config_copy):
        result = run_cli(
            [
                "--config",
                str(config_copy),
                "--add-publisher",
                "80",
                "--feed-id",
                "99999",
            ]
        )
        assert result.returncode != 0

    def test_warning_does_not_fail(self, config_copy):
        # State change with a regression warning should still exit 0.
        result = run_cli(
            [
                "--config",
                str(config_copy),
                "--set-state",
                "INACTIVE",
                "--feed-id",
                "1",
                "--apply",
            ]
        )
        assert result.returncode == 0
        assert "WARNING" in result.stdout or "warning" in result.stdout.lower()

    def test_set_state_inactive_marks_description_deprecated(self, config_copy):
        result = run_cli(
            [
                "--config",
                str(config_copy),
                "--set-state",
                "INACTIVE",
                "--feed-id",
                "922",
                "--apply",
            ]
        )
        assert result.returncode == 0, result.stderr
        data = json.loads(config_copy.read_text())
        f = next(x for x in data["feeds"] if x["feedId"] == 922)
        assert f["state"] == "INACTIVE"
        assert f["metadata"]["description"] == "DEPRECATED FEED - APPLE INC / US DOLLAR"

    def test_reactivation_round_trips_description(self, config_copy):
        deactivate = run_cli(
            [
                "--config",
                str(config_copy),
                "--set-state",
                "INACTIVE",
                "--feed-id",
                "922",
                "--apply",
            ]
        )
        assert deactivate.returncode == 0, deactivate.stderr
        reactivate = run_cli(
            [
                "--config",
                str(config_copy),
                "--set-state",
                "STABLE",
                "--feed-id",
                "922",
                "--apply",
            ]
        )
        assert reactivate.returncode == 0, reactivate.stderr
        data = json.loads(config_copy.read_text())
        f = next(x for x in data["feeds"] if x["feedId"] == 922)
        assert f["state"] == "STABLE"
        assert f["metadata"]["description"] == "APPLE INC / US DOLLAR"

    def test_yaml_spec(self, config_copy, tmp_path):
        spec = tmp_path / "spec.yaml"
        spec.write_text(
            "operations:\n"
            "  - op: add_publisher\n"
            "    publisher_id: 80\n"
            "    feed_id: 1\n",
            encoding="utf-8",
        )
        result = run_cli(
            [
                "--config",
                str(config_copy),
                "--from-spec",
                str(spec),
                "--apply",
            ]
        )
        assert result.returncode == 0, result.stderr
        data = json.loads(config_copy.read_text())
        f = next(x for x in data["feeds"] if x["feedId"] == 1)
        assert 80 in _regular_ids(f)

    def test_feed_ids_from_file(self, config_copy, tmp_path):
        ids_file = tmp_path / "ids.txt"
        ids_file.write_text("1, 100", encoding="utf-8")
        result = run_cli(
            [
                "--config",
                str(config_copy),
                "--add-publisher",
                "80",
                "--feed-ids-from",
                str(ids_file),
                "--apply",
            ]
        )
        assert result.returncode == 0, result.stderr
        data = json.loads(config_copy.read_text())
        f1 = next(x for x in data["feeds"] if x["feedId"] == 1)
        f100 = next(x for x in data["feeds"] if x["feedId"] == 100)
        assert 80 in _regular_ids(f1)
        assert 80 in _regular_ids(f100)

    def test_diff_always_prints_on_dry_run(self, config_copy):
        result = run_cli(
            [
                "--config",
                str(config_copy),
                "--add-publisher",
                "80",
                "--feed-id",
                "1",
            ]
        )
        assert "@@ feedId 1" in result.stdout

    def test_old_format_config_rejected(self, tmp_path):
        old = {
            "feeds": [
                {
                    "feedId": 1,
                    "symbol": "Crypto.BTC/USD",
                    "state": "STABLE",
                    "allowedPublisherIds": [1, 3],
                    "minPublishers": 1,
                    "marketSchedules": [{"session": "REGULAR"}],
                }
            ]
        }
        cfg = tmp_path / "after.json"
        cfg.write_text(json.dumps(old, indent=2), encoding="utf-8")
        result = run_cli(
            ["--config", str(cfg), "--add-publisher", "80", "--feed-id", "1"]
        )
        assert result.returncode == 1
        assert "old format" in result.stderr


class TestCliInProcess:
    """In-process tests calling main() directly so coverage can track edit_config.py.

    Subprocess invocations in TestCli are end-to-end smoke tests but the
    parent pytest coverage tracker can't see lines exercised inside the
    spawned interpreter. These tests reach the same code paths via
    main(argv) so the coverage report reflects reality.
    """

    def _import_main(self):
        # Import lazily so the conftest sys.path tweak applies.
        import importlib

        module = importlib.import_module("edit_config")
        return module

    def test_dry_run(self, config_copy, capsys):
        m = self._import_main()
        rc = m.main(
            [
                "--config",
                str(config_copy),
                "--add-publisher",
                "80",
                "--feed-id",
                "1",
            ]
        )
        out = capsys.readouterr().out
        assert rc == 0
        assert "[DRY RUN]" in out
        assert "@@ feedId 1" in out

    def test_apply_does_not_run_linter(self, config_copy, capsys):
        # The linter is intentionally NOT auto-run after --apply; users
        # invoke tools/config-linter/config_linter.py separately.
        m = self._import_main()
        rc = m.main(
            [
                "--config",
                str(config_copy),
                "--add-publisher",
                "80",
                "--feed-id",
                "1",
                "--apply",
            ]
        )
        out = capsys.readouterr().out
        assert rc == 0
        assert "Backup written" in out
        assert "Lint:" not in out
        assert "config-linter" not in out

    def test_apply_no_changes(self, config_copy, capsys):
        # Adding publisher 1 to feed 1 (already present) yields no changes.
        m = self._import_main()
        rc = m.main(
            [
                "--config",
                str(config_copy),
                "--add-publisher",
                "1",
                "--feed-id",
                "1",
                "--apply",
            ]
        )
        out = capsys.readouterr().out
        assert rc == 0
        assert "No changes to write." in out

    def test_apply_with_errors_refuses(self, config_copy, capsys):
        # No matching feeds → simulation reports an error → apply refuses.
        m = self._import_main()
        rc = m.main(
            [
                "--config",
                str(config_copy),
                "--add-publisher",
                "80",
                "--feed-id",
                "99999",
                "--apply",
            ]
        )
        err = capsys.readouterr().err
        assert rc == 1
        assert "Refusing to write" in err

    def test_no_op_flag_returns_error(self, config_copy, capsys):
        m = self._import_main()
        rc = m.main(["--config", str(config_copy), "--feed-id", "1"])
        err = capsys.readouterr().err
        assert rc == 1
        assert "no operation" in err.lower()

    def test_yaml_spec_in_process(self, config_copy, tmp_path, capsys):
        spec = tmp_path / "spec.yaml"
        spec.write_text(
            "operations:\n"
            "  - op: add_publisher\n"
            "    publisher_id: 80\n"
            "    feed_id: 1\n",
            encoding="utf-8",
        )
        m = self._import_main()
        rc = m.main(
            [
                "--config",
                str(config_copy),
                "--from-spec",
                str(spec),
            ]
        )
        out = capsys.readouterr().out
        assert rc == 0
        assert "1 operations" in out

    def test_warning_dry_run(self, config_copy, capsys):
        m = self._import_main()
        rc = m.main(
            [
                "--config",
                str(config_copy),
                "--set-state",
                "INACTIVE",
                "--feed-id",
                "1",
            ]
        )
        out = capsys.readouterr().out
        assert rc == 0
        assert "WARNING" in out or "warning" in out.lower()

    def test_show_full_diff_flag(self, config_copy, capsys):
        m = self._import_main()
        rc = m.main(
            [
                "--config",
                str(config_copy),
                "--add-publisher",
                "80",
                "--feed-id",
                "1",
                "--show-full-diff",
            ]
        )
        out = capsys.readouterr().out
        assert rc == 0
        assert "@@ feedId 1" in out

    def test_old_format_config_rejected_in_process(self, tmp_path, capsys):
        old = {
            "feeds": [
                {
                    "feedId": 1,
                    "symbol": "Crypto.BTC/USD",
                    "state": "STABLE",
                    "allowedPublisherIds": [1, 3],
                    "minPublishers": 1,
                    "marketSchedules": [{"session": "REGULAR"}],
                }
            ]
        }
        cfg = tmp_path / "after.json"
        cfg.write_text(json.dumps(old, indent=2), encoding="utf-8")
        m = self._import_main()
        rc = m.main(["--config", str(cfg), "--add-publisher", "80", "--feed-id", "1"])
        err = capsys.readouterr().err
        assert rc == 1
        assert "old format" in err


FIXTURES = Path(__file__).parent / "fixtures"
TOOL = Path(__file__).resolve().parents[1] / "edit_config.py"


def _run_cli_ric(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(TOOL), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_set_ric_mapping_dry_run(tmp_path):
    config = tmp_path / "after.json"
    shutil.copy(FIXTURES / "hk_sample.json", config)
    csv_path = FIXTURES / "hk-syms-sample.csv"

    result = _run_cli_ric(
        [
            "--config",
            str(config),
            "--set-ric-mapping",
            "--from-csv",
            str(csv_path),
            "--dry-run",
        ]
    )
    assert result.returncode == 0, result.stderr
    assert config.read_text() == (FIXTURES / "hk_sample.json").read_text()
    out = result.stdout + result.stderr
    assert "884" in out
    assert "0700.HK" in out


def test_cli_set_ric_mapping_apply(tmp_path):
    config = tmp_path / "after.json"
    shutil.copy(FIXTURES / "hk_sample.json", config)
    csv_path = FIXTURES / "hk-syms-sample.csv"

    result = _run_cli_ric(
        [
            "--config",
            str(config),
            "--set-ric-mapping",
            "--from-csv",
            str(csv_path),
            "--apply",
        ]
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(config.read_text())
    feeds_by_id = {f["feedId"]: f for f in data["feeds"]}
    assert (
        feeds_by_id[884]["marketSchedules"][0]["benchmarkMapping"]["datascope_ric"][
            "identifiers"
        ][0]["identifier"]
        == "0700.HK"
    )
    assert (
        feeds_by_id[885]["marketSchedules"][0]["benchmarkMapping"]["datascope_ric"][
            "identifiers"
        ][0]["identifier"]
        == "STALE.HK"
    )
    assert (
        feeds_by_id[886]["marketSchedules"][0]["benchmarkMapping"]["datascope_ric"][
            "identifiers"
        ][0]["identifier"]
        == ""
    )
    assert feeds_by_id[1000]["symbol"] == "Crypto.BTC/USD"


def test_cli_set_ric_mapping_requires_from_csv(tmp_path):
    config = tmp_path / "after.json"
    shutil.copy(FIXTURES / "hk_sample.json", config)
    result = _run_cli_ric(["--config", str(config), "--set-ric-mapping"])
    assert result.returncode != 0
    assert "--from-csv" in (result.stdout + result.stderr)


def test_cli_set_ric_mapping_reports_unmatched_csv_rows(tmp_path):
    """RIC mapping summary block appears, and unmatched RIC 1211.HK is listed."""
    config = tmp_path / "after.json"
    shutil.copy(FIXTURES / "hk_sample.json", config)
    csv_path = FIXTURES / "hk-syms-sample.csv"

    result = _run_cli_ric(
        [
            "--config",
            str(config),
            "--set-ric-mapping",
            "--from-csv",
            str(csv_path),
            "--apply",
        ]
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout + result.stderr
    assert "RIC mapping summary" in out
    assert "1211.HK" in out  # unmatched — no feed in fixture has this symbol
    assert "0700.HK" in out  # filled into feed 884
    assert "885" in out  # skipped feed (already populated)


# ---------------------------------------------------------------------------
# --set-ric (in-process, patched resolver — no network)
# ---------------------------------------------------------------------------
# conftest puts tools/edit-config on sys.path before collection, so a
# module-level import is safe here.
import edit_config

from edit_config_lib import config_editor as _ce
from edit_config_lib.config_ops import ResolvedRic as _ResolvedRic


def _write_us_config(path):
    cfg = {
        "feeds": [
            {
                "feedId": 990,
                "symbol": "Equity.US.BITS/USD",
                "state": "STABLE",
                "metadata": {"name": "BITS", "asset_type": "equity"},
                "marketSchedules": [
                    {
                        "session": "REGULAR",
                        "benchmarkMapping": {
                            "datascope_ric": {"identifiers": [{"identifier": "BITS"}]}
                        },
                    },
                    {
                        "session": "OVER_NIGHT",
                        "benchmarkMapping": {
                            "datascope_ric": {
                                "identifiers": [{"identifier": "BITS.BLUE"}]
                            }
                        },
                    },
                ],
            }
        ]
    }
    path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")


def test_cli_set_ric_apply_in_process(tmp_path, monkeypatch, capsys):
    config = tmp_path / "after.json"
    _write_us_config(config)

    def fake_resolve(feed_ids, symbols_path, force_refresh=False, resolver=None):
        return {990: _ResolvedRic(day_ric="BITS.O", overnight_ric="BITS.BLUE")}

    monkeypatch.setattr(_ce, "resolve_rics_for_feed_ids", fake_resolve)

    rc = edit_config.main(
        ["--config", str(config), "--set-ric", "--feed-id", "990", "--apply"]
    )
    out = capsys.readouterr().out
    assert "RIC resolution summary:" in out
    assert "identifiers overwritten: 1" in out
    assert rc == 0
    data = json.loads(config.read_text())
    feed = data["feeds"][0]
    reg = feed["marketSchedules"][0]["benchmarkMapping"]["datascope_ric"][
        "identifiers"
    ][0]["identifier"]
    ovn = feed["marketSchedules"][1]["benchmarkMapping"]["datascope_ric"][
        "identifiers"
    ][0]["identifier"]
    assert reg == "BITS.O"  # bare day RIC rewritten
    assert ovn == "BITS.BLUE"  # overnight unchanged


def test_cli_set_ric_dry_run_does_not_write(tmp_path, monkeypatch):
    config = tmp_path / "after.json"
    _write_us_config(config)
    before = config.read_text()

    def fake_resolve(feed_ids, symbols_path, force_refresh=False, resolver=None):
        return {990: _ResolvedRic(day_ric="BITS.O", overnight_ric="BITS.BLUE")}

    monkeypatch.setattr(_ce, "resolve_rics_for_feed_ids", fake_resolve)

    rc = edit_config.main(["--config", str(config), "--set-ric", "--feed-id", "990"])
    assert rc == 0
    assert config.read_text() == before  # dry-run default, nothing written


# ---------------------------------------------------------------------------
# --remove-ric (uses the hk_sample.json fixture: 885 = STALE.HK populated,
# 884/886 = empty, 1000 = no datascope_ric slots)
# ---------------------------------------------------------------------------
def test_cli_remove_ric_dry_run_does_not_write(tmp_path):
    config = tmp_path / "after.json"
    shutil.copy(FIXTURES / "hk_sample.json", config)
    before = config.read_text()
    result = _run_cli_ric(["--config", str(config), "--remove-ric", "--feed-id", "885"])
    assert result.returncode == 0, result.stderr
    out = result.stdout + result.stderr
    assert "[DRY RUN]" in out
    assert "RIC removal summary" in out
    assert "STALE.HK" in out  # the value being wiped is shown
    assert config.read_text() == before  # nothing written


def test_cli_remove_ric_apply_clears_value(tmp_path):
    config = tmp_path / "after.json"
    shutil.copy(FIXTURES / "hk_sample.json", config)
    result = _run_cli_ric(
        ["--config", str(config), "--remove-ric", "--feed-id", "885", "--apply"]
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(config.read_text())
    feeds_by_id = {f["feedId"]: f for f in data["feeds"]}
    cleared = feeds_by_id[885]["marketSchedules"][0]["benchmarkMapping"][
        "datascope_ric"
    ]["identifiers"][0]["identifier"]
    assert cleared == ""


def test_cli_remove_ric_already_empty_no_changes(tmp_path):
    config = tmp_path / "after.json"
    shutil.copy(FIXTURES / "hk_sample.json", config)
    # Feed 884 already has an empty identifier -> nothing to clear.
    result = _run_cli_ric(
        ["--config", str(config), "--remove-ric", "--feed-id", "884", "--apply"]
    )
    assert result.returncode == 0, result.stderr
    assert "No changes to write." in (result.stdout + result.stderr)


def test_cli_remove_ric_no_slots_warns(tmp_path):
    config = tmp_path / "after.json"
    shutil.copy(FIXTURES / "hk_sample.json", config)
    # Feed 1000 (Crypto.BTC) has empty marketSchedules -> no slots warning.
    result = _run_cli_ric(
        ["--config", str(config), "--remove-ric", "--feed-id", "1000"]
    )
    assert result.returncode == 0, result.stderr
    out = result.stdout + result.stderr
    assert "nothing to clear" in out


def test_cli_remove_ric_stable_feed_footer_counts(tmp_path):
    # A STABLE feed with a populated RIC -> the footer's STABLE counter is 1
    # and a STABLE-feed warning is emitted (dry-run).
    config = tmp_path / "after.json"
    cfg = {
        "feeds": [
            {
                "feedId": 777,
                "symbol": "Equity.US.FOO/USD",
                "state": "STABLE",
                "metadata": {"asset_type": "equity"},
                "marketSchedules": [
                    {
                        "session": "REGULAR",
                        "benchmarkMapping": {
                            "datascope_ric": {"identifiers": [{"identifier": "FOO.O"}]}
                        },
                    }
                ],
                "minPublishers": 1,
            }
        ]
    }
    config.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    result = _run_cli_ric(["--config", str(config), "--remove-ric", "--feed-id", "777"])
    assert result.returncode == 0, result.stderr
    out = result.stdout + result.stderr
    assert "STABLE feeds affected:  1" in out
    assert "STABLE feed" in out  # the per-feed warning fired


EX_FIXTURE = Path(__file__).parent / "fixtures" / "after_with_exchanges.json"


@pytest.fixture
def ex_config_copy(tmp_path):
    dst = tmp_path / "after_with_exchanges.json"
    shutil.copy(EX_FIXTURE, dst)
    return dst


def _feed(data, fid):
    return next(f for f in data["feeds"] if f["feedId"] == fid)


class TestExchangeCli:
    def test_add_exchange_id_apply(self, ex_config_copy):
        r = run_cli(
            [
                "--config",
                str(ex_config_copy),
                "--add-exchange-id",
                "1",
                "--feed-id",
                "100",
                "--apply",
            ]
        )
        assert r.returncode == 0, r.stderr
        data = json.loads(ex_config_copy.read_text())
        feed = _feed(data, 100)
        assert feed["exchangeId"] == 1
        assert all("marketSchedule" not in s for s in feed["marketSchedules"])

    def test_remove_exchange_id_apply(self, ex_config_copy):
        r = run_cli(
            [
                "--config",
                str(ex_config_copy),
                "--remove-exchange-id",
                "--feed-id",
                "200",
                "--apply",
            ]
        )
        assert r.returncode == 0, r.stderr
        feed = _feed(json.loads(ex_config_copy.read_text()), 200)
        assert "exchangeId" not in feed
        reg = next(s for s in feed["marketSchedules"] if s["session"] == "REGULAR")
        assert reg["marketSchedule"] == "America/New_York;0930-1600;R"

    def test_unknown_exchange_id_errors(self, ex_config_copy):
        r = run_cli(
            [
                "--config",
                str(ex_config_copy),
                "--add-exchange-id",
                "99",
                "--feed-id",
                "100",
            ]
        )
        assert r.returncode == 1
        assert "not defined in exchanges" in (r.stdout + r.stderr)

    def test_session_not_covered_blocks_apply(self, ex_config_copy):
        # feed 400 has OVER_NIGHT; exchange 21 (HK) lacks it.
        r = run_cli(
            [
                "--config",
                str(ex_config_copy),
                "--add-exchange-id",
                "21",
                "--feed-id",
                "400",
                "--apply",
            ]
        )
        assert r.returncode == 1
        assert "does not define session" in (r.stdout + r.stderr)
        # nothing written
        feed = _feed(json.loads(ex_config_copy.read_text()), 400)
        assert "exchangeId" not in feed

    def test_add_then_remove_round_trips_schedules(self, ex_config_copy):
        # Add exchange 1 to feed 100 (strips its 4 OLD-* strings).
        r1 = run_cli(
            [
                "--config",
                str(ex_config_copy),
                "--add-exchange-id",
                "1",
                "--feed-id",
                "100",
                "--apply",
            ]
        )
        assert r1.returncode == 0, r1.stderr
        # Remove it again (restores strings from exchange 1's definition).
        r2 = run_cli(
            [
                "--config",
                str(ex_config_copy),
                "--remove-exchange-id",
                "--feed-id",
                "100",
                "--apply",
            ]
        )
        assert r2.returncode == 0, r2.stderr
        feed = _feed(json.loads(ex_config_copy.read_text()), 100)
        assert "exchangeId" not in feed
        by_session = {
            s["session"]: s.get("marketSchedule") for s in feed["marketSchedules"]
        }
        # Restored values come from exchange 1, not the original OLD-* strings.
        assert by_session["REGULAR"] == "America/New_York;0930-1600;R"
        assert by_session["OVER_NIGHT"] == "America/New_York;2000-0400;O"

    def test_add_cleans_up_anomaly_feed(self, ex_config_copy):
        # Feed 300 already has exchangeId 1 AND two stale strings.
        r = run_cli(
            [
                "--config",
                str(ex_config_copy),
                "--add-exchange-id",
                "1",
                "--feed-id",
                "300",
                "--apply",
            ]
        )
        assert r.returncode == 0, r.stderr
        feed = _feed(json.loads(ex_config_copy.read_text()), 300)
        assert feed["exchangeId"] == 1
        assert all("marketSchedule" not in s for s in feed["marketSchedules"])


STALE_FIXTURE = Path(__file__).parent / "fixtures" / "stale_sample.json"


@pytest.fixture
def stale_config(tmp_path):
    dst = tmp_path / "stale.json"
    shutil.copy(STALE_FIXTURE, dst)
    return dst


def _spf(path, feed_id):
    feeds = json.loads(Path(path).read_text(encoding="utf-8"))["feeds"]
    feed = next(f for f in feeds if f["feedId"] == feed_id)
    return feed["marketSchedules"][0].get("stalePriceFilter")


class TestStaleFilterCli:
    def test_dry_run_reports_change_and_writes_nothing(self, stale_config):
        before = stale_config.read_text(encoding="utf-8")
        result = run_cli(
            ["--config", str(stale_config), "--set-stale-filter", "--feed-id", "1990"]
        )
        assert result.returncode == 0
        assert "[DRY RUN]" in result.stdout
        assert "@@ feedId 1990" in result.stdout
        assert stale_config.read_text(encoding="utf-8") == before

    def test_apply_creates_filter(self, stale_config):
        result = run_cli(
            [
                "--config",
                str(stale_config),
                "--set-stale-filter",
                "--feed-id",
                "1990",
                "--apply",
                "--no-backup",
            ]
        )
        assert result.returncode == 0
        assert _spf(stale_config, 1990) == {
            "movedPriceThresholdBps": 0.5,
            "stalenessThresholdSecs": 10800,
            "windowSecs": 60,
        }

    def test_apply_patches_single_knob(self, stale_config):
        result = run_cli(
            [
                "--config",
                str(stale_config),
                "--set-stale-filter",
                "--window-secs",
                "120",
                "--feed-id",
                "2166",
                "--apply",
                "--no-backup",
            ]
        )
        assert result.returncode == 0
        assert _spf(stale_config, 2166) == {
            "movedPriceThresholdBps": 0.5,
            "stalenessThresholdSecs": 10800,
            "windowSecs": 120,
        }

    def test_apply_clear(self, stale_config):
        result = run_cli(
            [
                "--config",
                str(stale_config),
                "--clear-stale-filter",
                "--feed-id",
                "2166",
                "--apply",
                "--no-backup",
            ]
        )
        assert result.returncode == 0
        assert _spf(stale_config, 2166) is None

    def test_value_flag_without_set_flag_errors(self, stale_config):
        result = run_cli(
            [
                "--config",
                str(stale_config),
                "--add-publisher",
                "80",
                "--window-secs",
                "120",
                "--feed-id",
                "1990",
            ]
        )
        assert result.returncode == 1
        assert "--window-secs" in result.stdout + result.stderr

    def test_feed_ids_from_csv(self, stale_config, tmp_path):
        csv_path = tmp_path / "batch.csv"
        csv_path.write_text(
            "1990, 2026-07-24, jp-equities\n2166, 2026-07-24, kr-equities\n",
            encoding="utf-8",
        )
        result = run_cli(
            [
                "--config",
                str(stale_config),
                "--set-stale-filter",
                "--feed-ids-from",
                str(csv_path),
                "--apply",
                "--no-backup",
            ]
        )
        assert result.returncode == 0
        assert _spf(stale_config, 1990) is not None

    def test_yaml_spec(self, stale_config, tmp_path):
        spec = tmp_path / "spec.yaml"
        spec.write_text(
            "version: 1\n"
            "operations:\n"
            "  - op: set_stale_filter\n"
            "    feed_id: 1990\n"
            "    session: REGULAR\n"
            "    window_secs: 90\n"
            "  - op: clear_stale_filter\n"
            "    feed_id: 2166\n"
            "    session: REGULAR\n",
            encoding="utf-8",
        )
        result = run_cli(
            [
                "--config",
                str(stale_config),
                "--from-spec",
                str(spec),
                "--apply",
                "--no-backup",
            ]
        )
        assert result.returncode == 0
        assert _spf(stale_config, 1990)["windowSecs"] == 90
        assert _spf(stale_config, 2166) is None
