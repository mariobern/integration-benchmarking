# Config Linter Baseline-Diff Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `config_linter.py` report only the findings introduced by changes in the current branch versus `origin/main`, with automatic baseline discovery so the user never manages a `before.json`. Add a CI workflow that runs the linter on every PR touching `after.json`.

**Architecture:** Two-pass post-filter. `lint_config_diff(after, before, now)` calls existing `lint_config()` twice and drops findings whose `(rule_id, feed_id, symbol)` tuple appears in the baseline. CLI gains `--baseline`, `--baseline-ref`, `--no-baseline` flags; default behavior auto-detects the baseline via `git merge-base HEAD origin/main` + `git show <merge-base>:<config-path>`. Falls back to full lint with a stderr note when auto-detect cannot succeed. Existing rule code is untouched.

**Tech Stack:** Python 3.11 stdlib (`subprocess`, `argparse`, `json`, `dataclasses`), pytest, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-04-28-config-linter-baseline-diff-design.md`

**Branch:** `feat/config-linter-baseline-diff`

---

## Task 1: Add `lint_config_diff` and `_finding_key` to `lib/config_lint.py`

**Files:**

- Modify: `lib/config_lint.py` — append new private helper `_finding_key` and new public function `lint_config_diff` at the end of the file (after `lint_config`).
- Test: `tests/test_config_lint.py` — append a new `TestLintConfigDiff` class at the end.

### - [ ] Step 1: Write the failing tests

Append to `tests/test_config_lint.py`:

```python
class TestLintConfigDiff:
    def test_suppresses_preexisting_finding(self):
        # Both before and after have feed 100 with E005 (STABLE, no publishers).
        feed = _make_feed(
            100,
            symbol="Equity.US.AAPL/USD",
            asset_type="equity",
            publisher_ids=[],
        )
        before = _make_config([feed])
        after = _make_config([dict(feed)])
        from lib.config_lint import lint_config_diff
        result = lint_config_diff(after, before)
        assert result == []

    def test_reports_newly_introduced_finding(self):
        clean = _make_feed(
            100,
            symbol="Equity.US.AAPL/USD",
            asset_type="equity",
            publisher_ids=[1, 2, 3],
        )
        broken = dict(clean)
        broken["allowedPublisherIds"] = []  # E005
        before = _make_config([clean])
        after = _make_config([broken])
        from lib.config_lint import lint_config_diff
        result = lint_config_diff(after, before)
        assert len(result) == 1
        assert result[0].rule_id == "E005"
        assert result[0].feed_id == 100

    def test_reports_finding_on_brand_new_feed(self):
        existing = _make_feed(
            100,
            symbol="Equity.US.AAPL/USD",
            asset_type="equity",
            publisher_ids=[1, 2, 3],
        )
        new_broken = _make_feed(
            999,
            symbol="Equity.US.NVDA/USD",
            asset_type="equity",
            publisher_ids=[],
        )
        before = _make_config([existing])
        after = _make_config([existing, new_broken])
        from lib.config_lint import lint_config_diff
        result = lint_config_diff(after, before)
        assert len(result) == 1
        assert result[0].rule_id == "E005"
        assert result[0].feed_id == 999

    def test_drops_findings_for_removed_feed(self):
        keep = _make_feed(
            100,
            symbol="Equity.US.AAPL/USD",
            asset_type="equity",
            publisher_ids=[1, 2, 3],
        )
        removed = _make_feed(
            200,
            symbol="Equity.US.MSFT/USD",
            asset_type="equity",
            publisher_ids=[],  # E005
        )
        before = _make_config([keep, removed])
        after = _make_config([keep])
        from lib.config_lint import lint_config_diff
        result = lint_config_diff(after, before)
        assert result == []

    def test_treats_symbol_rename_as_new(self):
        before_feed = _make_feed(
            100,
            symbol="Equity.US.OLD/USD",
            asset_type="equity",
            publisher_ids=[],  # E005
        )
        after_feed = _make_feed(
            100,
            symbol="Equity.US.NEW/USD",
            asset_type="equity",
            publisher_ids=[],  # E005
        )
        before = _make_config([before_feed])
        after = _make_config([after_feed])
        from lib.config_lint import lint_config_diff
        result = lint_config_diff(after, before)
        assert len(result) == 1
        assert result[0].symbol == "Equity.US.NEW/USD"

    def test_handles_group_rule_cascade(self):
        # Three STABLE equity feeds with identical schedule. Adding a 4th
        # with a deviating schedule should fire E011 only on the new feed.
        sched_us = [
            {
                "marketSchedule": "America/New_York;O,O,O,O,O,O,O;",
                "session": "REGULAR",
            }
        ]
        sched_other = [
            {
                "marketSchedule": "America/Chicago;O,O,O,O,O,O,O;",
                "session": "REGULAR",
            }
        ]
        existing = [
            _make_feed(
                fid,
                symbol=f"Equity.US.SYM{fid}/USD",
                asset_type="equity",
                publisher_ids=[1, 2, 3],
                schedules=sched_us,
            )
            for fid in (1, 2, 3)
        ]
        deviant = _make_feed(
            4,
            symbol="Equity.US.SYM4/USD",
            asset_type="equity",
            publisher_ids=[1, 2, 3],
            schedules=sched_other,
        )
        before = _make_config(existing)
        after = _make_config(existing + [deviant])
        from lib.config_lint import lint_config_diff
        result = lint_config_diff(after, before)
        e011 = [f for f in result if f.rule_id == "E011"]
        assert len(e011) == 1
        assert e011[0].feed_id == 4

    def test_uses_consistent_now_for_e013(self):
        # COMING_SOON futures feed with all validTo in the past.
        # Same feed in before and after — E013 fires identically.
        feed = {
            "feedId": 500,
            "symbol": "Commodities.GCH5/USD",
            "state": "COMING_SOON",
            "kind": "PRICE",
            "minPublishers": 0,
            "metadata": {"asset_type": "commodity"},
            "marketSchedules": [
                {
                    "marketSchedule": "America/New_York;O,O,O,O,O,O,O;",
                    "session": "REGULAR",
                    "benchmarkMapping": {
                        "datascope": {
                            "identifiers": [
                                {
                                    "identifier": "GCH5",
                                    "validFrom": "2024-01-01T00:00:00Z",
                                    "validTo": "2025-03-27T00:00:00Z",
                                }
                            ]
                        }
                    },
                }
            ],
        }
        before = _make_config([feed])
        after = _make_config([dict(feed)])
        from lib.config_lint import lint_config_diff
        # Now is well after the validTo so E013 fires in both runs.
        now = datetime(2026, 1, 1, tzinfo=timezone.utc)
        result = lint_config_diff(after, before, now=now)
        assert result == []

    def test_finding_key_is_rule_feed_symbol(self):
        from lib.config_lint import _finding_key
        a = LintFinding(
            rule_id="E001",
            severity="ERROR",
            message="msg-A",
            feed_id=10,
            symbol="X",
        )
        b = LintFinding(
            rule_id="E001",
            severity="ERROR",
            message="msg-B",
            feed_id=10,
            symbol="X",
        )
        assert _finding_key(a) == _finding_key(b)
        assert _finding_key(a) == ("E001", 10, "X")
