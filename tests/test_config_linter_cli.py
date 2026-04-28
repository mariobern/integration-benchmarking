import json
import subprocess
import sys
from pathlib import Path

PROJECT_DIR = str(Path(__file__).resolve().parent.parent)


def _write_config(tmp_dir, config):
    path = Path(tmp_dir) / "after.json"
    path.write_text(json.dumps(config))
    return str(path)


def _run_linter(*args):
    result = subprocess.run(
        [sys.executable, "config_linter.py", *args],
        capture_output=True,
        text=True,
        cwd=PROJECT_DIR,
    )
    return result


def _make_clean_config():
    return {
        "feeds": [
            {
                "feedId": 1,
                "symbol": "Crypto.BTC/USD",
                "state": "STABLE",
                "kind": "PRICE",
                "minPublishers": 3,
                "allowedPublisherIds": [1, 2, 3, 4, 5],
                "metadata": {"asset_type": "crypto"},
                "marketSchedules": [
                    {
                        "marketSchedule": "America/New_York;O,O,O,O,O,O,O;",
                        "session": "REGULAR",
                    }
                ],
            }
        ],
        "publishers": [
            {
                "publisherId": i,
                "name": f"pub{i}",
                "keyType": "PRODUCTION",
                "isActive": True,
            }
            for i in range(1, 6)
        ],
    }


class TestCLIExitCodes:
    def test_clean_config_exits_0(self, tmp_path):
        path = _write_config(tmp_path, _make_clean_config())
        result = _run_linter("--config", path)
        assert result.returncode == 0

    def test_errors_exit_1(self, tmp_path):
        config = _make_clean_config()
        config["feeds"].append(config["feeds"][0].copy())  # duplicate feedId
        path = _write_config(tmp_path, config)
        result = _run_linter("--config", path)
        assert result.returncode == 1

    def test_warnings_only_exit_0(self, tmp_path):
        config = _make_clean_config()
        config["feeds"][0]["minPublishers"] = 4  # W005: only 1 headroom
        path = _write_config(tmp_path, config)
        result = _run_linter("--config", path)
        assert result.returncode == 0
        assert "W005" in result.stdout

    def test_warnings_as_errors_exit_1(self, tmp_path):
        config = _make_clean_config()
        config["feeds"][0]["minPublishers"] = 4  # W005
        path = _write_config(tmp_path, config)
        result = _run_linter("--config", path, "--warnings-as-errors")
        assert result.returncode == 1


class TestCLIOutputFormats:
    def test_text_format(self, tmp_path):
        config = _make_clean_config()
        config["feeds"].append(config["feeds"][0].copy())
        path = _write_config(tmp_path, config)
        result = _run_linter("--config", path, "--format", "text")
        assert "E001" in result.stdout
        assert "Summary:" in result.stdout

    def test_json_format(self, tmp_path):
        config = _make_clean_config()
        config["feeds"].append(config["feeds"][0].copy())
        path = _write_config(tmp_path, config)
        result = _run_linter("--config", path, "--format", "json")
        findings = json.loads(result.stdout)
        assert isinstance(findings, list)
        assert any(f["rule_id"] == "E001" for f in findings)

    def test_json_format_clean(self, tmp_path):
        path = _write_config(tmp_path, _make_clean_config())
        result = _run_linter("--config", path, "--format", "json")
        findings = json.loads(result.stdout)
        errors = [f for f in findings if f["severity"] == "ERROR"]
        assert len(errors) == 0


class TestCLIFileHandling:
    def test_missing_file(self):
        result = _run_linter("--config", "/nonexistent/after.json")
        assert result.returncode == 1
        assert (
            "not found" in result.stderr.lower() or "not found" in result.stdout.lower()
        )

    def test_invalid_json(self, tmp_path):
        path = Path(tmp_path) / "bad.json"
        path.write_text("{invalid json")
        result = _run_linter("--config", str(path))
        assert result.returncode == 1


