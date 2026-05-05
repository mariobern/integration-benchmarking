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
        assert 80 not in f["allowedPublisherIds"]

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
        assert 80 in f["allowedPublisherIds"]

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
        assert 80 in f["allowedPublisherIds"]

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
        assert 80 in f1["allowedPublisherIds"]
        assert 80 in f100["allowedPublisherIds"]

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
