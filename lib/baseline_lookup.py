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
