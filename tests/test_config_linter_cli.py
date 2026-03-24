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