```

### - [ ] Step 2: Run tests to verify they fail

Run:

```bash
cd /home/mariobern/integration-benchmarking
source venv/bin/activate
pytest tests/test_config_lint.py::TestLintConfigDiff -v
```

Expected: 8 failures with `ImportError: cannot import name 'lint_config_diff' from 'lib.config_lint'` (or similar) — the function does not exist yet.

### - [ ] Step 3: Implement `_finding_key` and `lint_config_diff`

Append to `lib/config_lint.py` (at the very end of the file):

```python
def _finding_key(f: LintFinding) -> tuple[str, Optional[int], Optional[str]]:
    """Identity tuple for diff comparison.

    Two findings are considered "the same" iff this tuple matches.
    Message text is intentionally excluded so magnitude changes within a
    rule (e.g. publisher count dropping further on E004) do not surface
    as new findings.
    """
    return (f.rule_id, f.feed_id, f.symbol)


def lint_config_diff(
    after_config: dict,
    before_config: dict,
    now: Optional[datetime] = None,
) -> list[LintFinding]:
    """Lint after_config and return only findings not present in before_config.

    A finding is "pre-existing" when its `_finding_key` tuple matches any
    finding produced by linting before_config under the same `now`.
    Pre-existing findings are dropped from the result.

    The same `now` is passed to both runs so that time-dependent rules
    (E013) are evaluated against a single instant.
    """
    now = now or datetime.now(timezone.utc)
    before_findings = lint_config(before_config, now=now)
    after_findings = lint_config(after_config, now=now)
    baseline_keys = {_finding_key(f) for f in before_findings}
    return [f for f in after_findings if _finding_key(f) not in baseline_keys]
```

### - [ ] Step 4: Run tests to verify they pass

Run:

```bash
pytest tests/test_config_lint.py::TestLintConfigDiff -v
```

Expected: 8 passed.

### - [ ] Step 5: Run full test suite to verify no regressions

Run:

```bash
pytest tests/test_config_lint.py -v
```

Expected: all tests pass (existing + 8 new).

### - [ ] Step 6: Run pre-commit on modified files

Run:

```bash
pre-commit run --files lib/config_lint.py tests/test_config_lint.py
```

Expected: all hooks pass.

### - [ ] Step 7: Commit

```bash
git add lib/config_lint.py tests/test_config_lint.py
git commit -m "feat: add lint_config_diff for baseline-aware linting

Returns only findings whose (rule_id, feed_id, symbol) tuple is absent
from the baseline lint output. Existing rule code is untouched. The
same 'now' is threaded into both runs so E013 (time-dependent) is
evaluated against a single instant."
```

---

## Task 2: Create `lib/baseline_lookup.py` with git auto-detect

**Files:**

- Create: `lib/baseline_lookup.py`
- Create: `tests/test_baseline_lookup.py`

### - [ ] Step 1: Write the failing tests

Create `tests/test_baseline_lookup.py`:

```python
import json
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from lib.baseline_lookup import lookup_baseline_config


