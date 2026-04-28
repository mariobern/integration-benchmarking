import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from lib.baseline_lookup import lookup_baseline_config


def _ok(stdout=""):
    """Build a successful CompletedProcess with given stdout."""
    return subprocess.CompletedProcess(args=[], returncode=0, stdout=stdout, stderr="")


def _fail(stderr="", returncode=1):
    """Build a failed CompletedProcess."""
    return subprocess.CompletedProcess(
        args=[], returncode=returncode, stdout="", stderr=stderr
    )


class TestLookupBaselineConfig:
    def test_returns_parsed_config_on_success(self, monkeypatch):
        sample = {"feeds": [], "publishers": []}

        def fake_run(cmd, **kwargs):
            if cmd[:2] == ["git", "rev-parse"] and "--is-inside-work-tree" in cmd:
                return _ok("true\n")
            if cmd[:2] == ["git", "rev-parse"] and cmd[-1] == "origin/main":
                return _ok("a" * 40 + "\n")
            if cmd[:2] == ["git", "rev-parse"] and cmd[-1] == "HEAD":
                return _ok("b" * 40 + "\n")
            if cmd[:2] == ["git", "merge-base"]:
                return _ok("c" * 40 + "\n")
            if cmd[:2] == ["git", "show"]:
                return _ok(json.dumps(sample))
            raise AssertionError(f"unexpected cmd: {cmd}")

        monkeypatch.setattr(subprocess, "run", fake_run)
        config, reason = lookup_baseline_config(
            config_path="after.json", baseline_ref="origin/main"
        )
        assert reason is None
        assert config == sample

    def test_not_a_git_repo(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            return _fail("fatal: not a git repository\n", returncode=128)

        monkeypatch.setattr(subprocess, "run", fake_run)
        config, reason = lookup_baseline_config(
            config_path="after.json", baseline_ref="origin/main"
        )
        assert config is None
        assert reason == "not a git repository"

    def test_baseline_ref_missing(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            if "--is-inside-work-tree" in cmd:
                return _ok("true\n")
            if cmd[:2] == ["git", "rev-parse"] and cmd[-1] == "origin/main":
                return _fail("fatal: ambiguous argument\n", returncode=128)
            raise AssertionError(f"unexpected cmd: {cmd}")

        monkeypatch.setattr(subprocess, "run", fake_run)
        config, reason = lookup_baseline_config(
            config_path="after.json", baseline_ref="origin/main"
        )
        assert config is None
        assert reason == "ref 'origin/main' not found"

    def test_on_baseline_ref_no_diff(self, monkeypatch):
        # merge-base equals HEAD => on the baseline ref or behind it.
        sha = "a" * 40

        def fake_run(cmd, **kwargs):
            if "--is-inside-work-tree" in cmd:
                return _ok("true\n")
            if cmd[:2] == ["git", "rev-parse"] and cmd[-1] == "origin/main":
                return _ok(sha + "\n")
            if cmd[:2] == ["git", "rev-parse"] and cmd[-1] == "HEAD":
                return _ok(sha + "\n")
            if cmd[:2] == ["git", "merge-base"]:
                return _ok(sha + "\n")
            raise AssertionError(f"unexpected cmd: {cmd}")

        monkeypatch.setattr(subprocess, "run", fake_run)
        config, reason = lookup_baseline_config(
            config_path="after.json", baseline_ref="origin/main"
        )
        assert config is None
        assert reason == "on baseline ref, no diff to compute"

    def test_config_path_not_present_at_merge_base(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            if "--is-inside-work-tree" in cmd:
                return _ok("true\n")
            if cmd[:2] == ["git", "rev-parse"] and cmd[-1] == "origin/main":
                return _ok("a" * 40 + "\n")
            if cmd[:2] == ["git", "rev-parse"] and cmd[-1] == "HEAD":
                return _ok("b" * 40 + "\n")
            if cmd[:2] == ["git", "merge-base"]:
                return _ok("c" * 40 + "\n")
            if cmd[:2] == ["git", "show"]:
                return _fail(
                    "fatal: path 'after.json' does not exist\n", returncode=128
                )
            raise AssertionError(f"unexpected cmd: {cmd}")

        monkeypatch.setattr(subprocess, "run", fake_run)
        config, reason = lookup_baseline_config(
            config_path="after.json", baseline_ref="origin/main"
        )
        assert config is None
        assert "not present" in reason
        assert "after.json" in reason

    def test_git_binary_missing(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            raise FileNotFoundError("git not found")

        monkeypatch.setattr(subprocess, "run", fake_run)
        config, reason = lookup_baseline_config(
            config_path="after.json", baseline_ref="origin/main"
        )
        assert config is None
        assert reason == "git command not available"

    def test_invalid_baseline_json(self, monkeypatch):
        def fake_run(cmd, **kwargs):
            if "--is-inside-work-tree" in cmd:
                return _ok("true\n")
            if cmd[:2] == ["git", "rev-parse"] and cmd[-1] == "origin/main":
                return _ok("a" * 40 + "\n")
            if cmd[:2] == ["git", "rev-parse"] and cmd[-1] == "HEAD":
                return _ok("b" * 40 + "\n")
            if cmd[:2] == ["git", "merge-base"]:
                return _ok("c" * 40 + "\n")
            if cmd[:2] == ["git", "show"]:
                return _ok("{invalid json")
            raise AssertionError(f"unexpected cmd: {cmd}")

        monkeypatch.setattr(subprocess, "run", fake_run)
        config, reason = lookup_baseline_config(
            config_path="after.json", baseline_ref="origin/main"
        )
        assert config is None
        assert reason.startswith("baseline JSON invalid:")

    def test_alternate_baseline_ref(self, monkeypatch):
        sample = {"feeds": [], "publishers": []}

        def fake_run(cmd, **kwargs):
            if "--is-inside-work-tree" in cmd:
                return _ok("true\n")
            if cmd[:2] == ["git", "rev-parse"] and cmd[-1] == "develop":
                return _ok("a" * 40 + "\n")
            if cmd[:2] == ["git", "rev-parse"] and cmd[-1] == "HEAD":
                return _ok("b" * 40 + "\n")
            if cmd[:2] == ["git", "merge-base"]:
                return _ok("c" * 40 + "\n")
            if cmd[:2] == ["git", "show"]:
                return _ok(json.dumps(sample))
            raise AssertionError(f"unexpected cmd: {cmd}")

        monkeypatch.setattr(subprocess, "run", fake_run)
        config, reason = lookup_baseline_config(
            config_path="after.json", baseline_ref="develop"
        )
        assert reason is None
        assert config == sample
