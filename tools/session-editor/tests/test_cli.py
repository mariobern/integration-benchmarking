"""End-to-end CLI tests via subprocess."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

TOOL_ROOT = Path(__file__).resolve().parent.parent
CLI = TOOL_ROOT / "session_editor.py"
FIXTURE = TOOL_ROOT / "tests" / "fixtures" / "sample_after.json"


def _run(args, cwd=None):
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=cwd or TOOL_ROOT,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(TOOL_ROOT), **_clean_env()},
    )


def _clean_env():
    import os

    env = dict(os.environ)
    return env


@pytest.fixture
def config_copy(tmp_path) -> Path:
    dst = tmp_path / "after.json"
    shutil.copy2(FIXTURE, dst)
    return dst


def test_help():
    r = _run(["-h"])
    assert r.returncode == 0
    assert "session" in r.stdout.lower()


def test_dry_run_does_not_modify(config_copy):
    before = config_copy.read_bytes()
    r = _run(
        [
            "--config",
            str(config_copy),
            "--remove-session",
            "OVER_NIGHT",
            "--feed-id",
            "922",
        ]
    )
    assert r.returncode == 0, r.stderr
    assert config_copy.read_bytes() == before


def test_apply_writes_backup_and_changes(config_copy):
    r = _run(
        [
            "--config",
            str(config_copy),
            "--remove-session",
            "OVER_NIGHT",
            "--feed-id",
            "922",
            "--apply",
        ]
    )
    assert r.returncode == 0, r.stderr
    backup = config_copy.with_suffix(".json.bak")
    assert backup.exists()

    data = json.loads(config_copy.read_text())
    aapl = next(f for f in data["feeds"] if f["feedId"] == 922)
    sessions = [s["session"] for s in aapl["marketSchedules"]]
    assert "OVER_NIGHT" not in sessions
    assert "REGULAR" in sessions


def test_apply_no_backup_flag(config_copy):
    r = _run(
        [
            "--config",
            str(config_copy),
            "--remove-session",
            "OVER_NIGHT",
            "--feed-id",
            "922",
            "--apply",
            "--no-backup",
        ]
    )
    assert r.returncode == 0
    assert not config_copy.with_suffix(".json.bak").exists()


def test_no_op_exits_zero(config_copy):
    # AAPL doesn't lack OVER_NIGHT -> add is a no-op.
    r = _run(
        [
            "--config",
            str(config_copy),
            "--add-session",
            "OVER_NIGHT",
            "--feed-id",
            "922",
        ]
    )
    assert r.returncode == 0
    assert "session already present" in r.stdout


def test_missing_op_returns_error(config_copy):
    r = _run(["--config", str(config_copy)])
    assert r.returncode == 2
    assert "must specify" in r.stderr


def test_verify_templates_ok(config_copy):
    r = _run(["--config", str(config_copy), "--verify-templates"])
    assert r.returncode == 0
    assert "OK" in r.stdout


def test_verify_templates_detects_drift(config_copy):
    data = json.loads(config_copy.read_text())
    aapl = next(f for f in data["feeds"] if f["feedId"] == 922)
    for s in aapl["marketSchedules"]:
        if s["session"] == "PRE_MARKET":
            s["marketSchedule"] = "America/New_York;0500-0930,...;"
    config_copy.write_text(json.dumps(data))

    r = _run(["--config", str(config_copy), "--verify-templates"])
    assert r.returncode == 1
    assert "DRIFT" in r.stdout
    assert "PRE_MARKET" in r.stdout


def test_feed_ids_from_txt_file(tmp_path, config_copy):
    """--feed-ids-from accepts a .txt with ranges, comments, and whitespace."""
    selector_file = tmp_path / "stable-missing-overnight.txt"
    selector_file.write_text(
        "# Demo file\n"
        "922      # AAPL (already has OVER_NIGHT)\n"
        "924      # ABNB (missing OVER_NIGHT)\n"
        "923-925  # range\n"
        "9999     # nonexistent\n",
        encoding="utf-8",
    )
    r = _run(
        [
            "--config",
            str(config_copy),
            "--add-session",
            "OVER_NIGHT",
            "--feed-ids-from",
            str(selector_file),
        ]
    )
    assert r.returncode == 0, r.stderr
    # ABNB should be added; AAPL skipped (already present); 923/925 absent
    # from fixture; 9999 not in config.
    assert "added=1" in r.stdout
    assert "already present" in r.stdout


def test_feed_ids_from_stdin(config_copy):
    r = subprocess.run(
        [
            sys.executable,
            str(CLI),
            "--config",
            str(config_copy),
            "--add-session",
            "OVER_NIGHT",
            "--feed-ids-from",
            "-",
        ],
        input="924\n# comment\n",
        cwd=TOOL_ROOT,
        capture_output=True,
        text=True,
        env={"PYTHONPATH": str(TOOL_ROOT), **_clean_env()},
    )
    assert r.returncode == 0, r.stderr
    assert "added=1" in r.stdout


def test_yaml_spec_round_trip(tmp_path, config_copy):
    spec = tmp_path / "spec.yaml"
    spec.write_text(
        """
version: 1
operations:
  - op: remove_session
    session: [PRE_MARKET, POST_MARKET]
    feed_id: 924
  - op: add_session
    session: OVER_NIGHT
    feed_id: 924
        """,
        encoding="utf-8",
    )
    r = _run(
        [
            "--config",
            str(config_copy),
            "--from-spec",
            str(spec),
            "--apply",
            "--no-backup",
        ]
    )
    assert r.returncode == 0, r.stderr

    data = json.loads(config_copy.read_text())
    abnb = next(f for f in data["feeds"] if f["feedId"] == 924)
    sessions = [s["session"] for s in abnb["marketSchedules"]]
    assert sessions == ["REGULAR", "OVER_NIGHT"]