def _ok(stdout=""):
    """Build a successful CompletedProcess with given stdout."""
    return subprocess.CompletedProcess(
        args=[], returncode=0, stdout=stdout, stderr=""
    )


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
```

### - [ ] Step 2: Run tests to verify they fail

Run:

```bash
pytest tests/test_baseline_lookup.py -v
```

Expected: all tests fail with `ModuleNotFoundError: No module named 'lib.baseline_lookup'`.

### - [ ] Step 3: Implement `lib/baseline_lookup.py`

Create `lib/baseline_lookup.py`:

```python
"""Git auto-detect helper for the config linter baseline.

Resolves the baseline config (e.g. before.json) by walking the local
git history. All git invocations go through subprocess so this module
remains testable with a mocked subprocess.run.

Returns a (config_dict, reason) pair: on success, (parsed_dict, None);
on failure, (None, reason_str). Callers print the reason to stderr and
fall back to full lint.
"""

from __future__ import annotations

import json
import subprocess
from typing import Optional


def _run_git(args: list[str]) -> Optional[str]:
    """Run a git command and return stdout on success, None on failure.

    A failure is any non-zero exit, missing binary, or unparseable output.
    The caller decides how to interpret a None return.
    """
    try:
        result = subprocess.run(
            ["git", *args],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def lookup_baseline_config(
    config_path: str,
    baseline_ref: str,
) -> tuple[Optional[dict], Optional[str]]:
    """Resolve baseline config by walking git history.

    Returns (config_dict, None) on success or (None, reason) on failure.
    The reason strings match those listed in the design spec.
    """
    # 1. Inside a git work tree?
    try:
        check = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return None, "git command not available"
    if check.returncode != 0 or check.stdout.strip() != "true":
        return None, "not a git repository"

    # 2. Baseline ref resolves?
    ref_sha = _run_git(["rev-parse", baseline_ref])
    if ref_sha is None:
        return None, f"ref '{baseline_ref}' not found"

    # 3. HEAD resolves and merge-base is not HEAD?
    head_sha = _run_git(["rev-parse", "HEAD"])
    if head_sha is None:
        return None, "ref 'HEAD' not found"

    merge_base = _run_git(["merge-base", "HEAD", baseline_ref])
    if merge_base is None:
        return None, "merge-base could not be computed"
    if merge_base == head_sha:
        return None, "on baseline ref, no diff to compute"

    # 4. Config path tracked at merge-base?
    raw = _run_git(["show", f"{merge_base}:{config_path}"])
    if raw is None:
        return None, f"path '{config_path}' not present at {merge_base}"

    # 5. Parse JSON.
    try:
        return json.loads(raw), None
    except json.JSONDecodeError as e:
        return None, f"baseline JSON invalid: {e}"
```

### - [ ] Step 4: Run tests to verify they pass

Run:

```bash
pytest tests/test_baseline_lookup.py -v
```

Expected: 8 passed.

### - [ ] Step 5: Run pre-commit

Run:

```bash
pre-commit run --files lib/baseline_lookup.py tests/test_baseline_lookup.py
```

Expected: all hooks pass.

### - [ ] Step 6: Commit

```bash
git add lib/baseline_lookup.py tests/test_baseline_lookup.py
git commit -m "feat: add baseline_lookup helper for git auto-detect

Resolves baseline config via 'git merge-base HEAD <ref>' followed by
'git show <merge-base>:<config-path>'. Returns (config, None) on
success or (None, reason) on any failure. All subprocess calls are
unit-testable via monkeypatch."
```

---

## Task 3: Wire up `config_linter.py` with new flags and routing

**Files:**

- Modify: `config_linter.py` — add flags, routing, updated text formatter.
- Modify: `tests/test_config_linter_cli.py` — append `TestCLIBaseline` class with file-based tests.

### - [ ] Step 1: Write the failing tests

Append to `tests/test_config_linter_cli.py`:

```python
class TestCLIBaseline:
    def test_explicit_baseline_path_diff_mode(self, tmp_path):
        # Pre-existing E001 (duplicate feedId) in both files; --baseline
        # should suppress it and exit 0.
        bad = _make_clean_config()
        bad["feeds"].append(bad["feeds"][0].copy())
        before_path = Path(tmp_path) / "before.json"
        before_path.write_text(json.dumps(bad))
        after_path = _write_config(tmp_path, bad)
        result = _run_linter(
            "--config", after_path, "--baseline", str(before_path)
        )
        assert result.returncode == 0
        assert "No new issues found" in result.stdout
        assert "pre-existing" in result.stdout

    def test_explicit_baseline_reports_only_new(self, tmp_path):
        clean = _make_clean_config()
        with_dup = _make_clean_config()
        with_dup["feeds"].append(with_dup["feeds"][0].copy())
        before_path = Path(tmp_path) / "before.json"
        before_path.write_text(json.dumps(clean))
        after_path = _write_config(tmp_path, with_dup)
        result = _run_linter(
            "--config", after_path, "--baseline", str(before_path)
        )
        assert result.returncode == 1
        assert "ERRORS (1 new)" in result.stdout
        assert "E001" in result.stdout

    def test_no_baseline_disables_diff(self, tmp_path):
        bad = _make_clean_config()
        bad["feeds"].append(bad["feeds"][0].copy())
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
        result = _run_linter(
            "--config", after_path, "--baseline", str(before_path)
        )
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
            "not found" in result.stderr.lower()
            or "not found" in result.stdout.lower()
        )

    def test_auto_detect_outside_git_falls_back(self, tmp_path):
        # tmp_path is not a git repo. Default mode should auto-detect,
        # find no git, print a NOTE to stderr, and run full lint.
        path = _write_config(tmp_path, _make_clean_config())
        result = _run_linter("--config", path)
        # Clean config -> exit 0 either way; verify the NOTE is printed.
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
```

Note: `_run_linter` invokes the linter from `PROJECT_DIR` which is a git repo. This means the auto-detect path will run when no baseline flag is given. The `test_auto_detect_outside_git_falls_back` test creates files in `tmp_path` (not a git repo), but the linter still runs with cwd=PROJECT_DIR. To make that test deterministic, override the working directory.

Replace `_run_linter` invocation in `test_auto_detect_outside_git_falls_back` with a direct subprocess call that sets `cwd=str(tmp_path)`:

```python
    def test_auto_detect_outside_git_falls_back(self, tmp_path):
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
```

### - [ ] Step 2: Run tests to verify they fail

Run:

```bash
pytest tests/test_config_linter_cli.py::TestCLIBaseline -v
```

Expected: all 8 tests fail (unrecognized `--baseline`/`--no-baseline` arguments and absent NOTE output).

### - [ ] Step 3: Modify `config_linter.py`

Replace the entire `_format_text` function (lines 30–77) with a version that takes a `pre_existing_count` parameter (None = full lint, int = diff mode). Replace the entire `main` function (lines 97–170) with one that adds the new flags and routing.

Open `config_linter.py` and:

(a) Update imports at the top:

```python
"""Config linter CLI for after.json validation.

Usage:
    python3 config_linter.py --config after.json
    python3 config_linter.py --config after.json --baseline before.json
    python3 config_linter.py --config after.json --baseline-ref develop
    python3 config_linter.py --config after.json --no-baseline
    python3 config_linter.py --config after.json --format json
    python3 config_linter.py --config after.json --output lint_results.json
    python3 config_linter.py --config after.json --warnings-as-errors
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from lib.baseline_lookup import lookup_baseline_config
from lib.config_lint import LintFinding, lint_config, lint_config_diff
```

(b) Replace `_format_text` (the existing lines 30–77) with:

```python
def _format_text(
    findings: list[LintFinding],
    use_color: bool,
    pre_existing_count: Optional[int] = None,
) -> str:
    """Format findings as human-readable text.

    pre_existing_count: None = full lint mode (today's labels). An int
    means diff mode: the labels read 'N new' instead of 'N found' and
    the summary line tacks on the suppressed count.
    """
    errors = [f for f in findings if f.severity == "ERROR"]
    warnings = [f for f in findings if f.severity == "WARNING"]
    lines: list[str] = []

    label = "new" if pre_existing_count is not None else "found"

    if errors:
        header = f"ERRORS ({len(errors)} {label}):"
        if use_color:
            header = f"{_RED}{_BOLD}{header}{_RESET}"
        lines.append(header)
        for f in errors:
            loc = ""
            if f.feed_id is not None:
                loc = f"Feed {f.feed_id}"
                if f.symbol:
                    loc += f" ({f.symbol})"
                loc += ": "
            line = f"  {f.rule_id}  {loc}{f.message}"
            if use_color:
                line = f"  {_RED}{f.rule_id}{_RESET}  {loc}{f.message}"
            lines.append(line)
        lines.append("")

    if warnings:
        header = f"WARNINGS ({len(warnings)} {label}):"
        if use_color:
            header = f"{_YELLOW}{_BOLD}{header}{_RESET}"
        lines.append(header)
        for f in warnings:
            loc = ""
            if f.feed_id is not None:
                loc = f"Feed {f.feed_id}"
                if f.symbol:
                    loc += f" ({f.symbol})"
                loc += ": "
            line = f"  {f.rule_id}  {loc}{f.message}"
            if use_color:
                line = f"  {_YELLOW}{f.rule_id}{_RESET}  {loc}{f.message}"
            lines.append(line)
        lines.append("")

    if not errors and not warnings:
        if pre_existing_count is not None and pre_existing_count > 0:
            lines.append(
                f"No new issues found. ({pre_existing_count} pre-existing"
                f" findings suppressed)"
            )
        else:
            lines.append("No issues found.")
    else:
        if pre_existing_count is not None:
            summary = (
                f"Summary: {len(errors)} new errors, {len(warnings)} new"
                f" warnings ({pre_existing_count} pre-existing findings"
                f" suppressed)"
            )
        else:
            summary = (
                f"Summary: {len(errors)} errors, {len(warnings)} warnings"
            )
        lines.append(summary)

    return "\n".join(lines)
```

(`from typing import Optional` is already added in step (a).)

(c) Replace the `main` function with:

```python
def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lint after.json config for common errors"
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to after.json config file",
    )
    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format (default: text)",
    )
    parser.add_argument(
        "--warnings-as-errors",
        action="store_true",
        help="Treat warnings as errors (exit 1)",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Write findings to file (format auto-detected: .json -> JSON, else text)",
    )
    parser.add_argument(
        "--baseline-ref",
        default="origin/main",
        help=(
            "Git ref used for baseline auto-detect (default: origin/main)."
            " Ignored when --baseline or --no-baseline is provided."
        ),
    )
    baseline_group = parser.add_mutually_exclusive_group()
    baseline_group.add_argument(
        "--baseline",
        type=Path,
        help=(
            "Path to baseline config (overrides git auto-detect). When"
            " provided, only findings absent from the baseline are reported."
        ),
    )
    baseline_group.add_argument(
        "--no-baseline",
        action="store_true",
        help="Force full lint and bypass baseline diff mode entirely.",
    )
    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"ERROR: Config file not found: {config_path}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(config_path) as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        print(f"ERROR: Invalid JSON in {config_path}: {e}", file=sys.stderr)
        sys.exit(1)

    # Resolve baseline.
    baseline_config: Optional[dict] = None
    if args.no_baseline:
        baseline_config = None
    elif args.baseline is not None:
        if not args.baseline.exists():
            print(
                f"ERROR: Baseline file not found: {args.baseline}",
                file=sys.stderr,
            )
            sys.exit(1)
        try:
            with open(args.baseline) as f:
                baseline_config = json.load(f)
        except json.JSONDecodeError as e:
            print(
                f"ERROR: Invalid JSON in baseline {args.baseline}: {e}",
                file=sys.stderr,
            )
            sys.exit(1)
    else:
        # Default mode: try git auto-detect.
        baseline_config, reason = lookup_baseline_config(
            config_path=str(config_path),
            baseline_ref=args.baseline_ref,
        )
        if baseline_config is None:
            print(
                f"NOTE: baseline unavailable ({reason}); running full lint",
                file=sys.stderr,
            )

    # Run lint (diff or full).
    if baseline_config is not None:
        # Thread the same `now` into both calls so E013 (time-dependent)
        # is evaluated against a single instant in both runs.
        now = datetime.now(timezone.utc)
        findings = lint_config_diff(config, baseline_config, now=now)
        pre_existing_count = len(lint_config(baseline_config, now=now))
    else:
        findings = lint_config(config)
        pre_existing_count = None

    errors = [f for f in findings if f.severity == "ERROR"]
    warnings = [f for f in findings if f.severity == "WARNING"]

    if args.output:
        if args.output.suffix.lower() == ".json":
            content = _format_json(findings)
        else:
            content = _format_text(
                findings, use_color=False, pre_existing_count=pre_existing_count
            )
        try:
            args.output.write_text(content)
        except OSError as e:
            print(f"ERROR: Cannot write to {args.output}: {e}", file=sys.stderr)
            sys.exit(1)

        if not errors and not warnings:
            if pre_existing_count is not None and pre_existing_count > 0:
                print(
                    f"No new issues found. Wrote results to {args.output}"
                    f" ({pre_existing_count} pre-existing findings suppressed)"
                )
            else:
                print(f"No issues found. Wrote results to {args.output}")
        else:
            label = "new " if pre_existing_count is not None else ""
            print(
                f"Wrote {len(errors)} {label}errors,"
                f" {len(warnings)} {label}warnings to {args.output}"
            )
    else:
        if args.format == "json":
            print(_format_json(findings))
        else:
            print(
                _format_text(
                    findings,
                    use_color=_supports_color(),
                    pre_existing_count=pre_existing_count,
                )
            )

    if errors:
        sys.exit(1)
    if args.warnings_as_errors and warnings:
        sys.exit(1)
    sys.exit(0)
```

### - [ ] Step 4: Run new and existing CLI tests

Run:

```bash
pytest tests/test_config_linter_cli.py -v
```

Expected: all tests pass — existing `TestCLIExitCodes`, `TestCLIOutputFormats`, `TestCLIFileHandling`, plus new `TestCLIBaseline`.

If any existing test fails because the default behavior now auto-detects from git: update only the affected test to pass `--no-baseline`, since those tests are explicitly verifying full-lint semantics. Do not change linter behavior to satisfy them.

### - [ ] Step 5: Run full test suite

Run:

```bash
pytest tests/ -v
```

Expected: all tests pass.

### - [ ] Step 6: Run pre-commit

Run:

```bash
pre-commit run --files config_linter.py tests/test_config_linter_cli.py
```

Expected: all hooks pass.

### - [ ] Step 7: Commit

```bash
git add config_linter.py tests/test_config_linter_cli.py
git commit -m "feat: make diff mode default in config_linter CLI

Adds --baseline, --baseline-ref, --no-baseline flags. Default behavior
auto-detects baseline via git merge-base with origin/main and falls
back to full lint with a stderr NOTE on any failure. Output reads 'N
new' instead of 'N found' in diff mode and the summary line shows the
pre-existing count."
```

---

## Task 4: End-to-end git-repo integration test

**Files:**

- Modify: `tests/test_config_linter_cli.py` — append `TestCLIGitAutoDetect` class.

### - [ ] Step 1: Write the failing test

Append to `tests/test_config_linter_cli.py`:

```python
import os


class TestCLIGitAutoDetect:
    def _init_repo_with_after(self, tmp_path, after_config, baseline_config):
        """Create a tmp git repo, commit baseline_config to a 'main' branch,
        then create a feature branch with after_config staged.
        Returns the repo path.
        """
        repo = Path(tmp_path) / "repo"
        repo.mkdir()
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        }

        def run(cmd):
            subprocess.run(cmd, cwd=repo, env=env, check=True, capture_output=True)

        run(["git", "init", "-b", "main"])
        (repo / "after.json").write_text(json.dumps(baseline_config))
        run(["git", "add", "after.json"])
        run(["git", "commit", "-m", "baseline"])
        # Simulate origin/main by creating a remote-tracking ref.
        run(["git", "update-ref", "refs/remotes/origin/main", "HEAD"])
        # Create feature branch.
        run(["git", "checkout", "-b", "feat/test"])
        (repo / "after.json").write_text(json.dumps(after_config))
        # Don't commit yet; the linter reads the working-tree file.
        return repo

    def test_auto_detect_suppresses_preexisting(self, tmp_path):
        bad = _make_clean_config()
        bad["feeds"].append(bad["feeds"][0].copy())  # pre-existing E001
        repo = self._init_repo_with_after(tmp_path, after_config=bad, baseline_config=bad)
        result = subprocess.run(
            [
                sys.executable,
                str(Path(PROJECT_DIR) / "config_linter.py"),
                "--config",
                "after.json",
            ],
            capture_output=True,
            text=True,
            cwd=str(repo),
        )
        assert result.returncode == 0
        assert "No new issues found" in result.stdout
        assert "pre-existing" in result.stdout

    def test_auto_detect_reports_new_finding(self, tmp_path):
        clean = _make_clean_config()
        with_dup = _make_clean_config()
        with_dup["feeds"].append(with_dup["feeds"][0].copy())
        repo = self._init_repo_with_after(
            tmp_path, after_config=with_dup, baseline_config=clean
        )
        result = subprocess.run(
            [
                sys.executable,
                str(Path(PROJECT_DIR) / "config_linter.py"),
                "--config",
                "after.json",
            ],
            capture_output=True,
            text=True,
            cwd=str(repo),
        )
        assert result.returncode == 1
        assert "ERRORS (1 new)" in result.stdout
        assert "E001" in result.stdout

    def test_auto_detect_on_main_falls_back(self, tmp_path):
        # No feature branch; HEAD is on main, so merge-base == HEAD.
        clean = _make_clean_config()
        repo = Path(tmp_path) / "repo"
        repo.mkdir()
        env = {
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "t@example.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "t@example.com",
        }

        def run(cmd):
            subprocess.run(cmd, cwd=repo, env=env, check=True, capture_output=True)

        run(["git", "init", "-b", "main"])
        (repo / "after.json").write_text(json.dumps(clean))
        run(["git", "add", "after.json"])
        run(["git", "commit", "-m", "baseline"])
        run(["git", "update-ref", "refs/remotes/origin/main", "HEAD"])
        result = subprocess.run(
            [
                sys.executable,
                str(Path(PROJECT_DIR) / "config_linter.py"),
                "--config",
                "after.json",
            ],
            capture_output=True,
            text=True,
            cwd=str(repo),
        )
        assert "on baseline ref" in result.stderr
        assert "running full lint" in result.stderr
```

### - [ ] Step 2: Run tests to verify they pass

Run:

```bash
pytest tests/test_config_linter_cli.py::TestCLIGitAutoDetect -v
```

Expected: 3 passed. (The implementation from Task 3 is already complete; these are integration tests that validate the wiring end-to-end.)

If they fail, the failure points to a real wiring issue in Task 3 — fix Task 3's implementation before continuing.

### - [ ] Step 3: Run full test suite

Run:

```bash
pytest tests/ -v
```

Expected: all tests pass.

### - [ ] Step 4: Run pre-commit

Run:

```bash
pre-commit run --files tests/test_config_linter_cli.py
```

Expected: all hooks pass.

### - [ ] Step 5: Commit

```bash
git add tests/test_config_linter_cli.py
git commit -m "test: end-to-end git auto-detect integration tests

Three scenarios covering the default-mode path: pre-existing finding
suppressed, new finding reported, and fallback to full lint when HEAD
is on the baseline ref. Each test materialises a real tmp git repo
with origin/main configured."
```

---

## Task 5: Add CI workflow

**Files:**

- Create: `.github/workflows/config-lint.yaml`

### - [ ] Step 1: Create the workflow file

Create `.github/workflows/config-lint.yaml`:

```yaml
name: Config Lint

on:
  pull_request:
    paths:
      - "after.json"

jobs:
  lint:
    name: Lint after.json against origin/main
    runs-on: ubuntu-latest
    steps:
      - name: Check out PR branch with full history
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Run config linter
        run: python3 config_linter.py --config after.json
```

### - [ ] Step 2: Validate YAML locally

Run:

```bash
python3 -c "import yaml; yaml.safe_load(open('.github/workflows/config-lint.yaml'))" \
  && echo "YAML valid"
```

Expected: `YAML valid`.

### - [ ] Step 3: Run pre-commit

Run:

```bash
pre-commit run --files .github/workflows/config-lint.yaml
```

Expected: all hooks pass (prettier formats YAML).

### - [ ] Step 4: Commit

```bash
git add .github/workflows/config-lint.yaml
git commit -m "ci: lint after.json on every PR that touches it

Runs config_linter.py with default behavior (auto-detect baseline via
git merge-base with origin/main). Triggers only on pull_request events
that change after.json. fetch-depth: 0 ensures merge-base is computable."
```

---

## Task 6: Update `docs/config_linter.md`

**Files:**

- Modify: `docs/config_linter.md`

### - [ ] Step 1: Update the Usage section

Open `docs/config_linter.md` and replace the existing `## Usage` section (lines 5–23) with:

````markdown
## Usage

```bash
# Default: diff mode against origin/main (auto-detected via git)
python3 config_linter.py --config after.json

# Diff against an explicit baseline file
python3 config_linter.py --config after.json --baseline before.json

# Diff against a different ref (e.g. develop)
python3 config_linter.py --config after.json --baseline-ref develop

# Force full lint (skip baseline)
python3 config_linter.py --config after.json --no-baseline

# JSON output
python3 config_linter.py --config after.json --format json

# Write results to file (format auto-detected from extension)
python3 config_linter.py --config after.json --output lint.json

# Treat warnings as errors (in diff mode applies to NEW warnings only)
python3 config_linter.py --config after.json --warnings-as-errors
```
````

### - [ ] Step 2: Update the Arguments section

Replace the existing `## Arguments` table (lines 25–32) with:

```markdown
## Arguments

| Argument               | Description                                                                                        | Required | Default       |
| ---------------------- | -------------------------------------------------------------------------------------------------- | -------- | ------------- |
| `--config`             | Path to `after.json` config file                                                                   | Yes      | —             |
| `--baseline`           | Path to baseline config file (overrides git auto-detect). Mutually exclusive with `--no-baseline`. | No       | (auto-detect) |
| `--baseline-ref`       | Git ref used for auto-detect. Ignored when `--baseline` or `--no-baseline` is provided.            | No       | `origin/main` |
| `--no-baseline`        | Force full lint, skipping baseline-diff mode entirely. Mutually exclusive with `--baseline`.       | No       | False         |
| `--format`             | Output format: `text` or `json`                                                                    | No       | `text`        |
| `--warnings-as-errors` | Exit 1 if any warning is present (in diff mode, applies to **new** warnings only)                  | No       | False         |
| `--output`             | Write findings to file (format auto-detected from extension)                                       | No       | —             |
```

### - [ ] Step 3: Add a new "Default behavior (diff mode)" section

Insert immediately before the existing `## Exit Codes` section:

````markdown
## Default Behavior (Diff Mode)

By default the linter compares the current working-tree config against the version that existed at the merge-base of the current branch and `origin/main`, and reports only findings introduced by changes on the current branch. Pre-existing findings are silently suppressed.

The baseline is discovered automatically via:

1. `git rev-parse --is-inside-work-tree`
2. `git rev-parse <baseline-ref>` (default: `origin/main`)
3. `git merge-base HEAD <baseline-ref>` (must be different from HEAD)
4. `git show <merge-base>:<config-path>`

If any step fails, the linter prints `NOTE: baseline unavailable (<reason>); running full lint` to stderr and falls back to the legacy full-lint behavior.

### Auto-detect failure modes

| Situation                                             | `<reason>`                                      |
| ----------------------------------------------------- | ----------------------------------------------- |
| Not inside a git work tree                            | `not a git repository`                          |
| Baseline ref does not exist locally                   | `ref 'origin/main' not found`                   |
| Current `HEAD` is on the baseline ref (no divergence) | `on baseline ref, no diff to compute`           |
| Config path was not tracked at the merge-base         | `path 'after.json' not present at <merge-base>` |
| `git` binary not on PATH                              | `git command not available`                     |
| Baseline JSON fails to parse                          | `baseline JSON invalid: <error>`                |

### Diff-mode output

```
ERRORS (1 new):
  E004  Feed 1163 (Equity.US.NVDA/USD): minPublishers (5) >= publisher count (5), no fault tolerance

WARNINGS (1 new):
  W003  Feed 999 (Commodities.GCH6/USD): REGULAR schedule deviates from (commodity, GC) majority

Summary: 1 new errors, 1 new warnings (12 pre-existing findings suppressed)
```

When zero new findings are reported:

```
No new issues found. (12 pre-existing findings suppressed)
```

JSON output is unchanged in shape — a flat array of finding objects, just filtered. Pre-existing-count metadata appears only in text output.

### Comparison key

A finding is considered pre-existing when its `(rule_id, feed_id, symbol)` tuple matches any finding produced by linting the baseline. Message text is intentionally excluded from the key, so magnitude changes within a rule (e.g. a publisher count dropping further on E004) do not surface as new findings. If you want to address those, run with `--no-baseline` periodically.
````

### - [ ] Step 4: Update the Exit Codes section

Replace the existing `## Exit Codes` block (lines 33–37) with:

```markdown
## Exit Codes

- `0` — no errors (warnings allowed unless `--warnings-as-errors`)
- `1` — at least one **ERROR** finding (or any finding when `--warnings-as-errors`)

In diff mode, exit code reflects only **new** findings. Pre-existing findings never affect exit code.
```

### - [ ] Step 5: Run pre-commit

Run:

```bash
pre-commit run --files docs/config_linter.md
```

Expected: prettier formats and all hooks pass.

### - [ ] Step 6: Commit

```bash
git add docs/config_linter.md
git commit -m "docs: document baseline-diff default and new flags

Adds Default Behavior section covering the git auto-detect path,
failure-mode reasons, diff-mode output formatting, and the
comparison-key semantics. Updates Arguments and Exit Codes sections
to reflect the new flags."
```

---

## Task 7: Final verification

**Files:**

- None (verification only).

### - [ ] Step 1: Run the full test suite

Run:

```bash
pytest tests/ -v
```

Expected: all tests pass.

### - [ ] Step 2: Spot-check the linter against the real `after.json`

Run:

```bash
python3 config_linter.py --config after.json --no-baseline
```

Expected: full lint output (today's behavior). Note the count of findings — call it `N_full`.

Run:

```bash
python3 config_linter.py --config after.json --baseline after.json
```

Expected: `No new issues found.` and `(N_full pre-existing findings suppressed)` because before == after means every finding is pre-existing.

### - [ ] Step 3: Verify pre-commit on all touched files

Run:

```bash
pre-commit run --files \
  lib/config_lint.py \
  lib/baseline_lookup.py \
  config_linter.py \
  tests/test_config_lint.py \
  tests/test_baseline_lookup.py \
  tests/test_config_linter_cli.py \
  .github/workflows/config-lint.yaml \
  docs/config_linter.md
```

Expected: all hooks pass.

### - [ ] Step 4: Review commit log

Run:

```bash
git log --oneline main..HEAD
```

Expected: 6 commits matching the task structure (plus the spec commit from before brainstorming):

```
<sha> docs: document baseline-diff default and new flags
<sha> ci: lint after.json on every PR that touches it
<sha> test: end-to-end git auto-detect integration tests
<sha> feat: make diff mode default in config_linter CLI
<sha> feat: add baseline_lookup helper for git auto-detect
<sha> feat: add lint_config_diff for baseline-aware linting
<sha> docs: add config linter baseline-diff design spec
```

### - [ ] Step 5: Push and open a PR

```bash
git push -u origin feat/config-linter-baseline-diff
gh pr create --title "feat: baseline-diff mode for config linter" --body "$(cat <<'EOF'
## Summary

- Adds `lint_config_diff()` to `lib/config_lint.py`: returns only findings whose `(rule_id, feed_id, symbol)` tuple is absent from a baseline lint
- Adds `lib/baseline_lookup.py` to resolve the baseline via `git merge-base HEAD origin/main` and `git show`
- Makes diff mode the default for `config_linter.py`; new flags `--baseline`, `--baseline-ref`, `--no-baseline` for explicit control
- Adds `.github/workflows/config-lint.yaml` to run the linter on every PR touching `after.json`

Spec: `docs/superpowers/specs/2026-04-28-config-linter-baseline-diff-design.md`
Plan: `docs/superpowers/plans/2026-04-28-config-linter-baseline-diff-plan.md`

## Test plan

- [x] `pytest tests/test_config_lint.py::TestLintConfigDiff -v` — diff function unit tests
- [x] `pytest tests/test_baseline_lookup.py -v` — git auto-detect unit tests with mocked subprocess
- [x] `pytest tests/test_config_linter_cli.py -v` — CLI tests including end-to-end git integration
- [x] `python3 config_linter.py --config after.json --no-baseline` — full lint still works
- [x] `python3 config_linter.py --config after.json --baseline after.json` — diff against self → 0 new
- [ ] After merge: open a draft PR touching `after.json` and confirm the new workflow runs
EOF
)"
```

Expected: PR created. Capture the URL.

---

## Self-Review

**Spec coverage check:**

| Spec section                                  | Plan task                                                          |
| --------------------------------------------- | ------------------------------------------------------------------ |
| `lint_config_diff` signature + comparison key | Task 1                                                             |
| Default behavior decision tree                | Task 3 (CLI routing)                                               |
| Auto-detect failure modes (6 reasons)         | Task 2 (unit tests cover each) + Task 4 (one integration scenario) |
| Behavior matrix (6 invocation patterns)       | Tasks 3 + 4 cover all six                                          |
| Output (diff mode) — text labels and summary  | Task 3 (`_format_text` rewrite)                                    |
| Exit codes (diff mode)                        | Task 3 (main routing)                                              |
| Edge cases                                    | Task 1 (8 unit tests cover all listed cases)                       |
| CI workflow                                   | Task 5                                                             |
| Determinism (consistent `now`)                | Task 1 (`test_uses_consistent_now_for_e013`)                       |
| Documentation                                 | Task 6                                                             |

All spec sections have a corresponding task.

**Placeholder scan:** No `TBD`, `TODO`, or "implement appropriately" patterns. All code blocks contain complete, runnable code.

**Type consistency:** `lint_config_diff(after_config: dict, before_config: dict, now: Optional[datetime] = None)` matches across spec and Task 1. `lookup_baseline_config(config_path: str, baseline_ref: str) -> tuple[Optional[dict], Optional[str]]` matches across Task 2 and Task 3. The `pre_existing_count: Optional[int]` parameter on `_format_text` is consistent across all callers in Task 3.