class TestCLIBaseline:
    def test_explicit_baseline_path_diff_mode(self, tmp_path):
        # Pre-existing E001 (duplicate feedId) in both files; --baseline
        # should suppress it and exit 0.
        bad = _make_clean_config()
        bad["feeds"].append(bad["feeds"][0].copy())
        before_path = Path(tmp_path) / "before.json"
        before_path.write_text(json.dumps(bad))
        after_path = _write_config(tmp_path, bad)
        result = _run_linter("--config", after_path, "--baseline", str(before_path))
        assert result.returncode == 0
        assert "No new issues found" in result.stdout
        assert "pre-existing" in result.stdout

    def test_explicit_baseline_reports_only_new(self, tmp_path):
        clean = _make_clean_config()
        with_dup = _make_clean_config()
        # Duplicate the feedId only (different symbol) so only E001 fires.
        dup_feed = with_dup["feeds"][0].copy()
        dup_feed["symbol"] = "Crypto.ETH/USD"
        with_dup["feeds"].append(dup_feed)
        before_path = Path(tmp_path) / "before.json"
        before_path.write_text(json.dumps(clean))
        after_path = _write_config(tmp_path, with_dup)
        result = _run_linter("--config", after_path, "--baseline", str(before_path))
        assert result.returncode == 1
        assert "ERRORS (1 new)" in result.stdout
        assert "E001" in result.stdout

    def test_no_baseline_disables_diff(self, tmp_path):
        bad = _make_clean_config()
        # Duplicate the feedId only (different symbol) so only E001 fires.
        dup_feed = bad["feeds"][0].copy()
        dup_feed["symbol"] = "Crypto.ETH/USD"
        bad["feeds"].append(dup_feed)
        path = _write_config(tmp_path, bad)
        # Even though the linter is invoked outside any meaningful PR
        # context, --no-baseline forces full lint and exits non-zero.
        result = _run_linter("--config", path, "--no-baseline")
        assert result.returncode == 1
        assert "ERRORS (1 found)" in result.stdout
        assert "pre-existing" not in result.stdout

    def test_baseline_and_no_baseline_are_mutually_exclusive(self, tmp_path):
        path = _write_config(tmp_path, _make_clean_config())
        before = Path(tmp_path) / "before.json"
        before.write_text(json.dumps(_make_clean_config()))
        result = _run_linter(
            "--config",
            path,
            "--baseline",
            str(before),
            "--no-baseline",
        )
        assert result.returncode != 0
        assert "not allowed with" in result.stderr.lower()

    def test_summary_line_diff_mode(self, tmp_path):
        before = _make_clean_config()
        before["feeds"].append(before["feeds"][0].copy())  # pre-existing E001
        after = _make_clean_config()
        after["feeds"].append(after["feeds"][0].copy())  # same pre-existing
        # Add a new error: duplicate hermes_id.
        # Easier: append a second clean feed with same feedId again ->
        # actually we already have E001 from the dup; introduce a new
        # finding by emptying allowedPublisherIds on the first feed.
        after["feeds"][0]["allowedPublisherIds"] = []  # E005
        before_path = Path(tmp_path) / "before.json"
        before_path.write_text(json.dumps(before))
        after_path = _write_config(tmp_path, after)
        result = _run_linter("--config", after_path, "--baseline", str(before_path))
        # E001 was pre-existing and is suppressed; E005 is new.
        assert "E005" in result.stdout
        assert "E001" not in result.stdout
        assert "Summary:" in result.stdout
        assert "pre-existing findings suppressed" in result.stdout

    def test_baseline_missing_file_fails(self, tmp_path):
        path = _write_config(tmp_path, _make_clean_config())
        result = _run_linter(
            "--config",
            path,
            "--baseline",
            "/nonexistent/before.json",
        )
        assert result.returncode == 1
        assert (
            "not found" in result.stderr.lower() or "not found" in result.stdout.lower()
        )

    def test_auto_detect_outside_git_falls_back(self, tmp_path):
        # tmp_path is not a git repo. We invoke the linter with cwd=tmp_path
        # so auto-detect runs and finds no git, prints a NOTE to stderr,
        # and runs full lint.
        path = _write_config(tmp_path, _make_clean_config())
        result = subprocess.run(
            [
                sys.executable,
                str(Path(PROJECT_DIR) / "config_linter.py"),
                "--config",
                path,
            ],
            capture_output=True,
            text=True,
            cwd=str(tmp_path),
        )
        assert "NOTE: baseline unavailable" in result.stderr
        assert "running full lint" in result.stderr

    def test_warnings_as_errors_diff_mode_only_counts_new(self, tmp_path):
        # Pre-existing W005 (only-1-headroom) in before; same finding in
        # after. With --warnings-as-errors and --baseline, exit should be 0.
        before = _make_clean_config()
        before["feeds"][0]["minPublishers"] = 4  # W005
        after = _make_clean_config()
        after["feeds"][0]["minPublishers"] = 4  # same W005
        before_path = Path(tmp_path) / "before.json"
        before_path.write_text(json.dumps(before))
        after_path = _write_config(tmp_path, after)
        result = _run_linter(
            "--config",
            after_path,
            "--baseline",
            str(before_path),
            "--warnings-as-errors",
        )
        assert result.returncode == 0

    def test_config_with_non_dict_json_fails(self, tmp_path):
        # Top-level JSON list instead of object — should fail with clean error.
        path = Path(tmp_path) / "after.json"
        path.write_text(json.dumps([{"feedId": 1}]))
        result = _run_linter("--config", str(path), "--no-baseline")
        assert result.returncode == 1
        assert "must contain a JSON object" in result.stderr
        assert "list" in result.stderr

    def test_baseline_with_non_dict_json_fails(self, tmp_path):
        config_path = _write_config(tmp_path, _make_clean_config())
        baseline_path = Path(tmp_path) / "before.json"
        baseline_path.write_text(json.dumps([]))
        result = _run_linter("--config", config_path, "--baseline", str(baseline_path))
        assert result.returncode == 1
        assert "must contain a JSON object" in result.stderr
